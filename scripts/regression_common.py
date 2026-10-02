from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OBSERVABILITY_SCHEMA_VERSION = 1
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 30.0
STATE_FLUSH_INTERVAL_SECONDS = 0.5


class ObservabilityError(RuntimeError):
    """Raised when an evidence run cannot be safely started or resumed."""


class RunAlreadyActiveError(ObservabilityError):
    """Raised when an owner or child process is still alive for an evidence run."""


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_identity: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"pid": self.pid, "start_identity": self.start_identity}


def _windows_process_start_identity(pid: int) -> str | None:
    """Return the Windows process creation FILETIME without requiring psutil."""

    class FileTime(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetProcessTimes.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
        ctypes.POINTER(FileTime),
    ]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid)
    if not handle:
        return None
    creation = FileTime()
    exit_time = FileTime()
    kernel_time = FileTime()
    user_time = FileTime()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return f"windows-filetime:{value}"
    finally:
        kernel32.CloseHandle(handle)


def process_start_identity(pid: int) -> str | None:
    """Return a PID-reuse-safe process start token on Windows and Linux."""

    try:
        if os.name == "nt":
            return _windows_process_start_identity(pid)
        if sys.platform.startswith("linux"):
            stat_path = Path(f"/proc/{pid}/stat")
            raw = stat_path.read_text(encoding="utf-8")
            closing = raw.rfind(")")
            if closing < 0:
                return None
            fields = raw[closing + 2 :].split()
            # The process start time is field 22; after the comm field this is
            # index 19. Include boot_id so a reboot cannot reuse the token.
            start_ticks = fields[19]
            boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            return f"linux:{boot_id}:{start_ticks}"
    except (OSError, ValueError, IndexError):
        return None
    return None


def current_process_identity() -> ProcessIdentity:
    pid = os.getpid()
    return ProcessIdentity(pid=pid, start_identity=process_start_identity(pid))


def process_identity_matches(identity: dict[str, Any] | ProcessIdentity | None) -> bool:
    if isinstance(identity, ProcessIdentity):
        expected_pid = identity.pid
        expected_start = identity.start_identity
    elif isinstance(identity, dict):
        expected_pid = identity.get("pid")
        expected_start = identity.get("start_identity")
    else:
        return False
    if not isinstance(expected_pid, int) or not expected_start:
        return False
    return process_start_identity(expected_pid) == expected_start


def _json_hash(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _safe_relative_files(root: Path) -> list[Path]:
    ignored_parts = {
        ".git",
        ".codex",
        ".venv",
        ".venv-m0",
        "artifacts",
        "output",
        "node_modules",
        ".playwright-browsers",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
    if not root.exists():
        return []
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and not ignored_parts.intersection(path.relative_to(root).parts) and path.name != ".env"
    ]


def source_fingerprint(root: Path) -> dict[str, Any]:
    """Capture source identity without exposing file contents or secrets."""

    root = root.resolve()
    commit = None
    dirty = False
    git_status = ""
    git_diff_hash = None
    try:
        commit_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if commit_result.returncode == 0:
            commit = commit_result.stdout.strip() or None
            status_result = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain=v1", "--untracked-files=all"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            git_status = status_result.stdout
            dirty = bool(git_status.strip())
            diff_result = subprocess.run(
                ["git", "-C", str(root), "diff", "--no-ext-diff", "--binary", "HEAD", "--"],
                check=False,
                capture_output=True,
            )
            git_diff_hash = hashlib.sha256(diff_result.stdout).hexdigest()
    except OSError:
        pass

    file_hasher = hashlib.sha256()
    file_count = 0
    for path in _safe_relative_files(root):
        try:
            relative = path.relative_to(root).as_posix()
            file_hasher.update(relative.encode("utf-8"))
            file_hasher.update(b"\0")
            file_hasher.update(path.read_bytes())
            file_hasher.update(b"\0")
            file_count += 1
        except OSError:
            continue
    fingerprint = _json_hash(
        {
            "commit": commit,
            "dirty": dirty,
            "git_status": git_status,
            "git_diff_hash": git_diff_hash,
            "file_hash": file_hasher.hexdigest(),
            "file_count": file_count,
        }
    )
    return {
        "root": str(root),
        "commit": commit,
        "dirty": dirty,
        "fingerprint": fingerprint,
    }


def _file_fingerprint(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def environment_fingerprint(*, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_environment = {
        key: os.environ.get(key)
        for key in (
            "PYTHONUTF8",
            "VIRTUAL_ENV",
            "UV_PROJECT_ENVIRONMENT",
            "PLAYWRIGHT_BROWSERS_PATH",
            "RECONCILIATION_SCHEDULER_ENABLED",
            "LONGBRIDGE_MARKET_DATA_PREWARM_ENABLED",
            "EXECUTION_MODE",
        )
        if os.environ.get(key) is not None
    }
    payload = {
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "environment": safe_environment,
        "extra": extra or {},
    }
    return {"fingerprint": _json_hash(payload), **payload}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_child_name(name: str) -> str:
    rendered = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip(".-")
    return rendered[:96] or "child"


class ObservedRun:
    """Small local evidence-run coordinator for sequential regression children."""

    def __init__(
        self,
        evidence_dir: Path,
        *,
        source_root: Path,
        run_id: str | None = None,
        heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
        environment_extra: dict[str, Any] | None = None,
    ) -> None:
        self.evidence_dir = Path(evidence_dir).resolve()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.children_dir = self.evidence_dir / "children"
        self.children_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.evidence_dir / "state.json"
        self.events_path = self.evidence_dir / "events.jsonl"
        self.lock_path = self.evidence_dir / "run.lock"
        self.source = source_fingerprint(source_root)
        lock_fingerprints = {
            relative: _file_fingerprint(Path(source_root) / relative)
            for relative in (".python-version", "uv.lock", "package-lock.json", "compose.yaml")
        }
        self.environment = environment_fingerprint(
            extra={"project_lock_files": lock_fingerprints, **(environment_extra or {})}
        )
        self.owner = current_process_identity()
        self.heartbeat_interval_seconds = max(0.01, float(heartbeat_interval_seconds))
        self._state_lock = threading.RLock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._lock_owned = False
        self._last_state_flush = 0.0
        self._progress_counter = 0
        self._progress_counter_at_heartbeat = 0
        self._active_process: subprocess.Popen[str] | None = None
        self._state = self._load_state() or {
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "run_id": run_id or f"run-{uuid.uuid4().hex}",
            "status": "created",
            "source": self.source,
            "environment": self.environment,
            "owner": self.owner.as_dict(),
            "parent_owner": self.owner.as_dict(),
            "children": {},
            "active_child": None,
            "last_progress": None,
            "last_progress_at": None,
            "last_heartbeat_at": None,
            "next_action": "acquire run owner",
        }
        if run_id and self._state.get("run_id") != run_id:
            raise ObservabilityError("Existing evidence run id does not match the requested run id.")
        self.run_id = str(self._state["run_id"])

    def _load_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ObservabilityError(f"Evidence state is unreadable: {self.state_path}") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != OBSERVABILITY_SCHEMA_VERSION:
            raise ObservabilityError(f"Evidence state schema is unsupported: {self.state_path}")
        return payload

    def _write_state_locked(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_state_flush < STATE_FLUSH_INTERVAL_SECONDS:
            return
        self._state["source"] = self.source
        self._state["environment"] = self.environment
        self._state["owner"] = self.owner.as_dict()
        self._state["parent_owner"] = self.owner.as_dict()
        _atomic_write_json(self.state_path, self._state)
        self._last_state_flush = now

    def _append_event(self, event: str, **payload: Any) -> None:
        record = {
            "schema_version": OBSERVABILITY_SCHEMA_VERSION,
            "event_id": f"event-{uuid.uuid4().hex}",
            "event": event,
            "run_id": self.run_id,
            "at": utc_now_iso(),
            **payload,
        }
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _owner_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "pid": self.owner.pid,
            "start_identity": self.owner.start_identity,
            "host": platform.node(),
            "claimed_at": utc_now_iso(),
        }

    def _read_lock(self) -> dict[str, Any] | None:
        if not self.lock_path.exists():
            return None
        try:
            value = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _process_record_alive(record: dict[str, Any] | None) -> bool:
        return process_identity_matches(record)

    def _active_child_alive(self) -> bool:
        child = self._state.get("active_child")
        return self._process_record_alive(child) if isinstance(child, dict) else False

    def _mark_previous_run_interrupted(self, previous_owner: dict[str, Any] | None) -> None:
        if self._active_child_alive():
            child = self._state.get("active_child") or {}
            raise RunAlreadyActiveError(
                f"Evidence run {self.run_id} has a live child PID {child.get('pid')}; refusing a duplicate."
            )
        interrupted_children: list[str] = []
        for child_name, child in (self._state.get("children") or {}).items():
            if not isinstance(child, dict) or child.get("status") != "running":
                continue
            if self._process_record_alive(child):
                raise RunAlreadyActiveError(
                    f"Evidence run {self.run_id} has a live child PID {child.get('pid')}; refusing a duplicate."
                )
            child["status"] = "interrupted"
            child["interrupted_at"] = utc_now_iso()
            child["next_action"] = "resume interrupted child"
            interrupted_children.append(str(child_name))
        active_child = self._state.get("active_child")
        if isinstance(active_child, dict) and active_child.get("status") == "running":
            active_name = str(active_child.get("name") or "active-child")
            active_child["status"] = "interrupted"
            active_child["interrupted_at"] = utc_now_iso()
            active_child["next_action"] = "resume interrupted child"
            self._state.setdefault("children", {})[active_name] = active_child
            if active_name not in interrupted_children:
                interrupted_children.append(active_name)
        self._state["active_child"] = None
        self._state["status"] = "interrupted"
        self._state["last_progress"] = {"kind": "owner_lost"}
        self._state["next_action"] = "resume after previous owner loss"
        with self._state_lock:
            self._write_state_locked(force=True)
        self._append_event("owner_lost", previous_owner=previous_owner)
        for child_name in interrupted_children:
            self._append_event("child_interrupted", child=child_name, reason="owner_lost_or_process_exit")

    def acquire(self) -> None:
        if not self.owner.start_identity:
            raise ObservabilityError("Could not capture the current process start identity; refusing an unsafe run lock.")
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        if not self.lock_path.exists() and self._state.get("status") == "running":
            previous_owner = self._state.get("owner")
            if self._process_record_alive(previous_owner):
                raise RunAlreadyActiveError(
                    f"Evidence run {self.run_id} is already owned by PID {previous_owner.get('pid')}."
                )
            self._mark_previous_run_interrupted(previous_owner)
        while True:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError:
                existing = self._read_lock()
                if self._process_record_alive(existing):
                    raise RunAlreadyActiveError(
                        f"Evidence run {self.run_id} is already owned by PID {existing.get('pid')}."
                    )
                if self._active_child_alive():
                    child = self._state.get("active_child") or {}
                    raise RunAlreadyActiveError(
                        f"Evidence run {self.run_id} has a live child PID {child.get('pid')}; refusing a duplicate."
                    )
                previous_owner = self._state.get("owner")
                if self._process_record_alive(previous_owner):
                    raise RunAlreadyActiveError(
                        f"Evidence run {self.run_id} is already owned by PID {previous_owner.get('pid')}."
                    )
                stale_path = self.lock_path.with_name(
                    f"{self.lock_path.name}.stale.{os.getpid()}.{uuid.uuid4().hex}"
                )
                try:
                    os.replace(self.lock_path, stale_path)
                except FileNotFoundError:
                    continue
                self._mark_previous_run_interrupted(existing or previous_owner)
                continue
            except OSError as error:
                raise ObservabilityError(f"Could not acquire evidence lock {self.lock_path}: {error}") from error
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self._owner_record(), handle, ensure_ascii=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self._lock_owned = True
            return

    def start(self) -> None:
        self.acquire()
        with self._state_lock:
            self._state["status"] = "running"
            self._state["run_started_at"] = utc_now_iso()
            self._state["next_action"] = "run next child"
            self._write_state_locked(force=True)
        self._append_event("run_started", owner=self._owner_record())
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"observability-heartbeat-{self.run_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.wait(self.heartbeat_interval_seconds):
            with self._state_lock:
                progress_changed = self._progress_counter != self._progress_counter_at_heartbeat
                self._progress_counter_at_heartbeat = self._progress_counter
                active = self._active_process is not None and self._active_process.poll() is None
                self._state["last_heartbeat_at"] = utc_now_iso()
                self._state["heartbeat"] = {
                    "alive": active,
                    "progress_since_last_heartbeat": progress_changed,
                    "last_progress_at": self._state.get("last_progress_at"),
                }
                self._state["next_action"] = "wait for child progress" if active else "run next child"
                self._write_state_locked(force=True)
            self._append_event(
                "heartbeat",
                alive=active,
                progress_since_last_heartbeat=progress_changed,
                last_progress_at=self._state.get("last_progress_at"),
            )

    def _command_fingerprint(self, command: list[str], *, cwd: Path) -> str:
        return _json_hash({"command": command, "cwd": str(cwd.resolve()), "environment": self.environment["fingerprint"]})

    def _child_log_paths(self, name: str, attempt: int) -> tuple[Path, Path]:
        safe_name = _safe_child_name(name)
        return (
            self.children_dir / f"{safe_name}.attempt-{attempt}.stdout.log",
            self.children_dir / f"{safe_name}.attempt-{attempt}.stderr.log",
        )

    def _reusable_child(self, name: str, command: list[str], *, cwd: Path) -> dict[str, Any] | None:
        previous = self._state.get("children", {}).get(name)
        if not isinstance(previous, dict) or previous.get("status") != "passed":
            return None
        if previous.get("command_fingerprint") != self._command_fingerprint(command, cwd=cwd):
            self._append_event("child_invalidated", child=name, reason="command_or_environment_changed")
            return None
        if previous.get("source_fingerprint") != self.source["fingerprint"]:
            self._append_event("child_invalidated", child=name, reason="source_changed")
            return None
        if not all(Path(previous.get(key, "")).exists() for key in ("stdout_log", "stderr_log")):
            self._append_event("child_invalidated", child=name, reason="child_log_missing")
            return None
        reused = {**previous, "reused": True}
        self._state["last_progress"] = {"kind": "child_reused", "child": name}
        self._state["last_progress_at"] = utc_now_iso()
        with self._state_lock:
            self._write_state_locked(force=True)
        self._append_event("child_reused", child=name, command_fingerprint=previous.get("command_fingerprint"))
        return reused

    def run_child(
        self,
        spec: dict[str, Any],
        *,
        timeout_seconds: float | None = None,
        echo_output: bool = False,
    ) -> dict[str, Any]:
        name = str(spec["name"])
        command = [str(value) for value in spec["command"]]
        cwd = Path(spec.get("cwd") or Path.cwd()).resolve()
        reusable = self._reusable_child(name, command, cwd=cwd)
        if reusable is not None:
            return reusable

        previous = self._state.get("children", {}).get(name)
        attempt = int(previous.get("attempt", 0)) + 1 if isinstance(previous, dict) else 1
        stdout_log, stderr_log = self._child_log_paths(name, attempt)
        command_fingerprint = self._command_fingerprint(command, cwd=cwd)
        started_at = utc_now_iso()
        self._append_event("child_started", child=name, attempt=attempt, command_fingerprint=command_fingerprint)
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        identity = ProcessIdentity(process.pid, process_start_identity(process.pid))
        if not identity.start_identity:
            process.terminate()
            process.wait(timeout=5)
            raise ObservabilityError(f"Could not capture process start identity for child '{name}'.")
        child_state = {
            "name": name,
            "attempt": attempt,
            "status": "running",
            "command": command,
            "command_fingerprint": command_fingerprint,
            "source_fingerprint": self.source["fingerprint"],
            "environment_fingerprint": self.environment["fingerprint"],
            "pid": identity.pid,
            "start_identity": identity.start_identity,
            "parent_owner": self.owner.as_dict(),
            "started_at": started_at,
            "stdout_log": str(stdout_log),
            "stderr_log": str(stderr_log),
            "last_progress": None,
            "last_progress_at": None,
            "next_action": "wait for child completion",
        }
        with self._state_lock:
            self._state.setdefault("children", {})[name] = child_state
            self._state["active_child"] = child_state
            self._state["next_action"] = f"wait for child {name}"
            self._state["last_progress"] = {"kind": "child_started", "child": name}
            self._state["last_progress_at"] = started_at
            self._write_state_locked(force=True)
        self._active_process = process
        output_threads: list[threading.Thread] = []

        def consume(stream: Any, path: Path, stream_name: str) -> None:
            line_count = 0
            byte_count = 0
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for line in stream:
                    handle.write(line)
                    handle.flush()
                    line_count += 1
                    byte_count += len(line.encode("utf-8", errors="replace"))
                    with self._state_lock:
                        self._progress_counter += 1
                        progress = {
                            "kind": "child_output",
                            "child": name,
                            "stream": stream_name,
                            "line_count": line_count,
                            "bytes": byte_count,
                        }
                        child_state["last_progress"] = progress
                        child_state["last_progress_at"] = utc_now_iso()
                        self._state["last_progress"] = progress
                        self._state["last_progress_at"] = child_state["last_progress_at"]
                        self._write_state_locked()
                    if echo_output:
                        print(f"[{name}/{stream_name}] {line.rstrip()}", file=sys.stderr, flush=True)

        assert process.stdout is not None
        assert process.stderr is not None
        for stream, path, stream_name in (
            (process.stdout, stdout_log, "stdout"),
            (process.stderr, stderr_log, "stderr"),
        ):
            thread = threading.Thread(
                target=consume,
                args=(stream, path, stream_name),
                name=f"observability-{_safe_child_name(name)}-{stream_name}",
                daemon=True,
            )
            thread.start()
            output_threads.append(thread)

        timed_out = False
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                returncode = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=5)
        finally:
            for thread in output_threads:
                thread.join(timeout=5)
            self._active_process = None

        status = "passed" if returncode == 0 and not timed_out else "failed"
        completed_at = utc_now_iso()
        final_state = {
            **child_state,
            "status": status,
            "returncode": returncode,
            "timed_out": timed_out,
            "completed_at": completed_at,
            "next_action": "run next child" if status == "passed" else "inspect child logs and resume",
            "reused": False,
        }
        with self._state_lock:
            self._state["children"][name] = final_state
            self._state["active_child"] = None
            self._state["next_action"] = final_state["next_action"]
            self._state["last_progress"] = {"kind": "child_completed", "child": name, "status": status}
            self._state["last_progress_at"] = completed_at
            self._write_state_locked(force=True)
        self._append_event(
            "child_completed",
            child=name,
            attempt=attempt,
            status=status,
            returncode=returncode,
            timed_out=timed_out,
            stdout_log=str(stdout_log),
            stderr_log=str(stderr_log),
        )
        return final_state

    def finish(self, status: str, *, next_action: str | None = None, error: str | None = None) -> None:
        if self._heartbeat_thread is not None:
            self._heartbeat_stop.set()
            self._heartbeat_thread.join(timeout=max(1.0, self.heartbeat_interval_seconds + 1))
            self._heartbeat_thread = None
        with self._state_lock:
            self._state["status"] = status
            self._state["completed_at"] = utc_now_iso()
            self._state["next_action"] = next_action or ("inspect failed child logs" if status != "passed" else "none")
            if error:
                self._state["error"] = error
            self._write_state_locked(force=True)
        self._append_event("run_finished", status=status, next_action=self._state["next_action"], error=error)
        self.release()

    def release(self) -> None:
        if not self._lock_owned:
            return
        current = self._read_lock()
        if current and current.get("run_id") == self.run_id and current.get("pid") == self.owner.pid and current.get("start_identity") == self.owner.start_identity:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
        self._lock_owned = False

    def payload(self) -> dict[str, Any]:
        with self._state_lock:
            return {
                "schema_version": OBSERVABILITY_SCHEMA_VERSION,
                "run_id": self.run_id,
                "state_path": str(self.state_path),
                "events_path": str(self.events_path),
                "children_dir": str(self.children_dir),
                "source": self.source,
                "environment": {"fingerprint": self.environment["fingerprint"]},
                "owner": self.owner.as_dict(),
                "children": self._state.get("children", {}),
                "status": self._state.get("status"),
                "last_progress": self._state.get("last_progress"),
                "last_progress_at": self._state.get("last_progress_at"),
                "next_action": self._state.get("next_action"),
            }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_tail(path: str | Path, limit: int = 1200) -> str:
    """Read a bounded tail from a streamed child log for the legacy report shape."""

    try:
        with Path(path).open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - limit), os.SEEK_SET)
            value = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return value[-limit:]


def build_report(
    *,
    script: str,
    workflow: str,
    status: str,
    mode: str,
    summary: str,
    target: str,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    report = {
        "script": script,
        "workflow": workflow,
        "status": status,
        "mode": mode,
        "target": target,
        "summary": summary,
        "generated_at": utc_now_iso(),
        "payload": payload or {},
    }
    if error is not None:
        report["error"] = error
    return report


def emit_report(report: dict[str, Any], json_output: str | None = None) -> None:
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if json_output:
        output_path = Path(json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

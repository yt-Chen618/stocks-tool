from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
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


def _windows_process_start_identity(pid: int, *, include_exited: bool = False) -> str | None:
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
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
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
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return None
        if not include_exited and exit_code.value != 259:
            return None
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return None
        if not include_exited and (exit_time.dwHighDateTime or exit_time.dwLowDateTime):
            return None
        value = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        return f"windows-filetime:{value}"
    finally:
        kernel32.CloseHandle(handle)


def process_start_identity(pid: int, *, include_exited: bool = False) -> str | None:
    """Return a live process token, or capture an owned, not-yet-reaped child.

    A fast child can exit before its parent reads the creation token. Only the
    initial Popen capture includes exited processes; all recovery/liveness
    checks still reject exited processes and Linux zombies.
    """

    try:
        if os.name == "nt":
            return _windows_process_start_identity(pid, include_exited=include_exited)
        if sys.platform.startswith("linux"):
            stat_path = Path(f"/proc/{pid}/stat")
            raw = stat_path.read_text(encoding="utf-8")
            closing = raw.rfind(")")
            if closing < 0:
                return None
            fields = raw[closing + 2 :].split()
            if not fields or (not include_exited and fields[0] in {"Z", "X", "x"}):
                return None
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


_IGNORED_SOURCE_PARTS = {
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


def _safe_relative_files(root: Path) -> list[Path]:
    """List source files without walking ignored evidence, cache, or venv trees."""

    root = root.resolve()
    if not root.exists():
        return []
    git_files = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=False,
        capture_output=True,
    )
    if git_files.returncode == 0:
        candidates = [Path(item) for item in git_files.stdout.decode("utf-8", errors="replace").split("\0") if item]
        return [
            path
            for relative in candidates
            if not _IGNORED_SOURCE_PARTS.intersection(relative.parts)
            and relative.name != ".env"
            and (path := root / relative).is_file()
        ]

    files: list[Path] = []
    for current_root, directories, names in os.walk(root, followlinks=False):
        directories[:] = [directory for directory in directories if directory not in _IGNORED_SOURCE_PARTS]
        current = Path(current_root)
        files.extend(
            path
            for name in names
            if name != ".env" and (path := current / name).is_file()
        )
    return sorted(files)


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


def _installed_python_fingerprint() -> str:
    distributions: list[tuple[str, str]] = []
    for distribution in importlib_metadata.distributions():
        name = distribution.metadata.get("Name") or distribution.name or ""
        distributions.append((str(name).lower(), str(distribution.version)))
    return _json_hash(sorted(distributions))


def _node_version_fingerprint() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        completed = subprocess.run(
            [node, "--version"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return _json_hash({"executable": node, "version": completed.stdout.strip()})


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
        "python_runtime_fingerprint": _json_hash({"version": sys.version, "executable": sys.executable}),
        "python_distributions_fingerprint": _installed_python_fingerprint(),
        "node_version_fingerprint": _node_version_fingerprint(),
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
        self._lock_handle: Any | None = None
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

    def _write_lock_owner(self) -> None:
        if self._lock_handle is None:
            raise ObservabilityError("Run lock is not held.")
        rendered = json.dumps(self._owner_record(), ensure_ascii=True).encode("utf-8") + b"\n"
        self._lock_handle.seek(0)
        self._lock_handle.truncate()
        self._lock_handle.write(rendered)
        self._lock_handle.flush()
        os.fsync(self._lock_handle.fileno())

    def _acquire_os_lock(self, handle: Any) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RunAlreadyActiveError(f"Evidence run lock is held: {self.lock_path}") from error
            return
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, OSError) as error:
            raise RunAlreadyActiveError(f"Evidence run lock is held: {self.lock_path}") from error

    def _release_os_lock(self, handle: Any) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            return
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass

    @staticmethod
    def _process_record_alive(record: dict[str, Any] | None) -> bool:
        return process_identity_matches(record)

    def _active_child_alive(self) -> bool:
        child = self._state.get("active_child")
        return self._process_record_alive(child) if isinstance(child, dict) else False

    def _mark_previous_run_interrupted(self, previous_owner: dict[str, Any] | None) -> None:
        launching_children = [
            str(child_name)
            for child_name, child in (self._state.get("children") or {}).items()
            if isinstance(child, dict)
            and (
                child.get("status") == "launching"
                or (child.get("status") == "running" and not child.get("pid"))
            )
        ]
        active_child = self._state.get("active_child")
        if (
            isinstance(active_child, dict)
            and (
                active_child.get("status") == "launching"
                or (active_child.get("status") == "running" and not active_child.get("pid"))
            )
        ):
            active_name = str(active_child.get("name") or "active-child")
            if active_name not in launching_children:
                launching_children.append(active_name)
        if launching_children:
            self._state["status"] = "needs_review"
            self._state["next_action"] = "inspect launching child before resuming"
            with self._state_lock:
                self._write_state_locked(force=True)
            self._append_event(
                "resume_blocked",
                reason="child_launch_identity_missing",
                children=launching_children,
            )
            raise ObservabilityError(
                f"Evidence run {self.run_id} has a child in the spawn window without a persisted PID; inspect it before resuming."
            )
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
        handle = self.lock_path.open("a+b")
        try:
            self._acquire_os_lock(handle)
        except RunAlreadyActiveError as error:
            existing = self._read_lock()
            handle.close()
            if self._process_record_alive(existing):
                raise RunAlreadyActiveError(
                    f"Evidence run {self.run_id} is already owned by PID {existing.get('pid')}."
                ) from error
            raise RunAlreadyActiveError(
                f"Evidence run lock is held and owner metadata is unavailable: {self.lock_path}"
            ) from error

        self._lock_handle = handle
        try:
            latest_state = self._load_state()
            if latest_state is not None:
                self._state = latest_state
                if self._state.get("run_id") != self.run_id:
                    raise ObservabilityError("Evidence state run id changed while acquiring its lock.")
            missing_identity_children = [
                str(child_name)
                for child_name, child in (self._state.get("children") or {}).items()
                if isinstance(child, dict)
                and (
                    child.get("status") == "launching"
                    or (child.get("status") == "running" and (not child.get("pid") or not child.get("start_identity")))
                )
            ]
            if missing_identity_children:
                self._state["status"] = "needs_review"
                self._state["next_action"] = "inspect launching child before resuming"
                with self._state_lock:
                    self._write_state_locked(force=True)
                self._append_event(
                    "resume_blocked",
                    reason="child_identity_missing",
                    children=missing_identity_children,
                )
                raise ObservabilityError(
                    f"Evidence run {self.run_id} has child launch state without a persisted process identity; inspect it before resuming."
                )
            active_child = self._state.get("active_child")
            if isinstance(active_child, dict) and active_child.get("status") in {"launching", "running"}:
                if active_child.get("status") == "launching" or not active_child.get("pid") or not active_child.get("start_identity"):
                    self._state["status"] = "needs_review"
                    self._state["next_action"] = "inspect launching child before resuming"
                    with self._state_lock:
                        self._write_state_locked(force=True)
                    self._append_event("resume_blocked", reason="child_identity_missing")
                    raise ObservabilityError(
                        f"Evidence run {self.run_id} has a child in the spawn window without a persisted process identity; inspect it before resuming."
                    )
                if self._process_record_alive(active_child):
                    raise RunAlreadyActiveError(
                        f"Evidence run {self.run_id} has a live child PID {active_child.get('pid')}; refusing a duplicate."
                    )
                if self._state.get("status") != "running":
                    child_name = str(active_child.get("name") or "active-child")
                    active_child["status"] = "interrupted"
                    active_child["interrupted_at"] = utc_now_iso()
                    active_child["next_action"] = "resume interrupted child"
                    self._state.setdefault("children", {})[child_name] = active_child
                    self._state["active_child"] = None
                    self._state["next_action"] = "resume interrupted child"
                    with self._state_lock:
                        self._write_state_locked(force=True)
                    self._append_event("child_interrupted", child=child_name, reason="process_exit")
            if self._state.get("status") == "running":
                previous_owner = self._state.get("owner")
                if self._process_record_alive(previous_owner):
                    raise RunAlreadyActiveError(
                        f"Evidence run {self.run_id} is already owned by PID {previous_owner.get('pid')}."
                    )
                self._mark_previous_run_interrupted(previous_owner)
            self._write_lock_owner()
        except Exception:
            self.release()
            raise
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

    def _reusable_child(
        self,
        name: str,
        command: list[str],
        *,
        cwd: Path,
        cacheable: bool,
    ) -> dict[str, Any] | None:
        if not cacheable:
            self._append_event("child_not_reusable", child=name, reason="cacheable_not_declared")
            return None
        previous = self._state.get("children", {}).get(name)
        if not isinstance(previous, dict) or previous.get("status") != "passed":
            return None
        if previous.get("cacheable") is not True:
            self._append_event("child_invalidated", child=name, reason="previous_run_not_cacheable")
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
        cacheable: bool = False,
    ) -> dict[str, Any]:
        name = str(spec["name"])
        command = [str(value) for value in spec["command"]]
        cwd = Path(spec.get("cwd") or Path.cwd()).resolve()
        cacheable = bool(spec.get("cacheable", cacheable))
        reusable = self._reusable_child(name, command, cwd=cwd, cacheable=cacheable)
        if reusable is not None:
            return reusable

        previous = self._state.get("children", {}).get(name)
        attempt = int(previous.get("attempt", 0)) + 1 if isinstance(previous, dict) else 1
        stdout_log, stderr_log = self._child_log_paths(name, attempt)
        command_fingerprint = self._command_fingerprint(command, cwd=cwd)
        started_at = utc_now_iso()
        child_state = {
            "name": name,
            "attempt": attempt,
            "status": "launching",
            "command": command,
            "command_fingerprint": command_fingerprint,
            "source_fingerprint": self.source["fingerprint"],
            "environment_fingerprint": self.environment["fingerprint"],
            "cacheable": cacheable,
            "pid": None,
            "start_identity": None,
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
            self._state["next_action"] = f"spawn child {name}"
            self._state["last_progress"] = {"kind": "child_launching", "child": name}
            self._state["last_progress_at"] = started_at
            self._write_state_locked(force=True)
        self._append_event("child_launching", child=name, attempt=attempt, command_fingerprint=command_fingerprint)
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                **_process_launch_kwargs(),
            )
        except BaseException as error:
            completed_at = utc_now_iso()
            child_state.update(
                {
                    "status": "failed",
                    "completed_at": completed_at,
                    "error": f"{type(error).__name__}: {error}",
                    "next_action": "inspect child launch error",
                }
            )
            with self._state_lock:
                self._state["active_child"] = None
                self._state["next_action"] = child_state["next_action"]
                self._write_state_locked(force=True)
            self._append_event("child_completed", child=name, status="failed", error=child_state["error"])
            raise
        identity = ProcessIdentity(process.pid, process_start_identity(process.pid, include_exited=True))
        if not identity.start_identity:
            process.terminate()
            process.wait(timeout=5)
            child_state.update(
                {
                    "status": "failed",
                    "completed_at": utc_now_iso(),
                    "next_action": "inspect missing child process identity",
                }
            )
            with self._state_lock:
                self._state["active_child"] = None
                self._state["next_action"] = child_state["next_action"]
                self._write_state_locked(force=True)
            self._append_event("child_completed", child=name, status="failed", error="missing_process_identity")
            raise ObservabilityError(f"Could not capture process start identity for child '{name}'.")
        child_state.update(
            {
                "status": "running",
                "pid": identity.pid,
                "start_identity": identity.start_identity,
                "next_action": "wait for child completion",
            }
        )
        with self._state_lock:
            self._state["next_action"] = f"wait for child {name}"
            self._state["last_progress"] = {"kind": "child_started", "child": name}
            self._state["last_progress_at"] = utc_now_iso()
            self._write_state_locked(force=True)
        self._append_event("child_started", child=name, attempt=attempt, command_fingerprint=command_fingerprint)
        self._active_process = process
        output_threads: list[threading.Thread] = []

        def consume(stream: Any, path: Path, stream_name: str) -> None:
            chunk_count = 0
            byte_count = 0
            with path.open("wb") as handle:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    handle.write(chunk)
                    handle.flush()
                    chunk_count += 1
                    byte_count += len(chunk)
                    with self._state_lock:
                        self._progress_counter += 1
                        progress = {
                            "kind": "child_output",
                            "child": name,
                            "stream": stream_name,
                            "chunk_count": chunk_count,
                            "bytes": byte_count,
                        }
                        child_state["last_progress"] = progress
                        child_state["last_progress_at"] = utc_now_iso()
                        self._state["last_progress"] = progress
                        self._state["last_progress_at"] = child_state["last_progress_at"]
                        self._write_state_locked()
                    if echo_output:
                        sys.stderr.write(f"[{name}/{stream_name}] {chunk.decode('utf-8', errors='replace')}")
                        sys.stderr.flush()

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
        cleanup: dict[str, Any] | None = None
        completed_normally = False
        try:
            returncode = process.wait(timeout=timeout_seconds)
            completed_normally = True
        except subprocess.TimeoutExpired:
            timed_out = True
            cleanup = terminate_owned_process_tree(process)
            try:
                returncode = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child_state["next_action"] = "inspect live child after failed cleanup"
                with self._state_lock:
                    self._state["next_action"] = child_state["next_action"]
                    self._state["last_progress"] = {"kind": "child_cleanup_failed", "child": name}
                    self._write_state_locked(force=True)
                self._append_event("child_cleanup_failed", child=name, cleanup=cleanup)
                raise ObservabilityError(f"Timed-out child '{name}' could not be cleaned up safely.")
            completed_normally = True
        except (KeyboardInterrupt, SystemExit) as error:
            cleanup = terminate_owned_process_tree(process)
            cleaned = bool(cleanup and cleanup.get("terminated")) or process.poll() is not None
            child_state.update(
                {
                    "status": "interrupted" if cleaned else "running",
                    "cleanup": cleanup,
                    "next_action": "resume after explicit interruption" if cleaned else "inspect live child after failed cleanup",
                }
            )
            with self._state_lock:
                self._state["children"][name] = child_state
                self._state["active_child"] = None if cleaned else child_state
                self._state["next_action"] = child_state["next_action"]
                self._write_state_locked(force=True)
            self._append_event("child_interrupted", child=name, reason=type(error).__name__, cleanup=cleanup)
            raise
        except BaseException as error:
            child_state["next_action"] = "inspect live child before resuming"
            with self._state_lock:
                self._state["next_action"] = child_state["next_action"]
                self._state["last_progress"] = {"kind": "child_interrupted", "child": name}
                self._write_state_locked(force=True)
            self._append_event("child_interrupted", child=name, reason=type(error).__name__)
            raise
        finally:
            for thread in output_threads:
                thread.join(timeout=5)
            if completed_normally or process.poll() is not None:
                self._active_process = None

        status = "passed" if returncode == 0 and not timed_out else "failed"
        completed_at = utc_now_iso()
        final_state = {
            **child_state,
            "status": status,
            "returncode": returncode,
            "timed_out": timed_out,
            "cleanup": cleanup,
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
        if status == "passed" and (
            (self._active_process is not None and self._active_process.poll() is None)
            or self._active_child_alive()
        ):
            raise ObservabilityError("Cannot finish an evidence run as passed while a child process is still active.")
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
        if self._lock_handle is None:
            return
        handle = self._lock_handle
        self._lock_handle = None
        self._release_os_lock(handle)
        handle.close()

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


def build_observed_child_report(
    spec: dict[str, Any],
    child: dict[str, Any],
    *,
    started_monotonic: float,
) -> dict[str, Any]:
    return {
        "name": spec["name"],
        "command": spec["command"],
        "returncode": child["returncode"],
        "duration_seconds": round(time.monotonic() - started_monotonic, 3),
        "status": child["status"],
        "stdout_tail": read_tail(child["stdout_log"]),
        "stderr_tail": read_tail(child["stderr_log"]),
        "stdout_log": child["stdout_log"],
        "stderr_log": child["stderr_log"],
        "pid": child.get("pid"),
        "start_identity": child.get("start_identity"),
        "attempt": child.get("attempt"),
        "reused": child.get("reused", False),
        "timed_out": child.get("timed_out", False),
    }


def default_child_timeout_seconds(name: str) -> float:
    """Bound one child without imposing a total-gate timeout."""

    if name in {"mock-ui", "mock-dashboard-scenario-matrix"} or name.startswith("scenario-"):
        return 1800.0
    if name in {"pytest", "postgres-order-concurrency", "recovery-ui", "consistency-report", "paper-session-gate", "audit-export"}:
        return 600.0
    return 120.0


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


@dataclass(frozen=True)
class BoundedProcessResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    status: str
    timed_out: bool = False
    interrupted: bool = False
    cleanup: dict[str, Any] | None = None
    pid: int | None = None
    start_identity: str | None = None


def _process_launch_kwargs() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _attach_process_identity(process: subprocess.Popen[Any]) -> ProcessIdentity | None:
    identity = ProcessIdentity(process.pid, process_start_identity(process.pid, include_exited=True))
    setattr(process, "_codex_start_identity", identity.start_identity)
    return identity if identity.start_identity else None


def terminate_owned_process_tree(
    process: subprocess.Popen[Any],
    *,
    grace_seconds: float = 5.0,
) -> dict[str, Any]:
    """Terminate only a process tree whose PID still has its recorded start identity."""

    expected = getattr(process, "_codex_start_identity", None)
    current = process_start_identity(process.pid)
    if not expected or current != expected:
        return {"attempted": False, "reason": "pid_start_identity_mismatch", "pid": process.pid}

    if os.name == "nt":
        completed = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            return {
                "attempted": True,
                "method": "taskkill-tree",
                "returncode": completed.returncode,
                "terminated": False,
                "pid": process.pid,
            }
        return {
            "attempted": True,
            "method": "taskkill-tree",
            "returncode": completed.returncode,
            "terminated": True,
            "pid": process.pid,
        }

    try:
        process_group = os.getpgid(process.pid)
        os.killpg(process_group, signal.SIGTERM)
    except (OSError, ProcessLookupError) as error:
        return {"attempted": False, "reason": f"killpg_failed:{type(error).__name__}", "pid": process.pid}
    try:
        process.wait(timeout=grace_seconds)
        return {"attempted": True, "method": "killpg-term", "terminated": True, "pid": process.pid}
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process_group, signal.SIGKILL)
            process.wait(timeout=grace_seconds)
            return {"attempted": True, "method": "killpg-kill", "terminated": True, "pid": process.pid}
        except (OSError, ProcessLookupError, subprocess.TimeoutExpired) as error:
            return {"attempted": True, "method": "killpg-kill", "terminated": False, "pid": process.pid, "error": str(error)}


def run_bounded_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout_seconds: float,
) -> BoundedProcessResult:
    """Run a browser helper with finite timeout and owned-tree cleanup."""

    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_process_launch_kwargs(),
        )
    except OSError as error:
        return BoundedProcessResult(
            command=command,
            returncode=127,
            stdout="",
            stderr=f"{type(error).__name__}: {error}",
            status="launch_failed",
        )
    identity = _attach_process_identity(process)
    if identity is None:
        cleanup = terminate_owned_process_tree(process)
        return BoundedProcessResult(
            command=command,
            returncode=127,
            stdout="",
            stderr="Could not capture browser helper process identity.",
            status="launch_failed",
            cleanup=cleanup,
            pid=process.pid,
        )
    try:
        stdout, stderr = process.communicate(timeout=max(1.0, timeout_seconds))
        return BoundedProcessResult(
            command=command,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
            status="completed",
            pid=process.pid,
            start_identity=identity.start_identity,
        )
    except subprocess.TimeoutExpired as error:
        cleanup = terminate_owned_process_tree(process)
        stdout, stderr = process.communicate(timeout=10)
        timeout_stdout = stdout or error.output or ""
        timeout_stderr = stderr or error.stderr or ""
        if isinstance(timeout_stdout, bytes):
            timeout_stdout = timeout_stdout.decode("utf-8", errors="replace")
        if isinstance(timeout_stderr, bytes):
            timeout_stderr = timeout_stderr.decode("utf-8", errors="replace")
        return BoundedProcessResult(
            command=command,
            returncode=process.returncode if process.returncode is not None else 124,
            stdout=timeout_stdout,
            stderr=timeout_stderr,
            status="timed_out",
            timed_out=True,
            cleanup=cleanup,
            pid=process.pid,
            start_identity=identity.start_identity,
        )
    except (KeyboardInterrupt, SystemExit):
        cleanup = terminate_owned_process_tree(process)
        stdout, stderr = process.communicate(timeout=10)
        raise RuntimeError(
            f"Browser helper interrupted; process tree cleanup={cleanup}.\n{stderr[-1000:]}"
        )


def start_utf8_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    output_log: Path | None = None,
) -> subprocess.Popen[str]:
    log_handle = None
    if output_log is not None:
        output_log.parent.mkdir(parents=True, exist_ok=True)
        log_handle = output_log.open("wb")
        stdout = log_handle
    else:
        stdout = subprocess.DEVNULL
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=stdout,
            stderr=subprocess.STDOUT,
            env=env,
            **_process_launch_kwargs(),
        )
    except BaseException:
        if log_handle is not None:
            log_handle.close()
        raise
    identity = _attach_process_identity(process)
    setattr(process, "_codex_output_handle", log_handle)
    setattr(process, "_codex_output_path", str(output_log) if output_log is not None else None)
    setattr(process, "_codex_start_identity", identity.start_identity if identity else None)
    return process


def stop_process(process: subprocess.Popen[Any], *, timeout_seconds: float = 5.0) -> None:
    if process.poll() is not None:
        handle = getattr(process, "_codex_output_handle", None)
        if handle is not None:
            handle.close()
        return
    terminate_owned_process_tree(process, grace_seconds=timeout_seconds)
    handle = getattr(process, "_codex_output_handle", None)
    if handle is not None and process.poll() is not None:
        handle.close()


def wait_for_http(
    url: str,
    *,
    process: subprocess.Popen[Any],
    timeout_seconds: float,
) -> None:
    from urllib.error import URLError
    from urllib.request import urlopen

    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            log_path = getattr(process, "_codex_output_path", None)
            output = read_tail(log_path, 4000) if log_path else ""
            raise RuntimeError(
                f"Process exited early with code {process.returncode}. "
                f"Diagnostic log: {log_path or 'unavailable'}.\n{output}"
            )
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return
        except (OSError, URLError) as error:
            last_error = str(error)
        time.sleep(0.25)
    raise RuntimeError(f"Process did not become ready at {url}: {last_error}")


def emit_report(report: dict[str, Any], json_output: str | None = None) -> None:
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if json_output:
        output_path = Path(json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

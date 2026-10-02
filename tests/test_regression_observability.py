from __future__ import annotations

import json
import os
import subprocess
import signal
import sys
import threading
import time
from argparse import Namespace
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.append(str(SCRIPTS_DIR))

import regression_common as common  # noqa: E402
from regression_common import (  # noqa: E402
    ObservabilityError,
    ObservedRun,
    RunAlreadyActiveError,
    current_process_identity,
    process_identity_matches,
    process_start_identity,
    run_bounded_process,
    start_utf8_process,
    stop_process,
)
from run_p0_safety_gate import child_specs, run_child as run_p0_child  # noqa: E402
from run_operator_platform_v8_gate import run_child as run_v8_child  # noqa: E402


def _source_root(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    (root / "source.txt").write_text("v1\n", encoding="utf-8")
    return root


def _command(*body: str) -> list[str]:
    return [sys.executable, "-c", "; ".join(body)]


def _events(evidence_dir: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (evidence_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_observed_child_streams_independent_logs_and_heartbeat(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    runner = ObservedRun(
        evidence_dir,
        source_root=_source_root(tmp_path),
        heartbeat_interval_seconds=0.02,
    )
    runner.start()
    result: dict[str, object] = {}
    command = _command(
        "import sys, time",
        "sys.stdout.write('stdout-before-sleep'); sys.stdout.flush()",
        "sys.stderr.write('stderr-before-sleep'); sys.stderr.flush()",
        "time.sleep(0.12)",
        "sys.stdout.write('stdout-after-sleep'); sys.stdout.flush()",
    )

    thread = threading.Thread(
        target=lambda: result.update(runner.run_child({"name": "stream", "command": command}, echo_output=False)),
        daemon=True,
    )
    thread.start()
    stdout_log = evidence_dir / "children" / "stream.attempt-1.stdout.log"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and "stdout-before-sleep" not in (stdout_log.read_text(encoding="utf-8") if stdout_log.exists() else ""):
        time.sleep(0.01)
    assert stdout_log.exists()
    assert "stdout-before-sleep" in stdout_log.read_text(encoding="utf-8")
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result["status"] == "passed"
    assert "stderr-before-sleep" in (evidence_dir / "children" / "stream.attempt-1.stderr.log").read_text(encoding="utf-8")
    runner.finish("passed")

    state = json.loads((evidence_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "passed"
    assert state["environment"]["python_distributions_fingerprint"]
    assert "node_version_fingerprint" in state["environment"]
    assert state["children"]["stream"]["pid"]
    assert state["children"]["stream"]["start_identity"]
    events = _events(evidence_dir)
    assert {event["event"] for event in events} >= {"run_started", "child_started", "child_completed", "run_finished"}
    assert any(event["event"] == "heartbeat" and event["alive"] is True for event in events)
    assert all("stdout-before-sleep" not in json.dumps(event) for event in events)


def test_observed_child_error_keeps_exit_and_log_evidence(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    runner = ObservedRun(evidence_dir, source_root=_source_root(tmp_path))
    runner.start()
    result = runner.run_child(
        {
            "name": "failure",
            "command": _command("import sys", "print('expected-error', file=sys.stderr, flush=True)", "sys.exit(7)"),
        },
        echo_output=False,
    )
    assert result["status"] == "failed"
    assert result["returncode"] == 7
    assert "expected-error" in Path(result["stderr_log"]).read_text(encoding="utf-8")
    runner.finish("failed", next_action="inspect child logs")
    state = json.loads((evidence_dir / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "failed"
    assert state["next_action"] == "inspect child logs"


def test_resume_reuses_only_matching_passed_child(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    source = _source_root(tmp_path)
    marker = tmp_path / "marker.txt"
    command = _command(
        f"from pathlib import Path; p=Path(r'{marker}'); p.write_text(p.read_text() + 'x' if p.exists() else 'x')",
    )

    first = ObservedRun(evidence_dir, source_root=source)
    first.start()
    reusable_spec = {"name": "reusable", "command": command, "cacheable": True}
    first_result = first.run_child(reusable_spec, echo_output=False)
    first.finish("passed")
    assert first_result["reused"] is False
    assert marker.read_text(encoding="utf-8") == "x"

    second = ObservedRun(evidence_dir, source_root=source)
    second.start()
    reused = second.run_child(reusable_spec, echo_output=False)
    second.finish("passed")
    assert reused["reused"] is True
    assert marker.read_text(encoding="utf-8") == "x"

    changed_command = _command(
        f"from pathlib import Path; p=Path(r'{marker}'); p.write_text(p.read_text() + 'y')",
    )
    third = ObservedRun(evidence_dir, source_root=source)
    third.start()
    invalidated = third.run_child({**reusable_spec, "command": changed_command}, echo_output=False)
    third.finish("passed")
    assert invalidated["reused"] is False
    assert marker.read_text(encoding="utf-8") == "xy"

    (source / "source.txt").write_text("v2\n", encoding="utf-8")
    fourth = ObservedRun(evidence_dir, source_root=source)
    fourth.start()
    source_invalidated = fourth.run_child({**reusable_spec, "command": changed_command}, echo_output=False)
    fourth.finish("passed")
    assert source_invalidated["reused"] is False
    assert marker.read_text(encoding="utf-8") == "xyy"
    assert any(event["event"] == "child_invalidated" for event in _events(evidence_dir))


def test_live_owner_and_live_child_cannot_be_duplicated(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    source = _source_root(tmp_path)
    owner = ObservedRun(evidence_dir, source_root=source)
    owner.start()
    duplicate = ObservedRun(evidence_dir, source_root=source)
    with pytest.raises(RunAlreadyActiveError):
        duplicate.start()
    owner.finish("interrupted", next_action="resume")


def test_two_processes_contend_for_the_same_os_lock(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    source = _source_root(tmp_path)
    helper = f"""
import sys, time
sys.path.insert(0, {str(SCRIPTS_DIR)!r})
from pathlib import Path
from regression_common import ObservedRun, RunAlreadyActiveError
run = ObservedRun(Path({str(evidence_dir)!r}), source_root=Path({str(source)!r}), heartbeat_interval_seconds=0.05)
try:
    run.start()
except RunAlreadyActiveError:
    print('blocked', flush=True)
    raise SystemExit(0)
print('ready', flush=True)
time.sleep(1.2)
run.finish('passed')
"""
    first = subprocess.Popen(
        [sys.executable, "-c", helper],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert first.stdout is not None
    assert first.stdout.readline().strip() == "ready"
    second = subprocess.run(
        [sys.executable, "-c", helper],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
    )
    assert second.returncode == 0
    assert "blocked" in second.stdout
    assert first.wait(timeout=5) == 0


def test_stale_owner_marks_interrupted_and_resume_can_acquire(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    source = _source_root(tmp_path)
    seed = ObservedRun(evidence_dir, source_root=source, run_id="stale-run")
    seed._state["status"] = "running"
    seed._state["owner"] = {"pid": 999999, "start_identity": "stale-owner"}
    seed._state["active_child"] = {
        "pid": 999999,
        "start_identity": "stale-child",
        "status": "running",
    }
    seed._write_state_locked(force=True)
    state = json.loads((evidence_dir / "state.json").read_text(encoding="utf-8"))
    state["owner"] = {"pid": 999999, "start_identity": "stale-owner"}
    state["active_child"] = {"pid": 999999, "start_identity": "stale-child", "status": "running"}
    (evidence_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (evidence_dir / "run.lock").write_text(
        json.dumps({"run_id": "stale-run", "pid": 999999, "start_identity": "stale-owner"}),
        encoding="utf-8",
    )

    resumed = ObservedRun(evidence_dir, source_root=source, run_id="stale-run")
    resumed.start()
    resumed.finish("interrupted", next_action="resume child")
    events = _events(evidence_dir)
    assert any(event["event"] == "owner_lost" for event in events)
    assert any(event["event"] == "child_interrupted" for event in events)


def test_launching_child_without_identity_blocks_resume(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    source = _source_root(tmp_path)
    seed = ObservedRun(evidence_dir, source_root=source, run_id="launching-run")
    seed._state["status"] = "running"
    seed._state["owner"] = {"pid": 999999, "start_identity": "stale-owner"}
    seed._state["active_child"] = {"name": "spawn-window", "status": "launching", "pid": None, "start_identity": None}
    seed._write_state_locked(force=True)
    state = json.loads((evidence_dir / "state.json").read_text(encoding="utf-8"))
    state["owner"] = {"pid": 999999, "start_identity": "stale-owner"}
    state["active_child"] = {"name": "spawn-window", "status": "launching", "pid": None, "start_identity": None}
    (evidence_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

    resumed = ObservedRun(evidence_dir, source_root=source, run_id="launching-run")
    with pytest.raises(ObservabilityError, match="spawn window"):
        resumed.start()
    state_after = json.loads((evidence_dir / "state.json").read_text(encoding="utf-8"))
    assert state_after["status"] == "needs_review"


def test_active_child_cannot_be_marked_passed(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    runner = ObservedRun(evidence_dir, source_root=_source_root(tmp_path))
    runner.start()
    result: dict[str, object] = {}
    thread = threading.Thread(
        target=lambda: result.update(
            runner.run_child(
                {"name": "interruptible", "command": _command("import time; time.sleep(1.0)")},
                echo_output=False,
            )
        ),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and runner._active_process is None:
        time.sleep(0.01)
    assert runner._active_process is not None
    with pytest.raises(ObservabilityError, match="still active"):
        runner.finish("passed")
    runner._active_process.terminate()
    thread.join(timeout=3)
    assert not thread.is_alive()
    runner.finish("failed", next_action="inspect child interruption")


def test_volatile_p0_children_are_never_cacheable(tmp_path: Path) -> None:
    specs = child_specs(
        Namespace(
            base_url="http://127.0.0.1:8000",
            account_id="LBPT10087357",
            skip_running_api_checks=True,
        ),
        tmp_path,
    )
    by_name = {spec["name"]: spec for spec in specs}
    assert by_name["environment-preflight"].get("cacheable", False) is False
    assert by_name["alembic-current"].get("cacheable", False) is False
    assert by_name["order-idempotency-preflight"].get("cacheable", False) is False
    assert by_name["py-compile-scripts"]["cacheable"] is True
    assert by_name["git-diff-check"]["cacheable"] is True


def test_process_identity_requires_start_token_to_avoid_pid_reuse() -> None:
    current = current_process_identity()
    assert current.start_identity
    assert process_identity_matches(current)
    assert not process_identity_matches({"pid": current.pid, "start_identity": "different-process"})
    assert not process_identity_matches({"pid": current.pid})


def test_bounded_process_timeout_cleans_owned_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "descendant.pid"
    grandchild_code = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        if os.name != "nt"
        else "import time; time.sleep(30)"
    )
    child_code = (
        "import subprocess, sys, time; "
        f"spawn_kwargs={{'start_new_session': True}} if sys.platform != 'win32' else {{'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}}; "
        f"p=subprocess.Popen([sys.executable, '-c', {grandchild_code!r}], **spawn_kwargs); "
        f"open(r'{pid_file}', 'w', encoding='ascii').write(str(p.pid)); "
        "time.sleep(30)"
    )
    result = run_bounded_process(
        [sys.executable, "-c", child_code],
        cwd=tmp_path,
        timeout_seconds=0.5,
    )
    assert result.status == "timed_out"
    assert result.timed_out is True
    assert result.cleanup and result.cleanup.get("attempted") is True
    descendant_pid = int(pid_file.read_text(encoding="ascii"))
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and process_start_identity(descendant_pid) is not None:
            time.sleep(0.05)
        assert process_start_identity(descendant_pid) is None
    finally:
        if process_start_identity(descendant_pid) is not None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(descendant_pid), "/T", "/F"], check=False)
            else:
                os.kill(descendant_pid, signal.SIGKILL)


def test_bounded_process_records_launch_and_nonzero_exit_faults(tmp_path: Path) -> None:
    missing = run_bounded_process(
        [str(tmp_path / "missing-browser-helper.exe")],
        cwd=tmp_path,
        timeout_seconds=1,
    )
    assert missing.status == "launch_failed"
    assert missing.returncode != 0

    exited = run_bounded_process(
        [sys.executable, "-c", "import sys; print('node-like failure'); sys.exit(3)"],
        cwd=tmp_path,
        timeout_seconds=1,
    )
    assert exited.status == "completed"
    assert exited.returncode == 3
    assert "node-like failure" in exited.stdout


def test_bounded_process_preserves_explicit_interrupt_status_and_cleans_tree(tmp_path: Path, monkeypatch) -> None:
    launch_kwargs = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    real_process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **launch_kwargs,
    )

    class InterruptingProcess:
        pid = real_process.pid

        @staticmethod
        def communicate(timeout=None):
            raise KeyboardInterrupt()

        @staticmethod
        def poll():
            return real_process.poll()

        @staticmethod
        def wait(timeout=None):
            return real_process.wait(timeout=timeout)

    monkeypatch.setattr(common.subprocess, "Popen", lambda *args, **kwargs: InterruptingProcess())
    monkeypatch.setattr(common, "terminate_owned_process_tree", lambda process: {"attempted": True, "terminated": True, "pid": process.pid})
    result = common.run_bounded_process(
        [sys.executable, "-c", "pass"],
        cwd=tmp_path,
        timeout_seconds=1,
    )
    assert result.status == "interrupted"
    assert result.interrupted is True
    assert result.cleanup and result.cleanup.get("terminated") is True
    real_process.terminate()
    real_process.wait(timeout=5)
    assert real_process.poll() is not None


def test_server_output_is_drained_to_diagnostic_log_without_pipe_deadlock(tmp_path: Path) -> None:
    output_log = tmp_path / "server.log"
    process = start_utf8_process(
        [sys.executable, "-c", "import sys; sys.stderr.write('x' * 200000)"],
        cwd=tmp_path,
        output_log=output_log,
    )
    try:
        assert process.wait(timeout=5) == 0
    finally:
        stop_process(process)
    assert output_log.stat().st_size >= 200000


def test_fast_child_exit_is_not_a_missing_identity_failure(tmp_path: Path, monkeypatch) -> None:
    import regression_common

    runner = ObservedRun(tmp_path / "evidence", source_root=_source_root(tmp_path))
    runner.start()
    real_probe = regression_common.process_start_identity

    def delayed_probe(pid, **kwargs):
        if pid != runner.owner.pid:
            time.sleep(0.2)
        return real_probe(pid, **kwargs)

    monkeypatch.setattr(regression_common, "process_start_identity", delayed_probe)
    try:
        child = runner.run_child({"name": "fast-exit", "command": [sys.executable, "-S", "-c", "pass"]})
    except BaseException:
        runner.finish("failed")
        raise
    runner.finish("passed")
    assert child["status"] == "passed"
    assert child["start_identity"]
    assert not process_identity_matches(child)


@pytest.mark.parametrize("child_runner", [run_p0_child, run_v8_child], ids=["p0", "v8"])
def test_aggregate_child_report_keeps_legacy_fields_and_adds_stream_evidence(tmp_path: Path, child_runner) -> None:
    evidence_dir = tmp_path / "evidence"
    runner = ObservedRun(evidence_dir, source_root=_source_root(tmp_path))
    runner.start()
    report = child_runner(
        {
            "name": "legacy-shape",
            "command": _command("print('ok', flush=True)"),
        },
        runner,
    )
    runner.finish("passed")
    assert {"name", "command", "returncode", "duration_seconds", "status", "stdout_tail", "stderr_tail"} <= report.keys()
    assert report["status"] == "passed"
    assert report["reused"] is False
    assert report["stdout_log"]

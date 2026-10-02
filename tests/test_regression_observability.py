from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

import pytest


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.append(str(SCRIPTS_DIR))

from regression_common import (  # noqa: E402
    ObservedRun,
    RunAlreadyActiveError,
    current_process_identity,
    process_identity_matches,
)
from run_p0_safety_gate import run_child as run_p0_child  # noqa: E402
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
        "print('stdout-before-sleep', flush=True)",
        "print('stderr-before-sleep', file=sys.stderr, flush=True)",
        "time.sleep(0.12)",
        "print('stdout-after-sleep', flush=True)",
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
    first_result = first.run_child({"name": "reusable", "command": command}, echo_output=False)
    first.finish("passed")
    assert first_result["reused"] is False
    assert marker.read_text(encoding="utf-8") == "x"

    second = ObservedRun(evidence_dir, source_root=source)
    second.start()
    reused = second.run_child({"name": "reusable", "command": command}, echo_output=False)
    second.finish("passed")
    assert reused["reused"] is True
    assert marker.read_text(encoding="utf-8") == "x"

    changed_command = _command(
        f"from pathlib import Path; p=Path(r'{marker}'); p.write_text(p.read_text() + 'y')",
    )
    third = ObservedRun(evidence_dir, source_root=source)
    third.start()
    invalidated = third.run_child({"name": "reusable", "command": changed_command}, echo_output=False)
    third.finish("passed")
    assert invalidated["reused"] is False
    assert marker.read_text(encoding="utf-8") == "xy"

    (source / "source.txt").write_text("v2\n", encoding="utf-8")
    fourth = ObservedRun(evidence_dir, source_root=source)
    fourth.start()
    source_invalidated = fourth.run_child({"name": "reusable", "command": changed_command}, echo_output=False)
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
    owner.lock_path.unlink()
    missing_lock_duplicate = ObservedRun(evidence_dir, source_root=source)
    with pytest.raises(RunAlreadyActiveError):
        missing_lock_duplicate.start()
    owner.finish("interrupted", next_action="resume")


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


def test_process_identity_requires_start_token_to_avoid_pid_reuse() -> None:
    current = current_process_identity()
    assert current.start_identity
    assert process_identity_matches(current)
    assert not process_identity_matches({"pid": current.pid, "start_identity": "different-process"})
    assert not process_identity_matches({"pid": current.pid})


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

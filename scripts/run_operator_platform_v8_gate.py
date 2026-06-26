from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"
DEFAULT_MANIFEST = ROOT / "artifacts" / "operator-platform-v8-manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the local Operator Platform Reliability V8 aggregate gate."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Running local API base URL.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument(
        "--evidence-dir",
        default=str(ROOT / "artifacts" / "operator-platform-v8"),
        help="Directory for child JSON evidence.",
    )
    parser.add_argument("--json-output", default=str(DEFAULT_MANIFEST), help="Top-level manifest path.")
    return parser.parse_args()


def child_specs(args: argparse.Namespace, evidence_dir: Path) -> list[dict[str, Any]]:
    py_compile_paths = [
        str(path)
        for path in sorted((ROOT / "scripts").glob("*.py"))
        if path.name not in {"__init__.py"}
    ]
    dashboard_js_paths = [
        "lifecycle-warning.js",
        "api-client.js",
        "formatters.js",
        "i18n.js",
        "state.js",
        "app.js",
    ]
    dashboard_node_specs = [
        {
            "name": f"dashboard-node-check-{Path(filename).stem}",
            "command": ["node", "--check", str(ROOT / "src" / "stocks_tool" / "ui" / "static" / filename)],
        }
        for filename in dashboard_js_paths
    ]
    return [
        {"name": "pytest", "command": [sys.executable, "-m", "pytest", "-q"]},
        {"name": "py-compile-scripts", "command": [sys.executable, "-m", "py_compile", *py_compile_paths]},
        *dashboard_node_specs,
        {"name": "alembic-heads", "command": [str(ROOT / ".venv" / "Scripts" / "alembic.exe"), "heads"]},
        {"name": "alembic-current", "command": [str(ROOT / ".venv" / "Scripts" / "alembic.exe"), "current"]},
        {
            "name": "worktree-release-inventory",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "run_regression.py"),
                "worktree-release-inventory",
                "--json-output",
                str(evidence_dir / "worktree-release-inventory.json"),
            ],
        },
        {
            "name": "mock-ui",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "run_regression.py"),
                "mock-ui",
                "--scenario",
                "all",
                "--json-output",
                str(evidence_dir / "mock-ui.json"),
            ],
        },
        {
            "name": "paper-session-gate",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "run_regression.py"),
                "paper-session-gate",
                "--base-url",
                args.base_url.rstrip("/"),
                "--account-id",
                args.account_id,
                "--session",
                "full",
                "--strict",
                "--evidence-dir",
                str(evidence_dir / "paper-session-gate"),
                "--json-output",
                str(evidence_dir / "paper-session-gate.json"),
            ],
        },
        {
            "name": "audit-export",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "run_regression.py"),
                "audit-export",
                "--base-url",
                args.base_url.rstrip("/"),
                "--account-id",
                args.account_id,
                "--json-output",
                str(evidence_dir / "audit-export.json"),
            ],
        },
        {
            "name": "consistency-report",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "run_regression.py"),
                "consistency-report",
                "--base-url",
                args.base_url.rstrip("/"),
                "--account-id",
                args.account_id,
                "--json-output",
                str(evidence_dir / "consistency-report.json"),
            ],
        },
        {"name": "git-diff-check", "command": ["git", "diff", "--check"]},
    ]


def run_child(spec: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        spec["command"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "name": spec["name"],
        "command": spec["command"],
        "returncode": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "status": "passed" if completed.returncode == 0 else "failed",
        "stdout_tail": completed.stdout[-1200:],
        "stderr_tail": completed.stderr[-1200:],
    }


def main() -> None:
    args = parse_args()
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    children = [run_child(spec) for spec in child_specs(args, evidence_dir)]
    failed = any(child["returncode"] != 0 for child in children)
    emit_report(
        build_report(
            script="run_operator_platform_v8_gate.py",
            workflow="operator-platform-v8",
            status="failed" if failed else "passed",
            mode="local",
            target=str(ROOT),
            summary=(
                f"Operator Platform V8 aggregate gate {'failed' if failed else 'passed'} "
                f"with {len(children)} child checks."
            ),
            payload={
                "base_url": args.base_url.rstrip("/"),
                "account_id": args.account_id,
                "evidence_dir": str(evidence_dir),
                "broker_submit_allowed_by_default": False,
                "confirmed_zero_dte_force_scan_included": False,
                "deepseek_call_included": False,
                "children": children,
            },
        ),
        json_output=args.json_output,
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

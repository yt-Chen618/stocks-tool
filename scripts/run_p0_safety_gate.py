from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from regression_common import build_report, emit_report


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"
DEFAULT_MANIFEST = ROOT / "artifacts" / "p0-safety-manifest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the paper-first P0 trading safety aggregate gate."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument(
        "--evidence-dir",
        default=str(ROOT / "artifacts" / "p0-safety"),
    )
    parser.add_argument("--json-output", default=str(DEFAULT_MANIFEST))
    parser.add_argument(
        "--skip-running-api-checks",
        action="store_true",
        help="Skip read-only checks that require a separately running local API.",
    )
    return parser.parse_args()


def child_specs(args: argparse.Namespace, evidence_dir: Path) -> list[dict[str, Any]]:
    py_compile_paths = [
        str(path)
        for path in sorted((ROOT / "scripts").glob("*.py"))
        if path.name != "__init__.py"
    ]
    static_dir = ROOT / "src" / "stocks_tool" / "ui" / "static"
    dashboard_js_paths = [
        path.relative_to(static_dir).as_posix()
        for path in sorted(static_dir.rglob("*.js"))
    ]
    specs: list[dict[str, Any]] = [
        {"name": "pytest", "command": [sys.executable, "-m", "pytest", "-q"]},
        {
            "name": "py-compile-scripts",
            "command": [sys.executable, "-m", "py_compile", *py_compile_paths],
        },
        *[
            {
                "name": f"dashboard-node-check-{Path(filename).stem}",
                "command": [
                    "node",
                    "--check",
                    str(ROOT / "src" / "stocks_tool" / "ui" / "static" / filename),
                ],
            }
            for filename in dashboard_js_paths
        ],
        {
            "name": "alembic-heads",
            "command": [str(ROOT / ".venv" / "Scripts" / "alembic.exe"), "heads"],
        },
        {
            "name": "alembic-current",
            "command": [str(ROOT / ".venv" / "Scripts" / "alembic.exe"), "current"],
        },
        {
            "name": "alembic-head-current-match",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "check_alembic_head_current.py"),
                "--json-output",
                str(evidence_dir / "alembic-head-current-match.json"),
            ],
        },
        {
            "name": "order-idempotency-preflight",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "check_order_external_id_duplicates.py"),
                "--json-output",
                str(evidence_dir / "order-idempotency-preflight.json"),
            ],
        },
        {
            "name": "postgres-order-concurrency",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "run_postgres_order_concurrency.py"),
                "--json-output",
                str(evidence_dir / "postgres-order-concurrency.json"),
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
    ]
    if not args.skip_running_api_checks:
        specs.append(
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
            }
        )
    specs.append({"name": "git-diff-check", "command": ["git", "diff", "--check"]})
    return specs


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
            script="run_p0_safety_gate.py",
            workflow="p0-safety",
            status="failed" if failed else "passed",
            mode="local-isolated-test",
            target=str(ROOT),
            summary=(
                f"P0 safety aggregate gate {'failed' if failed else 'passed'} "
                f"with {len(children)} child checks."
            ),
            payload={
                "base_url": args.base_url.rstrip("/"),
                "account_id": args.account_id,
                "evidence_dir": str(evidence_dir),
                "broker_order_submit_allowed": False,
                "local_repair_allowed": False,
                "destructive_actions_allowed": False,
                "running_api_checks_skipped": args.skip_running_api_checks,
                "children": children,
            },
        ),
        json_output=args.json_output,
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

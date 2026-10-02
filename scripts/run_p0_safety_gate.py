from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from regression_common import ObservedRun, build_observed_child_report, build_report, emit_report


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
        {
            "name": "environment-preflight",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "check_environment.py"),
                "--strict", "--json-output", str(evidence_dir / "environment.json"),
            ],
        },
        {"name": "pytest", "command": [sys.executable, "-m", "pytest", "-q"]},
        {
            "name": "py-compile-scripts",
            "command": [sys.executable, "-m", "py_compile", *py_compile_paths],
            "cacheable": True,
        },
        *[
            {
                "name": f"dashboard-node-check-{Path(filename).stem}",
                "command": [
                    "node",
                    "--check",
                    str(ROOT / "src" / "stocks_tool" / "ui" / "static" / filename),
                ],
                "cacheable": True,
            }
            for filename in dashboard_js_paths
        ],
        {
            "name": "alembic-heads",
            "command": [sys.executable, "-m", "alembic", "heads"],
        },
        {
            "name": "alembic-current",
            "command": [sys.executable, "-m", "alembic", "current"],
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
        {
            "name": "recovery-ui",
            "command": [
                sys.executable,
                str(ROOT / "scripts" / "run_recovery_ui_regression.py"),
                "--json-output",
                str(evidence_dir / "recovery-ui.json"),
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
    specs.append({"name": "git-diff-check", "command": ["git", "diff", "--check"], "cacheable": True})
    return specs


def run_child(spec: dict[str, Any], observed_run: ObservedRun) -> dict[str, Any]:
    started = time.monotonic()
    child = observed_run.run_child(
        {**spec, "cwd": str(ROOT)},
        timeout_seconds=spec.get("timeout_seconds"),
    )
    return build_observed_child_report(spec, child, started_monotonic=started)


def main() -> None:
    args = parse_args()
    evidence_dir = Path(args.evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    observed_run = ObservedRun(evidence_dir, source_root=ROOT)
    observed_run.start()
    children: list[dict[str, Any]] = []
    failed = False
    try:
        for spec in child_specs(args, evidence_dir):
            child = run_child(spec, observed_run)
            children.append(child)
            if child["returncode"] != 0:
                failed = True
    except Exception as error:
        failed = True
        observed_run.finish("failed", next_action="inspect observability state and child logs", error=str(error))
        raise
    else:
        observed_run.finish("failed" if failed else "passed")
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
                "observability": observed_run.payload(),
            },
        ),
        json_output=args.json_output,
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

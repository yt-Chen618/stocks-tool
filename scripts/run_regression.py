from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_BY_WORKFLOW = {
    "audit-export": ROOT / "scripts" / "run_audit_export_regression.py",
    "bull-put-paper": ROOT / "scripts" / "run_bull_put_strategy_regression.py",
    "bull-put-readiness": ROOT / "scripts" / "run_bull_put_readiness_check.py",
    "bull-put-real-paper": ROOT / "scripts" / "run_bull_put_real_paper_smoke.py",
    "mock-ui": ROOT / "scripts" / "run_mock_ui_order_regression.py",
    "real-paper": ROOT / "scripts" / "run_real_paper_order_smoke.py",
    "real-preopen-board": ROOT / "scripts" / "run_real_local_preopen_board_regression.py",
    "real-ui-refresh": ROOT / "scripts" / "run_real_local_dashboard_refresh_regression.py",
    "scheduler-on-long-gate": ROOT / "scripts" / "run_scheduler_on_long_gate.py",
    "advisor-intake": ROOT / "scripts" / "run_strategy_advisor_intake.py",
    "unattended-paper": ROOT / "scripts" / "run_unattended_paper.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Unified entrypoint for dashboard/order regression scripts. "
            "Use `mock-ui` for the local in-memory UI flow, `bull-put-paper` for the in-memory bull put service flow, "
            "`bull-put-readiness` for the read-only opening readiness check, "
            "`bull-put-real-paper` for real Longbridge bull put preview smoke, `real-paper` for the stock-order paper smoke flow, "
            "`real-preopen-board` for live localhost pre-open board checks, `real-ui-refresh` for repeated reload "
            "timing checks against an already running localhost dashboard, `audit-export` for read-only audit evidence, "
            "and `scheduler-on-long-gate` for a temporary scheduler-enabled API gate. Use `advisor-intake` to fetch advisor context "
            "and optionally record read-only advisor responses. Use `unattended-paper` to arm, inspect, or resume "
            "the local paper unattended workflow."
        )
    )
    parser.add_argument(
        "workflow",
        choices=sorted(SCRIPT_BY_WORKFLOW),
        help="Regression workflow to run.",
    )
    parser.add_argument(
        "workflow_args",
        nargs=argparse.REMAINDER,
        help="Additional arguments passed through to the selected workflow script.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    command = [
        sys.executable,
        str(SCRIPT_BY_WORKFLOW[args.workflow]),
        *args.workflow_args,
    ]
    completed = subprocess.run(command, cwd=ROOT)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_BY_WORKFLOW = {
    "bull-put-paper": ROOT / "scripts" / "run_bull_put_strategy_regression.py",
    "mock-ui": ROOT / "scripts" / "run_mock_ui_order_regression.py",
    "real-paper": ROOT / "scripts" / "run_real_paper_order_smoke.py",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Unified entrypoint for dashboard/order regression scripts. "
            "Use `mock-ui` for the local in-memory UI flow, `bull-put-paper` for the in-memory bull put service flow, "
            "and `real-paper` for the local paper-account smoke flow."
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

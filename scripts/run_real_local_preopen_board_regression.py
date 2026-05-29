from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from regression_common import build_report, emit_report


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class RegressionError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the real localhost dashboard loads a fresh fast pre-open board.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--expected-session-date",
        default=datetime.now(ZoneInfo("America/New_York")).date().isoformat(),
        help="Expected pre-open target_session_date. Defaults to today's New York date.",
    )
    parser.add_argument("--json-output", type=Path, default=None)
    return parser.parse_args()


def require_ok(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        raise RegressionError(f"{response.request.method} {response.request.url} returned {response.status_code}: {response.text}")
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    return response.text


def resolve_playwright_core() -> str:
    npm_command = shutil.which("npm.cmd") or shutil.which("npm")
    if npm_command is None:
        raise RegressionError("Could not find npm. Install Node.js/npm before running browser regression.")
    npm_root = subprocess.run(
        [npm_command, "root", "-g"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    candidates = [
        Path(npm_root) / "@playwright" / "cli" / "node_modules" / "playwright-core",
        Path(npm_root) / "playwright-core",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    raise RegressionError("Could not locate a global playwright-core install. Install @playwright/cli and browsers first.")


def run_browser_flow(*, base_url: str, expected_session_date: str) -> dict[str, Any]:
    node_command = shutil.which("node.exe") or shutil.which("node")
    if node_command is None:
        raise RegressionError("Could not find node. Install Node.js before running browser regression.")
    screenshot_path = ROOT / "output" / "playwright" / "real-local-preopen-board.png"
    completed = subprocess.run(
        [
            node_command,
            str(ROOT / "scripts" / "real_local_preopen_board_flow.js"),
            base_url,
            str(screenshot_path),
            resolve_playwright_core(),
            expected_session_date,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ},
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown browser regression failure."
        raise RegressionError(detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RegressionError(f"Browser regression output was not valid JSON: {completed.stdout}") from error


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    client = httpx.Client(base_url=base_url, timeout=10)

    try:
        health = require_ok(client.get("/health"))
        browser = run_browser_flow(
            base_url=base_url,
            expected_session_date=args.expected_session_date,
        )
        response = browser["response"]["body"]
        emit_report(
            build_report(
                script="run_real_local_preopen_board_regression.py",
                workflow="real-local-preopen-board-regression",
                status="passed",
                mode="real-local",
                target=base_url,
                summary=(
                    "Real local pre-open board returned live fast-path data for "
                    f"{response['target_session_date']} with status {response['freshness_status']}."
                ),
                payload={
                    "health": health,
                    "expected_session_date": args.expected_session_date,
                    "response": response,
                    "snapshot": browser["snapshot"],
                    "screenshot": browser["screenshot"],
                },
            ),
            json_output=args.json_output,
        )
    except Exception as exc:
        emit_report(
            build_report(
                script="run_real_local_preopen_board_regression.py",
                workflow="real-local-preopen-board-regression",
                status="failed",
                mode="real-local",
                target=base_url,
                summary=str(exc),
                payload={"expected_session_date": args.expected_session_date},
            ),
            json_output=args.json_output,
        )
        raise
    finally:
        client.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
from browser_runtime import browser_environment, resolve_node, resolve_playwright_core
from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"


class RegressionError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a browser-driven refresh regression against an already running local dashboard instance. "
            "This keeps the real localhost:8000 process warm and measures repeated reload timings."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local dashboard base URL.")
    parser.add_argument("--iterations", type=int, default=5, help="Number of page loads including the initial open.")
    parser.add_argument(
        "--settle-timeout-seconds",
        type=float,
        default=15.0,
        help="Timeout for each page load to reach dashboard-ready and overlay-settled states.",
    )
    parser.add_argument(
        "--pause-milliseconds",
        type=int,
        default=500,
        help="Pause between reloads so repeated checks mimic a user-driven refresh cadence.",
    )
    parser.add_argument(
        "--dashboard-target-ms",
        type=int,
        default=3000,
        help="Target upper bound for the first-stage dashboard-ready timing.",
    )
    parser.add_argument(
        "--overlay-target-ms",
        type=int,
        default=7000,
        help="Target upper bound for the full overlay-settled timing.",
    )
    parser.add_argument(
        "--research-target-ms",
        type=int,
        default=3000,
        help="Target upper bound for warm research-table readiness without waiting for technicals.",
    )
    parser.add_argument(
        "--chart-target-ms",
        type=int,
        default=2000,
        help="Target upper bound for a warm cached selected-symbol chart.",
    )
    parser.add_argument("--json-output", help="Optional file path for the JSON regression report.")
    return parser.parse_args()


def require_ok(response: httpx.Response) -> Any:
    if response.is_success:
        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.text
    detail = f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("detail"):
        detail = str(payload["detail"])
    raise RegressionError(detail)


def run_browser_flow(
    *,
    base_url: str,
    iterations: int,
    settle_timeout_seconds: float,
    pause_milliseconds: int,
) -> dict[str, Any]:
    screenshot_path = ROOT / "output" / "playwright" / "real-local-dashboard-refresh.png"
    playwright_core_path = resolve_playwright_core()
    node_command = resolve_node()
    completed = subprocess.run(
        [
            node_command,
            str(ROOT / "scripts" / "real_local_dashboard_refresh_flow.js"),
            base_url,
            str(screenshot_path),
            playwright_core_path,
            str(iterations),
            str(int(settle_timeout_seconds * 1000)),
            str(pause_milliseconds),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=browser_environment(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown browser regression failure."
        raise RegressionError(detail)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RegressionError(f"Browser regression output was not valid JSON: {completed.stdout}") from error


def summarize_runs(
    runs: list[dict[str, Any]],
    *,
    dashboard_target_ms: int,
    overlay_target_ms: int,
    research_target_ms: int,
    chart_target_ms: int,
) -> dict[str, Any]:
    if not runs:
        raise RegressionError("Browser refresh regression returned no runs.")

    dashboard_timings = [int(run["dashboard_ready_ms"]) for run in runs]
    research_timings = [int(run["research_table_ready_ms"]) for run in runs]
    chart_timings = [int(run["selected_chart_ready_ms"]) for run in runs]
    overlay_timings = [int(run["overlays_settled_ms"]) for run in runs]
    warm_dashboard_timings = dashboard_timings[1:] or dashboard_timings
    warm_research_timings = research_timings[1:] or research_timings
    warm_chart_timings = chart_timings[1:] or chart_timings
    warm_overlay_timings = overlay_timings[1:] or overlay_timings
    dashboard_paths = [
        resource
        for run in runs
        for resource in run.get("resource_timings_ms", [])
    ]

    def aggregate_by_prefix(prefix: str) -> list[float]:
        return [
            float(resource["duration_ms"])
            for resource in dashboard_paths
            if str(resource.get("path", "")).startswith(prefix)
        ]

    def summarize_prefix(prefix: str) -> dict[str, Any] | None:
        durations = aggregate_by_prefix(prefix)
        if not durations:
            return None
        return {
            "count": len(durations),
            "max_ms": round(max(durations), 1),
            "avg_ms": round(sum(durations) / len(durations), 1),
        }

    resource_summary = {
        prefix: summary
        for prefix in (
            "/account-snapshots/latest",
            "/research/universe",
            "/research/technicals",
            "/research/symbols/",
            "/strategies/pre-open-risk",
            "/orders",
            "/strategies/bull-put/spreads",
            "/strategies/bull-put/runtime",
            "/strategies/experiment",
            "/executions",
            "/journals",
            "/strategies/pre-open-runs",
        )
        if (summary := summarize_prefix(prefix)) is not None
    }

    return {
        "iterations": len(runs),
        "dashboard_target_ms": dashboard_target_ms,
        "overlay_target_ms": overlay_target_ms,
        "research_target_ms": research_target_ms,
        "chart_target_ms": chart_target_ms,
        "dashboard_ready": {
            "min_ms": min(dashboard_timings),
            "max_ms": max(dashboard_timings),
            "avg_ms": round(sum(dashboard_timings) / len(dashboard_timings), 1),
            "warm_within_target": all(value <= dashboard_target_ms for value in warm_dashboard_timings),
        },
        "overlay_settled": {
            "min_ms": min(overlay_timings),
            "max_ms": max(overlay_timings),
            "avg_ms": round(sum(overlay_timings) / len(overlay_timings), 1),
            "warm_within_target": all(value <= overlay_target_ms for value in warm_overlay_timings),
        },
        "research_table_ready": {
            "min_ms": min(research_timings),
            "max_ms": max(research_timings),
            "avg_ms": round(sum(research_timings) / len(research_timings), 1),
            "warm_within_target": all(value <= research_target_ms for value in warm_research_timings),
        },
        "selected_chart_ready": {
            "min_ms": min(chart_timings),
            "max_ms": max(chart_timings),
            "avg_ms": round(sum(chart_timings) / len(chart_timings), 1),
            "warm_within_target": all(value <= chart_target_ms for value in warm_chart_timings),
        },
        "resource_summary_ms": resource_summary,
    }


def build_summary_line(summary: dict[str, Any]) -> str:
    dashboard = summary["dashboard_ready"]
    research = summary["research_table_ready"]
    chart = summary["selected_chart_ready"]
    overlay = summary["overlay_settled"]
    return (
        "Real local dashboard refresh regression passed. "
        f"Dashboard ready {dashboard['min_ms']}-{dashboard['max_ms']}ms, "
        f"research table {research['min_ms']}-{research['max_ms']}ms, "
        f"selected chart {chart['min_ms']}-{chart['max_ms']}ms, "
        f"overlays settled {overlay['min_ms']}-{overlay['max_ms']}ms across {summary['iterations']} loads."
    )


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    client = httpx.Client(base_url=base_url, timeout=max(5.0, args.settle_timeout_seconds))

    try:
        try:
            health = require_ok(client.get("/health"))
            dashboard_html = require_ok(client.get("/"))
            if "Holdings Overview" not in dashboard_html:
                raise RegressionError("Dashboard HTML did not include the expected Holdings Overview shell.")

            browser = run_browser_flow(
                base_url=base_url,
                iterations=args.iterations,
                settle_timeout_seconds=args.settle_timeout_seconds,
                pause_milliseconds=args.pause_milliseconds,
            )
            summary = summarize_runs(
                browser["runs"],
                dashboard_target_ms=args.dashboard_target_ms,
                overlay_target_ms=args.overlay_target_ms,
                research_target_ms=args.research_target_ms,
                chart_target_ms=args.chart_target_ms,
            )
            if (
                not summary["dashboard_ready"]["warm_within_target"]
                or not summary["overlay_settled"]["warm_within_target"]
                or not summary["research_table_ready"]["warm_within_target"]
                or not summary["selected_chart_ready"]["warm_within_target"]
            ):
                raise RegressionError(
                    "Dashboard refresh timings exceeded the configured target. "
                    f"dashboard={summary['dashboard_ready']} research={summary['research_table_ready']} "
                    f"chart={summary['selected_chart_ready']} overlay={summary['overlay_settled']}"
                )

            emit_report(
                build_report(
                    script="run_real_local_dashboard_refresh_regression.py",
                    workflow="real-local-dashboard-refresh-regression",
                    status="passed",
                    mode="real-local",
                    target=base_url,
                    summary=build_summary_line(summary),
                    payload={
                        "health": health,
                        "summary": summary,
                        "runs": browser["runs"],
                        "screenshot": browser["screenshot"],
                    },
                ),
                json_output=args.json_output,
            )
        except Exception as error:
            emit_report(
                build_report(
                    script="run_real_local_dashboard_refresh_regression.py",
                    workflow="real-local-dashboard-refresh-regression",
                    status="failed",
                    mode="real-local",
                    target=base_url,
                    summary="Real local dashboard refresh regression failed.",
                    error=str(error),
                ),
                json_output=args.json_output,
            )
            raise SystemExit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()

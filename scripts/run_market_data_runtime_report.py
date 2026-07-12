from __future__ import annotations

import argparse
import json
from typing import Any

import httpx

from regression_common import build_report, emit_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only Longbridge market-data runtime metrics."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--json-output")
    return parser.parse_args()


def require_ok(response: httpx.Response) -> Any:
    if response.is_success:
        return response.json()
    try:
        detail = response.json().get("detail")
    except (AttributeError, json.JSONDecodeError):
        detail = None
    raise RuntimeError(str(detail or f"HTTP {response.status_code}"))


def summarize(runtime: dict[str, Any]) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "session_count": 0,
        "request_count": 0,
        "sdk_call_count": 0,
        "cache_hit_count": 0,
        "cache_miss_count": 0,
        "failure_count": 0,
        "timeout_count": 0,
        "pending_requests": 0,
        "max_latency_ms": 0.0,
    }
    sessions = runtime.get("sessions") or []
    totals["session_count"] = len(sessions)
    for session in sessions:
        totals["pending_requests"] += int(session.get("pending_requests") or 0)
        for operation in session.get("operations") or []:
            for name in (
                "request_count",
                "sdk_call_count",
                "cache_hit_count",
                "cache_miss_count",
                "failure_count",
                "timeout_count",
            ):
                totals[name] += int(operation.get(name) or 0)
            totals["max_latency_ms"] = max(
                float(totals["max_latency_ms"]),
                float(operation.get("max_latency_ms") or 0),
            )
    return totals


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    try:
        with httpx.Client(base_url=base_url, timeout=args.timeout_seconds) as client:
            health = require_ok(client.get("/health"))
            runtime = require_ok(client.get("/ops/market-data-runtime"))
        if not isinstance(runtime, dict):
            raise RuntimeError("/ops/market-data-runtime did not return an object.")
        totals = summarize(runtime)
        status = (
            "warning"
            if totals["failure_count"] or totals["timeout_count"] or totals["pending_requests"]
            else "passed"
        )
        report = build_report(
            script="run_market_data_runtime_report.py",
            workflow="market-data-runtime",
            status=status,
            mode="read-only",
            target=base_url,
            summary=(
                "Market-data runtime metrics exported. "
                f"requests={totals['request_count']}, sdk_calls={totals['sdk_call_count']}, "
                f"cache_hits={totals['cache_hit_count']}, failures={totals['failure_count']}."
            ),
            payload={
                "health": health,
                "totals": totals,
                "runtime": runtime,
                "broker_order_submit_allowed": False,
                "local_repair_executed": False,
                "destructive_actions_executed": False,
            },
        )
    except Exception as exc:
        report = build_report(
            script="run_market_data_runtime_report.py",
            workflow="market-data-runtime",
            status="failed",
            mode="read-only",
            target=base_url,
            summary="Market-data runtime export failed.",
            error=str(exc),
        )
    emit_report(report, json_output=args.json_output)
    if report["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"


class ConsistencyReportError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export read-only operator consistency evidence from a running local API."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument("--mode", default="paper", help="Execution mode filter.")
    parser.add_argument("--strategy", help="Optional strategy id filter.")
    parser.add_argument("--limit", type=int, default=50, help="Consistency check export limit.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP timeout.")
    parser.add_argument("--json-output", help="Optional file path for the JSON regression report.")
    return parser.parse_args()


def require_ok(response: httpx.Response) -> Any:
    if response.is_success:
        return response.json()
    detail = f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict) and payload.get("detail"):
        detail = str(payload["detail"])
    raise ConsistencyReportError(detail)


def raw_export_path(json_output: str | None) -> Path | None:
    if not json_output:
        return None
    path = Path(json_output)
    return path.with_name(f"{path.stem}.raw-consistency{path.suffix or '.json'}")


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    status = "failed"
    with httpx.Client(base_url=base_url, timeout=args.timeout_seconds) as client:
        try:
            health = require_ok(client.get("/health"))
            params: dict[str, Any] = {
                "external_account_id": args.account_id,
                "mode": args.mode,
                "limit": args.limit,
            }
            if args.strategy:
                params["strategy"] = args.strategy
            consistency = require_ok(client.get("/ops/consistency", params=params))
            if not isinstance(consistency, dict):
                raise ConsistencyReportError("/ops/consistency did not return an object.")
            report_status = str(consistency.get("status") or "fail")
            status = "failed" if report_status == "fail" else "warning" if report_status == "warn" else "passed"
            raw_path = raw_export_path(args.json_output)
            if raw_path is not None:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(json.dumps(consistency, indent=2), encoding="utf-8")
            emit_report(
                build_report(
                    script="run_consistency_report.py",
                    workflow="consistency-report",
                    status=status,
                    mode=args.mode,
                    target=base_url,
                    summary=(
                        "Operator consistency report completed. "
                        f"status={report_status}, checks={consistency.get('check_count')}, "
                        f"repairs={consistency.get('repair_available_count')}."
                    ),
                    payload={
                        "health": health,
                        "account_id": args.account_id,
                        "strategy": args.strategy,
                        "consistency": consistency,
                        "raw_export_path": str(raw_path) if raw_path is not None else None,
                        "broker_order_submit_allowed": False,
                        "local_repair_available": bool(consistency.get("repair_available_count")),
                        "local_repair_executed": False,
                        "destructive_actions_executed": False,
                    },
                ),
                json_output=args.json_output,
            )
        except Exception as error:
            emit_report(
                build_report(
                    script="run_consistency_report.py",
                    workflow="consistency-report",
                    status="failed",
                    mode=args.mode,
                    target=base_url,
                    summary="Operator consistency report failed.",
                    error=str(error),
                    payload={
                        "account_id": args.account_id,
                        "broker_order_submit_allowed": False,
                        "local_repair_executed": False,
                        "destructive_actions_executed": False,
                    },
                ),
                json_output=args.json_output,
            )
            raise SystemExit(1)
    if status == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

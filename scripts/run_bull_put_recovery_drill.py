from __future__ import annotations

import argparse
from typing import Any

import httpx
from regression_common import build_report, emit_report

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"


class RecoveryDrillError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read bull put recover-close eligibility and emit a paper-only operator drill report."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument("--mode", default="paper", help="Execution mode filter.")
    parser.add_argument("--spread-id", help="Optional spread id to inspect. Defaults to all listed spreads.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP timeout.")
    parser.add_argument("--json-output", help="Optional file path for the JSON regression report.")
    return parser.parse_args()


def require_ok(response: httpx.Response) -> Any:
    if response.is_success:
        return response.json()
    detail = f"HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("detail"):
        detail = str(payload["detail"])
    raise RecoveryDrillError(detail)


def spread_brief(spread: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": spread.get("id"),
        "symbol": spread.get("underlying_symbol"),
        "status": spread.get("status"),
        "latest_should_close": spread.get("latest_monitor_should_close"),
        "short_exit_order_id": spread.get("short_exit_order_id"),
        "latest_close_order_status": spread.get("latest_close_order_status"),
        "manual_action_required": spread.get("manual_action_required"),
    }


def operator_action(eligibility: dict[str, Any]) -> str:
    if eligibility.get("eligible") is True:
        return "manual_recover_close_allowed"
    reasons = set(eligibility.get("reasons") or [])
    if "close_not_required" in reasons:
        return "observe_no_recovery"
    if "working_replacement_exists" in reasons:
        return "monitor_existing_replacement"
    if "account_mismatch" in reasons or "paper_mode_required" in reasons:
        return "fix_request_context"
    if "missing_short_close_order" in reasons:
        return "inspect_lifecycle_history"
    return "blocked_review_reasons"


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    with httpx.Client(base_url=base_url, timeout=args.timeout_seconds) as client:
        try:
            health = require_ok(client.get("/health"))
            if args.spread_id:
                spreads = [{"id": args.spread_id}]
            else:
                spreads_payload = require_ok(
                    client.get(
                        "/strategies/bull-put/spreads",
                        params={"external_account_id": args.account_id, "mode": args.mode},
                    )
                )
                if not isinstance(spreads_payload, list):
                    raise RecoveryDrillError("/strategies/bull-put/spreads did not return a list.")
                spreads = [item for item in spreads_payload if isinstance(item, dict) and item.get("id")]

            drill_items: list[dict[str, Any]] = []
            for spread in spreads:
                spread_id = str(spread["id"])
                eligibility = require_ok(
                    client.get(
                        f"/strategies/bull-put/spreads/{spread_id}/recover-close/eligibility",
                        params={"external_account_id": args.account_id, "mode": args.mode},
                    )
                )
                if not isinstance(eligibility, dict):
                    raise RecoveryDrillError("recover-close eligibility did not return an object.")
                drill_items.append(
                    {
                        "spread": spread_brief(spread),
                        "eligibility": eligibility,
                        "operator_action": operator_action(eligibility),
                    }
                )

            eligible_count = sum(1 for item in drill_items if item["eligibility"].get("eligible") is True)
            blocked_count = len(drill_items) - eligible_count
            emit_report(
                build_report(
                    script="run_bull_put_recovery_drill.py",
                    workflow="bull-put-recovery-drill",
                    status="passed",
                    mode=args.mode,
                    target=base_url,
                    summary=(
                        "Bull put recovery drill completed. "
                        f"spreads={len(drill_items)}, eligible={eligible_count}, blocked={blocked_count}."
                    ),
                    payload={
                        "health": health,
                        "account_id": args.account_id,
                        "inspected_spread_count": len(drill_items),
                        "eligible_count": eligible_count,
                        "blocked_count": blocked_count,
                        "items": drill_items,
                        "post_endpoint_called": False,
                    },
                ),
                json_output=args.json_output,
            )
        except Exception as error:
            emit_report(
                build_report(
                    script="run_bull_put_recovery_drill.py",
                    workflow="bull-put-recovery-drill",
                    status="failed",
                    mode=args.mode,
                    target=base_url,
                    summary="Bull put recovery drill failed.",
                    error=str(error),
                    payload={"account_id": args.account_id, "post_endpoint_called": False},
                ),
                json_output=args.json_output,
            )
            raise SystemExit(1)


if __name__ == "__main__":
    main()

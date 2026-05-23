from __future__ import annotations

import argparse
import json
from typing import Any

import httpx
from regression_common import build_report, emit_report

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"
DEFAULT_SYMBOLS = ("QQQ.US", "SMH.US", "SOXL.US", "EWY.US")


class SmokeError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only bull put smoke against the local API using the real Longbridge paper account. "
            "By default this only fetches runtime state and strategy previews. Use --execute to place the first eligible spread."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=list(DEFAULT_SYMBOLS),
        help="Configured bull put symbols to preview.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help="HTTP timeout for local API requests.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually submit the first eligible bull put spread through the local API.",
    )
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
    raise SmokeError(detail)


def preview_symbol(client: httpx.Client, account_id: str, symbol: str) -> dict[str, Any]:
    response = client.get(
        "/strategies/bull-put/preview",
        params={
            "external_account_id": account_id,
            "symbol": symbol,
            "mode": "paper",
        },
    )
    return require_ok(response)


def run_execute(client: httpx.Client, account_id: str, symbol: str) -> dict[str, Any]:
    response = client.post(
        "/strategies/bull-put/execute",
        json={
            "external_account_id": account_id,
            "symbol": symbol,
            "mode": "paper",
            "remark": "bull-put-real-paper-smoke",
        },
    )
    return require_ok(response)


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    symbols = [symbol.strip().upper() for symbol in args.symbols if symbol.strip()]
    if not symbols:
        raise SmokeError("At least one symbol is required for the bull put smoke preview.")

    client = httpx.Client(base_url=base_url, timeout=args.timeout_seconds)
    try:
        try:
            health = require_ok(client.get("/health"))
            runtime = require_ok(
                client.get(
                    "/strategies/bull-put/runtime",
                    params={"external_account_id": args.account_id, "mode": "paper"},
                )
            )
            previews = [preview_symbol(client, args.account_id, symbol) for symbol in symbols]
            eligible = [preview for preview in previews if preview.get("eligible")]

            if not args.execute:
                emit_report(
                    build_report(
                        script="run_bull_put_real_paper_smoke.py",
                        workflow="bull-put-real-paper-smoke",
                        status="passed",
                        mode="dry-run",
                        target=base_url,
                        summary="Real bull put preview smoke completed without placing option orders.",
                        payload={
                            "health": health,
                            "runtime": {
                                "auto_entry_enabled": runtime.get("auto_entry_enabled"),
                                "manual_pause": runtime.get("manual_pause"),
                                "kill_switch_active": runtime.get("kill_switch_active"),
                                "last_scan_result": runtime.get("last_scan_result"),
                                "last_review_status": runtime.get("last_review_status"),
                            },
                            "eligible_symbols": [preview["symbol"] for preview in eligible],
                            "previews": [
                                {
                                    "symbol": preview["symbol"],
                                    "eligible": preview["eligible"],
                                    "reason": preview["reasons"][0] if preview.get("reasons") else None,
                                    "selected_expiration_date": preview.get("selected_expiration_date"),
                                    "days_to_expiration": preview.get("days_to_expiration"),
                                    "entry_credit": (
                                        preview.get("candidate", {}).get("conservative_credit")
                                        if preview.get("candidate")
                                        else None
                                    ),
                                }
                                for preview in previews
                            ],
                        },
                    ),
                    json_output=args.json_output,
                )
                return

            if not eligible:
                emit_report(
                    build_report(
                        script="run_bull_put_real_paper_smoke.py",
                        workflow="bull-put-real-paper-smoke",
                        status="skipped",
                        mode="executed",
                        target=base_url,
                        summary="No eligible bull put preview was available, so no option order was submitted.",
                        payload={
                            "health": health,
                            "eligible_symbols": [],
                            "previews": previews,
                        },
                    ),
                    json_output=args.json_output,
                )
                return

            selected = eligible[0]
            spread = run_execute(client, args.account_id, selected["symbol"])
            emit_report(
                build_report(
                    script="run_bull_put_real_paper_smoke.py",
                    workflow="bull-put-real-paper-smoke",
                    status="passed",
                    mode="executed",
                    target=base_url,
                    summary=f"Real bull put paper execute smoke submitted {selected['symbol']}.",
                    payload={
                        "selected_symbol": selected["symbol"],
                        "preview": selected,
                        "spread": {
                            "id": spread["id"],
                            "status": spread["status"],
                            "underlying_symbol": spread["underlying_symbol"],
                            "entry_net_credit": spread.get("entry_net_credit"),
                            "long_symbol": spread["long_symbol"],
                            "short_symbol": spread["short_symbol"],
                        },
                    },
                ),
                json_output=args.json_output,
            )
        except Exception as error:
            emit_report(
                build_report(
                    script="run_bull_put_real_paper_smoke.py",
                    workflow="bull-put-real-paper-smoke",
                    status="failed",
                    mode="executed" if args.execute else "dry-run",
                    target=base_url,
                    summary="Real bull put smoke failed.",
                    error=str(error),
                    payload={"symbols": symbols, "account_id": args.account_id},
                ),
                json_output=args.json_output,
            )
            raise SystemExit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import sys
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"
PRICE_CENTS = Decimal("0.01")


class SmokeError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Submit, replace, and cancel a real Longbridge paper order through the local API. "
            "Use --execute to actually send the paper order."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument("--symbol", default="UNH.US", help="Broker-native symbol to trade.")
    parser.add_argument("--quantity", type=int, default=1, help="Initial order quantity.")
    parser.add_argument("--replace-quantity", type=int, default=2, help="Replacement order quantity.")
    parser.add_argument(
        "--discount-factor",
        type=Decimal,
        default=Decimal("0.75"),
        help="Factor applied to the last price to keep the initial buy limit far from market.",
    )
    parser.add_argument(
        "--replace-step",
        type=Decimal,
        default=Decimal("1.00"),
        help="Absolute price increment added during replace.",
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Polling interval between refresh calls.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0, help="HTTP timeout and step deadline.")
    parser.add_argument(
        "--remark-prefix",
        default="paper-smoke",
        help="Prefix for submit and replace remarks so the resulting order is easy to identify.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the paper order workflow. Without this flag the script only prints the plan.",
    )
    return parser.parse_args()


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def quantize_price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_CENTS, rounding=ROUND_DOWN)


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


def fetch_quote(client: httpx.Client, symbol: str) -> dict[str, Any]:
    response = client.get("/brokers/longbridge/quote", params={"symbol": symbol, "mode": "paper"})
    return require_ok(response)


def get_order(client: httpx.Client, order_id: str) -> dict[str, Any]:
    response = client.get(f"/orders/{order_id}")
    return require_ok(response)


def refresh_order(client: httpx.Client, order_id: str) -> dict[str, Any]:
    response = client.post(f"/orders/{order_id}/refresh")
    return require_ok(response)


def replace_order(client: httpx.Client, order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(f"/orders/{order_id}/replace", json=payload)
    return require_ok(response)


def cancel_order(client: httpx.Client, order_id: str) -> dict[str, Any]:
    response = client.post(f"/orders/{order_id}/cancel")
    return require_ok(response)


def wait_for(
    client: httpx.Client,
    order_id: str,
    *,
    timeout_seconds: float,
    poll_seconds: float,
    predicate,
    label: str,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_order: dict[str, Any] | None = None
    while time.time() < deadline:
        last_order = refresh_order(client, order_id)
        if predicate(last_order):
            return last_order
        time.sleep(poll_seconds)
    raise SmokeError(f"Timed out waiting for {label}. Last order state: {json.dumps(last_order, ensure_ascii=False)}")


def is_working_status(status_value: str) -> bool:
    return status_value in {"created", "submitted", "partially_filled"}


def main() -> None:
    args = parse_args()
    base_url = normalize_base_url(args.base_url)
    client = httpx.Client(base_url=base_url, timeout=args.timeout_seconds)
    created_order_id: str | None = None

    try:
        quote = fetch_quote(client, args.symbol)
        last_done = Decimal(str(quote["last_done"]))
        submit_price = quantize_price(last_done * args.discount_factor)
        replace_price = quantize_price(submit_price + args.replace_step)
        timestamp = int(time.time())
        submit_remark = f"{args.remark_prefix}-submit-{timestamp}"
        replace_remark = f"{args.remark_prefix}-replace-{timestamp}"
        plan = {
            "base_url": base_url,
            "account_id": args.account_id,
            "symbol": args.symbol,
            "last_done": str(last_done),
            "submit_quantity": args.quantity,
            "submit_limit_price": str(submit_price),
            "replace_quantity": args.replace_quantity,
            "replace_limit_price": str(replace_price),
            "submit_remark": submit_remark,
            "replace_remark": replace_remark,
        }

        if not args.execute:
            print(json.dumps({"mode": "dry-run", **plan}, indent=2))
            return

        submit_payload = {
            "external_account_id": args.account_id,
            "symbol": args.symbol,
            "side": "buy",
            "quantity": args.quantity,
            "order_type": "limit",
            "time_in_force": "day",
            "mode": "paper",
            "limit_price": float(submit_price),
            "remark": submit_remark,
        }
        created = require_ok(client.post("/orders/submit", json=submit_payload))
        created_order_id = created["id"]

        submitted = wait_for(
            client,
            created_order_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            predicate=lambda order: is_working_status(order["status"]),
            label="submitted order",
        )

        replaced = replace_order(
            client,
            created_order_id,
            {
                "quantity": args.replace_quantity,
                "limit_price": float(replace_price),
                "remark": replace_remark,
            },
        )
        replaced = wait_for(
            client,
            created_order_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            predicate=lambda order: (
                order["quantity"] == args.replace_quantity
                and Decimal(str(order["limit_price"])) == replace_price
                and is_working_status(order["status"])
            ),
            label="replaced order",
        )

        canceled = cancel_order(client, created_order_id)
        canceled = wait_for(
            client,
            created_order_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            predicate=lambda order: order["status"] == "canceled",
            label="canceled order",
        )

        print(
            json.dumps(
                {
                    "mode": "executed",
                    **plan,
                    "local_order_id": created_order_id,
                    "external_order_id": created["external_order_id"],
                    "submitted_status": submitted["status"],
                    "replaced_status": replaced["status"],
                    "canceled_status": canceled["status"],
                    "updated_at": canceled["updated_at"],
                },
                indent=2,
            )
        )
    except Exception as error:
        if created_order_id is not None:
            try:
                latest = get_order(client, created_order_id)
                if is_working_status(latest["status"]):
                    canceled = cancel_order(client, created_order_id)
                    print(
                        json.dumps(
                            {
                                "cleanup": "best-effort cancel applied after failure",
                                "local_order_id": created_order_id,
                                "final_status": canceled["status"],
                            }
                        ),
                        file=sys.stderr,
                    )
            except Exception as cleanup_error:  # pragma: no cover - best effort fallback
                print(f"Cleanup cancel failed for {created_order_id}: {cleanup_error}", file=sys.stderr)
        raise SmokeError(str(error)) from error
    finally:
        client.close()


if __name__ == "__main__":
    main()

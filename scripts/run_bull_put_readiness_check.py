from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"


class ReadinessCheckError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a read-only bull put opening readiness check against a local API session.",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("--mode", default="paper")
    parser.add_argument("--as-of", default=None, help="Optional UTC timestamp, e.g. 2026-05-29T14:45:00Z.")
    parser.add_argument("--json-output", type=Path, default=None)
    return parser.parse_args()


def require_json(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ReadinessCheckError(f"{response.request.method} {response.request.url} returned non-JSON.") from exc
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise ReadinessCheckError(f"{response.request.method} {response.request.url} returned {response.status_code}: {detail}")
    return payload


def summarize(readiness: dict[str, Any]) -> str:
    status = readiness.get("status")
    preferred = readiness.get("preferred_symbol")
    checks = readiness.get("checks") or []
    blocking = [check for check in checks if check.get("blocking")]
    if preferred:
        return f"Bull put readiness is {status}; preferred symbol is {preferred}."
    if blocking:
        return f"Bull put readiness is {status}; first blocker: {blocking[0].get('detail')}"
    return f"Bull put readiness is {status}; no eligible candidate is ready yet."


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    client = httpx.Client(base_url=base_url, timeout=90)
    try:
        try:
            health = require_json(client.get("/health"))
            params = {
                "external_account_id": args.account_id,
                "mode": args.mode,
            }
            if args.as_of:
                params["as_of"] = args.as_of
            readiness = require_json(client.get("/strategies/bull-put/readiness", params=params))
            emit_report(
                build_report(
                    script="run_bull_put_readiness_check.py",
                    workflow="bull-put-readiness-check",
                    status="passed",
                    mode=args.mode,
                    target=base_url,
                    summary=summarize(readiness),
                    payload={
                        "health": health,
                        "readiness": readiness,
                    },
                ),
                json_output=str(args.json_output) if args.json_output else None,
            )
        except Exception as error:
            emit_report(
                build_report(
                    script="run_bull_put_readiness_check.py",
                    workflow="bull-put-readiness-check",
                    status="failed",
                    mode=args.mode,
                    target=base_url,
                    summary="Bull put readiness check failed.",
                    error=str(error),
                    payload={"account_id": args.account_id},
                ),
                json_output=str(args.json_output) if args.json_output else None,
            )
            raise SystemExit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()

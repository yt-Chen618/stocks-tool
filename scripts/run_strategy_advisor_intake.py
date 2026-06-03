from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.adapters.advisors.deepseek import DeepSeekAdvisorClient
from stocks_tool.core.config import Settings
from stocks_tool.domain.models import StrategyAdvisorContext

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"


class AdvisorIntakeError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch local strategy advisor context and optionally record an advisor response "
            "as read-only proposals or reviews."
        )
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID)
    parser.add_argument("--source", default="deepseek")
    parser.add_argument("--context-limit", type=int, default=10)
    parser.add_argument(
        "--response-json",
        type=Path,
        default=None,
        help="JSON file containing proposals, reviews, and optional raw_response fields.",
    )
    parser.add_argument(
        "--call-deepseek",
        action="store_true",
        help="Call DeepSeek using local .env settings to generate the advisor response payload.",
    )
    parser.add_argument(
        "--deepseek-model",
        default=None,
        help="Optional model override. Defaults to DEEPSEEK_MODEL from .env.",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="POST the advisor response into the local ledger. Without this flag the script is read-only.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--json-output", type=Path, default=None)
    return parser.parse_args()


def require_json(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise AdvisorIntakeError(f"{response.request.method} {response.request.url} returned non-JSON.") from exc
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise AdvisorIntakeError(f"{response.request.method} {response.request.url} returned {response.status_code}: {detail}")
    return payload


def load_response_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdvisorIntakeError(f"{path} does not contain valid JSON.") from exc
    if not isinstance(payload, dict):
        raise AdvisorIntakeError(f"{path} must contain a JSON object.")
    return payload


def build_intake_payload(args: argparse.Namespace) -> dict[str, Any]:
    if args.response_json is None:
        raise AdvisorIntakeError("--record requires --response-json.")
    payload = load_response_payload(args.response_json)
    payload["external_account_id"] = args.account_id
    payload["source"] = args.source
    payload["mode"] = "paper"
    payload["context_limit"] = args.context_limit
    return payload


def build_deepseek_intake_payload(
    args: argparse.Namespace,
    context: dict[str, Any],
) -> dict[str, Any]:
    advisor_context = StrategyAdvisorContext.model_validate(context)
    client = DeepSeekAdvisorClient(settings=Settings())
    payload = client.create_advisor_response(
        context=advisor_context,
        model=args.deepseek_model,
    )
    payload["external_account_id"] = args.account_id
    payload["source"] = args.source
    payload["mode"] = "paper"
    payload["context_limit"] = args.context_limit
    return payload


def summarize_context(context: dict[str, Any]) -> str:
    experiment = context.get("experiment") if isinstance(context, dict) else {}
    proposals = experiment.get("proposals") if isinstance(experiment, dict) else []
    reviews = experiment.get("reviews") if isinstance(experiment, dict) else []
    return f"Advisor context loaded with {len(proposals or [])} proposal(s) and {len(reviews or [])} review(s)."


def summarize_recorded(result: dict[str, Any]) -> str:
    return (
        f"Recorded advisor response with {len(result.get('proposals') or [])} proposal(s) "
        f"and {len(result.get('reviews') or [])} review(s)."
    )


def summarize_generated(payload: dict[str, Any]) -> str:
    return (
        f"Generated advisor response with {len(payload.get('proposals') or [])} proposal(s) "
        f"and {len(payload.get('reviews') or [])} review(s)."
    )


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    client = httpx.Client(base_url=base_url, timeout=args.timeout_seconds)
    try:
        try:
            health = require_json(client.get("/health"))
            context = require_json(
                client.get(
                    "/strategies/advisor-context",
                    params={
                        "external_account_id": args.account_id,
                        "limit": args.context_limit,
                    },
                )
            )
            if args.call_deepseek and args.response_json is not None:
                raise AdvisorIntakeError("Use either --call-deepseek or --response-json, not both.")
            if args.record and not args.call_deepseek and args.response_json is None:
                raise AdvisorIntakeError("--record requires --call-deepseek or --response-json.")
            if args.call_deepseek:
                intake_payload = build_deepseek_intake_payload(args, context)
            else:
                intake_payload = build_intake_payload(args) if args.response_json is not None else None
            intake_result = None
            if args.record:
                intake_result = require_json(client.post("/strategies/advisor/responses", json=intake_payload))

            if intake_result is not None:
                summary = summarize_recorded(intake_result)
            elif intake_payload is not None:
                summary = summarize_generated(intake_payload)
            else:
                summary = summarize_context(context)
            emit_report(
                build_report(
                    script="run_strategy_advisor_intake.py",
                    workflow="strategy-advisor-intake",
                    status="passed",
                    mode="paper",
                    target=base_url,
                    summary=summary,
                    payload={
                        "health": health,
                        "context": {
                            "external_account_id": context.get("external_account_id"),
                            "advisor_sources": context.get("advisor_sources"),
                            "hard_rules": context.get("hard_rules"),
                        },
                        "recorded": intake_result is not None,
                        "intake_result": intake_result,
                        "dry_run_payload": intake_payload if intake_result is None else None,
                    },
                ),
                json_output=str(args.json_output) if args.json_output else None,
            )
        except Exception as error:
            emit_report(
                build_report(
                    script="run_strategy_advisor_intake.py",
                    workflow="strategy-advisor-intake",
                    status="failed",
                    mode="paper",
                    target=base_url,
                    summary="Strategy advisor intake check failed.",
                    error=str(error),
                    payload={"account_id": args.account_id, "source": args.source},
                ),
                json_output=str(args.json_output) if args.json_output else None,
            )
            raise SystemExit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()

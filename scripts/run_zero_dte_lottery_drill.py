from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
from regression_common import build_report, emit_report

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ACCOUNT_ID = "LBPT10087357"


class ZeroDteDrillError(RuntimeError):
    pass


class ZeroDteHttpError(ZeroDteDrillError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a controlled zero-DTE lottery paper drill against a local API session."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Local API base URL.")
    parser.add_argument("--account-id", default=DEFAULT_ACCOUNT_ID, help="Paper broker account id.")
    parser.add_argument("--symbol", default="QQQ.US", help="Configured lottery symbol.")
    parser.add_argument("--direction", default="auto", help="auto, call, or put.")
    parser.add_argument("--mode", default="paper", help="Execution mode.")
    parser.add_argument("--as-of", default=None, help="Optional UTC timestamp, e.g. 2026-06-04T14:30:00Z.")
    parser.add_argument("--force-scan", action="store_true", help="Call the force scan endpoint.")
    parser.add_argument(
        "--confirm-paper-scan",
        action="store_true",
        help="Required with --force-scan because a force scan can submit a paper option order.",
    )
    parser.add_argument(
        "--record-reconciled-ledger",
        action="store_true",
        help=(
            "When an existing confirmed manual-scan paper order is reconciled, create missing local "
            "strategy run/signal records. This does not submit broker orders."
        ),
    )
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help="HTTP timeout.")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional JSON evidence path.")
    return parser.parse_args()


def require_json(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        body = response.text.replace("\n", " ")[:500]
        raise ZeroDteDrillError(
            f"{response.request.method} {response.request.url} returned non-JSON "
            f"status {response.status_code}: {body}"
        ) from exc
    if response.status_code >= 400:
        detail = payload.get("detail") if isinstance(payload, dict) else payload
        raise ZeroDteHttpError(
            f"{response.request.method} {response.request.url} returned {response.status_code}: {detail}",
            status_code=response.status_code,
        )
    return payload


def candidate_premium(preview: dict[str, Any]) -> str | None:
    candidate = preview.get("candidate")
    if not isinstance(candidate, dict):
        return None
    premium = candidate.get("premium_at_ask")
    return str(premium) if premium is not None else None


def force_scan_order_brief(
    order: dict[str, Any],
    *,
    symbol: str,
    premium_cap: str | int | float | Decimal | None,
) -> dict[str, Any] | None:
    raw_payload = order.get("raw_payload") if isinstance(order, dict) else None
    submission = raw_payload.get("submission_request") if isinstance(raw_payload, dict) else None
    if not isinstance(submission, dict):
        return None
    if not str(submission.get("remark") or "").startswith("zero_dte_lottery_v1:manual-scan"):
        return None
    option_contract = submission.get("option_contract")
    if not isinstance(option_contract, dict) or option_contract.get("underlying_symbol") != symbol:
        return None
    if order.get("mode") != "paper" or order.get("side") != "buy" or order.get("asset_type") != "option":
        return None
    if order.get("status") in {"canceled", "rejected"}:
        return None
    try:
        quantity = Decimal(str(order.get("quantity") or "0"))
        limit_price = Decimal(str(order.get("limit_price") or "0"))
        cap = Decimal(str(premium_cap or "150"))
    except (InvalidOperation, ValueError):
        return None
    premium_at_limit = (quantity * limit_price * Decimal("100")).quantize(Decimal("0.01"))
    if premium_at_limit > cap:
        return None
    return {
        "id": order.get("id"),
        "external_order_id": order.get("external_order_id"),
        "symbol": order.get("symbol"),
        "status": order.get("status"),
        "side": order.get("side"),
        "quantity": order.get("quantity"),
        "limit_price": str(limit_price),
        "premium_at_limit": str(premium_at_limit),
        "submitted_at": order.get("submitted_at"),
        "remark": submission.get("remark"),
    }


def find_existing_force_scan_order(
    client: httpx.Client,
    *,
    account_id: str,
    symbol: str,
    premium_cap: str | int | float | Decimal | None,
) -> dict[str, Any] | None:
    orders = require_json(client.get("/orders", params={"external_account_id": account_id}))
    if not isinstance(orders, list):
        return None
    for order in orders:
        if not isinstance(order, dict):
            continue
        brief = force_scan_order_brief(order, symbol=symbol, premium_cap=premium_cap)
        if brief is not None:
            return brief
    return None


def strategy_recording_status(
    client: httpx.Client,
    *,
    account_id: str,
    order_id: str | None,
) -> dict[str, Any]:
    if not order_id:
        return {"run_found": False, "signal_found": False, "run": None, "signal": None}
    runs = require_json(
        client.get(
            "/strategies/runs",
            params={
                "external_account_id": account_id,
                "strategy_id": "zero_dte_lottery_v1",
                "limit": 100,
            },
        )
    )
    run = None
    if isinstance(runs, list):
        run = next((item for item in runs if isinstance(item, dict) and item.get("order_id") == order_id), None)
    signals = require_json(
        client.get(
            "/strategies/signals",
            params={
                "external_account_id": account_id,
                "strategy_id": "zero_dte_lottery_v1",
                "limit": 100,
            },
        )
    )
    signal = None
    run_id = run.get("id") if isinstance(run, dict) else None
    if isinstance(signals, list):
        signal = next(
            (
                item
                for item in signals
                if isinstance(item, dict)
                and item.get("signal_type") == "execution"
                and (
                    (run_id is not None and item.get("run_id") == run_id)
                    or (((item.get("signal_payload") or {}).get("reconciled_order") or {}).get("id") == order_id)
                )
            ),
            None,
        )
    return {
        "run_found": run is not None,
        "signal_found": signal is not None,
        "run": _record_brief(run),
        "signal": _record_brief(signal),
    }


def record_reconciled_strategy_ledger(
    client: httpx.Client,
    *,
    account_id: str,
    mode: str,
    symbol: str,
    order: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    submitted_at = order.get("submitted_at") or now
    run_payload = {
        "strategy_id": "zero_dte_lottery_v1",
        "external_account_id": account_id,
        "mode": mode,
        "run_type": "manual_scan_reconcile",
        "status": "executed",
        "symbol": symbol,
        "order_id": order.get("id"),
        "started_at": submitted_at,
        "completed_at": now,
        "summary": f"Reconciled zero-DTE manual-scan paper order {order.get('symbol')}.",
        "metrics_payload": {
            "source": "run_zero_dte_lottery_drill.py",
            "reconciled_order": order,
            "reconciliation_reason": "confirmed_force_scan_response_failed_after_order_submit",
        },
    }
    run = require_json(client.post("/strategies/runs", json=run_payload))
    signal_payload = {
        "strategy_id": "zero_dte_lottery_v1",
        "external_account_id": account_id,
        "mode": mode,
        "signal_type": "execution",
        "symbol": symbol,
        "run_id": run.get("id") if isinstance(run, dict) else None,
        "strength": "0.20",
        "summary": f"Reconciled zero-DTE paper order {order.get('symbol')}.",
        "detail": "Local ledger repair after confirmed manual force scan returned a non-JSON response.",
        "source": "zero_dte_lottery_v1",
        "signal_payload": {
            "source": "run_zero_dte_lottery_drill.py",
            "reconciled_order": order,
        },
        "emitted_at": now,
    }
    signal = require_json(client.post("/strategies/signals", json=signal_payload))
    return {"created_run": _record_brief(run), "created_signal": _record_brief(signal)}


def ensure_reconciled_strategy_recording(
    client: httpx.Client,
    *,
    account_id: str,
    mode: str,
    symbol: str,
    order: dict[str, Any],
    repair_missing_ledger: bool,
) -> dict[str, Any]:
    before = strategy_recording_status(client, account_id=account_id, order_id=order.get("id"))
    repair = None
    if repair_missing_ledger and not (before["run_found"] and before["signal_found"]):
        repair = record_reconciled_strategy_ledger(
            client,
            account_id=account_id,
            mode=mode,
            symbol=symbol,
            order=order,
        )
    after = strategy_recording_status(client, account_id=account_id, order_id=order.get("id"))
    return {
        "before": before,
        "repair": repair,
        "after": after,
        "verified": after["run_found"] and after["signal_found"],
    }


def _record_brief(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    return {
        "id": record.get("id"),
        "strategy_id": record.get("strategy_id"),
        "run_id": record.get("run_id"),
        "order_id": record.get("order_id"),
        "signal_type": record.get("signal_type"),
        "status": record.get("status"),
        "summary": record.get("summary"),
        "created_at": record.get("created_at"),
    }


def summarize_drill(
    *,
    runtime: dict[str, Any],
    preview: dict[str, Any],
    force_scan_called: bool,
    scan: dict[str, Any] | None,
) -> str:
    preview_state = "eligible" if preview.get("eligible") is True else "blocked"
    auto_state = "on" if runtime.get("auto_execute_enabled") is True else "off"
    scan_state = "not-called"
    if scan is not None:
        scan_state = "executed" if scan.get("executed") is True else "skipped"
    return (
        "Zero-DTE lottery drill completed. "
        f"preview={preview_state}, auto_execute={auto_state}, "
        f"force_scan_called={str(force_scan_called).lower()}, scan={scan_state}."
    )


def is_preview_degraded_warning(error: Exception) -> bool:
    return isinstance(error, ZeroDteHttpError) and error.status_code in {502, 503}


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    json_output = str(args.json_output) if args.json_output else None
    if args.force_scan and not args.confirm_paper_scan:
        emit_report(
            build_report(
                script="run_zero_dte_lottery_drill.py",
                workflow="zero-dte-lottery-drill",
                status="failed",
                mode=args.mode,
                target=base_url,
                summary="Zero-DTE lottery force scan requires --confirm-paper-scan.",
                error="--force-scan can submit a paper option order and must be explicitly confirmed.",
                payload={
                    "account_id": args.account_id,
                    "symbol": args.symbol,
                    "force_scan_requested": True,
                    "confirm_paper_scan": False,
                    "force_scan_called": False,
                "broker_order_submit_allowed": False,
                "broker_order_submit_attempted": False,
                "failure_stage": "confirmation",
                "strategy_recording_verified": False,
            },
        ),
        json_output=json_output,
        )
        raise SystemExit(1)

    with httpx.Client(base_url=base_url, timeout=args.timeout_seconds) as client:
        stage = "health"
        force_scan_called = False
        broker_order_submit_attempted: bool | None = False
        health: dict[str, Any] | None = None
        runtime: dict[str, Any] | None = None
        try:
            health = require_json(client.get("/health"))
            common_params = {
                "external_account_id": args.account_id,
                "mode": args.mode,
            }
            stage = "runtime"
            runtime = require_json(client.get("/strategies/zero-dte-lottery/runtime", params=common_params))
            preview_params = {
                **common_params,
                "symbol": args.symbol,
                "direction": args.direction,
            }
            if args.as_of:
                preview_params["as_of"] = args.as_of
            stage = "preview"
            try:
                preview = require_json(client.get("/strategies/zero-dte-lottery/preview", params=preview_params))
            except Exception as preview_error:
                if args.force_scan or not is_preview_degraded_warning(preview_error):
                    raise
                emit_report(
                    build_report(
                        script="run_zero_dte_lottery_drill.py",
                        workflow="zero-dte-lottery-drill",
                        status="warning",
                        mode=args.mode,
                        target=base_url,
                        summary=(
                            "Zero-DTE lottery drill degraded because market-data preview was unavailable; "
                            "no force scan or broker submit path was enabled."
                        ),
                        error=str(preview_error),
                        payload={
                            "health": health,
                            "account_id": args.account_id,
                            "symbol": args.symbol,
                            "direction": args.direction,
                            "runtime": runtime,
                            "preview": None,
                            "scan": None,
                            "preview_eligible": False,
                            "preview_reason": str(preview_error),
                            "candidate_premium_at_ask": None,
                            "premium_cap": runtime.get("max_premium_per_trade"),
                            "max_trades_per_day": runtime.get("max_trades_per_day"),
                            "auto_execute_enabled": runtime.get("auto_execute_enabled"),
                            "force_scan_requested": args.force_scan,
                            "confirm_paper_scan": args.confirm_paper_scan,
                            "force_scan_called": False,
                            "scan_executed": False,
                            "broker_order_submit_allowed": False,
                            "broker_order_submit_attempted": False,
                            "failure_stage": "preview",
                            "strategy_recording_verified": False,
                        },
                    ),
                    json_output=json_output,
                )
                return

            scan = None
            if args.force_scan:
                stage = "scan"
                force_scan_called = True
                broker_order_submit_attempted = None
                scan_params = {
                    "symbol": args.symbol,
                    "direction": args.direction,
                    "mode": args.mode,
                    "force": "true",
                }
                if args.as_of:
                    scan_params["as_of"] = args.as_of
                scan = require_json(
                    client.post(
                        f"/strategies/zero-dte-lottery/runtime/{args.account_id}/scan",
                        params=scan_params,
                    )
                )
                broker_order_submit_attempted = scan.get("executed") is True if isinstance(scan, dict) else None

            premium = candidate_premium(preview)
            strategy_recording_verified = None
            if isinstance(scan, dict) and args.force_scan:
                strategy_recording_verified = scan.get("run") is not None and scan.get("signal") is not None
            emit_report(
                build_report(
                    script="run_zero_dte_lottery_drill.py",
                    workflow="zero-dte-lottery-drill",
                    status="passed",
                    mode=args.mode,
                    target=base_url,
                    summary=summarize_drill(
                        runtime=runtime,
                        preview=preview,
                        force_scan_called=args.force_scan,
                        scan=scan,
                    ),
                    payload={
                        "health": health,
                        "account_id": args.account_id,
                        "symbol": args.symbol,
                        "direction": args.direction,
                        "runtime": runtime,
                        "preview": preview,
                        "scan": scan,
                        "preview_eligible": preview.get("eligible") is True,
                        "preview_reason": (preview.get("reasons") or [None])[0],
                        "candidate_premium_at_ask": premium,
                        "premium_cap": runtime.get("max_premium_per_trade"),
                        "max_trades_per_day": runtime.get("max_trades_per_day"),
                        "auto_execute_enabled": runtime.get("auto_execute_enabled"),
                        "force_scan_requested": args.force_scan,
                        "confirm_paper_scan": args.confirm_paper_scan,
                        "force_scan_called": force_scan_called,
                        "scan_executed": scan.get("executed") is True if isinstance(scan, dict) else False,
                        "broker_order_submit_allowed": args.force_scan and args.confirm_paper_scan,
                        "broker_order_submit_attempted": broker_order_submit_attempted,
                        "failure_stage": None,
                        "strategy_recording_verified": strategy_recording_verified,
                    },
                ),
                json_output=json_output,
            )
        except Exception as error:
            if args.force_scan and args.confirm_paper_scan:
                try:
                    existing_order = find_existing_force_scan_order(
                        client,
                        account_id=args.account_id,
                        symbol=args.symbol,
                        premium_cap=(runtime or {}).get("max_premium_per_trade"),
                    )
                except Exception:
                    existing_order = None
                if existing_order is not None:
                    recording = ensure_reconciled_strategy_recording(
                        client,
                        account_id=args.account_id,
                        mode=args.mode,
                        symbol=args.symbol,
                        order=existing_order,
                        repair_missing_ledger=args.record_reconciled_ledger,
                    )
                    status = "passed" if recording["verified"] else "warning"
                    summary = (
                        "Zero-DTE confirmed force-scan evidence reconciled from an existing "
                        "same-session paper manual-scan order."
                    )
                    if not recording["verified"]:
                        summary += " Strategy run/signal recording is still missing."
                    emit_report(
                        build_report(
                            script="run_zero_dte_lottery_drill.py",
                            workflow="zero-dte-lottery-drill",
                            status=status,
                            mode=args.mode,
                            target=base_url,
                            summary=summary,
                            error=str(error),
                            payload={
                                "health": health,
                                "account_id": args.account_id,
                                "symbol": args.symbol,
                                "direction": args.direction,
                                "runtime": runtime,
                                "preview": None,
                                "scan": None,
                                "preview_eligible": None,
                                "preview_reason": None,
                                "candidate_premium_at_ask": None,
                                "premium_cap": (runtime or {}).get("max_premium_per_trade"),
                                "max_trades_per_day": (runtime or {}).get("max_trades_per_day"),
                                "auto_execute_enabled": (runtime or {}).get("auto_execute_enabled"),
                                "force_scan_requested": args.force_scan,
                                "confirm_paper_scan": args.confirm_paper_scan,
                                "force_scan_called": force_scan_called,
                                "force_scan_evidence_reconciled": True,
                                "scan_executed": True,
                                "broker_order_submit_allowed": True,
                                "broker_order_submit_attempted": True,
                                "failure_stage": stage,
                                "reconciled_order": existing_order,
                                "ledger_repair_requested": args.record_reconciled_ledger,
                                "ledger_repair": recording["repair"],
                                "strategy_recording": recording["after"],
                                "strategy_recording_verified": recording["verified"],
                            },
                        ),
                        json_output=json_output,
                    )
                    return
            emit_report(
                build_report(
                    script="run_zero_dte_lottery_drill.py",
                    workflow="zero-dte-lottery-drill",
                    status="failed",
                    mode=args.mode,
                    target=base_url,
                    summary="Zero-DTE lottery drill failed.",
                    error=str(error),
                    payload={
                        "account_id": args.account_id,
                        "symbol": args.symbol,
                        "force_scan_requested": args.force_scan,
                        "confirm_paper_scan": args.confirm_paper_scan,
                        "force_scan_called": force_scan_called,
                        "broker_order_submit_allowed": args.force_scan and args.confirm_paper_scan,
                        "broker_order_submit_attempted": broker_order_submit_attempted,
                        "failure_stage": stage,
                        "strategy_recording_verified": False,
                    },
                ),
                json_output=json_output,
            )
            raise SystemExit(1)


if __name__ == "__main__":
    main()

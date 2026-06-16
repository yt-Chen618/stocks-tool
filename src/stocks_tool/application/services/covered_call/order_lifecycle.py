from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from stocks_tool.domain.models import CoveredCallCandidate, CreateOrderRequest, OptionContractRef, Order


def order_timing_payload(order: Order, *, prefix: str = "order") -> dict[str, str | None]:
    return {
        f"{prefix}_submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        f"{prefix}_updated_at": order.updated_at.isoformat() if order.updated_at else None,
    }


def build_order_request(
    *,
    external_account_id: str,
    mode: ExecutionMode,
    candidate: CoveredCallCandidate,
    side: OrderSide,
    limit_price: Decimal,
    remark: str,
) -> CreateOrderRequest:
    return CreateOrderRequest(
        external_account_id=external_account_id,
        broker=BrokerName.LONGBRIDGE,
        symbol=candidate.call_symbol,
        asset_type=AssetType.OPTION,
        side=side,
        quantity=candidate.contracts,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=mode,
        limit_price=limit_price,
        option_contract=OptionContractRef(
            underlying_symbol=candidate.underlying_symbol,
            expiration_date=candidate.expiration_date,
            strike=candidate.call_strike,
            right=OptionRight.CALL,
        ),
        remark=remark,
    )


def validate_roll_buyback_order(
    *,
    buyback_order: Order,
    proposal,
    roll_from: CoveredCallCandidate,
) -> None:
    if buyback_order.external_account_id != proposal.external_account_id:
        raise ValueError("Roll buyback order belongs to a different account.")
    if buyback_order.mode != proposal.mode:
        raise ValueError("Roll buyback order mode does not match the proposal.")
    if buyback_order.symbol != roll_from.call_symbol:
        raise ValueError("Roll buyback order does not match the current short call symbol.")
    if buyback_order.side != OrderSide.BUY:
        raise ValueError("Roll buyback order must be a buy-to-close order.")


def validate_roll_sell_order(
    *,
    sell_order: Order,
    proposal,
    roll_to: CoveredCallCandidate,
) -> None:
    if sell_order.external_account_id != proposal.external_account_id:
        raise ValueError("Roll sell order belongs to a different account.")
    if sell_order.mode != proposal.mode:
        raise ValueError("Roll sell order mode does not match the proposal.")
    if sell_order.symbol != roll_to.call_symbol:
        raise ValueError("Roll sell order does not match the new short call symbol.")
    if sell_order.side != OrderSide.SELL:
        raise ValueError("Roll sell order must be a sell-to-open order.")


def validate_open_sell_order(
    *,
    sell_order: Order,
    proposal,
    candidate: CoveredCallCandidate,
) -> None:
    if sell_order.external_account_id != proposal.external_account_id:
        raise ValueError("Covered call sell order belongs to a different account.")
    if sell_order.mode != proposal.mode:
        raise ValueError("Covered call sell order mode does not match the proposal.")
    if sell_order.symbol != candidate.call_symbol:
        raise ValueError("Covered call sell order does not match the proposed short call symbol.")
    if sell_order.side != OrderSide.SELL:
        raise ValueError("Covered call sell order must be a sell-to-open order.")


def validate_close_order(
    *,
    close_order: Order,
    proposal,
    candidate: CoveredCallCandidate,
) -> None:
    if close_order.external_account_id != proposal.external_account_id:
        raise ValueError("Covered call close order belongs to a different account.")
    if close_order.mode != proposal.mode:
        raise ValueError("Covered call close order mode does not match the proposal.")
    if close_order.symbol != candidate.call_symbol:
        raise ValueError("Covered call close order does not match the current short call symbol.")
    if close_order.side != OrderSide.BUY:
        raise ValueError("Covered call close order must be a buy-to-close order.")


def order_filled(order: Order | None) -> bool:
    return order is not None and order.status == OrderStatus.FILLED


def latest_runs_by_proposal(runs: list[object], run_types: set[str]) -> dict[str, object]:
    latest: dict[str, object] = {}
    for run in runs:
        proposal_id = getattr(run, "proposal_id", None)
        run_type = getattr(run, "run_type", None)
        if not proposal_id or run_type not in run_types or proposal_id in latest:
            continue
        latest[proposal_id] = run
    return latest


def optional_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def reference_time(as_of: datetime | None) -> datetime:
    reference = as_of or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        return reference.replace(tzinfo=timezone.utc)
    return reference


def normalize_symbol(symbol: str | None) -> str:
    if symbol is None:
        return ""
    return symbol.strip().upper()

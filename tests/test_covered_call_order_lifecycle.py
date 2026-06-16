from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from stocks_tool.application.services.covered_call.order_lifecycle import (
    build_order_request,
    latest_runs_by_proposal,
    normalize_symbol,
    optional_decimal,
    order_filled,
    reference_time,
    validate_close_order,
    validate_open_sell_order,
    validate_roll_buyback_order,
)
from stocks_tool.domain.enums import AssetType, BrokerName, ExecutionMode, OrderSide, OrderStatus, OrderType, TimeInForce
from stocks_tool.domain.models import CoveredCallCandidate, Order


NOW = datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc)


def _candidate(**updates) -> CoveredCallCandidate:
    base = CoveredCallCandidate(
        underlying_symbol="UNH.US",
        expiration_date=date(2026, 7, 17),
        days_to_expiration=32,
        contracts=1,
        covered_shares=100,
        share_quantity=Decimal("150"),
        average_cost=Decimal("410"),
        underlying_price=Decimal("415"),
        call_symbol="UNH260717C430000.US",
        call_strike=Decimal("430"),
        call_bid=Decimal("4.00"),
        call_ask=Decimal("4.20"),
        call_mid=Decimal("4.10"),
        premium_income=Decimal("400.00"),
        quote_timestamp=NOW,
    )
    return base.model_copy(update=updates)


def _proposal(**updates):
    data = {
        "external_account_id": "LBPT10087357",
        "mode": ExecutionMode.PAPER,
    }
    data.update(updates)
    return SimpleNamespace(**data)


def _order(**updates) -> Order:
    base = Order(
        id="order-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        symbol="UNH260717C430000.US",
        asset_type=AssetType.OPTION,
        side=OrderSide.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.SUBMITTED,
        limit_price=Decimal("4.00"),
        created_at=NOW,
        updated_at=NOW,
    )
    return base.model_copy(update=updates)


def test_build_order_request_matches_candidate_contract() -> None:
    request = build_order_request(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        candidate=_candidate(),
        side=OrderSide.SELL,
        limit_price=Decimal("4.00"),
        remark="covered-call",
    )

    assert request.broker == BrokerName.LONGBRIDGE
    assert request.symbol == "UNH260717C430000.US"
    assert request.side == OrderSide.SELL
    assert request.quantity == 1
    assert request.option_contract is not None
    assert request.option_contract.strike == Decimal("430")
    assert request.remark == "covered-call"


def test_order_validation_rejects_mismatched_symbol_and_side() -> None:
    with pytest.raises(ValueError, match="proposed short call"):
        validate_open_sell_order(
            sell_order=_order(symbol="OTHER.US"),
            proposal=_proposal(),
            candidate=_candidate(),
        )

    with pytest.raises(ValueError, match="buy-to-close"):
        validate_roll_buyback_order(
            buyback_order=_order(side=OrderSide.SELL),
            proposal=_proposal(),
            roll_from=_candidate(),
        )

    with pytest.raises(ValueError, match="buy-to-close"):
        validate_close_order(
            close_order=_order(side=OrderSide.SELL),
            proposal=_proposal(),
            candidate=_candidate(),
        )


def test_small_lifecycle_helpers_are_stable() -> None:
    assert order_filled(_order(status=OrderStatus.FILLED)) is True
    assert order_filled(_order(status=OrderStatus.SUBMITTED)) is False
    assert optional_decimal("1.23") == Decimal("1.23")
    assert optional_decimal(object()) is None
    assert normalize_symbol(" unh.us ") == "UNH.US"
    assert reference_time(datetime(2026, 6, 15, 14, 45)).tzinfo == timezone.utc

    newer = SimpleNamespace(proposal_id="proposal-1", run_type="proposal_execution")
    older_duplicate = SimpleNamespace(proposal_id="proposal-1", run_type="proposal_execution")
    ignored = SimpleNamespace(proposal_id="proposal-2", run_type="other")
    assert latest_runs_by_proposal([newer, older_duplicate, ignored], {"proposal_execution"}) == {
        "proposal-1": newer
    }

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from stocks_tool.application.services.covered_call.lifecycle import (
    CloseAuthorization,
    ContinueRollAuthorization,
    ContinueSellAuthorization,
    CoveredCallLifecycle,
    OpenAuthorization,
    RollAuthorization,
)
from stocks_tool.domain.enums import ExecutionMode, OrderSide, OrderStatus
from stocks_tool.domain.models import CoveredCallCandidate, StrategyProposal


NOW = datetime(2026, 10, 2, 14, 0, tzinfo=timezone.utc)


def candidate(symbol: str, *, contracts: int = 1) -> CoveredCallCandidate:
    return CoveredCallCandidate(
        underlying_symbol="UNH.US",
        expiration_date=date(2026, 11, 20),
        days_to_expiration=49,
        contracts=contracts,
        covered_shares=contracts * 100,
        share_quantity=Decimal("200"),
        average_cost=Decimal("300"),
        underlying_price=Decimal("320"),
        call_symbol=symbol,
        call_strike=Decimal("330"),
        call_bid=Decimal("2.00"),
        call_ask=Decimal("2.20"),
        call_mid=Decimal("2.10"),
        premium_income=Decimal("200"),
        quote_timestamp=NOW,
    )


def proposal() -> StrategyProposal:
    return StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Covered Call",
        proposed_action="roll_covered_call",
        rationale="test",
        candidate_payload={"roll_from": candidate("UNH261120C330000.US").model_dump(mode="json"), "roll_to": candidate("UNH261218C335000.US").model_dump(mode="json")},
    )


def build_lifecycle(
    policy: Mock,
    orders: Mock,
    recorder: Mock,
    *,
    mark_child_failure: Mock | None = None,
    mark_persistence_failure: Mock | None = None,
) -> CoveredCallLifecycle:
    @contextmanager
    def prebroker(_parent_id):
        yield

    return CoveredCallLifecycle(
        policy=policy,
        orders=orders,
        recorder=recorder,
        prebroker_phase=prebroker,
        mark_child_failure=mark_child_failure or Mock(),
        mark_persistence_failure=mark_persistence_failure or Mock(),
    )


def test_lifecycle_open_preserves_account_mode_and_contract_quantity() -> None:
    current = proposal().model_copy(update={"proposed_action": "sell_covered_call"})
    selected = candidate("UNH261120C330000.US", contracts=2)
    policy = Mock()
    policy.authorize_open.return_value = OpenAuthorization(candidate=selected, limit_price=Decimal("2.00"))
    orders = Mock()
    submitted = SimpleNamespace(id="sell-1", status=OrderStatus.FILLED)
    orders.submit.return_value = submitted
    orders.is_filled.return_value = True
    recorder = Mock()
    expected = object()
    recorder.record_open.return_value = expected

    result = build_lifecycle(policy, orders, recorder).execute_open(
        proposal=current,
        request=SimpleNamespace(remark="test"),
        parent_action_intent_id="parent-1",
    )

    assert result is expected
    call = orders.submit.call_args.kwargs
    assert call["proposal"].external_account_id == "LBPT10087357"
    assert call["proposal"].mode == ExecutionMode.PAPER
    assert call["candidate"].contracts == 2
    assert call["side"] == OrderSide.SELL
    assert call["parent_action_intent_id"] == "parent-1"


@pytest.mark.parametrize("failure", [LookupError("run lookup failed"), ValueError("run payload failed")])
def test_lifecycle_recorder_failure_uses_persistence_failure_seam(failure: Exception) -> None:
    selected = candidate("UNH261120C330000.US")
    policy = Mock()
    policy.authorize_open.return_value = OpenAuthorization(candidate=selected, limit_price=Decimal("2.00"))
    orders = Mock()
    orders.submit.return_value = SimpleNamespace(id="sell-1", status=OrderStatus.FILLED)
    recorder = Mock()
    recorder.record_open.side_effect = failure
    mark_child_failure = Mock()
    mark_persistence_failure = Mock()

    with pytest.raises(type(failure), match=str(failure)):
        build_lifecycle(
            policy,
            orders,
            recorder,
            mark_child_failure=mark_child_failure,
            mark_persistence_failure=mark_persistence_failure,
        ).execute_open(
            proposal=proposal(),
            request=SimpleNamespace(remark="test"),
            parent_action_intent_id="parent-persist-failure",
        )

    orders.submit.assert_called_once()
    mark_child_failure.assert_not_called()
    mark_persistence_failure.assert_called_once_with("parent-persist-failure", failure)


def test_lifecycle_roll_holds_new_sell_until_buyback_fills() -> None:
    current = proposal()
    roll_from = candidate("UNH261120C330000.US")
    roll_to = candidate("UNH261218C335000.US")
    policy = Mock()
    policy.authorize_roll.return_value = RollAuthorization(
        roll_from=roll_from,
        roll_to=roll_to,
        buyback_limit=Decimal("1.00"),
        sell_limit=Decimal("2.00"),
    )
    orders = Mock()
    orders.submit.return_value = SimpleNamespace(id="buyback-1", status=OrderStatus.SUBMITTED)
    orders.is_filled.return_value = False
    recorder = Mock()
    expected = object()
    recorder.record_roll.return_value = expected

    result = build_lifecycle(policy, orders, recorder).execute_roll(
        proposal=current,
        request=SimpleNamespace(remark="roll"),
        parent_action_intent_id="parent-2",
    )

    assert result is expected
    assert orders.submit.call_count == 1
    recorder.record_roll.assert_called_once()
    assert recorder.record_roll.call_args.kwargs["sell_order"] is None
    assert recorder.record_roll.call_args.kwargs["sequence_status"] == "buyback_submitted_waiting_fill"


def test_lifecycle_continue_submits_one_new_sell_after_filled_buyback() -> None:
    current = proposal()
    roll_from = candidate("UNH261120C330000.US")
    roll_to = candidate("UNH261218C335000.US", contracts=2)
    buyback = SimpleNamespace(id="buyback-1", status=OrderStatus.FILLED)
    sell = SimpleNamespace(id="sell-1", status=OrderStatus.FILLED)
    policy = Mock()
    policy.authorize_continue_preflight.return_value = ContinueRollAuthorization(
        roll_from=roll_from,
        roll_to=roll_to,
        buyback_order=buyback,
    )
    policy.authorize_continue_sell.return_value = ContinueSellAuthorization(
        sell_order=None,
        roll_to=roll_to,
        sell_limit=Decimal("2.25"),
    )
    orders = Mock()
    orders.is_filled.return_value = True
    orders.submit.return_value = sell
    recorder = Mock()
    expected = object()
    recorder.record_continue_roll.return_value = expected

    result = build_lifecycle(policy, orders, recorder).continue_roll(
        proposal=current,
        request=SimpleNamespace(buyback_order_id="buyback-1", sell_order_id=None, remark="continue"),
        parent_action_intent_id="parent-3",
    )

    assert result is expected
    assert orders.submit.call_count == 1
    submitted = orders.submit.call_args.kwargs
    assert submitted["candidate"].contracts == 2
    assert submitted["side"] == OrderSide.SELL
    assert recorder.record_continue_roll.call_args.kwargs["buyback_order"] is buyback

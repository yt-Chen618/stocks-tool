from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from stocks_tool.application.services.order_authorization import (
    OrderActionClass,
    OrderAuthorizationError,
    OrderAuthorizationService,
    classify_order_action,
    is_exposure_increasing_replace,
)
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.covered_call_strategy import _CoveredCallLifecyclePolicy
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AccountSnapshotProvenance,
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    OptionRight,
    TimeInForce,
    TradingIntentState,
    TradingOperation,
    StrategyProposalStatus,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    CloseCoveredCallProposalRequest,
    CoveredCallCandidate,
    CreateOrderRequest,
    OptionContractRef,
    Order,
    BrokerOrderIntent,
    BrokerOrderSnapshot,
    PreparedBrokerOrderIntent,
    PositionSnapshot,
    ReplaceOrderRequest,
    SecurityQuoteSnapshot,
    OptionMarketSnapshot,
    TradingActionContext,
    ExecuteCoveredCallProposalRequest,
    ExecuteCoveredCallRollProposalRequest,
    StrategyProposal,
)


NOW = datetime(2026, 10, 4, 14, 30, tzinfo=timezone.utc)


def snapshot(
    *,
    age_seconds: int = 5,
    mode: str | None = "paper",
    buying_power: str = "10000",
    options_level: str | None = "level_2",
    positions: list[PositionSnapshot] | None = None,
) -> AccountSnapshot:
    payload = {"mode": mode} if mode is not None else {}
    return AccountSnapshot(
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        mode=ExecutionMode.PAPER if mode == "paper" else ExecutionMode.LIVE if mode == "live" else None,
        provenance=(
            AccountSnapshotProvenance.BROKER_SYNC
            if mode is not None
            else AccountSnapshotProvenance.LEGACY_UNKNOWN
        ),
        cash_balance=Decimal("10000"),
        net_liquidation=Decimal("10000"),
        buying_power=Decimal(buying_power),
        options_level=options_level,
        positions=positions or [],
        raw_payload=payload,
        captured_at=NOW - timedelta(seconds=age_seconds),
    )


def account_service(current: AccountSnapshot) -> OrderAuthorizationService:
    repository = Mock()
    repository.get_latest_account_snapshot.return_value = current
    market_data = Mock()
    market_data.get_quote.return_value = SecurityQuoteSnapshot(
        symbol="QQQ.US",
        last_done=Decimal("450"),
        prev_close=Decimal("449"),
        open=Decimal("449"),
        high=Decimal("451"),
        low=Decimal("448"),
        timestamp=NOW,
        volume=1000,
        turnover=Decimal("450000"),
        trade_status="normal",
        data_quality="live",
    )
    market_data.get_option_market_snapshots.side_effect = lambda symbols, mode: [
        OptionMarketSnapshot(
            symbol=symbols[0],
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 10, 16),
            strike=Decimal("500"),
            right=OptionRight.CALL,
            last_done=Decimal("1"),
            prev_close=Decimal("1"),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            timestamp=NOW,
            volume=100,
            turnover=Decimal("10000"),
            bid=Decimal("0.90"),
            ask=Decimal("1.10"),
        )
    ]
    return OrderAuthorizationService(
        account_snapshots=repository,
        market_data=market_data,
        max_snapshot_age_seconds=120,
        clock=lambda: NOW,
    )


def stock_buy(*, order_type: OrderType = OrderType.LIMIT, limit_price: str | None = "10") -> CreateOrderRequest:
    return CreateOrderRequest(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        symbol="QQQ.US",
        asset_type=AssetType.ETF,
        side=OrderSide.BUY,
        quantity=10,
        order_type=order_type,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        limit_price=Decimal(limit_price) if limit_price is not None else None,
    )


def option_buy(
    *,
    option_contract: OptionContractRef | None = None,
    symbol: str = "QQQ261016C500000.US",
) -> CreateOrderRequest:
    return CreateOrderRequest(
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        symbol=symbol,
        asset_type=AssetType.OPTION,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        limit_price=Decimal("1.00"),
        option_contract=option_contract,
    )


def test_manual_limit_entry_requires_fresh_mode_scoped_snapshot() -> None:
    authorization = account_service(snapshot())

    evidence = authorization.authorize_manual_entry(request=stock_buy(), evaluated_at=NOW)

    assert evidence.mode == ExecutionMode.PAPER
    assert evidence.age_seconds == 5


@pytest.mark.parametrize(
    ("current", "code"),
    [
        (snapshot(age_seconds=121), "account_snapshot_stale"),
        (snapshot(mode=None), "account_snapshot_mode_unknown"),
        (snapshot(mode="live"), "account_snapshot_mode_mismatch"),
    ],
)
def test_manual_entry_fails_closed_for_stale_or_untrusted_snapshot(
    current: AccountSnapshot,
    code: str,
) -> None:
    with pytest.raises(OrderAuthorizationError) as caught:
        account_service(current).authorize_manual_entry(request=stock_buy(), evaluated_at=NOW)

    assert caught.value.code == code


def test_manual_market_entry_is_rejected_as_unbounded_before_broker() -> None:
    with pytest.raises(OrderAuthorizationError) as caught:
        account_service(snapshot()).authorize_manual_entry(
            request=stock_buy(order_type=OrderType.MARKET, limit_price=None),
            evaluated_at=NOW,
        )

    assert caught.value.code == "manual_entry_unbounded_risk"


def test_future_account_snapshot_is_not_treated_as_fresh() -> None:
    with pytest.raises(OrderAuthorizationError) as caught:
        account_service(snapshot(age_seconds=-1)).authorize_manual_entry(
            request=stock_buy(),
            evaluated_at=NOW,
        )

    assert caught.value.code == "account_snapshot_future"


def test_manual_buy_requires_live_quote_evidence() -> None:
    current = snapshot()
    repository = Mock()
    repository.get_latest_account_snapshot.return_value = current
    market_data = Mock()
    market_data.get_quote.side_effect = RuntimeError("quote unavailable")
    authorization = OrderAuthorizationService(
        account_snapshots=repository,
        market_data=market_data,
        clock=lambda: NOW,
    )

    with pytest.raises(OrderAuthorizationError) as caught:
        authorization.authorize_manual_entry(request=stock_buy(), evaluated_at=NOW)

    assert caught.value.code == "manual_entry_quote_unavailable"


def test_manual_buy_uses_explicit_two_percent_account_risk_budget() -> None:
    with pytest.raises(OrderAuthorizationError) as caught:
        account_service(snapshot()).authorize_manual_entry(
            request=stock_buy().model_copy(update={"quantity": 21}),
            evaluated_at=NOW,
        )

    assert caught.value.code == "manual_entry_account_risk_exceeded"


def test_manual_sell_of_held_position_is_protective_without_buying_power() -> None:
    held = PositionSnapshot(
        symbol="QQQ.US",
        asset_type=AssetType.ETF,
        quantity=Decimal("20"),
        average_cost=Decimal("10"),
        market_value=Decimal("200"),
        unrealized_pnl=Decimal("0"),
    )
    request = stock_buy().model_copy(update={"side": OrderSide.SELL, "quantity": 10})

    evidence = account_service(
        snapshot(buying_power="0", positions=[held])
    ).authorize_manual_entry(request=request, evaluated_at=NOW)

    assert evidence.snapshot.buying_power == Decimal("0")


def test_manual_sell_does_not_treat_reserved_working_sell_as_available_position() -> None:
    held = PositionSnapshot(
        symbol="QQQ.US",
        asset_type=AssetType.ETF,
        quantity=Decimal("20"),
        average_cost=Decimal("10"),
        market_value=Decimal("200"),
        unrealized_pnl=Decimal("0"),
    )
    request = stock_buy().model_copy(update={"side": OrderSide.SELL, "quantity": 1})

    with pytest.raises(OrderAuthorizationError) as caught:
        account_service(snapshot(positions=[held])).authorize_manual_entry(
            request=request,
            reserved_quantity=Decimal("20"),
            evaluated_at=NOW,
        )

    assert caught.value.code == "manual_entry_position_reserved"


def test_manual_uncovered_sell_is_rejected_as_unbounded_short() -> None:
    request = stock_buy().model_copy(update={"side": OrderSide.SELL})

    with pytest.raises(OrderAuthorizationError) as caught:
        account_service(snapshot()).authorize_manual_entry(request=request, evaluated_at=NOW)

    assert caught.value.code == "manual_entry_short_exposure_unbounded"


def test_manual_option_entry_requires_contract_and_options_approval() -> None:
    with pytest.raises(OrderAuthorizationError) as missing_contract:
        account_service(snapshot()).authorize_manual_entry(
            request=option_buy(),
            evaluated_at=NOW,
        )
    assert missing_contract.value.code == "manual_entry_option_contract_required"

    contract = OptionContractRef(
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 10, 16),
        strike=Decimal("500"),
        right="call",
    )
    with pytest.raises(OrderAuthorizationError) as missing_approval:
        account_service(snapshot(options_level=None)).authorize_manual_entry(
            request=option_buy(option_contract=contract),
            evaluated_at=NOW,
        )
    assert missing_approval.value.code == "manual_entry_options_approval_missing"


def option_request_for_expiration(expiration: date, *, side: OrderSide = OrderSide.BUY) -> CreateOrderRequest:
    symbol = f"QQQ{expiration.strftime('%y%m%d')}C500000.US"
    contract = OptionContractRef(
        underlying_symbol="QQQ.US",
        expiration_date=expiration,
        strike=Decimal("500"),
        right=OptionRight.CALL,
    )
    return option_buy(option_contract=contract, symbol=symbol).model_copy(update={"side": side})


def test_manual_new_option_exposure_preserves_zero_dte_lock_and_expiry_guard() -> None:
    same_day = option_request_for_expiration(NOW.date())
    with pytest.raises(OrderAuthorizationError) as zero_dte:
        account_service(snapshot()).authorize_manual_entry(request=same_day, evaluated_at=NOW)
    assert zero_dte.value.code == "zero_dte_execution_disabled_pending_lifecycle"

    past = option_request_for_expiration(NOW.date() - timedelta(days=1))
    with pytest.raises(OrderAuthorizationError) as expired:
        account_service(snapshot()).authorize_manual_entry(request=past, evaluated_at=NOW)
    assert expired.value.code == "zero_dte_contract_expired"

    future = option_request_for_expiration(NOW.date() + timedelta(days=1))
    evidence = account_service(snapshot()).authorize_manual_entry(request=future, evaluated_at=NOW)
    assert evidence.mode == ExecutionMode.PAPER


def test_zero_dte_risk_reducing_option_close_remains_allowed() -> None:
    same_day = option_request_for_expiration(NOW.date(), side=OrderSide.SELL)
    held = PositionSnapshot(
        symbol=same_day.symbol,
        asset_type=AssetType.OPTION,
        quantity=Decimal("1"),
        average_cost=Decimal("1"),
        market_value=Decimal("100"),
        unrealized_pnl=Decimal("0"),
    )

    evidence = account_service(snapshot(positions=[held], options_level=None)).authorize_manual_entry(
        request=same_day,
        evaluated_at=NOW,
    )

    assert evidence.mode == ExecutionMode.PAPER


def test_manual_entry_cannot_use_past_as_of_to_extend_snapshot_freshness() -> None:
    with pytest.raises(OrderAuthorizationError) as caught:
        account_service(snapshot(age_seconds=121)).authorize_manual_entry(
            request=stock_buy(),
            evaluated_at=NOW - timedelta(seconds=121),
        )

    assert caught.value.code == "account_snapshot_stale"


@pytest.mark.parametrize(
    ("action", "leg", "expected"),
    [
        ("order_submit", None, OrderActionClass.MANUAL_ENTRY),
        ("bull_put_entry", "long_entry", OrderActionClass.STRATEGY_ENTRY),
        ("bull_put_exit", "short_exit", OrderActionClass.PROTECTIVE),
        ("bull_put_rollback", "long_exit", OrderActionClass.PROTECTIVE),
        ("covered_call_roll", "roll_buyback", OrderActionClass.PROTECTIVE),
        ("covered_call_roll", "roll_sell_open", OrderActionClass.STRATEGY_ENTRY),
    ],
)
def test_action_classification_does_not_use_order_side(
    action: str,
    leg: str | None,
    expected: str,
) -> None:
    assert classify_order_action(TradingActionContext(action=action, leg=leg)) == expected


def test_exposure_increasing_replace_is_detected_without_blocking_protective_replace() -> None:
    opening = Order(
        id="opening",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        asset_type=AssetType.ETF,
        side=OrderSide.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.SUBMITTED,
        limit_price=Decimal("10"),
        created_at=NOW,
        updated_at=NOW,
    )
    assert is_exposure_increasing_replace(
        opening,
        ReplaceOrderRequest(quantity=20, limit_price=Decimal("10")),
        OrderActionClass.UNKNOWN,
    )

    close = opening.model_copy(update={"side": OrderSide.SELL})
    assert not is_exposure_increasing_replace(
        close,
        ReplaceOrderRequest(quantity=20, limit_price=Decimal("10")),
        OrderActionClass.PROTECTIVE,
    )


def _local_order(*, id: str = "order-1", side: OrderSide = OrderSide.BUY) -> Order:
    return Order(
        id=id,
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id=f"external-{id}",
        client_order_id=f"client-{id}",
        symbol="QQQ.US",
        asset_type=AssetType.ETF,
        side=side,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        limit_price=Decimal("10"),
        created_at=NOW,
        updated_at=NOW,
    )


def _intent(*, state: TradingIntentState, request_hash: str) -> BrokerOrderIntent:
    return BrokerOrderIntent(
        id="intent-1",
        trade_action_intent_id="action-1",
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="manual-order-key-0001",
        request_hash=request_hash,
        operation=TradingOperation.SUBMIT,
        action="order_submit",
        broker_marker="st:0123456789abcdef",
        state=state,
        request_payload=stock_buy().model_dump(mode="json"),
        created_at=NOW,
        updated_at=NOW,
    )


def _order_service(*, ledger: Mock, adapter: Mock, authorization: Mock) -> OrderService:
    ledger.list_intents.return_value = []
    accounts = Mock()
    accounts.get_by_external_account_id.return_value = Mock(
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        is_active=True,
    )
    orders = Mock()
    orders.list_orders.return_value = []
    return OrderService(
        settings=Settings(),
        broker_accounts=accounts,
        trade_plans=Mock(),
        orders=orders,
        executions=Mock(),
        longbridge_adapter=adapter,
        intent_ledger=ledger,
        order_authorization=authorization,
    )


def test_exact_replay_returns_saved_response_without_authorization_or_broker_call() -> None:
    ledger = Mock()
    adapter = Mock()
    authorization = Mock()
    service = _order_service(ledger=ledger, adapter=adapter, authorization=authorization)
    request = stock_buy()
    saved = _local_order()
    request_hash = service._request_hash(request.model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=_intent(state=TradingIntentState.PERSISTED, request_hash=request_hash),
        created=False,
        replayed_order=saved.model_copy(update={"idempotent_replayed": True}),
    )

    result = service.submit_order(request, idempotency_key="manual-order-key-0001")

    assert result.id == saved.id
    assert result.idempotent_replayed is True
    authorization.authorize_manual_entry.assert_not_called()
    adapter.submit_order.assert_not_called()


def test_manual_authorization_rejection_is_terminal_before_broker_call() -> None:
    ledger = Mock()
    adapter = Mock()
    authorization = Mock()
    authorization.authorize_manual_entry.side_effect = OrderAuthorizationError(
        "account_snapshot_stale",
        "The broker account snapshot is stale; refresh the selected paper account before submitting this order.",
    )
    service = _order_service(ledger=ledger, adapter=adapter, authorization=authorization)
    request = stock_buy()
    request_hash = service._request_hash(request.model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=_intent(state=TradingIntentState.PREPARED, request_hash=request_hash),
        created=True,
    )

    with pytest.raises(OrderAuthorizationError) as caught:
        service.submit_order(request, idempotency_key="manual-order-key-0001")

    assert caught.value.code == "account_snapshot_stale"
    ledger.mark_rejected.assert_called_once()
    adapter.submit_order.assert_not_called()


def test_missing_order_authorization_fails_closed_for_manual_submit() -> None:
    ledger = Mock()
    adapter = Mock()
    authorization = Mock()
    service = _order_service(ledger=ledger, adapter=adapter, authorization=authorization)
    service.order_authorization = None
    request = stock_buy()
    request_hash = service._request_hash(request.model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=_intent(state=TradingIntentState.PREPARED, request_hash=request_hash),
        created=True,
    )

    with pytest.raises(OrderAuthorizationError) as caught:
        service.submit_order(request, idempotency_key="manual-order-key-0001")

    assert caught.value.code == "order_authorization_unavailable"
    ledger.mark_rejected.assert_called_once()
    adapter.submit_order.assert_not_called()


def test_missing_order_authorization_fails_closed_for_exposure_increasing_replace() -> None:
    ledger = Mock()
    adapter = Mock()
    authorization = Mock()
    service = _order_service(ledger=ledger, adapter=adapter, authorization=authorization)
    service.order_authorization = None
    service.orders.get_order.return_value = _local_order()

    def prepare(**kwargs):
        return PreparedBrokerOrderIntent(
            intent=_intent(
                state=TradingIntentState.PREPARED,
                request_hash=kwargs["request_hash"],
            ).model_copy(update={"operation": TradingOperation.REPLACE}),
            created=True,
        )

    ledger.prepare_intent.side_effect = prepare

    with pytest.raises(OrderAuthorizationError) as caught:
        service.replace_order(
            "order-1",
            ReplaceOrderRequest(quantity=2, limit_price=Decimal("11")),
            idempotency_key="manual-replace-auth-0001",
        )

    assert caught.value.code == "order_authorization_unavailable"
    ledger.mark_rejected.assert_called_once()
    adapter.replace_order.assert_not_called()


def test_protective_action_skips_manual_entry_gate_but_keeps_intent_path() -> None:
    ledger = Mock()
    adapter = Mock()
    authorization = Mock()
    adapter.submit_order.return_value = BrokerOrderSnapshot(
        external_order_id="external-close-1",
        symbol="QQQ.US",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        limit_price=Decimal("10"),
        submitted_at=NOW,
        updated_at=NOW,
    )
    service = _order_service(ledger=ledger, adapter=adapter, authorization=authorization)
    request = stock_buy()
    request_hash = service._request_hash(request.model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=_intent(state=TradingIntentState.PREPARED, request_hash=request_hash),
        created=True,
    )
    ledger.persist_broker_result.side_effect = lambda **kwargs: kwargs["order"]

    result = service.submit_order(
        request,
        idempotency_key="protective-order-key-0001",
        action_context=TradingActionContext(
            action="bull_put_exit",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-1",
            leg="short_exit",
        ),
    )

    assert result.external_order_id == "external-close-1"
    authorization.authorize_manual_entry.assert_not_called()
    adapter.submit_order.assert_called_once()


def _covered_candidate() -> CoveredCallCandidate:
    return CoveredCallCandidate(
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 10, 30),
        days_to_expiration=26,
        contracts=1,
        covered_shares=100,
        share_quantity=Decimal("100"),
        average_cost=Decimal("400"),
        underlying_price=Decimal("450"),
        call_symbol="QQQ261030C470000.US",
        call_strike=Decimal("470"),
        call_bid=Decimal("1.20"),
        call_ask=Decimal("1.30"),
        call_mid=Decimal("1.25"),
        premium_income=Decimal("120"),
        quote_timestamp=NOW,
    )


def _covered_policy(*, snapshot_check: Mock) -> _CoveredCallLifecyclePolicy:
    candidate = _covered_candidate()
    return _CoveredCallLifecyclePolicy(
        assert_execution_policy=Mock(),
        authorization_clock=lambda: NOW,
        current_candidate=lambda _proposal, _proposal_id: candidate,
        assert_no_same_day=Mock(),
        assert_no_unresolved=Mock(),
        refresh_candidate=lambda _candidate, _account, _mode, _evaluated: candidate,
        ensure_current_snapshot=snapshot_check,
        ensure_covered=Mock(),
        current_mark=lambda _candidate, _mode: Decimal("1.10"),
        parse_roll_payload=lambda payload, _proposal_id: (candidate, candidate),
        validate_roll_provenance=Mock(),
        validate_roll_buyback=Mock(),
        validate_roll_sell=Mock(),
        refresh_order=Mock(),
    )


def _covered_proposal(*, status: StrategyProposalStatus) -> StrategyProposal:
    candidate = _covered_candidate()
    return StrategyProposal(
        id="covered-proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="QQQ.US",
        title="Sell covered call",
        proposed_action="sell_covered_call",
        rationale="Covered lot",
        status=status,
        candidate_payload=candidate.model_dump(mode="json"),
        checks=["local_position_covered", "liquidity_filter", "manual_approval_required"],
        created_at=NOW,
        updated_at=NOW,
    )


def test_covered_call_snapshot_evidence_applies_to_open_and_roll_sell_but_not_close() -> None:
    snapshot_check = Mock()
    policy = _covered_policy(snapshot_check=snapshot_check)
    approved = _covered_proposal(status=StrategyProposalStatus.APPROVED)
    executed = approved.model_copy(update={"status": StrategyProposalStatus.EXECUTED})

    policy.authorize_open(
        proposal=approved,
        request=ExecuteCoveredCallProposalRequest(limit_price=Decimal("1.10")),
        parent_action_intent_id="parent-open",
    )
    assert snapshot_check.call_count == 2

    snapshot_check.reset_mock()
    policy.authorize_close(
        proposal=executed,
        request=CloseCoveredCallProposalRequest(limit_price=Decimal("1.10")),
    )
    snapshot_check.assert_not_called()

    policy.authorize_roll_sell(
        proposal=approved,
        request=ExecuteCoveredCallRollProposalRequest(sell_limit_price=Decimal("1.10")),
        roll_from=_covered_candidate(),
        roll_to=_covered_candidate(),
        buyback_order=_local_order(id="buyback", side=OrderSide.BUY),
        proposed_sell_limit=Decimal("1.10"),
    )
    assert snapshot_check.call_count == 2


def test_covered_call_rechecks_account_evidence_after_slow_candidate_refresh() -> None:
    repository = Mock()
    repository.get_latest_account_snapshot.return_value = snapshot()
    now = [NOW]
    authorization = OrderAuthorizationService(
        account_snapshots=repository,
        clock=lambda: now[0],
    )
    checks = {"count": 0}

    def ensure_current(account_id: str, mode: ExecutionMode, evaluated_at: datetime) -> None:
        del account_id, mode, evaluated_at
        checks["count"] += 1
        authorization.require_current_account_snapshot(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            evaluated_at=now[0],
        )
        if checks["count"] == 1:
            now[0] = NOW + timedelta(seconds=121)

    policy = _covered_policy(snapshot_check=Mock(side_effect=ensure_current))
    policy.ensure_current_snapshot = ensure_current

    with pytest.raises(OrderAuthorizationError) as caught:
        policy.authorize_open(
            proposal=_covered_proposal(status=StrategyProposalStatus.APPROVED),
            request=ExecuteCoveredCallProposalRequest(limit_price=Decimal("1.10")),
            parent_action_intent_id="parent-slow-refresh",
        )

    assert caught.value.code == "account_snapshot_stale"
    assert checks["count"] == 2

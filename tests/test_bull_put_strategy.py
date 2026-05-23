from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    SpreadStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerAccount,
    BullPutSpread,
    ExecuteBullPutSpreadRequest,
    HistoricalPriceBar,
    OptionContractRef,
    OptionChainEntry,
    OptionMarketSnapshot,
    Order,
    SecurityQuoteSnapshot,
    UpdateBullPutStrategyRuntimeRequest,
)


def build_broker_account() -> BrokerAccount:
    now = datetime(2026, 5, 22, 9, 30, tzinfo=timezone.utc)
    return BrokerAccount(
        id="broker-account-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        display_name="Longbridge Paper",
        base_currency="USD",
        options_level="Level 2",
        is_active=True,
        auto_reconcile_enabled=True,
        created_at=now,
        updated_at=now,
    )


def build_account_snapshot(
    *,
    options_level: str | None = "Level 2",
    net_liquidation: Decimal = Decimal("50000"),
    buying_power: Decimal = Decimal("25000"),
) -> AccountSnapshot:
    return AccountSnapshot(
        id="snapshot-1",
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        currency="USD",
        cash_balance=Decimal("25000"),
        net_liquidation=net_liquidation,
        buying_power=buying_power,
        options_level=options_level,
        positions=[],
        captured_at=datetime(2026, 5, 22, 14, 35, tzinfo=timezone.utc),
    )


def build_underlying_quote(*, last_done: Decimal = Decimal("500")) -> SecurityQuoteSnapshot:
    return SecurityQuoteSnapshot(
        symbol="QQQ.US",
        last_done=last_done,
        prev_close=Decimal("498"),
        open=Decimal("499"),
        high=Decimal("501"),
        low=Decimal("497"),
        timestamp=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        volume=1_000_000,
        turnover=Decimal("500000000"),
        trade_status="Normal",
    )


def build_bars() -> list[HistoricalPriceBar]:
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    bars: list[HistoricalPriceBar] = []
    for offset in range(60):
        close = Decimal("400") + Decimal(offset)
        bars.append(
            HistoricalPriceBar(
                symbol="QQQ.US",
                timestamp=start + timedelta(days=offset),
                open=close - Decimal("1"),
                high=close + Decimal("2"),
                low=close - Decimal("2"),
                close=close,
                volume=1000 + offset,
                turnover=close * Decimal("1000"),
            )
        )
    return bars


def build_option_chain() -> list[OptionChainEntry]:
    return [
        OptionChainEntry(
            strike=Decimal("470"),
            call_symbol="QQQ260619C470000.US",
            put_symbol="QQQ260619P470000.US",
            standard=True,
        ),
        OptionChainEntry(
            strike=Decimal("467"),
            call_symbol="QQQ260619C467000.US",
            put_symbol="QQQ260619P467000.US",
            standard=True,
        ),
        OptionChainEntry(
            strike=Decimal("464"),
            call_symbol="QQQ260619C464000.US",
            put_symbol="QQQ260619P464000.US",
            standard=True,
        ),
    ]


def build_option_quotes() -> list[OptionMarketSnapshot]:
    timestamp = datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc)
    return [
        OptionMarketSnapshot(
            symbol="QQQ260619P470000.US",
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 6, 19),
            strike=Decimal("470"),
            right=OptionRight.PUT,
            last_done=Decimal("2.50"),
            prev_close=Decimal("2.30"),
            open=Decimal("2.40"),
            high=Decimal("2.65"),
            low=Decimal("2.35"),
            timestamp=timestamp,
            volume=2000,
            turnover=Decimal("500000"),
            trade_status="Normal",
            open_interest=500,
            implied_volatility=Decimal("0.22"),
            historical_volatility=Decimal("0.18"),
            delta=Decimal("-0.22"),
            gamma=Decimal("0.01"),
            theta=Decimal("-0.02"),
            vega=Decimal("0.05"),
        ),
        OptionMarketSnapshot(
            symbol="QQQ260619P467000.US",
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 6, 19),
            strike=Decimal("467"),
            right=OptionRight.PUT,
            last_done=Decimal("1.05"),
            prev_close=Decimal("1.00"),
            open=Decimal("1.02"),
            high=Decimal("1.15"),
            low=Decimal("0.95"),
            timestamp=timestamp,
            volume=1800,
            turnover=Decimal("180000"),
            trade_status="Normal",
            open_interest=450,
            implied_volatility=Decimal("0.21"),
            historical_volatility=Decimal("0.18"),
            delta=Decimal("-0.16"),
            gamma=Decimal("0.01"),
            theta=Decimal("-0.01"),
            vega=Decimal("0.04"),
        ),
        OptionMarketSnapshot(
            symbol="QQQ260619P464000.US",
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 6, 19),
            strike=Decimal("464"),
            right=OptionRight.PUT,
            last_done=Decimal("0.70"),
            prev_close=Decimal("0.65"),
            open=Decimal("0.68"),
            high=Decimal("0.75"),
            low=Decimal("0.60"),
            timestamp=timestamp,
            volume=1200,
            turnover=Decimal("90000"),
            trade_status="Normal",
            open_interest=420,
            implied_volatility=Decimal("0.20"),
            historical_volatility=Decimal("0.18"),
            delta=Decimal("-0.12"),
            gamma=Decimal("0.01"),
            theta=Decimal("-0.01"),
            vega=Decimal("0.03"),
        ),
    ]


def build_open_spread(
    *,
    status: SpreadStatus = SpreadStatus.OPEN,
    expiration_date: date = date(2026, 6, 19),
) -> BullPutSpread:
    now = datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc)
    return BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=expiration_date,
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260619P467000.US",
        long_strike=Decimal("467"),
        short_symbol="QQQ260619P470000.US",
        short_strike=Decimal("470"),
        status=status,
        entry_long_price=Decimal("1.10"),
        entry_short_price=Decimal("2.40"),
        entry_net_credit=Decimal("1.30"),
        max_profit=Decimal("130.00"),
        max_loss=Decimal("170.00"),
        break_even=Decimal("468.70"),
        account_risk_pct=Decimal("0.0034"),
        opened_at=now,
        created_at=now,
        updated_at=now,
    )


def build_scan_time() -> datetime:
    return datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc)


def build_service(
    *,
    account_snapshot: AccountSnapshot | None = None,
    underlying_quote: SecurityQuoteSnapshot | None = None,
) -> tuple[BullPutStrategyService, Mock, Mock, Mock]:
    adapter = Mock()
    broker_accounts = Mock()
    account_snapshots = Mock()
    spreads = Mock()
    order_service = Mock()
    broker_accounts.get_by_external_account_id.return_value = build_broker_account()
    account_snapshots.list_account_snapshots.return_value = [account_snapshot or build_account_snapshot()]
    adapter.get_quote.return_value = underlying_quote or build_underlying_quote()
    adapter.get_recent_daily_bars.return_value = build_bars()
    adapter.list_option_expiry_dates.return_value = [
        date(2026, 6, 12),
        date(2026, 6, 19),
        date(2026, 7, 17),
    ]
    adapter.list_option_chain.return_value = build_option_chain()
    adapter.get_option_market_snapshots.return_value = build_option_quotes()
    adapter.get_best_bid_ask.side_effect = lambda symbol, mode: {
        "QQQ260619P470000.US": (Decimal("2.40"), Decimal("2.60")),
        "QQQ260619P467000.US": (Decimal("1.00"), Decimal("1.10")),
        "QQQ260619P464000.US": (Decimal("0.60"), Decimal("0.70")),
    }[symbol]
    spreads.list_spreads.return_value = []
    spreads.create_spread.side_effect = lambda spread: spread
    spreads.update_spread.side_effect = lambda spread: spread
    runtime_states = Mock()
    runtime_store: dict[str, object] = {}

    def get_runtime_state(*, external_account_id: str, strategy_id: str = "paper_bull_put_v1"):
        return runtime_store.get((external_account_id, strategy_id))

    def upsert_runtime_state(state):
        runtime_store[(state.external_account_id, state.strategy_id)] = state
        return state

    runtime_states.get_runtime_state.side_effect = get_runtime_state
    runtime_states.upsert_runtime_state.side_effect = upsert_runtime_state
    journal_service = Mock()

    service = BullPutStrategyService(
        settings=Settings(),
        broker_accounts=broker_accounts,
        account_snapshots=account_snapshots,
        spreads=spreads,
        runtime_states=runtime_states,
        order_service=order_service,
        longbridge_adapter=adapter,
        risk_service=RiskService(settings=Settings()),
        journal_service=journal_service,
    )
    return service, adapter, spreads, order_service


def build_option_order(
    *,
    order_id: str,
    symbol: str,
    side: OrderSide,
    status: OrderStatus,
    limit_price: Decimal | None,
    external_order_id: str | None = None,
) -> Order:
    option_contract = OptionContractRef(
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 19),
        strike=Decimal("470") if "470" in symbol else Decimal("467"),
        right=OptionRight.PUT,
    )
    return Order(
        id=order_id,
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id=external_order_id or f"remote-{order_id}",
        symbol=symbol,
        asset_type=AssetType.OPTION,
        side=side,
        quantity=1,
        order_type=OrderType.LIMIT if limit_price is not None else OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=status,
        limit_price=limit_price,
        option_contract=option_contract,
        raw_payload={
            "remote_order": {
                "executed_price": str(limit_price) if limit_price is not None else None,
            }
        },
        submitted_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        created_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
    )


def test_preview_spread_selects_tradeable_candidate() -> None:
    service, adapter, _, _ = build_service()

    result = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
    )

    assert result.eligible is True
    assert result.selected_expiration_date == date(2026, 6, 19)
    assert result.days_to_expiration == 28
    assert result.candidate is not None
    assert result.candidate.short_put.strike == Decimal("470")
    assert result.candidate.long_put.strike == Decimal("467")
    assert result.candidate.mid_credit == Decimal("1.45")
    assert result.risk is not None
    assert result.risk.max_profit == Decimal("145.00")
    assert result.risk.max_loss == Decimal("170.00")
    assert adapter.get_best_bid_ask.call_count >= 2


def test_preview_spread_fails_trend_filter() -> None:
    service, _, _, _ = build_service(underlying_quote=build_underlying_quote(last_done=Decimal("430")))

    result = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
    )

    assert result.eligible is False
    assert "Underlying price is below the 20-day moving average." in result.reasons


def test_preview_spread_blocks_risk_above_per_trade_limit() -> None:
    small_account = build_account_snapshot(
        net_liquidation=Decimal("12000"),
        buying_power=Decimal("25000"),
    )
    service, _, _, _ = build_service(account_snapshot=small_account)

    result = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
    )

    assert result.eligible is False
    assert (
        "Estimated spread max loss exceeds the per-trade account risk cap for this strategy."
        in result.reasons
    )


def test_execute_spread_opens_position_when_both_legs_fill() -> None:
    service, _, _, order_service = build_service()
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
        ),
        build_option_order(
            order_id="short-entry",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
        ),
    ]

    spread = service.execute_spread(
        ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        )
    )

    assert spread.status == SpreadStatus.OPEN
    assert spread.long_entry_order_id == "long-entry"
    assert spread.short_entry_order_id == "short-entry"
    assert spread.entry_long_price == Decimal("1.10")
    assert spread.entry_short_price == Decimal("2.40")
    assert spread.entry_net_credit == Decimal("1.30")


def test_execute_spread_rolls_back_when_short_leg_does_not_fill() -> None:
    service, _, _, order_service = build_service()
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
        ),
        build_option_order(
            order_id="short-entry",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("2.40"),
        ),
        build_option_order(
            order_id="long-exit",
            symbol="QQQ260619P467000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=None,
        ),
    ]
    order_service.refresh_order.return_value = build_option_order(
        order_id="short-entry",
        symbol="QQQ260619P470000.US",
        side=OrderSide.SELL,
        status=OrderStatus.CANCELED,
        limit_price=Decimal("2.40"),
    )

    spread = service.execute_spread(
        ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        )
    )

    assert spread.status == SpreadStatus.ROLLED_BACK
    assert spread.short_entry_order_id == "short-entry"
    assert spread.long_exit_order_id == "long-exit"
    assert spread.exit_reason == "short_entry_unfilled"


def test_execute_spread_blocks_when_same_symbol_is_already_active() -> None:
    service, _, spreads, _ = build_service()
    spreads.list_spreads.return_value = [build_open_spread()]

    try:
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            )
        )
    except ValueError as exc:
        assert (
            str(exc)
            == "An active bull put spread already exists for 'QQQ.US' in account 'LBPT10087357'."
        )
    else:
        raise AssertionError("Expected execute_spread to block when the same symbol is already active.")


def test_execute_spread_blocks_when_correlated_group_is_already_at_capacity() -> None:
    service, _, spreads, _ = build_service()
    spreads.list_spreads.return_value = [
        build_open_spread().model_copy(update={"underlying_symbol": "QQQ.US"})
    ]

    try:
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="SMH.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            )
        )
    except ValueError as exc:
        assert (
            str(exc)
            == "Account 'LBPT10087357' already has the maximum number of active correlated bull put spreads in [QQQ.US, SMH.US, SOXL.US]."
        )
    else:
        raise AssertionError("Expected execute_spread to block when the correlated group is at capacity.")


def test_execute_spread_blocks_when_account_is_already_at_capacity() -> None:
    service, _, spreads, _ = build_service()
    spreads.list_spreads.return_value = [
        build_open_spread().model_copy(update={"underlying_symbol": "QQQ.US"}),
        build_open_spread().model_copy(update={"id": "spread-2", "underlying_symbol": "EWY.US"}),
    ]

    try:
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="SMH.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            )
        )
    except ValueError as exc:
        assert (
            str(exc)
            == "Account 'LBPT10087357' already has the maximum number of active bull put spreads."
        )
    else:
        raise AssertionError("Expected execute_spread to block when the account is at capacity.")


def test_update_runtime_state_normalizes_paused_symbols() -> None:
    service, _, _, _ = build_service()

    runtime = service.update_runtime_state(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        request=UpdateBullPutStrategyRuntimeRequest(
            auto_entry_enabled=False,
            paused_symbols=[" qqq.us ", "QQQ.US", "BAD.US", "smh.us"],
        ),
        as_of=build_scan_time(),
    )

    assert runtime.auto_entry_enabled is False
    assert runtime.paused_symbols == ["QQQ.US", "SMH.US"]


def test_preview_spread_blocks_when_kill_switch_is_active() -> None:
    service, _, _, _ = build_service()
    service.update_runtime_state(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        request=UpdateBullPutStrategyRuntimeRequest(kill_switch_active=True),
        as_of=build_scan_time(),
    )

    result = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )

    assert result.eligible is False
    assert result.reasons == ["Bull put kill switch is active for this account."]


def test_run_entry_scan_executes_and_updates_runtime_state() -> None:
    service, _, _, order_service = build_service()
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
        ),
        build_option_order(
            order_id="short-entry",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
        ),
    ]

    result = service.run_entry_scan(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
        force=True,
    )

    assert result.executed is True
    assert result.executed_spread is not None
    assert result.strategy_state.daily_entry_count == 1
    assert result.strategy_state.last_scan_result == "executed"
    assert service.journal_service.create_entry.call_count >= 1


def test_monitor_spread_keeps_open_position_without_exit_trigger() -> None:
    service, _, spreads, _ = build_service()
    spreads.get_spread.return_value = build_open_spread()

    result = service.monitor_spread(
        "spread-1",
        as_of=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
    )

    assert result.should_close is False
    assert result.exit_reason is None
    assert result.spread.status == SpreadStatus.OPEN
    assert result.estimated_exit_debit == Decimal("1.60")
    assert result.estimated_pnl == Decimal("-30.00")
    assert result.days_to_expiration == 27


def test_monitor_spread_closes_position_on_take_profit() -> None:
    service, adapter, spreads, order_service = build_service()
    spreads.get_spread.return_value = build_open_spread()
    adapter.get_best_bid_ask.side_effect = lambda symbol, mode: {
        "QQQ260619P470000.US": (Decimal("0.70"), Decimal("0.80")),
        "QQQ260619P467000.US": (Decimal("0.30"), Decimal("0.40")),
        "QQQ260619P464000.US": (Decimal("0.20"), Decimal("0.30")),
    }[symbol]
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="short-exit",
            symbol="QQQ260619P470000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("0.80"),
        ),
        build_option_order(
            order_id="long-exit",
            symbol="QQQ260619P467000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=None,
        ),
    ]

    result = service.monitor_spread(
        "spread-1",
        as_of=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
    )

    assert result.should_close is True
    assert result.exit_reason == "take_profit"
    assert result.spread.status == SpreadStatus.CLOSED
    assert result.spread.short_exit_order_id == "short-exit"
    assert result.spread.long_exit_order_id == "long-exit"
    assert result.estimated_exit_debit == Decimal("0.50")
    assert result.estimated_pnl == Decimal("80.00")


def test_monitor_spread_leaves_residual_long_when_long_exit_does_not_fill() -> None:
    service, _, spreads, order_service = build_service()
    spreads.get_spread.return_value = build_open_spread(expiration_date=date(2026, 5, 29))
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="short-exit",
            symbol="QQQ260619P470000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.60"),
        ),
        build_option_order(
            order_id="long-exit",
            symbol="QQQ260619P467000.US",
            side=OrderSide.SELL,
            status=OrderStatus.SUBMITTED,
            limit_price=None,
        ),
    ]
    order_service.refresh_order.return_value = build_option_order(
        order_id="long-exit",
        symbol="QQQ260619P467000.US",
        side=OrderSide.SELL,
        status=OrderStatus.CANCELED,
        limit_price=None,
    )

    result = service.monitor_spread(
        "spread-1",
        as_of=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
    )

    assert result.should_close is True
    assert result.exit_reason == "days_to_expiration_limit"
    assert result.spread.status == SpreadStatus.EXIT_PENDING_LONG
    assert result.spread.short_exit_order_id == "short-exit"
    assert result.spread.long_exit_order_id == "long-exit"

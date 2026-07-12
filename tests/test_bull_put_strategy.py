from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from stocks_tool.adapters.brokers.longbridge import LongbridgeIntegrationError
from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.application.services.orders import (
    TradingIntentConflictError,
    TradingIntentOutcomeUnknownError,
)
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
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerAccount,
    BrokerOrderIntent,
    BullPutSpread,
    ExecuteBullPutSpreadRequest,
    HistoricalPriceBar,
    OptionContractRef,
    OptionChainEntry,
    OptionMarketSnapshot,
    Order,
    PositionSnapshot,
    PreparedTradeActionIntent,
    RecoverBullPutCloseRequest,
    SecurityQuoteSnapshot,
    TradeActionIntent,
    UpdateBullPutStrategyRuntimeRequest,
)
from stocks_tool.ports.repository import ConcurrentSpreadUpdateError


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


def build_market_quote(
    *,
    symbol: str,
    last_done: Decimal,
    prev_close: Decimal,
    pre_market_last_done: Decimal | None = None,
    timestamp: datetime = datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
) -> SecurityQuoteSnapshot:
    pre_market_quote = None
    if pre_market_last_done is not None:
        pre_market_quote = {
            "last_done": pre_market_last_done,
            "timestamp": datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
            "volume": 1000,
            "turnover": pre_market_last_done * Decimal("1000"),
            "high": pre_market_last_done,
            "low": pre_market_last_done,
            "prev_close": prev_close,
        }
    return SecurityQuoteSnapshot(
        symbol=symbol,
        last_done=last_done,
        prev_close=prev_close,
        open=prev_close,
        high=max(last_done, prev_close),
        low=min(last_done, prev_close),
        timestamp=timestamp,
        volume=1_000_000,
        turnover=last_done * Decimal("1000000"),
        trade_status="Normal",
        pre_market_quote=pre_market_quote,
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


def build_spy_option_chain() -> list[OptionChainEntry]:
    return [
        OptionChainEntry(
            strike=Decimal("610"),
            call_symbol="SPY260529C610000.US",
            put_symbol="SPY260529P610000.US",
            standard=True,
        ),
        OptionChainEntry(
            strike=Decimal("600"),
            call_symbol="SPY260529C600000.US",
            put_symbol="SPY260529P600000.US",
            standard=True,
        ),
    ]


def build_spy_next_option_chain() -> list[OptionChainEntry]:
    return [
        OptionChainEntry(
            strike=Decimal("612"),
            call_symbol="SPY260605C612000.US",
            put_symbol="SPY260605P612000.US",
            standard=True,
        ),
        OptionChainEntry(
            strike=Decimal("600"),
            call_symbol="SPY260605C600000.US",
            put_symbol="SPY260605P600000.US",
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


def build_spy_option_quotes() -> list[OptionMarketSnapshot]:
    timestamp = datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc)
    return [
        OptionMarketSnapshot(
            symbol="SPY260529P610000.US",
            underlying_symbol="SPY.US",
            expiration_date=date(2026, 5, 29),
            strike=Decimal("610"),
            right=OptionRight.PUT,
            last_done=Decimal("7.20"),
            prev_close=Decimal("6.90"),
            open=Decimal("7.10"),
            high=Decimal("7.35"),
            low=Decimal("6.80"),
            timestamp=timestamp,
            volume=5000,
            turnover=Decimal("360000"),
            trade_status="Normal",
            open_interest=1200,
            implied_volatility=Decimal("0.19"),
            historical_volatility=Decimal("0.16"),
            delta=Decimal("-0.44"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.03"),
            vega=Decimal("0.07"),
        ),
        OptionMarketSnapshot(
            symbol="SPY260529P600000.US",
            underlying_symbol="SPY.US",
            expiration_date=date(2026, 5, 29),
            strike=Decimal("600"),
            right=OptionRight.PUT,
            last_done=Decimal("3.40"),
            prev_close=Decimal("3.20"),
            open=Decimal("3.30"),
            high=Decimal("3.55"),
            low=Decimal("3.10"),
            timestamp=timestamp,
            volume=4200,
            turnover=Decimal("145000"),
            trade_status="Normal",
            open_interest=1500,
            implied_volatility=Decimal("0.18"),
            historical_volatility=Decimal("0.16"),
            delta=Decimal("-0.27"),
            gamma=Decimal("0.01"),
            theta=Decimal("-0.02"),
            vega=Decimal("0.05"),
        ),
    ]


def build_spy_next_option_quotes() -> list[OptionMarketSnapshot]:
    timestamp = datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc)
    return [
        OptionMarketSnapshot(
            symbol="SPY260605P612000.US",
            underlying_symbol="SPY.US",
            expiration_date=date(2026, 6, 5),
            strike=Decimal("612"),
            right=OptionRight.PUT,
            last_done=Decimal("5.10"),
            prev_close=Decimal("4.95"),
            open=Decimal("5.00"),
            high=Decimal("5.25"),
            low=Decimal("4.85"),
            timestamp=timestamp,
            volume=3600,
            turnover=Decimal("240000"),
            trade_status="Normal",
            open_interest=1600,
            implied_volatility=Decimal("0.21"),
            historical_volatility=Decimal("0.16"),
            delta=Decimal("-0.31"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.03"),
            vega=Decimal("0.07"),
        ),
        OptionMarketSnapshot(
            symbol="SPY260605P600000.US",
            underlying_symbol="SPY.US",
            expiration_date=date(2026, 6, 5),
            strike=Decimal("600"),
            right=OptionRight.PUT,
            last_done=Decimal("2.60"),
            prev_close=Decimal("2.45"),
            open=Decimal("2.50"),
            high=Decimal("2.70"),
            low=Decimal("2.35"),
            timestamp=timestamp,
            volume=3300,
            turnover=Decimal("126000"),
            trade_status="Normal",
            open_interest=1700,
            implied_volatility=Decimal("0.23"),
            historical_volatility=Decimal("0.17"),
            delta=Decimal("-0.24"),
            gamma=Decimal("0.01"),
            theta=Decimal("-0.02"),
            vega=Decimal("0.05"),
        ),
    ]


def build_qqq_shortdated_option_chain() -> list[OptionChainEntry]:
    return [
        OptionChainEntry(
            strike=Decimal("498"),
            call_symbol="QQQ260529C498000.US",
            put_symbol="QQQ260529P498000.US",
            standard=True,
        ),
        OptionChainEntry(
            strike=Decimal("490"),
            call_symbol="QQQ260529C490000.US",
            put_symbol="QQQ260529P490000.US",
            standard=True,
        ),
    ]


def build_qqq_next_option_chain() -> list[OptionChainEntry]:
    return [
        OptionChainEntry(
            strike=Decimal("500"),
            call_symbol="QQQ260612C500000.US",
            put_symbol="QQQ260612P500000.US",
            standard=True,
        ),
        OptionChainEntry(
            strike=Decimal("490"),
            call_symbol="QQQ260612C490000.US",
            put_symbol="QQQ260612P490000.US",
            standard=True,
        ),
    ]


def build_qqq_shortdated_option_quotes() -> list[OptionMarketSnapshot]:
    timestamp = datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc)
    return [
        OptionMarketSnapshot(
            symbol="QQQ260529P498000.US",
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 5, 29),
            strike=Decimal("498"),
            right=OptionRight.PUT,
            last_done=Decimal("3.70"),
            prev_close=Decimal("3.40"),
            open=Decimal("3.55"),
            high=Decimal("3.90"),
            low=Decimal("3.30"),
            timestamp=timestamp,
            volume=6500,
            turnover=Decimal("480000"),
            trade_status="Normal",
            open_interest=2200,
            implied_volatility=Decimal("0.25"),
            historical_volatility=Decimal("0.20"),
            delta=Decimal("-0.29"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.03"),
            vega=Decimal("0.08"),
        ),
        OptionMarketSnapshot(
            symbol="QQQ260529P490000.US",
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 5, 29),
            strike=Decimal("490"),
            right=OptionRight.PUT,
            last_done=Decimal("1.90"),
            prev_close=Decimal("1.75"),
            open=Decimal("1.82"),
            high=Decimal("2.05"),
            low=Decimal("1.70"),
            timestamp=timestamp,
            volume=5400,
            turnover=Decimal("215000"),
            trade_status="Normal",
            open_interest=2500,
            implied_volatility=Decimal("0.23"),
            historical_volatility=Decimal("0.19"),
            delta=Decimal("-0.18"),
            gamma=Decimal("0.01"),
            theta=Decimal("-0.02"),
            vega=Decimal("0.05"),
        ),
    ]


def build_qqq_next_option_quotes() -> list[OptionMarketSnapshot]:
    timestamp = datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc)
    return [
        OptionMarketSnapshot(
            symbol="QQQ260612P500000.US",
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 6, 12),
            strike=Decimal("500"),
            right=OptionRight.PUT,
            last_done=Decimal("6.15"),
            prev_close=Decimal("5.80"),
            open=Decimal("5.95"),
            high=Decimal("6.30"),
            low=Decimal("5.70"),
            timestamp=timestamp,
            volume=3100,
            turnover=Decimal("310000"),
            trade_status="Normal",
            open_interest=1800,
            implied_volatility=Decimal("0.27"),
            historical_volatility=Decimal("0.21"),
            delta=Decimal("-0.33"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.03"),
            vega=Decimal("0.08"),
        ),
        OptionMarketSnapshot(
            symbol="QQQ260612P490000.US",
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 6, 12),
            strike=Decimal("490"),
            right=OptionRight.PUT,
            last_done=Decimal("3.10"),
            prev_close=Decimal("2.95"),
            open=Decimal("3.00"),
            high=Decimal("3.22"),
            low=Decimal("2.84"),
            timestamp=timestamp,
            volume=2900,
            turnover=Decimal("154000"),
            trade_status="Normal",
            open_interest=2600,
            implied_volatility=Decimal("0.25"),
            historical_volatility=Decimal("0.20"),
            delta=Decimal("-0.22"),
            gamma=Decimal("0.01"),
            theta=Decimal("-0.02"),
            vega=Decimal("0.06"),
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


def build_closed_spread(
    *,
    spread_id: str,
    closed_at: datetime,
    exit_reason: str,
) -> BullPutSpread:
    return build_open_spread(status=SpreadStatus.CLOSED).model_copy(
        update={
            "id": spread_id,
            "status": SpreadStatus.CLOSED,
            "short_exit_order_id": f"{spread_id}-short-exit",
            "long_exit_order_id": f"{spread_id}-long-exit",
            "exit_reason": exit_reason,
            "closed_at": closed_at,
            "updated_at": closed_at,
        }
    )


def build_scan_time() -> datetime:
    return datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc)


def build_service(
    *,
    account_snapshot: AccountSnapshot | None = None,
    underlying_quote: SecurityQuoteSnapshot | None = None,
) -> tuple[BullPutStrategyService, Mock, Mock, Mock]:
    adapter = Mock()
    adapter.get_us_market_calendar.return_value = (True, False)
    broker_accounts = Mock()
    account_snapshots = Mock()
    spreads = Mock()
    order_service = Mock()
    order_service.has_unresolved_intents.return_value = False
    broker_accounts.get_by_external_account_id.return_value = build_broker_account()
    current_account_snapshot = account_snapshot or build_account_snapshot()
    account_snapshots.list_account_snapshots.return_value = [current_account_snapshot]
    account_snapshots.create_account_snapshot.return_value = current_account_snapshot
    adapter.build_account_snapshot.return_value = current_account_snapshot
    order_service.reconcile_unresolved_intents.return_value = Mock(unresolved_intents=0)
    order_service.sync_today_orders.return_value = Mock()
    order_service.list_trading_intents.return_value = []
    parent_counter = 0

    def prepare_trade_action(**kwargs):
        nonlocal parent_counter
        parent_counter += 1
        return PreparedTradeActionIntent(
            intent=TradeActionIntent(
                id=f"parent-action-{parent_counter}",
                external_account_id=kwargs["external_account_id"],
                broker=kwargs["broker"],
                mode=kwargs["mode"],
                idempotency_key=kwargs["idempotency_key"],
                request_hash=kwargs["request_hash"],
                action=kwargs["action_context"].action,
                strategy_id=kwargs["action_context"].strategy_id,
                entity_id=kwargs["action_context"].entity_id,
                state=TradingIntentState.PREPARED,
                request_payload=kwargs["request_payload"],
                created_at=build_scan_time(),
                updated_at=build_scan_time(),
            ),
            created=True,
        )

    order_service.prepare_trade_action.side_effect = prepare_trade_action
    quote_map = {
        "QQQ.US": underlying_quote or build_underlying_quote(),
        "SMH.US": build_market_quote(
            symbol="SMH.US",
            last_done=Decimal("500"),
            prev_close=Decimal("498"),
            timestamp=build_scan_time(),
        ),
        "SOXL.US": build_market_quote(
            symbol="SOXL.US",
            last_done=Decimal("500"),
            prev_close=Decimal("498"),
            timestamp=build_scan_time(),
        ),
        "EWY.US": build_market_quote(
            symbol="EWY.US",
            last_done=Decimal("500"),
            prev_close=Decimal("498"),
            timestamp=build_scan_time(),
        ),
        "SPY.US": build_market_quote(
            symbol="SPY.US",
            last_done=Decimal("612"),
            prev_close=Decimal("615"),
            pre_market_last_done=Decimal("611.5"),
        ),
        "SOXX.US": build_market_quote(
            symbol="SOXX.US",
            last_done=Decimal("245"),
            prev_close=Decimal("249"),
            pre_market_last_done=Decimal("244.5"),
        ),
        "USO.US": build_market_quote(
            symbol="USO.US",
            last_done=Decimal("84"),
            prev_close=Decimal("82.5"),
            pre_market_last_done=Decimal("84.2"),
        ),
        "TLT.US": build_market_quote(
            symbol="TLT.US",
            last_done=Decimal("92"),
            prev_close=Decimal("92.8"),
            pre_market_last_done=Decimal("91.9"),
        ),
    }
    adapter.get_quote.return_value = underlying_quote or build_underlying_quote()
    adapter.get_quote.side_effect = lambda symbol, mode: quote_map[symbol]
    adapter.get_quotes.side_effect = lambda symbols, mode: {
        symbol: quote_map[symbol]
        for symbol in symbols
        if symbol in quote_map
    }
    adapter.get_recent_daily_bars.return_value = build_bars()
    adapter.list_option_expiry_dates.side_effect = lambda symbol, mode: (
        [date(2026, 5, 29), date(2026, 6, 5), date(2026, 6, 12)]
        if symbol == "SPY.US"
        else [date(2026, 5, 29), date(2026, 6, 12), date(2026, 6, 19), date(2026, 7, 17)]
    )
    adapter.list_option_chain.side_effect = lambda symbol, expiry_date, mode: (
        build_spy_option_chain()
        if symbol == "SPY.US" and expiry_date == date(2026, 5, 29)
        else build_spy_next_option_chain()
        if symbol == "SPY.US" and expiry_date == date(2026, 6, 5)
        else build_qqq_shortdated_option_chain()
        if symbol == "QQQ.US" and expiry_date == date(2026, 5, 29)
        else build_qqq_next_option_chain()
        if symbol == "QQQ.US" and expiry_date == date(2026, 6, 12)
        else build_option_chain()
    )
    adapter.get_option_market_snapshots.side_effect = lambda symbols, mode: (
        build_spy_option_quotes()
        if symbols and str(symbols[0]).startswith("SPY260529")
        else build_spy_next_option_quotes()
        if symbols and str(symbols[0]).startswith("SPY260605")
        else build_qqq_shortdated_option_quotes()
        if symbols and str(symbols[0]).startswith("QQQ260529")
        else build_qqq_next_option_quotes()
        if symbols and str(symbols[0]).startswith("QQQ260612")
        else build_option_quotes()
    )
    adapter.get_best_bid_ask.side_effect = lambda symbol, mode: {
        "QQQ260619P470000.US": (Decimal("2.40"), Decimal("2.60")),
        "QQQ260619P467000.US": (Decimal("1.00"), Decimal("1.10")),
        "QQQ260619P464000.US": (Decimal("0.60"), Decimal("0.70")),
        "QQQ260529P498000.US": (Decimal("3.64"), Decimal("3.84")),
        "QQQ260529P490000.US": (Decimal("1.88"), Decimal("2.00")),
        "QQQ260612P500000.US": (Decimal("6.10"), Decimal("6.30")),
        "QQQ260612P490000.US": (Decimal("3.00"), Decimal("3.18")),
        "SPY260529P610000.US": (Decimal("7.10"), Decimal("7.30")),
        "SPY260529P600000.US": (Decimal("3.30"), Decimal("3.45")),
        "SPY260605P612000.US": (Decimal("5.00"), Decimal("5.20")),
        "SPY260605P600000.US": (Decimal("2.50"), Decimal("2.70")),
    }[symbol]
    spreads.list_spreads.return_value = []
    spreads.get_spread.return_value = None
    spreads.create_spread.side_effect = lambda spread: spread
    spreads.update_spread.side_effect = lambda spread, **kwargs: spread
    runtime_states = Mock()
    pre_open_runs = Mock()
    runtime_store: dict[str, object] = {}
    pre_open_store: dict[tuple[str, date, str], object] = {}

    def get_runtime_state(*, external_account_id: str, strategy_id: str = "paper_bull_put_v1"):
        return runtime_store.get((external_account_id, strategy_id))

    def upsert_runtime_state(state):
        runtime_store[(state.external_account_id, state.strategy_id)] = state
        return state

    runtime_states.get_runtime_state.side_effect = get_runtime_state
    runtime_states.lock_for_entry.side_effect = get_runtime_state
    runtime_states.upsert_runtime_state.side_effect = upsert_runtime_state
    pre_open_runs.get_by_session_date.side_effect = (
        lambda *, external_account_id, target_session_date, strategy_id="pre_open_put_check_v1": pre_open_store.get(
            (external_account_id, target_session_date, strategy_id)
        )
    )
    pre_open_runs.list_runs.side_effect = (
        lambda *, external_account_id=None, limit=20: [
            run
            for key, run in sorted(pre_open_store.items(), key=lambda item: item[1].target_session_date, reverse=True)
            if external_account_id is None or key[0] == external_account_id
        ][:limit]
    )
    pre_open_runs.upsert_run.side_effect = (
        lambda run: pre_open_store.__setitem__((run.external_account_id, run.target_session_date, run.strategy_id), run) or run
    )
    journal_service = Mock()

    settings = Settings(bull_put_strategy={"entry_kill_switch_active": False})
    service = BullPutStrategyService(
        settings=settings,
        broker_accounts=broker_accounts,
        account_snapshots=account_snapshots,
        spreads=spreads,
        runtime_states=runtime_states,
        pre_open_runs=pre_open_runs,
        order_service=order_service,
        longbridge_adapter=adapter,
        risk_service=RiskService(settings=settings),
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
    executed_quantity: int = 0,
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
        executed_quantity=executed_quantity,
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


def test_bull_put_p0_defaults_are_fail_closed_and_single_contract() -> None:
    strategy = Settings().bull_put_strategy

    assert strategy.entry_kill_switch_active is True
    assert strategy.contracts_per_trade == 1
    assert strategy.max_option_quote_age_seconds == 15

    with pytest.raises(ValueError, match="contracts_per_trade=1"):
        Settings(bull_put_strategy={"contracts_per_trade": 2})


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
    assert result.candidate_token is not None
    assert result.risk is not None
    assert result.risk.max_profit == Decimal("145.00")
    assert result.risk.max_loss == Decimal("170.00")
    assert adapter.get_best_bid_ask.call_count >= 2


def test_top_of_book_uses_quote_bid_ask_without_depth_lookup() -> None:
    service, adapter, _, _ = build_service()
    quote = build_option_quotes()[0].model_copy(
        update={
            "bid": Decimal("2.40"),
            "ask": Decimal("2.60"),
        }
    )

    enriched = service._with_top_of_book(quote, mode=ExecutionMode.PAPER)

    assert enriched == quote
    adapter.get_best_bid_ask.assert_not_called()


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


def test_preview_spread_rejects_cached_underlying_quote_for_entry() -> None:
    cached_quote = build_underlying_quote().model_copy(
        update={
            "data_quality": "cached",
            "warning_code": "longbridge_quote_cache_fallback",
            "cache_age_seconds": 4,
        }
    )
    service, _, _, _ = build_service(underlying_quote=cached_quote)

    result = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )

    assert result.eligible is False
    assert any("cached quote" in reason.lower() for reason in result.reasons)


def test_preview_spread_rejects_stale_underlying_quote_for_entry() -> None:
    stale_quote = build_underlying_quote().model_copy(
        update={"timestamp": build_scan_time() - timedelta(seconds=16)}
    )
    service, _, _, _ = build_service(underlying_quote=stale_quote)

    result = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )

    assert result.eligible is False
    assert any("underlying quote is stale" in reason.lower() for reason in result.reasons)


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


def test_preview_spread_blocks_low_leg_volume() -> None:
    service, _, _, _ = build_service()
    service.settings.bull_put_strategy.min_short_leg_volume = 10_000

    result = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )

    assert result.eligible is False
    assert any("volume" in reason for reason in result.reasons)
    assert result.timing_ms["total"] >= 0


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
        ),
        idempotency_key="bull-reprice-parent-key-0001",
    )

    assert spread.status == SpreadStatus.OPEN
    assert spread.long_entry_order_id == "long-entry"
    assert spread.short_entry_order_id == "short-entry"
    assert spread.entry_long_price == Decimal("1.10")
    assert spread.entry_short_price == Decimal("2.40")
    assert spread.entry_net_credit == Decimal("1.30")
    assert spread.max_profit == Decimal("130.00")
    assert spread.max_loss == Decimal("170.00")
    assert spread.break_even == Decimal("468.70")
    first_submit, second_submit = order_service.submit_order.call_args_list
    assert first_submit.kwargs["idempotency_key"].startswith("strategy:")
    assert second_submit.kwargs["idempotency_key"].startswith("strategy:")
    assert first_submit.kwargs["idempotency_key"] != second_submit.kwargs["idempotency_key"]
    assert first_submit.kwargs["action_context"].leg == "long_entry"
    assert second_submit.kwargs["action_context"].leg == "short_entry"


def test_execute_spread_locks_runtime_before_capacity_check_and_broker_submit() -> None:
    service, _, spreads, order_service = build_service()
    events: list[str] = []
    service.runtime_states.lock_for_entry.side_effect = lambda **kwargs: (
        events.append("runtime-lock")
        or service.runtime_states.get_runtime_state(**kwargs)
    )
    spreads.list_spreads.return_value = []
    spreads.create_spread.side_effect = lambda spread: events.append("spread-reserved") or spread
    submitted_orders = iter(
        [
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
    )
    order_service.submit_order.side_effect = lambda *args, **kwargs: (
        events.append("broker-submit") or next(submitted_orders)
    )

    service.execute_spread(
        ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        )
    )

    assert events[:3] == [
        "runtime-lock",
        "spread-reserved",
        "broker-submit",
    ]


def test_failed_entry_attempt_consumes_daily_capacity_before_broker_submit() -> None:
    service, _, spreads, order_service = build_service()
    attempted_at = build_scan_time()
    spreads.list_spreads.return_value = [
        build_open_spread(status=SpreadStatus.ENTRY_FAILED).model_copy(
            update={
                "entry_started_at": attempted_at,
                "created_at": attempted_at,
                "updated_at": attempted_at,
            }
        )
    ]

    with pytest.raises(ValueError, match="daily bull put entry-attempt capacity"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=attempted_at,
            )
        )

    order_service.submit_order.assert_not_called()


def test_execute_spread_rejects_changed_locked_candidate() -> None:
    service, _, _, order_service = build_service()

    with pytest.raises(ValueError, match="candidate changed"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
                candidate_token="stale-token",
            )
        )

    order_service.submit_order.assert_not_called()


def test_execute_spread_reuses_locked_preview_and_refreshes_selected_legs() -> None:
    service, adapter, _, order_service = build_service()
    preview = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )
    assert preview.candidate_token is not None
    adapter.list_option_chain.side_effect = AssertionError("full option-chain rescan should not run")
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
            candidate_token=preview.candidate_token,
            minimum_net_credit=preview.candidate.conservative_credit if preview.candidate else None,
        )
    )

    assert spread.status == SpreadStatus.OPEN
    assert spread.long_symbol == "QQQ260619P467000.US"
    assert spread.short_symbol == "QQQ260619P470000.US"
    qqq_calls = [
        call
        for call in adapter.get_quote.call_args_list
        if call.kwargs.get("symbol") == "QQQ.US" or (call.args and call.args[0] == "QQQ.US")
    ]
    assert len(qqq_calls) == 2


def test_execute_spread_blocks_when_refreshed_underlying_is_cached() -> None:
    service, adapter, _, order_service = build_service()
    preview = service.preview_spread(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )
    assert preview.candidate_token is not None
    adapter.get_quote.side_effect = None
    adapter.get_quote.return_value = build_underlying_quote().model_copy(
        update={"data_quality": "cached", "warning_code": "quote_cache_fallback"}
    )

    with pytest.raises(ValueError, match="Cached quote evidence"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
                candidate_token=preview.candidate_token,
            )
        )

    order_service.submit_order.assert_not_called()


def test_execute_spread_uses_buffered_long_limit_and_waits_for_fill() -> None:
    service, _, _, order_service = build_service()
    service.settings.bull_put_strategy.entry_fill_timeout_seconds = 10
    service.settings.bull_put_strategy.entry_fill_poll_interval_seconds = 0
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("1.20"),
        ),
        build_option_order(
            order_id="short-entry",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
        ),
    ]
    order_service.refresh_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("1.20"),
        ),
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.20"),
        ),
    ]

    with patch("stocks_tool.application.services.bull_put_strategy.time.monotonic", side_effect=[0, 0, 1]):
        spread = service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            )
        )

    assert spread.status == SpreadStatus.OPEN
    assert order_service.submit_order.call_args_list[0].args[0].limit_price == Decimal("1.10")
    assert order_service.refresh_order.call_count == 2


def test_execute_spread_reprices_long_leg_before_fill() -> None:
    service, _, _, order_service = build_service()
    service.settings.bull_put_strategy.entry_fill_timeout_seconds = 0
    service.settings.bull_put_strategy.entry_reprice_increment = Decimal("0.05")
    service.settings.bull_put_strategy.entry_reprice_max_steps = 2
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry-1",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("1.10"),
        ),
        build_option_order(
            order_id="long-entry-2",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.15"),
        ),
        build_option_order(
            order_id="short-entry",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
        ),
    ]
    order_service.refresh_order.side_effect = [
        build_option_order(
            order_id="long-entry-1",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("1.10"),
        )
    ]
    order_service.cancel_order.return_value = build_option_order(
        order_id="long-entry-1",
        symbol="QQQ260619P467000.US",
        side=OrderSide.BUY,
        status=OrderStatus.CANCELED,
        limit_price=Decimal("1.10"),
    )

    spread = service.execute_spread(
        ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        ),
        idempotency_key="bull-reprice-parent-key-0002",
    )

    assert spread.status == SpreadStatus.OPEN
    assert order_service.submit_order.call_args_list[0].args[0].limit_price == Decimal("1.10")
    assert order_service.submit_order.call_args_list[1].args[0].limit_price == Decimal("1.15")
    assert {
        call_args.kwargs["parent_action_intent_id"]
        for call_args in order_service.submit_order.call_args_list
    } == {"parent-action-1"}
    assert order_service.cancel_order.call_args.kwargs["parent_action_intent_id"] == "parent-action-1"
    assert (
        order_service.cancel_order.call_args.kwargs["action_context"].entity_id
        == order_service.submit_order.call_args_list[0].kwargs["action_context"].entity_id
    )


def test_execute_spread_blocks_outside_regular_session() -> None:
    service, _, _, _ = build_service()

    try:
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=datetime(2026, 5, 22, 12, 15, tzinfo=timezone.utc),
            )
        )
    except ValueError as exc:
        assert str(exc) == "Bull put entries only execute during regular U.S. options hours (09:30-16:00 ET)."
    else:
        raise AssertionError("Expected execute_spread to block outside regular U.S. options hours.")


def test_execute_spread_waits_for_opening_confirmation_window() -> None:
    service, _, _, _ = build_service()

    with pytest.raises(ValueError, match="opening confirmation window"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=datetime(2026, 5, 22, 13, 35, tzinfo=timezone.utc),
            )
        )


def test_check_entry_readiness_reports_ready_candidate() -> None:
    service, _, _, _ = build_service()

    result = service.check_entry_readiness(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )

    assert result.ready is True
    assert result.status == "ready"
    assert result.preferred_symbol == "QQQ.US"
    assert any(check.name == "entry_window" and check.status == "ok" for check in result.checks)
    assert any(preview.eligible for preview in result.previews)


def test_check_entry_readiness_blocks_before_opening_confirmation() -> None:
    service, _, _, _ = build_service()

    result = service.check_entry_readiness(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=datetime(2026, 5, 22, 13, 35, tzinfo=timezone.utc),
    )

    assert result.ready is False
    assert result.status == "blocked"
    assert any(check.name == "entry_window" and check.blocking for check in result.checks)
    assert result.previews == []


def test_execute_spread_rolls_back_when_short_leg_does_not_fill() -> None:
    service, _, _, order_service = build_service()
    service.settings.bull_put_strategy.entry_fill_timeout_seconds = 0
    service.settings.bull_put_strategy.entry_reprice_max_steps = 1
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
        ),
        build_option_order(
            order_id="short-entry-1",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("2.40"),
        ),
        build_option_order(
            order_id="short-entry-2",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("2.35"),
        ),
        build_option_order(
            order_id="long-exit",
            symbol="QQQ260619P467000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=None,
        ),
    ]
    order_service.refresh_order.side_effect = [
        build_option_order(
            order_id="short-entry-1",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.CANCELED,
            limit_price=Decimal("2.40"),
        ),
        build_option_order(
            order_id="short-entry-2",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.CANCELED,
            limit_price=Decimal("2.35"),
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

    assert spread.status == SpreadStatus.ROLLED_BACK
    assert spread.short_entry_order_id == "short-entry-2"
    assert spread.long_exit_order_id == "long-exit"
    assert spread.exit_reason == "short_entry_unfilled"


def test_execute_spread_retains_long_hedge_when_short_submit_outcome_is_unknown() -> None:
    service, _, _, order_service = build_service()
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            executed_quantity=1,
        ),
        TradingIntentOutcomeUnknownError("short-intent-1"),
    ]

    with pytest.raises(TradingIntentOutcomeUnknownError):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            )
        )

    persisted = service.spreads.update_spread.call_args.args[0]
    assert persisted.status == SpreadStatus.ENTRY_PENDING_SHORT
    assert persisted.manual_action_required is True
    assert persisted.lifecycle_warning_code == "short_entry_outcome_unknown"
    assert persisted.long_exit_order_id is None
    assert order_service.submit_order.call_count == 2


def test_execute_spread_marks_unknown_long_submit_for_manual_action() -> None:
    service, _, _, order_service = build_service()
    order_service.submit_order.side_effect = TradingIntentOutcomeUnknownError("long-intent-1")

    with pytest.raises(TradingIntentOutcomeUnknownError):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            )
        )

    persisted = service.spreads.update_spread.call_args.args[0]
    assert persisted.status == SpreadStatus.ENTRY_PENDING_LONG
    assert persisted.manual_action_required is True
    assert persisted.lifecycle_warning_code == "long_entry_outcome_unknown"
    assert order_service.submit_order.call_count == 1


def test_execute_spread_links_long_order_and_stops_when_local_link_initially_fails() -> None:
    service, _, spreads, order_service = build_service()
    order_service.submit_order.return_value = build_option_order(
        order_id="long-entry",
        symbol="QQQ260619P467000.US",
        side=OrderSide.BUY,
        status=OrderStatus.FILLED,
        limit_price=Decimal("1.10"),
        executed_quantity=1,
    )

    def update_spread(spread: BullPutSpread, **kwargs) -> BullPutSpread:
        if spread.long_entry_order_id == "long-entry" and not spread.manual_action_required:
            raise ValueError("local spread link failed")
        return spread

    spreads.update_spread.side_effect = update_spread

    result = service.execute_spread(
        ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        )
    )

    assert result.status == SpreadStatus.ENTRY_PENDING_LONG
    assert result.long_entry_order_id == "long-entry"
    assert result.manual_action_required is True
    assert result.lifecycle_warning_code == "long_entry_link_failed"
    assert order_service.submit_order.call_count == 1


def test_execute_spread_retains_hedge_and_links_short_when_local_link_initially_fails() -> None:
    service, _, spreads, order_service = build_service()
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            executed_quantity=1,
        ),
        build_option_order(
            order_id="short-entry",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
            executed_quantity=1,
        ),
    ]

    def update_spread(spread: BullPutSpread, **kwargs) -> BullPutSpread:
        if spread.short_entry_order_id == "short-entry" and not spread.manual_action_required:
            raise ValueError("local spread link failed")
        return spread

    spreads.update_spread.side_effect = update_spread

    result = service.execute_spread(
        ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        )
    )

    assert result.status == SpreadStatus.ENTRY_PENDING_SHORT
    assert result.long_entry_order_id == "long-entry"
    assert result.short_entry_order_id == "short-entry"
    assert result.manual_action_required is True
    assert result.lifecycle_warning_code == "short_entry_link_failed"
    assert result.long_exit_order_id is None
    assert order_service.submit_order.call_count == 2


def test_execute_spread_does_not_reprice_while_cancel_is_still_pending() -> None:
    service, _, _, order_service = build_service()
    service.settings.bull_put_strategy.entry_fill_timeout_seconds = 0
    service.settings.bull_put_strategy.entry_reprice_max_steps = 2
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            executed_quantity=1,
        ),
        build_option_order(
            order_id="short-entry-1",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.SUBMITTED,
            limit_price=Decimal("2.40"),
        ),
    ]
    order_service.refresh_order.return_value = build_option_order(
        order_id="short-entry-1",
        symbol="QQQ260619P470000.US",
        side=OrderSide.SELL,
        status=OrderStatus.SUBMITTED,
        limit_price=Decimal("2.40"),
    )
    order_service.cancel_order.return_value = build_option_order(
        order_id="short-entry-1",
        symbol="QQQ260619P470000.US",
        side=OrderSide.SELL,
        status=OrderStatus.SUBMITTED,
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

    assert spread.manual_action_required is True
    assert order_service.submit_order.call_count == 2


def test_execute_spread_does_not_reprice_after_partial_fill_cancel() -> None:
    service, _, _, order_service = build_service()
    service.settings.bull_put_strategy.entry_fill_timeout_seconds = 0
    service.settings.bull_put_strategy.entry_reprice_max_steps = 2
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            executed_quantity=1,
        ),
        build_option_order(
            order_id="short-entry-1",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.PARTIALLY_FILLED,
            limit_price=Decimal("2.40"),
            executed_quantity=1,
        ),
    ]
    order_service.refresh_order.return_value = build_option_order(
        order_id="short-entry-1",
        symbol="QQQ260619P470000.US",
        side=OrderSide.SELL,
        status=OrderStatus.PARTIALLY_FILLED,
        limit_price=Decimal("2.40"),
        executed_quantity=1,
    )
    order_service.cancel_order.return_value = build_option_order(
        order_id="short-entry-1",
        symbol="QQQ260619P470000.US",
        side=OrderSide.SELL,
        status=OrderStatus.CANCELED,
        limit_price=Decimal("2.40"),
        executed_quantity=1,
    )

    spread = service.execute_spread(
        ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        )
    )

    assert spread.manual_action_required is True
    assert order_service.submit_order.call_count == 2


def test_execute_spread_replays_action_before_capacity_and_conflicts_on_changed_request() -> None:
    service, _, spreads, order_service = build_service()
    stored: dict[str, BullPutSpread] = {}

    def create_spread(spread: BullPutSpread) -> BullPutSpread:
        stored[spread.id] = spread
        return spread

    def update_spread(spread: BullPutSpread, *, expected_version: int) -> BullPutSpread:
        assert stored[spread.id].version == expected_version
        saved = spread.model_copy(update={"version": expected_version + 1})
        stored[saved.id] = saved
        return saved

    spreads.get_spread.side_effect = lambda spread_id: stored.get(spread_id)
    spreads.list_spreads.side_effect = lambda **kwargs: list(stored.values())
    spreads.create_spread.side_effect = create_spread
    spreads.update_spread.side_effect = update_spread
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            executed_quantity=1,
        ),
        build_option_order(
            order_id="short-entry",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
            executed_quantity=1,
        ),
    ]
    request = ExecuteBullPutSpreadRequest(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )

    first = service.execute_spread(request, idempotency_key="bull-action-0001")
    replay = service.execute_spread(request, idempotency_key="bull-action-0001")

    assert first.status == SpreadStatus.OPEN
    assert replay.model_dump() == first.model_dump()
    assert replay.idempotent_replayed is True
    assert order_service.submit_order.call_count == 2
    child_parent_ids = {
        call_args.kwargs["parent_action_intent_id"]
        for call_args in order_service.submit_order.call_args_list
    }
    child_keys = {
        call_args.kwargs["idempotency_key"]
        for call_args in order_service.submit_order.call_args_list
    }
    assert child_parent_ids == {"parent-action-1"}
    assert len(child_keys) == 2
    assert "bull-action-0001" not in child_keys
    assert order_service.has_unresolved_intents.call_args.kwargs[
        "exclude_action_intent_id"
    ] == "parent-action-1"

    with pytest.raises(ValueError, match="already used for a different request"):
        service.execute_spread(
            request.model_copy(update={"symbol": "SMH.US"}),
            idempotency_key="bull-action-0001",
        )
    assert order_service.submit_order.call_count == 2


def test_force_scan_replay_without_as_of_ignores_new_server_time_and_skips_sync() -> None:
    service, _, spreads, order_service = build_service()
    key = "bull-force-scan-key-0001"
    spread_id, request_hash = service._bull_put_action_identity_for_payload(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        idempotency_key=key,
        request_payload={
            "action": "bull_put_scan",
            "external_account_id": "LBPT10087357",
            "mode": "paper",
            "force": True,
            "as_of": None,
        },
    )
    existing = build_open_spread().model_copy(
        update={
            "id": spread_id,
            "raw_payload": {"action_request_hash": request_hash},
        }
    )
    spreads.get_spread.return_value = existing

    result = service.run_entry_scan(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        force=True,
        idempotency_key=key,
    )

    assert result.executed_spread is not None
    assert result.executed_spread.id == spread_id
    assert result.executed_spread.idempotent_replayed is True
    order_service.sync_today_orders.assert_not_called()


def test_execute_spread_replays_persisted_parent_action_before_sync() -> None:
    service, _, _, order_service = build_service()
    original = build_open_spread().model_copy(
        update={
            "id": "parent-replay-spread",
            "raw_payload": {"action_request_hash": "stored-by-parent"},
        }
    )
    order_service.prepare_trade_action.side_effect = None
    order_service.prepare_trade_action.return_value = PreparedTradeActionIntent(
        intent=TradeActionIntent(
            id="parent-replay-action",
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key="parent-replay-key-0001",
            request_hash="request-hash",
            action="bull_put_execute",
            strategy_id="paper_bull_put_v1",
            entity_id=original.id,
            state=TradingIntentState.PERSISTED,
            request_payload={},
            response_payload=original.model_dump(mode="json"),
            created_at=build_scan_time(),
            updated_at=build_scan_time(),
        ),
        created=False,
    )

    replay = service.execute_spread(
        ExecuteBullPutSpreadRequest(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            mode=ExecutionMode.PAPER,
            as_of=build_scan_time(),
        ),
        idempotency_key="parent-replay-key-0001",
    )

    assert replay.model_dump() == original.model_dump()
    assert replay.idempotent_replayed is True
    order_service.sync_today_orders.assert_not_called()
    order_service.submit_order.assert_not_called()


def test_execute_spread_parent_action_changed_payload_conflicts_before_sync() -> None:
    service, _, _, order_service = build_service()
    order_service.prepare_trade_action.side_effect = TradingIntentConflictError(
        "parent-conflict-action"
    )

    with pytest.raises(TradingIntentConflictError) as exc_info:
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            ),
            idempotency_key="parent-conflict-key-0001",
        )

    assert exc_info.value.intent_id == "parent-conflict-action"
    order_service.sync_today_orders.assert_not_called()
    order_service.submit_order.assert_not_called()


def test_execute_spread_marks_shared_parent_unknown_after_hedge_then_unknown_short() -> None:
    service, _, _, order_service = build_service()
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
            executed_quantity=1,
        ),
        TradingIntentOutcomeUnknownError("short-child-unknown"),
    ]

    with pytest.raises(TradingIntentOutcomeUnknownError):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            ),
            idempotency_key="parent-unknown-key-0001",
        )

    assert {
        call_args.kwargs["parent_action_intent_id"]
        for call_args in order_service.submit_order.call_args_list
    } == {"parent-action-1"}
    order_service.mark_trade_action_unknown.assert_called_with(
        "parent-action-1",
        "Broker mutation outcome is unknown; do not retry with a new key.",
    )
    persisted = service.spreads.update_spread.call_args.args[0]
    assert persisted.manual_action_required is True
    assert persisted.status == SpreadStatus.ENTRY_PENDING_SHORT

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


def test_execute_spread_blocks_when_trading_intent_is_unresolved() -> None:
    service, _, _, order_service = build_service()
    order_service.has_unresolved_intents.return_value = True

    with pytest.raises(ValueError, match="unresolved trading intent"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            )
        )

    order_service.submit_order.assert_not_called()


def test_execute_spread_blocks_when_current_cycle_order_sync_fails() -> None:
    service, _, _, order_service = build_service()
    order_service.sync_today_orders.side_effect = RuntimeError("order sync failed")

    with pytest.raises(ValueError, match="current-cycle order/account synchronization failed"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            ),
            idempotency_key="sync-failure-parent-key-0001",
        )

    order_service.submit_order.assert_not_called()
    order_service.mark_trade_action_rejected.assert_called_with(
        "parent-action-1",
        "Bull Put entry is blocked because current-cycle order/account synchronization failed.",
    )


def test_execute_spread_blocks_same_day_option_position_mapped_as_stock() -> None:
    snapshot = build_account_snapshot()
    snapshot.positions.append(
        PositionSnapshot(
            symbol="QQQ260522P470000.US",
            asset_type=AssetType.STOCK,
            quantity=Decimal("1"),
            average_cost=Decimal("2.50"),
            market_value=Decimal("250"),
            unrealized_pnl=Decimal("0"),
        )
    )
    service, _, _, order_service = build_service(account_snapshot=snapshot)
    audit_events = Mock()
    service.audit_events = audit_events

    with pytest.raises(ValueError, match="current-cycle order/account synchronization failed"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            ),
            idempotency_key="bull-same-day-option-key-0001",
        )

    order_service.submit_order.assert_not_called()
    order_service.mark_trade_action_rejected.assert_called_once()
    warning = audit_events.create_event.call_args.args[0]
    assert warning.warning_code == "same_day_option_position_requires_manual_action"
    assert warning.payload["severity"] == "critical"
    assert warning.payload["manual_action_required"] is True
    order_service.mark_trade_action_unknown.assert_not_called()


def test_reconciled_unknown_short_entry_is_linked_and_remains_manual() -> None:
    service, _, spreads, order_service = build_service()
    spread = build_open_spread(status=SpreadStatus.ENTRY_PENDING_SHORT).model_copy(
        update={
            "short_entry_order_id": None,
            "manual_action_required": True,
            "lifecycle_warning_code": "short_entry_outcome_unknown",
        }
    )
    spreads.get_spread.return_value = spread
    order_service.list_trading_intents.return_value = [
        BrokerOrderIntent(
            id="short-intent-1",
            trade_action_intent_id="short-action-1",
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key="strategy-short-entry",
            request_hash="request-hash",
            operation=TradingOperation.SUBMIT,
            action="bull_put_entry",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-1:publickeyhash",
            leg="short_entry",
            broker_marker="st:0123456789abcdef",
            state=TradingIntentState.PERSISTED,
            request_payload={},
            response_payload={"id": "short-entry-reconciled"},
            created_at=build_scan_time(),
            updated_at=build_scan_time(),
        )
    ]

    linked = service.relink_reconciled_order_intents(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    assert linked == 1
    persisted = spreads.update_spread.call_args.args[0]
    assert persisted.short_entry_order_id == "short-entry-reconciled"
    assert persisted.manual_action_required is True
    assert persisted.lifecycle_warning_code == "reconciled_leg_linked_manual_review"


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


def test_runtime_state_reports_monitor_next_action_for_open_spread() -> None:
    service, _, spreads, _ = build_service()
    spreads.list_spreads.return_value = [build_open_spread()]

    runtime = service.get_runtime_state(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )

    assert runtime.holding_open_position is True
    assert runtime.active_spread_count == 1
    assert runtime.open_spread_count == 1
    assert runtime.next_action == "monitor_open_spread"


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


def test_run_entry_scan_pre_window_does_not_block_later_due_window() -> None:
    service, _, _, order_service = build_service()
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="long-entry-after-pre-window",
            symbol="QQQ260619P467000.US",
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
        ),
        build_option_order(
            order_id="short-entry-after-pre-window",
            symbol="QQQ260619P470000.US",
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
        ),
    ]

    early = service.run_entry_scan(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc),
    )
    due = service.run_entry_scan(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=build_scan_time(),
    )

    assert early.executed is False
    assert early.reason is not None
    assert due.executed is True
    parent_keys = [
        call_args.kwargs["idempotency_key"]
        for call_args in order_service.prepare_trade_action.call_args_list
    ]
    assert len(parent_keys) == 2
    assert parent_keys[0] != parent_keys[1]
    assert order_service.submit_order.call_count == 2


def test_run_entry_scan_replays_exact_success_result_before_sync() -> None:
    service, _, _, order_service = build_service()
    scanned_at = datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc)
    key = "bull-scan-not-due-replay-key-0001"

    first = service.run_entry_scan(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=scanned_at,
        idempotency_key=key,
    )
    response_payload = order_service.complete_trade_action.call_args.args[1]
    sync_calls_after_first = order_service.sync_today_orders.call_count
    order_service.prepare_trade_action.side_effect = None
    order_service.prepare_trade_action.return_value = PreparedTradeActionIntent(
        intent=TradeActionIntent(
            id="persisted-scan-parent",
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key=key,
            request_hash="persisted-scan-hash",
            action="bull_put_scan",
            strategy_id="paper_bull_put_v1",
            entity_id="persisted-scan-entity",
            state=TradingIntentState.PERSISTED,
            request_payload={},
            response_payload=response_payload,
            created_at=scanned_at,
            updated_at=scanned_at,
        ),
        created=False,
    )

    replay = service.run_entry_scan(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=scanned_at,
        idempotency_key=key,
    )

    assert replay.model_dump(mode="json") == first.model_dump(mode="json")
    assert order_service.sync_today_orders.call_count == sync_calls_after_first


def test_run_review_returns_not_due_before_threshold() -> None:
    service, _, spreads, _ = build_service()
    closed_at = datetime(2026, 5, 20, 14, 45, tzinfo=timezone.utc)
    spreads.list_spreads.side_effect = lambda external_account_id=None, status=None: (
        [build_closed_spread(spread_id="closed-1", closed_at=closed_at, exit_reason="take_profit")]
        if status == SpreadStatus.CLOSED
        else []
    )

    result = service.run_review(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc),
    )

    assert result.review_status == "not_due"
    assert result.reason == "Bull put review is not due yet."


def test_pre_open_downside_assessment_prefers_qqq_puts_when_semis_and_qqq_are_weaker() -> None:
    service, adapter, _, _ = build_service()

    result = service.get_pre_open_downside_assessment(
        as_of=datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
    )

    adapter.get_quotes.assert_any_call(
        symbols=["SPY.US", "QQQ.US", "SOXX.US", "USO.US", "TLT.US"],
        mode=ExecutionMode.PAPER,
    )
    assert result.session == "premarket"
    assert result.market_open is False
    assert result.downside_score >= 5
    assert result.preferred_vehicle == "QQQ"
    assert result.plain_put_view == "reasonable"
    assert result.trade_action == "wait_for_failed_bounce"
    assert result.gap_chase_risk == "high"
    assert len(result.checkpoints) == 4
    assert {snapshot.underlying_symbol for snapshot in result.put_snapshots} == {"SPY.US", "QQQ.US"}
    qqq_snapshot = next(snapshot for snapshot in result.put_snapshots if snapshot.underlying_symbol == "QQQ.US")
    assert qqq_snapshot.mid_price == Decimal("3.74")
    assert qqq_snapshot.spread_width == Decimal("0.20")
    assert qqq_snapshot.spread_pct == Decimal("5.35")
    assert qqq_snapshot.distance_from_spot_pct == Decimal("0.40")
    assert qqq_snapshot.liquidity_label == "workable"
    assert {analysis.underlying_symbol for analysis in result.chain_analyses} == {"SPY.US", "QQQ.US"}
    qqq_analysis = next(analysis for analysis in result.chain_analyses if analysis.underlying_symbol == "QQQ.US")
    assert qqq_analysis.front_expiration is not None
    assert qqq_analysis.next_expiration is not None
    assert qqq_analysis.front_expiration.atm_strike == Decimal("498")
    assert qqq_analysis.front_expiration.put_skew_diff == Decimal("0.0000")
    assert qqq_analysis.front_expiration.median_spread_pct == Decimal("5.77")
    assert qqq_analysis.next_expiration.atm_strike == Decimal("500")
    assert qqq_analysis.atm_iv_term_diff == Decimal("0.0200")
    assert qqq_analysis.term_structure_label == "next_richer"


def test_pre_open_assessment_targets_next_trading_day_on_memorial_day() -> None:
    service, _, _, _ = build_service()

    result = service.get_pre_open_downside_assessment(
        as_of=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
    )

    assert result.session == "holiday"
    assert result.target_session_date == date(2026, 5, 26)
    assert result.next_regular_open_at is not None
    assert result.next_regular_open_at.astimezone(service.new_york).date() == date(2026, 5, 26)


def test_pre_open_assessment_can_skip_option_overlays_for_fast_board() -> None:
    service, adapter, _, _ = build_service()

    result = service.get_pre_open_downside_assessment(
        as_of=datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
        include_option_overlays=False,
    )

    assert result.freshness_status == "partial"
    assert "Option overlays skipped" in (result.freshness_detail or "")
    assert result.signals
    assert result.put_snapshots == []
    assert result.chain_analyses == []
    adapter.list_option_expiry_dates.assert_not_called()


def test_capture_pre_open_run_persists_assessment_for_next_session() -> None:
    service, _, _, _ = build_service()

    result = service.capture_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
    )

    assert result.captured is True
    assert result.run.target_session_date == date(2026, 5, 26)
    assert result.run.review_status == "awaiting_open"
    assert len(result.run.checkpoints) == 3
    assert service.journal_service.create_entry.call_count >= 1


def test_capture_pre_open_run_persists_partial_assessment_when_only_spy_proxy_is_available() -> None:
    service, adapter, _, _ = build_service()
    original_get_quotes = adapter.get_quotes.side_effect

    def partial_get_quotes(symbols, mode):
        quotes = original_get_quotes(symbols, mode)
        return {"SPY.US": quotes["SPY.US"]}

    adapter.get_quotes.side_effect = partial_get_quotes

    result = service.capture_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
        force=True,
    )

    assert result.captured is True
    assert result.run.assessment.freshness_status == "partial"
    assert [signal.symbol for signal in result.run.assessment.signals] == ["SPY.US"]
    assert "Missing signals" in (result.run.assessment.freshness_detail or "")


def test_get_pre_open_assessment_falls_back_to_latest_persisted_run_on_transient_failure() -> None:
    service, adapter, _, _ = build_service()
    captured = service.capture_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
    )
    adapter.get_quotes.side_effect = LongbridgeIntegrationError(
        "Longbridge timed out while trying to load quotes for SPY.US, QQQ.US, SOXX.US, USO.US, TLT.US after 20s."
    )

    result = service.get_pre_open_downside_assessment(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
    )

    assert result.freshness_status == "stale"
    assert result.source_run_id == captured.run.id
    assert "timed out" in (result.stale_reason or "").lower()
    assert "latest stored pre-open board" in (result.freshness_detail or "").lower()
    assert result.summary == captured.run.assessment.summary


def test_get_pre_open_assessment_returns_unavailable_board_without_persisted_fallback() -> None:
    service, adapter, _, _ = build_service()
    adapter.get_quotes.side_effect = LongbridgeIntegrationError(
        "Longbridge timed out while trying to load quotes for SPY.US, QQQ.US, SOXX.US, USO.US, TLT.US after 20s."
    )

    result = service.get_pre_open_downside_assessment(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
    )

    assert result.freshness_status == "error"
    assert result.regime == "unavailable"
    assert "no stored pre-open board" in (result.freshness_detail or "").lower()
    assert "timed out" in (result.stale_reason or "").lower()


def test_get_pre_open_assessment_raises_without_fallback_when_disabled() -> None:
    service, adapter, _, _ = build_service()
    adapter.get_quotes.side_effect = LongbridgeIntegrationError(
        "Longbridge timed out while trying to load quotes for SPY.US, QQQ.US, SOXX.US, USO.US, TLT.US after 20s."
    )

    with pytest.raises(LongbridgeIntegrationError, match="timed out"):
        service.get_pre_open_downside_assessment(
            external_account_id="LBPT10087357",
            as_of=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
            allow_fallback=False,
        )


def test_get_pre_open_assessment_keeps_partial_board_when_optional_proxy_times_out() -> None:
    service, adapter, _, _ = build_service()
    original_get_quotes = adapter.get_quotes.side_effect

    def partial_get_quotes(symbols, mode):
        quotes = original_get_quotes(symbols, mode)
        quotes.pop("SOXX.US")
        return quotes

    adapter.get_quotes.side_effect = partial_get_quotes

    result = service.get_pre_open_downside_assessment(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
    )

    assert result.freshness_status == "partial"
    assert "Semiconductor Proxy" in (result.freshness_detail or "")
    assert all(signal.key != "semis" for signal in result.signals)
    assert result.preferred_vehicle in {"SPY", "QQQ", None}


def test_get_pre_open_assessment_keeps_partial_board_when_spy_proxy_times_out() -> None:
    service, adapter, _, _ = build_service()
    original_get_quotes = adapter.get_quotes.side_effect

    def partial_get_quotes(symbols, mode):
        quotes = original_get_quotes(symbols, mode)
        quotes.pop("SPY.US")
        return quotes

    adapter.get_quotes.side_effect = partial_get_quotes

    result = service.get_pre_open_downside_assessment(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
    )

    assert result.freshness_status == "partial"
    assert "S&P 500 ETF" in (result.freshness_detail or "")
    assert all(signal.key != "spy" for signal in result.signals)
    assert all(analysis.underlying_symbol != "SPY.US" for analysis in result.chain_analyses)


def test_get_pre_open_assessment_keeps_partial_board_when_option_chain_overlay_times_out() -> None:
    service, adapter, _, _ = build_service()
    original_list_option_expiry_dates = adapter.list_option_expiry_dates.side_effect

    def flaky_list_option_expiry_dates(symbol, mode):
        if symbol == "QQQ.US":
            raise LongbridgeIntegrationError(
                "Longbridge timed out while trying to load option expiry dates for 'QQQ.US' after 6s."
            )
        return original_list_option_expiry_dates(symbol, mode)

    adapter.list_option_expiry_dates.side_effect = flaky_list_option_expiry_dates

    result = service.get_pre_open_downside_assessment(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
    )

    assert result.freshness_status == "partial"
    assert "Option-chain analysis unavailable for QQQ.US." in (result.freshness_detail or "")
    assert any(signal.symbol == "QQQ.US" for signal in result.signals)
    assert all(analysis.underlying_symbol != "QQQ.US" for analysis in result.chain_analyses)


def test_review_pre_open_run_updates_opening_checkpoints_and_final_status() -> None:
    service, _, _, _ = build_service()
    capture = service.capture_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
    )

    first = service.review_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 13, 30, tzinfo=timezone.utc),
    )

    assert first.reviewed is True
    assert first.updated_checkpoint_keys == ["open"]
    assert first.run is not None
    assert first.run.review_status == "in_progress"
    assert first.run.checkpoints[0].confirmation == "failed"

    final = service.review_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 14, 0, tzinfo=timezone.utc),
    )

    assert final.reviewed is True
    assert final.run is not None
    assert final.run.review_status == "failed"
    assert final.run.review_completed_at is not None
    assert set(final.updated_checkpoint_keys) == {"first_15", "first_30"}
    assert service.journal_service.create_entry.call_count >= 2


def test_review_pre_open_run_captures_partial_checkpoint_when_some_quotes_timeout() -> None:
    service, adapter, _, _ = build_service()
    capture = service.capture_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
    )
    original_get_quote = adapter.get_quote.side_effect

    def flaky_get_quote(symbol, mode):
        if symbol in {"SPY.US", "SOXX.US"}:
            raise LongbridgeIntegrationError(
                f"Longbridge timed out while trying to load quote for '{symbol}' after 6s."
            )
        return original_get_quote(symbol, mode)

    adapter.get_quote.side_effect = flaky_get_quote

    first = service.review_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 13, 30, tzinfo=timezone.utc),
    )

    assert first.reviewed is True
    assert first.updated_checkpoint_keys == ["open"]
    assert first.run is not None
    assert first.run.review_status == "in_progress"
    assert first.run.checkpoints[0].status == "captured"
    assert first.run.checkpoints[0].confirmation == "failed"
    assert first.run.checkpoints[0].captured_at is not None
    assert first.run.checkpoints[0].qqq_change_pct == Decimal("0.40")
    assert first.run.checkpoints[0].spy_change_pct is None
    assert first.run.checkpoints[0].semis_change_pct is None
    assert "S&P 500 ETF" in (first.run.checkpoints[0].detail or "")
    assert "Semiconductor Proxy" in (first.run.checkpoints[0].detail or "")

    stored = service.list_pre_open_runs(external_account_id="LBPT10087357", limit=1)[0]
    assert stored.checkpoints[0].captured_at is not None
    assert stored.checkpoints[0].confirmation == "failed"
    assert capture.run.id == stored.id


def test_run_review_suggests_tighter_delta_after_stop_loss_cluster() -> None:
    service, _, spreads, order_service = build_service()
    service.journal_service.create_entry.return_value = Mock(id="journal-1")
    closed_spreads = []
    order_map = {}
    for index in range(20):
        closed_at = datetime(2026, 6, 20, 14, 45, tzinfo=timezone.utc) - timedelta(days=index)
        spread = build_closed_spread(
            spread_id=f"closed-{index}",
            closed_at=closed_at,
            exit_reason="stop_loss",
        )
        closed_spreads.append(spread)
        order_map[spread.short_exit_order_id] = build_option_order(
            order_id=spread.short_exit_order_id,
            symbol=spread.short_symbol,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.60"),
        )
        order_map[spread.long_exit_order_id] = build_option_order(
            order_id=spread.long_exit_order_id,
            symbol=spread.long_symbol,
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("0.50"),
        )

    spreads.list_spreads.side_effect = lambda external_account_id=None, status=None: (
        closed_spreads if status == SpreadStatus.CLOSED else []
    )
    order_service.get_order.side_effect = lambda order_id: order_map.get(order_id)

    result = service.run_review(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        as_of=datetime(2026, 6, 22, 14, 45, tzinfo=timezone.utc),
        force=True,
    )

    assert result.review_status == "suggested"
    assert result.parameter_name == "short_delta_target"
    assert result.suggested_value == "0.20"
    assert result.journal_entry_id == "journal-1"
    assert service.journal_service.create_entry.call_count >= 1


def test_refresh_spread_marks_canceled_stop_loss_close_order_for_manual_action() -> None:
    service, _, spreads, order_service = build_service()
    spread = build_open_spread().model_copy(
        update={
            "short_exit_order_id": "short-exit",
            "exit_reason": "stop_loss",
            "raw_payload": {
                "monitor": {
                    "should_close": True,
                    "exit_reason": "stop_loss",
                }
            },
        }
    )
    spreads.get_spread.return_value = spread
    order_service.refresh_order.return_value = build_option_order(
        order_id="short-exit",
        symbol=spread.short_symbol,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELED,
        limit_price=Decimal("1.63"),
    )

    result = service.refresh_spread("spread-1")

    assert result.status == SpreadStatus.OPEN
    assert result.raw_payload is not None
    lifecycle = result.raw_payload["lifecycle"]
    assert lifecycle["warning"] == "close_order_canceled_manual_action_needed"
    assert lifecycle["manual_action_required"] is True
    assert lifecycle["close_order_id"] == "short-exit"
    assert lifecycle["close_order_state"] == "canceled"
    assert lifecycle["exit_reason"] == "stop_loss"
    assert result.lifecycle_warning_code == "close_order_canceled_manual_action_needed"
    assert result.manual_action_required is True
    assert result.latest_monitor_should_close is True
    assert result.latest_close_order_status == "canceled"


def test_refresh_spread_does_not_reopen_exit_pending_long_from_filled_entries() -> None:
    service, _, spreads, order_service = build_service()
    spread = build_open_spread(status=SpreadStatus.EXIT_PENDING_LONG).model_copy(
        update={
            "long_entry_order_id": "long-entry",
            "short_entry_order_id": "short-entry",
            "short_exit_order_id": "short-exit",
            "long_exit_order_id": "long-exit",
        }
    )
    spreads.get_spread.return_value = spread
    orders = {
        "long-entry": build_option_order(
            order_id="long-entry",
            symbol=spread.long_symbol,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.10"),
        ),
        "short-entry": build_option_order(
            order_id="short-entry",
            symbol=spread.short_symbol,
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.40"),
        ),
        "short-exit": build_option_order(
            order_id="short-exit",
            symbol=spread.short_symbol,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("1.60"),
        ),
        "long-exit": build_option_order(
            order_id="long-exit",
            symbol=spread.long_symbol,
            side=OrderSide.SELL,
            status=OrderStatus.SUBMITTED,
            limit_price=None,
        ),
    }
    order_service.refresh_order.side_effect = lambda order_id: orders[order_id]

    result = service.refresh_spread(spread.id)

    assert result.status == SpreadStatus.EXIT_PENDING_LONG


def test_refresh_spread_reloads_and_reevaluates_once_after_version_conflict() -> None:
    service, _, spreads, order_service = build_service()
    initial = build_open_spread(status=SpreadStatus.EXIT_PENDING_LONG).model_copy(
        update={"version": 0, "long_exit_order_id": "long-exit"}
    )
    concurrent = initial.model_copy(update={"version": 1})
    persisted = concurrent.model_copy(update={"version": 2})
    spreads.get_spread.side_effect = [initial, concurrent]
    spreads.update_spread.side_effect = [
        ConcurrentSpreadUpdateError(initial.id),
        persisted,
    ]
    order_service.refresh_order.return_value = build_option_order(
        order_id="long-exit",
        symbol=initial.long_symbol,
        side=OrderSide.SELL,
        status=OrderStatus.SUBMITTED,
        limit_price=None,
    )

    result = service.refresh_spread(initial.id)

    assert result.version == 2
    assert spreads.update_spread.call_args_list[0].kwargs["expected_version"] == 0
    assert spreads.update_spread.call_args_list[1].kwargs["expected_version"] == 1


def test_recover_close_rejects_unconfirmed_paper_order_and_audits() -> None:
    service, _, spreads, order_service = build_service()
    audit_events = Mock()
    service.audit_events = audit_events
    spread = build_open_spread().model_copy(
        update={
            "short_exit_order_id": "short-exit",
            "latest_monitor_should_close": True,
            "latest_close_order_status": "canceled",
        }
    )
    spreads.get_spread.return_value = spread

    with pytest.raises(ValueError, match="confirm_paper_order=true"):
        service.recover_close(
            "spread-1",
            RecoverBullPutCloseRequest(
                external_account_id="LBPT10087357",
                confirm_paper_order=False,
            ),
        )

    order_service.submit_order.assert_not_called()
    audit_request = audit_events.create_event.call_args.args[0]
    assert audit_request.action == "bull_put_recover_close_rejected"
    assert audit_request.warning_code == "paper_order_not_confirmed"


def test_execute_spread_blocks_when_official_calendar_is_unavailable() -> None:
    service, adapter, _, order_service = build_service()
    adapter.get_us_market_calendar.side_effect = RuntimeError("calendar unavailable")

    with pytest.raises(ValueError, match="Official U.S. market calendar is unavailable"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=build_scan_time(),
            )
        )

    order_service.submit_order.assert_not_called()


def test_execute_spread_uses_13_et_close_on_half_trading_day() -> None:
    service, adapter, _, order_service = build_service()
    adapter.get_us_market_calendar.return_value = (True, True)

    with pytest.raises(ValueError, match="stop before the close"):
        service.execute_spread(
            ExecuteBullPutSpreadRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                mode=ExecutionMode.PAPER,
                as_of=datetime(2026, 5, 22, 16, 56, tzinfo=timezone.utc),
            )
        )

    order_service.submit_order.assert_not_called()


def test_recover_close_rejects_existing_working_short_close_order_and_audits() -> None:
    service, _, spreads, order_service = build_service()
    audit_events = Mock()
    service.audit_events = audit_events
    spread = build_open_spread().model_copy(
        update={
            "short_exit_order_id": "short-exit",
            "latest_monitor_should_close": True,
            "latest_close_order_status": "submitted",
        }
    )
    spreads.get_spread.return_value = spread
    order_service.refresh_order.return_value = build_option_order(
        order_id="short-exit",
        symbol=spread.short_symbol,
        side=OrderSide.BUY,
        status=OrderStatus.SUBMITTED,
        limit_price=Decimal("1.63"),
    )

    with pytest.raises(ValueError, match="still working"):
        service.recover_close(
            "spread-1",
            RecoverBullPutCloseRequest(
                external_account_id="LBPT10087357",
                confirm_paper_order=True,
            ),
        )

    order_service.submit_order.assert_not_called()
    audit_request = audit_events.create_event.call_args.args[0]
    assert audit_request.action == "bull_put_recover_close_rejected"
    assert audit_request.warning_code == "working_replacement_exists"


def test_recover_close_eligibility_reports_canceled_short_close_order() -> None:
    service, _, spreads, order_service = build_service()
    spread = build_open_spread().model_copy(
        update={
            "short_exit_order_id": "short-exit",
            "latest_monitor_should_close": True,
            "latest_close_order_status": "canceled",
            "raw_payload": {"monitor": {"should_close": True, "estimated_exit_debit": "2.35"}},
        }
    )
    spreads.get_spread.return_value = spread
    order_service.get_order.return_value = build_option_order(
        order_id="short-exit",
        symbol=spread.short_symbol,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELED,
        limit_price=Decimal("1.63"),
    )

    eligibility = service.get_recover_close_eligibility(
        "spread-1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    assert eligibility.eligible is True
    assert eligibility.reasons == []
    assert eligibility.latest_should_close is True
    assert eligibility.old_short_close_order_status == "canceled"
    assert eligibility.working_replacement_order_id is None
    assert eligibility.max_debit_required_hint == Decimal("2.35")
    order_service.refresh_order.assert_not_called()


def test_recover_close_eligibility_reports_account_mismatch_and_working_order() -> None:
    service, _, spreads, order_service = build_service()
    spread = build_open_spread().model_copy(
        update={
            "short_exit_order_id": "short-exit",
            "latest_monitor_should_close": True,
            "latest_close_order_status": "submitted",
        }
    )
    spreads.get_spread.return_value = spread
    order_service.get_order.return_value = build_option_order(
        order_id="short-exit",
        symbol=spread.short_symbol,
        side=OrderSide.BUY,
        status=OrderStatus.SUBMITTED,
        limit_price=Decimal("1.63"),
    )

    eligibility = service.get_recover_close_eligibility(
        "spread-1",
        external_account_id="other-account",
        mode=ExecutionMode.LIVE,
    )

    assert eligibility.eligible is False
    assert "mode_not_paper" in eligibility.reasons
    assert "account_mismatch" in eligibility.reasons
    assert "working_replacement_exists" in eligibility.reasons
    assert eligibility.old_short_close_order_status == "submitted"
    assert eligibility.working_replacement_order_id == "short-exit"


def test_recover_close_submits_replacement_after_canceled_short_close_order() -> None:
    service, adapter, spreads, order_service = build_service()
    audit_events = Mock()
    service.audit_events = audit_events
    spread = build_open_spread().model_copy(
        update={
            "short_exit_order_id": "short-exit",
            "exit_reason": "stop_loss",
            "latest_monitor_should_close": True,
            "latest_close_order_status": "canceled",
        }
    )
    spreads.get_spread.return_value = spread
    order_service.refresh_order.return_value = build_option_order(
        order_id="short-exit",
        symbol=spread.short_symbol,
        side=OrderSide.BUY,
        status=OrderStatus.CANCELED,
        limit_price=Decimal("1.63"),
    )
    adapter.get_best_bid_ask.side_effect = lambda symbol, mode: {
        "QQQ260619P470000.US": (Decimal("2.40"), Decimal("2.60")),
        "QQQ260619P467000.US": (Decimal("1.00"), Decimal("1.10")),
    }[symbol]
    order_service.submit_order.side_effect = [
        build_option_order(
            order_id="short-exit-replacement",
            symbol=spread.short_symbol,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            limit_price=Decimal("2.60"),
        ),
        build_option_order(
            order_id="long-exit",
            symbol=spread.long_symbol,
            side=OrderSide.SELL,
            status=OrderStatus.FILLED,
            limit_price=None,
        ),
    ]

    recover_request = RecoverBullPutCloseRequest(
        external_account_id="LBPT10087357",
        confirm_paper_order=True,
        max_debit=Decimal("3.00"),
        actor="operator-a",
        note="manual stop-loss recovery",
    )
    result = service.recover_close(
        "spread-1",
        recover_request,
        idempotency_key="recover-public-key-0001",
    )

    assert result.status == SpreadStatus.CLOSED
    assert result.short_exit_order_id == "short-exit-replacement"
    assert result.long_exit_order_id == "long-exit"
    assert order_service.submit_order.call_count == 2
    assert all(
        call_args.kwargs["action_context"].entity_id == "spread-1"
        for call_args in order_service.submit_order.call_args_list
    )
    assert {
        call_args.kwargs["parent_action_intent_id"]
        for call_args in order_service.submit_order.call_args_list
    } == {"parent-action-1"}
    order_service.complete_trade_action.assert_called_once()
    actions = [call_args.args[0].action for call_args in audit_events.create_event.call_args_list]
    assert actions == ["bull_put_recover_close_submitted", "bull_put_recover_close_completed"]

    order_service.submit_order.reset_mock()
    order_service.prepare_trade_action.side_effect = None
    order_service.prepare_trade_action.return_value = PreparedTradeActionIntent(
        intent=TradeActionIntent(
            id="recover-parent-replay",
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key="recover-public-key-0001",
            request_hash="recover-parent-hash",
            action="bull_put_recover_close",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-1",
            state=TradingIntentState.PERSISTED,
            request_payload={},
            response_payload=result.model_dump(mode="json"),
            created_at=build_scan_time(),
            updated_at=build_scan_time(),
        ),
        created=False,
    )
    replay = service.recover_close(
        "spread-1",
        recover_request,
        idempotency_key="recover-public-key-0001",
    )
    assert replay.model_dump() == result.model_dump()
    assert replay.idempotent_replayed is True
    order_service.submit_order.assert_not_called()


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
    assert result.spread.raw_payload is not None
    assert result.spread.raw_payload["monitor"]["estimated_exit_debit"] == "1.60"
    assert result.spread.raw_payload["monitor"]["estimated_pnl"] == "-30.00"
    assert result.spread.raw_payload["monitor"]["take_profit_debit"] == "0.6500"
    assert result.spread.raw_payload["monitor"]["stop_loss_debit"] == "2.6000"
    assert result.spread.raw_payload["monitor"]["should_close"] is False
    assert result.spread.latest_monitor_should_close is False
    assert result.spread.next_monitor_after == datetime(2026, 5, 23, 14, 50, tzinfo=timezone.utc)


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

    monitor_as_of = datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc)
    result = service.monitor_spread(
        "spread-1",
        as_of=monitor_as_of,
        idempotency_key="monitor-public-key-0001",
    )

    assert result.should_close is True
    assert result.exit_reason == "take_profit"
    assert result.spread.status == SpreadStatus.CLOSED
    assert result.spread.short_exit_order_id == "short-exit"
    assert result.spread.long_exit_order_id == "long-exit"
    assert result.estimated_exit_debit == Decimal("0.50")
    assert result.estimated_pnl == Decimal("80.00")
    assert all(
        call_args.kwargs["action_context"].entity_id == "spread-1"
        for call_args in order_service.submit_order.call_args_list
    )
    assert {
        call_args.kwargs["parent_action_intent_id"]
        for call_args in order_service.submit_order.call_args_list
    } == {"parent-action-1"}
    order_service.complete_trade_action.assert_called_once()

    order_service.submit_order.reset_mock()
    order_service.prepare_trade_action.side_effect = None
    order_service.prepare_trade_action.return_value = PreparedTradeActionIntent(
        intent=TradeActionIntent(
            id="monitor-parent-replay",
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key="monitor-public-key-0001",
            request_hash="monitor-parent-hash",
            action="bull_put_monitor",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-1",
            state=TradingIntentState.PERSISTED,
            request_payload={},
            response_payload=result.model_dump(mode="json"),
            created_at=monitor_as_of,
            updated_at=monitor_as_of,
        ),
        created=False,
    )
    replay = service.monitor_spread(
        "spread-1",
        as_of=monitor_as_of,
        idempotency_key="monitor-public-key-0001",
    )
    assert replay.model_dump() == result.model_dump()
    assert replay.spread.idempotent_replayed is True
    order_service.submit_order.assert_not_called()


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

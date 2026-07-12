from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from stocks_tool.application.services.zero_dte_lottery_strategy import (
    ZeroDteExecutionDisabledError,
    ZeroDteLotteryStrategyService,
)
from stocks_tool.core.config import Settings
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
from stocks_tool.domain.models import (
    BrokerAccount,
    CreateOrderRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    ExecuteZeroDteLotteryRequest,
    OptionContractRef,
    OptionChainEntry,
    OptionMarketSnapshot,
    Order,
    SecurityQuoteSnapshot,
    StrategyRun,
    StrategySignal,
    UpdateZeroDteLotteryRuntimeRequest,
)


NOW = datetime(2026, 6, 4, 14, 30, tzinfo=timezone.utc)
TODAY = date(2026, 6, 4)


class FakeBrokerAccounts:
    def get_by_external_account_id(self, external_account_id: str) -> BrokerAccount | None:
        if external_account_id != "LBPT10087357":
            return None
        return BrokerAccount(
            id="broker-account-1",
            broker=BrokerName.LONGBRIDGE,
            external_account_id=external_account_id,
            display_name="Longbridge Paper",
            base_currency="USD",
            is_active=True,
            auto_reconcile_enabled=True,
            created_at=NOW,
            updated_at=NOW,
        )


class FakeLongbridgeAdapter:
    def __init__(
        self,
        *,
        quote: SecurityQuoteSnapshot | None = None,
        option_quotes: list[OptionMarketSnapshot] | None = None,
    ) -> None:
        self.quote = quote or build_underlying_quote()
        self.option_quotes = option_quotes or [build_option_quote(symbol="QQQ260604C736000.US")]
        self.list_option_chain_called = False

    def get_quote(self, symbol: str, mode: ExecutionMode) -> SecurityQuoteSnapshot:
        return self.quote

    def list_option_expiry_dates(self, symbol: str, mode: ExecutionMode) -> list[date]:
        return [TODAY]

    def list_option_chain(
        self,
        symbol: str,
        expiry_date: date,
        mode: ExecutionMode,
    ) -> list[OptionChainEntry]:
        self.list_option_chain_called = True
        return [
            OptionChainEntry(
                strike=Decimal("734"),
                call_symbol="QQQ260604C734000.US",
                put_symbol="QQQ260604P734000.US",
                standard=True,
            ),
            OptionChainEntry(
                strike=Decimal("736"),
                call_symbol="QQQ260604C736000.US",
                put_symbol="QQQ260604P736000.US",
                standard=True,
            ),
        ]

    def get_option_market_snapshots(
        self,
        symbols: list[str],
        mode: ExecutionMode,
    ) -> list[OptionMarketSnapshot]:
        return [quote for quote in self.option_quotes if quote.symbol in symbols]

    def get_best_bid_ask(self, symbol: str, mode: ExecutionMode):
        return Decimal("1.40"), Decimal("1.45")


class FakeOrderService:
    def __init__(self, existing_orders: list[Order] | None = None) -> None:
        self.existing_orders = existing_orders or []
        self.submitted_request: CreateOrderRequest | None = None

    def list_orders(self, external_account_id: str | None = None) -> list[Order]:
        return [
            order
            for order in self.existing_orders
            if external_account_id is None or order.external_account_id == external_account_id
        ]

    def submit_order(self, request: CreateOrderRequest) -> Order:
        self.submitted_request = request
        return build_order(
            symbol=request.symbol,
            side=request.side,
            status=OrderStatus.SUBMITTED,
            limit_price=request.limit_price,
            option_contract=request.option_contract,
            raw_payload={"submission_request": request.model_dump(mode="json")},
        )


class FakeExperiments:
    def __init__(self) -> None:
        self.run_request: CreateStrategyRunRequest | None = None
        self.signal_request: CreateStrategySignalRequest | None = None

    def create_run(self, request: CreateStrategyRunRequest) -> StrategyRun:
        self.run_request = request
        return StrategyRun(
            id="run-1",
            strategy_id=request.strategy_id,
            external_account_id=request.external_account_id,
            mode=request.mode,
            run_type=request.run_type,
            status=request.status,
            symbol=request.symbol,
            order_id=request.order_id,
            started_at=request.started_at,
            completed_at=request.completed_at,
            summary=request.summary,
            reason=request.reason,
            metrics_payload=request.metrics_payload,
            created_at=NOW,
            updated_at=NOW,
        )

    def create_signal(self, request: CreateStrategySignalRequest) -> StrategySignal:
        self.signal_request = request
        return StrategySignal(
            id="signal-1",
            strategy_id=request.strategy_id,
            external_account_id=request.external_account_id,
            mode=request.mode,
            signal_type=request.signal_type,
            symbol=request.symbol,
            run_id=request.run_id,
            strength=request.strength,
            summary=request.summary,
            detail=request.detail,
            source=request.source,
            signal_payload=request.signal_payload,
            emitted_at=NOW,
            created_at=NOW,
        )


def build_service(
    adapter: FakeLongbridgeAdapter | None = None,
    order_service: FakeOrderService | None = None,
    settings: Settings | None = None,
    experiments: FakeExperiments | None = None,
) -> ZeroDteLotteryStrategyService:
    return ZeroDteLotteryStrategyService(
        settings=settings or Settings(),
        broker_accounts=FakeBrokerAccounts(),
        longbridge_adapter=adapter or FakeLongbridgeAdapter(),
        order_service=order_service,
        experiments=experiments,
    )


def build_underlying_quote(
    *,
    last_done: Decimal = Decimal("735"),
    prev_close: Decimal = Decimal("731"),
) -> SecurityQuoteSnapshot:
    return SecurityQuoteSnapshot(
        symbol="QQQ.US",
        last_done=last_done,
        prev_close=prev_close,
        open=prev_close,
        high=max(last_done, prev_close),
        low=min(last_done, prev_close),
        timestamp=NOW,
        volume=1_000_000,
        turnover=last_done * Decimal("1000000"),
        trade_status="Normal",
    )


def build_option_quote(
    *,
    symbol: str,
    right: OptionRight = OptionRight.CALL,
    strike: Decimal = Decimal("736"),
    bid: Decimal = Decimal("1.40"),
    ask: Decimal = Decimal("1.45"),
    delta: Decimal = Decimal("0.22"),
    volume: int = 25,
    open_interest: int = 400,
) -> OptionMarketSnapshot:
    return OptionMarketSnapshot(
        symbol=symbol,
        underlying_symbol="QQQ.US",
        expiration_date=TODAY,
        strike=strike,
        right=right,
        last_done=(bid + ask) / Decimal("2"),
        prev_close=Decimal("1.00"),
        open=Decimal("1.20"),
        high=Decimal("1.60"),
        low=Decimal("1.10"),
        timestamp=NOW,
        volume=volume,
        turnover=Decimal("1000"),
        trade_status="Normal",
        bid=bid,
        ask=ask,
        open_interest=open_interest,
        delta=delta,
    )


def build_order(
    *,
    symbol: str = "QQQ260604C736000.US",
    side: OrderSide = OrderSide.BUY,
    status: OrderStatus = OrderStatus.SUBMITTED,
    limit_price: Decimal | None = Decimal("1.45"),
    option_contract: OptionContractRef | None = None,
    raw_payload: dict | None = None,
    submitted_at: datetime = NOW,
) -> Order:
    return Order(
        id="order-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-order-1",
        client_order_id="client-order-1",
        symbol=symbol,
        asset_type=AssetType.OPTION,
        side=side,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=status,
        limit_price=limit_price,
        option_contract=option_contract,
        raw_payload=raw_payload,
        submitted_at=submitted_at,
        created_at=submitted_at,
        updated_at=submitted_at,
    )


def test_preview_selects_zero_dte_call_under_150_premium_cap() -> None:
    service = build_service()

    result = service.preview(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        direction="auto",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert result.eligible is True
    assert result.direction == OptionRight.CALL
    assert result.max_premium_per_trade == Decimal("150")
    assert result.candidate is not None
    assert result.candidate.option_symbol == "QQQ260604C736000.US"
    assert result.candidate.premium_at_ask == Decimal("145.00")
    assert result.candidate.max_loss == Decimal("145.00")


def test_preview_blocks_candidate_above_150_premium_cap() -> None:
    adapter = FakeLongbridgeAdapter(
        option_quotes=[
            build_option_quote(
                symbol="QQQ260604C736000.US",
                bid=Decimal("1.50"),
                ask=Decimal("1.55"),
            )
        ]
    )
    service = build_service(adapter)

    result = service.preview(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        direction="call",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert result.eligible is False
    assert result.candidate is None
    assert result.max_premium_per_trade == Decimal("150")
    assert "150 premium" in result.reasons[0]


def test_preview_skips_auto_direction_when_underlying_signal_is_unclear() -> None:
    adapter = FakeLongbridgeAdapter(
        quote=build_underlying_quote(last_done=Decimal("735.10"), prev_close=Decimal("735")),
    )
    service = build_service(adapter)

    result = service.preview(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        direction="auto",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert result.eligible is False
    assert result.direction is None
    assert "auto direction is unclear" in result.reasons[0]
    assert adapter.list_option_chain_called is False


def test_execute_is_disabled_before_order_submission() -> None:
    order_service = FakeOrderService()
    service = build_service(order_service=order_service)

    try:
        service.execute(
            ExecuteZeroDteLotteryRequest(
                external_account_id="LBPT10087357",
                symbol="QQQ.US",
                direction="auto",
                mode=ExecutionMode.PAPER,
                as_of=NOW,
                confirm_paper_order=True,
            )
        )
    except ZeroDteExecutionDisabledError as exc:
        assert exc.code == "zero_dte_execution_disabled_pending_lifecycle"
    else:
        raise AssertionError("Expected zero-DTE execution to remain disabled.")

    assert order_service.submitted_request is None


def test_update_runtime_state_rejects_auto_ordering() -> None:
    settings = Settings()
    service = build_service(settings=settings)

    try:
        service.update_runtime_state(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            request=UpdateZeroDteLotteryRuntimeRequest(auto_execute_enabled=True),
        )
    except ZeroDteExecutionDisabledError:
        pass
    else:
        raise AssertionError("Expected zero-DTE auto-ordering to remain disabled.")

    assert settings.zero_dte_lottery_strategy.auto_execute_enabled is False


def test_update_runtime_state_rejects_live_auto_ordering() -> None:
    service = build_service()

    try:
        service.update_runtime_state(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.LIVE,
            request=UpdateZeroDteLotteryRuntimeRequest(auto_execute_enabled=True),
        )
    except ValueError as exc:
        assert "paper-only" in str(exc)
    else:
        raise AssertionError("Expected live zero-DTE lottery runtime updates to be rejected.")


def test_run_scan_skips_when_auto_execution_is_disabled() -> None:
    service = build_service(order_service=FakeOrderService(), experiments=FakeExperiments())

    result = service.run_scan(
        external_account_id="LBPT10087357",
        symbol="QQQ.US",
        direction="auto",
        mode=ExecutionMode.PAPER,
        as_of=NOW,
    )

    assert result.executed is False
    assert result.preview is None
    assert "auto-execution is disabled" in (result.reason or "")


def test_run_scan_force_is_disabled_before_order_submission() -> None:
    experiments = FakeExperiments()
    order_service = FakeOrderService()
    adapter = FakeLongbridgeAdapter()
    service = build_service(
        adapter=adapter,
        order_service=order_service,
        experiments=experiments,
    )

    try:
        service.run_scan(
            external_account_id="LBPT10087357",
            symbol="QQQ.US",
            direction="auto",
            mode=ExecutionMode.PAPER,
            as_of=NOW,
            force=True,
        )
    except ZeroDteExecutionDisabledError:
        pass
    else:
        raise AssertionError("Expected force scan execution to remain disabled.")

    assert order_service.submitted_request is None
    assert experiments.run_request is None
    assert adapter.list_option_chain_called is False


def test_run_scan_rejects_enabled_auto_execution_before_market_data() -> None:
    settings = Settings(zero_dte_lottery_strategy={"auto_execute_enabled": True})
    adapter = FakeLongbridgeAdapter()
    order_service = FakeOrderService()
    service = build_service(
        adapter=adapter,
        order_service=order_service,
        settings=settings,
    )

    try:
        service.run_scan(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            as_of=NOW,
        )
    except ZeroDteExecutionDisabledError:
        pass
    else:
        raise AssertionError("Expected configured zero-DTE auto execution to remain disabled.")

    assert adapter.list_option_chain_called is False
    assert order_service.submitted_request is None

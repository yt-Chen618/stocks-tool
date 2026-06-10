from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, Mock, call

import stocks_tool.application.services.reconciliation as reconciliation_module
from stocks_tool.adapters.brokers.longbridge import LongbridgeIntegrationError
from stocks_tool.application.services.longbridge_integration import (
    LongbridgeIntegrationService,
)
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.reconciliation import ReconciliationCoordinator
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    MarketEventSeverity,
    MarketEventType,
    OrderSide,
    OrderStatus,
    OrderType,
    ReconciliationStatus,
    SpreadStatus,
    StrategyProposalStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerAccount,
    BrokerOrderSnapshot,
    BullPutSpread,
    Execution,
    MarketEvent,
    MarketEventImportResult,
    PositionSnapshot,
)


def build_broker_account() -> BrokerAccount:
    now = datetime(2026, 5, 22, 9, 30, tzinfo=timezone.utc)
    return BrokerAccount(
        id="broker-account-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        display_name="Paper Account",
        base_currency="USD",
        options_level=None,
        is_active=True,
        auto_reconcile_enabled=True,
        account_sync_status=ReconciliationStatus.IDLE,
        account_last_sync_attempt_at=None,
        account_last_synced_at=None,
        account_last_sync_error=None,
        orders_sync_status=ReconciliationStatus.IDLE,
        orders_last_sync_attempt_at=None,
        orders_last_synced_at=None,
        orders_last_sync_error=None,
        created_at=now,
        updated_at=now,
    )


def build_account_snapshot() -> AccountSnapshot:
    captured_at = datetime(2026, 5, 22, 9, 45, tzinfo=timezone.utc)
    return AccountSnapshot(
        id="snapshot-1",
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        currency="USD",
        cash_balance=Decimal("12000.00"),
        net_liquidation=Decimal("15300.00"),
        buying_power=Decimal("10000.00"),
        positions=[
            PositionSnapshot(
                symbol="UNH.US",
                asset_type=AssetType.STOCK,
                quantity=Decimal("10"),
                average_cost=Decimal("388.35"),
                market_value=Decimal("3833.00"),
                unrealized_pnl=Decimal("-53.50"),
            )
        ],
        captured_at=captured_at,
    )


def build_remote_order() -> BrokerOrderSnapshot:
    submitted_at = datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc)
    updated_at = datetime(2026, 5, 22, 10, 4, tzinfo=timezone.utc)
    return BrokerOrderSnapshot(
        external_order_id="1241940481017913344",
        symbol="UNH.US",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.SUBMITTED,
        limit_price=Decimal("321.00"),
        stop_price=None,
        executed_quantity=1,
        executed_price=Decimal("320.75"),
        submitted_at=submitted_at,
        updated_at=updated_at,
        raw_payload={"id": "1241940481017913344"},
    )


def build_open_spread(*, last_synced_at: datetime | None = None) -> BullPutSpread:
    now = datetime(2026, 5, 23, 14, 45, tzinfo=timezone.utc)
    return BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=datetime(2026, 6, 19, tzinfo=timezone.utc).date(),
        contracts=1,
        width=Decimal("3"),
        long_symbol="QQQ260619P467000.US",
        long_strike=Decimal("467"),
        short_symbol="QQQ260619P470000.US",
        short_strike=Decimal("470"),
        status=SpreadStatus.OPEN,
        entry_net_credit=Decimal("1.30"),
        last_synced_at=last_synced_at,
        opened_at=now,
        created_at=now,
        updated_at=now,
    )


def patch_covered_call_reconciliation_dependencies(
    monkeypatch,
    *,
    broker_accounts: Mock,
    orders: Mock,
    experiments: Mock,
    covered_call_service: Mock,
) -> None:
    class FakeCoveredCallStrategyService:
        strategy_id = "covered_call_v1"
        open_proposal_actions = {"sell_covered_call", "roll_covered_call"}

        def __new__(cls, **kwargs):
            return covered_call_service

    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBrokerAccountRepository",
        lambda session: broker_accounts,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyAccountSnapshotRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyOrderRepository",
        lambda session: orders,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyExecutionRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyTradePlanRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBullPutSpreadRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyPreOpenAssessmentRunRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyMarketEventRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyStrategyExperimentRepository",
        lambda session: experiments,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "CoveredCallStrategyService",
        FakeCoveredCallStrategyService,
    )


def test_sync_account_marks_syncing_then_success() -> None:
    adapter = Mock()
    broker_accounts = Mock()
    account_snapshots = Mock()
    broker_account = build_broker_account()
    snapshot = build_account_snapshot()
    broker_accounts.get_by_external_account_id.return_value = broker_account
    adapter.build_account_snapshot.return_value = snapshot
    account_snapshots.create_account_snapshot.return_value = snapshot
    service = LongbridgeIntegrationService(
        adapter=adapter,
        broker_accounts=broker_accounts,
        account_snapshots=account_snapshots,
    )

    result = service.sync_account(
        external_account_id=broker_account.external_account_id,
        mode=ExecutionMode.PAPER,
    )

    assert result.snapshot_id == "snapshot-1"
    assert broker_accounts.update_account_sync_state.call_count == 2
    first_call = broker_accounts.update_account_sync_state.call_args_list[0]
    second_call = broker_accounts.update_account_sync_state.call_args_list[1]
    assert first_call.args[0] == broker_account.external_account_id
    assert first_call.kwargs["status"] == ReconciliationStatus.SYNCING
    assert second_call.kwargs["status"] == ReconciliationStatus.SUCCESS
    assert second_call.kwargs["synced_at"] == snapshot.captured_at


def test_sync_account_marks_error_on_failure() -> None:
    adapter = Mock()
    broker_accounts = Mock()
    account_snapshots = Mock()
    broker_account = build_broker_account()
    broker_accounts.get_by_external_account_id.return_value = broker_account
    adapter.build_account_snapshot.side_effect = RuntimeError("quote bridge offline")
    service = LongbridgeIntegrationService(
        adapter=adapter,
        broker_accounts=broker_accounts,
        account_snapshots=account_snapshots,
    )

    try:
        service.sync_account(
            external_account_id=broker_account.external_account_id,
            mode=ExecutionMode.PAPER,
        )
    except RuntimeError as exc:
        assert str(exc) == "quote bridge offline"
    else:
        raise AssertionError("Expected sync_account to re-raise the adapter failure.")

    second_call = broker_accounts.update_account_sync_state.call_args_list[1]
    assert second_call.kwargs["status"] == ReconciliationStatus.ERROR
    assert second_call.kwargs["error"] == "quote bridge offline"


def test_sync_today_orders_marks_syncing_then_success() -> None:
    broker_accounts = Mock()
    trade_plans = Mock()
    orders = Mock()
    executions = Mock()
    adapter = Mock()
    broker_account = build_broker_account()
    remote_order = build_remote_order()
    broker_accounts.get_by_external_account_id.return_value = broker_account
    adapter.list_today_orders.return_value = [remote_order]
    orders.get_by_external_order_id.return_value = None
    orders.create_order.side_effect = lambda order: order
    executions.get_by_external_execution_id.return_value = None
    service = OrderService(
        settings=Settings(),
        broker_accounts=broker_accounts,
        trade_plans=trade_plans,
        orders=orders,
        executions=executions,
        longbridge_adapter=adapter,
    )

    result = service.sync_today_orders(
        external_account_id=broker_account.external_account_id,
        mode=ExecutionMode.PAPER,
    )

    assert result.synced_orders == 1
    assert result.created_orders == 1
    assert broker_accounts.update_orders_sync_state.call_count == 2
    assert executions.upsert_execution.call_count == 1
    first_call = broker_accounts.update_orders_sync_state.call_args_list[0]
    second_call = broker_accounts.update_orders_sync_state.call_args_list[1]
    assert first_call.kwargs["status"] == ReconciliationStatus.SYNCING
    assert second_call.kwargs["status"] == ReconciliationStatus.SUCCESS
    assert second_call.kwargs["synced_at"] is not None
    execution_arg = executions.upsert_execution.call_args.args[0]
    assert isinstance(execution_arg, Execution)
    assert execution_arg.quantity == 1
    assert execution_arg.price == Decimal("320.75")


def test_sync_today_orders_marks_error_on_failure() -> None:
    broker_accounts = Mock()
    trade_plans = Mock()
    orders = Mock()
    executions = Mock()
    adapter = Mock()
    broker_account = build_broker_account()
    broker_accounts.get_by_external_account_id.return_value = broker_account
    adapter.list_today_orders.side_effect = RuntimeError("trade bridge offline")
    service = OrderService(
        settings=Settings(),
        broker_accounts=broker_accounts,
        trade_plans=trade_plans,
        orders=orders,
        executions=executions,
        longbridge_adapter=adapter,
    )

    try:
        service.sync_today_orders(
            external_account_id=broker_account.external_account_id,
            mode=ExecutionMode.PAPER,
        )
    except RuntimeError as exc:
        assert str(exc) == "trade bridge offline"
    else:
        raise AssertionError("Expected sync_today_orders to re-raise the adapter failure.")

    second_call = broker_accounts.update_orders_sync_state.call_args_list[1]
    assert second_call.kwargs["status"] == ReconciliationStatus.ERROR
    assert second_call.kwargs["error"] == "trade bridge offline"


def test_reconciliation_coordinator_monitors_due_bull_put_spreads(monkeypatch) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    broker_accounts = Mock()
    account_snapshots = Mock()
    orders = Mock()
    executions = Mock()
    trade_plans = Mock()
    spreads = Mock()
    pre_open_runs = Mock()
    strategy_service = Mock()

    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": datetime.now(timezone.utc),
            "orders_last_sync_attempt_at": datetime.now(timezone.utc),
        }
    )
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders.list_orders.return_value = []
    spreads.list_spreads.side_effect = [
        [build_open_spread(last_synced_at=None)],
        [],
        [],
    ]

    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBrokerAccountRepository",
        lambda session: broker_accounts,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyAccountSnapshotRepository",
        lambda session: account_snapshots,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyOrderRepository",
        lambda session: orders,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyExecutionRepository",
        lambda session: executions,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyTradePlanRepository",
        lambda session: trade_plans,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBullPutSpreadRepository",
        lambda session: spreads,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyPreOpenAssessmentRunRepository",
        lambda session: pre_open_runs,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "BullPutStrategyService",
        lambda **kwargs: strategy_service,
    )

    settings = Settings()
    coordinator = ReconciliationCoordinator(
        settings=settings,
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()

    strategy_service.capture_pre_open_run.assert_called_once()
    strategy_service.review_pre_open_run.assert_called_once()
    strategy_service.run_entry_scan.assert_called_once()
    strategy_service.run_review.assert_called_once()
    scan_call = strategy_service.run_entry_scan.call_args
    strategy_service.monitor_spread.assert_called_once()
    monitor_call = strategy_service.monitor_spread.call_args
    assert strategy_service.method_calls[:5] == [
        call.monitor_spread("spread-1", as_of=monitor_call.kwargs["as_of"]),
        call.run_entry_scan(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            as_of=scan_call.kwargs["as_of"],
        ),
        call.run_review(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            as_of=scan_call.kwargs["as_of"],
        ),
        call.capture_pre_open_run(
            external_account_id="LBPT10087357",
            as_of=scan_call.kwargs["as_of"],
            automatic=True,
        ),
        call.review_pre_open_run(
            external_account_id="LBPT10087357",
            as_of=scan_call.kwargs["as_of"],
        ),
    ]
    assert scan_call.kwargs["external_account_id"] == "LBPT10087357"


def test_reconciliation_coordinator_runs_zero_dte_lottery_scan_when_enabled(monkeypatch) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    now = datetime.now(timezone.utc)
    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": now,
            "orders_last_sync_attempt_at": now,
        }
    )
    broker_accounts = Mock()
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders = Mock()
    orders.list_orders.return_value = []
    zero_dte_service = Mock()

    class FakeZeroDteLotteryStrategyService:
        def __new__(cls, **kwargs):
            return zero_dte_service

    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBrokerAccountRepository",
        lambda session: broker_accounts,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyAccountSnapshotRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyOrderRepository",
        lambda session: orders,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyExecutionRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyTradePlanRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBullPutSpreadRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBullPutStrategyRuntimeRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyPreOpenAssessmentRunRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyMarketEventRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyStrategyExperimentRepository",
        lambda session: Mock(),
    )
    monkeypatch.setattr(
        reconciliation_module,
        "ZeroDteLotteryStrategyService",
        FakeZeroDteLotteryStrategyService,
    )

    settings = Settings(
        bull_put_strategy={"enabled": False},
        covered_call_strategy={"enabled": False},
        zero_dte_lottery_strategy={
            "enabled": True,
            "auto_execute_enabled": True,
            "scan_interval_seconds": 60,
        },
    )
    coordinator = ReconciliationCoordinator(
        settings=settings,
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()

    zero_dte_service.run_scan.assert_called_once()
    scan_call = zero_dte_service.run_scan.call_args
    assert scan_call.kwargs["external_account_id"] == "LBPT10087357"
    assert scan_call.kwargs["mode"] == ExecutionMode.PAPER
    assert scan_call.kwargs["as_of"] is not None


def test_reconciliation_coordinator_imports_configured_market_event_csv(
    monkeypatch,
    tmp_path,
) -> None:
    csv_path = tmp_path / "events.csv"
    csv_path.write_text(
        "symbol,event_type,title,scheduled_at,severity,source\n"
        "UNH.US,earnings,UNH earnings,2026-06-01T13:30:00Z,high,manual\n",
        encoding="utf-8",
    )
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    broker_accounts = Mock()
    broker_accounts.list_broker_accounts.return_value = []
    market_events = Mock()
    market_events.list_events.return_value = []
    market_events.create_event.side_effect = lambda request: MarketEvent(
        id="event-1",
        symbol=request.symbol,
        event_type=request.event_type,
        title=request.title,
        scheduled_at=request.scheduled_at,
        source=request.source,
        severity=request.severity,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBrokerAccountRepository",
        lambda session: broker_accounts,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyMarketEventRepository",
        lambda session: market_events,
    )

    coordinator = ReconciliationCoordinator(
        settings=Settings(
            market_event_auto_import_enabled=True,
            market_event_import_csv_path=str(csv_path),
            bull_put_strategy={"enabled": False},
        ),
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()
    coordinator.run_once()

    market_events.create_event.assert_called_once()
    request = market_events.create_event.call_args.args[0]
    assert request.symbol == "UNH.US"
    assert request.event_type == MarketEventType.EARNINGS
    assert request.severity == MarketEventSeverity.HIGH


def test_reconciliation_coordinator_imports_configured_market_event_provider(
    monkeypatch,
) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    broker_accounts = Mock()
    broker_accounts.list_broker_accounts.return_value = []
    market_events = Mock()
    provider_requests = []

    class FakeProviderIngestionService:
        def __init__(self, **kwargs) -> None:
            pass

        def import_from_provider(self, request):
            provider_requests.append(request)
            return MarketEventImportResult(requested=1, created=1, skipped_duplicates=0, events=[])

    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBrokerAccountRepository",
        lambda session: broker_accounts,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyMarketEventRepository",
        lambda session: market_events,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "MarketEventProviderIngestionService",
        FakeProviderIngestionService,
    )

    coordinator = ReconciliationCoordinator(
        settings=Settings(
            market_event_provider_auto_import_enabled=True,
            market_event_provider="fmp",
            market_event_provider_symbols="UNH.US",
            market_event_provider_lookahead_days=14,
            bull_put_strategy={"enabled": False},
        ),
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()
    coordinator.run_once()

    assert len(provider_requests) == 1
    request = provider_requests[0]
    assert request.provider == "fmp"
    assert request.symbols == ["UNH.US"]
    assert (request.end - request.start).days == 14


def test_reconciliation_coordinator_runs_covered_call_proposal_scan_when_enabled(monkeypatch) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    now = datetime.now(timezone.utc)
    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": now,
            "orders_last_sync_attempt_at": now,
        }
    )
    broker_accounts = Mock()
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders = Mock()
    orders.list_orders.return_value = []
    experiments = Mock()
    experiments.list_proposals.return_value = []
    covered_call_service = Mock()

    patch_covered_call_reconciliation_dependencies(
        monkeypatch,
        broker_accounts=broker_accounts,
        orders=orders,
        experiments=experiments,
        covered_call_service=covered_call_service,
    )

    coordinator = ReconciliationCoordinator(
        settings=Settings(
            bull_put_strategy={"enabled": False},
            covered_call_strategy={"auto_propose_enabled": True, "proposal_interval_seconds": 60},
        ),
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()
    coordinator.run_once()

    covered_call_service.create_proposal.assert_called_once()
    proposal_call = covered_call_service.create_proposal.call_args
    assert proposal_call.kwargs["external_account_id"] == "LBPT10087357"
    assert proposal_call.kwargs["mode"] == ExecutionMode.PAPER
    assert proposal_call.kwargs["as_of"] is not None
    experiments.list_proposals.assert_any_call(
        external_account_id="LBPT10087357",
        strategy_id="covered_call_v1",
        status=StrategyProposalStatus.PENDING,
        limit=100,
    )


def test_reconciliation_coordinator_skips_covered_call_scan_with_active_proposal(monkeypatch) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    now = datetime.now(timezone.utc)
    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": now,
            "orders_last_sync_attempt_at": now,
        }
    )
    broker_accounts = Mock()
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders = Mock()
    orders.list_orders.return_value = []
    active_proposal = Mock()
    active_proposal.proposed_action = "sell_covered_call"
    experiments = Mock()
    experiments.list_proposals.return_value = [active_proposal]
    covered_call_service = Mock()

    patch_covered_call_reconciliation_dependencies(
        monkeypatch,
        broker_accounts=broker_accounts,
        orders=orders,
        experiments=experiments,
        covered_call_service=covered_call_service,
    )

    coordinator = ReconciliationCoordinator(
        settings=Settings(
            bull_put_strategy={"enabled": False},
            covered_call_strategy={"auto_propose_enabled": True, "proposal_interval_seconds": 60},
        ),
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()
    coordinator.run_once()

    covered_call_service.create_proposal.assert_not_called()


def test_reconciliation_coordinator_monitors_executed_covered_calls_when_enabled(monkeypatch) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    now = datetime.now(timezone.utc)
    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": now,
            "orders_last_sync_attempt_at": now,
        }
    )
    broker_accounts = Mock()
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders = Mock()
    orders.list_orders.return_value = []
    proposal = Mock()
    proposal.id = "proposal-1"
    proposal.proposed_action = "sell_covered_call"
    experiments = Mock()
    experiments.list_proposals.return_value = [proposal]
    covered_call_service = Mock()

    patch_covered_call_reconciliation_dependencies(
        monkeypatch,
        broker_accounts=broker_accounts,
        orders=orders,
        experiments=experiments,
        covered_call_service=covered_call_service,
    )

    coordinator = ReconciliationCoordinator(
        settings=Settings(
            bull_put_strategy={"enabled": False},
            covered_call_strategy={"auto_monitor_enabled": True, "monitor_interval_seconds": 60},
        ),
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()
    coordinator.run_once()

    covered_call_service.monitor_proposal.assert_called_once()
    monitor_call = covered_call_service.monitor_proposal.call_args
    assert monitor_call.args[0] == "proposal-1"
    assert monitor_call.kwargs["as_of"] is not None
    assert monitor_call.kwargs["record_signal"] is True
    experiments.list_proposals.assert_called_once_with(
        external_account_id="LBPT10087357",
        strategy_id="covered_call_v1",
        status=StrategyProposalStatus.EXECUTED,
        limit=100,
    )


def test_reconciliation_coordinator_reconciles_covered_call_lifecycle_when_enabled(monkeypatch) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    now = datetime.now(timezone.utc)
    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": now,
            "orders_last_sync_attempt_at": now,
        }
    )
    broker_accounts = Mock()
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders = Mock()
    orders.list_orders.return_value = []
    experiments = Mock()
    covered_call_service = Mock()

    patch_covered_call_reconciliation_dependencies(
        monkeypatch,
        broker_accounts=broker_accounts,
        orders=orders,
        experiments=experiments,
        covered_call_service=covered_call_service,
    )

    coordinator = ReconciliationCoordinator(
        settings=Settings(
            bull_put_strategy={"enabled": False},
            covered_call_strategy={"auto_lifecycle_enabled": True, "lifecycle_interval_seconds": 60},
        ),
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()
    coordinator.run_once()

    covered_call_service.reconcile_pending_lifecycle.assert_called_once()
    lifecycle_call = covered_call_service.reconcile_pending_lifecycle.call_args
    assert lifecycle_call.kwargs["external_account_id"] == "LBPT10087357"
    assert lifecycle_call.kwargs["as_of"] is not None


def test_reconciliation_coordinator_skips_recently_monitored_spreads(monkeypatch) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    broker_accounts = Mock()
    account_snapshots = Mock()
    orders = Mock()
    executions = Mock()
    trade_plans = Mock()
    spreads = Mock()
    pre_open_runs = Mock()
    strategy_service = Mock()

    now = datetime.now(timezone.utc)
    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": now,
            "orders_last_sync_attempt_at": now,
        }
    )
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders.list_orders.return_value = []
    spreads.list_spreads.side_effect = [
        [build_open_spread(last_synced_at=now)],
        [],
        [],
    ]

    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBrokerAccountRepository",
        lambda session: broker_accounts,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyAccountSnapshotRepository",
        lambda session: account_snapshots,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyOrderRepository",
        lambda session: orders,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyExecutionRepository",
        lambda session: executions,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyTradePlanRepository",
        lambda session: trade_plans,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBullPutSpreadRepository",
        lambda session: spreads,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyPreOpenAssessmentRunRepository",
        lambda session: pre_open_runs,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "BullPutStrategyService",
        lambda **kwargs: strategy_service,
    )

    settings = Settings()
    coordinator = ReconciliationCoordinator(
        settings=settings,
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()

    strategy_service.capture_pre_open_run.assert_called_once()
    strategy_service.review_pre_open_run.assert_called_once()
    strategy_service.run_entry_scan.assert_called_once()
    strategy_service.run_review.assert_called_once()
    strategy_service.monitor_spread.assert_not_called()


def test_reconciliation_coordinator_backs_off_transient_longbridge_strategy_failures(monkeypatch) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    broker_accounts = Mock()
    account_snapshots = Mock()
    orders = Mock()
    executions = Mock()
    trade_plans = Mock()
    spreads = Mock()
    pre_open_runs = Mock()
    strategy_service = Mock()

    now = datetime.now(timezone.utc)
    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": now,
            "orders_last_sync_attempt_at": now,
        }
    )
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders.list_orders.return_value = []
    spreads.list_spreads.return_value = []
    strategy_service.capture_pre_open_run.side_effect = LongbridgeIntegrationError(
        "Longbridge timed out while trying to load quote for 'SPY.US' after 6s."
    )

    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBrokerAccountRepository",
        lambda session: broker_accounts,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyAccountSnapshotRepository",
        lambda session: account_snapshots,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyOrderRepository",
        lambda session: orders,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyExecutionRepository",
        lambda session: executions,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyTradePlanRepository",
        lambda session: trade_plans,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBullPutSpreadRepository",
        lambda session: spreads,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyPreOpenAssessmentRunRepository",
        lambda session: pre_open_runs,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "BullPutStrategyService",
        lambda **kwargs: strategy_service,
    )

    coordinator = ReconciliationCoordinator(
        settings=Settings(),
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()
    coordinator.run_once()

    assert strategy_service.capture_pre_open_run.call_count == 1
    strategy_service.review_pre_open_run.assert_called()
    assert strategy_service.review_pre_open_run.call_count == 2


def test_reconciliation_coordinator_backs_off_remaining_spread_monitors_after_transient_failure(
    monkeypatch,
) -> None:
    session_factory = MagicMock()
    session_factory.return_value.__enter__.return_value = object()
    session_factory.return_value.__exit__.return_value = False

    broker_accounts = Mock()
    account_snapshots = Mock()
    orders = Mock()
    executions = Mock()
    trade_plans = Mock()
    spreads = Mock()
    pre_open_runs = Mock()
    strategy_service = Mock()

    now = datetime.now(timezone.utc)
    broker_account = build_broker_account().model_copy(
        update={
            "account_last_sync_attempt_at": now,
            "orders_last_sync_attempt_at": now,
        }
    )
    broker_accounts.list_broker_accounts.return_value = [broker_account]
    orders.list_orders.return_value = []
    spreads.list_spreads.return_value = [
        build_open_spread(last_synced_at=None),
        build_open_spread(last_synced_at=None).model_copy(update={"id": "spread-2"}),
    ]
    strategy_service.monitor_spread.side_effect = LongbridgeIntegrationError(
        "Longbridge timed out while trying to load quote for 'QQQ.US' after 6s."
    )

    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBrokerAccountRepository",
        lambda session: broker_accounts,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyAccountSnapshotRepository",
        lambda session: account_snapshots,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyOrderRepository",
        lambda session: orders,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyExecutionRepository",
        lambda session: executions,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyTradePlanRepository",
        lambda session: trade_plans,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyBullPutSpreadRepository",
        lambda session: spreads,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "SQLAlchemyPreOpenAssessmentRunRepository",
        lambda session: pre_open_runs,
    )
    monkeypatch.setattr(
        reconciliation_module,
        "BullPutStrategyService",
        lambda **kwargs: strategy_service,
    )

    coordinator = ReconciliationCoordinator(
        settings=Settings(),
        session_factory=session_factory,
        longbridge_adapter=Mock(),
    )

    coordinator.run_once()
    coordinator.run_once()

    assert strategy_service.monitor_spread.call_count == 1

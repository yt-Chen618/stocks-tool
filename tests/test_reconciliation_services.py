from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, Mock

import stocks_tool.application.services.reconciliation as reconciliation_module
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
    OrderSide,
    OrderStatus,
    OrderType,
    ReconciliationStatus,
    SpreadStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerAccount,
    BrokerOrderSnapshot,
    BullPutSpread,
    Execution,
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

    strategy_service.monitor_spread.assert_called_once()
    monitor_call = strategy_service.monitor_spread.call_args
    assert monitor_call.args[0] == "spread-1"
    assert monitor_call.kwargs["as_of"] is not None


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

    strategy_service.monitor_spread.assert_not_called()

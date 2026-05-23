from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.application.services.journal import JournalService
from stocks_tool.application.services.longbridge_integration import LongbridgeIntegrationService
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import BrokerName, ExecutionMode, OrderStatus, SpreadStatus
from stocks_tool.repositories.sqlalchemy_account_snapshot_repository import (
    SQLAlchemyAccountSnapshotRepository,
)
from stocks_tool.repositories.sqlalchemy_broker_account_repository import (
    SQLAlchemyBrokerAccountRepository,
)
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import (
    SQLAlchemyBullPutSpreadRepository,
)
from stocks_tool.repositories.sqlalchemy_bull_put_strategy_runtime_repository import (
    SQLAlchemyBullPutStrategyRuntimeRepository,
)
from stocks_tool.repositories.sqlalchemy_execution_repository import (
    SQLAlchemyExecutionRepository,
)
from stocks_tool.repositories.sqlalchemy_journal_repository import (
    SQLAlchemyJournalRepository,
)
from stocks_tool.repositories.sqlalchemy_order_repository import (
    SQLAlchemyOrderRepository,
)
from stocks_tool.repositories.sqlalchemy_trade_plan_repository import (
    SQLAlchemyTradePlanRepository,
)

logger = logging.getLogger(__name__)

WORKING_ORDER_STATUSES = {
    OrderStatus.CREATED,
    OrderStatus.SUBMITTED,
    OrderStatus.PARTIALLY_FILLED,
}

MONITORABLE_SPREAD_STATUSES = (
    SpreadStatus.OPEN,
    SpreadStatus.EXIT_PENDING_SHORT,
    SpreadStatus.EXIT_PENDING_LONG,
)


class ReconciliationCoordinator:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker,
        longbridge_adapter: LongbridgeBrokerAdapter,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.longbridge_adapter = longbridge_adapter

    def run_once(self) -> None:
        with self.session_factory() as session:
            broker_accounts = SQLAlchemyBrokerAccountRepository(session)
            account_snapshots = SQLAlchemyAccountSnapshotRepository(session)
            orders = SQLAlchemyOrderRepository(session)
            executions = SQLAlchemyExecutionRepository(session)
            trade_plans = SQLAlchemyTradePlanRepository(session)
            spreads = SQLAlchemyBullPutSpreadRepository(session)
            runtime_states = SQLAlchemyBullPutStrategyRuntimeRepository(session)
            account_service = LongbridgeIntegrationService(
                adapter=self.longbridge_adapter,
                broker_accounts=broker_accounts,
                account_snapshots=account_snapshots,
            )
            order_service = OrderService(
                settings=self.settings,
                broker_accounts=broker_accounts,
                trade_plans=trade_plans,
                orders=orders,
                executions=executions,
                longbridge_adapter=self.longbridge_adapter,
            )
            journal_service = JournalService(
                journals=SQLAlchemyJournalRepository(session),
                orders=orders,
                trade_plans=trade_plans,
                executions=executions,
            )
            strategy_service = BullPutStrategyService(
                settings=self.settings,
                broker_accounts=broker_accounts,
                account_snapshots=account_snapshots,
                spreads=spreads,
                runtime_states=runtime_states,
                order_service=order_service,
                longbridge_adapter=self.longbridge_adapter,
                risk_service=RiskService(settings=self.settings),
                journal_service=journal_service,
            )

            now = datetime.now(timezone.utc)
            for broker_account in broker_accounts.list_broker_accounts():
                if not broker_account.is_active or not broker_account.auto_reconcile_enabled:
                    continue
                if broker_account.broker != BrokerName.LONGBRIDGE:
                    continue

                account_due = self._is_due(
                    broker_account.account_last_sync_attempt_at,
                    self.settings.reconciliation_account_interval_seconds,
                    now,
                )
                if account_due:
                    try:
                        account_service.sync_account(
                            external_account_id=broker_account.external_account_id,
                            mode=ExecutionMode.PAPER,
                        )
                    except Exception:
                        logger.exception(
                            "Automatic account reconciliation failed for %s",
                            broker_account.external_account_id,
                        )

                account_orders = orders.list_orders(external_account_id=broker_account.external_account_id)
                has_working_orders = any(order.status in WORKING_ORDER_STATUSES for order in account_orders)
                orders_interval = (
                    self.settings.reconciliation_working_orders_interval_seconds
                    if has_working_orders
                    else self.settings.reconciliation_orders_interval_seconds
                )
                orders_due = self._is_due(
                    broker_account.orders_last_sync_attempt_at,
                    orders_interval,
                    now,
                )
                if orders_due:
                    try:
                        order_service.sync_today_orders(
                            external_account_id=broker_account.external_account_id,
                            mode=ExecutionMode.PAPER,
                        )
                    except Exception:
                        logger.exception(
                            "Automatic order reconciliation failed for %s",
                            broker_account.external_account_id,
                        )

                if not self.settings.bull_put_strategy.enabled:
                    continue
                if self.settings.bull_put_strategy.auto_scan_enabled:
                    try:
                        strategy_service.run_entry_scan(
                            external_account_id=broker_account.external_account_id,
                            mode=ExecutionMode.PAPER,
                            as_of=now,
                        )
                    except Exception:
                        logger.exception(
                            "Automatic bull put entry scan failed for %s",
                            broker_account.external_account_id,
                        )
                if self.settings.bull_put_strategy.auto_review_enabled:
                    try:
                        strategy_service.run_review(
                            external_account_id=broker_account.external_account_id,
                            mode=ExecutionMode.PAPER,
                            as_of=now,
                        )
                    except Exception:
                        logger.exception(
                            "Automatic bull put review failed for %s",
                            broker_account.external_account_id,
                        )
                if not self.settings.bull_put_strategy.auto_monitor_enabled:
                    continue

                for status in MONITORABLE_SPREAD_STATUSES:
                    account_spreads = spreads.list_spreads(
                        external_account_id=broker_account.external_account_id,
                        status=status,
                    )
                    for spread in account_spreads:
                        if not self._is_due(
                            spread.last_synced_at,
                            self.settings.bull_put_strategy.monitor_interval_seconds,
                            now,
                        ):
                            continue
                        try:
                            strategy_service.monitor_spread(spread.id, as_of=now)
                        except Exception:
                            logger.exception(
                                "Automatic bull put monitoring failed for spread %s",
                                spread.id,
                            )

    @staticmethod
    def _is_due(
        last_attempt_at: datetime | None,
        interval_seconds: int,
        now: datetime,
    ) -> bool:
        if last_attempt_at is None:
            return True
        return (now - last_attempt_at).total_seconds() >= interval_seconds


class ReconciliationScheduler:
    def __init__(
        self,
        *,
        coordinator: ReconciliationCoordinator,
        poll_interval_seconds: int,
    ) -> None:
        self.coordinator = coordinator
        self.poll_interval_seconds = poll_interval_seconds
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self.coordinator.run_once)
            except Exception:
                logger.exception("Automatic reconciliation loop failed.")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval_seconds,
                )
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop_event.set()

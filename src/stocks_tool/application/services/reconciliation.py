from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import sessionmaker

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeBrokerAdapter,
    LongbridgeIntegrationError,
)
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
from stocks_tool.repositories.sqlalchemy_pre_open_assessment_run_repository import (
    SQLAlchemyPreOpenAssessmentRunRepository,
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


@dataclass
class AutomaticTaskBackoffState:
    consecutive_failures: int = 0
    next_attempt_at: datetime | None = None


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
        self._automatic_task_backoffs: dict[tuple[str, str], AutomaticTaskBackoffState] = {}

    def run_once(self) -> None:
        with self.session_factory() as session:
            broker_accounts = SQLAlchemyBrokerAccountRepository(session)
            account_snapshots = SQLAlchemyAccountSnapshotRepository(session)
            orders = SQLAlchemyOrderRepository(session)
            executions = SQLAlchemyExecutionRepository(session)
            trade_plans = SQLAlchemyTradePlanRepository(session)
            spreads = SQLAlchemyBullPutSpreadRepository(session)
            runtime_states = SQLAlchemyBullPutStrategyRuntimeRepository(session)
            pre_open_runs = SQLAlchemyPreOpenAssessmentRunRepository(session)
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
                pre_open_runs=pre_open_runs,
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

                if self.settings.bull_put_strategy.enabled:
                    if self.settings.bull_put_strategy.auto_monitor_enabled:
                        self._monitor_due_spreads(
                            external_account_id=broker_account.external_account_id,
                            spreads=spreads,
                            strategy_service=strategy_service,
                            now=now,
                        )
                    if self.settings.bull_put_strategy.auto_scan_enabled:
                        self._run_account_task(
                            external_account_id=broker_account.external_account_id,
                            task_key="bull-put-scan",
                            task_label="bull put entry scan",
                            now=now,
                            callback=lambda: strategy_service.run_entry_scan(
                                external_account_id=broker_account.external_account_id,
                                mode=ExecutionMode.PAPER,
                                as_of=now,
                            ),
                        )
                    if self.settings.bull_put_strategy.auto_review_enabled:
                        self._run_account_task(
                            external_account_id=broker_account.external_account_id,
                            task_key="bull-put-review",
                            task_label="bull put review",
                            now=now,
                            callback=lambda: strategy_service.run_review(
                                external_account_id=broker_account.external_account_id,
                                mode=ExecutionMode.PAPER,
                                as_of=now,
                            ),
                        )
                    self._run_account_task(
                        external_account_id=broker_account.external_account_id,
                        task_key="pre-open-capture",
                        task_label="pre-open assessment capture",
                        now=now,
                        callback=lambda: strategy_service.capture_pre_open_run(
                            external_account_id=broker_account.external_account_id,
                            as_of=now,
                            automatic=True,
                        ),
                    )
                    self._run_account_task(
                        external_account_id=broker_account.external_account_id,
                        task_key="pre-open-review",
                        task_label="pre-open review",
                        now=now,
                        callback=lambda: strategy_service.review_pre_open_run(
                            external_account_id=broker_account.external_account_id,
                            as_of=now,
                        ),
                    )

                account_due = self._is_due(
                    broker_account.account_last_sync_attempt_at,
                    self.settings.reconciliation_account_interval_seconds,
                    now,
                )
                if account_due:
                    self._run_account_task(
                        external_account_id=broker_account.external_account_id,
                        task_key="account-sync",
                        task_label="account reconciliation",
                        now=now,
                        callback=lambda: account_service.sync_account(
                            external_account_id=broker_account.external_account_id,
                            mode=ExecutionMode.PAPER,
                        ),
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
                    self._run_account_task(
                        external_account_id=broker_account.external_account_id,
                        task_key="orders-sync",
                        task_label="order reconciliation",
                        now=now,
                        callback=lambda: order_service.sync_today_orders(
                            external_account_id=broker_account.external_account_id,
                            mode=ExecutionMode.PAPER,
                        ),
                    )

    def _run_account_task(
        self,
        *,
        external_account_id: str,
        task_key: str,
        task_label: str,
        now: datetime,
        callback: Callable[[], object],
    ) -> None:
        if self._is_task_backoff_active(
            external_account_id=external_account_id,
            task_key=task_key,
            now=now,
        ):
            return
        try:
            callback()
        except Exception as exc:
            if self._should_backoff_for_failure(exc):
                delay_seconds = self._record_task_backoff(
                    external_account_id=external_account_id,
                    task_key=task_key,
                    now=now,
                )
                logger.warning(
                    "Automatic %s failed for %s; backing off for %ss. %s",
                    task_label,
                    external_account_id,
                    delay_seconds,
                    exc,
                )
                return
            self._clear_task_backoff(
                external_account_id=external_account_id,
                task_key=task_key,
            )
            logger.exception(
                "Automatic %s failed for %s",
                task_label,
                external_account_id,
            )
            return
        self._clear_task_backoff(
            external_account_id=external_account_id,
            task_key=task_key,
        )

    def _monitor_due_spreads(
        self,
        *,
        external_account_id: str,
        spreads: SQLAlchemyBullPutSpreadRepository,
        strategy_service: BullPutStrategyService,
        now: datetime,
    ) -> None:
        task_key = "bull-put-monitor"
        if self._is_task_backoff_active(
            external_account_id=external_account_id,
            task_key=task_key,
            now=now,
        ):
            return

        executed_monitor = False
        for status in MONITORABLE_SPREAD_STATUSES:
            account_spreads = spreads.list_spreads(
                external_account_id=external_account_id,
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
                except Exception as exc:
                    if self._should_backoff_for_failure(exc):
                        delay_seconds = self._record_task_backoff(
                            external_account_id=external_account_id,
                            task_key=task_key,
                            now=now,
                        )
                        logger.warning(
                            "Automatic bull put monitoring failed for %s on spread %s; backing off for %ss. %s",
                            external_account_id,
                            spread.id,
                            delay_seconds,
                            exc,
                        )
                        return
                    self._clear_task_backoff(
                        external_account_id=external_account_id,
                        task_key=task_key,
                    )
                    logger.exception(
                        "Automatic bull put monitoring failed for spread %s",
                        spread.id,
                    )
                    continue
                executed_monitor = True
        if executed_monitor:
            self._clear_task_backoff(
                external_account_id=external_account_id,
                task_key=task_key,
            )

    def _is_task_backoff_active(
        self,
        *,
        external_account_id: str,
        task_key: str,
        now: datetime,
    ) -> bool:
        state = self._automatic_task_backoffs.get((external_account_id, task_key))
        if state is None or state.next_attempt_at is None:
            return False
        return now < state.next_attempt_at

    def _record_task_backoff(
        self,
        *,
        external_account_id: str,
        task_key: str,
        now: datetime,
    ) -> int:
        key = (external_account_id, task_key)
        state = self._automatic_task_backoffs.get(key, AutomaticTaskBackoffState())
        state.consecutive_failures += 1
        delay_seconds = self._task_backoff_delay_seconds(state.consecutive_failures)
        state.next_attempt_at = now + timedelta(seconds=delay_seconds)
        self._automatic_task_backoffs[key] = state
        return delay_seconds

    def _clear_task_backoff(
        self,
        *,
        external_account_id: str,
        task_key: str,
    ) -> None:
        self._automatic_task_backoffs.pop((external_account_id, task_key), None)

    def _task_backoff_delay_seconds(self, consecutive_failures: int) -> int:
        base_seconds = max(
            self.settings.reconciliation_poll_interval_seconds,
            self.settings.longbridge_circuit_breaker_seconds,
        )
        max_seconds = max(
            base_seconds,
            self.settings.reconciliation_account_interval_seconds,
            self.settings.reconciliation_orders_interval_seconds,
            self.settings.reconciliation_working_orders_interval_seconds,
            self.settings.bull_put_strategy.monitor_interval_seconds,
        )
        return min(max_seconds, base_seconds * (2 ** max(0, consecutive_failures - 1)))

    @staticmethod
    def _should_backoff_for_failure(exc: Exception) -> bool:
        if not isinstance(exc, LongbridgeIntegrationError):
            return False
        message = str(exc).lower()
        transient_markers = (
            "timed out",
            "timeout",
            "skipping attempt",
            "connectivity failed",
            "client error (connect)",
            "connection refused",
            "connection reset",
            "connection aborted",
            "dns",
            "socket/token",
            "network",
        )
        return any(marker in message for marker in transient_markers)

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

from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.application.services.longbridge_integration import (
    LongbridgeIntegrationService,
)
from stocks_tool.application.services.execution import ExecutionService
from stocks_tool.application.services.journal import JournalService
from stocks_tool.application.services.planner import PlannerService
from stocks_tool.application.services.research import ResearchService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.application.services.orders import OrderService
from stocks_tool.core.config import Settings, get_settings
from stocks_tool.db.session import get_db_session
from stocks_tool.ports.repository import TradePlanRepository
from stocks_tool.ports.repository import (
    AccountSnapshotRepository,
    BrokerAccountRepository,
    ExecutionRepository,
    JournalRepository,
    OrderRepository,
    WatchlistRepository,
)
from stocks_tool.repositories.sqlalchemy_order_repository import (
    SQLAlchemyOrderRepository,
)
from stocks_tool.repositories.sqlalchemy_execution_repository import (
    SQLAlchemyExecutionRepository,
)
from stocks_tool.repositories.sqlalchemy_journal_repository import (
    SQLAlchemyJournalRepository,
)
from stocks_tool.repositories.sqlalchemy_account_snapshot_repository import (
    SQLAlchemyAccountSnapshotRepository,
)
from stocks_tool.repositories.sqlalchemy_broker_account_repository import (
    SQLAlchemyBrokerAccountRepository,
)
from stocks_tool.repositories.sqlalchemy_trade_plan_repository import (
    SQLAlchemyTradePlanRepository,
)
from stocks_tool.repositories.sqlalchemy_watchlist_repository import (
    SQLAlchemyWatchlistRepository,
)


@lru_cache
def get_planner_service() -> PlannerService:
    return PlannerService()


@lru_cache
def get_research_service() -> ResearchService:
    return ResearchService()


@lru_cache
def get_risk_service() -> RiskService:
    settings: Settings = get_settings()
    return RiskService(settings=settings)


@lru_cache
def get_execution_service() -> ExecutionService:
    return ExecutionService()


def get_trade_plan_repository(
    session: Session = Depends(get_db_session),
) -> TradePlanRepository:
    return SQLAlchemyTradePlanRepository(session)


def get_watchlist_repository(
    session: Session = Depends(get_db_session),
) -> WatchlistRepository:
    return SQLAlchemyWatchlistRepository(session)


def get_broker_account_repository(
    session: Session = Depends(get_db_session),
) -> BrokerAccountRepository:
    return SQLAlchemyBrokerAccountRepository(session)


def get_account_snapshot_repository(
    session: Session = Depends(get_db_session),
) -> AccountSnapshotRepository:
    return SQLAlchemyAccountSnapshotRepository(session)


def get_order_repository(
    session: Session = Depends(get_db_session),
) -> OrderRepository:
    return SQLAlchemyOrderRepository(session)


def get_execution_repository(
    session: Session = Depends(get_db_session),
) -> ExecutionRepository:
    return SQLAlchemyExecutionRepository(session)


def get_journal_repository(
    session: Session = Depends(get_db_session),
) -> JournalRepository:
    return SQLAlchemyJournalRepository(session)


@lru_cache
def get_longbridge_adapter() -> LongbridgeBrokerAdapter:
    settings: Settings = get_settings()
    return LongbridgeBrokerAdapter(settings=settings)


def get_longbridge_integration_service(
    broker_accounts: BrokerAccountRepository = Depends(get_broker_account_repository),
    account_snapshots: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
    adapter: LongbridgeBrokerAdapter = Depends(get_longbridge_adapter),
) -> LongbridgeIntegrationService:
    return LongbridgeIntegrationService(
        adapter=adapter,
        broker_accounts=broker_accounts,
        account_snapshots=account_snapshots,
    )


def get_order_service(
    broker_accounts: BrokerAccountRepository = Depends(get_broker_account_repository),
    trade_plans: TradePlanRepository = Depends(get_trade_plan_repository),
    orders: OrderRepository = Depends(get_order_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
    adapter: LongbridgeBrokerAdapter = Depends(get_longbridge_adapter),
) -> OrderService:
    settings: Settings = get_settings()
    return OrderService(
        settings=settings,
        broker_accounts=broker_accounts,
        trade_plans=trade_plans,
        orders=orders,
        executions=executions,
        longbridge_adapter=adapter,
    )


def get_journal_service(
    journals: JournalRepository = Depends(get_journal_repository),
    orders: OrderRepository = Depends(get_order_repository),
    trade_plans: TradePlanRepository = Depends(get_trade_plan_repository),
    executions: ExecutionRepository = Depends(get_execution_repository),
) -> JournalService:
    return JournalService(
        journals=journals,
        orders=orders,
        trade_plans=trade_plans,
        executions=executions,
    )

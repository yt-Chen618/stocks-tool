from functools import lru_cache

from fastapi import Depends
from sqlalchemy.orm import Session

from stocks_tool.adapters.advisors.deepseek import DeepSeekAdvisorClient
from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.ports.broker_gateway import (
    BrokerGateway,
    BrokerIntegrationGateway,
    BrokerMarketDataGateway,
    BrokerOrderGateway,
)
from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.application.services.covered_call_strategy import CoveredCallStrategyService
from stocks_tool.application.services.zero_dte_lottery_strategy import (
    ZeroDteLotteryStrategyService,
)
from stocks_tool.application.services.longbridge_integration import (
    LongbridgeIntegrationService,
)
from stocks_tool.application.services.market_event_ingestion import (
    MarketEventIngestionService,
)
from stocks_tool.application.services.market_event_provider_ingestion import (
    MarketEventProviderIngestionService,
    SettingsMarketEventProviderFactory,
)
from stocks_tool.application.services.execution import ExecutionService
from stocks_tool.application.services.journal import JournalService
from stocks_tool.application.services.planner import PlannerService
from stocks_tool.application.services.research import ResearchService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.operator_status import OperatorStatusService
from stocks_tool.application.services.strategy_advisor_intake import (
    StrategyAdvisorIntakeService,
)
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.core.config import Settings, get_settings
from stocks_tool.db.session import get_db_session
from stocks_tool.ports.repository import (
    AccountSnapshotRepository,
    BrokerAccountRepository,
    BullPutSpreadRepository,
    BullPutStrategyRuntimeRepository,
    ExecutionRepository,
    JournalRepository,
    MarketEventRepository,
    OrderRepository,
    PreOpenAssessmentRunRepository,
    SchedulerJobRunRepository,
    StrategyAuditEventRepository,
    StrategyExperimentRepository,
    TradePlanRepository,
    WatchlistRepository,
)
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import (
    SQLAlchemyBullPutSpreadRepository,
)
from stocks_tool.repositories.sqlalchemy_bull_put_strategy_runtime_repository import (
    SQLAlchemyBullPutStrategyRuntimeRepository,
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
from stocks_tool.repositories.sqlalchemy_market_event_repository import (
    SQLAlchemyMarketEventRepository,
)
from stocks_tool.repositories.sqlalchemy_pre_open_assessment_run_repository import (
    SQLAlchemyPreOpenAssessmentRunRepository,
)
from stocks_tool.repositories.sqlalchemy_scheduler_job_run_repository import (
    SQLAlchemySchedulerJobRunRepository,
)
from stocks_tool.repositories.sqlalchemy_strategy_audit_event_repository import (
    SQLAlchemyStrategyAuditEventRepository,
)
from stocks_tool.repositories.sqlalchemy_strategy_experiment_repository import (
    SQLAlchemyStrategyExperimentRepository,
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


def get_market_event_repository(
    session: Session = Depends(get_db_session),
) -> MarketEventRepository:
    return SQLAlchemyMarketEventRepository(session)


def get_market_event_ingestion_service(
    repository: MarketEventRepository = Depends(get_market_event_repository),
) -> MarketEventIngestionService:
    return MarketEventIngestionService(repository)


def get_market_event_provider_ingestion_service(
    ingestion_service: MarketEventIngestionService = Depends(get_market_event_ingestion_service),
    settings: Settings = Depends(get_settings),
) -> MarketEventProviderIngestionService:
    return MarketEventProviderIngestionService(
        ingestion_service=ingestion_service,
        provider_factory=SettingsMarketEventProviderFactory(settings),
    )


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


def get_bull_put_spread_repository(
    session: Session = Depends(get_db_session),
) -> BullPutSpreadRepository:
    return SQLAlchemyBullPutSpreadRepository(session)


def get_bull_put_strategy_runtime_repository(
    session: Session = Depends(get_db_session),
) -> BullPutStrategyRuntimeRepository:
    return SQLAlchemyBullPutStrategyRuntimeRepository(session)


def get_pre_open_assessment_run_repository(
    session: Session = Depends(get_db_session),
) -> PreOpenAssessmentRunRepository:
    return SQLAlchemyPreOpenAssessmentRunRepository(session)


def get_scheduler_job_run_repository(
    session: Session = Depends(get_db_session),
) -> SchedulerJobRunRepository:
    return SQLAlchemySchedulerJobRunRepository(session)


def get_strategy_audit_event_repository(
    session: Session = Depends(get_db_session),
) -> StrategyAuditEventRepository:
    return SQLAlchemyStrategyAuditEventRepository(session)


def get_strategy_experiment_repository(
    session: Session = Depends(get_db_session),
) -> StrategyExperimentRepository:
    return SQLAlchemyStrategyExperimentRepository(session)


@lru_cache
def get_longbridge_adapter() -> BrokerGateway:
    settings: Settings = get_settings()
    return LongbridgeBrokerAdapter(settings=settings)


def get_longbridge_integration_service(
    broker_accounts: BrokerAccountRepository = Depends(get_broker_account_repository),
    account_snapshots: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
    adapter: BrokerIntegrationGateway = Depends(get_longbridge_adapter),
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
    audit_events: StrategyAuditEventRepository = Depends(get_strategy_audit_event_repository),
    adapter: BrokerOrderGateway = Depends(get_longbridge_adapter),
) -> OrderService:
    settings: Settings = get_settings()
    return OrderService(
        settings=settings,
        broker_accounts=broker_accounts,
        trade_plans=trade_plans,
        orders=orders,
        executions=executions,
        longbridge_adapter=adapter,
        audit_events=audit_events,
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


def get_strategy_experiment_service(
    experiments: StrategyExperimentRepository = Depends(get_strategy_experiment_repository),
    broker_accounts: BrokerAccountRepository = Depends(get_broker_account_repository),
    audit_events: StrategyAuditEventRepository = Depends(get_strategy_audit_event_repository),
    settings: Settings = Depends(get_settings),
) -> StrategyExperimentService:
    return StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=settings,
        audit_events=audit_events,
    )


def get_strategy_advisor_intake_service(
    strategy_experiments: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyAdvisorIntakeService:
    return StrategyAdvisorIntakeService(strategy_experiments=strategy_experiments)


def get_deepseek_advisor_client(
    settings: Settings = Depends(get_settings),
) -> DeepSeekAdvisorClient:
    return DeepSeekAdvisorClient(settings=settings)


def get_covered_call_strategy_service(
    broker_accounts: BrokerAccountRepository = Depends(get_broker_account_repository),
    account_snapshots: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
    experiments: StrategyExperimentRepository = Depends(get_strategy_experiment_repository),
    market_events: MarketEventRepository = Depends(get_market_event_repository),
    order_service: OrderService = Depends(get_order_service),
    adapter: BrokerMarketDataGateway = Depends(get_longbridge_adapter),
) -> CoveredCallStrategyService:
    settings: Settings = get_settings()
    return CoveredCallStrategyService(
        settings=settings,
        broker_accounts=broker_accounts,
        account_snapshots=account_snapshots,
        experiments=experiments,
        longbridge_adapter=adapter,
        order_service=order_service,
        market_events=market_events,
    )


def get_zero_dte_lottery_strategy_service(
    broker_accounts: BrokerAccountRepository = Depends(get_broker_account_repository),
    adapter: BrokerMarketDataGateway = Depends(get_longbridge_adapter),
    order_service: OrderService = Depends(get_order_service),
    experiments: StrategyExperimentRepository = Depends(get_strategy_experiment_repository),
) -> ZeroDteLotteryStrategyService:
    settings: Settings = get_settings()
    return ZeroDteLotteryStrategyService(
        settings=settings,
        broker_accounts=broker_accounts,
        longbridge_adapter=adapter,
        order_service=order_service,
        experiments=experiments,
    )


def get_bull_put_strategy_service(
    broker_accounts: BrokerAccountRepository = Depends(get_broker_account_repository),
    account_snapshots: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
    spreads: BullPutSpreadRepository = Depends(get_bull_put_spread_repository),
    runtime_states: BullPutStrategyRuntimeRepository = Depends(get_bull_put_strategy_runtime_repository),
    pre_open_runs: PreOpenAssessmentRunRepository = Depends(get_pre_open_assessment_run_repository),
    order_service: OrderService = Depends(get_order_service),
    adapter: BrokerMarketDataGateway = Depends(get_longbridge_adapter),
    risk_service: RiskService = Depends(get_risk_service),
    journal_service: JournalService = Depends(get_journal_service),
    audit_events: StrategyAuditEventRepository = Depends(get_strategy_audit_event_repository),
) -> BullPutStrategyService:
    settings: Settings = get_settings()
    return BullPutStrategyService(
        settings=settings,
        broker_accounts=broker_accounts,
        account_snapshots=account_snapshots,
        spreads=spreads,
        runtime_states=runtime_states,
        pre_open_runs=pre_open_runs,
        order_service=order_service,
        longbridge_adapter=adapter,
        risk_service=risk_service,
        journal_service=journal_service,
        audit_events=audit_events,
    )


def get_operator_status_service(
    strategy_experiments: StrategyExperimentService = Depends(get_strategy_experiment_service),
    bull_put_strategy: BullPutStrategyService = Depends(get_bull_put_strategy_service),
    zero_dte_lottery_strategy: ZeroDteLotteryStrategyService = Depends(get_zero_dte_lottery_strategy_service),
    order_service: OrderService = Depends(get_order_service),
    scheduler_job_runs: SchedulerJobRunRepository = Depends(get_scheduler_job_run_repository),
    audit_events: StrategyAuditEventRepository = Depends(get_strategy_audit_event_repository),
    adapter: BrokerIntegrationGateway = Depends(get_longbridge_adapter),
) -> OperatorStatusService:
    return OperatorStatusService(
        strategy_experiments=strategy_experiments,
        bull_put_strategy=bull_put_strategy,
        zero_dte_lottery_strategy=zero_dte_lottery_strategy,
        order_service=order_service,
        scheduler_job_runs=scheduler_job_runs,
        audit_events=audit_events,
        broker_adapter=adapter,
    )

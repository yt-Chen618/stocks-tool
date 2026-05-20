from functools import lru_cache

from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.application.services.execution import ExecutionService
from stocks_tool.application.services.planner import PlannerService
from stocks_tool.application.services.research import ResearchService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.core.config import Settings, get_settings
from stocks_tool.repositories.in_memory_trade_plan_repository import (
    InMemoryTradePlanRepository,
)


@lru_cache
def get_trade_plan_repository() -> InMemoryTradePlanRepository:
    return InMemoryTradePlanRepository()


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


@lru_cache
def get_longbridge_adapter() -> LongbridgeBrokerAdapter:
    settings: Settings = get_settings()
    return LongbridgeBrokerAdapter(settings=settings)


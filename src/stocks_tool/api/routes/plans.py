from fastapi import APIRouter, Depends, HTTPException

from stocks_tool.api.dependencies import (
    get_execution_service,
    get_planner_service,
    get_risk_service,
    get_trade_plan_repository,
)
from stocks_tool.application.services.execution import ExecutionService
from stocks_tool.application.services.planner import PlannerService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.domain.models import (
    DraftTradePlanRequest,
    OrderIntent,
    OrderIntentRequest,
    RiskEvaluationRequest,
    RiskCheckResult,
    TradePlan,
)
from stocks_tool.ports.repository import TradePlanRepository

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[TradePlan])
def list_trade_plans(
    repository: TradePlanRepository = Depends(get_trade_plan_repository),
) -> list[TradePlan]:
    return repository.list_plans()


@router.get("/{plan_id}", response_model=TradePlan)
def get_trade_plan(
    plan_id: str,
    repository: TradePlanRepository = Depends(get_trade_plan_repository),
) -> TradePlan:
    plan = repository.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Trade plan not found.")
    return plan


@router.post("/draft", response_model=TradePlan)
def draft_trade_plan(
    request: DraftTradePlanRequest,
    planner_service: PlannerService = Depends(get_planner_service),
    repository: TradePlanRepository = Depends(get_trade_plan_repository),
) -> TradePlan:
    plan = planner_service.build_plan(request)
    repository.save_plan(plan)
    return plan


@router.post("/validate", response_model=RiskCheckResult)
def validate_trade_plan(
    request: RiskEvaluationRequest,
    risk_service: RiskService = Depends(get_risk_service),
) -> RiskCheckResult:
    return risk_service.evaluate_trade_plan(
        plan=request.plan,
        account=request.account,
        mode=request.mode,
    )


@router.post("/order-intent", response_model=OrderIntent)
def build_order_intent(
    request: OrderIntentRequest,
    execution_service: ExecutionService = Depends(get_execution_service),
) -> OrderIntent:
    return execution_service.build_order_intent(
        plan=request.plan,
        broker=request.broker,
        quantity=request.quantity,
        mode=request.mode,
    )


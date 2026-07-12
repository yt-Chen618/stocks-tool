from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.api.dependencies import (
    get_longbridge_adapter,
    get_operator_consistency_service,
    get_operator_status_service,
    get_order_service,
)
from stocks_tool.application.services.orders import OrderService
from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.application.services.operator_consistency import OperatorConsistencyService
from stocks_tool.application.services.operator_status import OPERATOR_REASON_CODE_DETAILS, OperatorStatusService
from stocks_tool.domain.enums import ExecutionMode, TradingIntentState
from stocks_tool.domain.models import (
    OperatorConsistencyRepairRequest,
    OperatorConsistencyRepairResult,
    OperatorConsistencySummary,
    OperatorStatusSnapshot,
    MarketDataRuntimeSnapshot,
    BrokerOrderIntent,
    ResolveTradingIntentRequest,
    SchedulerStatusSnapshot,
    StrategyAuditEvent,
    StrategyAuditSummary,
    TradeActionIntent,
)


router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/trade-actions", response_model=list[TradeActionIntent])
def list_trade_actions(
    external_account_id: str | None = Query(default=None),
    mode: ExecutionMode | None = Query(default=None),
    state: TradingIntentState | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: OrderService = Depends(get_order_service),
) -> list[TradeActionIntent]:
    return service.list_trade_actions(
        external_account_id=external_account_id,
        mode=mode,
        state=state,
        limit=limit,
    )


@router.get("/trade-actions/{action_intent_id}", response_model=TradeActionIntent)
def get_trade_action(
    action_intent_id: str,
    service: OrderService = Depends(get_order_service),
) -> TradeActionIntent:
    action = service.get_trade_action(action_intent_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Trade action intent not found.")
    return action


@router.get("/trading-intents", response_model=list[BrokerOrderIntent])
def list_trading_intents(
    external_account_id: str | None = Query(default=None),
    mode: ExecutionMode | None = Query(default=None),
    state: TradingIntentState | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    service: OrderService = Depends(get_order_service),
) -> list[BrokerOrderIntent]:
    return service.list_trading_intents(
        external_account_id=external_account_id,
        mode=mode,
        state=state,
        limit=limit,
    )


@router.get("/trading-intents/{intent_id}", response_model=BrokerOrderIntent)
def get_trading_intent(
    intent_id: str,
    service: OrderService = Depends(get_order_service),
) -> BrokerOrderIntent:
    intent = service.get_trading_intent(intent_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="Trading intent not found.")
    return intent


@router.post(
    "/trading-intents/{intent_id}/resolve-no-order",
    response_model=BrokerOrderIntent,
)
def resolve_trading_intent_no_order(
    intent_id: str,
    request: ResolveTradingIntentRequest,
    service: OrderService = Depends(get_order_service),
) -> BrokerOrderIntent:
    try:
        return service.resolve_trading_intent_no_order(intent_id, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/reason-codes", response_model=dict[str, str])
def list_operator_reason_codes() -> dict[str, str]:
    return dict(sorted(OPERATOR_REASON_CODE_DETAILS.items()))


@router.get("/market-data-runtime", response_model=MarketDataRuntimeSnapshot)
def get_market_data_runtime(
    adapter: LongbridgeBrokerAdapter = Depends(get_longbridge_adapter),
) -> MarketDataRuntimeSnapshot:
    return adapter.get_market_data_runtime_status()


@router.get("/unattended-status", response_model=OperatorStatusSnapshot)
def get_unattended_operator_status(
    external_account_id: str = Query(..., description="Broker account id, e.g. LBPT10087357"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    service: OperatorStatusService = Depends(get_operator_status_service),
) -> OperatorStatusSnapshot:
    try:
        return service.get_unattended_status(
            external_account_id=external_account_id,
            mode=mode,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/consistency", response_model=OperatorConsistencySummary)
def get_operator_consistency_report(
    external_account_id: str = Query(..., description="Broker account id, e.g. LBPT10087357"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    strategy: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    service: OperatorConsistencyService = Depends(get_operator_consistency_service),
) -> OperatorConsistencySummary:
    try:
        return service.get_summary(
            external_account_id=external_account_id,
            mode=mode,
            strategy=strategy,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/consistency/repairs/{repair_id}", response_model=OperatorConsistencyRepairResult)
def apply_operator_consistency_repair(
    repair_id: str,
    request: OperatorConsistencyRepairRequest,
    service: OperatorConsistencyService = Depends(get_operator_consistency_service),
) -> OperatorConsistencyRepairResult:
    try:
        return service.apply_repair(repair_id=repair_id, request=request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/scheduler", response_model=SchedulerStatusSnapshot)
def get_scheduler_status(
    external_account_id: str | None = Query(default=None, description="Optional broker account id, e.g. LBPT10087357"),
    limit: int = Query(default=50, ge=1, le=200),
    service: OperatorStatusService = Depends(get_operator_status_service),
) -> SchedulerStatusSnapshot:
    return service.get_scheduler_status(
        external_account_id=external_account_id,
        limit=limit,
    )


@router.get("/audit", response_model=list[StrategyAuditEvent])
def list_operator_audit_events(
    external_account_id: str | None = Query(default=None, description="Optional broker account id, e.g. LBPT10087357"),
    mode: ExecutionMode | None = Query(default=None),
    source: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    action: str | None = Query(default=None),
    warning_only: bool = Query(default=False),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    service: OperatorStatusService = Depends(get_operator_status_service),
) -> list[StrategyAuditEvent]:
    try:
        return service.list_audit_events(
            external_account_id=external_account_id,
            mode=mode,
            source=source,
            strategy=strategy,
            action=action,
            warning_only=warning_only,
            since=since,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/audit/summary", response_model=StrategyAuditSummary)
def summarize_operator_audit_events(
    external_account_id: str | None = Query(default=None, description="Optional broker account id, e.g. LBPT10087357"),
    mode: ExecutionMode | None = Query(default=None),
    since: datetime | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
    service: OperatorStatusService = Depends(get_operator_status_service),
) -> StrategyAuditSummary:
    try:
        return service.get_audit_summary(
            external_account_id=external_account_id,
            mode=mode,
            since=since,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

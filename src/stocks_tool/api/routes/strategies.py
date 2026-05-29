from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import get_bull_put_strategy_service
from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.domain.enums import ExecutionMode, SpreadStatus
from stocks_tool.domain.models import (
    BullPutSpread,
    BullPutSpreadMonitorResult,
    BullPutSpreadScanResult,
    PreOpenDownsideAssessment,
    PreOpenAssessmentRun,
    PreOpenAssessmentCaptureResult,
    PreOpenAssessmentReviewResult,
    BullPutStrategyReviewResult,
    BullPutStrategyRuntimeState,
    BullPutStrategyScanRunResult,
    ExecuteBullPutSpreadRequest,
    UpdateBullPutStrategyRuntimeRequest,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/pre-open-risk", response_model=PreOpenDownsideAssessment)
def get_pre_open_risk_assessment(
    external_account_id: str | None = Query(
        default=None,
        description="Optional broker account id so the route can fall back to the latest stored run for that account.",
    ),
    as_of: datetime | None = Query(
        default=None,
        description="Optional UTC timestamp for deterministic pre-open checks, e.g. 2026-05-26T12:35:00Z",
    ),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> PreOpenDownsideAssessment:
    try:
        return service.get_pre_open_downside_assessment(
            as_of=as_of,
            external_account_id=external_account_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/pre-open-runs", response_model=list[PreOpenAssessmentRun])
def list_pre_open_runs(
    external_account_id: str | None = Query(default=None, description="Optional broker account id filter, e.g. LBPT10087357"),
    limit: int = Query(default=20, ge=1, le=100),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> list[PreOpenAssessmentRun]:
    return service.list_pre_open_runs(
        external_account_id=external_account_id,
        limit=limit,
    )


@router.post("/pre-open-runs/{external_account_id}/capture", response_model=PreOpenAssessmentCaptureResult)
def capture_pre_open_run(
    external_account_id: str,
    as_of: datetime | None = Query(default=None),
    force: bool = Query(default=False),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> PreOpenAssessmentCaptureResult:
    try:
        return service.capture_pre_open_run(
            external_account_id=external_account_id,
            as_of=as_of,
            force=force,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/pre-open-runs/{external_account_id}/review", response_model=PreOpenAssessmentReviewResult)
def review_pre_open_run(
    external_account_id: str,
    as_of: datetime | None = Query(default=None),
    force: bool = Query(default=False),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> PreOpenAssessmentReviewResult:
    try:
        return service.review_pre_open_run(
            external_account_id=external_account_id,
            as_of=as_of,
            force=force,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/bull-put/preview", response_model=BullPutSpreadScanResult)
def preview_bull_put_spread(
    external_account_id: str = Query(..., description="Local broker account id, e.g. LBPT10087357"),
    symbol: str = Query(..., description="Configured underlying symbol, e.g. QQQ.US"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    as_of: datetime | None = Query(
        default=None,
        description="Optional UTC timestamp for deterministic preview, e.g. 2026-05-22T15:00:00Z",
    ),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutSpreadScanResult:
    try:
        return service.preview_spread(
            external_account_id=external_account_id,
            symbol=symbol,
            mode=mode,
            as_of=as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/bull-put/spreads", response_model=list[BullPutSpread])
def list_bull_put_spreads(
    external_account_id: str | None = Query(
        default=None,
        description="Optional broker account id filter, e.g. LBPT10087357",
    ),
    status: SpreadStatus | None = Query(default=None),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> list[BullPutSpread]:
    return service.list_spreads(
        external_account_id=external_account_id,
        status=status,
    )


@router.get("/bull-put/spreads/{spread_id}", response_model=BullPutSpread)
def get_bull_put_spread(
    spread_id: str,
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutSpread:
    spread = service.get_spread(spread_id)
    if spread is None:
        raise HTTPException(status_code=404, detail="Bull put spread not found.")
    return spread


@router.get("/bull-put/runtime", response_model=BullPutStrategyRuntimeState)
def get_bull_put_runtime_state(
    external_account_id: str = Query(..., description="Broker account id, e.g. LBPT10087357"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutStrategyRuntimeState:
    try:
        return service.get_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bull-put/runtime/{external_account_id}", response_model=BullPutStrategyRuntimeState)
def update_bull_put_runtime_state(
    external_account_id: str,
    request: UpdateBullPutStrategyRuntimeRequest,
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutStrategyRuntimeState:
    try:
        return service.update_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bull-put/runtime/{external_account_id}/scan", response_model=BullPutStrategyScanRunResult)
def run_bull_put_runtime_scan(
    external_account_id: str,
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    force: bool = Query(default=False, description="Run outside the scheduled ET scan window."),
    as_of: datetime | None = Query(
        default=None,
        description="Optional UTC timestamp for deterministic auto-scan checks, e.g. 2026-05-23T14:45:00Z",
    ),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutStrategyScanRunResult:
    try:
        return service.run_entry_scan(
            external_account_id=external_account_id,
            mode=mode,
            as_of=as_of,
            force=force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/bull-put/runtime/{external_account_id}/review", response_model=BullPutStrategyReviewResult)
def run_bull_put_runtime_review(
    external_account_id: str,
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    force: bool = Query(default=False, description="Run even if the periodic review is not due yet."),
    as_of: datetime | None = Query(
        default=None,
        description="Optional UTC timestamp for deterministic review checks, e.g. 2026-06-22T15:00:00Z",
    ),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutStrategyReviewResult:
    try:
        return service.run_review(
            external_account_id=external_account_id,
            mode=mode,
            as_of=as_of,
            force=force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/bull-put/execute", response_model=BullPutSpread, status_code=201)
def execute_bull_put_spread(
    request: ExecuteBullPutSpreadRequest,
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutSpread:
    try:
        return service.execute_spread(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/bull-put/spreads/{spread_id}/refresh", response_model=BullPutSpread)
def refresh_bull_put_spread(
    spread_id: str,
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutSpread:
    try:
        return service.refresh_spread(spread_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/bull-put/spreads/{spread_id}/monitor", response_model=BullPutSpreadMonitorResult)
def monitor_bull_put_spread(
    spread_id: str,
    as_of: datetime | None = Query(
        default=None,
        description="Optional UTC timestamp for deterministic exit checks, e.g. 2026-05-23T15:00:00Z",
    ),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutSpreadMonitorResult:
    try:
        return service.monitor_spread(spread_id, as_of=as_of)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

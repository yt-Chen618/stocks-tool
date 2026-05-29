from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import (
    get_bull_put_strategy_service,
    get_covered_call_strategy_service,
    get_strategy_experiment_service,
)
from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.application.services.covered_call_strategy import CoveredCallStrategyService
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.domain.enums import ExecutionMode, SpreadStatus, StrategyProposalStatus
from stocks_tool.domain.models import (
    BullPutSpread,
    BullPutSpreadMonitorResult,
    BullPutSpreadScanResult,
    CreateStrategyProposalRequest,
    CreateStrategyReviewRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    PreOpenDownsideAssessment,
    PreOpenAssessmentRun,
    PreOpenAssessmentCaptureResult,
    PreOpenAssessmentReviewResult,
    BullPutStrategyReviewResult,
    BullPutStrategyReadinessResult,
    BullPutStrategyRuntimeState,
    BullPutStrategyScanRunResult,
    CoveredCallExecutionResult,
    CoveredCallMonitorResult,
    CoveredCallPreviewResult,
    CoveredCallProposalResult,
    ExecuteBullPutSpreadRequest,
    ExecuteCoveredCallProposalRequest,
    StrategyExperimentSnapshot,
    StrategyProposal,
    StrategyReview,
    StrategyRun,
    StrategySignal,
    UpdateBullPutStrategyRuntimeRequest,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("/covered-call/preview", response_model=CoveredCallPreviewResult)
def preview_covered_call(
    external_account_id: str = Query(..., description="Broker account id, e.g. LBPT10087357"),
    symbol: str | None = Query(default=None, description="Optional held stock/ETF symbol, e.g. UNH.US"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    as_of: datetime | None = Query(default=None),
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> CoveredCallPreviewResult:
    try:
        return service.preview(
            external_account_id=external_account_id,
            symbol=symbol,
            mode=mode,
            as_of=as_of,
        )
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


@router.post("/covered-call/propose", response_model=CoveredCallProposalResult)
def propose_covered_call(
    external_account_id: str = Query(..., description="Broker account id, e.g. LBPT10087357"),
    symbol: str | None = Query(default=None, description="Optional held stock/ETF symbol, e.g. UNH.US"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    as_of: datetime | None = Query(default=None),
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> CoveredCallProposalResult:
    try:
        return service.create_proposal(
            external_account_id=external_account_id,
            symbol=symbol,
            mode=mode,
            as_of=as_of,
        )
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


@router.post("/covered-call/proposals/{proposal_id}/execute", response_model=CoveredCallExecutionResult)
def execute_covered_call_proposal(
    proposal_id: str,
    request: ExecuteCoveredCallProposalRequest,
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> CoveredCallExecutionResult:
    try:
        return service.execute_approved_proposal(proposal_id, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/covered-call/proposals/{proposal_id}/monitor", response_model=CoveredCallMonitorResult)
def monitor_covered_call_proposal(
    proposal_id: str,
    as_of: datetime | None = Query(default=None),
    record_signal: bool = Query(default=True),
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> CoveredCallMonitorResult:
    try:
        return service.monitor_proposal(
            proposal_id,
            as_of=as_of,
            record_signal=record_signal,
        )
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


@router.get("/experiment", response_model=StrategyExperimentSnapshot)
def get_strategy_experiment_snapshot(
    external_account_id: str | None = Query(default=None, description="Optional broker account id filter, e.g. LBPT10087357"),
    strategy_id: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=100),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyExperimentSnapshot:
    try:
        return service.get_snapshot(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/proposals", response_model=list[StrategyProposal])
def list_strategy_proposals(
    external_account_id: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    status: StrategyProposalStatus | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> list[StrategyProposal]:
    try:
        return service.list_proposals(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            status=status,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/proposals", response_model=StrategyProposal, status_code=201)
def create_strategy_proposal(
    request: CreateStrategyProposalRequest,
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyProposal:
    try:
        return service.create_proposal(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/proposals/{proposal_id}/approve", response_model=StrategyProposal)
def approve_strategy_proposal(
    proposal_id: str,
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyProposal:
    try:
        return service.approve_proposal(proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/proposals/{proposal_id}/reject", response_model=StrategyProposal)
def reject_strategy_proposal(
    proposal_id: str,
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyProposal:
    try:
        return service.reject_proposal(proposal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/runs", response_model=list[StrategyRun])
def list_strategy_runs(
    external_account_id: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> list[StrategyRun]:
    try:
        return service.list_runs(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs", response_model=StrategyRun, status_code=201)
def create_strategy_run(
    request: CreateStrategyRunRequest,
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyRun:
    try:
        return service.create_run(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/signals", response_model=list[StrategySignal])
def list_strategy_signals(
    external_account_id: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> list[StrategySignal]:
    try:
        return service.list_signals(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/signals", response_model=StrategySignal, status_code=201)
def create_strategy_signal(
    request: CreateStrategySignalRequest,
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategySignal:
    try:
        return service.create_signal(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reviews", response_model=list[StrategyReview])
def list_strategy_reviews(
    external_account_id: str | None = Query(default=None),
    strategy_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> list[StrategyReview]:
    try:
        return service.list_reviews(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reviews", response_model=StrategyReview, status_code=201)
def create_strategy_review(
    request: CreateStrategyReviewRequest,
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyReview:
    try:
        return service.create_review(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    include_option_overlays: bool = Query(
        default=False,
        description="When true, also load directional put and option-chain overlays. Defaults off so the dashboard refresh stays responsive.",
    ),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> PreOpenDownsideAssessment:
    try:
        return service.get_pre_open_downside_assessment(
            as_of=as_of,
            external_account_id=external_account_id,
            include_option_overlays=include_option_overlays,
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
    include_option_overlays: bool = Query(
        default=False,
        description="When true, persist slower directional put and option-chain overlays with the capture.",
    ),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> PreOpenAssessmentCaptureResult:
    try:
        return service.capture_pre_open_run(
            external_account_id=external_account_id,
            as_of=as_of,
            force=force,
            include_option_overlays=include_option_overlays,
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


@router.get("/bull-put/readiness", response_model=BullPutStrategyReadinessResult)
def check_bull_put_readiness(
    external_account_id: str = Query(..., description="Broker account id, e.g. LBPT10087357"),
    symbol: str | None = Query(default=None, description="Optional configured symbol to check first, e.g. QQQ.US"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    as_of: datetime | None = Query(
        default=None,
        description="Optional UTC timestamp for deterministic readiness checks, e.g. 2026-05-22T14:45:00Z",
    ),
    service: BullPutStrategyService = Depends(get_bull_put_strategy_service),
) -> BullPutStrategyReadinessResult:
    try:
        return service.check_entry_readiness(
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

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from stocks_tool.adapters.advisors.deepseek import DeepSeekAdvisorClient, DeepSeekAdvisorError
from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import (
    get_deepseek_advisor_client,
    get_bull_put_strategy_service,
    get_covered_call_strategy_service,
    get_strategy_advisor_intake_service,
    get_strategy_experiment_service,
)
from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.application.services.covered_call_strategy import CoveredCallStrategyService
from stocks_tool.application.services.strategy_advisor_intake import StrategyAdvisorIntakeService
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.domain.enums import (
    ExecutionMode,
    SpreadStatus,
    StrategyAdvisorRunStatus,
    StrategyProposalStatus,
)
from stocks_tool.domain.models import (
    BullPutSpread,
    BullPutSpreadMonitorResult,
    BullPutSpreadScanResult,
    CreateStrategyProposalRequest,
    CreateStrategyAdvisorRunRequest,
    CreateStrategyReviewRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    DeepSeekAdvisorDryRunResult,
    PreOpenDownsideAssessment,
    PreOpenAssessmentRun,
    PreOpenAssessmentCaptureResult,
    PreOpenAssessmentReviewResult,
    RecordStrategyAdvisorResponseRequest,
    RunDeepSeekAdvisorRequest,
    BullPutStrategyReviewResult,
    BullPutStrategyReadinessResult,
    BullPutStrategyRuntimeState,
    BullPutStrategyScanRunResult,
    CloseCoveredCallProposalRequest,
    ContinueCoveredCallRollRequest,
    CoveredCallActivitySnapshot,
    CreateCoveredCallRollProposalRequest,
    CoveredCallCloseResult,
    CoveredCallExecutionResult,
    CoveredCallMonitorResult,
    CoveredCallPreviewResult,
    CoveredCallProposalResult,
    CoveredCallRollExecutionResult,
    CoveredCallRollProposalResult,
    ExecuteBullPutSpreadRequest,
    ExecuteCoveredCallProposalRequest,
    ExecuteCoveredCallRollProposalRequest,
    StrategyAdvisorContext,
    StrategyAdvisorRun,
    StrategyAdvisorResponseResult,
    StrategyControlSnapshot,
    StrategyExperimentSnapshot,
    StrategyProposalDecisionRequest,
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


@router.post("/covered-call/proposals/{proposal_id}/roll-propose", response_model=CoveredCallRollProposalResult)
def propose_covered_call_roll(
    proposal_id: str,
    request: CreateCoveredCallRollProposalRequest,
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> CoveredCallRollProposalResult:
    try:
        return service.create_roll_proposal(proposal_id, request)
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


@router.post("/covered-call/proposals/{proposal_id}/roll-execute", response_model=CoveredCallRollExecutionResult)
def execute_covered_call_roll_proposal(
    proposal_id: str,
    request: ExecuteCoveredCallRollProposalRequest,
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> CoveredCallRollExecutionResult:
    try:
        return service.execute_approved_roll_proposal(proposal_id, request)
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


@router.post("/covered-call/proposals/{proposal_id}/roll-continue", response_model=CoveredCallRollExecutionResult)
def continue_covered_call_roll_proposal(
    proposal_id: str,
    request: ContinueCoveredCallRollRequest,
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> CoveredCallRollExecutionResult:
    try:
        return service.continue_roll_proposal(proposal_id, request)
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


@router.post("/covered-call/proposals/{proposal_id}/close", response_model=CoveredCallCloseResult)
def close_covered_call_proposal(
    proposal_id: str,
    request: CloseCoveredCallProposalRequest,
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> CoveredCallCloseResult:
    try:
        return service.close_proposal(proposal_id, request)
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


@router.get("/covered-call/activity", response_model=CoveredCallActivitySnapshot)
def get_covered_call_activity(
    external_account_id: str | None = Query(default=None, description="Optional broker account id filter, e.g. LBPT10087357"),
    limit: int = Query(default=12, ge=1, le=100),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> CoveredCallActivitySnapshot:
    try:
        return service.get_covered_call_activity(
            external_account_id=external_account_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/covered-call/lifecycle/{external_account_id}/reconcile")
def reconcile_covered_call_lifecycle(
    external_account_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    service: CoveredCallStrategyService = Depends(get_covered_call_strategy_service),
) -> dict[str, int]:
    try:
        return service.reconcile_pending_lifecycle(
            external_account_id=external_account_id,
            limit=limit,
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


@router.get("/controls", response_model=StrategyControlSnapshot)
def get_strategy_controls(
    external_account_id: str | None = Query(default=None),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyControlSnapshot:
    try:
        return service.get_control_snapshot(external_account_id=external_account_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/advisor-context", response_model=StrategyAdvisorContext)
def get_strategy_advisor_context(
    external_account_id: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyAdvisorContext:
    try:
        return service.get_advisor_context(
            external_account_id=external_account_id,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/advisor/deepseek/dry-run", response_model=DeepSeekAdvisorDryRunResult)
def run_deepseek_advisor_dry_run(
    request: RunDeepSeekAdvisorRequest,
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
    advisor_client: DeepSeekAdvisorClient = Depends(get_deepseek_advisor_client),
) -> DeepSeekAdvisorDryRunResult:
    started_at = datetime.now(timezone.utc)
    context: StrategyAdvisorContext | None = None
    try:
        context = service.get_advisor_context(
            external_account_id=request.external_account_id,
            limit=request.context_limit,
        )
        response_payload = advisor_client.create_advisor_response(
            context=context,
            model=request.model,
        )
        recordable_payload = RecordStrategyAdvisorResponseRequest.model_validate(
            {
                "external_account_id": request.external_account_id,
                "source": "deepseek",
                "mode": ExecutionMode.PAPER,
                "context_limit": request.context_limit,
                **response_payload,
            }
        )
        completed_at = datetime.now(timezone.utc)
        advisor_run = service.create_advisor_run(
            _advisor_run_request_from_payload(
                external_account_id=request.external_account_id,
                context_limit=request.context_limit,
                response_payload=recordable_payload,
                status=StrategyAdvisorRunStatus.SUCCEEDED,
                started_at=started_at,
                completed_at=completed_at,
            )
        )
        recordable_payload.advisor_run_id = advisor_run.id
        return DeepSeekAdvisorDryRunResult(
            external_account_id=request.external_account_id,
            context=context,
            response_payload=recordable_payload,
            advisor_run=advisor_run,
            generated_at=completed_at,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DeepSeekAdvisorError as exc:
        if context is not None:
            _record_failed_advisor_run(
                service=service,
                external_account_id=request.external_account_id,
                context_limit=request.context_limit,
                model=request.model,
                error=exc,
                started_at=started_at,
            )
        status_code = 400 if "configured" in str(exc).lower() else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/advisor/runs", response_model=list[StrategyAdvisorRun])
def list_strategy_advisor_runs(
    external_account_id: str | None = Query(default=None),
    source: str | None = Query(default="deepseek"),
    limit: int = Query(default=10, ge=1, le=50),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> list[StrategyAdvisorRun]:
    try:
        return service.list_advisor_runs(
            external_account_id=external_account_id,
            source=source,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/advisor/responses", response_model=StrategyAdvisorResponseResult, status_code=201)
def record_strategy_advisor_response(
    request: RecordStrategyAdvisorResponseRequest,
    service: StrategyAdvisorIntakeService = Depends(get_strategy_advisor_intake_service),
) -> StrategyAdvisorResponseResult:
    try:
        return service.record_response(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _advisor_run_request_from_payload(
    *,
    external_account_id: str,
    context_limit: int,
    response_payload: RecordStrategyAdvisorResponseRequest,
    status: StrategyAdvisorRunStatus,
    started_at: datetime,
    completed_at: datetime,
    error_message: str | None = None,
) -> CreateStrategyAdvisorRunRequest:
    raw_response = response_payload.raw_response if isinstance(response_payload.raw_response, dict) else {}
    usage = raw_response.get("usage") if isinstance(raw_response.get("usage"), dict) else {}
    prompt_details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    completion_details = (
        usage.get("completion_tokens_details")
        if isinstance(usage.get("completion_tokens_details"), dict)
        else {}
    )
    proposal_count = len(response_payload.proposals)
    review_count = len(response_payload.reviews)
    response_json = response_payload.model_dump(mode="json", exclude_none=True)
    return CreateStrategyAdvisorRunRequest(
        external_account_id=external_account_id,
        source=response_payload.source,
        mode=ExecutionMode.PAPER,
        provider=_str_or_none(raw_response.get("provider")) or "deepseek",
        model=_str_or_none(raw_response.get("model")),
        status=status,
        context_format=DeepSeekAdvisorClient.context_format,
        context_limit=context_limit,
        prompt_tokens=_int_or_none(usage.get("prompt_tokens")),
        completion_tokens=_int_or_none(usage.get("completion_tokens")),
        total_tokens=_int_or_none(usage.get("total_tokens")),
        reasoning_tokens=_int_or_none(completion_details.get("reasoning_tokens")),
        cache_hit_tokens=_first_int_or_none(usage.get("prompt_cache_hit_tokens"), prompt_details.get("cached_tokens")),
        cache_miss_tokens=_int_or_none(usage.get("prompt_cache_miss_tokens")),
        proposal_count=proposal_count,
        review_count=review_count,
        response_id=_str_or_none(raw_response.get("response_id")),
        finish_reason=_str_or_none(raw_response.get("finish_reason")),
        error_message=error_message,
        response_payload=response_json,
        raw_response=raw_response or None,
        started_at=started_at,
        completed_at=completed_at,
    )


def _record_failed_advisor_run(
    *,
    service: StrategyExperimentService,
    external_account_id: str,
    context_limit: int,
    model: str | None,
    error: Exception,
    started_at: datetime,
) -> None:
    failed_at = datetime.now(timezone.utc)
    try:
        service.create_advisor_run(
            CreateStrategyAdvisorRunRequest(
                external_account_id=external_account_id,
                source="deepseek",
                mode=ExecutionMode.PAPER,
                provider="deepseek",
                model=model,
                status=StrategyAdvisorRunStatus.FAILED,
                context_format=DeepSeekAdvisorClient.context_format,
                context_limit=context_limit,
                error_message=str(error),
                started_at=started_at,
                completed_at=failed_at,
            )
        )
    except Exception:
        # The caller should still receive the original DeepSeek failure.
        pass


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _first_int_or_none(*values: Any) -> int | None:
    for value in values:
        parsed = _int_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
    request: StrategyProposalDecisionRequest | None = Body(default=None),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyProposal:
    try:
        decision = request or StrategyProposalDecisionRequest()
        return service.approve_proposal(
            proposal_id,
            actor=decision.actor,
            note=decision.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/proposals/{proposal_id}/reject", response_model=StrategyProposal)
def reject_strategy_proposal(
    proposal_id: str,
    request: StrategyProposalDecisionRequest | None = Body(default=None),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyProposal:
    try:
        decision = request or StrategyProposalDecisionRequest()
        return service.reject_proposal(
            proposal_id,
            actor=decision.actor,
            note=decision.note,
        )
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

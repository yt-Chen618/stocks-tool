from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import (
    get_covered_call_strategy_service,
    get_strategy_experiment_service,
)
from stocks_tool.application.services.covered_call_strategy import CoveredCallStrategyService
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    CloseCoveredCallProposalRequest,
    ContinueCoveredCallRollRequest,
    CoveredCallActivitySnapshot,
    CoveredCallCloseResult,
    CoveredCallExecutionResult,
    CoveredCallMonitorResult,
    CoveredCallPreviewResult,
    CoveredCallProposalResult,
    CoveredCallRollExecutionResult,
    CoveredCallRollProposalResult,
    CreateCoveredCallRollProposalRequest,
    ExecuteCoveredCallProposalRequest,
    ExecuteCoveredCallRollProposalRequest,
)

router = APIRouter()


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

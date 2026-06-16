from fastapi import APIRouter, Body, Depends, HTTPException, Query

from stocks_tool.api.dependencies import get_strategy_experiment_service
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.domain.enums import StrategyProposalStatus
from stocks_tool.domain.models import (
    CreateStrategyProposalRequest,
    CreateStrategyReviewRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    StrategyControlSnapshot,
    StrategyExperimentSnapshot,
    StrategyProposal,
    StrategyProposalDecisionRequest,
    StrategyReview,
    StrategyRun,
    StrategySignal,
)

router = APIRouter()


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

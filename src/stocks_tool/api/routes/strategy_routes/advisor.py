import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.adapters.advisors.deepseek import DeepSeekAdvisorClient, DeepSeekAdvisorError
from stocks_tool.api.dependencies import (
    get_deepseek_advisor_client,
    get_strategy_advisor_intake_service,
    get_strategy_experiment_service,
)
from stocks_tool.application.services.strategy_advisor_intake import StrategyAdvisorIntakeService
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.domain.enums import ExecutionMode, StrategyAdvisorRunStatus
from stocks_tool.domain.models import (
    AdvisorPlaybook,
    AdvisorRunCard,
    CreateStrategyAdvisorRunRequest,
    DeepSeekAdvisorDryRunResult,
    RecordStrategyAdvisorResponseRequest,
    RunDeepSeekAdvisorRequest,
    StrategyAdvisorAuditSnapshot,
    StrategyAdvisorContext,
    StrategyAdvisorResponseResult,
    StrategyAdvisorRun,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_SENSITIVE_ERROR_VALUE = re.compile(
    r"(?i)(api[_ -]?key|authorization|token|secret)(\s*[:=]\s*)([^\s,;]+)"
)


@router.get("/advisor-context", response_model=StrategyAdvisorContext)
def get_strategy_advisor_context(
    external_account_id: str | None = Query(default=None),
    mode: ExecutionMode | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyAdvisorContext:
    try:
        return service.get_advisor_context(
            external_account_id=external_account_id,
            mode=mode,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/advisor/playbooks", response_model=list[AdvisorPlaybook])
def list_strategy_advisor_playbooks(
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> list[AdvisorPlaybook]:
    return service.list_advisor_playbooks()


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
        advisor_run_id = str(uuid4())
        response_payload = advisor_client.create_advisor_response(
            context=context,
            model=request.model,
        )
        recordable_payload = RecordStrategyAdvisorResponseRequest.model_validate(
            {
                **response_payload,
                "external_account_id": request.external_account_id,
                "source": "deepseek",
                "mode": ExecutionMode.PAPER,
                "context_limit": request.context_limit,
                "advisor_run_id": advisor_run_id,
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
                advisor_run_id=advisor_run_id,
            )
        status_code = 400 if "configured" in str(exc).lower() else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/advisor/audit", response_model=StrategyAdvisorAuditSnapshot)
def get_strategy_advisor_audit(
    external_account_id: str | None = Query(default=None),
    source: str | None = Query(default="deepseek"),
    limit: int = Query(default=10, ge=1, le=50),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> StrategyAdvisorAuditSnapshot:
    try:
        return service.get_advisor_audit_snapshot(
            external_account_id=external_account_id,
            source=source,
            limit=limit,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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


@router.get("/advisor/run-cards", response_model=list[AdvisorRunCard])
def list_strategy_advisor_run_cards(
    external_account_id: str | None = Query(default=None),
    source: str | None = Query(default="deepseek"),
    limit: int = Query(default=10, ge=1, le=50),
    service: StrategyExperimentService = Depends(get_strategy_experiment_service),
) -> list[AdvisorRunCard]:
    try:
        return service.list_advisor_run_cards(
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
        detail = str(exc)
        status_code = 409 if any(
            phrase in detail
            for phrase in ("different response payload", "replay could not recover")
        ) else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


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
        id=response_payload.advisor_run_id,
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
    advisor_run_id: str,
) -> None:
    failed_at = datetime.now(timezone.utc)
    try:
        service.create_advisor_run(
            CreateStrategyAdvisorRunRequest(
                id=advisor_run_id,
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
    except Exception as record_error:
        logger.warning(
            "advisor_dry_run_failure_record_failed",
            extra={
                "event": "advisor_dry_run_failure_record_failed",
                "external_account_id": external_account_id,
                "advisor_run_id": advisor_run_id,
                "provider": "deepseek",
                "provider_error_type": type(error).__name__,
                "provider_error": _redact_error(error),
                "record_error_type": type(record_error).__name__,
                "record_error": _redact_error(record_error),
            },
        )


def _redact_error(error: Exception) -> str:
    message = _SENSITIVE_ERROR_VALUE.sub(r"\1\2[REDACTED]", str(error))
    return message[:500]


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

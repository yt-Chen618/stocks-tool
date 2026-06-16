from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import get_bull_put_strategy_service
from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.domain.models import (
    PreOpenAssessmentCaptureResult,
    PreOpenAssessmentReviewResult,
    PreOpenAssessmentRun,
    PreOpenDownsideAssessment,
)

router = APIRouter()


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

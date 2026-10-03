"""Read-only-safe dataset and offline backtest HTTP contracts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stocks_tool.api.dependencies import get_db_session
from stocks_tool.adapters.backtesting.engine_lock import LEAN_ENGINE_IMAGE_DIGEST, LEAN_ENGINE_VERSION
from stocks_tool.core.config import get_settings
from stocks_tool.domain.backtesting import (
    BACKTEST_DEFAULT_END,
    BACKTEST_DEFAULT_START,
    BacktestCompareRequest,
    BacktestComparison,
    BacktestCreate,
    BacktestRun,
    BacktestState,
    DatasetRegistration,
    DatasetSummary,
    DatasetValidationReport,
)
from stocks_tool.repositories.sqlalchemy_backtest_repository import SQLAlchemyBacktestRepository
from stocks_tool.db.session import get_session_factory
from stocks_tool.application.services.backtesting import (
    BacktestDatasetConflictError,
    BacktestDataBlockedError,
    BacktestFreezeError,
    BacktestNotFoundError,
    BacktestingService,
    DatasetNotFoundError,
)

router = APIRouter(prefix="/backtests", tags=["backtests"])


class DatasetValidateRequest(BaseModel):
    strategy: str | None = Field(default=None, max_length=32)
    start_date: date = BACKTEST_DEFAULT_START
    end_date: date = BACKTEST_DEFAULT_END


def get_backtesting_service(
    session: Session = Depends(get_db_session),
) -> BacktestingService:
    """Build the service without passing environment secrets to LEAN."""

    settings = get_settings()
    data_root = Path(settings.backtest_data_root)
    result_root = Path(settings.backtest_result_root)
    digest = settings.lean_image_digest or LEAN_ENGINE_IMAGE_DIGEST
    return BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=data_root,
        result_root=result_root,
        engine_image_digest=digest,
        engine_version=LEAN_ENGINE_VERSION,
        # A worker must open its own session after the request session closes.
        session_factory=get_session_factory(),
        auto_start=False,
    )


@router.post("/datasets", response_model=DatasetSummary, status_code=201)
def register_dataset(
    request: DatasetRegistration,
    service: BacktestingService = Depends(get_backtesting_service),
) -> DatasetSummary:
    try:
        return service.register_dataset(request)
    except BacktestDatasetConflictError as exc:
        raise HTTPException(status_code=409, detail={"code": "dataset_identity_conflict", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "dataset_invalid", "message": str(exc)}) from exc


@router.get("/datasets", response_model=list[DatasetSummary])
def list_datasets(
    service: BacktestingService = Depends(get_backtesting_service),
) -> list[DatasetSummary]:
    return service.repository.list_datasets()


@router.get("/datasets/{dataset_id}", response_model=DatasetSummary)
def get_dataset(
    dataset_id: str,
    service: BacktestingService = Depends(get_backtesting_service),
) -> DatasetSummary:
    dataset = service.repository.get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail={"code": "dataset_not_found", "dataset_id": dataset_id})
    return dataset


@router.post("/datasets/{dataset_id}/validate", response_model=DatasetValidationReport)
def validate_dataset(
    dataset_id: str,
    request: DatasetValidateRequest | None = None,
    service: BacktestingService = Depends(get_backtesting_service),
) -> DatasetValidationReport:
    request = request or DatasetValidateRequest()
    try:
        return service.validate_dataset(
            dataset_id,
            strategy=request.strategy,
            start_date=request.start_date,
            end_date=request.end_date,
        )
    except DatasetNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "dataset_not_found", "dataset_id": dataset_id}) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "dataset_invalid", "message": str(exc)}) from exc


@router.post("", response_model=BacktestRun, status_code=201)
def create_backtest(
    request: BacktestCreate,
    service: BacktestingService = Depends(get_backtesting_service),
) -> BacktestRun:
    try:
        return service.create_backtest(request)
    except BacktestFreezeError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except BacktestDataBlockedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "blocked_data", "message": str(exc)},
        ) from exc
    except DatasetNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "dataset_not_found", "dataset_id": request.dataset_id}) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "backtest_invalid", "message": str(exc)}) from exc


@router.get("", response_model=list[BacktestRun])
def list_backtests(
    state: BacktestState | None = Query(default=None),
    dataset_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=100, ge=1, le=500),
    service: BacktestingService = Depends(get_backtesting_service),
) -> list[BacktestRun]:
    return service.list_backtests(state=state, dataset_id=dataset_id, limit=limit)


@router.post("/compare", response_model=BacktestComparison)
def compare_backtests(
    request: BacktestCompareRequest,
    service: BacktestingService = Depends(get_backtesting_service),
) -> BacktestComparison:
    return service.compare_backtests(request)


@router.get("/{run_id}", response_model=BacktestRun)
def get_backtest(
    run_id: str,
    service: BacktestingService = Depends(get_backtesting_service),
) -> BacktestRun:
    try:
        return service.get_backtest(run_id)
    except BacktestNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "backtest_not_found", "run_id": run_id}) from None


@router.post("/{run_id}/start", response_model=BacktestRun)
def start_backtest(
    run_id: str,
    service: BacktestingService = Depends(get_backtesting_service),
) -> BacktestRun:
    try:
        service.dispatch(run_id)
        return service.get_backtest(run_id)
    except BacktestNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "backtest_not_found", "run_id": run_id}) from None


@router.post("/{run_id}/cancel", response_model=BacktestRun)
def cancel_backtest(
    run_id: str,
    service: BacktestingService = Depends(get_backtesting_service),
) -> BacktestRun:
    try:
        return service.cancel_backtest(run_id)
    except BacktestNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "backtest_not_found", "run_id": run_id}) from None

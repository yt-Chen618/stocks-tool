from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import get_zero_dte_lottery_strategy_service
from stocks_tool.application.services.zero_dte_lottery_strategy import (
    ZeroDteLotteryStrategyService,
)
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    ExecuteZeroDteLotteryRequest,
    UpdateZeroDteLotteryRuntimeRequest,
    ZeroDteLotteryExecutionResult,
    ZeroDteLotteryPreviewResult,
    ZeroDteLotteryRuntimeState,
    ZeroDteLotteryScanResult,
)

router = APIRouter()


@router.get("/zero-dte-lottery/preview", response_model=ZeroDteLotteryPreviewResult)
def preview_zero_dte_lottery(
    external_account_id: str = Query(..., description="Broker account id, e.g. LBPT10087357"),
    symbol: str | None = Query(default=None, description="Configured lottery symbol, e.g. QQQ.US"),
    direction: str = Query(default="auto", description="auto, call, or put"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    as_of: datetime | None = Query(default=None),
    service: ZeroDteLotteryStrategyService = Depends(get_zero_dte_lottery_strategy_service),
) -> ZeroDteLotteryPreviewResult:
    try:
        return service.preview(
            external_account_id=external_account_id,
            symbol=symbol,
            direction=direction,
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


@router.post("/zero-dte-lottery/execute", response_model=ZeroDteLotteryExecutionResult, status_code=201)
def execute_zero_dte_lottery(
    request: ExecuteZeroDteLotteryRequest,
    service: ZeroDteLotteryStrategyService = Depends(get_zero_dte_lottery_strategy_service),
) -> ZeroDteLotteryExecutionResult:
    try:
        return service.execute(request)
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


@router.get("/zero-dte-lottery/runtime", response_model=ZeroDteLotteryRuntimeState)
def get_zero_dte_lottery_runtime(
    external_account_id: str = Query(..., description="Broker account id, e.g. LBPT10087357"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    service: ZeroDteLotteryStrategyService = Depends(get_zero_dte_lottery_strategy_service),
) -> ZeroDteLotteryRuntimeState:
    try:
        return service.get_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/zero-dte-lottery/runtime/{external_account_id}", response_model=ZeroDteLotteryRuntimeState)
def update_zero_dte_lottery_runtime(
    external_account_id: str,
    request: UpdateZeroDteLotteryRuntimeRequest,
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    service: ZeroDteLotteryStrategyService = Depends(get_zero_dte_lottery_strategy_service),
) -> ZeroDteLotteryRuntimeState:
    try:
        return service.update_runtime_state(
            external_account_id=external_account_id,
            request=request,
            mode=mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/zero-dte-lottery/runtime/{external_account_id}/scan", response_model=ZeroDteLotteryScanResult)
def run_zero_dte_lottery_scan(
    external_account_id: str,
    symbol: str | None = Query(default=None, description="Configured lottery symbol, e.g. QQQ.US"),
    direction: str = Query(default="auto", description="auto, call, or put"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    force: bool = Query(default=False, description="Run even when auto-execution is disabled or outside the scan window."),
    as_of: datetime | None = Query(default=None),
    service: ZeroDteLotteryStrategyService = Depends(get_zero_dte_lottery_strategy_service),
) -> ZeroDteLotteryScanResult:
    try:
        return service.run_scan(
            external_account_id=external_account_id,
            symbol=symbol,
            direction=direction,
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

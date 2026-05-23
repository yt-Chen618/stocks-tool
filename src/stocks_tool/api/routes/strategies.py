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
    ExecuteBullPutSpreadRequest,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])


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

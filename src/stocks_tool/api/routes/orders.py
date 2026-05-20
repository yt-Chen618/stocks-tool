from fastapi import APIRouter, Depends, HTTPException

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import get_order_service
from stocks_tool.application.services.orders import OrderService
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    CreateOrderRequest,
    Order,
    OrderSyncResult,
    ReplaceOrderRequest,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[Order])
def list_orders(
    external_account_id: str | None = None,
    service: OrderService = Depends(get_order_service),
) -> list[Order]:
    return service.list_orders(external_account_id=external_account_id)


@router.get("/{order_id}", response_model=Order)
def get_order(
    order_id: str,
    service: OrderService = Depends(get_order_service),
) -> Order:
    order = service.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found.")
    return order


@router.post("/submit", response_model=Order, status_code=201)
def submit_order(
    request: CreateOrderRequest,
    service: OrderService = Depends(get_order_service),
) -> Order:
    try:
        return service.submit_order(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{order_id}/refresh", response_model=Order)
def refresh_order(
    order_id: str,
    service: OrderService = Depends(get_order_service),
) -> Order:
    try:
        return service.refresh_order(order_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{order_id}/cancel", response_model=Order)
def cancel_order(
    order_id: str,
    service: OrderService = Depends(get_order_service),
) -> Order:
    try:
        return service.cancel_order(order_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{order_id}/replace", response_model=Order)
def replace_order(
    order_id: str,
    request: ReplaceOrderRequest,
    service: OrderService = Depends(get_order_service),
) -> Order:
    try:
        return service.replace_order(order_id, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/sync/longbridge/{external_account_id}", response_model=OrderSyncResult)
def sync_longbridge_orders(
    external_account_id: str,
    mode: ExecutionMode = ExecutionMode.PAPER,
    symbol: str | None = None,
    service: OrderService = Depends(get_order_service),
) -> OrderSyncResult:
    try:
        return service.sync_today_orders(
            external_account_id=external_account_id,
            mode=mode,
            symbol=symbol,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

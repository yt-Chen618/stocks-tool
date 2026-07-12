from fastapi import APIRouter, Depends, HTTPException, Response

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import get_order_service
from stocks_tool.api.idempotency import require_idempotency_key
from stocks_tool.application.services.orders import (
    OrderService,
    TradingIntentConflictError,
    TradingIntentError,
    TradingIntentOutcomeUnknownError,
)
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    CreateOrderRequest,
    Order,
    OrderSyncResult,
    ReplaceOrderRequest,
)

router = APIRouter(prefix="/orders", tags=["orders"])


def _raise_intent_http_error(exc: TradingIntentError) -> None:
    if isinstance(exc, TradingIntentConflictError):
        code = "idempotency_conflict"
    elif isinstance(exc, TradingIntentOutcomeUnknownError):
        code = "order_outcome_unknown"
    else:
        code = "order_intent_rejected"
    raise HTTPException(
        status_code=409,
        detail={"code": code, "intent_id": exc.intent_id, "retryable": False},
    ) from exc


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
    response: Response,
    idempotency_key: str = Depends(require_idempotency_key),
    service: OrderService = Depends(get_order_service),
) -> Order:
    try:
        order = service.submit_order(request, idempotency_key=idempotency_key)
        if order.idempotent_replayed:
            response.headers["Idempotent-Replayed"] = "true"
        return order
    except TradingIntentError as exc:
        _raise_intent_http_error(exc)
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


@router.post("/{order_id}/cancel", response_model=Order)
def cancel_order(
    order_id: str,
    response: Response,
    idempotency_key: str = Depends(require_idempotency_key),
    service: OrderService = Depends(get_order_service),
) -> Order:
    try:
        order = service.cancel_order(order_id, idempotency_key=idempotency_key)
        if order.idempotent_replayed:
            response.headers["Idempotent-Replayed"] = "true"
        return order
    except TradingIntentError as exc:
        _raise_intent_http_error(exc)
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


@router.post("/{order_id}/replace", response_model=Order)
def replace_order(
    order_id: str,
    request: ReplaceOrderRequest,
    response: Response,
    idempotency_key: str = Depends(require_idempotency_key),
    service: OrderService = Depends(get_order_service),
) -> Order:
    try:
        order = service.replace_order(order_id, request, idempotency_key=idempotency_key)
        if order.idempotent_replayed:
            response.headers["Idempotent-Replayed"] = "true"
        return order
    except TradingIntentError as exc:
        _raise_intent_http_error(exc)
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

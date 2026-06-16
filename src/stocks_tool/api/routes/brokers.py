from fastapi import APIRouter, Depends, HTTPException, Query

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)
from stocks_tool.api.dependencies import (
    get_longbridge_adapter,
    get_longbridge_integration_service,
)
from stocks_tool.application.services.longbridge_integration import (
    LongbridgeIntegrationService,
)
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    BrokerAccountSyncResult,
    BrokerConfigurationStatus,
    BrokerProfile,
    SecurityQuoteSnapshot,
)
from stocks_tool.ports.broker_gateway import BrokerAccountGateway

router = APIRouter(prefix="/brokers", tags=["brokers"])


@router.get("/profiles", response_model=list[BrokerProfile])
def list_broker_profiles(
    adapter: BrokerAccountGateway = Depends(get_longbridge_adapter),
) -> list[BrokerProfile]:
    return [adapter.get_profile()]


@router.get("/longbridge/profile", response_model=BrokerProfile)
def get_longbridge_profile(
    adapter: BrokerAccountGateway = Depends(get_longbridge_adapter),
) -> BrokerProfile:
    return adapter.get_profile()


@router.get("/longbridge/configuration", response_model=BrokerConfigurationStatus)
def get_longbridge_configuration(
    adapter: BrokerAccountGateway = Depends(get_longbridge_adapter),
) -> BrokerConfigurationStatus:
    return adapter.get_configuration_status()


@router.get("/longbridge/quote", response_model=SecurityQuoteSnapshot)
def get_longbridge_quote(
    symbol: str = Query(..., description="Longbridge security symbol, e.g. AAPL.US"),
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    service: LongbridgeIntegrationService = Depends(get_longbridge_integration_service),
) -> SecurityQuoteSnapshot:
    try:
        return service.get_quote(symbol=symbol, mode=mode)
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post(
    "/longbridge/account-sync/{external_account_id}",
    response_model=BrokerAccountSyncResult,
)
def sync_longbridge_account(
    external_account_id: str,
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    currency: str | None = Query(
        default=None,
        description="Optional currency override. Defaults to the local broker account base currency.",
    ),
    service: LongbridgeIntegrationService = Depends(get_longbridge_integration_service),
) -> BrokerAccountSyncResult:
    try:
        return service.sync_account(
            external_account_id=external_account_id,
            mode=mode,
            currency=currency,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LongbridgeDependencyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LongbridgeConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LongbridgeIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

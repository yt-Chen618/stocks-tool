from fastapi import APIRouter, Depends

from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.api.dependencies import get_longbridge_adapter
from stocks_tool.domain.models import BrokerConfigurationStatus, BrokerProfile

router = APIRouter(prefix="/brokers", tags=["brokers"])


@router.get("/longbridge/profile", response_model=BrokerProfile)
def get_longbridge_profile(
    adapter: LongbridgeBrokerAdapter = Depends(get_longbridge_adapter),
) -> BrokerProfile:
    return adapter.get_profile()


@router.get("/longbridge/configuration", response_model=BrokerConfigurationStatus)
def get_longbridge_configuration(
    adapter: LongbridgeBrokerAdapter = Depends(get_longbridge_adapter),
) -> BrokerConfigurationStatus:
    return adapter.get_configuration_status()


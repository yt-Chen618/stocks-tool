from fastapi import APIRouter, Depends

from stocks_tool.api.dependencies import get_broker_account_repository
from stocks_tool.domain.models import BrokerAccount, CreateBrokerAccountRequest
from stocks_tool.ports.repository import BrokerAccountRepository

router = APIRouter(prefix="/broker-accounts", tags=["broker-accounts"])


@router.get("", response_model=list[BrokerAccount])
def list_broker_accounts(
    repository: BrokerAccountRepository = Depends(get_broker_account_repository),
) -> list[BrokerAccount]:
    return repository.list_broker_accounts()


@router.post("", response_model=BrokerAccount, status_code=201)
def create_broker_account(
    request: CreateBrokerAccountRequest,
    repository: BrokerAccountRepository = Depends(get_broker_account_repository),
) -> BrokerAccount:
    return repository.create_broker_account(request)


from fastapi import APIRouter, Depends

from stocks_tool.api.dependencies import get_execution_repository
from stocks_tool.domain.models import Execution
from stocks_tool.ports.repository import ExecutionRepository

router = APIRouter(prefix="/executions", tags=["executions"])


@router.get("", response_model=list[Execution])
def list_executions(
    external_account_id: str | None = None,
    order_id: str | None = None,
    repository: ExecutionRepository = Depends(get_execution_repository),
) -> list[Execution]:
    return repository.list_executions(
        external_account_id=external_account_id,
        order_id=order_id,
    )

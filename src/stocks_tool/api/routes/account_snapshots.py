from fastapi import APIRouter, Depends

from stocks_tool.api.dependencies import get_account_snapshot_repository
from stocks_tool.domain.models import AccountSnapshot
from stocks_tool.ports.repository import AccountSnapshotRepository

router = APIRouter(prefix="/account-snapshots", tags=["account-snapshots"])


@router.get("", response_model=list[AccountSnapshot])
def list_account_snapshots(
    external_account_id: str | None = None,
    repository: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
) -> list[AccountSnapshot]:
    return repository.list_account_snapshots(external_account_id=external_account_id)


@router.post("", response_model=AccountSnapshot, status_code=201)
def create_account_snapshot(
    snapshot: AccountSnapshot,
    repository: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
) -> AccountSnapshot:
    return repository.create_account_snapshot(snapshot)


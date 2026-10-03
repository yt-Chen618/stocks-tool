from fastapi import APIRouter, Depends, Query

from stocks_tool.api.dependencies import get_account_snapshot_repository
from stocks_tool.domain.enums import AccountSnapshotProvenance, ExecutionMode
from stocks_tool.domain.models import AccountSnapshot, AccountSnapshotSummary
from stocks_tool.ports.repository import AccountSnapshotRepository

router = APIRouter(prefix="/account-snapshots", tags=["account-snapshots"])


@router.get("/latest", response_model=AccountSnapshotSummary | None)
def get_latest_account_snapshot(
    external_account_id: str,
    mode: ExecutionMode = Query(default=ExecutionMode.PAPER),
    repository: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
) -> AccountSnapshotSummary | None:
    snapshot = repository.get_latest_account_snapshot(
        external_account_id=external_account_id,
        mode=mode,
        trusted_only=False,
    )
    if snapshot is None:
        return None
    return AccountSnapshotSummary.from_snapshot(snapshot)


@router.get("", response_model=list[AccountSnapshot])
def list_account_snapshots(
    external_account_id: str | None = None,
    mode: ExecutionMode | None = Query(default=None),
    repository: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
) -> list[AccountSnapshot]:
    return repository.list_account_snapshots(
        external_account_id=external_account_id,
        mode=mode,
    )


@router.post("", response_model=AccountSnapshot, status_code=201)
def create_account_snapshot(
    snapshot: AccountSnapshot,
    repository: AccountSnapshotRepository = Depends(get_account_snapshot_repository),
) -> AccountSnapshot:
    # New public uploads follow the paper-first API default. Historical rows
    # retain their unknown mode; an explicit null still records unknown mode.
    # Provenance remains untrusted regardless of the caller's mode declaration.
    if "mode" not in snapshot.model_fields_set:
        snapshot = snapshot.model_copy(update={"mode": ExecutionMode.PAPER})
    return repository.create_account_snapshot(
        snapshot,
        provenance=AccountSnapshotProvenance.PUBLIC_UPLOAD,
    )

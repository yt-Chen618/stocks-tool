from datetime import datetime, timezone

from stocks_tool.domain.enums import BrokerName, ExecutionMode, ReconciliationStatus
from stocks_tool.domain.models import BrokerAccountSyncResult, SecurityQuoteSnapshot
from stocks_tool.ports.broker_gateway import BrokerIntegrationGateway
from stocks_tool.ports.repository import AccountSnapshotRepository, BrokerAccountRepository


class LongbridgeIntegrationService:
    def __init__(
        self,
        adapter: BrokerIntegrationGateway,
        broker_accounts: BrokerAccountRepository,
        account_snapshots: AccountSnapshotRepository,
    ) -> None:
        self.adapter = adapter
        self.broker_accounts = broker_accounts
        self.account_snapshots = account_snapshots

    def get_quote(
        self,
        symbol: str,
        mode: ExecutionMode,
    ) -> SecurityQuoteSnapshot:
        return self.adapter.get_quote(symbol=symbol, mode=mode)

    def sync_account(
        self,
        external_account_id: str,
        mode: ExecutionMode,
        currency: str | None = None,
    ) -> BrokerAccountSyncResult:
        broker_account = self.broker_accounts.get_by_external_account_id(external_account_id)
        if broker_account is None or broker_account.broker != BrokerName.LONGBRIDGE:
            raise LookupError(
                f"No local Longbridge broker account was found for '{external_account_id}'."
            )

        attempted_at = datetime.now(timezone.utc)
        self.broker_accounts.update_account_sync_state(
            external_account_id,
            status=ReconciliationStatus.SYNCING,
            attempted_at=attempted_at,
            error=None,
        )

        try:
            snapshot = self.adapter.build_account_snapshot(
                external_account_id=external_account_id,
                mode=mode,
                currency=currency or broker_account.base_currency,
                options_level=broker_account.options_level,
            )
            persisted_snapshot = self.account_snapshots.create_account_snapshot(snapshot)
            self.broker_accounts.update_account_sync_state(
                external_account_id,
                status=ReconciliationStatus.SUCCESS,
                attempted_at=attempted_at,
                synced_at=persisted_snapshot.captured_at,
                error=None,
            )
            return BrokerAccountSyncResult(
                broker=BrokerName.LONGBRIDGE,
                mode=mode,
                external_account_id=external_account_id,
                snapshot_id=persisted_snapshot.id,
                positions_synced=len(persisted_snapshot.positions),
                account_snapshot=persisted_snapshot,
            )
        except Exception as exc:
            self.broker_accounts.update_account_sync_state(
                external_account_id,
                status=ReconciliationStatus.ERROR,
                attempted_at=attempted_at,
                error=str(exc),
            )
            raise

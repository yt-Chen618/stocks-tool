from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord
from stocks_tool.domain.enums import BrokerName, ReconciliationStatus
from stocks_tool.domain.models import BrokerAccount, CreateBrokerAccountRequest
from stocks_tool.ports.repository import BrokerAccountRepository


class SQLAlchemyBrokerAccountRepository(BrokerAccountRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_broker_account(self, request: CreateBrokerAccountRequest) -> BrokerAccount:
        record = BrokerAccountRecord(
            broker=request.broker.value,
            external_account_id=request.external_account_id,
            display_name=request.display_name,
            base_currency=request.base_currency,
            options_level=request.options_level,
            is_active=request.is_active,
            auto_reconcile_enabled=request.auto_reconcile_enabled,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def list_broker_accounts(self) -> list[BrokerAccount]:
        query = select(BrokerAccountRecord).order_by(BrokerAccountRecord.created_at.desc())
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

    def get_by_external_account_id(
        self,
        external_account_id: str,
    ) -> BrokerAccount | None:
        query = select(BrokerAccountRecord).where(
            BrokerAccountRecord.external_account_id == external_account_id
        )
        record = self.session.execute(query).scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    def update_account_sync_state(
        self,
        external_account_id: str,
        *,
        status: ReconciliationStatus,
        attempted_at: datetime | None = None,
        synced_at: datetime | None = None,
        error: str | None = None,
    ) -> BrokerAccount:
        record = self._get_record_or_raise(external_account_id)
        record.account_sync_status = status.value
        if attempted_at is not None:
            record.account_last_sync_attempt_at = attempted_at
        if synced_at is not None:
            record.account_last_synced_at = synced_at
        record.account_last_sync_error = error
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def update_orders_sync_state(
        self,
        external_account_id: str,
        *,
        status: ReconciliationStatus,
        attempted_at: datetime | None = None,
        synced_at: datetime | None = None,
        error: str | None = None,
    ) -> BrokerAccount:
        record = self._get_record_or_raise(external_account_id)
        record.orders_sync_status = status.value
        if attempted_at is not None:
            record.orders_last_sync_attempt_at = attempted_at
        if synced_at is not None:
            record.orders_last_synced_at = synced_at
        record.orders_last_sync_error = error
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def _get_record_or_raise(self, external_account_id: str) -> BrokerAccountRecord:
        query = select(BrokerAccountRecord).where(
            BrokerAccountRecord.external_account_id == external_account_id
        )
        record = self.session.execute(query).scalar_one_or_none()
        if record is None:
            raise ValueError(f"Broker account '{external_account_id}' was not found.")
        return record

    @staticmethod
    def _to_domain(record: BrokerAccountRecord) -> BrokerAccount:
        return BrokerAccount(
            id=record.id,
            broker=BrokerName(record.broker),
            external_account_id=record.external_account_id,
            display_name=record.display_name,
            base_currency=record.base_currency,
            options_level=record.options_level,
            is_active=record.is_active,
            auto_reconcile_enabled=record.auto_reconcile_enabled,
            account_sync_status=ReconciliationStatus(record.account_sync_status),
            account_last_sync_attempt_at=record.account_last_sync_attempt_at,
            account_last_synced_at=record.account_last_synced_at,
            account_last_sync_error=record.account_last_sync_error,
            orders_sync_status=ReconciliationStatus(record.orders_sync_status),
            orders_last_sync_attempt_at=record.orders_last_sync_attempt_at,
            orders_last_synced_at=record.orders_last_synced_at,
            orders_last_sync_error=record.orders_last_sync_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

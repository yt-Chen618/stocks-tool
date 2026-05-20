from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord
from stocks_tool.domain.enums import BrokerName
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
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


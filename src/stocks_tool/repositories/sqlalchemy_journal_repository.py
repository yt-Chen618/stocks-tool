from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import JournalEntryRecord
from stocks_tool.domain.enums import JournalEntryType
from stocks_tool.domain.models import JournalEntry
from stocks_tool.ports.repository import JournalRepository


class SQLAlchemyJournalRepository(JournalRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_entry(self, entry: JournalEntry) -> JournalEntry:
        record = JournalEntryRecord(id=entry.id)
        self.session.add(record)
        self._apply_entry(record, entry)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def list_entries(
        self,
        external_account_id: str | None = None,
        order_id: str | None = None,
        trade_plan_id: str | None = None,
        entry_type: JournalEntryType | None = None,
    ) -> list[JournalEntry]:
        query = select(JournalEntryRecord).order_by(
            JournalEntryRecord.updated_at.desc(),
            JournalEntryRecord.created_at.desc(),
        )
        if external_account_id is not None:
            query = query.where(JournalEntryRecord.external_account_id == external_account_id)
        if order_id is not None:
            query = query.where(JournalEntryRecord.order_id == order_id)
        if trade_plan_id is not None:
            query = query.where(JournalEntryRecord.trade_plan_id == trade_plan_id)
        if entry_type is not None:
            query = query.where(JournalEntryRecord.entry_type == entry_type.value)
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _apply_entry(record: JournalEntryRecord, entry: JournalEntry) -> None:
        record.trade_plan_id = entry.trade_plan_id
        record.order_id = entry.order_id
        record.execution_id = entry.execution_id
        record.external_account_id = entry.external_account_id
        record.symbol = entry.symbol
        record.entry_type = entry.entry_type.value
        record.title = entry.title
        record.notes = entry.notes
        record.tags = entry.tags or None

    @staticmethod
    def _to_domain(record: JournalEntryRecord) -> JournalEntry:
        return JournalEntry(
            id=record.id,
            external_account_id=record.external_account_id,
            symbol=record.symbol,
            entry_type=JournalEntryType(record.entry_type),
            title=record.title,
            notes=record.notes,
            order_id=record.order_id,
            trade_plan_id=record.trade_plan_id,
            execution_id=record.execution_id,
            tags=list(record.tags or []),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

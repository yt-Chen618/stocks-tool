from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from stocks_tool.db.models import ExecutionRecord
from stocks_tool.domain.enums import BrokerName, OrderSide
from stocks_tool.domain.models import Execution
from stocks_tool.ports.repository import ExecutionRepository


class SQLAlchemyExecutionRepository(ExecutionRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_external_execution_id(self, external_execution_id: str) -> Execution | None:
        record = self.session.execute(
            select(ExecutionRecord)
            .options(selectinload(ExecutionRecord.order))
            .where(ExecutionRecord.external_execution_id == external_execution_id)
        ).scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    def list_executions(
        self,
        external_account_id: str | None = None,
        order_id: str | None = None,
    ) -> list[Execution]:
        query = (
            select(ExecutionRecord)
            .options(selectinload(ExecutionRecord.order))
            .order_by(ExecutionRecord.executed_at.desc(), ExecutionRecord.created_at.desc())
        )
        if external_account_id is not None:
            query = query.where(ExecutionRecord.external_account_id == external_account_id)
        if order_id is not None:
            query = query.where(ExecutionRecord.order_id == order_id)
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

    def upsert_execution(self, execution: Execution) -> Execution:
        record = None
        if execution.external_execution_id is not None:
            record = self.session.execute(
                select(ExecutionRecord).where(
                    ExecutionRecord.external_execution_id == execution.external_execution_id
                )
            ).scalar_one_or_none()
        if record is None:
            record = self.session.get(ExecutionRecord, execution.id)

        if record is None:
            record = ExecutionRecord(id=execution.id or str(uuid4()))
            self.session.add(record)

        self._apply_execution(record, execution)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    @staticmethod
    def _apply_execution(record: ExecutionRecord, execution: Execution) -> None:
        record.order_id = execution.order_id
        record.broker = execution.broker.value
        record.external_account_id = execution.external_account_id
        record.external_order_id = execution.external_order_id
        record.external_execution_id = execution.external_execution_id
        record.symbol = execution.symbol
        record.side = execution.side.value
        record.quantity = execution.quantity
        record.price = execution.price
        record.executed_at = execution.executed_at
        record.raw_payload = execution.raw_payload

    @staticmethod
    def _to_domain(record: ExecutionRecord) -> Execution:
        return Execution(
            id=record.id,
            order_id=record.order_id,
            broker=BrokerName(record.broker),
            external_account_id=record.external_account_id,
            external_order_id=record.external_order_id,
            external_execution_id=record.external_execution_id,
            symbol=record.symbol,
            side=OrderSide(record.side),
            quantity=record.quantity,
            price=Decimal(record.price) if record.price is not None else None,
            executed_at=record.executed_at,
            raw_payload=record.raw_payload,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

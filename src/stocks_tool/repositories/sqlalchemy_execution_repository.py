from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session, selectinload

from stocks_tool.db.models import ExecutionRecord
from stocks_tool.domain.enums import BrokerName, OrderSide
from stocks_tool.domain.models import Execution
from stocks_tool.domain.pagination import (
    CursorPage,
    decode_cursor,
    encode_cursor,
    normalize_page_limit,
)
from stocks_tool.ports.repository import ExecutionRepository


class SQLAlchemyExecutionRepository(ExecutionRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_execution(self, execution_id: str) -> Execution | None:
        record = self.session.execute(
            select(ExecutionRecord)
            .options(selectinload(ExecutionRecord.order))
            .where(ExecutionRecord.id == execution_id)
        ).scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

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
            .order_by(
                ExecutionRecord.executed_at.desc(),
                ExecutionRecord.created_at.desc(),
                ExecutionRecord.id.desc(),
            )
        )
        if external_account_id is not None:
            query = query.where(ExecutionRecord.external_account_id == external_account_id)
        if order_id is not None:
            query = query.where(ExecutionRecord.order_id == order_id)
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

    def list_executions_page(
        self,
        *,
        external_account_id: str | None = None,
        order_id: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> CursorPage[Execution]:
        page_limit = normalize_page_limit(limit)
        scope = {
            "external_account_id": external_account_id,
            "order_id": order_id,
        }
        query = select(ExecutionRecord.id).order_by(
            ExecutionRecord.created_at.desc(),
            ExecutionRecord.id.desc(),
        )
        if external_account_id is not None:
            query = query.where(ExecutionRecord.external_account_id == external_account_id)
        if order_id is not None:
            query = query.where(ExecutionRecord.order_id == order_id)
        if cursor is not None:
            position = decode_cursor(cursor, resource="executions", scope=scope)
            try:
                created_at = datetime.fromisoformat(str(position["created_at"]))
                execution_id = str(position["id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid pagination cursor position.") from exc
            query = query.where(
                tuple_(ExecutionRecord.created_at, ExecutionRecord.id) < (created_at, execution_id)
            )
        record_ids = self.session.execute(query.limit(page_limit + 1)).scalars().all()
        has_more = len(record_ids) > page_limit
        record_ids = record_ids[:page_limit]
        if record_ids:
            record_by_id = {
                record.id: record
                for record in self.session.execute(
                    select(ExecutionRecord).where(ExecutionRecord.id.in_(record_ids))
                ).scalars().all()
            }
            records = [record_by_id[record_id] for record_id in record_ids]
        else:
            records = []
        items = [self._to_domain(record) for record in records]
        next_cursor = None
        if has_more and records:
            last = records[-1]
            next_cursor = encode_cursor(
                resource="executions",
                scope=scope,
                position={
                    "created_at": last.created_at.isoformat(),
                    "id": last.id,
                },
            )
        return CursorPage(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            limit=page_limit,
        )

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

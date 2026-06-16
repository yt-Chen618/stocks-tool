from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord, StrategyAuditEventRecord
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import CreateStrategyAuditEventRequest, StrategyAuditEvent
from stocks_tool.ports.repository import StrategyAuditEventRepository


class SQLAlchemyStrategyAuditEventRepository(StrategyAuditEventRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_event(self, request: CreateStrategyAuditEventRequest) -> StrategyAuditEvent:
        record = StrategyAuditEventRecord(id=request.id or str(uuid4()))
        self.session.add(record)
        self._apply_request(record, request)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def list_events(
        self,
        *,
        external_account_id: str | None = None,
        mode: str | ExecutionMode | None = None,
        source: str | None = None,
        strategy: str | None = None,
        action: str | None = None,
        warning_only: bool = False,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[StrategyAuditEvent]:
        query = (
            select(StrategyAuditEventRecord)
            .order_by(StrategyAuditEventRecord.emitted_at.desc(), StrategyAuditEventRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(StrategyAuditEventRecord.external_account_id == external_account_id)
        if mode is not None:
            query = query.where(StrategyAuditEventRecord.execution_mode == self._mode_value(mode))
        if source is not None:
            query = query.where(StrategyAuditEventRecord.source == source)
        if strategy is not None:
            query = query.where(StrategyAuditEventRecord.strategy == strategy)
        if action is not None:
            query = query.where(StrategyAuditEventRecord.action == action)
        if warning_only:
            query = query.where(StrategyAuditEventRecord.warning_code.is_not(None))
        if since is not None:
            query = query.where(StrategyAuditEventRecord.emitted_at >= since)
        return [self._to_domain(record) for record in self.session.execute(query).scalars().all()]

    def _apply_request(self, record: StrategyAuditEventRecord, request: CreateStrategyAuditEventRequest) -> None:
        record.broker_account_id = self._resolve_broker_account_id(request.external_account_id)
        record.external_account_id = request.external_account_id
        record.execution_mode = self._mode_value(request.mode)
        record.actor = request.actor
        record.source = request.source
        record.strategy = request.strategy
        record.action = request.action
        record.before_payload = request.before
        record.after_payload = request.after
        record.order_ids = request.order_ids
        record.proposal_id = request.proposal_id
        record.run_id = request.run_id
        record.warning_code = request.warning_code
        record.summary = request.summary
        record.detail = request.detail
        record.payload = request.payload
        record.event_origin = request.event_origin or "durable"
        record.emitted_at = request.emitted_at or datetime.now(timezone.utc)

    def _resolve_broker_account_id(self, external_account_id: str | None) -> str | None:
        if external_account_id is None:
            return None
        broker_account = self.session.execute(
            select(BrokerAccountRecord).where(BrokerAccountRecord.external_account_id == external_account_id)
        ).scalar_one_or_none()
        return broker_account.id if broker_account is not None else None

    @staticmethod
    def _mode_value(mode: str | ExecutionMode | None) -> str | None:
        if mode is None:
            return None
        if isinstance(mode, ExecutionMode):
            return mode.value
        return str(mode)

    @staticmethod
    def _to_domain(record: StrategyAuditEventRecord) -> StrategyAuditEvent:
        return StrategyAuditEvent(
            id=record.id,
            emitted_at=record.emitted_at,
            external_account_id=record.external_account_id,
            mode=ExecutionMode(record.execution_mode) if record.execution_mode else None,
            actor=record.actor,
            source=record.source,
            strategy=record.strategy,
            action=record.action,
            before=record.before_payload,
            after=record.after_payload,
            order_ids=record.order_ids or [],
            proposal_id=record.proposal_id,
            run_id=record.run_id,
            warning_code=record.warning_code,
            summary=record.summary,
            detail=record.detail,
            payload=record.payload or {},
            event_origin=record.event_origin or "durable",
        )

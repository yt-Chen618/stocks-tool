from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord, SchedulerJobRunRecord
from stocks_tool.domain.enums import SchedulerJobRunStatus
from stocks_tool.domain.models import SchedulerJobRun
from stocks_tool.ports.repository import SchedulerJobRunRepository


class SQLAlchemySchedulerJobRunRepository(SchedulerJobRunRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(self, run: SchedulerJobRun) -> SchedulerJobRun:
        record = SchedulerJobRunRecord(id=run.id)
        self.session.add(record)
        self._apply_run(record, run)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def list_runs(
        self,
        *,
        external_account_id: str | None = None,
        job_key: str | None = None,
        limit: int = 50,
    ) -> list[SchedulerJobRun]:
        query = (
            select(SchedulerJobRunRecord)
            .order_by(SchedulerJobRunRecord.started_at.desc(), SchedulerJobRunRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(SchedulerJobRunRecord.external_account_id == external_account_id)
        if job_key is not None:
            query = query.where(SchedulerJobRunRecord.job_key == job_key)
        return [self._to_domain(record) for record in self.session.execute(query).scalars().all()]

    @staticmethod
    def _resolve_broker_account_id(session: Session, external_account_id: str | None) -> str | None:
        if external_account_id is None:
            return None
        broker_account = session.execute(
            select(BrokerAccountRecord).where(BrokerAccountRecord.external_account_id == external_account_id)
        ).scalar_one_or_none()
        return broker_account.id if broker_account is not None else None

    def _apply_run(self, record: SchedulerJobRunRecord, run: SchedulerJobRun) -> None:
        record.broker_account_id = self._resolve_broker_account_id(self.session, run.external_account_id)
        record.external_account_id = run.external_account_id
        record.job_key = run.job_key
        record.job_label = run.job_label
        record.status = run.status.value
        record.started_at = run.started_at
        record.completed_at = run.completed_at
        record.duration_ms = run.duration_ms
        record.next_attempt_at = run.next_attempt_at
        record.backoff_seconds = run.backoff_seconds
        record.consecutive_failures = run.consecutive_failures
        record.error_message = run.error_message
        record.detail = run.detail
        record.raw_payload = run.raw_payload

    @staticmethod
    def _to_domain(record: SchedulerJobRunRecord) -> SchedulerJobRun:
        return SchedulerJobRun(
            id=record.id,
            job_key=record.job_key,
            job_label=record.job_label,
            external_account_id=record.external_account_id,
            status=SchedulerJobRunStatus(record.status),
            started_at=record.started_at,
            completed_at=record.completed_at,
            duration_ms=record.duration_ms,
            next_attempt_at=record.next_attempt_at,
            backoff_seconds=record.backoff_seconds,
            consecutive_failures=record.consecutive_failures,
            error_message=record.error_message,
            detail=record.detail,
            raw_payload=record.raw_payload,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord, SchedulerJobRunRecord, SchedulerTaskStateRecord
from stocks_tool.domain.enums import SchedulerJobRunStatus
from stocks_tool.domain.models import SchedulerJobRun, SchedulerTaskState
from stocks_tool.ports.repository import SchedulerJobRunRepository, SchedulerTaskStateRepository


class SQLAlchemySchedulerJobRunRepository(SchedulerJobRunRepository, SchedulerTaskStateRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(self, run: SchedulerJobRun, *, update_task_state: bool = True) -> SchedulerJobRun:
        record = SchedulerJobRunRecord(id=run.id)
        self.session.add(record)
        self._apply_run(record, run)
        if update_task_state:
            self._upsert_state_from_run(run)
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

    def get_state(
        self,
        *,
        external_account_id: str | None,
        job_key: str,
    ) -> SchedulerTaskState | None:
        record = self._get_state_record(external_account_id=external_account_id, job_key=job_key)
        return self._state_to_domain(record) if record is not None else None

    def list_states(
        self,
        *,
        external_account_id: str | None = None,
        job_key: str | None = None,
        limit: int = 100,
    ) -> list[SchedulerTaskState]:
        query = (
            select(SchedulerTaskStateRecord)
            .order_by(SchedulerTaskStateRecord.updated_at.desc(), SchedulerTaskStateRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(SchedulerTaskStateRecord.external_account_id == external_account_id)
        if job_key is not None:
            query = query.where(SchedulerTaskStateRecord.job_key == job_key)
        return [self._state_to_domain(record) for record in self.session.execute(query).scalars().all()]

    def try_acquire_lease(
        self,
        *,
        external_account_id: str | None,
        job_key: str,
        job_label: str | None,
        lease_owner: str,
        lease_expires_at: datetime,
        now: datetime,
    ) -> SchedulerTaskState:
        record = self._get_state_record(external_account_id=external_account_id, job_key=job_key, for_update=True)
        if record is None:
            record = SchedulerTaskStateRecord(
                broker_account_id=self._resolve_broker_account_id(self.session, external_account_id),
                external_account_id=external_account_id,
                job_key=job_key,
            )
            self.session.add(record)
        if (
            record.lease_owner
            and record.lease_owner != lease_owner
            and record.lease_expires_at is not None
            and record.lease_expires_at > now
        ):
            self.session.commit()
            return self._state_to_domain(record)
        record.job_label = job_label or record.job_label
        record.lease_owner = lease_owner
        record.lease_acquired_at = now
        record.lease_expires_at = lease_expires_at
        record.updated_at = now
        self.session.commit()
        self.session.refresh(record)
        return self._state_to_domain(record)

    def release_lease(
        self,
        *,
        external_account_id: str | None,
        job_key: str,
        lease_owner: str,
    ) -> SchedulerTaskState | None:
        record = self._get_state_record(external_account_id=external_account_id, job_key=job_key, for_update=True)
        if record is None:
            return None
        if record.lease_owner == lease_owner:
            record.lease_owner = None
            record.lease_acquired_at = None
            record.lease_expires_at = None
            record.updated_at = datetime.now(timezone.utc)
            self.session.commit()
            self.session.refresh(record)
        return self._state_to_domain(record)

    def upsert_from_run(self, run: SchedulerJobRun) -> SchedulerTaskState:
        state = self._upsert_state_from_run(run)
        self.session.commit()
        self.session.refresh(state)
        return self._state_to_domain(state)

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

    def _get_state_record(
        self,
        *,
        external_account_id: str | None,
        job_key: str,
        for_update: bool = False,
    ) -> SchedulerTaskStateRecord | None:
        query = select(SchedulerTaskStateRecord).where(
            SchedulerTaskStateRecord.external_account_id == external_account_id,
            SchedulerTaskStateRecord.job_key == job_key,
        )
        if for_update:
            query = query.with_for_update()
        return self.session.execute(query).scalar_one_or_none()

    def _upsert_state_from_run(self, run: SchedulerJobRun) -> SchedulerTaskStateRecord:
        record = self._get_state_record(
            external_account_id=run.external_account_id,
            job_key=run.job_key,
            for_update=True,
        )
        if record is None:
            record = SchedulerTaskStateRecord(id=run.id)
            self.session.add(record)
        record.broker_account_id = self._resolve_broker_account_id(self.session, run.external_account_id)
        record.external_account_id = run.external_account_id
        record.job_key = run.job_key
        record.job_label = run.job_label
        record.last_run_id = run.id
        record.last_status = run.status.value
        record.last_started_at = run.started_at
        record.last_completed_at = run.completed_at
        record.next_attempt_at = run.next_attempt_at
        record.backoff_seconds = run.backoff_seconds
        record.consecutive_failures = run.consecutive_failures
        record.error_message = run.error_message
        record.detail = run.detail
        record.updated_at = datetime.now(timezone.utc)
        return record

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

    @staticmethod
    def _state_to_domain(record: SchedulerTaskStateRecord) -> SchedulerTaskState:
        return SchedulerTaskState(
            id=record.id,
            job_key=record.job_key,
            job_label=record.job_label,
            external_account_id=record.external_account_id,
            last_run_id=record.last_run_id,
            last_status=SchedulerJobRunStatus(record.last_status) if record.last_status else None,
            last_started_at=record.last_started_at,
            last_completed_at=record.last_completed_at,
            next_attempt_at=record.next_attempt_at,
            backoff_seconds=record.backoff_seconds,
            consecutive_failures=record.consecutive_failures,
            error_message=record.error_message,
            detail=record.detail,
            lease_owner=record.lease_owner,
            lease_acquired_at=record.lease_acquired_at,
            lease_expires_at=record.lease_expires_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

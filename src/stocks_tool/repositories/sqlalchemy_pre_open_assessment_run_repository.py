from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord, PreOpenAssessmentRunRecord
from stocks_tool.domain.models import (
    PreOpenAssessmentRun,
)
from stocks_tool.ports.repository import PreOpenAssessmentRunRepository


class SQLAlchemyPreOpenAssessmentRunRepository(PreOpenAssessmentRunRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_run(self, run_id: str) -> PreOpenAssessmentRun | None:
        record = self.session.get(PreOpenAssessmentRunRecord, run_id)
        if record is None:
            return None
        return self._to_domain(record)

    def get_by_session_date(
        self,
        *,
        external_account_id: str,
        target_session_date,
        strategy_id: str = "pre_open_put_check_v1",
    ) -> PreOpenAssessmentRun | None:
        record = self.session.execute(
            select(PreOpenAssessmentRunRecord).where(
                PreOpenAssessmentRunRecord.external_account_id == external_account_id,
                PreOpenAssessmentRunRecord.strategy_id == strategy_id,
                PreOpenAssessmentRunRecord.target_session_date == target_session_date,
            )
        ).scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    def list_runs(
        self,
        *,
        external_account_id: str | None = None,
        limit: int = 20,
    ) -> list[PreOpenAssessmentRun]:
        query = (
            select(PreOpenAssessmentRunRecord)
            .order_by(
                PreOpenAssessmentRunRecord.target_session_date.desc(),
                PreOpenAssessmentRunRecord.created_at.desc(),
            )
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(PreOpenAssessmentRunRecord.external_account_id == external_account_id)
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

    def upsert_run(
        self,
        run: PreOpenAssessmentRun,
    ) -> PreOpenAssessmentRun:
        record = self.session.get(PreOpenAssessmentRunRecord, run.id)
        if record is None:
            record = self.session.execute(
                select(PreOpenAssessmentRunRecord).where(
                    PreOpenAssessmentRunRecord.external_account_id == run.external_account_id,
                    PreOpenAssessmentRunRecord.strategy_id == run.strategy_id,
                    PreOpenAssessmentRunRecord.target_session_date == run.target_session_date,
                )
            ).scalar_one_or_none()
        if record is None:
            record = PreOpenAssessmentRunRecord(id=run.id)
            self.session.add(record)
        self._apply_run(record, run)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    @staticmethod
    def _resolve_broker_account_id(session: Session, run: PreOpenAssessmentRun) -> str | None:
        broker_account = session.execute(
            select(BrokerAccountRecord).where(
                BrokerAccountRecord.external_account_id == run.external_account_id,
            )
        ).scalar_one_or_none()
        return broker_account.id if broker_account is not None else None

    def _apply_run(self, record: PreOpenAssessmentRunRecord, run: PreOpenAssessmentRun) -> None:
        record.broker_account_id = self._resolve_broker_account_id(self.session, run)
        record.strategy_id = run.strategy_id
        record.external_account_id = run.external_account_id
        record.target_session_date = run.target_session_date
        record.assessment_payload = run.assessment.model_dump(mode="json")
        record.checkpoints_payload = [checkpoint.model_dump(mode="json") for checkpoint in run.checkpoints]
        record.review_status = run.review_status
        record.review_summary = run.review_summary
        record.last_reviewed_at = run.last_reviewed_at
        record.review_completed_at = run.review_completed_at
        record.raw_payload = run.raw_payload

    @staticmethod
    def _to_domain(record: PreOpenAssessmentRunRecord) -> PreOpenAssessmentRun:
        payload = dict(record.assessment_payload or {})
        payload.setdefault("chain_analyses", [])
        payload.setdefault("put_snapshots", [])
        payload.setdefault("signals", [])
        payload.setdefault("reasons", [])
        payload.setdefault("checkpoints", [])
        checkpoints_payload = list(record.checkpoints_payload or [])
        return PreOpenAssessmentRun.model_validate(
            {
                "id": record.id,
                "strategy_id": record.strategy_id,
                "external_account_id": record.external_account_id,
                "target_session_date": record.target_session_date,
                "assessment": payload,
                "checkpoints": checkpoints_payload,
                "review_status": record.review_status,
                "review_summary": record.review_summary,
                "last_reviewed_at": record.last_reviewed_at,
                "review_completed_at": record.review_completed_at,
                "raw_payload": record.raw_payload,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

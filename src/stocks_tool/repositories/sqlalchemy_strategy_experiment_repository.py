from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import (
    BrokerAccountRecord,
    StrategyAdvisorRunRecord,
    StrategyProposalRecord,
    StrategyReviewRecord,
    StrategyRunRecord,
    StrategySignalRecord,
)
from stocks_tool.domain.enums import (
    StrategyProposalStatus,
    StrategyAdvisorRunStatus,
    StrategyReviewStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    CreateStrategyProposalRequest,
    CreateStrategyAdvisorRunRequest,
    CreateStrategyReviewRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    StrategyProposal,
    StrategyAdvisorRun,
    StrategyReview,
    StrategyRun,
    StrategySignal,
)
from stocks_tool.ports.repository import StrategyExperimentRepository


class SQLAlchemyStrategyExperimentRepository(StrategyExperimentRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_proposal(self, request: CreateStrategyProposalRequest) -> StrategyProposal:
        proposal = StrategyProposal(
            strategy_id=request.strategy_id.strip(),
            external_account_id=request.external_account_id.strip(),
            mode=request.mode,
            symbol=request.symbol.strip().upper() if request.symbol else None,
            title=request.title.strip(),
            proposed_action=request.proposed_action.strip(),
            thesis=request.thesis.strip() if request.thesis else None,
            rationale=request.rationale.strip(),
            confidence=request.confidence,
            expected_max_loss=request.expected_max_loss,
            expected_max_profit=request.expected_max_profit,
            approval_required=request.approval_required,
            expires_at=request.expires_at,
            source=request.source.strip() if request.source else None,
            source_run_id=request.source_run_id,
            candidate_payload=request.candidate_payload,
            risk_payload=request.risk_payload,
            checks=[check.strip() for check in request.checks if check.strip()],
        )
        record = StrategyProposalRecord(id=proposal.id)
        self.session.add(record)
        self._apply_proposal(record, proposal)
        self.session.commit()
        self.session.refresh(record)
        return self._to_proposal(record)

    def get_proposal(self, proposal_id: str) -> StrategyProposal | None:
        record = self.session.get(StrategyProposalRecord, proposal_id)
        if record is None:
            return None
        return self._to_proposal(record)

    def update_proposal_status(
        self,
        proposal_id: str,
        *,
        status: StrategyProposalStatus,
        approved_at: datetime | None = None,
        rejected_at: datetime | None = None,
    ) -> StrategyProposal:
        record = self.session.get(StrategyProposalRecord, proposal_id)
        if record is None:
            raise LookupError(f"Strategy proposal '{proposal_id}' was not found.")
        record.status = status.value
        if approved_at is not None:
            record.approved_at = approved_at
            record.rejected_at = None
        if rejected_at is not None:
            record.rejected_at = rejected_at
            record.approved_at = None
        self.session.commit()
        self.session.refresh(record)
        return self._to_proposal(record)

    def list_proposals(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        status: StrategyProposalStatus | None = None,
        limit: int = 20,
    ) -> list[StrategyProposal]:
        query = (
            select(StrategyProposalRecord)
            .order_by(StrategyProposalRecord.updated_at.desc(), StrategyProposalRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(StrategyProposalRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategyProposalRecord.strategy_id == strategy_id)
        if status is not None:
            query = query.where(StrategyProposalRecord.status == status.value)
        return [self._to_proposal(record) for record in self.session.execute(query).scalars().all()]

    def create_run(self, request: CreateStrategyRunRequest) -> StrategyRun:
        run = StrategyRun(
            strategy_id=request.strategy_id.strip(),
            external_account_id=request.external_account_id.strip(),
            mode=request.mode,
            run_type=request.run_type.strip(),
            status=request.status,
            symbol=request.symbol.strip().upper() if request.symbol else None,
            proposal_id=request.proposal_id,
            trade_plan_id=request.trade_plan_id,
            order_id=request.order_id,
            spread_id=request.spread_id,
            started_at=request.started_at,
            completed_at=request.completed_at,
            summary=request.summary.strip() if request.summary else None,
            reason=request.reason.strip() if request.reason else None,
            metrics_payload=request.metrics_payload,
            raw_payload=request.raw_payload,
        )
        record = StrategyRunRecord(id=run.id)
        self.session.add(record)
        self._apply_run(record, run)
        self.session.commit()
        self.session.refresh(record)
        return self._to_run(record)

    def list_runs(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategyRun]:
        query = (
            select(StrategyRunRecord)
            .order_by(StrategyRunRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(StrategyRunRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategyRunRecord.strategy_id == strategy_id)
        return [self._to_run(record) for record in self.session.execute(query).scalars().all()]

    def create_signal(self, request: CreateStrategySignalRequest) -> StrategySignal:
        signal = StrategySignal(
            strategy_id=request.strategy_id.strip(),
            external_account_id=request.external_account_id.strip(),
            mode=request.mode,
            signal_type=request.signal_type,
            symbol=request.symbol.strip().upper() if request.symbol else None,
            run_id=request.run_id,
            proposal_id=request.proposal_id,
            strength=request.strength,
            summary=request.summary.strip(),
            detail=request.detail.strip() if request.detail else None,
            source=request.source.strip() if request.source else None,
            signal_payload=request.signal_payload,
            emitted_at=request.emitted_at or datetime.now(timezone.utc),
        )
        record = StrategySignalRecord(id=signal.id)
        self.session.add(record)
        self._apply_signal(record, signal)
        self.session.commit()
        self.session.refresh(record)
        return self._to_signal(record)

    def list_signals(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategySignal]:
        query = (
            select(StrategySignalRecord)
            .order_by(StrategySignalRecord.emitted_at.desc(), StrategySignalRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(StrategySignalRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategySignalRecord.strategy_id == strategy_id)
        return [self._to_signal(record) for record in self.session.execute(query).scalars().all()]

    def create_review(self, request: CreateStrategyReviewRequest) -> StrategyReview:
        review = StrategyReview(
            strategy_id=request.strategy_id.strip(),
            external_account_id=request.external_account_id.strip(),
            mode=request.mode,
            review_type=request.review_type.strip(),
            status=request.status,
            summary=request.summary.strip(),
            recommendation=request.recommendation.strip() if request.recommendation else None,
            parameter_name=request.parameter_name.strip() if request.parameter_name else None,
            current_value=request.current_value.strip() if request.current_value else None,
            suggested_value=request.suggested_value.strip() if request.suggested_value else None,
            run_id=request.run_id,
            proposal_id=request.proposal_id,
            journal_entry_id=request.journal_entry_id,
            metrics_payload=request.metrics_payload,
            reviewed_at=request.reviewed_at or datetime.now(timezone.utc),
        )
        record = StrategyReviewRecord(id=review.id)
        self.session.add(record)
        self._apply_review(record, review)
        self.session.commit()
        self.session.refresh(record)
        return self._to_review(record)

    def list_reviews(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategyReview]:
        query = (
            select(StrategyReviewRecord)
            .order_by(StrategyReviewRecord.reviewed_at.desc(), StrategyReviewRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(StrategyReviewRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategyReviewRecord.strategy_id == strategy_id)
        return [self._to_review(record) for record in self.session.execute(query).scalars().all()]

    def create_advisor_run(self, request: CreateStrategyAdvisorRunRequest) -> StrategyAdvisorRun:
        advisor_run = StrategyAdvisorRun(
            external_account_id=request.external_account_id.strip(),
            source=request.source.strip().lower(),
            mode=request.mode,
            provider=request.provider.strip().lower() if request.provider else None,
            model=request.model.strip() if request.model else None,
            status=request.status,
            context_format=request.context_format.strip() if request.context_format else None,
            context_limit=request.context_limit,
            prompt_tokens=request.prompt_tokens,
            completion_tokens=request.completion_tokens,
            total_tokens=request.total_tokens,
            reasoning_tokens=request.reasoning_tokens,
            cache_hit_tokens=request.cache_hit_tokens,
            cache_miss_tokens=request.cache_miss_tokens,
            proposal_count=request.proposal_count,
            review_count=request.review_count,
            response_id=request.response_id,
            finish_reason=request.finish_reason,
            error_message=request.error_message.strip() if request.error_message else None,
            response_payload=request.response_payload,
            raw_response=request.raw_response,
            started_at=request.started_at,
            completed_at=request.completed_at,
            recorded_at=request.recorded_at,
        )
        record = StrategyAdvisorRunRecord(id=advisor_run.id)
        self.session.add(record)
        self._apply_advisor_run(record, advisor_run)
        self.session.commit()
        self.session.refresh(record)
        return self._to_advisor_run(record)

    def mark_advisor_run_recorded(
        self,
        advisor_run_id: str,
        *,
        recorded_at: datetime,
        proposal_count: int,
        review_count: int,
        response_payload: dict | None = None,
    ) -> StrategyAdvisorRun:
        record = self.session.get(StrategyAdvisorRunRecord, advisor_run_id)
        if record is None:
            raise LookupError(f"Advisor run '{advisor_run_id}' was not found.")
        record.status = StrategyAdvisorRunStatus.RECORDED.value
        record.recorded_at = recorded_at
        record.proposal_count = proposal_count
        record.review_count = review_count
        if response_payload is not None:
            record.response_payload = response_payload
        self.session.commit()
        self.session.refresh(record)
        return self._to_advisor_run(record)

    def list_advisor_runs(
        self,
        *,
        external_account_id: str | None = None,
        source: str | None = None,
        limit: int = 20,
    ) -> list[StrategyAdvisorRun]:
        query = (
            select(StrategyAdvisorRunRecord)
            .order_by(StrategyAdvisorRunRecord.created_at.desc())
            .limit(limit)
        )
        if external_account_id is not None:
            query = query.where(StrategyAdvisorRunRecord.external_account_id == external_account_id)
        if source is not None:
            query = query.where(StrategyAdvisorRunRecord.source == source.strip().lower())
        return [self._to_advisor_run(record) for record in self.session.execute(query).scalars().all()]

    def _resolve_broker_account_id(self, external_account_id: str) -> str | None:
        broker_account = self.session.execute(
            select(BrokerAccountRecord).where(
                BrokerAccountRecord.external_account_id == external_account_id,
            )
        ).scalar_one_or_none()
        return broker_account.id if broker_account is not None else None

    def _apply_proposal(self, record: StrategyProposalRecord, proposal: StrategyProposal) -> None:
        record.broker_account_id = self._resolve_broker_account_id(proposal.external_account_id)
        record.strategy_id = proposal.strategy_id
        record.external_account_id = proposal.external_account_id
        record.execution_mode = proposal.mode.value
        record.symbol = proposal.symbol
        record.title = proposal.title
        record.proposed_action = proposal.proposed_action
        record.thesis = proposal.thesis
        record.rationale = proposal.rationale
        record.status = proposal.status.value
        record.confidence = proposal.confidence
        record.expected_max_loss = proposal.expected_max_loss
        record.expected_max_profit = proposal.expected_max_profit
        record.approval_required = proposal.approval_required
        record.approved_at = proposal.approved_at
        record.rejected_at = proposal.rejected_at
        record.expires_at = proposal.expires_at
        record.source = proposal.source
        record.source_run_id = proposal.source_run_id
        record.candidate_payload = proposal.candidate_payload
        record.risk_payload = proposal.risk_payload
        record.checks = proposal.checks or None

    def _apply_run(self, record: StrategyRunRecord, run: StrategyRun) -> None:
        record.broker_account_id = self._resolve_broker_account_id(run.external_account_id)
        record.strategy_id = run.strategy_id
        record.external_account_id = run.external_account_id
        record.execution_mode = run.mode.value
        record.run_type = run.run_type
        record.status = run.status.value
        record.symbol = run.symbol
        record.proposal_id = run.proposal_id
        record.trade_plan_id = run.trade_plan_id
        record.order_id = run.order_id
        record.spread_id = run.spread_id
        record.started_at = run.started_at
        record.completed_at = run.completed_at
        record.summary = run.summary
        record.reason = run.reason
        record.metrics_payload = run.metrics_payload
        record.raw_payload = run.raw_payload

    def _apply_signal(self, record: StrategySignalRecord, signal: StrategySignal) -> None:
        record.broker_account_id = self._resolve_broker_account_id(signal.external_account_id)
        record.strategy_id = signal.strategy_id
        record.external_account_id = signal.external_account_id
        record.execution_mode = signal.mode.value
        record.signal_type = signal.signal_type.value
        record.symbol = signal.symbol
        record.run_id = signal.run_id
        record.proposal_id = signal.proposal_id
        record.strength = signal.strength
        record.summary = signal.summary
        record.detail = signal.detail
        record.source = signal.source
        record.signal_payload = signal.signal_payload
        record.emitted_at = signal.emitted_at

    def _apply_review(self, record: StrategyReviewRecord, review: StrategyReview) -> None:
        record.broker_account_id = self._resolve_broker_account_id(review.external_account_id)
        record.strategy_id = review.strategy_id
        record.external_account_id = review.external_account_id
        record.execution_mode = review.mode.value
        record.review_type = review.review_type
        record.status = review.status.value
        record.summary = review.summary
        record.recommendation = review.recommendation
        record.parameter_name = review.parameter_name
        record.current_value = review.current_value
        record.suggested_value = review.suggested_value
        record.run_id = review.run_id
        record.proposal_id = review.proposal_id
        record.journal_entry_id = review.journal_entry_id
        record.metrics_payload = review.metrics_payload
        record.reviewed_at = review.reviewed_at

    def _apply_advisor_run(self, record: StrategyAdvisorRunRecord, advisor_run: StrategyAdvisorRun) -> None:
        record.broker_account_id = self._resolve_broker_account_id(advisor_run.external_account_id)
        record.external_account_id = advisor_run.external_account_id
        record.execution_mode = advisor_run.mode.value
        record.source = advisor_run.source
        record.provider = advisor_run.provider
        record.model = advisor_run.model
        record.status = advisor_run.status.value
        record.context_format = advisor_run.context_format
        record.context_limit = advisor_run.context_limit
        record.prompt_tokens = advisor_run.prompt_tokens
        record.completion_tokens = advisor_run.completion_tokens
        record.total_tokens = advisor_run.total_tokens
        record.reasoning_tokens = advisor_run.reasoning_tokens
        record.cache_hit_tokens = advisor_run.cache_hit_tokens
        record.cache_miss_tokens = advisor_run.cache_miss_tokens
        record.proposal_count = advisor_run.proposal_count
        record.review_count = advisor_run.review_count
        record.response_id = advisor_run.response_id
        record.finish_reason = advisor_run.finish_reason
        record.error_message = advisor_run.error_message
        record.response_payload = advisor_run.response_payload
        record.raw_response = advisor_run.raw_response
        record.started_at = advisor_run.started_at
        record.completed_at = advisor_run.completed_at
        record.recorded_at = advisor_run.recorded_at

    @staticmethod
    def _to_proposal(record: StrategyProposalRecord) -> StrategyProposal:
        return StrategyProposal.model_validate(
            {
                "id": record.id,
                "strategy_id": record.strategy_id,
                "external_account_id": record.external_account_id,
                "mode": record.execution_mode,
                "symbol": record.symbol,
                "title": record.title,
                "proposed_action": record.proposed_action,
                "thesis": record.thesis,
                "rationale": record.rationale,
                "status": record.status,
                "confidence": record.confidence,
                "expected_max_loss": record.expected_max_loss,
                "expected_max_profit": record.expected_max_profit,
                "approval_required": record.approval_required,
                "approved_at": record.approved_at,
                "rejected_at": record.rejected_at,
                "expires_at": record.expires_at,
                "source": record.source,
                "source_run_id": record.source_run_id,
                "candidate_payload": record.candidate_payload,
                "risk_payload": record.risk_payload,
                "checks": list(record.checks or []),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

    @staticmethod
    def _to_run(record: StrategyRunRecord) -> StrategyRun:
        return StrategyRun.model_validate(
            {
                "id": record.id,
                "strategy_id": record.strategy_id,
                "external_account_id": record.external_account_id,
                "mode": record.execution_mode,
                "run_type": record.run_type,
                "status": record.status,
                "symbol": record.symbol,
                "proposal_id": record.proposal_id,
                "trade_plan_id": record.trade_plan_id,
                "order_id": record.order_id,
                "spread_id": record.spread_id,
                "started_at": record.started_at,
                "completed_at": record.completed_at,
                "summary": record.summary,
                "reason": record.reason,
                "metrics_payload": record.metrics_payload,
                "raw_payload": record.raw_payload,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

    @staticmethod
    def _to_signal(record: StrategySignalRecord) -> StrategySignal:
        return StrategySignal.model_validate(
            {
                "id": record.id,
                "strategy_id": record.strategy_id,
                "external_account_id": record.external_account_id,
                "mode": record.execution_mode,
                "signal_type": record.signal_type,
                "symbol": record.symbol,
                "run_id": record.run_id,
                "proposal_id": record.proposal_id,
                "strength": record.strength,
                "summary": record.summary,
                "detail": record.detail,
                "source": record.source,
                "signal_payload": record.signal_payload,
                "emitted_at": record.emitted_at,
                "created_at": record.created_at,
            }
        )

    @staticmethod
    def _to_review(record: StrategyReviewRecord) -> StrategyReview:
        return StrategyReview.model_validate(
            {
                "id": record.id,
                "strategy_id": record.strategy_id,
                "external_account_id": record.external_account_id,
                "mode": record.execution_mode,
                "review_type": record.review_type,
                "status": record.status,
                "summary": record.summary,
                "recommendation": record.recommendation,
                "parameter_name": record.parameter_name,
                "current_value": record.current_value,
                "suggested_value": record.suggested_value,
                "run_id": record.run_id,
                "proposal_id": record.proposal_id,
                "journal_entry_id": record.journal_entry_id,
                "metrics_payload": record.metrics_payload,
                "reviewed_at": record.reviewed_at,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

    @staticmethod
    def _to_advisor_run(record: StrategyAdvisorRunRecord) -> StrategyAdvisorRun:
        return StrategyAdvisorRun.model_validate(
            {
                "id": record.id,
                "external_account_id": record.external_account_id,
                "source": record.source,
                "mode": record.execution_mode,
                "provider": record.provider,
                "model": record.model,
                "status": record.status,
                "context_format": record.context_format,
                "context_limit": record.context_limit,
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": record.completion_tokens,
                "total_tokens": record.total_tokens,
                "reasoning_tokens": record.reasoning_tokens,
                "cache_hit_tokens": record.cache_hit_tokens,
                "cache_miss_tokens": record.cache_miss_tokens,
                "proposal_count": record.proposal_count,
                "review_count": record.review_count,
                "response_id": record.response_id,
                "finish_reason": record.finish_reason,
                "error_message": record.error_message,
                "response_payload": record.response_payload,
                "raw_response": record.raw_response,
                "started_at": record.started_at,
                "completed_at": record.completed_at,
                "recorded_at": record.recorded_at,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            }
        )

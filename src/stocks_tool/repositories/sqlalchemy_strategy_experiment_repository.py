import hashlib
import json
from collections import Counter
from collections.abc import Collection
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from stocks_tool.db.models import (
    BrokerAccountRecord,
    StrategyAuditEventRecord,
    StrategyAdvisorRunRecord,
    StrategyProposalRecord,
    StrategyReviewRecord,
    StrategyRunRecord,
    StrategySignalRecord,
)
from stocks_tool.domain.enums import (
    ExecutionMode,
    StrategyProposalStatus,
    StrategyAdvisorRunStatus,
    StrategyReviewStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    CreateStrategyAuditEventRequest,
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
from stocks_tool.repositories.sqlalchemy_strategy_audit_event_repository import (
    SQLAlchemyStrategyAuditEventRepository,
)
from stocks_tool.ports.repository import StrategyExperimentRepository


class SQLAlchemyStrategyExperimentRepository(StrategyExperimentRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_proposal(self, request: CreateStrategyProposalRequest) -> StrategyProposal:
        proposal = self._proposal_from_request(request)
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
        statuses: Collection[StrategyProposalStatus] | None = None,
        mode: ExecutionMode | None = None,
        symbol: str | None = None,
        symbols: Collection[str] | None = None,
        proposal_ids: Collection[str] | None = None,
        proposed_actions: Collection[str] | None = None,
        limit: int | None = 20,
    ) -> list[StrategyProposal]:
        query = (
            select(StrategyProposalRecord)
            .order_by(
                StrategyProposalRecord.updated_at.desc(),
                StrategyProposalRecord.created_at.desc(),
                StrategyProposalRecord.id.desc(),
            )
        )
        if external_account_id is not None:
            query = query.where(StrategyProposalRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategyProposalRecord.strategy_id == strategy_id)
        if status is not None:
            query = query.where(StrategyProposalRecord.status == status.value)
        if statuses is not None:
            normalized_statuses = [item.value for item in statuses]
            if not normalized_statuses:
                return []
            query = query.where(StrategyProposalRecord.status.in_(normalized_statuses))
        if mode is not None:
            query = query.where(StrategyProposalRecord.execution_mode == mode.value)
        if symbol is not None:
            query = query.where(StrategyProposalRecord.symbol == symbol.strip().upper())
        if symbols is not None:
            normalized_symbols = [item.strip().upper() for item in symbols if item.strip()]
            if not normalized_symbols:
                return []
            query = query.where(StrategyProposalRecord.symbol.in_(normalized_symbols))
        if proposal_ids is not None:
            normalized_ids = [str(item) for item in proposal_ids if str(item)]
            if not normalized_ids:
                return []
            query = query.where(StrategyProposalRecord.id.in_(normalized_ids))
        if proposed_actions is not None:
            normalized_actions = [item.strip() for item in proposed_actions if item.strip()]
            if not normalized_actions:
                return []
            query = query.where(StrategyProposalRecord.proposed_action.in_(normalized_actions))
        if limit is not None:
            query = query.limit(limit)
        return [self._to_proposal(record) for record in self.session.execute(query).scalars().all()]

    def iter_proposals(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        status: StrategyProposalStatus | None = None,
        mode: ExecutionMode | None = None,
    ):
        query = select(StrategyProposalRecord).order_by(
            StrategyProposalRecord.updated_at.desc(),
            StrategyProposalRecord.created_at.desc(),
            StrategyProposalRecord.id.desc(),
        )
        if external_account_id is not None:
            query = query.where(StrategyProposalRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategyProposalRecord.strategy_id == strategy_id)
        if status is not None:
            query = query.where(StrategyProposalRecord.status == status.value)
        if mode is not None:
            query = query.where(StrategyProposalRecord.execution_mode == mode.value)
        result = self.session.execute(
            query.execution_options(stream_results=True, yield_per=200)
        ).scalars()
        for record in result:
            yield self._to_proposal(record)

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
        status: StrategyRunStatus | None = None,
        statuses: Collection[StrategyRunStatus] | None = None,
        mode: ExecutionMode | None = None,
        symbol: str | None = None,
        order_id: str | None = None,
        proposal_id: str | None = None,
        proposal_ids: Collection[str] | None = None,
        run_types: Collection[str] | None = None,
        limit: int | None = 20,
    ) -> list[StrategyRun]:
        query = (
            select(StrategyRunRecord)
            .order_by(StrategyRunRecord.created_at.desc(), StrategyRunRecord.id.desc())
        )
        if external_account_id is not None:
            query = query.where(StrategyRunRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategyRunRecord.strategy_id == strategy_id)
        if status is not None:
            query = query.where(StrategyRunRecord.status == status.value)
        if statuses is not None:
            normalized_statuses = [item.value for item in statuses]
            if not normalized_statuses:
                return []
            query = query.where(StrategyRunRecord.status.in_(normalized_statuses))
        if mode is not None:
            query = query.where(StrategyRunRecord.execution_mode == mode.value)
        if symbol is not None:
            query = query.where(StrategyRunRecord.symbol == symbol.strip().upper())
        if order_id is not None:
            query = query.where(StrategyRunRecord.order_id == order_id)
        if proposal_id is not None:
            query = query.where(StrategyRunRecord.proposal_id == proposal_id)
        if proposal_ids is not None:
            normalized_ids = [str(item) for item in proposal_ids if str(item)]
            if not normalized_ids:
                return []
            query = query.where(StrategyRunRecord.proposal_id.in_(normalized_ids))
        if run_types is not None:
            normalized_run_types = [item.strip() for item in run_types if item.strip()]
            if not normalized_run_types:
                return []
            query = query.where(StrategyRunRecord.run_type.in_(normalized_run_types))
        if limit is not None:
            query = query.limit(limit)
        return [self._to_run(record) for record in self.session.execute(query).scalars().all()]

    def iter_runs(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        mode: ExecutionMode | None = None,
        order_id: str | None = None,
        proposal_ids: Collection[str] | None = None,
    ):
        query = select(StrategyRunRecord).order_by(
            StrategyRunRecord.created_at.desc(),
            StrategyRunRecord.id.desc(),
        )
        if external_account_id is not None:
            query = query.where(StrategyRunRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategyRunRecord.strategy_id == strategy_id)
        if mode is not None:
            query = query.where(StrategyRunRecord.execution_mode == mode.value)
        if order_id is not None:
            query = query.where(StrategyRunRecord.order_id == order_id)
        if proposal_ids is not None:
            normalized_ids = [str(item) for item in proposal_ids if str(item)]
            if not normalized_ids:
                return
            query = query.where(StrategyRunRecord.proposal_id.in_(normalized_ids))
        result = self.session.execute(
            query.execution_options(stream_results=True, yield_per=200)
        ).scalars()
        for record in result:
            yield self._to_run(record)

    def get_latest_run_for_proposal(
        self,
        *,
        proposal_id: str,
        strategy_id: str,
        run_types: set[str],
    ) -> StrategyRun | None:
        """Return the latest matching run for one proposal exactly."""
        query = (
            select(StrategyRunRecord)
            .where(
                StrategyRunRecord.proposal_id == proposal_id,
                StrategyRunRecord.strategy_id == strategy_id,
                StrategyRunRecord.run_type.in_(sorted(run_types)),
            )
            .order_by(StrategyRunRecord.created_at.desc(), StrategyRunRecord.id.desc())
            .limit(1)
        )
        record = self.session.execute(query).scalar_one_or_none()
        return self._to_run(record) if record is not None else None

    def list_latest_runs_by_proposal(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        mode: ExecutionMode | None = None,
        run_types: Collection[str],
        proposal_ids: Collection[str] | None = None,
    ) -> list[StrategyRun]:
        normalized_types = [item.strip() for item in run_types if item.strip()]
        if not normalized_types:
            return []
        ranked = select(
            StrategyRunRecord.id.label("run_id"),
            func.row_number()
            .over(
                partition_by=(StrategyRunRecord.proposal_id, StrategyRunRecord.run_type),
                order_by=(StrategyRunRecord.created_at.desc(), StrategyRunRecord.id.desc()),
            )
            .label("row_number"),
        ).where(
            StrategyRunRecord.proposal_id.is_not(None),
            StrategyRunRecord.run_type.in_(normalized_types),
        )
        if external_account_id is not None:
            ranked = ranked.where(StrategyRunRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            ranked = ranked.where(StrategyRunRecord.strategy_id == strategy_id)
        if mode is not None:
            ranked = ranked.where(StrategyRunRecord.execution_mode == mode.value)
        if proposal_ids is not None:
            normalized_ids = [str(item) for item in proposal_ids if str(item)]
            if not normalized_ids:
                return []
            ranked = ranked.where(StrategyRunRecord.proposal_id.in_(normalized_ids))
        ranked_subquery = ranked.subquery()
        query = (
            select(StrategyRunRecord)
            .join(ranked_subquery, StrategyRunRecord.id == ranked_subquery.c.run_id)
            .where(ranked_subquery.c.row_number == 1)
            .order_by(StrategyRunRecord.created_at.desc(), StrategyRunRecord.id.desc())
        )
        records = self.session.execute(query).scalars().all()
        return [self._to_run(record) for record in records]

    def get_covered_call_activity_aggregate(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
    ) -> dict[str, object]:
        proposal_query = select(
            func.count(StrategyProposalRecord.id),
            func.coalesce(
                func.sum(
                    case(
                        (
                            StrategyProposalRecord.status.in_(
                                [StrategyProposalStatus.PENDING.value, StrategyProposalStatus.APPROVED.value]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            StrategyProposalRecord.proposed_action.in_(
                                ["sell_covered_call", "roll_covered_call"]
                            )
                            & (StrategyProposalRecord.status == StrategyProposalStatus.EXECUTED.value),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (StrategyProposalRecord.proposed_action == "roll_covered_call")
                            & StrategyProposalRecord.status.in_(
                                [StrategyProposalStatus.PENDING.value, StrategyProposalStatus.APPROVED.value]
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.max(StrategyProposalRecord.updated_at),
        ).where(StrategyProposalRecord.strategy_id == "covered_call_v1")
        if external_account_id is not None:
            proposal_query = proposal_query.where(
                StrategyProposalRecord.external_account_id == external_account_id
            )
        if mode is not None:
            proposal_query = proposal_query.where(StrategyProposalRecord.execution_mode == mode.value)
        proposal_values = self.session.execute(proposal_query).one()

        run_query = select(
            func.count(StrategyRunRecord.id),
            func.max(StrategyRunRecord.created_at),
        ).where(
            StrategyRunRecord.strategy_id == "covered_call_v1",
            StrategyRunRecord.run_type == "proposal_close",
        )
        activity_run_query = select(func.max(StrategyRunRecord.created_at)).where(
            StrategyRunRecord.strategy_id == "covered_call_v1",
            StrategyRunRecord.run_type.in_(
                [
                    "proposal_close",
                    "proposal_execution",
                    "open_lifecycle_refresh",
                    "roll_execution",
                    "roll_continuation",
                ]
            ),
        )
        for query_name in ("run_query", "activity_run_query"):
            query = locals()[query_name]
            if external_account_id is not None:
                query = query.where(StrategyRunRecord.external_account_id == external_account_id)
            if mode is not None:
                query = query.where(StrategyRunRecord.execution_mode == mode.value)
            if query_name == "run_query":
                run_query = query
            else:
                activity_run_query = query
        close_count, close_latest = self.session.execute(run_query).one()
        lifecycle_latest = self.session.execute(activity_run_query).scalar_one()
        signal_latest = self.session.execute(
            select(func.max(StrategySignalRecord.emitted_at)).where(
                StrategySignalRecord.strategy_id == "covered_call_v1",
                *([StrategySignalRecord.external_account_id == external_account_id] if external_account_id is not None else []),
                *([StrategySignalRecord.execution_mode == mode.value] if mode is not None else []),
            )
        ).scalar_one()
        review_latest = self.session.execute(
            select(func.max(StrategyReviewRecord.reviewed_at)).where(
                StrategyReviewRecord.strategy_id == "covered_call_v1",
                *([StrategyReviewRecord.external_account_id == external_account_id] if external_account_id is not None else []),
                *([StrategyReviewRecord.execution_mode == mode.value] if mode is not None else []),
            )
        ).scalar_one()
        latest_values = [value for value in (proposal_values[4], lifecycle_latest, signal_latest, review_latest) if value]
        return {
            "total_proposals": int(proposal_values[0] or 0),
            "active_proposals": int(proposal_values[1] or 0),
            "executed_positions": int(proposal_values[2] or 0),
            "pending_rolls": int(proposal_values[3] or 0),
            "close_runs": int(close_count or 0),
            "latest_activity_at": max(latest_values) if latest_values else None,
        }

    def list_runs_for_order_ids(
        self,
        *,
        external_account_id: str,
        strategy_id: str,
        mode: ExecutionMode,
        order_ids: Collection[str],
    ) -> list[StrategyRun]:
        ids = [str(item) for item in order_ids if str(item)]
        if not ids:
            return []
        query = select(StrategyRunRecord).where(
            StrategyRunRecord.external_account_id == external_account_id,
            StrategyRunRecord.strategy_id == strategy_id,
            StrategyRunRecord.execution_mode == mode.value,
            or_(
                StrategyRunRecord.order_id.in_(ids),
                StrategyRunRecord.metrics_payload["order_id"].as_string().in_(ids),
                StrategyRunRecord.metrics_payload["reconciled_order_id"].as_string().in_(ids),
                StrategyRunRecord.metrics_payload["manual_scan_order_id"].as_string().in_(ids),
            ),
        ).order_by(StrategyRunRecord.created_at.desc(), StrategyRunRecord.id.desc())
        return [self._to_run(record) for record in self.session.execute(query).scalars().all()]

    def list_signals_for_run_or_order_ids(
        self,
        *,
        external_account_id: str,
        strategy_id: str,
        mode: ExecutionMode,
        run_ids: Collection[str],
        order_ids: Collection[str],
    ) -> list[StrategySignal]:
        normalized_runs = [str(item) for item in run_ids if str(item)]
        normalized_orders = [str(item) for item in order_ids if str(item)]
        if not normalized_runs and not normalized_orders:
            return []
        predicates = []
        if normalized_runs:
            predicates.append(StrategySignalRecord.run_id.in_(normalized_runs))
        if normalized_orders:
            predicates.extend(
                [
                    StrategySignalRecord.signal_payload["reconciled_order"]["id"].as_string().in_(normalized_orders),
                    StrategySignalRecord.signal_payload["order"]["id"].as_string().in_(normalized_orders),
                ]
            )
        query = select(StrategySignalRecord).where(
            StrategySignalRecord.external_account_id == external_account_id,
            StrategySignalRecord.strategy_id == strategy_id,
            StrategySignalRecord.execution_mode == mode.value,
            or_(*predicates),
        ).order_by(StrategySignalRecord.emitted_at.desc(), StrategySignalRecord.created_at.desc())
        return [self._to_signal(record) for record in self.session.execute(query).scalars().all()]

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
        mode: ExecutionMode | None = None,
        run_id: str | None = None,
        proposal_id: str | None = None,
        limit: int | None = 20,
    ) -> list[StrategySignal]:
        query = (
            select(StrategySignalRecord)
            .order_by(StrategySignalRecord.emitted_at.desc(), StrategySignalRecord.created_at.desc())
        )
        if external_account_id is not None:
            query = query.where(StrategySignalRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategySignalRecord.strategy_id == strategy_id)
        if mode is not None:
            query = query.where(StrategySignalRecord.execution_mode == mode.value)
        if run_id is not None:
            query = query.where(StrategySignalRecord.run_id == run_id)
        if proposal_id is not None:
            query = query.where(StrategySignalRecord.proposal_id == proposal_id)
        if limit is not None:
            query = query.limit(limit)
        return [self._to_signal(record) for record in self.session.execute(query).scalars().all()]

    def iter_signals(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        mode: ExecutionMode | None = None,
        run_id: str | None = None,
        proposal_id: str | None = None,
    ):
        query = select(StrategySignalRecord).order_by(
            StrategySignalRecord.emitted_at.desc(),
            StrategySignalRecord.created_at.desc(),
            StrategySignalRecord.id.desc(),
        )
        if external_account_id is not None:
            query = query.where(StrategySignalRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategySignalRecord.strategy_id == strategy_id)
        if mode is not None:
            query = query.where(StrategySignalRecord.execution_mode == mode.value)
        if run_id is not None:
            query = query.where(StrategySignalRecord.run_id == run_id)
        if proposal_id is not None:
            query = query.where(StrategySignalRecord.proposal_id == proposal_id)
        result = self.session.execute(
            query.execution_options(stream_results=True, yield_per=200)
        ).scalars()
        for record in result:
            yield self._to_signal(record)

    def create_review(self, request: CreateStrategyReviewRequest) -> StrategyReview:
        review = self._review_from_request(request)
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
        mode: ExecutionMode | None = None,
        limit: int | None = 20,
    ) -> list[StrategyReview]:
        query = (
            select(StrategyReviewRecord)
            .order_by(StrategyReviewRecord.reviewed_at.desc(), StrategyReviewRecord.created_at.desc())
        )
        if external_account_id is not None:
            query = query.where(StrategyReviewRecord.external_account_id == external_account_id)
        if strategy_id is not None:
            query = query.where(StrategyReviewRecord.strategy_id == strategy_id)
        if mode is not None:
            query = query.where(StrategyReviewRecord.execution_mode == mode.value)
        if limit is not None:
            query = query.limit(limit)
        return [self._to_review(record) for record in self.session.execute(query).scalars().all()]

    def create_advisor_run(self, request: CreateStrategyAdvisorRunRequest) -> StrategyAdvisorRun:
        advisor_run = StrategyAdvisorRun(
            id=request.id or str(uuid4()),
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
        try:
            self._apply_advisor_run(record, advisor_run)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        self.session.refresh(record)
        return self._to_advisor_run(record)

    def record_advisor_intake(
        self,
        *,
        external_account_id: str,
        source: str,
        mode: ExecutionMode,
        advisor_run_id: str | None,
        proposal_requests: list[CreateStrategyProposalRequest],
        review_requests: list[CreateStrategyReviewRequest],
        response_payload: dict,
        recorded_at: datetime,
    ) -> tuple[list[StrategyProposal], list[StrategyReview], StrategyAdvisorRun | None]:
        """Persist one advisor response and its policy evidence atomically.

        The normal create methods intentionally remain small CRUD commands for
        the other strategy workflows.  Advisor recording needs a stronger
        boundary: the run is locked, all downstream records are inserted, and
        the run is marked recorded only by one transaction.  The fingerprint
        is kept in the existing JSON response payload so this does not require
        a schema migration.
        """
        if self.session.new or self.session.dirty or self.session.deleted:
            raise RuntimeError(
                "Advisor intake requires a clean SQLAlchemy session before its atomic write boundary."
            )
        if self.session.in_transaction():
            # The intake service reads its context before entering this write
            # boundary.  Those reads have opened an implicit transaction; no
            # writes are allowed to cross into the batch transaction.
            self.session.rollback()

        fingerprint = self._advisor_response_fingerprint(response_payload)
        proposal_records: list[StrategyProposalRecord] = []
        review_records: list[StrategyReviewRecord] = []
        proposal_models: list[StrategyProposal] = []

        try:
            with self.session.begin():
                advisor_run_record = None
                if advisor_run_id is not None:
                    advisor_run_record = self.session.execute(
                        select(StrategyAdvisorRunRecord)
                        .where(StrategyAdvisorRunRecord.id == advisor_run_id)
                        .with_for_update()
                    ).scalar_one_or_none()
                    if advisor_run_record is None:
                        raise LookupError(f"Advisor run '{advisor_run_id}' was not found.")
                    self._validate_advisor_run_for_intake(
                        advisor_run_record,
                        external_account_id=external_account_id,
                        source=source,
                        mode=mode,
                        fingerprint=fingerprint,
                    )

                    if advisor_run_record.status == StrategyAdvisorRunStatus.RECORDED.value:
                        expected_proposal_count = self._advisor_record_count(
                            response_payload,
                            "proposals",
                            fallback=advisor_run_record.proposal_count,
                        )
                        expected_review_count = self._advisor_record_count(
                            response_payload,
                            "reviews",
                            fallback=advisor_run_record.review_count,
                        )
                        expected_proposal_strategies = self._advisor_record_strategies(
                            response_payload,
                            "proposals",
                        )
                        expected_review_strategies = self._advisor_record_strategies(
                            response_payload,
                            "reviews",
                        )
                        proposals = self._existing_advisor_proposals(
                            advisor_run_id,
                            external_account_id=external_account_id,
                            mode=mode,
                        )
                        reviews = self._existing_advisor_reviews(
                            advisor_run_id,
                            external_account_id=external_account_id,
                            mode=mode,
                            strategy_ids=expected_review_strategies,
                        )
                        self._assert_replay_records_complete(
                            advisor_run_id,
                            records=proposals,
                            expected_count=expected_proposal_count,
                            expected_strategies=expected_proposal_strategies,
                            record_type="proposal",
                        )
                        self._assert_replay_records_complete(
                            advisor_run_id,
                            records=reviews,
                            expected_count=expected_review_count,
                            expected_strategies=expected_review_strategies,
                            record_type="review",
                        )
                        return (
                            proposals,
                            reviews,
                            self._to_advisor_run(advisor_run_record),
                        )

                for request in proposal_requests:
                    proposal = self._proposal_from_request(request)
                    record = StrategyProposalRecord(id=proposal.id)
                    self.session.add(record)
                    self._apply_proposal(record, proposal)
                    proposal_records.append(record)
                    proposal_models.append(proposal)

                for request in review_requests:
                    review = self._review_from_request(request)
                    record = StrategyReviewRecord(id=review.id)
                    self.session.add(record)
                    self._apply_review(record, review)
                    review_records.append(record)

                # proposal/review records use server-side timestamps.  Flush
                # before creating linked policy evidence and before converting
                # the records back to domain models.
                self.session.flush()

                audit_repository = SQLAlchemyStrategyAuditEventRepository(self.session)
                for proposal in proposal_models:
                    signal = self._advisor_policy_signal(
                        proposal,
                        advisor_run_id=advisor_run_id,
                    )
                    signal_record = StrategySignalRecord(id=signal.id)
                    self.session.add(signal_record)
                    self._apply_signal(signal_record, signal)
                    audit_request = CreateStrategyAuditEventRequest(
                        external_account_id=proposal.external_account_id,
                        mode=proposal.mode,
                        actor="advisor",
                        source="strategy_policy",
                        strategy=proposal.strategy_id,
                        action="advisor_proposal_recorded",
                        proposal_id=proposal.id,
                        run_id=advisor_run_id,
                        summary="Advisor-sourced strategy proposal recorded as read-only advice.",
                        detail="Local deterministic checks and manual approval are still required before execution.",
                        payload={
                            "signal_id": signal.id,
                            "advisor_source": self._normalized_source(proposal.source),
                            "llm_direct_execution_allowed": False,
                            "approval_required": proposal.approval_required,
                        },
                    )
                    audit_record = StrategyAuditEventRecord(id=audit_request.id or str(uuid4()))
                    self.session.add(audit_record)
                    audit_repository._apply_request(audit_record, audit_request)

                advisor_run = None
                if advisor_run_record is not None:
                    advisor_run_record.status = StrategyAdvisorRunStatus.RECORDED.value
                    advisor_run_record.recorded_at = recorded_at
                    advisor_run_record.proposal_count = len(proposal_records)
                    advisor_run_record.review_count = len(review_records)
                    advisor_run_record.response_payload = self._with_advisor_fingerprint(
                        response_payload,
                        fingerprint,
                    )
                    run_audit_request = CreateStrategyAuditEventRequest(
                        external_account_id=external_account_id,
                        mode=mode,
                        actor="advisor",
                        source=source,
                        strategy="strategy_advisor",
                        action="advisor_run_card_recorded",
                        run_id=advisor_run_id,
                        summary=(
                            f"Advisor run recorded with {len(proposal_records)} proposal(s) "
                            f"and {len(review_records)} review(s)."
                        ),
                        payload={
                            "status": StrategyAdvisorRunStatus.RECORDED.value,
                            "proposal_count": len(proposal_records),
                            "review_count": len(review_records),
                        },
                    )
                    run_audit_record = StrategyAuditEventRecord(
                        id=run_audit_request.id or str(uuid4())
                    )
                    self.session.add(run_audit_record)
                    audit_repository._apply_request(run_audit_record, run_audit_request)

                self.session.flush()

                proposals = [self._to_proposal(record) for record in proposal_records]
                reviews = [self._to_review(record) for record in review_records]
                if advisor_run_record is not None:
                    advisor_run = self._to_advisor_run(advisor_run_record)
                return proposals, reviews, advisor_run
        except Exception:
            self.session.rollback()
            raise

    @staticmethod
    def _proposal_from_request(request: CreateStrategyProposalRequest) -> StrategyProposal:
        return StrategyProposal(
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

    @staticmethod
    def _review_from_request(request: CreateStrategyReviewRequest) -> StrategyReview:
        return StrategyReview(
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

    @staticmethod
    def _advisor_policy_signal(
        proposal: StrategyProposal,
        *,
        advisor_run_id: str | None,
    ) -> StrategySignal:
        return StrategySignal(
            strategy_id=proposal.strategy_id,
            external_account_id=proposal.external_account_id,
            mode=proposal.mode,
            signal_type=StrategySignalType.REVIEW,
            symbol=proposal.symbol,
            run_id=advisor_run_id,
            proposal_id=proposal.id,
            summary="Advisor-sourced strategy proposal recorded as read-only advice.",
            detail="Local deterministic checks and manual approval are still required before execution.",
            source="strategy_policy",
            signal_payload={
                "audit_event": "advisor_proposal_recorded",
                "advisor_source": proposal.source.strip().lower() if proposal.source else None,
                "advisor_run_id": advisor_run_id,
                "llm_direct_execution_allowed": False,
                "approval_required": proposal.approval_required,
                "proposed_action": proposal.proposed_action,
                "checks": proposal.checks,
            },
        )

    @staticmethod
    def _normalized_source(source: str | None) -> str | None:
        return source.strip().lower() if source is not None else None

    @classmethod
    def _advisor_response_fingerprint(cls, response_payload: dict) -> str:
        payload = dict(response_payload)
        payload.pop("_recording_fingerprint", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _with_advisor_fingerprint(response_payload: dict, fingerprint: str) -> dict:
        payload = dict(response_payload)
        payload["_recording_fingerprint"] = fingerprint
        return payload

    def _validate_advisor_run_for_intake(
        self,
        record: StrategyAdvisorRunRecord,
        *,
        external_account_id: str,
        source: str,
        mode: ExecutionMode,
        fingerprint: str,
    ) -> None:
        if record.external_account_id != external_account_id:
            raise ValueError("Advisor run belongs to a different broker account.")
        if record.source.strip().lower() != source.strip().lower():
            raise ValueError("Advisor run source does not match the response source.")
        if record.execution_mode != mode.value:
            raise ValueError("Advisor run mode does not match the response mode.")
        if record.status not in {
            StrategyAdvisorRunStatus.SUCCEEDED.value,
            StrategyAdvisorRunStatus.RECORDED.value,
        }:
            raise ValueError(
                f"Advisor run '{record.id}' cannot record a response from state '{record.status}'."
            )

        stored_payload = dict(record.response_payload or {})
        stored_fingerprint = stored_payload.get("_recording_fingerprint")
        if stored_fingerprint is None and stored_payload:
            stored_fingerprint = self._advisor_response_fingerprint(stored_payload)
        if stored_fingerprint is not None and stored_fingerprint != fingerprint:
            raise ValueError(
                f"Advisor run '{record.id}' was already associated with a different response payload."
            )

    @staticmethod
    def _advisor_record_count(payload: dict, key: str, *, fallback: int) -> int:
        records = payload.get(key)
        return len(records) if isinstance(records, list) else fallback

    @staticmethod
    def _advisor_record_strategies(payload: dict, key: str) -> Counter[str]:
        records = payload.get(key)
        if not isinstance(records, list):
            return Counter()
        return Counter(
            str(record.get("strategy_id"))
            for record in records
            if isinstance(record, dict) and record.get("strategy_id")
        )

    @staticmethod
    def _assert_replay_records_complete(
        advisor_run_id: str,
        *,
        records: list[StrategyProposal] | list[StrategyReview],
        expected_count: int,
        expected_strategies: Counter[str],
        record_type: str,
    ) -> None:
        actual_strategies = Counter(record.strategy_id for record in records)
        if len(records) != expected_count or (
            expected_strategies and actual_strategies != expected_strategies
        ):
            raise ValueError(
                f"Advisor run '{advisor_run_id}' replay could not recover its complete "
                f"{record_type} set (expected {expected_count}, found {len(records)})."
            )

    def _existing_advisor_proposals(
        self,
        advisor_run_id: str,
        *,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> list[StrategyProposal]:
        query = (
            select(StrategyProposalRecord)
            .where(
                StrategyProposalRecord.source_run_id == advisor_run_id,
                StrategyProposalRecord.external_account_id == external_account_id,
                StrategyProposalRecord.execution_mode == mode.value,
            )
            .order_by(StrategyProposalRecord.created_at.asc(), StrategyProposalRecord.id.asc())
        )
        return [self._to_proposal(record) for record in self.session.execute(query).scalars().all()]

    def _existing_advisor_reviews(
        self,
        advisor_run_id: str,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        strategy_ids: Counter[str],
    ) -> list[StrategyReview]:
        query = (
            select(StrategyReviewRecord)
            .where(
                StrategyReviewRecord.external_account_id == external_account_id,
                StrategyReviewRecord.execution_mode == mode.value,
            )
            .order_by(StrategyReviewRecord.created_at.asc(), StrategyReviewRecord.id.asc())
        )
        records: list[StrategyReview] = []
        for record in self.session.execute(query).scalars().all():
            metadata = record.metrics_payload if isinstance(record.metrics_payload, dict) else {}
            linked_run_id = record.run_id or metadata.get("advisor_run_id")
            if linked_run_id != advisor_run_id:
                continue
            if strategy_ids and record.strategy_id not in strategy_ids:
                continue
            records.append(self._to_review(record))
        return records

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

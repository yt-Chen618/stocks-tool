from datetime import datetime, timezone

from stocks_tool.domain.enums import StrategyProposalStatus
from stocks_tool.domain.models import (
    CoveredCallActivitySnapshot,
    CoveredCallActivitySummary,
    CreateStrategyProposalRequest,
    CreateStrategyReviewRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    StrategyExperimentSnapshot,
    StrategyProposal,
    StrategyReview,
    StrategyRun,
    StrategySignal,
)
from stocks_tool.ports.repository import BrokerAccountRepository, StrategyExperimentRepository


class StrategyExperimentService:
    def __init__(
        self,
        *,
        experiments: StrategyExperimentRepository,
        broker_accounts: BrokerAccountRepository,
    ) -> None:
        self.experiments = experiments
        self.broker_accounts = broker_accounts

    def get_snapshot(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 10,
    ) -> StrategyExperimentSnapshot:
        if external_account_id is not None:
            self._ensure_account(external_account_id)
        return StrategyExperimentSnapshot(
            external_account_id=external_account_id,
            proposals=self.list_proposals(
                external_account_id=external_account_id,
                strategy_id=strategy_id,
                limit=limit,
            ),
            runs=self.list_runs(
                external_account_id=external_account_id,
                strategy_id=strategy_id,
                limit=limit,
            ),
            signals=self.list_signals(
                external_account_id=external_account_id,
                strategy_id=strategy_id,
                limit=limit,
            ),
            reviews=self.list_reviews(
                external_account_id=external_account_id,
                strategy_id=strategy_id,
                limit=limit,
            ),
        )

    def get_covered_call_activity(
        self,
        *,
        external_account_id: str | None = None,
        limit: int = 12,
    ) -> CoveredCallActivitySnapshot:
        snapshot = self.get_snapshot(
            external_account_id=external_account_id,
            strategy_id="covered_call_v1",
            limit=limit,
        )
        return CoveredCallActivitySnapshot(
            external_account_id=external_account_id,
            summary=self._covered_call_activity_summary(snapshot),
            proposals=snapshot.proposals,
            runs=snapshot.runs,
            signals=snapshot.signals,
            reviews=snapshot.reviews,
        )

    def create_proposal(self, request: CreateStrategyProposalRequest) -> StrategyProposal:
        self._ensure_account(request.external_account_id)
        return self.experiments.create_proposal(request)

    def get_proposal(self, proposal_id: str) -> StrategyProposal:
        proposal = self.experiments.get_proposal(proposal_id)
        if proposal is None:
            raise LookupError(f"Strategy proposal '{proposal_id}' was not found.")
        return proposal

    def approve_proposal(self, proposal_id: str) -> StrategyProposal:
        proposal = self.get_proposal(proposal_id)
        if proposal.status != StrategyProposalStatus.PENDING:
            raise ValueError(f"Strategy proposal '{proposal_id}' is not pending approval.")
        now = datetime.now(timezone.utc)
        if proposal.expires_at is not None and proposal.expires_at < now:
            self.experiments.update_proposal_status(
                proposal_id,
                status=StrategyProposalStatus.EXPIRED,
            )
            raise ValueError(f"Strategy proposal '{proposal_id}' has expired.")
        return self.experiments.update_proposal_status(
            proposal_id,
            status=StrategyProposalStatus.APPROVED,
            approved_at=now,
        )

    def reject_proposal(self, proposal_id: str) -> StrategyProposal:
        proposal = self.get_proposal(proposal_id)
        if proposal.status not in {StrategyProposalStatus.PENDING, StrategyProposalStatus.APPROVED}:
            raise ValueError(
                f"Strategy proposal '{proposal_id}' cannot be rejected from status '{proposal.status.value}'."
            )
        return self.experiments.update_proposal_status(
            proposal_id,
            status=StrategyProposalStatus.REJECTED,
            rejected_at=datetime.now(timezone.utc),
        )

    def list_proposals(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        status: StrategyProposalStatus | None = None,
        limit: int = 20,
    ) -> list[StrategyProposal]:
        if external_account_id is not None:
            self._ensure_account(external_account_id)
        return self.experiments.list_proposals(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            status=status,
            limit=limit,
        )

    def create_run(self, request: CreateStrategyRunRequest) -> StrategyRun:
        self._ensure_account(request.external_account_id)
        return self.experiments.create_run(request)

    def list_runs(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategyRun]:
        if external_account_id is not None:
            self._ensure_account(external_account_id)
        return self.experiments.list_runs(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )

    def create_signal(self, request: CreateStrategySignalRequest) -> StrategySignal:
        self._ensure_account(request.external_account_id)
        return self.experiments.create_signal(request)

    def list_signals(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategySignal]:
        if external_account_id is not None:
            self._ensure_account(external_account_id)
        return self.experiments.list_signals(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )

    def create_review(self, request: CreateStrategyReviewRequest) -> StrategyReview:
        self._ensure_account(request.external_account_id)
        return self.experiments.create_review(request)

    def list_reviews(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategyReview]:
        if external_account_id is not None:
            self._ensure_account(external_account_id)
        return self.experiments.list_reviews(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )

    def _ensure_account(self, external_account_id: str) -> None:
        if self.broker_accounts.get_by_external_account_id(external_account_id) is None:
            raise LookupError(f"Broker account '{external_account_id}' was not found.")

    @staticmethod
    def _covered_call_activity_summary(
        snapshot: StrategyExperimentSnapshot,
    ) -> CoveredCallActivitySummary:
        active_statuses = {
            StrategyProposalStatus.PENDING,
            StrategyProposalStatus.APPROVED,
        }
        latest_candidates = [
            proposal.updated_at for proposal in snapshot.proposals if proposal.updated_at is not None
        ]
        latest_candidates.extend(run.created_at for run in snapshot.runs if run.created_at is not None)
        latest_candidates.extend(signal.emitted_at for signal in snapshot.signals if signal.emitted_at is not None)
        latest_candidates.extend(review.reviewed_at for review in snapshot.reviews if review.reviewed_at is not None)
        return CoveredCallActivitySummary(
            external_account_id=snapshot.external_account_id,
            total_proposals=len(snapshot.proposals),
            active_proposals=sum(1 for proposal in snapshot.proposals if proposal.status in active_statuses),
            executed_positions=sum(
                1
                for proposal in snapshot.proposals
                if proposal.proposed_action == "sell_covered_call"
                and proposal.status == StrategyProposalStatus.EXECUTED
            ),
            pending_rolls=sum(
                1
                for proposal in snapshot.proposals
                if proposal.proposed_action == "roll_covered_call" and proposal.status in active_statuses
            ),
            close_runs=sum(1 for run in snapshot.runs if run.run_type == "proposal_close"),
            latest_activity_at=max(latest_candidates) if latest_candidates else None,
        )

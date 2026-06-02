from datetime import datetime, timezone

from decimal import Decimal, InvalidOperation

from stocks_tool.domain.enums import StrategyProposalStatus, StrategySignalType
from stocks_tool.domain.models import (
    CoveredCallLifecycleTask,
    CoveredCallActivitySnapshot,
    CoveredCallActivitySummary,
    CoveredCallMonitorSnapshot,
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
    WORKING_ORDER_STALE_AFTER_SECONDS = 15 * 60

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
            lifecycle_tasks=self._covered_call_lifecycle_tasks(snapshot),
            latest_monitor=self._covered_call_latest_monitor(snapshot),
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
                if proposal.proposed_action in {"sell_covered_call", "roll_covered_call"}
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

    @staticmethod
    def _covered_call_lifecycle_tasks(
        snapshot: StrategyExperimentSnapshot,
    ) -> list[CoveredCallLifecycleTask]:
        close_runs = StrategyExperimentService._latest_runs_by_proposal(
            snapshot.runs,
            {"proposal_close"},
        )
        execution_runs = StrategyExperimentService._latest_runs_by_proposal(
            snapshot.runs,
            {"proposal_execution", "open_lifecycle_refresh"},
        )
        roll_runs = StrategyExperimentService._latest_runs_by_proposal(
            snapshot.runs,
            {"roll_execution", "roll_continuation"},
        )
        tasks: list[CoveredCallLifecycleTask] = []
        for proposal in snapshot.proposals:
            if proposal.proposed_action == "sell_covered_call" and proposal.status == StrategyProposalStatus.APPROVED:
                execution_run = execution_runs.get(proposal.id)
                if execution_run is not None:
                    open_order_id = (
                        StrategyExperimentService._payload_str(execution_run.metrics_payload, "order_id")
                        or execution_run.order_id
                    )
                    if open_order_id:
                        open_status = (
                            StrategyExperimentService._payload_str(execution_run.metrics_payload, "sell_status")
                            or StrategyExperimentService._payload_str(execution_run.metrics_payload, "order_status")
                        )
                        sequence_status = StrategyExperimentService._payload_str(
                            execution_run.metrics_payload,
                            "sequence_status",
                        )
                        last_refresh_at = (
                            execution_run.completed_at
                            or execution_run.updated_at
                            or execution_run.created_at
                        )
                        order_submitted_at = StrategyExperimentService._payload_datetime(
                            execution_run.metrics_payload,
                            "order_submitted_at",
                        )
                        diagnostic = StrategyExperimentService._working_order_diagnostic(
                            task_type="open",
                            status=sequence_status or open_status,
                            order_submitted_at=order_submitted_at,
                            last_refresh_at=last_refresh_at,
                        )
                        tasks.append(
                            CoveredCallLifecycleTask(
                                proposal_id=proposal.id,
                                proposal_title=proposal.title,
                                symbol=proposal.symbol,
                                task_type="open",
                                proposal_status=proposal.status,
                                last_run_id=execution_run.id,
                                last_run_type=execution_run.run_type,
                                open_order_id=open_order_id,
                                open_status=open_status,
                                sequence_status=sequence_status,
                                last_refresh_status=sequence_status or open_status or "sell_submitted_waiting_fill",
                                last_refresh_at=last_refresh_at,
                                order_submitted_at=order_submitted_at,
                                order_age_seconds=diagnostic["order_age_seconds"],
                                stale_after_seconds=diagnostic["stale_after_seconds"],
                                is_stale=diagnostic["is_stale"],
                                diagnostic=diagnostic["diagnostic"],
                                suggested_action=diagnostic["suggested_action"],
                                summary=execution_run.summary,
                                reason=execution_run.reason,
                            )
                        )

            if proposal.proposed_action in {"sell_covered_call", "roll_covered_call"}:
                close_run = close_runs.get(proposal.id)
                if proposal.status == StrategyProposalStatus.EXECUTED and close_run is not None:
                    close_order_id = (
                        StrategyExperimentService._payload_str(close_run.metrics_payload, "order_id")
                        or close_run.order_id
                    )
                    if close_order_id:
                        close_status = (
                            StrategyExperimentService._payload_str(close_run.metrics_payload, "close_status")
                            or StrategyExperimentService._payload_str(close_run.metrics_payload, "order_status")
                        )
                        last_refresh_at = close_run.completed_at or close_run.updated_at or close_run.created_at
                        order_submitted_at = StrategyExperimentService._payload_datetime(
                            close_run.metrics_payload,
                            "order_submitted_at",
                        )
                        diagnostic = StrategyExperimentService._working_order_diagnostic(
                            task_type="close",
                            status=close_status,
                            order_submitted_at=order_submitted_at,
                            last_refresh_at=last_refresh_at,
                        )
                        tasks.append(
                            CoveredCallLifecycleTask(
                                proposal_id=proposal.id,
                                proposal_title=proposal.title,
                                symbol=proposal.symbol,
                                task_type="close",
                                proposal_status=proposal.status,
                                last_run_id=close_run.id,
                                last_run_type=close_run.run_type,
                                close_order_id=close_order_id,
                                close_status=close_status,
                                last_refresh_status=close_status or "submitted_waiting_fill",
                                last_refresh_at=last_refresh_at,
                                order_submitted_at=order_submitted_at,
                                order_age_seconds=diagnostic["order_age_seconds"],
                                stale_after_seconds=diagnostic["stale_after_seconds"],
                                is_stale=diagnostic["is_stale"],
                                diagnostic=diagnostic["diagnostic"],
                                suggested_action=diagnostic["suggested_action"],
                                summary=close_run.summary,
                                reason=close_run.reason,
                            )
                        )

            if proposal.proposed_action == "roll_covered_call" and proposal.status == StrategyProposalStatus.APPROVED:
                roll_run = roll_runs.get(proposal.id)
                if roll_run is None:
                    continue
                buyback_order_id = (
                    StrategyExperimentService._payload_str(roll_run.metrics_payload, "buyback_order_id")
                    or roll_run.order_id
                )
                if not buyback_order_id:
                    continue
                sequence_status = StrategyExperimentService._payload_str(roll_run.metrics_payload, "sequence_status")
                buyback_status = StrategyExperimentService._payload_str(roll_run.metrics_payload, "buyback_status")
                sell_status = StrategyExperimentService._payload_str(roll_run.metrics_payload, "sell_status")
                sell_order_id = StrategyExperimentService._payload_str(roll_run.metrics_payload, "sell_order_id")
                last_refresh_status = sequence_status or sell_status or buyback_status or "buyback_submitted_waiting_fill"
                last_refresh_at = roll_run.completed_at or roll_run.updated_at or roll_run.created_at
                order_submitted_at = StrategyExperimentService._payload_datetime(
                    roll_run.metrics_payload,
                    "sell_order_submitted_at" if sell_order_id else "buyback_order_submitted_at",
                )
                diagnostic = StrategyExperimentService._working_order_diagnostic(
                    task_type="roll",
                    status=last_refresh_status,
                    order_submitted_at=order_submitted_at,
                    last_refresh_at=last_refresh_at,
                )
                tasks.append(
                    CoveredCallLifecycleTask(
                        proposal_id=proposal.id,
                        proposal_title=proposal.title,
                        symbol=proposal.symbol,
                        task_type="roll",
                        proposal_status=proposal.status,
                        last_run_id=roll_run.id,
                        last_run_type=roll_run.run_type,
                        roll_buyback_order_id=buyback_order_id,
                        roll_sell_order_id=sell_order_id,
                        buyback_status=buyback_status,
                        sell_status=sell_status,
                        sequence_status=sequence_status,
                        last_refresh_status=last_refresh_status,
                        last_refresh_at=last_refresh_at,
                        order_submitted_at=order_submitted_at,
                        order_age_seconds=diagnostic["order_age_seconds"],
                        stale_after_seconds=diagnostic["stale_after_seconds"],
                        is_stale=diagnostic["is_stale"],
                        diagnostic=diagnostic["diagnostic"],
                        suggested_action=diagnostic["suggested_action"],
                        summary=roll_run.summary,
                        reason=roll_run.reason,
                    )
                )
        return sorted(
            tasks,
            key=lambda task: task.last_refresh_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    @staticmethod
    def _covered_call_latest_monitor(
        snapshot: StrategyExperimentSnapshot,
    ) -> CoveredCallMonitorSnapshot | None:
        for signal in snapshot.signals:
            if signal.signal_type != StrategySignalType.MONITOR:
                continue
            payload = signal.signal_payload if isinstance(signal.signal_payload, dict) else {}
            return CoveredCallMonitorSnapshot(
                proposal_id=signal.proposal_id,
                symbol=signal.symbol,
                action=StrategyExperimentService._payload_str(payload, "action"),
                detail=signal.detail,
                underlying_price=StrategyExperimentService._payload_decimal(payload, "underlying_price"),
                call_mark=StrategyExperimentService._payload_decimal(payload, "call_mark"),
                estimated_open_pnl=StrategyExperimentService._payload_decimal(payload, "estimated_open_pnl"),
                premium_capture_pct=StrategyExperimentService._payload_decimal(payload, "premium_capture_pct"),
                days_to_expiration=StrategyExperimentService._payload_int(payload, "days_to_expiration"),
                emitted_at=signal.emitted_at,
                signal_id=signal.id,
            )
        return None

    @staticmethod
    def _latest_runs_by_proposal(
        runs: list[StrategyRun],
        run_types: set[str],
    ) -> dict[str, StrategyRun]:
        latest: dict[str, StrategyRun] = {}
        for run in runs:
            if run.proposal_id is None or run.run_type not in run_types or run.proposal_id in latest:
                continue
            latest[run.proposal_id] = run
        return latest

    @staticmethod
    def _payload_str(payload: dict | None, key: str) -> str | None:
        if not payload:
            return None
        value = payload.get(key)
        if value is None:
            return None
        return str(value)

    @staticmethod
    def _payload_decimal(payload: dict | None, key: str) -> Decimal | None:
        value = StrategyExperimentService._payload_str(payload, key)
        if value is None:
            return None
        try:
            return Decimal(value)
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _payload_int(payload: dict | None, key: str) -> int | None:
        value = StrategyExperimentService._payload_str(payload, key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _payload_datetime(payload: dict | None, key: str) -> datetime | None:
        value = StrategyExperimentService._payload_str(payload, key)
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _working_order_diagnostic(
        *,
        task_type: str,
        status: str | None,
        order_submitted_at: datetime | None,
        last_refresh_at: datetime | None,
    ) -> dict[str, int | bool | str | None]:
        stale_after_seconds = StrategyExperimentService.WORKING_ORDER_STALE_AFTER_SECONDS
        if order_submitted_at is None or last_refresh_at is None:
            return {
                "order_age_seconds": None,
                "stale_after_seconds": stale_after_seconds,
                "is_stale": False,
                "diagnostic": None,
                "suggested_action": None,
            }

        order_age_seconds = max(0, int((last_refresh_at - order_submitted_at).total_seconds()))
        status_text = (status or "").lower()
        working = any(token in status_text for token in ("submitted", "waiting", "new"))
        is_stale = working and order_age_seconds >= stale_after_seconds
        if not is_stale:
            return {
                "order_age_seconds": order_age_seconds,
                "stale_after_seconds": stale_after_seconds,
                "is_stale": False,
                "diagnostic": f"Working order age is {order_age_seconds // 60} min.",
                "suggested_action": None,
            }

        action_map = {
            "open": "Refresh quote and order detail; if still marketable but unfilled, consider cancel/re-enter or replace with explicit approval.",
            "close": "Refresh quote and order detail; if risk is rising and the order is still unfilled, consider replacing the buyback limit with explicit approval.",
            "roll": "Refresh both roll legs; if the active leg is still unfilled, avoid submitting a duplicate and consider replace/cancel only with explicit approval.",
        }
        return {
            "order_age_seconds": order_age_seconds,
            "stale_after_seconds": stale_after_seconds,
            "is_stale": True,
            "diagnostic": f"Working order has been unfilled for {order_age_seconds // 60} min.",
            "suggested_action": action_map.get(task_type, action_map["open"]),
        }

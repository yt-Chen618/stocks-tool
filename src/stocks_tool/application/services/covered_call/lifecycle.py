from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from stocks_tool.application.services.covered_call.order_lifecycle import (
    build_order_request,
    order_filled,
    order_timing_payload,
)
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.strategy_idempotency import strategy_order_identity
from stocks_tool.domain.enums import (
    ExecutionMode,
    OrderSide,
    StrategyProposalStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    CloseCoveredCallProposalRequest,
    ContinueCoveredCallRollRequest,
    CoveredCallCandidate,
    CoveredCallCloseResult,
    CoveredCallExecutionResult,
    CoveredCallRollExecutionResult,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    ExecuteCoveredCallProposalRequest,
    ExecuteCoveredCallRollProposalRequest,
    Order,
    StrategyProposal,
)
from stocks_tool.ports.repository import StrategyExperimentRepository


@dataclass(frozen=True)
class OpenAuthorization:
    candidate: CoveredCallCandidate
    limit_price: Decimal


@dataclass(frozen=True)
class CloseAuthorization:
    candidate: CoveredCallCandidate
    limit_price: Decimal


@dataclass(frozen=True)
class RollAuthorization:
    roll_from: CoveredCallCandidate
    roll_to: CoveredCallCandidate
    buyback_limit: Decimal
    sell_limit: Decimal


@dataclass(frozen=True)
class ContinueRollAuthorization:
    roll_from: CoveredCallCandidate
    roll_to: CoveredCallCandidate
    buyback_order: Order


@dataclass(frozen=True)
class ContinueSellAuthorization:
    sell_order: Order | None
    roll_to: CoveredCallCandidate
    sell_limit: Decimal | None


class CoveredCallLifecyclePolicy(Protocol):
    def authorize_open(
        self,
        *,
        proposal: StrategyProposal,
        request: ExecuteCoveredCallProposalRequest,
        parent_action_intent_id: str | None,
    ) -> OpenAuthorization: ...

    def authorize_close(
        self,
        *,
        proposal: StrategyProposal,
        request: CloseCoveredCallProposalRequest,
    ) -> CloseAuthorization: ...

    def authorize_roll(
        self,
        *,
        proposal: StrategyProposal,
        request: ExecuteCoveredCallRollProposalRequest,
    ) -> RollAuthorization: ...

    def authorize_roll_sell(
        self,
        *,
        proposal: StrategyProposal,
        request: ExecuteCoveredCallRollProposalRequest,
        roll_from: CoveredCallCandidate,
        roll_to: CoveredCallCandidate,
        buyback_order: Order,
        proposed_sell_limit: Decimal,
    ) -> ContinueSellAuthorization: ...

    def authorize_continue_preflight(
        self,
        *,
        proposal: StrategyProposal,
        request: ContinueCoveredCallRollRequest,
    ) -> ContinueRollAuthorization: ...

    def authorize_continue_sell(
        self,
        *,
        proposal: StrategyProposal,
        request: ContinueCoveredCallRollRequest,
        roll_from: CoveredCallCandidate,
        roll_to: CoveredCallCandidate,
    ) -> ContinueSellAuthorization: ...


class CoveredCallLifecycleOrders(Protocol):
    def submit(
        self,
        *,
        proposal: StrategyProposal,
        candidate: CoveredCallCandidate,
        side: OrderSide,
        limit_price: Decimal,
        remark: str,
        action: str,
        leg: str,
        parent_action_intent_id: str | None,
    ) -> Order: ...

    def refresh(self, order_id: str) -> Order: ...

    def is_filled(self, order: Order | None) -> bool: ...


class CoveredCallLifecycleRecorder(Protocol):
    def record_open(
        self,
        *,
        proposal: StrategyProposal,
        candidate: CoveredCallCandidate,
        order: Order,
        limit_price: Decimal,
    ) -> CoveredCallExecutionResult: ...

    def record_close(
        self,
        *,
        proposal: StrategyProposal,
        candidate: CoveredCallCandidate,
        order: Order,
        limit_price: Decimal,
    ) -> CoveredCallCloseResult: ...

    def record_roll(
        self,
        *,
        proposal: StrategyProposal,
        roll_from: CoveredCallCandidate,
        roll_to: CoveredCallCandidate,
        buyback_order: Order,
        sell_order: Order | None,
        sequence_status: str,
        reason: str | None,
        buyback_limit_price: Decimal | None = None,
        sell_limit_price: Decimal | None = None,
    ) -> CoveredCallRollExecutionResult: ...

    def record_continue_roll(
        self,
        *,
        proposal: StrategyProposal,
        roll_from: CoveredCallCandidate,
        roll_to: CoveredCallCandidate,
        buyback_order: Order,
        sell_order: Order | None,
        sequence_status: str,
        reason: str | None,
        buyback_limit_price: Decimal | None = None,
        sell_limit_price: Decimal | None = None,
    ) -> CoveredCallRollExecutionResult: ...


class CoveredCallLifecycleChildFailure(Protocol):
    def __call__(self, parent_action_intent_id: str | None, exc: Exception) -> None: ...


class CoveredCallLifecyclePersistenceFailure(Protocol):
    def __call__(self, parent_action_intent_id: str | None, exc: Exception) -> None: ...


class CoveredCallLifecycleOrderGateway:
    """Submit and refresh Covered Call child orders through the shared ledger."""

    def __init__(self, *, order_service: OrderService, strategy_id: str) -> None:
        self.order_service = order_service
        self.strategy_id = strategy_id

    def submit(
        self,
        *,
        proposal: StrategyProposal,
        candidate: CoveredCallCandidate,
        side: OrderSide,
        limit_price: Decimal,
        remark: str,
        action: str,
        leg: str,
        parent_action_intent_id: str | None,
    ) -> Order:
        idempotency_key, action_context = strategy_order_identity(
            strategy_id=self.strategy_id,
            entity_id=proposal.id,
            action=action,
            leg=leg,
        )
        return self.order_service.submit_order(
            build_order_request(
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                candidate=candidate,
                side=side,
                limit_price=limit_price,
                remark=remark,
            ),
            idempotency_key=idempotency_key,
            action_context=action_context,
            parent_action_intent_id=parent_action_intent_id,
        )

    def refresh(self, order_id: str) -> Order:
        return self.order_service.refresh_order(order_id)

    @staticmethod
    def is_filled(order: Order | None) -> bool:
        return order_filled(order)


class CoveredCallLifecycleRecorderImpl:
    """Persist lifecycle runs/signals and proposal transitions after child orders."""

    def __init__(
        self,
        *,
        experiments: StrategyExperimentRepository,
        strategy_id: str,
        mark_roll_source_rolled: Callable[[StrategyProposal], None],
    ) -> None:
        self.experiments = experiments
        self.strategy_id = strategy_id
        self.mark_roll_source_rolled = mark_roll_source_rolled

    def record_open(
        self,
        *,
        proposal: StrategyProposal,
        candidate: CoveredCallCandidate,
        order: Order,
        limit_price: Decimal,
    ) -> CoveredCallExecutionResult:
        now = datetime.now(timezone.utc)
        filled = order_filled(order)
        reason = None if filled else "Sell-to-open order is working; proposal stays approved until the short call is filled."
        run = self.experiments.create_run(
            CreateStrategyRunRequest(
                strategy_id=self.strategy_id,
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                run_type="proposal_execution",
                status=StrategyRunStatus.EXECUTED,
                symbol=proposal.symbol,
                proposal_id=proposal.id,
                order_id=order.id,
                started_at=now,
                completed_at=now,
                summary=f"Submitted covered call sell order for {candidate.call_symbol}.",
                reason=reason,
                metrics_payload={
                    "proposal_id": proposal.id,
                    "order_id": order.id,
                    "sequence_status": "sell_filled" if filled else "sell_submitted_waiting_fill",
                    "sell_status": order.status.value,
                    "limit_price": str(limit_price),
                    **order_timing_payload(order),
                    "candidate": candidate.model_dump(mode="json"),
                },
            )
        )
        signal = self.experiments.create_signal(
            CreateStrategySignalRequest(
                strategy_id=self.strategy_id,
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                signal_type=StrategySignalType.EXECUTION,
                symbol=proposal.symbol,
                run_id=run.id,
                proposal_id=proposal.id,
                summary=f"Covered call order submitted for {candidate.call_symbol}.",
                detail=reason,
                source="covered_call_v1",
                signal_payload={
                    "order_id": order.id,
                    "sequence_status": "sell_filled" if filled else "sell_submitted_waiting_fill",
                    "sell_status": order.status.value,
                    **order_timing_payload(order),
                    "candidate": candidate.model_dump(mode="json"),
                },
            )
        )
        result_proposal = (
            self.experiments.update_proposal_status(proposal.id, status=StrategyProposalStatus.EXECUTED)
            if filled
            else proposal
        )
        return CoveredCallExecutionResult(proposal=result_proposal, order=order, run=run, signal=signal)

    def record_close(
        self,
        *,
        proposal: StrategyProposal,
        candidate: CoveredCallCandidate,
        order: Order,
        limit_price: Decimal,
    ) -> CoveredCallCloseResult:
        now = datetime.now(timezone.utc)
        run = self.experiments.create_run(
            CreateStrategyRunRequest(
                strategy_id=self.strategy_id,
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                run_type="proposal_close",
                status=StrategyRunStatus.EXECUTED,
                symbol=proposal.symbol,
                proposal_id=proposal.id,
                order_id=order.id,
                started_at=now,
                completed_at=now,
                summary=f"Submitted covered call buy-to-close order for {candidate.call_symbol}.",
                metrics_payload={
                    "proposal_id": proposal.id,
                    "order_id": order.id,
                    "limit_price": str(limit_price),
                    **order_timing_payload(order),
                    "candidate": candidate.model_dump(mode="json"),
                },
            )
        )
        signal = self.experiments.create_signal(
            CreateStrategySignalRequest(
                strategy_id=self.strategy_id,
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                signal_type=StrategySignalType.EXECUTION,
                symbol=proposal.symbol,
                run_id=run.id,
                proposal_id=proposal.id,
                summary=f"Covered call close order submitted for {candidate.call_symbol}.",
                source="covered_call_v1",
                signal_payload={
                    "order_id": order.id,
                    **order_timing_payload(order),
                    "candidate": candidate.model_dump(mode="json"),
                },
            )
        )
        result_proposal = (
            self.experiments.update_proposal_status(proposal.id, status=StrategyProposalStatus.CLOSED)
            if order_filled(order)
            else proposal
        )
        return CoveredCallCloseResult(proposal=result_proposal, order=order, run=run, signal=signal)

    def record_roll(
        self,
        *,
        proposal: StrategyProposal,
        roll_from: CoveredCallCandidate,
        roll_to: CoveredCallCandidate,
        buyback_order: Order,
        sell_order: Order | None,
        sequence_status: str,
        reason: str | None,
        buyback_limit_price: Decimal | None = None,
        sell_limit_price: Decimal | None = None,
    ) -> CoveredCallRollExecutionResult:
        return self._record_roll(
            run_type="roll_execution",
            summary=(
                f"Submitted covered call roll orders for {roll_from.underlying_symbol}."
                if sell_order is not None
                else f"Submitted covered call buyback order for {roll_from.call_symbol}; waiting to open roll."
            ),
            proposal=proposal,
            roll_from=roll_from,
            roll_to=roll_to,
            buyback_order=buyback_order,
            sell_order=sell_order,
            sequence_status=sequence_status,
            reason=reason,
            buyback_limit_price=buyback_limit_price,
            sell_limit_price=sell_limit_price,
        )

    def record_continue_roll(
        self,
        *,
        proposal: StrategyProposal,
        roll_from: CoveredCallCandidate,
        roll_to: CoveredCallCandidate,
        buyback_order: Order,
        sell_order: Order | None,
        sequence_status: str,
        reason: str | None,
        buyback_limit_price: Decimal | None = None,
        sell_limit_price: Decimal | None = None,
    ) -> CoveredCallRollExecutionResult:
        return self._record_roll(
            run_type="roll_continuation",
            summary=(
                f"Continued covered call roll into {roll_to.call_symbol}."
                if sell_order is not None
                else f"Refreshed covered call roll buyback order {buyback_order.id}; still waiting."
            ),
            proposal=proposal,
            roll_from=roll_from,
            roll_to=roll_to,
            buyback_order=buyback_order,
            sell_order=sell_order,
            sequence_status=sequence_status,
            reason=reason,
            buyback_limit_price=buyback_limit_price,
            sell_limit_price=sell_limit_price,
        )

    def _record_roll(
        self,
        *,
        run_type: str,
        summary: str,
        proposal: StrategyProposal,
        roll_from: CoveredCallCandidate,
        roll_to: CoveredCallCandidate,
        buyback_order: Order,
        sell_order: Order | None,
        sequence_status: str,
        reason: str | None,
        buyback_limit_price: Decimal | None,
        sell_limit_price: Decimal | None,
    ) -> CoveredCallRollExecutionResult:
        now = datetime.now(timezone.utc)
        run = self.experiments.create_run(
            CreateStrategyRunRequest(
                strategy_id=self.strategy_id,
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                run_type=run_type,
                status=StrategyRunStatus.EXECUTED,
                symbol=proposal.symbol,
                proposal_id=proposal.id,
                order_id=sell_order.id if sell_order is not None else buyback_order.id,
                started_at=now,
                completed_at=now,
                summary=summary,
                reason=reason,
                metrics_payload={
                    "proposal_id": proposal.id,
                    "sequence_status": sequence_status,
                    "buyback_order_id": buyback_order.id,
                    "sell_order_id": sell_order.id if sell_order is not None else None,
                    "buyback_status": buyback_order.status.value,
                    "sell_status": sell_order.status.value if sell_order is not None else None,
                    "buyback_limit_price": (
                        str(buyback_limit_price) if buyback_limit_price is not None else None
                    ),
                    "sell_limit_price": str(sell_limit_price) if sell_limit_price is not None else None,
                    **order_timing_payload(buyback_order, prefix="buyback_order"),
                    **(order_timing_payload(sell_order, prefix="sell_order") if sell_order is not None else {}),
                    "roll_from": roll_from.model_dump(mode="json"),
                    "roll_to": roll_to.model_dump(mode="json"),
                },
            )
        )
        signal = self.experiments.create_signal(
            CreateStrategySignalRequest(
                strategy_id=self.strategy_id,
                external_account_id=proposal.external_account_id,
                mode=proposal.mode,
                signal_type=StrategySignalType.EXECUTION,
                symbol=proposal.symbol,
                run_id=run.id,
                proposal_id=proposal.id,
                summary=(
                    f"Covered call roll submitted from {roll_from.call_symbol} to {roll_to.call_symbol}."
                    if sell_order is not None
                    else f"Covered call roll buyback submitted for {roll_from.call_symbol}."
                ),
                detail=reason,
                source="covered_call_v1",
                signal_payload={
                    "sequence_status": sequence_status,
                    "buyback_order_id": buyback_order.id,
                    "sell_order_id": sell_order.id if sell_order is not None else None,
                },
            )
        )
        result_proposal = proposal
        if order_filled(sell_order):
            self.mark_roll_source_rolled(proposal)
            result_proposal = self.experiments.update_proposal_status(
                proposal.id,
                status=StrategyProposalStatus.EXECUTED,
            )
        return CoveredCallRollExecutionResult(
            proposal=result_proposal,
            buyback_order=buyback_order,
            sell_order=sell_order,
            run=run,
            signal=signal,
            sequence_status=sequence_status,
            reason=reason,
        )


class CoveredCallLifecycle:
    """Coordinate Covered Call open, close, roll, and roll continuation phases."""

    def __init__(
        self,
        *,
        policy: CoveredCallLifecyclePolicy,
        orders: CoveredCallLifecycleOrders,
        recorder: CoveredCallLifecycleRecorder,
        prebroker_phase: Callable[[str | None], AbstractContextManager[None]],
        mark_child_failure: CoveredCallLifecycleChildFailure,
        mark_persistence_failure: CoveredCallLifecyclePersistenceFailure,
    ) -> None:
        self.policy = policy
        self.orders = orders
        self.recorder = recorder
        self.prebroker_phase = prebroker_phase
        self.mark_child_failure = mark_child_failure
        self.mark_persistence_failure = mark_persistence_failure

    def _submit(
        self,
        *,
        parent_action_intent_id: str | None,
        **kwargs,
    ) -> Order:
        try:
            return self.orders.submit(parent_action_intent_id=parent_action_intent_id, **kwargs)
        except Exception as exc:
            self.mark_child_failure(parent_action_intent_id, exc)
            raise

    def _record(self, callback: Callable[[], object], parent_action_intent_id: str | None):
        try:
            return callback()
        except Exception as exc:
            self.mark_persistence_failure(parent_action_intent_id, exc)
            raise

    def execute_open(
        self,
        *,
        proposal: StrategyProposal,
        request: ExecuteCoveredCallProposalRequest,
        parent_action_intent_id: str | None,
    ) -> CoveredCallExecutionResult:
        with self.prebroker_phase(parent_action_intent_id):
            authorization = self.policy.authorize_open(
                proposal=proposal,
                request=request,
                parent_action_intent_id=parent_action_intent_id,
            )
        order = self._submit(
            parent_action_intent_id=parent_action_intent_id,
            proposal=proposal,
            candidate=authorization.candidate,
            side=OrderSide.SELL,
            limit_price=authorization.limit_price,
            remark=request.remark or "covered-call",
            action="covered_call_open",
            leg="short_call_open",
        )
        return self._record(
            lambda: self.recorder.record_open(
                proposal=proposal,
                candidate=authorization.candidate,
                order=order,
                limit_price=authorization.limit_price,
            ),
            parent_action_intent_id,
        )

    def close(
        self,
        *,
        proposal: StrategyProposal,
        request: CloseCoveredCallProposalRequest,
        parent_action_intent_id: str | None,
    ) -> CoveredCallCloseResult:
        with self.prebroker_phase(parent_action_intent_id):
            authorization = self.policy.authorize_close(proposal=proposal, request=request)
        order = self._submit(
            parent_action_intent_id=parent_action_intent_id,
            proposal=proposal,
            candidate=authorization.candidate,
            side=OrderSide.BUY,
            limit_price=authorization.limit_price,
            remark=request.remark or "covered-call-close",
            action="covered_call_close",
            leg="short_call_close",
        )
        return self._record(
            lambda: self.recorder.record_close(
                proposal=proposal,
                candidate=authorization.candidate,
                order=order,
                limit_price=authorization.limit_price,
            ),
            parent_action_intent_id,
        )

    def execute_roll(
        self,
        *,
        proposal: StrategyProposal,
        request: ExecuteCoveredCallRollProposalRequest,
        parent_action_intent_id: str | None,
    ) -> CoveredCallRollExecutionResult:
        with self.prebroker_phase(parent_action_intent_id):
            authorization = self.policy.authorize_roll(proposal=proposal, request=request)
        buyback_order = self._submit(
            parent_action_intent_id=parent_action_intent_id,
            proposal=proposal,
            candidate=authorization.roll_from,
            side=OrderSide.BUY,
            limit_price=authorization.buyback_limit,
            remark=request.remark or "covered-call-roll-close",
            action="covered_call_roll",
            leg="roll_buyback",
        )
        sell_order = None
        sequence_status = "buyback_submitted_waiting_fill"
        reason = "Buyback order was submitted; sell-to-open is held until the old call is filled closed."
        if self.orders.is_filled(buyback_order):
            try:
                sell_authorization = self.policy.authorize_roll_sell(
                    proposal=proposal,
                    request=request,
                    roll_from=authorization.roll_from,
                    roll_to=authorization.roll_to,
                    buyback_order=buyback_order,
                    proposed_sell_limit=authorization.sell_limit,
                )
            except (LookupError, PermissionError, RuntimeError, ValueError) as exc:
                sequence_status = "roll_sell_blocked_manual_action"
                reason = f"Buyback filled, but the replacement sell-to-open is blocked and requires manual review: {exc}"
            else:
                sell_order = self._submit(
                    parent_action_intent_id=parent_action_intent_id,
                    proposal=proposal,
                    candidate=sell_authorization.roll_to,
                    side=OrderSide.SELL,
                    limit_price=sell_authorization.sell_limit,
                    remark=request.remark or "covered-call-roll-open",
                    action="covered_call_roll",
                    leg="roll_sell_open",
                )
                if self.orders.is_filled(sell_order):
                    sequence_status = "roll_filled"
                    reason = None
                else:
                    sequence_status = "roll_sell_submitted_waiting_fill"
                    reason = "Sell-to-open order was submitted; roll stays pending until the new short call is filled."
        return self._record(
            lambda: self.recorder.record_roll(
                proposal=proposal,
                roll_from=authorization.roll_from,
                roll_to=authorization.roll_to,
                buyback_order=buyback_order,
                sell_order=sell_order,
                sequence_status=sequence_status,
                reason=reason,
                buyback_limit_price=authorization.buyback_limit,
                sell_limit_price=authorization.sell_limit,
            ),
            parent_action_intent_id,
        )

    def continue_roll(
        self,
        *,
        proposal: StrategyProposal,
        request: ContinueCoveredCallRollRequest,
        parent_action_intent_id: str | None,
    ) -> CoveredCallRollExecutionResult:
        with self.prebroker_phase(parent_action_intent_id):
            authorization = self.policy.authorize_continue_preflight(
                proposal=proposal,
                request=request,
            )
        buyback_order = authorization.buyback_order
        sell_order = None
        sequence_status = "buyback_still_working"
        reason = "Buyback order is not filled yet; sell-to-open remains held."
        if self.orders.is_filled(buyback_order):
            with self.prebroker_phase(parent_action_intent_id):
                sell_authorization = self.policy.authorize_continue_sell(
                    proposal=proposal,
                    request=request,
                    roll_from=authorization.roll_from,
                    roll_to=authorization.roll_to,
                )
            sell_order = sell_authorization.sell_order
            if sell_order is None:
                sell_order = self._submit(
                    parent_action_intent_id=parent_action_intent_id,
                    proposal=proposal,
                    candidate=sell_authorization.roll_to,
                    side=OrderSide.SELL,
                    limit_price=sell_authorization.sell_limit or Decimal("0"),
                    remark=request.remark or "covered-call-roll-open",
                    action="covered_call_roll",
                    leg="roll_sell_open",
                )
            if self.orders.is_filled(sell_order):
                sequence_status = "roll_filled"
                reason = None
            else:
                sequence_status = "roll_sell_submitted_waiting_fill"
                reason = "Sell-to-open order is working; roll stays pending until the new short call is filled."
        return self._record(
            lambda: self.recorder.record_continue_roll(
                proposal=proposal,
                roll_from=authorization.roll_from,
                roll_to=authorization.roll_to,
                buyback_order=buyback_order,
                sell_order=sell_order,
                sequence_status=sequence_status,
                reason=reason,
                sell_limit_price=getattr(request, "sell_limit_price", None),
            ),
            parent_action_intent_id,
        )

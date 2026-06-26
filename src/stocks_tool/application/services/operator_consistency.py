from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from stocks_tool.application.services.bull_put_strategy import ACTIVE_SPREAD_STATUSES, BullPutStrategyService
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.application.services.strategy_lifecycle import bull_put_close_order_warning
from stocks_tool.domain.enums import (
    AssetType,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    SpreadStatus,
    StrategyProposalStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    BullPutSpread,
    CreateStrategyAuditEventRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    OperatorConsistencyCheck,
    OperatorConsistencyRepairRequest,
    OperatorConsistencyRepairResult,
    OperatorConsistencySummary,
    Order,
    StrategyProposal,
    StrategyRun,
    StrategySignal,
)
from stocks_tool.ports.repository import StrategyAuditEventRepository


ZERO_DTE_STRATEGY_ID = "zero_dte_lottery_v1"
COVERED_CALL_STRATEGY_ID = "covered_call_v1"
BULL_PUT_STRATEGY_ID = "paper_bull_put_v1"
ZERO_DTE_MANUAL_SCAN_REPAIR_PREFIX = "zero-dte-ledger"
ZERO_DTE_MAX_PREMIUM = Decimal("150")


class OperatorConsistencyService:
    def __init__(
        self,
        *,
        strategy_experiments: StrategyExperimentService,
        bull_put_strategy: BullPutStrategyService,
        order_service: OrderService,
        audit_events: StrategyAuditEventRepository | None = None,
    ) -> None:
        self.strategy_experiments = strategy_experiments
        self.bull_put_strategy = bull_put_strategy
        self.order_service = order_service
        self.audit_events = audit_events

    def get_summary(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        strategy: str | None = None,
        limit: int = 50,
    ) -> OperatorConsistencySummary:
        generated_at = datetime.now(timezone.utc)
        effective_limit = max(1, min(int(limit), 200))
        strategy_filter = strategy.strip() if strategy else None
        orders = [
            order
            for order in self.order_service.list_orders(external_account_id=external_account_id)
            if order.mode == mode
        ]
        checks: list[OperatorConsistencyCheck] = []
        if strategy_filter in (None, ZERO_DTE_STRATEGY_ID):
            checks.extend(
                self._zero_dte_manual_scan_checks(
                    external_account_id=external_account_id,
                    mode=mode,
                    orders=orders,
                    checked_at=generated_at,
                    limit=effective_limit,
                )
            )
        if strategy_filter in (None, COVERED_CALL_STRATEGY_ID):
            checks.extend(
                self._covered_call_order_linkage_checks(
                    external_account_id=external_account_id,
                    mode=mode,
                    checked_at=generated_at,
                    limit=effective_limit,
                )
            )
        if strategy_filter in (None, BULL_PUT_STRATEGY_ID):
            checks.extend(
                self._bull_put_lifecycle_drift_checks(
                    external_account_id=external_account_id,
                    mode=mode,
                    orders=orders,
                    checked_at=generated_at,
                    limit=effective_limit,
                )
            )
        checks = checks[:effective_limit]
        fail_count = sum(1 for check in checks if check.status == "fail")
        warn_count = sum(1 for check in checks if check.status == "warn")
        pass_count = sum(1 for check in checks if check.status == "pass")
        status = "fail" if fail_count else "warn" if warn_count else "pass"
        return OperatorConsistencySummary(
            generated_at=generated_at,
            external_account_id=external_account_id,
            mode=mode,
            strategy=strategy_filter,
            limit=effective_limit,
            status=status,
            check_count=len(checks),
            pass_count=pass_count,
            warn_count=warn_count,
            fail_count=fail_count,
            repair_available_count=sum(1 for check in checks if check.repair_available),
            checks=checks,
        )

    def apply_repair(
        self,
        repair_id: str,
        request: OperatorConsistencyRepairRequest,
    ) -> OperatorConsistencyRepairResult:
        if request.mode != ExecutionMode.PAPER:
            raise ValueError("Consistency repairs are paper-only.")
        if not request.confirm_local_repair:
            raise ValueError("Set confirm_local_repair=true to apply a local ledger repair.")
        order_id = self._parse_zero_dte_repair_id(repair_id)
        order = self.order_service.get_order(order_id)
        if order is None:
            raise LookupError(f"Order '{order_id}' was not found.")
        if order.external_account_id != request.external_account_id:
            raise ValueError("Repair account does not match the local order account.")
        if order.mode != request.mode:
            raise ValueError("Repair mode does not match the local order mode.")
        brief = self._zero_dte_manual_scan_order_brief(order)
        if brief is None:
            raise ValueError(f"Order '{order_id}' is not an eligible zero-DTE manual-scan paper order.")

        runs = self.strategy_experiments.list_runs(
            external_account_id=request.external_account_id,
            strategy_id=ZERO_DTE_STRATEGY_ID,
            limit=200,
        )
        signals = self.strategy_experiments.list_signals(
            external_account_id=request.external_account_id,
            strategy_id=ZERO_DTE_STRATEGY_ID,
            limit=200,
        )
        run = self._find_zero_dte_run_for_order(runs, order_id=order.id)
        signal = self._find_zero_dte_execution_signal(signals, run=run, order_id=order.id)
        if run is not None and signal is not None:
            check = self._zero_dte_check_for_order(
                external_account_id=request.external_account_id,
                mode=request.mode,
                order=order,
                run=run,
                signal=signal,
                checked_at=datetime.now(timezone.utc),
            )
            return OperatorConsistencyRepairResult(
                repair_id=repair_id,
                repaired=False,
                status="already_repaired",
                message="Zero-DTE manual-scan order already has local run and signal records.",
                check=check,
            )

        now = datetime.now(timezone.utc)
        created_run: StrategyRun | None = None
        created_signal: StrategySignal | None = None
        symbol = self._zero_dte_underlying_symbol(order) or brief.get("underlying_symbol") or order.symbol
        if run is None:
            created_run = self.strategy_experiments.create_run(
                CreateStrategyRunRequest(
                    strategy_id=ZERO_DTE_STRATEGY_ID,
                    external_account_id=request.external_account_id,
                    mode=request.mode,
                    run_type="manual_scan_reconcile",
                    status=StrategyRunStatus.EXECUTED,
                    symbol=str(symbol),
                    order_id=order.id,
                    started_at=order.submitted_at or order.created_at,
                    completed_at=now,
                    summary=f"Reconciled zero-DTE manual-scan paper order {order.symbol}.",
                    metrics_payload={
                        "source": "/ops/consistency/repairs",
                        "repair_id": repair_id,
                        "actor": request.actor,
                        "note": request.note,
                        "reconciled_order": order.model_dump(mode="json"),
                    },
                )
            )
            run = created_run
        if signal is None:
            created_signal = self.strategy_experiments.create_signal(
                CreateStrategySignalRequest(
                    strategy_id=ZERO_DTE_STRATEGY_ID,
                    external_account_id=request.external_account_id,
                    mode=request.mode,
                    signal_type=StrategySignalType.EXECUTION,
                    symbol=str(symbol),
                    run_id=run.id if run else None,
                    strength=Decimal("0.20"),
                    summary=f"Reconciled zero-DTE paper order {order.symbol}.",
                    detail="Local consistency repair for a manual force-scan paper order.",
                    source=ZERO_DTE_STRATEGY_ID,
                    signal_payload={
                        "source": "/ops/consistency/repairs",
                        "repair_id": repair_id,
                        "reconciled_order": order.model_dump(mode="json"),
                    },
                    emitted_at=now,
                )
            )
            signal = created_signal

        self._append_repair_audit_event(
            request=request,
            repair_id=repair_id,
            order=order,
            run=run,
            signal=signal,
        )
        check = self._zero_dte_check_for_order(
            external_account_id=request.external_account_id,
            mode=request.mode,
            order=order,
            run=run,
            signal=signal,
            checked_at=now,
        )
        return OperatorConsistencyRepairResult(
            repair_id=repair_id,
            repaired=True,
            status="repaired",
            message="Local zero-DTE strategy run/signal ledger records were repaired. No broker order was submitted.",
            check=check,
            created_run=created_run,
            created_signal=created_signal,
            local_repair_executed=True,
        )

    def _zero_dte_manual_scan_checks(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        orders: list[Order],
        checked_at: datetime,
        limit: int,
    ) -> list[OperatorConsistencyCheck]:
        runs = self.strategy_experiments.list_runs(
            external_account_id=external_account_id,
            strategy_id=ZERO_DTE_STRATEGY_ID,
            limit=max(100, limit),
        )
        signals = self.strategy_experiments.list_signals(
            external_account_id=external_account_id,
            strategy_id=ZERO_DTE_STRATEGY_ID,
            limit=max(100, limit),
        )
        manual_scan_orders = [
            order for order in orders if self._zero_dte_manual_scan_order_brief(order) is not None
        ][:limit]
        if not manual_scan_orders:
            return [
                self._check(
                    checked_at=checked_at,
                    external_account_id=external_account_id,
                    mode=mode,
                    strategy=ZERO_DTE_STRATEGY_ID,
                    status="pass",
                    reason_code="zero_dte_manual_scan_ledger_clean",
                    summary="No zero-DTE manual-scan paper order requires local ledger repair.",
                    recommended_action="No operator action required.",
                )
            ]
        return [
            self._zero_dte_check_for_order(
                external_account_id=external_account_id,
                mode=mode,
                order=order,
                run=self._find_zero_dte_run_for_order(runs, order_id=order.id),
                signal=self._find_zero_dte_execution_signal(
                    signals,
                    run=self._find_zero_dte_run_for_order(runs, order_id=order.id),
                    order_id=order.id,
                ),
                checked_at=checked_at,
            )
            for order in manual_scan_orders
        ]

    def _covered_call_order_linkage_checks(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        checked_at: datetime,
        limit: int,
    ) -> list[OperatorConsistencyCheck]:
        proposals = [
            proposal
            for proposal in self.strategy_experiments.list_proposals(
                external_account_id=external_account_id,
                strategy_id=COVERED_CALL_STRATEGY_ID,
                limit=max(100, limit),
            )
            if proposal.mode == mode
        ]
        runs = [
            run
            for run in self.strategy_experiments.list_runs(
                external_account_id=external_account_id,
                strategy_id=COVERED_CALL_STRATEGY_ID,
                limit=max(100, limit),
            )
            if run.mode == mode
        ]
        executed = [
            proposal
            for proposal in proposals
            if proposal.status in {
                StrategyProposalStatus.EXECUTED,
                StrategyProposalStatus.CLOSED,
                StrategyProposalStatus.ROLLED,
            }
        ]
        missing = [
            proposal
            for proposal in executed
            if not self._covered_call_has_order_link(proposal=proposal, runs=runs)
        ][:limit]
        if not missing:
            return [
                self._check(
                    checked_at=checked_at,
                    external_account_id=external_account_id,
                    mode=mode,
                    strategy=COVERED_CALL_STRATEGY_ID,
                    status="pass",
                    reason_code="covered_call_order_linkage_clean",
                    summary="Covered-call executed proposals have observable order linkage.",
                    recommended_action="No operator action required.",
                    related_proposal_ids=[proposal.id for proposal in executed[: min(5, len(executed))]],
                )
            ]
        return [
            self._check(
                checked_at=checked_at,
                external_account_id=external_account_id,
                mode=mode,
                strategy=COVERED_CALL_STRATEGY_ID,
                status="warn",
                reason_code="covered_call_order_linkage_missing",
                summary=f"Covered-call proposal {proposal.id} is {proposal.status.value} but has no local order linkage.",
                detail="Review covered-call lifecycle runs before treating this proposal as fully reconciled.",
                related_proposal_ids=[proposal.id],
                recommended_action="Inspect covered-call activity and related strategy runs; do not submit a new order from this report.",
            )
            for proposal in missing
        ]

    def _bull_put_lifecycle_drift_checks(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        orders: list[Order],
        checked_at: datetime,
        limit: int,
    ) -> list[OperatorConsistencyCheck]:
        spreads = [
            spread
            for spread in self.bull_put_strategy.list_spreads(external_account_id=external_account_id)
            if spread.mode == mode
        ]
        orders_by_id = self._orders_by_id(orders)
        drifted: list[tuple[BullPutSpread, dict[str, Any]]] = []
        for spread in spreads:
            if spread.status not in ACTIVE_SPREAD_STATUSES and spread.status != SpreadStatus.OPEN:
                continue
            linked_order = orders_by_id.get(str(spread.short_exit_order_id))
            warning = bull_put_close_order_warning(
                spread_status=spread.status,
                short_exit_order_id=spread.short_exit_order_id,
                short_exit_order_status=(linked_order or {}).get("status") or spread.latest_close_order_status,
                short_symbol=spread.short_symbol,
                raw_payload=spread.raw_payload,
                exit_reason=spread.exit_reason,
                orders_by_id=orders_by_id,
                latest_monitor_should_close=spread.latest_monitor_should_close,
                lifecycle_warning_code=spread.lifecycle_warning_code,
                manual_action_required=spread.manual_action_required,
            )
            if warning is None:
                continue
            if spread.lifecycle_warning_code != warning["code"] or not spread.manual_action_required:
                drifted.append((spread, warning))
        if not drifted:
            return [
                self._check(
                    checked_at=checked_at,
                    external_account_id=external_account_id,
                    mode=mode,
                    strategy=BULL_PUT_STRATEGY_ID,
                    status="pass",
                    reason_code="bull_put_lifecycle_warning_clean",
                    summary="Bull put close-order lifecycle warnings are consistent with linked order state.",
                    recommended_action="No operator action required.",
                )
            ]
        return [
            self._check(
                checked_at=checked_at,
                external_account_id=external_account_id,
                mode=mode,
                strategy=BULL_PUT_STRATEGY_ID,
                status="warn",
                reason_code="bull_put_lifecycle_warning_drift",
                summary=f"Bull put spread {spread.id} has close-order warning drift.",
                detail=str(warning.get("detail") or "Lifecycle warning fields do not match the canonical close-order warning."),
                related_order_ids=[str(spread.short_exit_order_id)] if spread.short_exit_order_id else [],
                related_spread_ids=[spread.id],
                recommended_action="Use recover-close eligibility before considering any paper recovery order.",
                payload={"warning": warning},
            )
            for spread, warning in drifted[:limit]
        ]

    def _zero_dte_check_for_order(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        order: Order,
        run: StrategyRun | None,
        signal: StrategySignal | None,
        checked_at: datetime,
    ) -> OperatorConsistencyCheck:
        run_found = run is not None
        signal_found = signal is not None
        if run_found and signal_found:
            return self._check(
                checked_at=checked_at,
                external_account_id=external_account_id,
                mode=mode,
                strategy=ZERO_DTE_STRATEGY_ID,
                status="pass",
                reason_code="zero_dte_manual_scan_ledger_recorded",
                summary=f"Zero-DTE manual-scan paper order {order.id} has local run and signal records.",
                related_order_ids=[order.id],
                related_run_ids=[run.id],
                related_signal_ids=[signal.id],
                recommended_action="No operator action required.",
                payload={"order_symbol": order.symbol, "order_status": order.status.value},
            )
        missing = []
        if not run_found:
            missing.append("run")
        if not signal_found:
            missing.append("signal")
        return self._check(
            checked_at=checked_at,
            external_account_id=external_account_id,
            mode=mode,
            strategy=ZERO_DTE_STRATEGY_ID,
            status="fail",
            reason_code="zero_dte_strategy_recording_missing",
            summary=f"Zero-DTE manual-scan paper order {order.id} is missing local {'/'.join(missing)} evidence.",
            detail="This is a local ledger consistency issue only; repair must not submit another broker order.",
            repair_available=True,
            repair_id=f"{ZERO_DTE_MANUAL_SCAN_REPAIR_PREFIX}:{order.id}",
            related_order_ids=[order.id],
            related_run_ids=[run.id] if run else [],
            related_signal_ids=[signal.id] if signal else [],
            recommended_action="Run the guarded local repair if this order is confirmed as the intended manual force-scan evidence.",
            payload={"order_symbol": order.symbol, "order_status": order.status.value, "missing": missing},
        )

    @staticmethod
    def _check(
        *,
        checked_at: datetime,
        external_account_id: str,
        mode: ExecutionMode,
        strategy: str | None,
        status: str,
        reason_code: str,
        summary: str,
        detail: str | None = None,
        repair_available: bool = False,
        repair_id: str | None = None,
        related_order_ids: list[str] | None = None,
        related_run_ids: list[str] | None = None,
        related_signal_ids: list[str] | None = None,
        related_proposal_ids: list[str] | None = None,
        related_spread_ids: list[str] | None = None,
        recommended_action: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> OperatorConsistencyCheck:
        key_parts = [
            strategy or "operator",
            reason_code,
            *(related_order_ids or []),
            *(related_run_ids or []),
            *(related_signal_ids or []),
            *(related_proposal_ids or []),
            *(related_spread_ids or []),
        ]
        return OperatorConsistencyCheck(
            id=":".join(str(part) for part in key_parts if part),
            checked_at=checked_at,
            external_account_id=external_account_id,
            mode=mode,
            strategy=strategy,
            status=status,
            reason_code=reason_code,
            summary=summary,
            detail=detail,
            repair_available=repair_available,
            repair_id=repair_id,
            related_order_ids=related_order_ids or [],
            related_run_ids=related_run_ids or [],
            related_signal_ids=related_signal_ids or [],
            related_proposal_ids=related_proposal_ids or [],
            related_spread_ids=related_spread_ids or [],
            recommended_action=recommended_action,
            payload=payload or {},
        )

    @staticmethod
    def _find_zero_dte_run_for_order(runs: list[StrategyRun], *, order_id: str) -> StrategyRun | None:
        return next((run for run in runs if run.order_id == order_id), None)

    @staticmethod
    def _find_zero_dte_execution_signal(
        signals: list[StrategySignal],
        *,
        run: StrategyRun | None,
        order_id: str,
    ) -> StrategySignal | None:
        run_id = run.id if run else None
        for signal in signals:
            if signal.signal_type != StrategySignalType.EXECUTION:
                continue
            payload = signal.signal_payload or {}
            reconciled_order = payload.get("reconciled_order") if isinstance(payload, dict) else None
            payload_order = payload.get("order") if isinstance(payload, dict) else None
            if run_id is not None and signal.run_id == run_id:
                return signal
            if isinstance(reconciled_order, Mapping) and reconciled_order.get("id") == order_id:
                return signal
            if isinstance(payload_order, Mapping) and payload_order.get("id") == order_id:
                return signal
        return None

    @staticmethod
    def _covered_call_has_order_link(*, proposal: StrategyProposal, runs: list[StrategyRun]) -> bool:
        for run in runs:
            if run.proposal_id != proposal.id:
                continue
            if run.order_id:
                return True
            if _payload_has_order_id(run.raw_payload) or _payload_has_order_id(run.metrics_payload):
                return True
        return _payload_has_order_id(proposal.candidate_payload) or _payload_has_order_id(proposal.risk_payload)

    @staticmethod
    def _zero_dte_manual_scan_order_brief(order: Order) -> dict[str, Any] | None:
        raw_payload = _mapping(order.raw_payload)
        submission = _mapping(raw_payload.get("submission_request"))
        if not str(submission.get("remark") or "").startswith(f"{ZERO_DTE_STRATEGY_ID}:manual-scan"):
            return None
        if order.mode != ExecutionMode.PAPER:
            return None
        if order.side != OrderSide.BUY or order.asset_type != AssetType.OPTION:
            return None
        if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
            return None
        premium_at_limit = _premium_at_limit(order)
        if premium_at_limit is not None and premium_at_limit > ZERO_DTE_MAX_PREMIUM:
            return None
        return {
            "id": order.id,
            "symbol": order.symbol,
            "underlying_symbol": OperatorConsistencyService._zero_dte_underlying_symbol(order),
            "premium_at_limit": str(premium_at_limit) if premium_at_limit is not None else None,
        }

    @staticmethod
    def _zero_dte_underlying_symbol(order: Order) -> str | None:
        if order.option_contract is not None:
            return order.option_contract.underlying_symbol
        raw_payload = _mapping(order.raw_payload)
        submission = _mapping(raw_payload.get("submission_request"))
        option_contract = _mapping(submission.get("option_contract"))
        value = option_contract.get("underlying_symbol")
        return str(value) if value else None

    @staticmethod
    def _orders_by_id(orders: list[Order]) -> dict[str, dict[str, Any]]:
        return {
            order.id: {
                "status": order.status.value,
                "symbol": order.symbol,
                "side": order.side.value,
            }
            for order in orders
        }

    @staticmethod
    def _parse_zero_dte_repair_id(repair_id: str) -> str:
        prefix = f"{ZERO_DTE_MANUAL_SCAN_REPAIR_PREFIX}:"
        if not repair_id.startswith(prefix):
            raise LookupError(f"Repair '{repair_id}' is not recognized.")
        order_id = repair_id[len(prefix) :].strip()
        if not order_id:
            raise LookupError(f"Repair '{repair_id}' does not include an order id.")
        return order_id

    def _append_repair_audit_event(
        self,
        *,
        request: OperatorConsistencyRepairRequest,
        repair_id: str,
        order: Order,
        run: StrategyRun | None,
        signal: StrategySignal | None,
    ) -> None:
        if self.audit_events is None:
            return
        try:
            self.audit_events.create_event(
                CreateStrategyAuditEventRequest(
                    external_account_id=request.external_account_id,
                    mode=request.mode,
                    actor=request.actor,
                    source="operator_consistency",
                    strategy=ZERO_DTE_STRATEGY_ID,
                    action="local_ledger_repair",
                    after={
                        "repair_id": repair_id,
                        "run_id": run.id if run else None,
                        "signal_id": signal.id if signal else None,
                    },
                    order_ids=[order.id],
                    run_id=run.id if run else None,
                    summary="Local zero-DTE ledger repair recorded.",
                    detail=request.note,
                    payload={
                        "repair_id": repair_id,
                        "local_repair_only": True,
                        "broker_order_submitted": False,
                    },
                )
            )
        except Exception:
            return


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _payload_has_order_id(payload: Any) -> bool:
    if not isinstance(payload, Mapping):
        return False
    for key, value in payload.items():
        if key.endswith("order_id") and value:
            return True
        if key in {"order", "sell_order", "close_order", "buyback_order"} and isinstance(value, Mapping):
            if value.get("id") or value.get("order_id"):
                return True
        if isinstance(value, Mapping) and _payload_has_order_id(value):
            return True
        if isinstance(value, list) and any(_payload_has_order_id(item) for item in value):
            return True
    return False


def _premium_at_limit(order: Order) -> Decimal | None:
    if order.limit_price is None:
        return None
    try:
        return (Decimal(str(order.quantity)) * Decimal(str(order.limit_price)) * Decimal("100")).quantize(
            Decimal("0.01")
        )
    except (InvalidOperation, ValueError):
        return None

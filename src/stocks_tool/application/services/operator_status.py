from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stocks_tool.application.services.bull_put_strategy import ACTIVE_SPREAD_STATUSES, BullPutStrategyService
from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.application.services.strategy_lifecycle import bull_put_close_order_warning
from stocks_tool.application.services.zero_dte_lottery_strategy import ZeroDteLotteryStrategyService
from stocks_tool.domain.enums import BrokerName, ExecutionMode, OrderStatus, SchedulerJobRunStatus
from stocks_tool.domain.models import (
    BrokerProfile,
    BullPutSpread,
    Order,
    OperatorLifecycleWarning,
    OperatorStatusCheck,
    OperatorStatusSnapshot,
    PaperMandate,
    SchedulerJobSummary,
    SchedulerJobRun,
    SchedulerStatusSnapshot,
    StrategyAuditEvent,
    StrategyAuditSummary,
    StrategyAuditSummaryGroup,
    StrategyControlSnapshot,
)
from stocks_tool.ports.broker_gateway import BrokerAccountGateway
from stocks_tool.ports.repository import SchedulerJobRunRepository, StrategyAuditEventRepository


OPEN_ORDER_STATUSES = {
    OrderStatus.CREATED,
    OrderStatus.SUBMITTED,
    OrderStatus.PARTIALLY_FILLED,
}

SCHEDULER_PROBLEM_STATUSES = {SchedulerJobRunStatus.FAILED, SchedulerJobRunStatus.BACKOFF}

OPERATOR_REASON_CODE_DETAILS = {
    "degraded_broker": "Broker profile or credentials are degraded for the selected paper account.",
    "scheduler_backoff": "A scheduler job is backing off after a broker or local workflow failure.",
    "manual_pause": "Paper mandate has a manual pause active.",
    "kill_switch": "Paper mandate kill switch is active.",
    "advisor_pending_record": "Advisor output is pending an explicit Record Output action.",
    "manual_action_required": "A strategy lifecycle item requires manual operator recovery.",
    "operator_audit_summary_unavailable": "Operator audit summary is unavailable.",
}


def order_lifecycle_lookup(orders: list[Order]) -> dict[str, dict]:
    return {
        order.id: {
            "status": order.status.value,
            "symbol": order.symbol,
            "side": order.side.value,
        }
        for order in orders
    }


def bull_put_lifecycle_warnings(
    *,
    spreads: list[BullPutSpread],
    orders_by_id: dict[str, dict],
) -> list[OperatorLifecycleWarning]:
    warnings: list[OperatorLifecycleWarning] = []
    for spread in spreads:
        lifecycle = (spread.raw_payload or {}).get("lifecycle") or {}
        linked_order = orders_by_id.get(str(spread.short_exit_order_id))
        lifecycle_warning_code = spread.lifecycle_warning_code or lifecycle.get("warning")
        manual_action_required = spread.manual_action_required or lifecycle.get("manual_action_required") is True
        short_exit_order_status = (
            (linked_order or {}).get("status")
            or spread.latest_close_order_status
            or lifecycle.get("close_order_state")
        )
        warning_payload = bull_put_close_order_warning(
            spread_status=spread.status,
            short_exit_order_id=spread.short_exit_order_id,
            short_exit_order_status=short_exit_order_status,
            short_symbol=spread.short_symbol,
            raw_payload=spread.raw_payload,
            exit_reason=spread.exit_reason,
            orders_by_id=orders_by_id,
            latest_monitor_should_close=spread.latest_monitor_should_close,
            lifecycle_warning_code=lifecycle_warning_code,
            manual_action_required=manual_action_required,
        )
        if warning_payload is None and not manual_action_required:
            continue
        warning_payload = warning_payload or {
            "code": str(lifecycle_warning_code or "manual_action_required"),
            "message": "Strategy lifecycle manual action required",
            "detail": lifecycle.get("detail"),
            "manual_action_required": True,
        }
        warnings.append(
            OperatorLifecycleWarning(
                strategy_id=spread.strategy_id,
                code=str(warning_payload["code"]),
                message=str(warning_payload["message"]),
                detail=warning_payload.get("detail"),
                manual_action_required=bool(warning_payload.get("manual_action_required")),
                record_id=spread.id,
                context={
                    "spread_status": spread.status.value,
                    "short_exit_order_id": spread.short_exit_order_id,
                    "short_exit_order_status": warning_payload.get("order_status")
                    or short_exit_order_status,
                    "exit_reason": warning_payload.get("exit_reason") or lifecycle.get("exit_reason") or spread.exit_reason,
                },
            )
        )
    return warnings


def scheduler_job_summaries(runs: list[SchedulerJobRun]) -> list[SchedulerJobSummary]:
    grouped: dict[tuple[str, str | None], list[SchedulerJobRun]] = {}
    for run in runs:
        grouped.setdefault((run.job_key, run.external_account_id), []).append(run)

    summaries: list[SchedulerJobSummary] = []
    for group_runs in grouped.values():
        ordered = sorted(group_runs, key=lambda run: run.started_at, reverse=True)
        latest = ordered[0]
        problem_runs = [run for run in ordered if run.status in SCHEDULER_PROBLEM_STATUSES]
        recent_problem_count = len(problem_runs)
        posture, due_status, status_detail = scheduler_summary_status_detail(
            latest=latest,
            recent_problem_count=recent_problem_count,
        )
        summaries.append(
            SchedulerJobSummary(
                job_key=latest.job_key,
                job_label=latest.job_label,
                external_account_id=latest.external_account_id,
                posture=posture,
                due_status=due_status,
                status_detail=status_detail,
                last_status=latest.status,
                last_started_at=latest.started_at,
                last_completed_at=latest.completed_at,
                next_attempt_at=latest.next_attempt_at,
                backoff_seconds=latest.backoff_seconds,
                consecutive_failures=latest.consecutive_failures,
                error_message=latest.error_message,
                detail=latest.detail,
                last_problem_at=problem_runs[0].started_at if problem_runs else None,
                recent_run_count=len(ordered),
                recent_problem_count=recent_problem_count,
            )
        )
    return sorted(summaries, key=lambda summary: summary.last_started_at, reverse=True)


def scheduler_summary_status_detail(
    *,
    latest: SchedulerJobRun,
    recent_problem_count: int,
) -> tuple[str, str, str]:
    latest_detail = latest.error_message or latest.detail
    if latest.status == SchedulerJobRunStatus.FAILED:
        return (
            "fail",
            "failed",
            latest_detail or "Last scheduler run failed without a recorded detail.",
        )
    if latest.status == SchedulerJobRunStatus.BACKOFF:
        next_attempt = (
            f"; next attempt at {latest.next_attempt_at.isoformat()}"
            if latest.next_attempt_at is not None
            else ""
        )
        failure_count = (
            f" after {latest.consecutive_failures} consecutive failure(s)"
            if latest.consecutive_failures
            else ""
        )
        reason = f": {latest_detail}" if latest_detail else "."
        return (
            "warn",
            "backoff",
            f"Backoff active{failure_count}{next_attempt}{reason}",
        )
    if latest.status == SchedulerJobRunStatus.SKIPPED:
        if latest.next_attempt_at is not None or latest.consecutive_failures:
            next_attempt = (
                f"; next attempt at {latest.next_attempt_at.isoformat()}"
                if latest.next_attempt_at is not None
                else ""
            )
            return (
                "warn",
                "backoff_skip",
                latest_detail or f"Skipped while backoff is active{next_attempt}.",
            )
        posture = "warn" if recent_problem_count else "pass"
        detail = latest_detail or "No scheduler work was due on the last pass."
        return posture, "not_due", detail

    posture = "warn" if recent_problem_count else "pass"
    if recent_problem_count:
        return (
            posture,
            "recovered",
            f"Last run succeeded, with {recent_problem_count} recent problem run(s) still in the window.",
        )
    return "pass", "healthy", latest_detail or "Last scheduler run succeeded."


class OperatorStatusService:
    def __init__(
        self,
        *,
        strategy_experiments: StrategyExperimentService,
        bull_put_strategy: BullPutStrategyService,
        zero_dte_lottery_strategy: ZeroDteLotteryStrategyService,
        order_service: OrderService,
        scheduler_job_runs: SchedulerJobRunRepository | None = None,
        audit_events: StrategyAuditEventRepository | None = None,
        broker_adapter: BrokerAccountGateway | None = None,
    ) -> None:
        self.strategy_experiments = strategy_experiments
        self.bull_put_strategy = bull_put_strategy
        self.zero_dte_lottery_strategy = zero_dte_lottery_strategy
        self.order_service = order_service
        self.scheduler_job_runs = scheduler_job_runs
        self.audit_events = audit_events
        self.broker_adapter = broker_adapter

    def get_unattended_status(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> OperatorStatusSnapshot:
        generated_at = datetime.now(timezone.utc)
        checks: list[OperatorStatusCheck] = []
        controls = self.strategy_experiments.get_control_snapshot(external_account_id=external_account_id)
        recent_scheduler_runs = self._recent_scheduler_runs(external_account_id=external_account_id, limit=20)
        recent_scheduler_summaries = scheduler_job_summaries(recent_scheduler_runs)
        bull_put_runtime = None
        zero_dte_runtime = None
        spreads: list[BullPutSpread] = []
        orders = self.order_service.list_orders(external_account_id=external_account_id)

        self._add_check(
            checks,
            name="paper_first_controls",
            status="pass" if controls.paper_execution_allowed and not controls.live_execution_allowed else "fail",
            detail=(
                "Paper execution is allowed and live execution is blocked."
                if controls.paper_execution_allowed and not controls.live_execution_allowed
                else "Paper/live execution boundaries are not in the expected unattended posture."
            ),
            reason_code=(
                "paper_first_controls_ok"
                if controls.paper_execution_allowed and not controls.live_execution_allowed
                else "live_boundary_not_blocked"
            ),
            severity="info" if controls.paper_execution_allowed and not controls.live_execution_allowed else "critical",
        )
        scheduler_problem_count = sum(summary.recent_problem_count for summary in recent_scheduler_summaries)
        if recent_scheduler_runs:
            summary_postures = {summary.posture for summary in recent_scheduler_summaries}
            if "fail" in summary_postures:
                scheduler_status = "fail"
            elif "warn" in summary_postures or scheduler_problem_count:
                scheduler_status = "warn"
            else:
                scheduler_status = "pass"
            scheduler_detail = self._scheduler_check_detail(
                summaries=recent_scheduler_summaries,
                problem_count=scheduler_problem_count,
            )
        else:
            scheduler_status = "warn" if controls.scheduler_enabled else "pass"
            scheduler_detail = (
                "Scheduler is enabled but no durable job-run observations have been recorded yet."
                if controls.scheduler_enabled
                else "Scheduler is disabled and no durable job-run observations are expected."
            )
        self._add_check(
            checks,
            name="scheduler_recent_runs",
            status=scheduler_status,
            detail=scheduler_detail,
            reason_code=self._scheduler_reason_code(
                scheduler_status=scheduler_status,
                controls_scheduler_enabled=controls.scheduler_enabled,
                summaries=recent_scheduler_summaries,
            ),
            severity=self._status_severity(scheduler_status),
        )
        self._add_check(
            checks,
            name="llm_execution_boundary",
            status="pass" if not controls.llm_direct_execution_allowed else "fail",
            detail=(
                "Advisor output cannot directly execute broker orders."
                if not controls.llm_direct_execution_allowed
                else "Advisor direct execution is enabled."
            ),
            reason_code="advisor_read_only" if not controls.llm_direct_execution_allowed else "advisor_direct_execution_enabled",
            severity="info" if not controls.llm_direct_execution_allowed else "critical",
        )
        self._add_check(
            checks,
            name="scheduler_configured",
            status="pass" if controls.scheduler_enabled else "warn",
            detail=(
                "In-process scheduler is enabled by configuration."
                if controls.scheduler_enabled
                else "In-process scheduler is disabled; unattended monitoring requires manual scripts."
            ),
            reason_code="scheduler_enabled" if controls.scheduler_enabled else "scheduler_disabled",
            severity="info" if controls.scheduler_enabled else "warning",
        )

        try:
            bull_put_runtime = self.bull_put_strategy.get_runtime_state(
                external_account_id=external_account_id,
                mode=mode,
            )
            if bull_put_runtime.kill_switch_active:
                runtime_status = "fail"
                runtime_detail = "Bull put kill switch is active."
                runtime_reason_code = "kill_switch"
            elif bull_put_runtime.manual_pause:
                runtime_status = "warn"
                runtime_detail = "Bull put new entries are manually paused; existing spreads may still be monitored."
                runtime_reason_code = "manual_pause"
            elif not bull_put_runtime.auto_entry_enabled:
                runtime_status = "warn"
                runtime_detail = "Bull put auto-entry is disabled; this is expected for conservative unattended posture."
                runtime_reason_code = "bull_put_auto_entry_disabled"
            else:
                runtime_status = "pass"
                runtime_detail = "Bull put runtime controls allow configured automation."
                runtime_reason_code = "bull_put_runtime_ready"
            self._add_check(
                checks,
                name="bull_put_runtime",
                status=runtime_status,
                detail=runtime_detail,
                reason_code=runtime_reason_code,
                severity=self._status_severity(runtime_status),
            )
        except LookupError as exc:
            self._add_check(
                checks,
                name="bull_put_runtime",
                status="warn",
                detail=str(exc),
                reason_code="bull_put_runtime_missing",
                severity="warning",
            )

        try:
            zero_dte_runtime = self.zero_dte_lottery_strategy.get_runtime_state(
                external_account_id=external_account_id,
                mode=mode,
            )
            zero_status = "pass" if not zero_dte_runtime.auto_execute_enabled else "warn"
            zero_detail = (
                "Zero-DTE lottery auto-ordering is disabled."
                if not zero_dte_runtime.auto_execute_enabled
                else "Zero-DTE lottery auto-ordering is armed; verify this was intentional."
            )
            self._add_check(
                checks,
                name="zero_dte_lottery_runtime",
                status=zero_status,
                detail=zero_detail,
                reason_code=(
                    "zero_dte_auto_execute_disabled"
                    if not zero_dte_runtime.auto_execute_enabled
                    else "zero_dte_auto_execute_armed"
                ),
                severity=self._status_severity(zero_status),
            )
        except LookupError as exc:
            self._add_check(
                checks,
                name="zero_dte_lottery_runtime",
                status="warn",
                detail=str(exc),
                reason_code="zero_dte_runtime_missing",
                severity="warning",
            )

        try:
            spreads = self.bull_put_strategy.list_spreads(external_account_id=external_account_id)
        except LookupError as exc:
            self._add_check(
                checks,
                name="bull_put_spreads",
                status="warn",
                detail=str(exc),
                reason_code="bull_put_spreads_unavailable",
                severity="warning",
            )

        orders_by_id = order_lifecycle_lookup(orders)
        lifecycle_warnings = bull_put_lifecycle_warnings(spreads=spreads, orders_by_id=orders_by_id)
        self._add_check(
            checks,
            name="lifecycle_warnings",
            status="fail" if lifecycle_warnings else "pass",
            detail=(
                f"{len(lifecycle_warnings)} strategy lifecycle warning(s) require operator review."
                if lifecycle_warnings
                else "No strategy lifecycle warnings require manual action."
            ),
            reason_code="manual_action_required" if lifecycle_warnings else "no_manual_action_required",
            severity="critical" if lifecycle_warnings else "info",
        )

        open_order_count = sum(1 for order in orders if order.status in OPEN_ORDER_STATUSES)
        active_spread_count = sum(1 for spread in spreads if spread.status in ACTIVE_SPREAD_STATUSES)
        status = self._overall_status(checks)
        broker_profiles = self._broker_profiles(
            external_account_id=external_account_id,
            mode=mode,
        )
        paper_mandate = self._paper_mandate(
            controls=controls,
            bull_put_runtime=bull_put_runtime,
            zero_dte_runtime=zero_dte_runtime,
            external_account_id=external_account_id,
        )
        audit_events = self._combined_audit_events(
            external_account_id=external_account_id,
            mode=mode,
            orders=orders,
            scheduler_runs=recent_scheduler_runs,
            source=None,
            strategy=None,
            action=None,
            warning_only=False,
            since=None,
            limit=12,
        )
        return OperatorStatusSnapshot(
            external_account_id=external_account_id,
            mode=mode,
            generated_at=generated_at,
            status=status,
            ready_for_unattended=status != "fail",
            operator_posture_reason=self._posture_reason(checks),
            checks=checks,
            controls=controls,
            broker_profiles=broker_profiles,
            paper_mandate=paper_mandate,
            audit_events=audit_events,
            audit_summary=self._audit_summary(audit_events),
            bull_put_runtime=bull_put_runtime,
            zero_dte_lottery_runtime=zero_dte_runtime,
            active_bull_put_spread_count=active_spread_count,
            open_order_count=open_order_count,
            lifecycle_warnings=lifecycle_warnings,
            recent_scheduler_runs=recent_scheduler_runs,
            recent_scheduler_summaries=recent_scheduler_summaries,
        )

    def get_scheduler_status(
        self,
        *,
        external_account_id: str | None = None,
        limit: int = 50,
    ) -> SchedulerStatusSnapshot:
        runs = self._recent_scheduler_runs(external_account_id=external_account_id, limit=limit)
        return SchedulerStatusSnapshot(
            generated_at=datetime.now(timezone.utc),
            external_account_id=external_account_id,
            runs=runs,
            summaries=scheduler_job_summaries(runs),
        )

    def list_audit_events(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        source: str | None = None,
        strategy: str | None = None,
        action: str | None = None,
        warning_only: bool = False,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[StrategyAuditEvent]:
        scheduler_runs = self._recent_scheduler_runs(external_account_id=external_account_id, limit=limit)
        orders: list[Order] = []
        if external_account_id is not None:
            try:
                orders = self.order_service.list_orders(external_account_id=external_account_id)
            except LookupError:
                orders = []
        return self._combined_audit_events(
            external_account_id=external_account_id,
            mode=mode,
            orders=orders,
            scheduler_runs=scheduler_runs,
            source=source,
            strategy=strategy,
            action=action,
            warning_only=warning_only,
            since=since,
            limit=limit,
        )

    def get_audit_summary(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        since: datetime | None = None,
        limit: int = 200,
    ) -> StrategyAuditSummary:
        events = self.list_audit_events(
            external_account_id=external_account_id,
            mode=mode,
            since=since,
            limit=limit,
        )
        groups: dict[tuple, StrategyAuditSummaryGroup] = {}
        warning_count = 0
        for event in events:
            if event.warning_code:
                warning_count += 1
            key = (
                event.external_account_id,
                event.mode,
                event.source,
                event.action,
                event.strategy,
                event.warning_code,
                event.event_origin,
            )
            current = groups.get(key)
            if current is None:
                groups[key] = StrategyAuditSummaryGroup(
                    external_account_id=event.external_account_id,
                    mode=event.mode,
                    source=event.source,
                    action=event.action,
                    strategy=event.strategy,
                    warning_code=event.warning_code,
                    event_origin=event.event_origin,
                    count=1,
                    latest_emitted_at=event.emitted_at,
                )
                continue
            groups[key] = current.model_copy(
                update={
                    "count": current.count + 1,
                    "latest_emitted_at": max(current.latest_emitted_at, event.emitted_at),
                }
            )
        ordered_groups = sorted(
            groups.values(),
            key=lambda group: (group.latest_emitted_at, group.count),
            reverse=True,
        )
        return StrategyAuditSummary(
            generated_at=datetime.now(timezone.utc),
            external_account_id=external_account_id,
            mode=mode,
            since=since,
            limit=limit,
            event_count=len(events),
            warning_count=warning_count,
            groups=ordered_groups,
        )

    def _recent_scheduler_runs(
        self,
        *,
        external_account_id: str | None,
        limit: int,
    ) -> list[SchedulerJobRun]:
        if self.scheduler_job_runs is None:
            return []
        return self.scheduler_job_runs.list_runs(
            external_account_id=external_account_id,
            limit=limit,
        )

    def _combined_audit_events(
        self,
        *,
        external_account_id: str | None,
        mode: ExecutionMode | None,
        orders: list[Order],
        scheduler_runs: list[SchedulerJobRun],
        source: str | None,
        strategy: str | None,
        action: str | None,
        warning_only: bool,
        since: datetime | None,
        limit: int,
    ) -> list[StrategyAuditEvent]:
        events: list[StrategyAuditEvent] = []
        if self.audit_events is not None:
            try:
                events.extend(
                    self.audit_events.list_events(
                        external_account_id=external_account_id,
                        mode=mode,
                        source=source,
                        strategy=strategy,
                        action=action,
                        warning_only=warning_only,
                        since=since,
                        limit=limit,
                    )
                )
            except Exception:
                pass
        try:
            strategy_events = self.strategy_experiments.list_audit_events(
                external_account_id=external_account_id,
                limit=limit,
            )
            if isinstance(strategy_events, list):
                events.extend(strategy_events)
        except (AttributeError, LookupError):
            pass
        events.extend(self._audit_events_from_scheduler_runs(scheduler_runs))
        events.extend(self._audit_events_from_orders(orders, mode=mode))
        events = self._filter_audit_events(
            events,
            mode=mode,
            source=source,
            strategy=strategy,
            action=action,
            warning_only=warning_only,
            since=since,
        )
        events = self._dedupe_audit_events(events)
        return sorted(events, key=lambda event: event.emitted_at, reverse=True)[:limit]

    @staticmethod
    def _audit_events_from_scheduler_runs(runs: list[SchedulerJobRun]) -> list[StrategyAuditEvent]:
        events: list[StrategyAuditEvent] = []
        for run in runs:
            events.append(
                StrategyAuditEvent(
                    id=f"scheduler-{run.id}",
                    emitted_at=run.completed_at or run.started_at,
                    external_account_id=run.external_account_id,
                    actor="scheduler",
                    source="scheduler",
                    strategy=run.job_key,
                    action="scheduler_lifecycle_advance",
                    run_id=run.id,
                    warning_code=run.status.value if run.status in SCHEDULER_PROBLEM_STATUSES else None,
                    summary=run.detail or run.error_message,
                    detail=run.error_message,
                    payload={
                        "job_key": run.job_key,
                        "job_label": run.job_label,
                        "status": run.status.value,
                        "consecutive_failures": run.consecutive_failures,
                        "next_attempt_at": run.next_attempt_at.isoformat() if run.next_attempt_at else None,
                    },
                    event_origin="synthetic",
                )
            )
        return events

    @staticmethod
    def _audit_events_from_orders(
        orders: list[Order],
        *,
        mode: ExecutionMode | None,
    ) -> list[StrategyAuditEvent]:
        events: list[StrategyAuditEvent] = []
        for order in orders:
            events.append(
                StrategyAuditEvent(
                    id=f"order-{order.id}",
                    emitted_at=order.updated_at,
                    external_account_id=order.external_account_id,
                    mode=mode or order.mode,
                    actor="broker_gateway",
                    source="orders",
                    strategy="paper_order",
                    action="paper_order_state_observed",
                    order_ids=[order.id],
                    warning_code=(
                        f"order_{order.status.value}"
                        if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
                        else None
                    ),
                    summary=f"{order.symbol} {order.side.value} order is {order.status.value}.",
                    payload={
                        "symbol": order.symbol,
                        "side": order.side.value,
                        "status": order.status.value,
                        "external_order_id": order.external_order_id,
                    },
                    event_origin="synthetic",
                )
            )
        return events

    def _broker_profiles(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
    ) -> list[BrokerProfile]:
        if self.broker_adapter is not None:
            try:
                profile = self.broker_adapter.get_profile()
                return [
                    profile.model_copy(
                        update={
                            "external_account_id": external_account_id,
                            "mode": mode,
                        }
                    )
                ]
            except Exception:
                pass
        return [
            BrokerProfile(
                id=f"longbridge-{mode.value}-{external_account_id}",
                broker=BrokerName.LONGBRIDGE,
                name=BrokerName.LONGBRIDGE,
                external_account_id=external_account_id,
                mode=mode,
                supported_modes=[ExecutionMode.PAPER],
                readonly=False,
                paper_guard="config_declared",
                configured=False,
                credential_status="unknown",
                notes=["Profile was synthesized from local operator status inputs."],
            )
        ]

    @staticmethod
    def _paper_mandate(
        *,
        controls: StrategyControlSnapshot,
        bull_put_runtime: Any,
        zero_dte_runtime: Any,
        external_account_id: str,
    ) -> PaperMandate:
        mandate = controls.paper_mandate or PaperMandate(external_account_id=external_account_id)
        auto_switches = dict(mandate.auto_switches)
        manual_pause = mandate.manual_pause
        kill_switch = mandate.kill_switch
        if bull_put_runtime is not None:
            auto_switches["bull_put_auto_entry"] = bool(bull_put_runtime.auto_entry_enabled)
            manual_pause = bool(bull_put_runtime.manual_pause)
            kill_switch = bool(bull_put_runtime.kill_switch_active)
        if zero_dte_runtime is not None:
            auto_switches["zero_dte_auto_execute"] = bool(zero_dte_runtime.auto_execute_enabled)
        reason_codes = set(mandate.reason_codes)
        if manual_pause:
            reason_codes.add("manual_pause")
        if kill_switch:
            reason_codes.add("kill_switch")
        if zero_dte_runtime is not None and zero_dte_runtime.auto_execute_enabled:
            reason_codes.add("zero_dte_auto_execute_armed")
        severity = "critical" if kill_switch else "warning" if manual_pause else mandate.severity
        return mandate.model_copy(
            update={
                "external_account_id": external_account_id,
                "auto_switches": auto_switches,
                "manual_pause": manual_pause,
                "kill_switch": kill_switch,
                "reason_codes": sorted(reason_codes),
                "severity": severity,
            }
        )

    @staticmethod
    def _audit_summary(events: list[StrategyAuditEvent]) -> dict[str, Any]:
        by_action: dict[str, int] = {}
        warnings = 0
        for event in events:
            by_action[event.action] = by_action.get(event.action, 0) + 1
            if event.warning_code:
                warnings += 1
        return {
            "event_count": len(events),
            "warning_count": warnings,
            "by_action": by_action,
        }

    @staticmethod
    def _filter_audit_events(
        events: list[StrategyAuditEvent],
        *,
        mode: ExecutionMode | None,
        source: str | None,
        strategy: str | None,
        action: str | None,
        warning_only: bool,
        since: datetime | None,
    ) -> list[StrategyAuditEvent]:
        filtered: list[StrategyAuditEvent] = []
        for event in events:
            if mode is not None and event.mode is not None and event.mode != mode:
                continue
            if source is not None and event.source != source:
                continue
            if strategy is not None and event.strategy != strategy:
                continue
            if action is not None and event.action != action:
                continue
            if warning_only and not event.warning_code:
                continue
            if since is not None and event.emitted_at < since:
                continue
            filtered.append(event)
        return filtered

    @staticmethod
    def reason_code_detail(reason_code: str | None) -> str | None:
        if not reason_code:
            return None
        return OPERATOR_REASON_CODE_DETAILS.get(reason_code)

    @staticmethod
    def _dedupe_audit_events(events: list[StrategyAuditEvent]) -> list[StrategyAuditEvent]:
        priority = {"durable": 0, "synthetic": 1}
        ordered = sorted(events, key=lambda event: priority.get(event.event_origin or "synthetic", 2))
        seen: set[tuple] = set()
        deduped: list[StrategyAuditEvent] = []
        for event in ordered:
            key = OperatorStatusService._audit_dedupe_key(event)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)
        return deduped

    @staticmethod
    def _audit_dedupe_key(event: StrategyAuditEvent) -> tuple:
        identifiers = (
            event.proposal_id,
            event.run_id,
            tuple(sorted(event.order_ids)),
        )
        if any(identifiers):
            return (
                event.source,
                event.strategy,
                event.action,
                event.proposal_id,
                event.run_id,
                tuple(sorted(event.order_ids)),
            )
        return ("id", event.id)

    @staticmethod
    def _add_check(
        checks: list[OperatorStatusCheck],
        *,
        name: str,
        status: str,
        detail: str,
        reason_code: str | None = None,
        severity: str | None = None,
    ) -> None:
        checks.append(
            OperatorStatusCheck(
                name=name,
                status=status,
                detail=detail,
                reason_code=reason_code,
                severity=severity,
            )
        )

    @staticmethod
    def _status_severity(status: str) -> str:
        if status == "fail":
            return "critical"
        if status == "warn":
            return "warning"
        return "info"

    @staticmethod
    def _scheduler_reason_code(
        *,
        scheduler_status: str,
        controls_scheduler_enabled: bool,
        summaries: list[SchedulerJobSummary],
    ) -> str:
        if not summaries:
            return "scheduler_no_observations" if controls_scheduler_enabled else "scheduler_disabled"
        due_statuses = {summary.due_status for summary in summaries}
        if "backoff" in due_statuses or "backoff_skip" in due_statuses:
            return "scheduler_backoff"
        if scheduler_status == "fail":
            return "scheduler_failed"
        if scheduler_status == "warn":
            return "scheduler_degraded"
        return "scheduler_recent_runs_healthy"

    @staticmethod
    def _scheduler_check_detail(*, summaries: list[SchedulerJobSummary], problem_count: int) -> str:
        for posture in ("fail", "warn"):
            summary = next((item for item in summaries if item.posture == posture), None)
            if summary is not None and summary.status_detail:
                label = summary.job_label or summary.job_key
                return f"{label}: {summary.status_detail}"
        if problem_count:
            return f"{problem_count} recent scheduler run(s) failed or entered backoff."
        return "Recent scheduler job-run observations are available."

    @staticmethod
    def _posture_reason(checks: list[OperatorStatusCheck]) -> str:
        failing = next((check for check in checks if check.status == "fail"), None)
        if failing is not None:
            return failing.detail
        warning = next((check for check in checks if check.status == "warn"), None)
        if warning is not None:
            return warning.detail
        return "All operator posture checks passed."

    @staticmethod
    def _overall_status(checks: list[OperatorStatusCheck]) -> str:
        statuses = {check.status for check in checks}
        if "fail" in statuses:
            return "fail"
        if "warn" in statuses:
            return "warn"
        return "pass"

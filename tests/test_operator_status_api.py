from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_operator_status_service
from stocks_tool.application.services.operator_status import (
    OperatorStatusService,
    bull_put_lifecycle_warnings,
    order_lifecycle_lookup,
    scheduler_job_summaries,
)
from stocks_tool.application.services.strategy_lifecycle import BULL_PUT_CLOSE_ORDER_WARNING
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    SchedulerJobRunStatus,
    SpreadStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    BullPutSpread,
    BullPutStrategyRuntimeState,
    Order,
    SchedulerJobSummary,
    SchedulerJobRun,
    SchedulerStatusSnapshot,
    StrategyAuditEvent,
    StrategyAuditSummary,
    StrategyAuditSummaryGroup,
    StrategyControlSnapshot,
    ZeroDteLotteryRuntimeState,
)
from stocks_tool.main import app


NOW = datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)


def _controls() -> StrategyControlSnapshot:
    return StrategyControlSnapshot(
        external_account_id="LBPT10087357",
        execution_mode=ExecutionMode.PAPER,
        live_trading_enabled=False,
        scheduler_enabled=True,
        live_execution_allowed=False,
    )


def _bull_put_runtime() -> BullPutStrategyRuntimeState:
    return BullPutStrategyRuntimeState(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        auto_entry_enabled=False,
        next_action="Monitor existing spreads.",
    )


def _zero_dte_runtime() -> ZeroDteLotteryRuntimeState:
    return ZeroDteLotteryRuntimeState(
        external_account_id="LBPT10087357",
        enabled=True,
        auto_execute_enabled=False,
        scan_interval_seconds=900,
        scan_window_start="10:00",
        scan_window_end="14:30",
        max_premium_per_trade=Decimal("150"),
        contracts_per_trade=1,
        max_trades_per_day=1,
        symbols=["QQQ.US"],
    )


def _short_exit_order() -> Order:
    return Order(
        id="short-exit",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id="external-short-exit",
        client_order_id="client-short-exit",
        symbol="QQQ260619P450000.US",
        asset_type=AssetType.OPTION,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.CANCELED,
        limit_price=Decimal("1.20"),
        created_at=NOW,
        updated_at=NOW,
    )


def _spread_requiring_manual_close_action() -> BullPutSpread:
    return BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 19),
        contracts=1,
        width=Decimal("2"),
        long_symbol="QQQ260619P448000.US",
        long_strike=Decimal("448"),
        short_symbol="QQQ260619P450000.US",
        short_strike=Decimal("450"),
        status=SpreadStatus.OPEN,
        short_exit_order_id="short-exit",
        raw_payload={"monitor": {"should_close": True, "exit_reason": "stop_loss"}},
        created_at=NOW,
        updated_at=NOW,
    )


def _operator_status_service() -> OperatorStatusService:
    strategy_experiments = Mock()
    strategy_experiments.get_control_snapshot.return_value = _controls()
    bull_put = Mock()
    bull_put.get_runtime_state.return_value = _bull_put_runtime()
    bull_put.list_spreads.return_value = [_spread_requiring_manual_close_action()]
    zero_dte = Mock()
    zero_dte.get_runtime_state.return_value = _zero_dte_runtime()
    orders = Mock()
    orders.list_orders.return_value = [_short_exit_order()]
    scheduler_runs = Mock()
    scheduler_runs.list_runs.return_value = [
        SchedulerJobRun(
            job_key="bull-put-monitor",
            job_label="bull put monitor",
            external_account_id="LBPT10087357",
            status=SchedulerJobRunStatus.SUCCEEDED,
            started_at=NOW,
            completed_at=NOW,
            detail="Monitored 1 due bull put spread.",
        )
    ]
    return OperatorStatusService(
        strategy_experiments=strategy_experiments,
        bull_put_strategy=bull_put,
        zero_dte_lottery_strategy=zero_dte,
        order_service=orders,
        scheduler_job_runs=scheduler_runs,
    )


def test_operator_status_service_reports_lifecycle_manual_action() -> None:
    status = _operator_status_service().get_unattended_status(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    )

    assert status.status == "fail"
    assert status.ready_for_unattended is False
    assert status.active_bull_put_spread_count == 1
    assert status.open_order_count == 0
    assert status.lifecycle_warnings[0].code == BULL_PUT_CLOSE_ORDER_WARNING
    assert status.lifecycle_warnings[0].record_id == "spread-1"
    assert status.operator_posture_reason == "1 strategy lifecycle warning(s) require operator review."
    assert status.broker_profiles[0].paper_guard == "config_declared"
    assert status.paper_mandate is not None
    assert status.paper_mandate.manual_pause is False
    assert status.paper_mandate.kill_switch is False
    assert status.audit_summary["event_count"] >= 1
    assert status.recent_scheduler_runs[0].job_key == "bull-put-monitor"
    assert status.recent_scheduler_summaries[0].job_key == "bull-put-monitor"
    assert status.recent_scheduler_summaries[0].posture == "pass"
    assert status.recent_scheduler_summaries[0].due_status == "healthy"
    assert status.recent_scheduler_summaries[0].recent_problem_count == 0


def test_scheduler_job_summaries_group_recent_runs_by_job_and_account() -> None:
    runs = [
        SchedulerJobRun(
            job_key="orders-sync",
            job_label="order sync",
            external_account_id="LBPT10087357",
            status=SchedulerJobRunStatus.BACKOFF,
            started_at=datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc),
            completed_at=datetime(2026, 6, 15, 14, 46, tzinfo=timezone.utc),
            next_attempt_at=datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc),
            backoff_seconds=900,
            consecutive_failures=2,
            error_message="timed out",
        ),
        SchedulerJobRun(
            job_key="orders-sync",
            job_label="order sync",
            external_account_id="LBPT10087357",
            status=SchedulerJobRunStatus.SUCCEEDED,
            started_at=datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc),
            completed_at=datetime(2026, 6, 15, 14, 31, tzinfo=timezone.utc),
        ),
    ]

    summaries = scheduler_job_summaries(runs)

    assert len(summaries) == 1
    assert summaries[0].job_key == "orders-sync"
    assert summaries[0].last_status == SchedulerJobRunStatus.BACKOFF
    assert summaries[0].posture == "warn"
    assert summaries[0].due_status == "backoff"
    assert "next attempt at 2026-06-15T15:00:00+00:00" in summaries[0].status_detail
    assert summaries[0].recent_run_count == 2
    assert summaries[0].recent_problem_count == 1
    assert summaries[0].last_problem_at == datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc)
    assert summaries[0].next_attempt_at == datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc)


def test_scheduler_job_summaries_report_failure_and_recovered_postures() -> None:
    runs = [
        SchedulerJobRun(
            job_key="account-sync",
            job_label="account sync",
            external_account_id="LBPT10087357",
            status=SchedulerJobRunStatus.SUCCEEDED,
            started_at=datetime(2026, 6, 15, 14, 50, tzinfo=timezone.utc),
            completed_at=datetime(2026, 6, 15, 14, 51, tzinfo=timezone.utc),
        ),
        SchedulerJobRun(
            job_key="account-sync",
            job_label="account sync",
            external_account_id="LBPT10087357",
            status=SchedulerJobRunStatus.FAILED,
            started_at=datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc),
            completed_at=datetime(2026, 6, 15, 14, 31, tzinfo=timezone.utc),
            error_message="broker rejected request",
        ),
        SchedulerJobRun(
            job_key="market-events-import",
            job_label="market event import",
            external_account_id=None,
            status=SchedulerJobRunStatus.FAILED,
            started_at=datetime(2026, 6, 15, 14, 40, tzinfo=timezone.utc),
            completed_at=datetime(2026, 6, 15, 14, 41, tzinfo=timezone.utc),
            error_message="provider unavailable",
        ),
    ]

    summaries = scheduler_job_summaries(runs)

    account_summary = next(summary for summary in summaries if summary.job_key == "account-sync")
    provider_summary = next(summary for summary in summaries if summary.job_key == "market-events-import")
    assert account_summary.posture == "warn"
    assert account_summary.due_status == "recovered"
    assert account_summary.last_problem_at == datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)
    assert "recent problem run" in account_summary.status_detail
    assert provider_summary.posture == "fail"
    assert provider_summary.due_status == "failed"
    assert provider_summary.status_detail == "provider unavailable"


def test_bull_put_lifecycle_warnings_uses_normalized_fields_without_raw_payload() -> None:
    spread = _spread_requiring_manual_close_action().model_copy(
        update={
            "raw_payload": None,
            "lifecycle_warning_code": BULL_PUT_CLOSE_ORDER_WARNING,
            "manual_action_required": True,
            "latest_monitor_should_close": True,
            "latest_close_order_status": "canceled",
        }
    )

    warnings = bull_put_lifecycle_warnings(
        spreads=[spread],
        orders_by_id=order_lifecycle_lookup([_short_exit_order()]),
    )

    assert len(warnings) == 1
    assert warnings[0].code == BULL_PUT_CLOSE_ORDER_WARNING
    assert warnings[0].record_id == "spread-1"
    assert warnings[0].context["short_exit_order_status"] == "canceled"


def test_ops_unattended_status_route_returns_operator_snapshot() -> None:
    app.dependency_overrides[get_operator_status_service] = _operator_status_service
    client = TestClient(app)
    try:
        response = client.get(
            "/ops/unattended-status",
            params={"external_account_id": "LBPT10087357", "mode": "paper"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["external_account_id"] == "LBPT10087357"
    assert body["status"] == "fail"
    assert body["operator_posture_reason"] == "1 strategy lifecycle warning(s) require operator review."
    assert body["broker_profiles"][0]["external_account_id"] == "LBPT10087357"
    assert body["paper_mandate"]["manual_pause"] is False
    assert body["audit_summary"]["event_count"] >= 1
    assert body["lifecycle_warnings"][0]["code"] == BULL_PUT_CLOSE_ORDER_WARNING
    assert body["recent_scheduler_runs"][0]["job_key"] == "bull-put-monitor"


def test_ops_scheduler_route_returns_recent_scheduler_runs() -> None:
    service = Mock()
    service.get_scheduler_status.return_value = SchedulerStatusSnapshot(
        generated_at=NOW,
        external_account_id="LBPT10087357",
        runs=[
            SchedulerJobRun(
                job_key="orders-sync",
                job_label="order reconciliation",
                external_account_id="LBPT10087357",
                status=SchedulerJobRunStatus.BACKOFF,
                started_at=NOW,
                completed_at=NOW,
                next_attempt_at=datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc),
                backoff_seconds=900,
                consecutive_failures=2,
                error_message="timed out",
            )
        ],
        summaries=[
            SchedulerJobSummary(
                job_key="orders-sync",
                job_label="order reconciliation",
                external_account_id="LBPT10087357",
                last_status=SchedulerJobRunStatus.BACKOFF,
                last_started_at=NOW,
                last_completed_at=NOW,
                next_attempt_at=datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc),
                backoff_seconds=900,
                consecutive_failures=2,
                error_message="timed out",
                posture="warn",
                due_status="backoff",
                status_detail="Backoff active after 2 consecutive failure(s).",
                recent_run_count=1,
                recent_problem_count=1,
            )
        ],
    )
    app.dependency_overrides[get_operator_status_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/ops/scheduler",
            params={"external_account_id": "LBPT10087357", "limit": 20},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["external_account_id"] == "LBPT10087357"
    assert body["runs"][0]["job_key"] == "orders-sync"
    assert body["runs"][0]["status"] == "backoff"
    assert body["summaries"][0]["job_key"] == "orders-sync"
    assert body["summaries"][0]["last_status"] == "backoff"
    assert body["summaries"][0]["posture"] == "warn"
    assert body["summaries"][0]["due_status"] == "backoff"
    assert body["summaries"][0]["status_detail"] == "Backoff active after 2 consecutive failure(s)."
    assert body["summaries"][0]["recent_problem_count"] == 1
    service.get_scheduler_status.assert_called_once_with(
        external_account_id="LBPT10087357",
        limit=20,
    )


def test_ops_audit_route_returns_strategy_audit_events() -> None:
    service = Mock()
    service.list_audit_events.return_value = [
        StrategyAuditEvent(
            id="signal-audit-1",
            emitted_at=NOW,
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            actor="operator-a",
            source="strategy_policy",
            strategy="paper_bull_put_v1",
            action="approve",
            before={"status": "pending"},
            after={"status": "approved"},
            proposal_id="proposal-1",
            summary="Strategy proposal approve recorded.",
        )
    ]
    app.dependency_overrides[get_operator_status_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/ops/audit",
            params={"external_account_id": "LBPT10087357", "limit": 20},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "signal-audit-1"
    assert body[0]["actor"] == "operator-a"
    assert body[0]["before"] == {"status": "pending"}
    service.list_audit_events.assert_called_once_with(
        external_account_id="LBPT10087357",
        mode=None,
        source=None,
        strategy=None,
        action=None,
        warning_only=False,
        since=None,
        limit=20,
    )


def test_ops_audit_route_forwards_filter_query_params() -> None:
    service = Mock()
    service.list_audit_events.return_value = []
    app.dependency_overrides[get_operator_status_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/ops/audit",
            params={
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "source": "orders",
                "strategy": "paper_order",
                "action": "paper_order_submitted",
                "warning_only": "true",
                "since": "2026-06-16T10:00:00Z",
                "limit": "5",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    service.list_audit_events.assert_called_once()
    kwargs = service.list_audit_events.call_args.kwargs
    assert kwargs["external_account_id"] == "LBPT10087357"
    assert kwargs["mode"] == ExecutionMode.PAPER
    assert kwargs["source"] == "orders"
    assert kwargs["strategy"] == "paper_order"
    assert kwargs["action"] == "paper_order_submitted"
    assert kwargs["warning_only"] is True
    assert kwargs["since"] == datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc)
    assert kwargs["limit"] == 5


def test_operator_status_service_summarizes_audit_events_by_stable_groups() -> None:
    service = _operator_status_service()
    durable = StrategyAuditEvent(
        id="durable-1",
        emitted_at=datetime(2026, 6, 16, 10, 5, tzinfo=timezone.utc),
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        actor="operator-a",
        source="manual_recovery",
        strategy="paper_bull_put_v1",
        action="bull_put_recover_close_rejected",
        warning_code="working_replacement_exists",
        event_origin="durable",
    )
    synthetic = durable.model_copy(
        update={
            "id": "synthetic-1",
            "emitted_at": datetime(2026, 6, 16, 10, 4, tzinfo=timezone.utc),
            "event_origin": "synthetic",
        }
    )
    service.list_audit_events = Mock(return_value=[durable, synthetic])  # type: ignore[method-assign]

    summary = service.get_audit_summary(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        limit=20,
    )

    assert summary.event_count == 2
    assert summary.warning_count == 2
    assert len(summary.groups) == 2
    assert summary.groups[0].event_origin == "durable"
    assert summary.groups[0].latest_emitted_at == datetime(2026, 6, 16, 10, 5, tzinfo=timezone.utc)
    service.list_audit_events.assert_called_once_with(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        since=None,
        limit=20,
    )


def test_operator_status_service_prefers_durable_audit_events_when_deduping() -> None:
    durable = StrategyAuditEvent(
        id="durable-order-1",
        emitted_at=datetime(2026, 6, 16, 10, 5, tzinfo=timezone.utc),
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        actor="broker_gateway",
        source="orders",
        strategy="paper_order",
        action="paper_order_state_observed",
        order_ids=["order-1"],
        event_origin="durable",
    )
    synthetic_duplicate = durable.model_copy(
        update={
            "id": "synthetic-order-1",
            "emitted_at": datetime(2026, 6, 16, 10, 4, tzinfo=timezone.utc),
            "event_origin": "synthetic",
        }
    )
    older = StrategyAuditEvent(
        id="durable-order-2",
        emitted_at=datetime(2026, 6, 16, 10, 1, tzinfo=timezone.utc),
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        source="orders",
        strategy="paper_order",
        action="paper_order_submitted",
        order_ids=["order-2"],
        event_origin="durable",
    )
    strategy_experiments = Mock()
    strategy_experiments.get_control_snapshot.return_value = _controls()
    strategy_experiments.list_audit_events.return_value = [synthetic_duplicate]
    service = OperatorStatusService(
        strategy_experiments=strategy_experiments,
        bull_put_strategy=Mock(),
        zero_dte_lottery_strategy=Mock(),
        order_service=Mock(list_orders=Mock(return_value=[])),
        scheduler_job_runs=Mock(list_runs=Mock(return_value=[])),
        audit_events=Mock(list_events=Mock(return_value=[older, durable])),
    )

    events = service.list_audit_events(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        limit=10,
    )

    assert [event.id for event in events] == ["durable-order-1", "durable-order-2"]
    assert all(event.event_origin == "durable" for event in events)


def test_operator_reason_code_catalog_covers_v3_codes() -> None:
    assert OperatorStatusService.reason_code_detail("scheduler_backoff")
    assert OperatorStatusService.reason_code_detail("manual_pause")
    assert OperatorStatusService.reason_code_detail("kill_switch")
    assert OperatorStatusService.reason_code_detail("advisor_pending_record")
    assert OperatorStatusService.reason_code_detail("manual_action_required")
    assert OperatorStatusService.reason_code_detail("operator_audit_summary_unavailable")


def test_ops_audit_summary_route_returns_grouped_summary() -> None:
    service = Mock()
    service.get_audit_summary.return_value = StrategyAuditSummary(
        generated_at=NOW,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        since=datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc),
        limit=50,
        event_count=2,
        warning_count=1,
        groups=[
            StrategyAuditSummaryGroup(
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                source="manual_recovery",
                action="bull_put_recover_close_rejected",
                strategy="paper_bull_put_v1",
                warning_code="working_replacement_exists",
                event_origin="durable",
                count=1,
                latest_emitted_at=NOW,
            )
        ],
    )
    app.dependency_overrides[get_operator_status_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/ops/audit/summary",
            params={
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "since": "2026-06-16T10:00:00Z",
                "limit": "50",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["event_count"] == 2
    assert body["warning_count"] == 1
    assert body["groups"][0]["event_origin"] == "durable"
    service.get_audit_summary.assert_called_once_with(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        since=datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc),
        limit=50,
    )


def test_ops_audit_routes_reject_bad_limit_queries() -> None:
    client = TestClient(app)

    audit_response = client.get("/ops/audit", params={"limit": "1000"})
    summary_response = client.get("/ops/audit/summary", params={"limit": "1000"})

    assert audit_response.status_code == 422
    assert summary_response.status_code == 422

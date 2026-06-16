from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from stocks_tool.adapters.advisors.deepseek import DeepSeekAdvisorError
from stocks_tool.api.dependencies import get_deepseek_advisor_client, get_strategy_experiment_service
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    ExecutionMode,
    StrategyAdvisorRunStatus,
    StrategyProposalStatus,
    StrategyReviewStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    AdvisorRunCard,
    CreateStrategyAdvisorRunRequest,
    CreateStrategyProposalRequest,
    CoveredCallLifecycleTask,
    CoveredCallActivitySnapshot,
    CoveredCallActivitySummary,
    CoveredCallMonitorSnapshot,
    StrategyAdvisorAuditSnapshot,
    StrategyAdvisorRunAudit,
    StrategyAdvisorRunComparison,
    StrategyAdvisorRunImpact,
    StrategyAdvisorContext,
    StrategyAdvisorRun,
    StrategyAdvisorRunAuditCheck,
    StrategyExperimentSnapshot,
    StrategyAutomationControl,
    StrategyControlSnapshot,
    StrategyPermissionBoundary,
    StrategyProposal,
    StrategyReview,
    StrategyRun,
    StrategySignal,
)
from stocks_tool.main import app


NOW = datetime(2026, 5, 29, 14, 45, tzinfo=timezone.utc)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def with_experiment_service(service: Mock) -> TestClient:
    app.dependency_overrides[get_strategy_experiment_service] = lambda: service
    return TestClient(app)


def build_proposal(status: StrategyProposalStatus = StrategyProposalStatus.PENDING) -> StrategyProposal:
    return StrategyProposal(
        id="proposal-1",
        strategy_id="paper_bull_put_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="QQQ.US",
        title="Locked QQQ bull put candidate",
        proposed_action="execute_locked_preview",
        rationale="Candidate passed preview and risk checks.",
        status=status,
        confidence=Decimal("0.68"),
        expected_max_loss=Decimal("248.00"),
        checks=["candidate_token", "minimum_net_credit"],
        created_at=NOW,
        updated_at=NOW,
    )


def build_covered_call_proposal(
    *,
    proposal_id: str = "proposal-cc-1",
    action: str = "sell_covered_call",
    status: StrategyProposalStatus = StrategyProposalStatus.PENDING,
) -> StrategyProposal:
    return StrategyProposal(
        id=proposal_id,
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell covered call on UNH.US",
        proposed_action=action,
        rationale="Candidate passed covered-call readiness checks.",
        status=status,
        confidence=Decimal("0.55"),
        created_at=NOW,
        updated_at=NOW,
    )


def build_run() -> StrategyRun:
    return StrategyRun(
        id="run-1",
        strategy_id="paper_bull_put_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        run_type="preview",
        status=StrategyRunStatus.EXECUTED,
        symbol="QQQ.US",
        summary="Preview returned an eligible candidate.",
        started_at=NOW,
        completed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def build_covered_call_run(
    run_type: str = "proposal_close",
    *,
    proposal_id: str | None = None,
    order_id: str | None = None,
    metrics_payload: dict | None = None,
    created_at: datetime = NOW,
) -> StrategyRun:
    return StrategyRun(
        id=f"run-{run_type}",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        run_type=run_type,
        status=StrategyRunStatus.EXECUTED,
        symbol="UNH.US",
        proposal_id=proposal_id,
        order_id=order_id,
        summary="Covered-call action recorded.",
        metrics_payload=metrics_payload,
        started_at=created_at,
        completed_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )


def build_signal() -> StrategySignal:
    return StrategySignal(
        id="signal-1",
        strategy_id="paper_bull_put_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        signal_type=StrategySignalType.CANDIDATE,
        symbol="QQQ.US",
        strength=Decimal("0.4"),
        summary="Candidate survived liquidity filters.",
        emitted_at=NOW,
        created_at=NOW,
    )


def build_covered_call_monitor_signal() -> StrategySignal:
    return StrategySignal(
        id="signal-monitor-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        signal_type=StrategySignalType.MONITOR,
        symbol="UNH.US",
        proposal_id="proposal-open-1",
        summary="Covered call monitor action: hold.",
        detail="No trigger is active.",
        signal_payload={
            "action": "hold",
            "underlying_price": "100.25",
            "call_mark": "0.55",
            "estimated_open_pnl": "65.00",
            "premium_capture_pct": "54.17",
            "days_to_expiration": 28,
        },
        emitted_at=NOW + timedelta(minutes=30),
        created_at=NOW + timedelta(minutes=30),
    )


def build_review() -> StrategyReview:
    return StrategyReview(
        id="review-1",
        strategy_id="paper_bull_put_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        review_type="runtime",
        status=StrategyReviewStatus.OBSERVED,
        summary="Monitor one existing open spread.",
        recommendation="Do not add another correlated spread while QQQ is open.",
        reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def build_advisor_run(status: StrategyAdvisorRunStatus = StrategyAdvisorRunStatus.SUCCEEDED) -> StrategyAdvisorRun:
    return StrategyAdvisorRun(
        id="advisor-run-1",
        external_account_id="LBPT10087357",
        source="deepseek",
        mode=ExecutionMode.PAPER,
        provider="deepseek",
        model="deepseek-v4-pro",
        status=status,
        context_format="compact_v1",
        context_limit=6,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        cache_hit_tokens=40,
        cache_miss_tokens=60,
        proposal_count=0,
        review_count=1,
        response_id="chatcmpl-1",
        finish_reason="stop",
        response_payload={
            "external_account_id": "LBPT10087357",
            "source": "deepseek",
            "mode": "paper",
            "reviews": [
                {
                    "strategy_id": "covered_call_v1",
                    "review_type": "advisor",
                    "status": "observed",
                    "summary": "Current covered-call lifecycle is flat.",
                }
            ],
        },
        started_at=NOW,
        completed_at=NOW,
        recorded_at=NOW if status == StrategyAdvisorRunStatus.RECORDED else None,
        created_at=NOW,
        updated_at=NOW,
    )


def build_advisor_context() -> StrategyAdvisorContext:
    controls = StrategyControlSnapshot(
        external_account_id="LBPT10087357",
        execution_mode=ExecutionMode.PAPER,
        live_trading_enabled=False,
        scheduler_enabled=True,
        permission_boundaries=[
            StrategyPermissionBoundary(
                name="llm_read_only_advisor",
                allowed=False,
                detail="Advisor output cannot execute directly.",
            )
        ],
    )
    return StrategyAdvisorContext(
        external_account_id="LBPT10087357",
        controls=controls,
        experiment=StrategyExperimentSnapshot(
            external_account_id="LBPT10087357",
            proposals=[build_proposal()],
            runs=[build_run()],
            signals=[build_signal()],
            reviews=[build_review()],
        ),
        covered_call_activity=CoveredCallActivitySnapshot(
            external_account_id="LBPT10087357",
            summary=CoveredCallActivitySummary(external_account_id="LBPT10087357"),
        ),
        advisor_sources=["deepseek", "external_advisor", "llm", "llm_advisor", "openai"],
        hard_rules=[
            StrategyPermissionBoundary(
                name="advisor_context_is_read_only",
                allowed=False,
                detail="Context cannot submit broker orders.",
            )
        ],
    )


def test_strategy_experiment_snapshot_route_returns_unified_lists() -> None:
    service = Mock()
    service.get_snapshot.return_value = StrategyExperimentSnapshot(
        external_account_id="LBPT10087357",
        proposals=[build_proposal()],
        runs=[build_run()],
        signals=[build_signal()],
        reviews=[build_review()],
    )

    client = with_experiment_service(service)
    try:
        response = client.get(
            "/strategies/experiment",
            params={"external_account_id": "LBPT10087357", "limit": "6"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["proposals"][0]["id"] == "proposal-1"
    assert body["runs"][0]["status"] == "executed"
    assert body["signals"][0]["signal_type"] == "candidate"
    assert body["reviews"][0]["status"] == "observed"
    service.get_snapshot.assert_called_once_with(
        external_account_id="LBPT10087357",
        strategy_id=None,
        limit=6,
    )


def test_covered_call_activity_route_returns_dedicated_snapshot() -> None:
    service = Mock()
    service.get_covered_call_activity.return_value = CoveredCallActivitySnapshot(
        external_account_id="LBPT10087357",
        summary=CoveredCallActivitySummary(
            external_account_id="LBPT10087357",
            total_proposals=2,
            active_proposals=1,
            executed_positions=1,
            pending_rolls=1,
            close_runs=1,
            latest_activity_at=NOW,
        ),
        latest_monitor=CoveredCallMonitorSnapshot(
            proposal_id="proposal-cc-1",
            symbol="UNH.US",
            action="hold",
            detail="No trigger is active.",
            underlying_price=Decimal("100"),
            call_mark=Decimal("0.55"),
            estimated_open_pnl=Decimal("65.00"),
            premium_capture_pct=Decimal("54.17"),
            days_to_expiration=28,
            emitted_at=NOW,
            signal_id="signal-monitor-1",
        ),
        lifecycle_tasks=[
            CoveredCallLifecycleTask(
                proposal_id="proposal-cc-1",
                proposal_title="Sell covered call on UNH.US",
                symbol="UNH.US",
                task_type="close",
                proposal_status=StrategyProposalStatus.EXECUTED,
                last_run_id="run-proposal_close",
                last_run_type="proposal_close",
                close_order_id="close-order-1",
                close_status="submitted",
                last_refresh_status="submitted",
                last_refresh_at=NOW,
            )
        ],
        proposals=[
            build_covered_call_proposal(status=StrategyProposalStatus.EXECUTED),
            build_covered_call_proposal(
                proposal_id="proposal-roll-1",
                action="roll_covered_call",
                status=StrategyProposalStatus.PENDING,
            ),
        ],
        runs=[build_covered_call_run()],
    )

    client = with_experiment_service(service)
    try:
        response = client.get(
            "/strategies/covered-call/activity",
            params={"external_account_id": "LBPT10087357", "limit": "8"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["executed_positions"] == 1
    assert body["summary"]["pending_rolls"] == 1
    assert body["latest_monitor"]["action"] == "hold"
    assert body["latest_monitor"]["estimated_open_pnl"] == "65.00"
    assert body["lifecycle_tasks"][0]["task_type"] == "close"
    assert body["lifecycle_tasks"][0]["close_order_id"] == "close-order-1"
    assert body["proposals"][1]["proposed_action"] == "roll_covered_call"
    service.get_covered_call_activity.assert_called_once_with(
        external_account_id="LBPT10087357",
        limit=8,
    )


def test_strategy_experiment_service_summarizes_covered_call_activity() -> None:
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    experiments.list_proposals.return_value = [
        build_covered_call_proposal(status=StrategyProposalStatus.EXECUTED),
        build_covered_call_proposal(
            proposal_id="proposal-roll-executed",
            action="roll_covered_call",
            status=StrategyProposalStatus.EXECUTED,
        ),
        build_covered_call_proposal(
            proposal_id="proposal-closed",
            status=StrategyProposalStatus.CLOSED,
        ),
        build_covered_call_proposal(
            proposal_id="proposal-rolled",
            status=StrategyProposalStatus.ROLLED,
        ),
        build_covered_call_proposal(
            proposal_id="proposal-roll-1",
            action="roll_covered_call",
            status=StrategyProposalStatus.APPROVED,
        ),
    ]
    experiments.list_runs.return_value = [build_covered_call_run("proposal_close")]
    experiments.list_signals.return_value = []
    experiments.list_reviews.return_value = []
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
    )

    activity = service.get_covered_call_activity(
        external_account_id="LBPT10087357",
        limit=8,
    )

    assert activity.summary.total_proposals == 5
    assert activity.summary.active_proposals == 1
    assert activity.summary.executed_positions == 2
    assert activity.summary.pending_rolls == 1
    assert activity.summary.close_runs == 1
    assert activity.summary.latest_activity_at == NOW
    experiments.list_proposals.assert_called_once_with(
        external_account_id="LBPT10087357",
        strategy_id="covered_call_v1",
        status=None,
        limit=8,
    )


def test_strategy_experiment_service_lists_covered_call_lifecycle_tasks() -> None:
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    experiments.list_proposals.return_value = [
        build_covered_call_proposal(
            proposal_id="proposal-open-1",
            status=StrategyProposalStatus.APPROVED,
        ),
        build_covered_call_proposal(
            proposal_id="proposal-close-1",
            status=StrategyProposalStatus.EXECUTED,
        ),
        build_covered_call_proposal(
            proposal_id="proposal-roll-1",
            action="roll_covered_call",
            status=StrategyProposalStatus.APPROVED,
        ),
    ]
    experiments.list_runs.return_value = [
        build_covered_call_run(
            "proposal_execution",
            proposal_id="proposal-open-1",
            order_id="sell-order-1",
            metrics_payload={
                "order_id": "sell-order-1",
                "sequence_status": "sell_submitted_waiting_fill",
                "sell_status": "submitted",
                "order_submitted_at": NOW.isoformat(),
            },
            created_at=NOW + timedelta(minutes=20),
        ),
        build_covered_call_run(
            "roll_continuation",
            proposal_id="proposal-roll-1",
            order_id="roll-open-order-1",
            metrics_payload={
                "sequence_status": "roll_sell_submitted_waiting_fill",
                "buyback_order_id": "buyback-order-1",
                "sell_order_id": "roll-open-order-1",
                "buyback_status": "filled",
                "sell_status": "submitted",
            },
            created_at=NOW + timedelta(minutes=5),
        ),
        build_covered_call_run(
            "proposal_close",
            proposal_id="proposal-close-1",
            order_id="close-order-1",
            metrics_payload={
                "order_id": "close-order-1",
                "close_status": "submitted",
            },
            created_at=NOW,
        ),
    ]
    experiments.list_signals.return_value = [build_covered_call_monitor_signal()]
    experiments.list_reviews.return_value = []
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
    )

    activity = service.get_covered_call_activity(
        external_account_id="LBPT10087357",
        limit=8,
    )

    assert len(activity.lifecycle_tasks) == 3
    open_task = activity.lifecycle_tasks[0]
    roll_task = activity.lifecycle_tasks[1]
    close_task = activity.lifecycle_tasks[2]
    assert open_task.task_type == "open"
    assert open_task.open_order_id == "sell-order-1"
    assert open_task.last_refresh_status == "sell_submitted_waiting_fill"
    assert open_task.order_age_seconds == 1200
    assert open_task.is_stale is True
    assert "cancel/re-enter" in open_task.suggested_action
    assert roll_task.task_type == "roll"
    assert roll_task.roll_buyback_order_id == "buyback-order-1"
    assert roll_task.roll_sell_order_id == "roll-open-order-1"
    assert roll_task.last_refresh_status == "roll_sell_submitted_waiting_fill"
    assert close_task.task_type == "close"
    assert close_task.close_order_id == "close-order-1"
    assert close_task.last_refresh_status == "submitted"
    assert activity.latest_monitor is not None
    assert activity.latest_monitor.action == "hold"
    assert activity.latest_monitor.call_mark == Decimal("0.55")
    assert activity.latest_monitor.estimated_open_pnl == Decimal("65.00")


def test_create_strategy_proposal_route_returns_created_proposal() -> None:
    service = Mock()
    service.create_proposal.return_value = build_proposal()

    client = with_experiment_service(service)
    try:
        response = client.post(
            "/strategies/proposals",
            json={
                "strategy_id": "paper_bull_put_v1",
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "symbol": "QQQ.US",
                "title": "Locked QQQ bull put candidate",
                "proposed_action": "execute_locked_preview",
                "rationale": "Candidate passed preview and risk checks.",
                "confidence": "0.68",
                "expected_max_loss": "248.00",
                "checks": ["candidate_token", "minimum_net_credit"],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    request = service.create_proposal.call_args.args[0]
    assert request.external_account_id == "LBPT10087357"
    assert request.checks == ["candidate_token", "minimum_net_credit"]


def test_approve_strategy_proposal_route_returns_approved_proposal() -> None:
    service = Mock()
    service.approve_proposal.return_value = build_proposal(StrategyProposalStatus.APPROVED)

    client = with_experiment_service(service)
    try:
        response = client.post("/strategies/proposals/proposal-1/approve")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    service.approve_proposal.assert_called_once_with(
        "proposal-1",
        actor="local_operator",
        note=None,
    )


def test_approve_strategy_proposal_route_accepts_audit_actor() -> None:
    service = Mock()
    service.approve_proposal.return_value = build_proposal(StrategyProposalStatus.APPROVED)

    client = with_experiment_service(service)
    try:
        response = client.post(
            "/strategies/proposals/proposal-1/approve",
            json={"actor": "operator-a", "note": "paper test approval"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    service.approve_proposal.assert_called_once_with(
        "proposal-1",
        actor="operator-a",
        note="paper test approval",
    )


def test_strategy_controls_route_returns_policy_snapshot() -> None:
    service = Mock()
    service.get_control_snapshot.return_value = StrategyControlSnapshot(
        external_account_id="LBPT10087357",
        execution_mode=ExecutionMode.PAPER,
        live_trading_enabled=False,
        scheduler_enabled=True,
        automation_controls=[
            StrategyAutomationControl(
                strategy_id="covered_call_v1",
                enabled=True,
                auto_monitor_enabled=True,
                auto_lifecycle_enabled=True,
            )
        ],
        permission_boundaries=[
            StrategyPermissionBoundary(
                name="manual_approval_before_execution",
                allowed=True,
                detail="Opening and roll executions require approval.",
            )
        ],
    )

    client = with_experiment_service(service)
    try:
        response = client.get(
            "/strategies/controls",
            params={"external_account_id": "LBPT10087357"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["automation_controls"][0]["strategy_id"] == "covered_call_v1"
    assert body["automation_controls"][0]["auto_monitor_enabled"] is True
    assert body["llm_direct_execution_allowed"] is False
    service.get_control_snapshot.assert_called_once_with(
        external_account_id="LBPT10087357",
    )


def test_strategy_advisor_context_route_returns_read_only_context() -> None:
    service = Mock()
    controls = StrategyControlSnapshot(
        external_account_id="LBPT10087357",
        execution_mode=ExecutionMode.PAPER,
        live_trading_enabled=False,
        scheduler_enabled=True,
        permission_boundaries=[
            StrategyPermissionBoundary(
                name="llm_read_only_advisor",
                allowed=False,
                detail="Advisor output cannot execute directly.",
            )
        ],
    )
    service.get_advisor_context.return_value = StrategyAdvisorContext(
        external_account_id="LBPT10087357",
        controls=controls,
        experiment=StrategyExperimentSnapshot(
            external_account_id="LBPT10087357",
            proposals=[build_proposal()],
            runs=[build_run()],
            signals=[build_signal()],
            reviews=[build_review()],
        ),
        covered_call_activity=CoveredCallActivitySnapshot(
            external_account_id="LBPT10087357",
            summary=CoveredCallActivitySummary(external_account_id="LBPT10087357"),
        ),
        advisor_sources=["deepseek", "external_advisor", "llm", "llm_advisor", "openai"],
        hard_rules=[
            StrategyPermissionBoundary(
                name="advisor_context_is_read_only",
                allowed=False,
                detail="Context cannot submit broker orders.",
            )
        ],
    )

    client = with_experiment_service(service)
    try:
        response = client.get(
            "/strategies/advisor-context",
            params={"external_account_id": "LBPT10087357", "limit": "6"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["controls"]["llm_direct_execution_allowed"] is False
    assert body["advisor_sources"][0] == "deepseek"
    assert body["hard_rules"][0]["name"] == "advisor_context_is_read_only"
    assert body["experiment"]["proposals"][0]["id"] == "proposal-1"
    assert body["covered_call_activity"]["summary"]["external_account_id"] == "LBPT10087357"
    service.get_advisor_context.assert_called_once_with(
        external_account_id="LBPT10087357",
        limit=6,
    )


def test_deepseek_advisor_dry_run_route_returns_recordable_payload_without_writing() -> None:
    service = Mock()
    service.get_advisor_context.return_value = build_advisor_context()
    service.create_advisor_run.return_value = build_advisor_run()
    advisor_client = Mock()
    advisor_client.create_advisor_response.return_value = {
        "reviews": [
            {
                "strategy_id": "covered_call_v1",
                "review_type": "advisor",
                "status": "observed",
                "summary": "Current covered-call lifecycle is flat.",
                "recommendation": "No broker action is needed.",
            }
        ],
        "raw_response": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "response_id": "chatcmpl-1",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 60,
            },
        },
    }
    app.dependency_overrides[get_strategy_experiment_service] = lambda: service
    app.dependency_overrides[get_deepseek_advisor_client] = lambda: advisor_client
    updated_run = build_advisor_run()
    updated_run.response_payload = {
        **(updated_run.response_payload or {}),
        "advisor_run_id": "advisor-run-1",
    }
    service.update_advisor_run_response_payload.return_value = updated_run
    client = TestClient(app)
    try:
        response = client.post(
            "/strategies/advisor/deepseek/dry-run",
            json={
                "external_account_id": "LBPT10087357",
                "context_limit": 6,
                "model": "v4 pro",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["recorded"] is False
    assert body["source"] == "deepseek"
    assert body["advisor_run"]["id"] == "advisor-run-1"
    assert body["advisor_run"]["context_format"] == "compact_v1"
    assert body["advisor_run"]["prompt_tokens"] == 100
    assert body["advisor_run"]["response_payload"]["advisor_run_id"] == "advisor-run-1"
    assert body["response_payload"]["external_account_id"] == "LBPT10087357"
    assert body["response_payload"]["advisor_run_id"] == "advisor-run-1"
    assert body["response_payload"]["reviews"][0]["summary"] == "Current covered-call lifecycle is flat."
    assert body["response_payload"]["raw_response"]["usage"]["prompt_cache_hit_tokens"] == 40
    service.get_advisor_context.assert_called_once_with(
        external_account_id="LBPT10087357",
        limit=6,
    )
    advisor_client.create_advisor_response.assert_called_once_with(
        context=service.get_advisor_context.return_value,
        model="v4 pro",
    )
    run_request = service.create_advisor_run.call_args.args[0]
    assert run_request.source == "deepseek"
    assert run_request.provider == "deepseek"
    assert run_request.model == "deepseek-v4-pro"
    assert run_request.status == StrategyAdvisorRunStatus.SUCCEEDED
    assert run_request.context_format == "compact_v1"
    assert run_request.context_limit == 6
    assert run_request.cache_hit_tokens == 40
    assert run_request.cache_miss_tokens == 60
    assert run_request.review_count == 1
    service.update_advisor_run_response_payload.assert_called_once()
    update_args = service.update_advisor_run_response_payload.call_args
    assert update_args.args[0] == "advisor-run-1"
    assert update_args.kwargs["response_payload"]["advisor_run_id"] == "advisor-run-1"


def test_deepseek_advisor_dry_run_route_maps_missing_key_to_400() -> None:
    service = Mock()
    service.get_advisor_context.return_value = build_advisor_context()
    advisor_client = Mock()
    advisor_client.create_advisor_response.side_effect = DeepSeekAdvisorError("DEEPSEEK_API_KEY is not configured.")
    app.dependency_overrides[get_strategy_experiment_service] = lambda: service
    app.dependency_overrides[get_deepseek_advisor_client] = lambda: advisor_client
    client = TestClient(app)
    try:
        response = client.post(
            "/strategies/advisor/deepseek/dry-run",
            json={"external_account_id": "LBPT10087357"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 400
    assert "DEEPSEEK_API_KEY" in response.json()["detail"]
    run_request = service.create_advisor_run.call_args.args[0]
    assert run_request.status == StrategyAdvisorRunStatus.FAILED
    assert run_request.error_message == "DEEPSEEK_API_KEY is not configured."


def test_strategy_advisor_runs_route_lists_deepseek_history() -> None:
    service = Mock()
    service.list_advisor_runs.return_value = [build_advisor_run(StrategyAdvisorRunStatus.RECORDED)]

    client = with_experiment_service(service)
    try:
        response = client.get(
            "/strategies/advisor/runs",
            params={"external_account_id": "LBPT10087357", "source": "deepseek", "limit": "5"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "advisor-run-1"
    assert body[0]["status"] == "recorded"
    assert body[0]["cache_hit_tokens"] == 40
    service.list_advisor_runs.assert_called_once_with(
        external_account_id="LBPT10087357",
        source="deepseek",
        limit=5,
    )


def test_strategy_advisor_run_cards_route_lists_run_card_projection() -> None:
    service = Mock()
    service.list_advisor_run_cards.return_value = [
        AdvisorRunCard(
            run_id="advisor-run-1",
            external_account_id="LBPT10087357",
            source="deepseek",
            provider="deepseek",
            model="deepseek-v4-pro",
            status=StrategyAdvisorRunStatus.RECORDED,
            context_format="compact_v1",
            context_hash="abc123",
            token_usage={"total_tokens": 120, "cache_hit_tokens": 40},
            summary="recorded; 0 proposal(s), 1 review(s).",
            recorded=True,
            proposal_count=0,
            review_count=1,
            warnings=[],
            completed_at=NOW,
            recorded_at=NOW,
            created_at=NOW,
        )
    ]

    client = with_experiment_service(service)
    try:
        response = client.get(
            "/strategies/advisor/run-cards",
            params={"external_account_id": "LBPT10087357", "source": "deepseek", "limit": "5"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body[0]["run_id"] == "advisor-run-1"
    assert body[0]["recorded"] is True
    assert body[0]["token_usage"]["cache_hit_tokens"] == 40
    service.list_advisor_run_cards.assert_called_once_with(
        external_account_id="LBPT10087357",
        source="deepseek",
        limit=5,
    )


def test_strategy_advisor_playbooks_route_lists_static_boundaries() -> None:
    service = Mock()
    service.list_advisor_playbooks.return_value = StrategyExperimentService.advisor_playbooks

    client = with_experiment_service(service)
    try:
        response = client.get("/strategies/advisor/playbooks")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    playbook_ids = {item["id"] for item in body}
    assert {"bull_put_v1", "covered_call_v1", "zero_dte_lottery_v1"} <= playbook_ids
    assert any("Cannot submit" in " ".join(item["hard_limits"]) for item in body)
    service.list_advisor_playbooks.assert_called_once_with()


def test_strategy_advisor_audit_route_returns_traceable_summary() -> None:
    service = Mock()
    run = build_advisor_run(StrategyAdvisorRunStatus.RECORDED)
    service.get_advisor_audit_snapshot.return_value = StrategyAdvisorAuditSnapshot(
        external_account_id="LBPT10087357",
        source="deepseek",
        runs=[
            StrategyAdvisorRunAudit(
                advisor_run=run,
                record_state="recorded",
                response_payload={**(run.response_payload or {}), "advisor_run_id": run.id},
                raw_response=run.raw_response,
                token_usage={
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                    "cache_hit_tokens": 40,
                    "cache_miss_tokens": 60,
                },
                comparison=StrategyAdvisorRunComparison(
                    previous_run_id="advisor-run-older",
                    total_tokens_delta=-30,
                    cache_hit_tokens_delta=10,
                ),
                downstream_impact=StrategyAdvisorRunImpact(
                    advisor_run_id=run.id,
                    proposal_ids=["proposal-advisor-1"],
                    review_ids=["review-advisor-1"],
                    proposal_status_counts={"pending": 1},
                    review_status_counts={"observed": 1},
                ),
                checks=[
                    StrategyAdvisorRunAuditCheck(
                        name="paper_mode_only",
                        status="pass",
                        detail="Advisor run is recorded in paper mode.",
                    )
                ],
            )
        ],
    )

    client = with_experiment_service(service)
    try:
        response = client.get(
            "/strategies/advisor/audit",
            params={"external_account_id": "LBPT10087357", "source": "deepseek", "limit": "5"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["runs"][0]["record_state"] == "recorded"
    assert body["runs"][0]["response_payload"]["advisor_run_id"] == "advisor-run-1"
    assert body["runs"][0]["token_usage"]["cache_hit_tokens"] == 40
    assert body["runs"][0]["comparison"]["previous_run_id"] == "advisor-run-older"
    assert body["runs"][0]["downstream_impact"]["proposal_ids"] == ["proposal-advisor-1"]
    service.get_advisor_audit_snapshot.assert_called_once_with(
        external_account_id="LBPT10087357",
        source="deepseek",
        limit=5,
    )


def test_strategy_experiment_service_records_approval_audit_signal() -> None:
    proposal = build_proposal()
    approved = build_proposal(StrategyProposalStatus.APPROVED)
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    experiments.get_proposal.return_value = proposal
    experiments.update_proposal_status.return_value = approved
    experiments.create_signal.side_effect = lambda request: StrategySignal(
        id="signal-policy-audit",
        strategy_id=request.strategy_id,
        external_account_id=request.external_account_id,
        mode=request.mode,
        signal_type=request.signal_type,
        symbol=request.symbol,
        proposal_id=request.proposal_id,
        summary=request.summary,
        detail=request.detail,
        source=request.source,
        signal_payload=request.signal_payload,
        emitted_at=NOW,
        created_at=NOW,
    )
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )

    result = service.approve_proposal(
        "proposal-1",
        actor="operator-a",
        note="manual paper approval",
    )

    assert result.status == StrategyProposalStatus.APPROVED
    signal_request = experiments.create_signal.call_args.args[0]
    assert signal_request.source == "strategy_policy"
    assert signal_request.signal_payload["audit_event"] == "proposal_decision"
    assert signal_request.signal_payload["actor"] == "operator-a"
    assert signal_request.signal_payload["previous_status"] == "pending"
    assert signal_request.signal_payload["new_status"] == "approved"


def test_strategy_experiment_service_projects_audit_events_from_existing_ledgers() -> None:
    signal = build_signal().model_copy(
        update={
            "id": "signal-audit-1",
            "source": "strategy_policy",
            "proposal_id": "proposal-1",
            "signal_payload": {
                "audit_event": "proposal_decision",
                "action": "approve",
                "actor": "operator-a",
                "previous_status": "pending",
                "new_status": "approved",
            },
        }
    )
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    experiments.list_signals.return_value = [signal]
    experiments.list_advisor_runs.return_value = [build_advisor_run(StrategyAdvisorRunStatus.RECORDED)]
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )

    events = service.list_audit_events(
        external_account_id="LBPT10087357",
        limit=10,
    )

    proposal_event = next(event for event in events if event.id == "signal-audit-1")
    advisor_event = next(event for event in events if event.id == "advisor-run-advisor-run-1")
    assert proposal_event.actor == "operator-a"
    assert proposal_event.action == "approve"
    assert proposal_event.before == {"status": "pending"}
    assert proposal_event.after == {"status": "approved"}
    assert advisor_event.action == "advisor_run_card_recorded"


def test_strategy_experiment_service_blocks_advisor_proposal_without_manual_approval() -> None:
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )

    with pytest.raises(ValueError, match="manual approval"):
        service.create_proposal(
            CreateStrategyProposalRequest(
                strategy_id="covered_call_v1",
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                symbol="QQQ.US",
                title="Advisor covered-call idea",
                proposed_action="sell_covered_call",
                rationale="LLM advisor suggested testing this candidate.",
                approval_required=False,
                source="deepseek",
            )
        )

    experiments.create_proposal.assert_not_called()
    experiments.create_signal.assert_not_called()


def test_strategy_experiment_service_blocks_advisor_live_mode_proposal() -> None:
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )

    with pytest.raises(ValueError, match="live mode"):
        service.create_proposal(
            CreateStrategyProposalRequest(
                strategy_id="covered_call_v1",
                external_account_id="LBPT10087357",
                mode=ExecutionMode.LIVE,
                symbol="QQQ.US",
                title="Advisor live covered-call idea",
                proposed_action="sell_covered_call",
                rationale="LLM advisor suggested testing this candidate.",
                approval_required=True,
                source="deepseek",
            )
        )

    experiments.create_proposal.assert_not_called()
    experiments.create_signal.assert_not_called()


def test_strategy_experiment_service_records_advisor_proposal_audit_signal() -> None:
    proposal = StrategyProposal(
        id="proposal-llm-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="QQQ.US",
        title="Advisor covered-call idea",
        proposed_action="sell_covered_call",
        rationale="LLM advisor suggested testing this candidate.",
        source="deepseek",
        approval_required=True,
        checks=["local_risk_snapshot"],
        created_at=NOW,
        updated_at=NOW,
    )
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    experiments.create_proposal.return_value = proposal
    experiments.create_signal.side_effect = lambda request: StrategySignal(
        id="signal-advisor-audit",
        strategy_id=request.strategy_id,
        external_account_id=request.external_account_id,
        mode=request.mode,
        signal_type=request.signal_type,
        symbol=request.symbol,
        proposal_id=request.proposal_id,
        summary=request.summary,
        detail=request.detail,
        source=request.source,
        signal_payload=request.signal_payload,
        emitted_at=NOW,
        created_at=NOW,
    )
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )

    result = service.create_proposal(
        CreateStrategyProposalRequest(
            strategy_id="covered_call_v1",
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            symbol="QQQ.US",
            title="Advisor covered-call idea",
            proposed_action="sell_covered_call",
            rationale="LLM advisor suggested testing this candidate.",
            source="deepseek",
            checks=["local_risk_snapshot"],
        )
    )

    assert result.id == "proposal-llm-1"
    signal_request = experiments.create_signal.call_args.args[0]
    assert signal_request.source == "strategy_policy"
    assert signal_request.signal_payload["audit_event"] == "advisor_proposal_recorded"
    assert signal_request.signal_payload["advisor_source"] == "deepseek"
    assert signal_request.signal_payload["llm_direct_execution_allowed"] is False
    assert signal_request.signal_payload["checks"] == ["local_risk_snapshot"]


def test_strategy_experiment_service_builds_advisor_context() -> None:
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    experiments.list_proposals.side_effect = [
        [build_proposal()],
        [build_covered_call_proposal(status=StrategyProposalStatus.CLOSED)],
    ]
    experiments.list_runs.side_effect = [[build_run()], []]
    experiments.list_signals.side_effect = [[build_signal()], []]
    experiments.list_reviews.side_effect = [[build_review()], []]
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )

    context = service.get_advisor_context(
        external_account_id="LBPT10087357",
        limit=6,
    )

    assert context.controls.llm_direct_execution_allowed is False
    assert context.experiment.proposals[0].id == "proposal-1"
    assert context.covered_call_activity.summary.total_proposals == 1
    assert context.advisor_sources[0] == "deepseek"
    assert context.hard_rules[0].name == "advisor_context_is_read_only"
    assert [playbook.id for playbook in context.playbooks] == [
        "bull_put_v1",
        "covered_call_v1",
        "zero_dte_lottery_v1",
    ]
    experiments.list_proposals.assert_any_call(
        external_account_id="LBPT10087357",
        strategy_id=None,
        status=None,
        limit=6,
    )
    experiments.list_proposals.assert_any_call(
        external_account_id="LBPT10087357",
        strategy_id="covered_call_v1",
        status=None,
        limit=6,
    )


def test_strategy_experiment_service_records_and_lists_advisor_runs() -> None:
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    advisor_run = build_advisor_run()
    experiments.create_advisor_run.return_value = advisor_run
    experiments.list_advisor_runs.return_value = [advisor_run]
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )

    created = service.create_advisor_run(
        CreateStrategyAdvisorRunRequest(
            external_account_id="LBPT10087357",
            source="deepseek",
            mode=ExecutionMode.PAPER,
            provider="deepseek",
            model="deepseek-v4-pro",
            status=StrategyAdvisorRunStatus.SUCCEEDED,
            context_format="compact_v1",
            context_limit=6,
            prompt_tokens=100,
        )
    )
    runs = service.list_advisor_runs(
        external_account_id="LBPT10087357",
        source="deepseek",
        limit=5,
    )

    assert created.id == "advisor-run-1"
    assert runs == [advisor_run]
    experiments.create_advisor_run.assert_called_once()
    experiments.list_advisor_runs.assert_called_once_with(
        external_account_id="LBPT10087357",
        source="deepseek",
        limit=5,
    )


def test_strategy_experiment_service_builds_advisor_audit_snapshot() -> None:
    experiments = Mock()
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    latest_run = build_advisor_run(StrategyAdvisorRunStatus.RECORDED).model_copy(
        update={
            "proposal_count": 1,
            "response_payload": {
                **(build_advisor_run(StrategyAdvisorRunStatus.RECORDED).response_payload or {}),
                "proposals": [
                    {
                        "strategy_id": "covered_call_v1",
                        "title": "Advisor covered-call idea",
                        "proposed_action": "sell_covered_call",
                    }
                ],
            },
        }
    )
    older_run = build_advisor_run(StrategyAdvisorRunStatus.SUCCEEDED).model_copy(
        update={
            "id": "advisor-run-older",
            "total_tokens": 150,
            "cache_hit_tokens": 30,
            "cache_miss_tokens": 120,
            "proposal_count": 0,
            "review_count": 0,
        }
    )
    linked_proposal = build_covered_call_proposal(
        proposal_id="proposal-advisor-1",
        status=StrategyProposalStatus.PENDING,
    ).model_copy(
        update={
            "source": "deepseek",
            "source_run_id": latest_run.id,
            "approval_required": True,
            "candidate_payload": {
                "advisor_run_id": latest_run.id,
                "llm_direct_execution_allowed": False,
            },
        }
    )
    linked_review = build_review().model_copy(
        update={
            "id": "review-advisor-1",
            "strategy_id": "covered_call_v1",
            "status": StrategyReviewStatus.OBSERVED,
            "metrics_payload": {
                "advisor_run_id": latest_run.id,
                "llm_direct_execution_allowed": False,
            },
        }
    )
    experiments.list_advisor_runs.return_value = [latest_run, older_run]
    experiments.list_proposals.return_value = [linked_proposal]
    experiments.list_reviews.return_value = [linked_review]
    service = StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )

    audit = service.get_advisor_audit_snapshot(
        external_account_id="LBPT10087357",
        source="deepseek",
        limit=5,
    )

    assert audit.runs[0].record_state == "recorded"
    assert audit.runs[0].response_payload["advisor_run_id"] == "advisor-run-1"
    assert audit.runs[0].token_usage["total_tokens"] == 120
    assert audit.runs[0].comparison is not None
    assert audit.runs[0].comparison.previous_run_id == "advisor-run-older"
    assert audit.runs[0].comparison.total_tokens_delta == -30
    assert audit.runs[0].comparison.cache_hit_tokens_delta == 10
    assert audit.runs[0].downstream_impact.proposal_ids == ["proposal-advisor-1"]
    assert audit.runs[0].downstream_impact.review_ids == ["review-advisor-1"]
    assert audit.runs[0].downstream_impact.proposal_status_counts == {"pending": 1}
    assert {check.name: check.status for check in audit.runs[0].checks}[
        "record_counts_match_downstream"
    ] == "pass"
    assert {check.name: check.status for check in audit.runs[0].checks}[
        "advisor_metadata_blocks_direct_execution"
    ] == "pass"
    experiments.list_advisor_runs.assert_called_once_with(
        external_account_id="LBPT10087357",
        source="deepseek",
        limit=5,
    )

    cards = service.list_advisor_run_cards(
        external_account_id="LBPT10087357",
        source="deepseek",
        limit=5,
    )

    assert cards[0].run_id == "advisor-run-1"
    assert cards[0].recorded is True
    assert cards[0].context_hash
    assert cards[0].downstream_proposal_ids == ["proposal-advisor-1"]


def test_create_strategy_run_signal_and_review_routes() -> None:
    service = Mock()
    service.create_run.return_value = build_run()
    service.create_signal.return_value = build_signal()
    service.create_review.return_value = build_review()

    client = with_experiment_service(service)
    try:
        run_response = client.post(
            "/strategies/runs",
            json={
                "strategy_id": "paper_bull_put_v1",
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "run_type": "preview",
                "status": "executed",
                "symbol": "QQQ.US",
                "summary": "Preview returned an eligible candidate.",
            },
        )
        signal_response = client.post(
            "/strategies/signals",
            json={
                "strategy_id": "paper_bull_put_v1",
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "signal_type": "candidate",
                "symbol": "QQQ.US",
                "summary": "Candidate survived liquidity filters.",
            },
        )
        review_response = client.post(
            "/strategies/reviews",
            json={
                "strategy_id": "paper_bull_put_v1",
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "review_type": "runtime",
                "status": "observed",
                "summary": "Monitor one existing open spread.",
                "recommendation": "Do not add another correlated spread while QQQ is open.",
            },
        )
    finally:
        clear_overrides()

    assert run_response.status_code == 201
    assert signal_response.status_code == 201
    assert review_response.status_code == 201
    assert run_response.json()["id"] == "run-1"
    assert signal_response.json()["id"] == "signal-1"
    assert review_response.json()["id"] == "review-1"

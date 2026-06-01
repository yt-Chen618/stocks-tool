from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_strategy_experiment_service
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.domain.enums import (
    ExecutionMode,
    StrategyProposalStatus,
    StrategyReviewStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    CoveredCallActivitySnapshot,
    CoveredCallActivitySummary,
    StrategyExperimentSnapshot,
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


def build_covered_call_run(run_type: str = "proposal_close") -> StrategyRun:
    return StrategyRun(
        id=f"run-{run_type}",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        run_type=run_type,
        status=StrategyRunStatus.EXECUTED,
        symbol="UNH.US",
        summary="Covered-call action recorded.",
        started_at=NOW,
        completed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
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
    service.approve_proposal.assert_called_once_with("proposal-1")


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

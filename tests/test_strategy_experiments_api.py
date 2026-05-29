from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_strategy_experiment_service
from stocks_tool.domain.enums import (
    ExecutionMode,
    StrategyProposalStatus,
    StrategyReviewStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
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

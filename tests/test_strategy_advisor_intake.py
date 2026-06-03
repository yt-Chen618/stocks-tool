from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_strategy_advisor_intake_service
from stocks_tool.application.services.strategy_advisor_intake import StrategyAdvisorIntakeService
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    ExecutionMode,
    StrategyProposalStatus,
    StrategyReviewStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    CoveredCallActivitySnapshot,
    CoveredCallActivitySummary,
    RecordStrategyAdvisorResponseRequest,
    StrategyAdvisorContext,
    StrategyAdvisorProposalDraft,
    StrategyAdvisorResponseResult,
    StrategyAdvisorReviewDraft,
    StrategyControlSnapshot,
    StrategyExperimentSnapshot,
    StrategyPermissionBoundary,
    StrategyProposal,
    StrategyReview,
    StrategySignal,
)
from stocks_tool.main import app


NOW = datetime(2026, 6, 3, 14, 0, tzinfo=timezone.utc)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def build_context() -> StrategyAdvisorContext:
    controls = StrategyControlSnapshot(
        external_account_id="LBPT10087357",
        execution_mode=ExecutionMode.PAPER,
        live_trading_enabled=False,
        scheduler_enabled=True,
    )
    return StrategyAdvisorContext(
        external_account_id="LBPT10087357",
        controls=controls,
        experiment=StrategyExperimentSnapshot(external_account_id="LBPT10087357"),
        covered_call_activity=CoveredCallActivitySnapshot(
            external_account_id="LBPT10087357",
            summary=CoveredCallActivitySummary(external_account_id="LBPT10087357"),
        ),
        advisor_sources=["deepseek", "llm", "openai"],
        hard_rules=[
            StrategyPermissionBoundary(
                name="advisor_context_is_read_only",
                allowed=False,
                detail="Advisor context cannot submit broker orders.",
            ),
            StrategyPermissionBoundary(
                name="advisor_proposals_require_manual_approval",
                allowed=True,
                detail="Advisor proposals must require manual approval.",
            ),
        ],
    )


def build_strategy_experiment_service(experiments: Mock) -> StrategyExperimentService:
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = object()
    experiments.list_proposals.side_effect = [[], []]
    experiments.list_runs.side_effect = [[], []]
    experiments.list_signals.side_effect = [[], []]
    experiments.list_reviews.side_effect = [[], []]
    return StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )


def test_strategy_advisor_intake_records_response_as_read_only_ledger_entries() -> None:
    experiments = Mock()

    def create_proposal(request):
        return StrategyProposal(
            id="proposal-advisor-1",
            strategy_id=request.strategy_id,
            external_account_id=request.external_account_id,
            mode=request.mode,
            symbol=request.symbol,
            title=request.title,
            proposed_action=request.proposed_action,
            rationale=request.rationale,
            status=StrategyProposalStatus.PENDING,
            approval_required=request.approval_required,
            source=request.source,
            candidate_payload=request.candidate_payload,
            risk_payload=request.risk_payload,
            checks=request.checks,
            created_at=NOW,
            updated_at=NOW,
        )

    def create_review(request):
        return StrategyReview(
            id="review-advisor-1",
            strategy_id=request.strategy_id,
            external_account_id=request.external_account_id,
            mode=request.mode,
            review_type=request.review_type,
            status=request.status,
            summary=request.summary,
            recommendation=request.recommendation,
            metrics_payload=request.metrics_payload,
            reviewed_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )

    experiments.create_proposal.side_effect = create_proposal
    experiments.create_review.side_effect = create_review
    experiments.create_signal.side_effect = lambda request: StrategySignal(
        id="signal-advisor-policy",
        strategy_id=request.strategy_id,
        external_account_id=request.external_account_id,
        mode=request.mode,
        signal_type=StrategySignalType.REVIEW,
        symbol=request.symbol,
        proposal_id=request.proposal_id,
        summary=request.summary,
        detail=request.detail,
        source=request.source,
        signal_payload=request.signal_payload,
        emitted_at=NOW,
        created_at=NOW,
    )
    service = StrategyAdvisorIntakeService(
        strategy_experiments=build_strategy_experiment_service(experiments),
    )

    result = service.record_response(
        RecordStrategyAdvisorResponseRequest(
            external_account_id="LBPT10087357",
            source="DeepSeek",
            proposals=[
                StrategyAdvisorProposalDraft(
                    strategy_id="covered_call_v1",
                    symbol="QQQ.US",
                    title="Advisor covered-call idea",
                    proposed_action="sell_covered_call",
                    rationale="Advisor sees premium as attractive, pending local checks.",
                    confidence=Decimal("0.62"),
                    candidate_payload={"call_symbol": "QQQ260626C764000.US"},
                    checks=["advisor_observed_premium"],
                )
            ],
            reviews=[
                StrategyAdvisorReviewDraft(
                    strategy_id="covered_call_v1",
                    status=StrategyReviewStatus.SUGGESTED,
                    summary="Review QQQ covered-call premium after local liquidity checks.",
                    recommendation="Keep this as advice until deterministic checks pass.",
                )
            ],
            raw_response={"model": "deepseek-chat", "response_id": "resp-1"},
        )
    )

    assert result.source == "deepseek"
    assert result.mode == ExecutionMode.PAPER
    assert result.context.controls.llm_direct_execution_allowed is False
    proposal_request = experiments.create_proposal.call_args.args[0]
    assert proposal_request.mode == ExecutionMode.PAPER
    assert proposal_request.approval_required is True
    assert proposal_request.source == "deepseek"
    assert "manual_approval_required" in proposal_request.checks
    assert "local_deterministic_checks_required" in proposal_request.checks
    assert "local_position_covered" not in proposal_request.checks
    assert proposal_request.candidate_payload["llm_direct_execution_allowed"] is False
    assert proposal_request.candidate_payload["advisor_raw_response"]["response_id"] == "resp-1"
    review_request = experiments.create_review.call_args.args[0]
    assert review_request.mode == ExecutionMode.PAPER
    assert review_request.metrics_payload["advisor_source"] == "deepseek"
    assert review_request.metrics_payload["llm_direct_execution_allowed"] is False
    signal_request = experiments.create_signal.call_args.args[0]
    assert signal_request.signal_payload["llm_direct_execution_allowed"] is False


def test_strategy_advisor_intake_rejects_live_mode_before_writing() -> None:
    experiments = Mock()
    service = StrategyAdvisorIntakeService(
        strategy_experiments=build_strategy_experiment_service(experiments),
    )

    with pytest.raises(ValueError, match="paper mode"):
        service.record_response(
            RecordStrategyAdvisorResponseRequest(
                external_account_id="LBPT10087357",
                source="deepseek",
                mode=ExecutionMode.LIVE,
                reviews=[
                    StrategyAdvisorReviewDraft(
                        strategy_id="covered_call_v1",
                        summary="Do not record live advisor advice.",
                    )
                ],
            )
        )

    experiments.create_proposal.assert_not_called()
    experiments.create_review.assert_not_called()
    experiments.create_signal.assert_not_called()


def test_strategy_advisor_intake_rejects_unknown_source() -> None:
    experiments = Mock()
    service = StrategyAdvisorIntakeService(
        strategy_experiments=build_strategy_experiment_service(experiments),
    )

    with pytest.raises(ValueError, match="not recognized"):
        service.record_response(
            RecordStrategyAdvisorResponseRequest(
                external_account_id="LBPT10087357",
                source="untrusted-bot",
                reviews=[
                    StrategyAdvisorReviewDraft(
                        strategy_id="covered_call_v1",
                        summary="Unknown source should not enter the advisor ledger.",
                    )
                ],
            )
        )

    experiments.create_proposal.assert_not_called()
    experiments.create_review.assert_not_called()


def test_strategy_advisor_response_route_records_response() -> None:
    service = Mock()
    service.record_response.return_value = StrategyAdvisorResponseResult(
        external_account_id="LBPT10087357",
        source="deepseek",
        mode=ExecutionMode.PAPER,
        context=build_context(),
        proposals=[
            StrategyProposal(
                id="proposal-advisor-1",
                strategy_id="covered_call_v1",
                external_account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                symbol="QQQ.US",
                title="Advisor covered-call idea",
                proposed_action="sell_covered_call",
                rationale="Advisor sees premium as attractive.",
                status=StrategyProposalStatus.PENDING,
                source="deepseek",
                approval_required=True,
                created_at=NOW,
                updated_at=NOW,
            )
        ],
        reviews=[],
        recorded_at=NOW,
    )
    app.dependency_overrides[get_strategy_advisor_intake_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.post(
            "/strategies/advisor/responses",
            json={
                "external_account_id": "LBPT10087357",
                "source": "deepseek",
                "proposals": [
                    {
                        "strategy_id": "covered_call_v1",
                        "symbol": "QQQ.US",
                        "title": "Advisor covered-call idea",
                        "proposed_action": "sell_covered_call",
                        "rationale": "Advisor sees premium as attractive.",
                    }
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["source"] == "deepseek"
    assert body["proposals"][0]["approval_required"] is True
    request = service.record_response.call_args.args[0]
    assert request.external_account_id == "LBPT10087357"
    assert request.proposals[0].strategy_id == "covered_call_v1"

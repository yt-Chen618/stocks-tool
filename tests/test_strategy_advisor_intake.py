from datetime import datetime, timezone
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
    StrategyAdvisorRunStatus,
    StrategyProposalStatus,
    StrategyReviewStatus,
)
from stocks_tool.domain.models import (
    CoveredCallActivitySnapshot,
    CoveredCallActivitySummary,
    RecordStrategyAdvisorResponseRequest,
    StrategyAdvisorContext,
    StrategyAdvisorProposalDraft,
    StrategyAdvisorResponseResult,
    StrategyAdvisorReviewDraft,
    StrategyAdvisorRun,
    StrategyControlSnapshot,
    StrategyExperimentSnapshot,
    StrategyPermissionBoundary,
    StrategyProposal,
    StrategyReview,
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
    experiments.iter_proposals.return_value = []
    experiments.iter_runs.return_value = []
    experiments.iter_signals.return_value = []
    experiments.list_latest_runs_by_proposal.return_value = []
    return StrategyExperimentService(
        experiments=experiments,
        broker_accounts=broker_accounts,
        settings=Settings(),
    )


def test_strategy_advisor_intake_records_response_as_read_only_ledger_entries() -> None:
    experiments = Mock()

    def record_advisor_intake(**kwargs):
        proposal_request = kwargs["proposal_requests"][0]
        review_request = kwargs["review_requests"][0]
        proposal = StrategyProposal(
            id="proposal-advisor-1",
            strategy_id=proposal_request.strategy_id,
            external_account_id=proposal_request.external_account_id,
            mode=proposal_request.mode,
            symbol=proposal_request.symbol,
            title=proposal_request.title,
            proposed_action=proposal_request.proposed_action,
            rationale=proposal_request.rationale,
            status=StrategyProposalStatus.PENDING,
            approval_required=proposal_request.approval_required,
            source=proposal_request.source,
            source_run_id=proposal_request.source_run_id,
            candidate_payload=proposal_request.candidate_payload,
            risk_payload=proposal_request.risk_payload,
            checks=proposal_request.checks,
            created_at=NOW,
            updated_at=NOW,
        )
        review = StrategyReview(
            id="review-advisor-1",
            strategy_id=review_request.strategy_id,
            external_account_id=review_request.external_account_id,
            mode=review_request.mode,
            review_type=review_request.review_type,
            status=review_request.status,
            summary=review_request.summary,
            recommendation=review_request.recommendation,
            run_id=review_request.run_id,
            metrics_payload=review_request.metrics_payload,
            reviewed_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        )
        return [proposal], [review], experiments.advisor_run_result

    experiments.advisor_run_result = StrategyAdvisorRun(
        id="advisor-run-1",
        external_account_id="LBPT10087357",
        source="deepseek",
        mode=ExecutionMode.PAPER,
        provider="deepseek",
        model="deepseek-v4-pro",
        status=StrategyAdvisorRunStatus.RECORDED,
        created_at=NOW,
        updated_at=NOW,
        recorded_at=NOW,
    )
    experiments.record_advisor_intake.side_effect = record_advisor_intake

    service = StrategyAdvisorIntakeService(
        strategy_experiments=build_strategy_experiment_service(experiments),
    )

    result = service.record_response(
        RecordStrategyAdvisorResponseRequest(
            external_account_id="LBPT10087357",
            source="DeepSeek",
            advisor_run_id="advisor-run-1",
            proposals=[
                StrategyAdvisorProposalDraft(
                    strategy_id="covered_call_v1",
                    symbol="QQQ.US",
                    title="Advisor covered-call idea",
                    proposed_action="sell_covered_call",
                    rationale="Advisor sees premium as attractive, pending local checks.",
                    confidence=Decimal("0.62"),
                    candidate_payload={
                        "call_symbol": "QQQ260626C764000.US",
                        "business_key": "keep",
                        "advisor_source": "spoofed-source",
                        "advisor_run_id": "spoofed-run",
                        "llm_direct_execution_allowed": True,
                        "advisor_hard_rules": ["spoofed-rule"],
                        "advisor_raw_response": {"spoofed": True},
                    },
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
    assert result.advisor_run is not None
    assert result.advisor_run.id == "advisor-run-1"
    command_kwargs = experiments.record_advisor_intake.call_args.kwargs
    proposal_request = command_kwargs["proposal_requests"][0]
    assert proposal_request.mode == ExecutionMode.PAPER
    assert proposal_request.approval_required is True
    assert proposal_request.source == "deepseek"
    assert proposal_request.source_run_id == "advisor-run-1"
    assert "manual_approval_required" in proposal_request.checks
    assert "local_deterministic_checks_required" in proposal_request.checks
    assert "local_position_covered" not in proposal_request.checks
    assert proposal_request.candidate_payload["llm_direct_execution_allowed"] is False
    assert proposal_request.candidate_payload["advisor_source"] == "deepseek"
    assert proposal_request.candidate_payload["advisor_run_id"] == "advisor-run-1"
    assert proposal_request.candidate_payload["advisor_hard_rules"] == [
        rule.name for rule in result.context.hard_rules
    ]
    assert proposal_request.candidate_payload["business_key"] == "keep"
    assert proposal_request.candidate_payload["advisor_raw_response"]["response_id"] == "resp-1"
    review_request = command_kwargs["review_requests"][0]
    assert review_request.mode == ExecutionMode.PAPER
    assert review_request.metrics_payload["advisor_source"] == "deepseek"
    assert review_request.metrics_payload["advisor_run_id"] == "advisor-run-1"
    assert review_request.metrics_payload["llm_direct_execution_allowed"] is False
    assert command_kwargs["advisor_run_id"] == "advisor-run-1"
    assert command_kwargs["response_payload"]["source"] == "deepseek"


def test_advisor_metadata_overwrites_untrusted_provenance_and_removes_run_without_id() -> None:
    enriched = StrategyAdvisorIntakeService._with_advisor_metadata(
        {
            "business_key": "keep",
            "advisor_source": "spoofed-source",
            "advisor_run_id": "spoofed-run",
            "llm_direct_execution_allowed": True,
            "advisor_hard_rules": ["spoofed-rule"],
            "advisor_raw_response": {"spoofed": True},
        },
        source="deepseek",
        context=build_context(),
        raw_response={"response_id": "actual"},
        advisor_run_id=None,
    )

    assert enriched["business_key"] == "keep"
    assert enriched["advisor_source"] == "deepseek"
    assert "advisor_run_id" not in enriched
    assert enriched["llm_direct_execution_allowed"] is False
    assert enriched["advisor_hard_rules"] == [
        "advisor_context_is_read_only",
        "advisor_proposals_require_manual_approval",
    ]
    assert enriched["advisor_raw_response"] == {"response_id": "actual"}


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

    experiments.record_advisor_intake.assert_not_called()


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

    experiments.record_advisor_intake.assert_not_called()


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

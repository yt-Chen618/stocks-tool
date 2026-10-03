from datetime import datetime, timezone

from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    CreateStrategyProposalRequest,
    CreateStrategyReviewRequest,
    RecordStrategyAdvisorResponseRequest,
    StrategyAdvisorContext,
    StrategyAdvisorProposalDraft,
    StrategyAdvisorResponseResult,
    StrategyAdvisorReviewDraft,
)


class StrategyAdvisorIntakeService:
    advisor_checks = (
        "advisor_context_read_only",
        "manual_approval_required",
        "local_deterministic_checks_required",
    )

    def __init__(
        self,
        *,
        strategy_experiments: StrategyExperimentService,
    ) -> None:
        self.strategy_experiments = strategy_experiments

    def record_response(
        self,
        request: RecordStrategyAdvisorResponseRequest,
    ) -> StrategyAdvisorResponseResult:
        if request.mode != ExecutionMode.PAPER:
            raise ValueError("Advisor responses can only be recorded in paper mode.")
        if not request.proposals and not request.reviews:
            raise ValueError("Advisor response must include at least one proposal or review.")

        source = self._normalize_source(request.source)
        context = self.strategy_experiments.get_advisor_context(
            external_account_id=request.external_account_id,
            limit=request.context_limit,
        )
        self._assert_source_allowed(source, context)

        proposal_requests = [
            self._proposal_request(request=request, source=source, context=context, draft=draft)
            for draft in request.proposals
        ]
        review_requests = [
            self._review_request(request=request, source=source, context=context, draft=draft)
            for draft in request.reviews
        ]
        response_payload = request.model_dump(mode="json", exclude_none=True)
        response_payload["source"] = source
        proposals, reviews, advisor_run = self.strategy_experiments.record_advisor_response(
            external_account_id=request.external_account_id,
            source=source,
            mode=ExecutionMode.PAPER,
            advisor_run_id=request.advisor_run_id,
            proposal_requests=proposal_requests,
            review_requests=review_requests,
            response_payload=response_payload,
            recorded_at=datetime.now(timezone.utc),
        )
        return StrategyAdvisorResponseResult(
            external_account_id=request.external_account_id,
            source=source,
            mode=ExecutionMode.PAPER,
            context=context,
            proposals=proposals,
            reviews=reviews,
            advisor_run=advisor_run,
            recorded_at=datetime.now(timezone.utc),
        )

    def _proposal_request(
        self,
        *,
        request: RecordStrategyAdvisorResponseRequest,
        source: str,
        context: StrategyAdvisorContext,
        draft: StrategyAdvisorProposalDraft,
    ) -> CreateStrategyProposalRequest:
        return CreateStrategyProposalRequest(
            strategy_id=draft.strategy_id,
            external_account_id=request.external_account_id,
            mode=ExecutionMode.PAPER,
            symbol=draft.symbol,
            title=draft.title,
            proposed_action=draft.proposed_action,
            thesis=draft.thesis,
            rationale=draft.rationale,
            confidence=draft.confidence,
            expected_max_loss=draft.expected_max_loss,
            expected_max_profit=draft.expected_max_profit,
            approval_required=True,
            expires_at=draft.expires_at,
            source=source,
            source_run_id=request.advisor_run_id,
            candidate_payload=self._with_advisor_metadata(
                draft.candidate_payload,
                source=source,
                context=context,
                raw_response=request.raw_response,
                advisor_run_id=request.advisor_run_id,
            ),
            risk_payload=self._with_advisor_metadata(
                draft.risk_payload,
                source=source,
                context=context,
                raw_response=None,
                advisor_run_id=request.advisor_run_id,
            ),
            checks=self._merge_checks(draft.checks),
        )

    def _review_request(
        self,
        *,
        request: RecordStrategyAdvisorResponseRequest,
        source: str,
        context: StrategyAdvisorContext,
        draft: StrategyAdvisorReviewDraft,
    ) -> CreateStrategyReviewRequest:
        return CreateStrategyReviewRequest(
            strategy_id=draft.strategy_id,
            external_account_id=request.external_account_id,
            mode=ExecutionMode.PAPER,
            review_type=draft.review_type,
            status=draft.status,
            summary=draft.summary,
            recommendation=draft.recommendation,
            parameter_name=draft.parameter_name,
            current_value=draft.current_value,
            suggested_value=draft.suggested_value,
            run_id=request.advisor_run_id,
            proposal_id=draft.proposal_id,
            metrics_payload=self._with_advisor_metadata(
                draft.metrics_payload,
                source=source,
                context=context,
                raw_response=request.raw_response,
                advisor_run_id=request.advisor_run_id,
            ),
            reviewed_at=draft.reviewed_at,
        )

    @classmethod
    def _merge_checks(cls, checks: list[str]) -> list[str]:
        merged: list[str] = []
        for check in [*checks, *cls.advisor_checks]:
            normalized = check.strip()
            if normalized and normalized not in merged:
                merged.append(normalized)
        return merged

    @staticmethod
    def _with_advisor_metadata(
        payload: dict | None,
        *,
        source: str,
        context: StrategyAdvisorContext,
        raw_response: dict | None,
        advisor_run_id: str | None,
    ) -> dict:
        enriched = dict(payload or {})
        # These fields are local provenance and safety controls.  They must
        # never be accepted from an advisor payload, even when the payload is
        # otherwise preserved for research-specific business data.
        enriched["advisor_source"] = source
        if advisor_run_id is not None:
            enriched["advisor_run_id"] = advisor_run_id
        else:
            enriched.pop("advisor_run_id", None)
        enriched["llm_direct_execution_allowed"] = False
        enriched["advisor_hard_rules"] = [rule.name for rule in context.hard_rules]
        if raw_response is not None:
            enriched["advisor_raw_response"] = raw_response
        else:
            enriched.pop("advisor_raw_response", None)
        return enriched

    @staticmethod
    def _normalize_source(source: str) -> str:
        normalized = source.strip().lower()
        if not normalized:
            raise ValueError("Advisor source is required.")
        return normalized

    @staticmethod
    def _assert_source_allowed(source: str, context: StrategyAdvisorContext) -> None:
        allowed_sources = {candidate.strip().lower() for candidate in context.advisor_sources}
        if source not in allowed_sources:
            raise ValueError(f"Advisor source '{source}' is not recognized.")

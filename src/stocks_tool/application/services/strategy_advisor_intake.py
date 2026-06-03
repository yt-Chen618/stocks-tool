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
    StrategyProposal,
    StrategyReview,
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

        proposals = [
            self._record_proposal(request=request, source=source, context=context, draft=draft)
            for draft in request.proposals
        ]
        reviews = [
            self._record_review(request=request, source=source, context=context, draft=draft)
            for draft in request.reviews
        ]
        response_payload = request.model_dump(mode="json", exclude_none=True)
        advisor_run = (
            self.strategy_experiments.mark_advisor_run_recorded(
                request.advisor_run_id,
                proposal_count=len(proposals),
                review_count=len(reviews),
                response_payload=response_payload,
            )
            if request.advisor_run_id
            else None
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

    def _record_proposal(
        self,
        *,
        request: RecordStrategyAdvisorResponseRequest,
        source: str,
        context: StrategyAdvisorContext,
        draft: StrategyAdvisorProposalDraft,
    ) -> StrategyProposal:
        return self.strategy_experiments.create_proposal(
            CreateStrategyProposalRequest(
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
        )

    def _record_review(
        self,
        *,
        request: RecordStrategyAdvisorResponseRequest,
        source: str,
        context: StrategyAdvisorContext,
        draft: StrategyAdvisorReviewDraft,
    ) -> StrategyReview:
        return self.strategy_experiments.create_review(
            CreateStrategyReviewRequest(
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
        enriched.setdefault("advisor_source", source)
        if advisor_run_id is not None:
            enriched.setdefault("advisor_run_id", advisor_run_id)
        enriched.setdefault("llm_direct_execution_allowed", False)
        enriched.setdefault("advisor_hard_rules", [rule.name for rule in context.hard_rules])
        if raw_response is not None:
            enriched.setdefault("advisor_raw_response", raw_response)
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

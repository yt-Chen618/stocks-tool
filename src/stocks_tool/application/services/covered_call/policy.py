from __future__ import annotations

from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import StrategyProposal


ADVISOR_SOURCES = {"deepseek", "llm", "llm_advisor", "openai", "external_advisor"}


def assert_order_execution_policy(
    *,
    proposal: StrategyProposal,
    action: str,
    required_checks: set[str],
    require_manual_approval: bool,
    allow_live_trading: bool,
    advisor_sources: set[str] = ADVISOR_SOURCES,
) -> None:
    if proposal.mode == ExecutionMode.LIVE and not allow_live_trading:
        raise PermissionError(
            f"{action} is blocked because live execution is disabled by ALLOW_LIVE_TRADING."
        )
    if require_manual_approval and not proposal.approval_required:
        raise PermissionError(f"{action} requires a proposal that cannot bypass manual approval.")
    source = (proposal.source or "").strip().lower()
    if source in advisor_sources:
        missing_checks = sorted(required_checks.difference(set(proposal.checks)))
        if missing_checks:
            raise PermissionError(
                f"{action} is blocked for advisor-sourced proposal '{proposal.id}' until local checks are present: "
                + ", ".join(missing_checks)
            )

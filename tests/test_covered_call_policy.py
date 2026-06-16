from datetime import datetime, timezone

import pytest

from stocks_tool.application.services.covered_call.policy import assert_order_execution_policy
from stocks_tool.domain.enums import ExecutionMode, StrategyProposalStatus
from stocks_tool.domain.models import StrategyProposal


NOW = datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)


def _proposal(**updates) -> StrategyProposal:
    proposal = StrategyProposal(
        id="proposal-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="UNH.US",
        title="Sell UNH covered call",
        proposed_action="sell_covered_call",
        rationale="Covered lot has a liquid OTM call.",
        status=StrategyProposalStatus.APPROVED,
        approval_required=True,
        checks=["manual_approval_required", "covered_position_still_valid"],
        created_at=NOW,
        updated_at=NOW,
    )
    return proposal.model_copy(update=updates)


def test_order_execution_policy_blocks_live_when_live_trading_disabled() -> None:
    with pytest.raises(PermissionError, match="live execution is disabled"):
        assert_order_execution_policy(
            proposal=_proposal(mode=ExecutionMode.LIVE),
            action="Covered call execution",
            required_checks=set(),
            require_manual_approval=True,
            allow_live_trading=False,
        )


def test_order_execution_policy_blocks_manual_approval_bypass() -> None:
    with pytest.raises(PermissionError, match="cannot bypass manual approval"):
        assert_order_execution_policy(
            proposal=_proposal(approval_required=False),
            action="Covered call execution",
            required_checks=set(),
            require_manual_approval=True,
            allow_live_trading=False,
        )


def test_order_execution_policy_blocks_advisor_source_until_local_checks_exist() -> None:
    with pytest.raises(PermissionError, match="covered_position_still_valid"):
        assert_order_execution_policy(
            proposal=_proposal(source="deepseek", checks=["manual_approval_required"]),
            action="Covered call execution",
            required_checks={"manual_approval_required", "covered_position_still_valid"},
            require_manual_approval=True,
            allow_live_trading=False,
        )


def test_order_execution_policy_allows_advisor_source_after_local_checks_exist() -> None:
    assert_order_execution_policy(
        proposal=_proposal(source="deepseek"),
        action="Covered call execution",
        required_checks={"manual_approval_required", "covered_position_still_valid"},
        require_manual_approval=True,
        allow_live_trading=False,
    )

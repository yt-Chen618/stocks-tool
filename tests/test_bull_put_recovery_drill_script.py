from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.append(str(SCRIPTS_DIR))

from run_bull_put_recovery_drill import operator_action  # noqa: E402


def test_recovery_drill_operator_action_allows_eligible_recovery() -> None:
    assert operator_action({"eligible": True, "reasons": []}) == "manual_recover_close_allowed"


def test_recovery_drill_operator_action_classifies_common_blocks() -> None:
    assert operator_action({"eligible": False, "reasons": ["close_not_required"]}) == "observe_no_recovery"
    assert (
        operator_action({"eligible": False, "reasons": ["working_replacement_exists"]})
        == "monitor_existing_replacement"
    )
    assert operator_action({"eligible": False, "reasons": ["account_mismatch"]}) == "fix_request_context"

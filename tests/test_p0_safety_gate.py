from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.append(str(SCRIPTS_DIR))

from check_alembic_head_current import compare_heads  # noqa: E402
from run_p0_safety_gate import child_specs  # noqa: E402


def test_p0_safety_gate_is_broker_read_only_and_covers_required_checks(tmp_path: Path) -> None:
    specs = child_specs(
        Namespace(
            base_url="http://127.0.0.1:8000",
            account_id="LBPT10087357",
            skip_running_api_checks=False,
        ),
        tmp_path,
    )

    names = {spec["name"] for spec in specs}
    assert {
        "pytest",
        "py-compile-scripts",
        "alembic-heads",
        "alembic-current",
        "alembic-head-current-match",
        "order-idempotency-preflight",
        "postgres-order-concurrency",
        "mock-ui",
        "consistency-report",
        "git-diff-check",
    } <= names

    rendered = "\n".join(" ".join(spec["command"]) for spec in specs)
    assert "--execute" not in rendered
    assert "--force-scan" not in rendered
    assert "--confirm-paper-scan" not in rendered
    assert "/repairs/" not in rendered


def test_p0_safety_gate_can_skip_checks_that_need_a_running_api(tmp_path: Path) -> None:
    specs = child_specs(
        Namespace(
            base_url="http://127.0.0.1:8000",
            account_id="LBPT10087357",
            skip_running_api_checks=True,
        ),
        tmp_path,
    )

    assert "consistency-report" not in {spec["name"] for spec in specs}


def test_alembic_head_current_match_requires_one_equal_revision() -> None:
    assert compare_heads(("20260711_0016",), ("20260711_0016",)) is True
    assert compare_heads(("head-a", "head-b"), ("head-a",)) is False
    assert compare_heads(("head-a",), ("old-revision",)) is False
    assert compare_heads(("head-a",), ()) is False

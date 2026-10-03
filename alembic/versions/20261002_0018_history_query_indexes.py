"""add bounded history and strategy decision query indexes

Revision ID: 20261002_0018
Revises: 20261002_0017
Create Date: 2026-10-02 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20261002_0018"
down_revision: Union[str, None] = "20261002_0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The history routes use an immutable (created_at, id) keyset.  The
    # account prefix keeps the database from materializing another account's
    # history before applying the page limit.
    op.create_index(
        "ix_orders_broker_account_created_id",
        "orders",
        ["broker_account_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_executions_account_created_id",
        "executions",
        ["external_account_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_journal_entries_account_created_id",
        "journal_entries",
        ["external_account_id", "created_at", "id"],
        unique=False,
    )

    # Covered Call reservation/lifecycle reads and the active-spread dashboard
    # read push their account, mode, lifecycle, symbol, and linkage predicates
    # into SQL.  The trailing timestamps preserve deterministic recent-first
    # reads without a Python-side history cap.
    op.create_index(
        "ix_strategy_proposals_decision_scope",
        "strategy_proposals",
        [
            "external_account_id",
            "strategy_id",
            "execution_mode",
            "symbol",
            "status",
            "proposed_action",
            "updated_at",
            "created_at",
            "id",
        ],
        unique=False,
    )
    op.create_index(
        "ix_strategy_runs_decision_scope",
        "strategy_runs",
        [
            "external_account_id",
            "strategy_id",
            "execution_mode",
            "proposal_id",
            "run_type",
            "created_at",
            "id",
        ],
        unique=False,
    )
    op.create_index(
        "ix_bull_put_spreads_active_scope",
        "bull_put_spreads",
        [
            "external_account_id",
            "execution_mode",
            "status",
            "underlying_symbol",
            "created_at",
            "id",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bull_put_spreads_active_scope", table_name="bull_put_spreads")
    op.drop_index("ix_strategy_runs_decision_scope", table_name="strategy_runs")
    op.drop_index("ix_strategy_proposals_decision_scope", table_name="strategy_proposals")
    op.drop_index("ix_journal_entries_account_created_id", table_name="journal_entries")
    op.drop_index("ix_executions_account_created_id", table_name="executions")
    op.drop_index("ix_orders_broker_account_created_id", table_name="orders")

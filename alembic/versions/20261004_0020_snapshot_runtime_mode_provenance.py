"""add snapshot provenance and mode-scoped bull put runtime state

Revision ID: 20261004_0020
Revises: 20261002_0019
Create Date: 2026-10-04 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261004_0020"
down_revision: Union[str, None] = "20261002_0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "account_snapshots",
        sa.Column("execution_mode", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "account_snapshots",
        sa.Column("provenance", sa.String(length=32), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE account_snapshots "
            "SET provenance = 'legacy_unknown' "
            "WHERE provenance IS NULL"
        )
    )
    op.alter_column(
        "account_snapshots",
        "provenance",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default=sa.text("'legacy_unknown'"),
    )
    op.create_check_constraint(
        "ck_account_snapshots_provenance",
        "account_snapshots",
        "provenance IN ('broker_sync', 'public_upload', 'legacy_unknown')",
    )
    op.create_check_constraint(
        "ck_account_snapshots_execution_mode",
        "account_snapshots",
        "execution_mode IS NULL OR execution_mode IN ('paper', 'live')",
    )
    op.create_index(
        "ix_account_snapshots_execution_mode",
        "account_snapshots",
        ["execution_mode"],
        unique=False,
    )
    op.create_index(
        "ix_account_snapshots_provenance",
        "account_snapshots",
        ["provenance"],
        unique=False,
    )
    op.create_index(
        "ix_account_snapshots_scope",
        "account_snapshots",
        ["external_account_id", "execution_mode", "provenance", "captured_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_account_snapshots_mode_captured_id",
        "account_snapshots",
        ["external_account_id", "execution_mode", "captured_at", "id"],
        unique=False,
    )

    op.drop_constraint(
        "uq_bull_put_strategy_runtime_account_strategy",
        "bull_put_strategy_runtime",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_bull_put_strategy_runtime_account_strategy_mode",
        "bull_put_strategy_runtime",
        ["external_account_id", "strategy_id", "execution_mode"],
    )
    op.create_index(
        "ix_bull_put_strategy_runtime_account_strategy_mode",
        "bull_put_strategy_runtime",
        ["external_account_id", "strategy_id", "execution_mode"],
        unique=False,
    )


def downgrade() -> None:
    conflicts = op.get_bind().execute(
        sa.text(
            "SELECT external_account_id, strategy_id, COUNT(*) AS row_count "
            "FROM bull_put_strategy_runtime "
            "GROUP BY external_account_id, strategy_id "
            "HAVING COUNT(*) > 1"
        )
    ).mappings().all()
    if conflicts:
        details = ", ".join(
            f"{row['external_account_id']}/{row['strategy_id']}={row['row_count']}"
            for row in conflicts
        )
        raise RuntimeError(
            "Cannot downgrade 20261004_0020 while mode-specific Bull Put runtime "
            f"rows would collide with the legacy uniqueness constraint: {details}"
        )

    op.drop_index(
        "ix_bull_put_strategy_runtime_account_strategy_mode",
        table_name="bull_put_strategy_runtime",
    )
    op.drop_constraint(
        "uq_bull_put_strategy_runtime_account_strategy_mode",
        "bull_put_strategy_runtime",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_bull_put_strategy_runtime_account_strategy",
        "bull_put_strategy_runtime",
        ["external_account_id", "strategy_id"],
    )
    op.drop_index("ix_account_snapshots_mode_captured_id", table_name="account_snapshots")
    op.drop_index("ix_account_snapshots_scope", table_name="account_snapshots")
    op.drop_constraint(
        "ck_account_snapshots_execution_mode",
        "account_snapshots",
        type_="check",
    )
    op.drop_constraint(
        "ck_account_snapshots_provenance",
        "account_snapshots",
        type_="check",
    )
    op.drop_index("ix_account_snapshots_provenance", table_name="account_snapshots")
    op.drop_index("ix_account_snapshots_execution_mode", table_name="account_snapshots")
    op.drop_column("account_snapshots", "provenance")
    op.drop_column("account_snapshots", "execution_mode")

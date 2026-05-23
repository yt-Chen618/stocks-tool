"""add bull put strategy runtime state

Revision ID: 20260523_0006
Revises: 20260522_0005
Create Date: 2026-05-23 12:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260523_0006"
down_revision: Union[str, None] = "20260522_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bull_put_strategy_runtime",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column(
            "strategy_id",
            sa.String(length=64),
            nullable=False,
            server_default="paper_bull_put_v1",
        ),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("auto_entry_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("manual_pause", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("kill_switch_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("paused_symbols", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("current_session_date", sa.Date(), nullable=True),
        sa.Column("daily_entry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("daily_realized_pnl", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scan_result", sa.String(length=32), nullable=True),
        sa.Column("last_scan_symbol", sa.String(length=32), nullable=True),
        sa.Column("last_skip_reason", sa.Text(), nullable=True),
        sa.Column("last_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_action", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["broker_account_id"],
            ["broker_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_account_id", "strategy_id", name="uq_bull_put_strategy_runtime_account_strategy"),
    )
    op.create_index(
        op.f("ix_bull_put_strategy_runtime_broker_account_id"),
        "bull_put_strategy_runtime",
        ["broker_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bull_put_strategy_runtime_strategy_id"),
        "bull_put_strategy_runtime",
        ["strategy_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bull_put_strategy_runtime_external_account_id"),
        "bull_put_strategy_runtime",
        ["external_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bull_put_strategy_runtime_current_session_date"),
        "bull_put_strategy_runtime",
        ["current_session_date"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bull_put_strategy_runtime_last_scan_at"),
        "bull_put_strategy_runtime",
        ["last_scan_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_bull_put_strategy_runtime_last_scan_at"), table_name="bull_put_strategy_runtime")
    op.drop_index(op.f("ix_bull_put_strategy_runtime_current_session_date"), table_name="bull_put_strategy_runtime")
    op.drop_index(op.f("ix_bull_put_strategy_runtime_external_account_id"), table_name="bull_put_strategy_runtime")
    op.drop_index(op.f("ix_bull_put_strategy_runtime_strategy_id"), table_name="bull_put_strategy_runtime")
    op.drop_index(op.f("ix_bull_put_strategy_runtime_broker_account_id"), table_name="bull_put_strategy_runtime")
    op.drop_table("bull_put_strategy_runtime")

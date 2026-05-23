"""add bull put spread persistence

Revision ID: 20260522_0005
Revises: 20260522_0004
Create Date: 2026-05-22 12:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260522_0005"
down_revision: Union[str, None] = "20260522_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bull_put_spreads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column(
            "strategy_id",
            sa.String(length=64),
            nullable=False,
            server_default="paper_bull_put_v1",
        ),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("underlying_symbol", sa.String(length=32), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("contracts", sa.Integer(), nullable=False),
        sa.Column("width", sa.Numeric(18, 4), nullable=False),
        sa.Column("long_symbol", sa.String(length=32), nullable=False),
        sa.Column("long_strike", sa.Numeric(18, 4), nullable=False),
        sa.Column("short_symbol", sa.String(length=32), nullable=False),
        sa.Column("short_strike", sa.Numeric(18, 4), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("long_entry_order_id", sa.String(length=36), nullable=True),
        sa.Column("short_entry_order_id", sa.String(length=36), nullable=True),
        sa.Column("long_exit_order_id", sa.String(length=36), nullable=True),
        sa.Column("short_exit_order_id", sa.String(length=36), nullable=True),
        sa.Column("entry_long_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("entry_short_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("entry_net_credit", sa.Numeric(18, 4), nullable=True),
        sa.Column("max_profit", sa.Numeric(18, 4), nullable=True),
        sa.Column("max_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("break_even", sa.Numeric(18, 4), nullable=True),
        sa.Column("account_risk_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("exit_reason", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("entry_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(op.f("ix_bull_put_spreads_broker_account_id"), "bull_put_spreads", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_broker"), "bull_put_spreads", ["broker"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_external_account_id"), "bull_put_spreads", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_strategy_id"), "bull_put_spreads", ["strategy_id"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_underlying_symbol"), "bull_put_spreads", ["underlying_symbol"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_expiration_date"), "bull_put_spreads", ["expiration_date"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_status"), "bull_put_spreads", ["status"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_long_entry_order_id"), "bull_put_spreads", ["long_entry_order_id"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_short_entry_order_id"), "bull_put_spreads", ["short_entry_order_id"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_long_exit_order_id"), "bull_put_spreads", ["long_exit_order_id"], unique=False)
    op.create_index(op.f("ix_bull_put_spreads_short_exit_order_id"), "bull_put_spreads", ["short_exit_order_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_bull_put_spreads_short_exit_order_id"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_long_exit_order_id"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_short_entry_order_id"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_long_entry_order_id"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_status"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_expiration_date"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_underlying_symbol"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_strategy_id"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_external_account_id"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_broker"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_broker_account_id"), table_name="bull_put_spreads")
    op.drop_table("bull_put_spreads")

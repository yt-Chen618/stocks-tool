"""add immutable pre-open and market-session comparisons

Revision ID: 20261004_0025
Revises: 20261004_0024
Create Date: 2026-10-04 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261004_0025"
down_revision: Union[str, None] = "20261004_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_session_comparisons",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False, server_default="paper"),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("account_currency", sa.String(length=8), nullable=True),
        sa.Column("quote_currency", sa.String(length=8), nullable=True),
        sa.Column("pre_open_run_id", sa.String(length=36), nullable=True),
        sa.Column("baseline_session_date", sa.Date(), nullable=True),
        sa.Column("target_trading_day", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("data_quality", sa.String(length=24), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason_detail", sa.Text(), nullable=False),
        sa.Column("field_explanations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("baseline_price", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("regular_close_price", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("after_hours_price", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("pre_to_regular_close_pct", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("regular_close_to_after_hours_pct", sa.Numeric(precision=18, scale=8), nullable=True),
        sa.Column("baseline_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("regular_close_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("post_market_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("evidence_as_of", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_market_session_comparisons_idempotency_key"),
    )
    op.create_index(
        "ix_market_session_comparisons_broker_account_id",
        "market_session_comparisons",
        ["broker_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_external_account_id",
        "market_session_comparisons",
        ["external_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_execution_mode",
        "market_session_comparisons",
        ["execution_mode"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_symbol",
        "market_session_comparisons",
        ["symbol"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_pre_open_run_id",
        "market_session_comparisons",
        ["pre_open_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_baseline_session_date",
        "market_session_comparisons",
        ["baseline_session_date"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_target_trading_day",
        "market_session_comparisons",
        ["target_trading_day"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_status",
        "market_session_comparisons",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_data_quality",
        "market_session_comparisons",
        ["data_quality"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_evidence_as_of",
        "market_session_comparisons",
        ["evidence_as_of"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_account_mode_created",
        "market_session_comparisons",
        ["external_account_id", "execution_mode", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_market_session_comparisons_account_mode_symbol",
        "market_session_comparisons",
        ["external_account_id", "execution_mode", "symbol", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_market_session_comparisons_account_mode_symbol", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_account_mode_created", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_evidence_as_of", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_data_quality", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_status", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_baseline_session_date", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_target_trading_day", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_pre_open_run_id", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_symbol", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_execution_mode", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_external_account_id", table_name="market_session_comparisons")
    op.drop_index("ix_market_session_comparisons_broker_account_id", table_name="market_session_comparisons")
    op.drop_table("market_session_comparisons")

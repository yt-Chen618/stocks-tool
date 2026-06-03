"""add strategy advisor run ledger

Revision ID: 20260603_0011
Revises: 20260529_0010
Create Date: 2026-06-03 22:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260603_0011"
down_revision: Union[str, None] = "20260529_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_advisor_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("context_format", sa.String(length=32), nullable=True),
        sa.Column("context_limit", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_hit_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_miss_tokens", sa.Integer(), nullable=True),
        sa.Column("proposal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_id", sa.String(length=128), nullable=True),
        sa.Column("finish_reason", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_response", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_advisor_runs_broker_account_id"), "strategy_advisor_runs", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_completed_at"), "strategy_advisor_runs", ["completed_at"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_context_format"), "strategy_advisor_runs", ["context_format"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_execution_mode"), "strategy_advisor_runs", ["execution_mode"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_external_account_id"), "strategy_advisor_runs", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_model"), "strategy_advisor_runs", ["model"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_provider"), "strategy_advisor_runs", ["provider"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_recorded_at"), "strategy_advisor_runs", ["recorded_at"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_response_id"), "strategy_advisor_runs", ["response_id"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_source"), "strategy_advisor_runs", ["source"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_started_at"), "strategy_advisor_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_strategy_advisor_runs_status"), "strategy_advisor_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_strategy_advisor_runs_status"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_started_at"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_source"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_response_id"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_recorded_at"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_provider"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_model"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_external_account_id"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_execution_mode"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_context_format"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_completed_at"), table_name="strategy_advisor_runs")
    op.drop_index(op.f("ix_strategy_advisor_runs_broker_account_id"), table_name="strategy_advisor_runs")
    op.drop_table("strategy_advisor_runs")

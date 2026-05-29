"""add strategy experiment tables

Revision ID: 20260529_0009
Revises: 20260524_0008
Create Date: 2026-05-29 23:20:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260529_0009"
down_revision: Union[str, None] = "20260524_0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("proposed_action", sa.String(length=64), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("confidence", sa.Numeric(10, 6), nullable=True),
        sa.Column("expected_max_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("expected_max_profit", sa.Numeric(18, 4), nullable=True),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("source_run_id", sa.String(length=36), nullable=True),
        sa.Column("candidate_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_proposals_approved_at"), "strategy_proposals", ["approved_at"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_broker_account_id"), "strategy_proposals", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_external_account_id"), "strategy_proposals", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_expires_at"), "strategy_proposals", ["expires_at"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_proposed_action"), "strategy_proposals", ["proposed_action"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_rejected_at"), "strategy_proposals", ["rejected_at"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_source_run_id"), "strategy_proposals", ["source_run_id"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_status"), "strategy_proposals", ["status"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_strategy_id"), "strategy_proposals", ["strategy_id"], unique=False)
    op.create_index(op.f("ix_strategy_proposals_symbol"), "strategy_proposals", ["symbol"], unique=False)

    op.create_table(
        "strategy_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("run_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("trade_plan_id", sa.String(length=36), nullable=True),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("spread_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metrics_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_runs_broker_account_id"), "strategy_runs", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_runs_completed_at"), "strategy_runs", ["completed_at"], unique=False)
    op.create_index(op.f("ix_strategy_runs_external_account_id"), "strategy_runs", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_runs_order_id"), "strategy_runs", ["order_id"], unique=False)
    op.create_index(op.f("ix_strategy_runs_proposal_id"), "strategy_runs", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_strategy_runs_run_type"), "strategy_runs", ["run_type"], unique=False)
    op.create_index(op.f("ix_strategy_runs_spread_id"), "strategy_runs", ["spread_id"], unique=False)
    op.create_index(op.f("ix_strategy_runs_started_at"), "strategy_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_strategy_runs_status"), "strategy_runs", ["status"], unique=False)
    op.create_index(op.f("ix_strategy_runs_strategy_id"), "strategy_runs", ["strategy_id"], unique=False)
    op.create_index(op.f("ix_strategy_runs_symbol"), "strategy_runs", ["symbol"], unique=False)
    op.create_index(op.f("ix_strategy_runs_trade_plan_id"), "strategy_runs", ["trade_plan_id"], unique=False)

    op.create_table(
        "strategy_signals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("signal_type", sa.String(length=32), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("strength", sa.Numeric(10, 6), nullable=True),
        sa.Column("summary", sa.String(length=240), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("signal_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("emitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_signals_broker_account_id"), "strategy_signals", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_emitted_at"), "strategy_signals", ["emitted_at"], unique=False)
    op.create_index(op.f("ix_strategy_signals_external_account_id"), "strategy_signals", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_proposal_id"), "strategy_signals", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_run_id"), "strategy_signals", ["run_id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_signal_type"), "strategy_signals", ["signal_type"], unique=False)
    op.create_index(op.f("ix_strategy_signals_strategy_id"), "strategy_signals", ["strategy_id"], unique=False)
    op.create_index(op.f("ix_strategy_signals_symbol"), "strategy_signals", ["symbol"], unique=False)

    op.create_table(
        "strategy_reviews",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("strategy_id", sa.String(length=64), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("review_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("parameter_name", sa.String(length=64), nullable=True),
        sa.Column("current_value", sa.String(length=120), nullable=True),
        sa.Column("suggested_value", sa.String(length=120), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("journal_entry_id", sa.String(length=36), nullable=True),
        sa.Column("metrics_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_reviews_broker_account_id"), "strategy_reviews", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_reviews_external_account_id"), "strategy_reviews", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_strategy_reviews_journal_entry_id"), "strategy_reviews", ["journal_entry_id"], unique=False)
    op.create_index(op.f("ix_strategy_reviews_proposal_id"), "strategy_reviews", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_strategy_reviews_review_type"), "strategy_reviews", ["review_type"], unique=False)
    op.create_index(op.f("ix_strategy_reviews_reviewed_at"), "strategy_reviews", ["reviewed_at"], unique=False)
    op.create_index(op.f("ix_strategy_reviews_run_id"), "strategy_reviews", ["run_id"], unique=False)
    op.create_index(op.f("ix_strategy_reviews_status"), "strategy_reviews", ["status"], unique=False)
    op.create_index(op.f("ix_strategy_reviews_strategy_id"), "strategy_reviews", ["strategy_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_strategy_reviews_strategy_id"), table_name="strategy_reviews")
    op.drop_index(op.f("ix_strategy_reviews_status"), table_name="strategy_reviews")
    op.drop_index(op.f("ix_strategy_reviews_run_id"), table_name="strategy_reviews")
    op.drop_index(op.f("ix_strategy_reviews_reviewed_at"), table_name="strategy_reviews")
    op.drop_index(op.f("ix_strategy_reviews_review_type"), table_name="strategy_reviews")
    op.drop_index(op.f("ix_strategy_reviews_proposal_id"), table_name="strategy_reviews")
    op.drop_index(op.f("ix_strategy_reviews_journal_entry_id"), table_name="strategy_reviews")
    op.drop_index(op.f("ix_strategy_reviews_external_account_id"), table_name="strategy_reviews")
    op.drop_index(op.f("ix_strategy_reviews_broker_account_id"), table_name="strategy_reviews")
    op.drop_table("strategy_reviews")

    op.drop_index(op.f("ix_strategy_signals_symbol"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_strategy_id"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_signal_type"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_run_id"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_proposal_id"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_external_account_id"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_emitted_at"), table_name="strategy_signals")
    op.drop_index(op.f("ix_strategy_signals_broker_account_id"), table_name="strategy_signals")
    op.drop_table("strategy_signals")

    op.drop_index(op.f("ix_strategy_runs_trade_plan_id"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_symbol"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_strategy_id"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_status"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_started_at"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_spread_id"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_run_type"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_proposal_id"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_order_id"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_external_account_id"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_completed_at"), table_name="strategy_runs")
    op.drop_index(op.f("ix_strategy_runs_broker_account_id"), table_name="strategy_runs")
    op.drop_table("strategy_runs")

    op.drop_index(op.f("ix_strategy_proposals_symbol"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_strategy_id"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_status"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_source_run_id"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_rejected_at"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_proposed_action"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_expires_at"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_external_account_id"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_broker_account_id"), table_name="strategy_proposals")
    op.drop_index(op.f("ix_strategy_proposals_approved_at"), table_name="strategy_proposals")
    op.drop_table("strategy_proposals")

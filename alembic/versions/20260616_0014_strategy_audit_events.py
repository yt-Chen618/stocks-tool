"""add durable strategy audit events

Revision ID: 20260616_0014
Revises: 20260615_0013
Create Date: 2026-06-16 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260616_0014"
down_revision: Union[str, None] = "20260615_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=True),
        sa.Column("execution_mode", sa.String(length=16), nullable=True),
        sa.Column("actor", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("strategy", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("before_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("order_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("warning_code", sa.String(length=96), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("event_origin", sa.String(length=16), server_default="durable", nullable=False),
        sa.Column("emitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_strategy_audit_events_action"), "strategy_audit_events", ["action"], unique=False)
    op.create_index(op.f("ix_strategy_audit_events_actor"), "strategy_audit_events", ["actor"], unique=False)
    op.create_index(
        op.f("ix_strategy_audit_events_broker_account_id"),
        "strategy_audit_events",
        ["broker_account_id"],
        unique=False,
    )
    op.create_index(op.f("ix_strategy_audit_events_emitted_at"), "strategy_audit_events", ["emitted_at"], unique=False)
    op.create_index(
        op.f("ix_strategy_audit_events_execution_mode"),
        "strategy_audit_events",
        ["execution_mode"],
        unique=False,
    )
    op.create_index(
        op.f("ix_strategy_audit_events_external_account_id"),
        "strategy_audit_events",
        ["external_account_id"],
        unique=False,
    )
    op.create_index(op.f("ix_strategy_audit_events_proposal_id"), "strategy_audit_events", ["proposal_id"], unique=False)
    op.create_index(op.f("ix_strategy_audit_events_run_id"), "strategy_audit_events", ["run_id"], unique=False)
    op.create_index(op.f("ix_strategy_audit_events_source"), "strategy_audit_events", ["source"], unique=False)
    op.create_index(op.f("ix_strategy_audit_events_strategy"), "strategy_audit_events", ["strategy"], unique=False)
    op.create_index(op.f("ix_strategy_audit_events_warning_code"), "strategy_audit_events", ["warning_code"], unique=False)
    op.create_index(
        "ix_strategy_audit_events_account_emitted",
        "strategy_audit_events",
        ["external_account_id", "emitted_at"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_audit_events_source_strategy_action",
        "strategy_audit_events",
        ["source", "strategy", "action"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_audit_events_source_strategy_action", table_name="strategy_audit_events")
    op.drop_index("ix_strategy_audit_events_account_emitted", table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_warning_code"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_strategy"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_source"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_run_id"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_proposal_id"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_external_account_id"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_execution_mode"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_emitted_at"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_broker_account_id"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_actor"), table_name="strategy_audit_events")
    op.drop_index(op.f("ix_strategy_audit_events_action"), table_name="strategy_audit_events")
    op.drop_table("strategy_audit_events")

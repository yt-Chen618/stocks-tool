"""add pre open assessment runs

Revision ID: 20260524_0008
Revises: 20260523_0007
Create Date: 2026-05-24 11:50:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260524_0008"
down_revision: Union[str, None] = "20260523_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pre_open_assessment_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("strategy_id", sa.String(length=64), nullable=False, server_default="pre_open_put_check_v1"),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("target_session_date", sa.Date(), nullable=False),
        sa.Column("assessment_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checkpoints_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("review_summary", sa.Text(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_account_id",
            "strategy_id",
            "target_session_date",
            name="uq_pre_open_assessment_runs_account_strategy_session_date",
        ),
    )
    op.create_index(op.f("ix_pre_open_assessment_runs_broker_account_id"), "pre_open_assessment_runs", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_pre_open_assessment_runs_external_account_id"), "pre_open_assessment_runs", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_pre_open_assessment_runs_last_reviewed_at"), "pre_open_assessment_runs", ["last_reviewed_at"], unique=False)
    op.create_index(op.f("ix_pre_open_assessment_runs_review_completed_at"), "pre_open_assessment_runs", ["review_completed_at"], unique=False)
    op.create_index(op.f("ix_pre_open_assessment_runs_strategy_id"), "pre_open_assessment_runs", ["strategy_id"], unique=False)
    op.create_index(op.f("ix_pre_open_assessment_runs_target_session_date"), "pre_open_assessment_runs", ["target_session_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pre_open_assessment_runs_target_session_date"), table_name="pre_open_assessment_runs")
    op.drop_index(op.f("ix_pre_open_assessment_runs_strategy_id"), table_name="pre_open_assessment_runs")
    op.drop_index(op.f("ix_pre_open_assessment_runs_review_completed_at"), table_name="pre_open_assessment_runs")
    op.drop_index(op.f("ix_pre_open_assessment_runs_last_reviewed_at"), table_name="pre_open_assessment_runs")
    op.drop_index(op.f("ix_pre_open_assessment_runs_external_account_id"), table_name="pre_open_assessment_runs")
    op.drop_index(op.f("ix_pre_open_assessment_runs_broker_account_id"), table_name="pre_open_assessment_runs")
    op.drop_table("pre_open_assessment_runs")

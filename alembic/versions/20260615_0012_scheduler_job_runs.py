"""add scheduler job run observations

Revision ID: 20260615_0012
Revises: 20260603_0011
Create Date: 2026-06-15 23:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260615_0012"
down_revision: Union[str, None] = "20260603_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduler_job_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=True),
        sa.Column("job_key", sa.String(length=80), nullable=False),
        sa.Column("job_label", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backoff_seconds", sa.Integer(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scheduler_job_runs_broker_account_id"), "scheduler_job_runs", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_scheduler_job_runs_completed_at"), "scheduler_job_runs", ["completed_at"], unique=False)
    op.create_index(op.f("ix_scheduler_job_runs_external_account_id"), "scheduler_job_runs", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_scheduler_job_runs_job_key"), "scheduler_job_runs", ["job_key"], unique=False)
    op.create_index(op.f("ix_scheduler_job_runs_next_attempt_at"), "scheduler_job_runs", ["next_attempt_at"], unique=False)
    op.create_index(op.f("ix_scheduler_job_runs_started_at"), "scheduler_job_runs", ["started_at"], unique=False)
    op.create_index(op.f("ix_scheduler_job_runs_status"), "scheduler_job_runs", ["status"], unique=False)
    op.create_index(
        "ix_scheduler_job_runs_account_job_started",
        "scheduler_job_runs",
        ["external_account_id", "job_key", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_scheduler_job_runs_account_job_started", table_name="scheduler_job_runs")
    op.drop_index(op.f("ix_scheduler_job_runs_status"), table_name="scheduler_job_runs")
    op.drop_index(op.f("ix_scheduler_job_runs_started_at"), table_name="scheduler_job_runs")
    op.drop_index(op.f("ix_scheduler_job_runs_next_attempt_at"), table_name="scheduler_job_runs")
    op.drop_index(op.f("ix_scheduler_job_runs_job_key"), table_name="scheduler_job_runs")
    op.drop_index(op.f("ix_scheduler_job_runs_external_account_id"), table_name="scheduler_job_runs")
    op.drop_index(op.f("ix_scheduler_job_runs_completed_at"), table_name="scheduler_job_runs")
    op.drop_index(op.f("ix_scheduler_job_runs_broker_account_id"), table_name="scheduler_job_runs")
    op.drop_table("scheduler_job_runs")

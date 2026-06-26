"""add scheduler task state read model

Revision ID: 20260618_0015
Revises: 20260616_0014
Create Date: 2026-06-18 11:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260618_0015"
down_revision: Union[str, None] = "20260616_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scheduler_task_states",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=True),
        sa.Column("job_key", sa.String(length=80), nullable=False),
        sa.Column("job_label", sa.String(length=160), nullable=True),
        sa.Column("last_run_id", sa.String(length=36), nullable=True),
        sa.Column("last_status", sa.String(length=24), nullable=True),
        sa.Column("last_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("backoff_seconds", sa.Integer(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_account_id", "job_key", name="uq_scheduler_task_states_account_job"),
    )
    op.create_index(
        op.f("ix_scheduler_task_states_broker_account_id"),
        "scheduler_task_states",
        ["broker_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduler_task_states_external_account_id"),
        "scheduler_task_states",
        ["external_account_id"],
        unique=False,
    )
    op.create_index(op.f("ix_scheduler_task_states_job_key"), "scheduler_task_states", ["job_key"], unique=False)
    op.create_index(
        op.f("ix_scheduler_task_states_last_completed_at"),
        "scheduler_task_states",
        ["last_completed_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduler_task_states_last_run_id"),
        "scheduler_task_states",
        ["last_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduler_task_states_last_started_at"),
        "scheduler_task_states",
        ["last_started_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduler_task_states_last_status"),
        "scheduler_task_states",
        ["last_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduler_task_states_lease_acquired_at"),
        "scheduler_task_states",
        ["lease_acquired_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduler_task_states_lease_expires_at"),
        "scheduler_task_states",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduler_task_states_lease_owner"),
        "scheduler_task_states",
        ["lease_owner"],
        unique=False,
    )
    op.create_index(
        op.f("ix_scheduler_task_states_next_attempt_at"),
        "scheduler_task_states",
        ["next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_scheduler_task_states_next_attempt_at"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_lease_owner"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_lease_expires_at"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_lease_acquired_at"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_last_status"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_last_started_at"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_last_run_id"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_last_completed_at"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_job_key"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_external_account_id"), table_name="scheduler_task_states")
    op.drop_index(op.f("ix_scheduler_task_states_broker_account_id"), table_name="scheduler_task_states")
    op.drop_table("scheduler_task_states")

"""Add journal entries table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260522_0004"
down_revision = "20260522_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "journal_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("trade_plan_id", sa.String(length=36), nullable=True),
        sa.Column("order_id", sa.String(length=36), nullable=True),
        sa.Column("execution_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("entry_type", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["trade_plan_id"], ["trade_plans.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["execution_id"], ["executions.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_journal_entries_trade_plan_id"), "journal_entries", ["trade_plan_id"], unique=False)
    op.create_index(op.f("ix_journal_entries_order_id"), "journal_entries", ["order_id"], unique=False)
    op.create_index(op.f("ix_journal_entries_execution_id"), "journal_entries", ["execution_id"], unique=False)
    op.create_index(
        op.f("ix_journal_entries_external_account_id"),
        "journal_entries",
        ["external_account_id"],
        unique=False,
    )
    op.create_index(op.f("ix_journal_entries_symbol"), "journal_entries", ["symbol"], unique=False)
    op.create_index(op.f("ix_journal_entries_entry_type"), "journal_entries", ["entry_type"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_journal_entries_entry_type"), table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_symbol"), table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_external_account_id"), table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_execution_id"), table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_order_id"), table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_trade_plan_id"), table_name="journal_entries")
    op.drop_table("journal_entries")

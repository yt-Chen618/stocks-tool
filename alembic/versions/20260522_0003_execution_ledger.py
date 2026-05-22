"""Add execution ledger table."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260522_0003"
down_revision = "20260522_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "executions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("external_order_id", sa.String(length=128), nullable=True),
        sa.Column("external_execution_id", sa.String(length=128), nullable=True, unique=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_executions_order_id"), "executions", ["order_id"], unique=False)
    op.create_index(op.f("ix_executions_broker"), "executions", ["broker"], unique=False)
    op.create_index(op.f("ix_executions_external_account_id"), "executions", ["external_account_id"], unique=False)
    op.create_index(op.f("ix_executions_external_order_id"), "executions", ["external_order_id"], unique=False)
    op.create_index(op.f("ix_executions_external_execution_id"), "executions", ["external_execution_id"], unique=False)
    op.create_index(op.f("ix_executions_symbol"), "executions", ["symbol"], unique=False)
    op.create_index(op.f("ix_executions_executed_at"), "executions", ["executed_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_executions_executed_at"), table_name="executions")
    op.drop_index(op.f("ix_executions_symbol"), table_name="executions")
    op.drop_index(op.f("ix_executions_external_execution_id"), table_name="executions")
    op.drop_index(op.f("ix_executions_external_order_id"), table_name="executions")
    op.drop_index(op.f("ix_executions_external_account_id"), table_name="executions")
    op.drop_index(op.f("ix_executions_broker"), table_name="executions")
    op.drop_index(op.f("ix_executions_order_id"), table_name="executions")
    op.drop_table("executions")

"""Add broker-account reconciliation state fields."""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "20260522_0002"
down_revision = "20260520_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "broker_accounts",
        sa.Column(
            "auto_reconcile_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "broker_accounts",
        sa.Column(
            "account_sync_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'idle'"),
        ),
    )
    op.add_column(
        "broker_accounts",
        sa.Column("account_last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "broker_accounts",
        sa.Column("account_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "broker_accounts",
        sa.Column("account_last_sync_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "broker_accounts",
        sa.Column(
            "orders_sync_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'idle'"),
        ),
    )
    op.add_column(
        "broker_accounts",
        sa.Column("orders_last_sync_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "broker_accounts",
        sa.Column("orders_last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "broker_accounts",
        sa.Column("orders_last_sync_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("broker_accounts", "orders_last_sync_error")
    op.drop_column("broker_accounts", "orders_last_synced_at")
    op.drop_column("broker_accounts", "orders_last_sync_attempt_at")
    op.drop_column("broker_accounts", "orders_sync_status")
    op.drop_column("broker_accounts", "account_last_sync_error")
    op.drop_column("broker_accounts", "account_last_synced_at")
    op.drop_column("broker_accounts", "account_last_sync_attempt_at")
    op.drop_column("broker_accounts", "account_sync_status")
    op.drop_column("broker_accounts", "auto_reconcile_enabled")

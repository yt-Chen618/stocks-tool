"""Initial database schema for the trading workbench."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260520_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=True, unique=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "broker_accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("base_currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("options_level", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("broker", "external_account_id", name="uq_broker_accounts_broker_external_account_id"),
    )
    op.create_index(op.f("ix_broker_accounts_broker"), "broker_accounts", ["broker"], unique=False)

    op.create_table(
        "watchlists",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("watchlist_id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlists.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_items_watchlist_symbol"),
    )
    op.create_index(op.f("ix_watchlist_items_watchlist_id"), "watchlist_items", ["watchlist_id"], unique=False)

    op.create_table(
        "trade_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("structure", sa.String(length=32), nullable=False),
        sa.Column("bias", sa.String(length=16), nullable=False),
        sa.Column("catalyst_type", sa.String(length=32), nullable=False),
        sa.Column("thesis", sa.Text(), nullable=False),
        sa.Column("entry_minimum", sa.Numeric(18, 4), nullable=True),
        sa.Column("entry_maximum", sa.Numeric(18, 4), nullable=True),
        sa.Column("stop_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("take_profit", sa.Numeric(18, 4), nullable=True),
        sa.Column("invalidation", sa.Text(), nullable=False),
        sa.Column("holding_period_days", sa.Integer(), nullable=False),
        sa.Column("max_account_risk_pct", sa.Numeric(10, 6), nullable=False),
        sa.Column("estimated_max_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("option_underlying_symbol", sa.String(length=32), nullable=True),
        sa.Column("option_expiration_date", sa.Date(), nullable=True),
        sa.Column("option_strike", sa.Numeric(18, 4), nullable=True),
        sa.Column("option_right", sa.String(length=8), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("context_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_trade_plans_broker_account_id"), "trade_plans", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_trade_plans_status"), "trade_plans", ["status"], unique=False)
    op.create_index(op.f("ix_trade_plans_symbol"), "trade_plans", ["symbol"], unique=False)

    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("cash_balance", sa.Numeric(18, 4), nullable=False),
        sa.Column("net_liquidation", sa.Numeric(18, 4), nullable=False),
        sa.Column("buying_power", sa.Numeric(18, 4), nullable=False),
        sa.Column("day_trade_buying_power", sa.Numeric(18, 4), nullable=True),
        sa.Column("options_level", sa.String(length=32), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_account_snapshots_broker"), "account_snapshots", ["broker"], unique=False)
    op.create_index(op.f("ix_account_snapshots_broker_account_id"), "account_snapshots", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_account_snapshots_captured_at"), "account_snapshots", ["captured_at"], unique=False)

    op.create_table(
        "position_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("account_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("average_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("market_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("unrealized_pnl", sa.Numeric(18, 4), nullable=False),
        sa.Column("option_underlying_symbol", sa.String(length=32), nullable=True),
        sa.Column("option_expiration_date", sa.Date(), nullable=True),
        sa.Column("option_strike", sa.Numeric(18, 4), nullable=True),
        sa.Column("option_right", sa.String(length=8), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["account_snapshot_id"], ["account_snapshots.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_position_snapshots_account_snapshot_id"), "position_snapshots", ["account_snapshot_id"], unique=False)
    op.create_index(op.f("ix_position_snapshots_symbol"), "position_snapshots", ["symbol"], unique=False)

    op.create_table(
        "orders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("trade_plan_id", sa.String(length=36), nullable=True),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("external_order_id", sa.String(length=128), nullable=True),
        sa.Column("client_order_id", sa.String(length=128), nullable=True, unique=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("asset_type", sa.String(length=16), nullable=True),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(length=16), nullable=False),
        sa.Column("time_in_force", sa.String(length=16), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("limit_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("stop_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column("option_underlying_symbol", sa.String(length=32), nullable=True),
        sa.Column("option_expiration_date", sa.Date(), nullable=True),
        sa.Column("option_strike", sa.Numeric(18, 4), nullable=True),
        sa.Column("option_right", sa.String(length=8), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["trade_plan_id"], ["trade_plans.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_orders_broker"), "orders", ["broker"], unique=False)
    op.create_index(op.f("ix_orders_broker_account_id"), "orders", ["broker_account_id"], unique=False)
    op.create_index(op.f("ix_orders_external_order_id"), "orders", ["external_order_id"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)
    op.create_index(op.f("ix_orders_submitted_at"), "orders", ["submitted_at"], unique=False)
    op.create_index(op.f("ix_orders_symbol"), "orders", ["symbol"], unique=False)
    op.create_index(op.f("ix_orders_trade_plan_id"), "orders", ["trade_plan_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_trade_plan_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_symbol"), table_name="orders")
    op.drop_index(op.f("ix_orders_submitted_at"), table_name="orders")
    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_external_order_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_broker_account_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_broker"), table_name="orders")
    op.drop_table("orders")

    op.drop_index(op.f("ix_position_snapshots_symbol"), table_name="position_snapshots")
    op.drop_index(op.f("ix_position_snapshots_account_snapshot_id"), table_name="position_snapshots")
    op.drop_table("position_snapshots")

    op.drop_index(op.f("ix_account_snapshots_captured_at"), table_name="account_snapshots")
    op.drop_index(op.f("ix_account_snapshots_broker_account_id"), table_name="account_snapshots")
    op.drop_index(op.f("ix_account_snapshots_broker"), table_name="account_snapshots")
    op.drop_table("account_snapshots")

    op.drop_index(op.f("ix_trade_plans_symbol"), table_name="trade_plans")
    op.drop_index(op.f("ix_trade_plans_status"), table_name="trade_plans")
    op.drop_index(op.f("ix_trade_plans_broker_account_id"), table_name="trade_plans")
    op.drop_table("trade_plans")

    op.drop_index(op.f("ix_watchlist_items_watchlist_id"), table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_table("watchlists")

    op.drop_index(op.f("ix_broker_accounts_broker"), table_name="broker_accounts")
    op.drop_table("broker_accounts")
    op.drop_table("users")


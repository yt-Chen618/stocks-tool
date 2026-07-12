"""add durable trading intent ledger

Revision ID: 20260711_0016
Revises: 20260618_0015
Create Date: 2026-07-11 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260711_0016"
down_revision: Union[str, None] = "20260618_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _assert_external_order_ids_are_unique() -> None:
    connection = op.get_bind()
    if connection is None:
        return
    result = connection.execute(
        sa.text(
            """
            SELECT broker, execution_mode, external_order_id, COUNT(*) AS duplicate_count
            FROM orders
            WHERE external_order_id IS NOT NULL
            GROUP BY broker, execution_mode, external_order_id
            HAVING COUNT(*) > 1
            ORDER BY broker, execution_mode, external_order_id
            """
        )
    )
    # Offline SQL generation has no result set to inspect; the live upgrade still
    # performs this gate before any schema mutation.
    if result is None:
        return
    duplicates = result.mappings().all()
    if not duplicates:
        return

    details = "; ".join(
        (
            f"broker={row['broker']}, mode={row['execution_mode']}, "
            f"external_order_id={row['external_order_id']}, count={row['duplicate_count']}"
        )
        for row in duplicates
    )
    raise RuntimeError(
        "Cannot add the external-order uniqueness constraint because duplicate rows exist: "
        f"{details}"
    )


def upgrade() -> None:
    _assert_external_order_ids_are_unique()

    op.create_table(
        "trade_action_intents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=96), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "state IN ('prepared', 'submitting', 'broker_acknowledged', 'persisted', "
            "'rejected', 'unknown', 'resolved_no_order')",
            name="ck_trade_action_intents_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_account_id",
            "execution_mode",
            "idempotency_key",
            name="uq_trade_action_intents_account_mode_key",
        ),
    )
    op.create_index(
        "ix_trade_action_intents_account_state",
        "trade_action_intents",
        ["external_account_id", "execution_mode", "state"],
        unique=False,
    )

    op.create_table(
        "order_intents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("trade_action_intent_id", sa.String(length=36), nullable=False),
        sa.Column("broker_account_id", sa.String(length=36), nullable=True),
        sa.Column("target_order_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=96), nullable=False),
        sa.Column("strategy_id", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=96), nullable=True),
        sa.Column("leg", sa.String(length=64), nullable=True),
        sa.Column("broker_marker", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("external_order_id", sa.String(length=128), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("reconciliation_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["broker_account_id"], ["broker_accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["trade_action_intent_id"], ["trade_action_intents.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "state IN ('prepared', 'submitting', 'broker_acknowledged', 'persisted', "
            "'rejected', 'unknown', 'resolved_no_order')",
            name="ck_order_intents_state",
        ),
        sa.CheckConstraint(
            "operation IN ('submit', 'cancel', 'replace')",
            name="ck_order_intents_operation",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_account_id",
            "execution_mode",
            "idempotency_key",
            name="uq_order_intents_account_mode_key",
        ),
    )
    op.create_index(
        "ix_order_intents_account_state",
        "order_intents",
        ["external_account_id", "execution_mode", "state"],
        unique=False,
    )
    op.create_index("ix_order_intents_broker_marker", "order_intents", ["broker_marker"], unique=False)
    op.create_index("ix_order_intents_external_order_id", "order_intents", ["external_order_id"], unique=False)
    op.create_index("ix_order_intents_first_reconciled_at", "order_intents", ["first_reconciled_at"], unique=False)
    op.create_index("ix_order_intents_target_order_id", "order_intents", ["target_order_id"], unique=False)
    op.create_index(
        "ix_order_intents_trade_action_intent_id",
        "order_intents",
        ["trade_action_intent_id"],
        unique=False,
    )

    op.add_column("orders", sa.Column("order_intent_id", sa.String(length=36), nullable=True))
    op.add_column("orders", sa.Column("executed_quantity", sa.Integer(), server_default="0", nullable=False))
    op.add_column("orders", sa.Column("executed_price", sa.Numeric(18, 4), nullable=True))
    op.create_foreign_key(
        "fk_orders_order_intent_id_order_intents",
        "orders",
        "order_intents",
        ["order_intent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_orders_order_intent_id", "orders", ["order_intent_id"], unique=True)
    op.create_unique_constraint(
        "uq_orders_broker_mode_external_order_id",
        "orders",
        ["broker", "execution_mode", "external_order_id"],
    )

    op.add_column("bull_put_spreads", sa.Column("version", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("bull_put_spreads", "version")
    op.drop_constraint("uq_orders_broker_mode_external_order_id", "orders", type_="unique")
    op.drop_index("ix_orders_order_intent_id", table_name="orders")
    op.drop_constraint("fk_orders_order_intent_id_order_intents", "orders", type_="foreignkey")
    op.drop_column("orders", "executed_price")
    op.drop_column("orders", "executed_quantity")
    op.drop_column("orders", "order_intent_id")
    op.drop_index("ix_order_intents_trade_action_intent_id", table_name="order_intents")
    op.drop_index("ix_order_intents_target_order_id", table_name="order_intents")
    op.drop_index("ix_order_intents_first_reconciled_at", table_name="order_intents")
    op.drop_index("ix_order_intents_external_order_id", table_name="order_intents")
    op.drop_index("ix_order_intents_broker_marker", table_name="order_intents")
    op.drop_index("ix_order_intents_account_state", table_name="order_intents")
    op.drop_table("order_intents")
    op.drop_index("ix_trade_action_intents_account_state", table_name="trade_action_intents")
    op.drop_table("trade_action_intents")

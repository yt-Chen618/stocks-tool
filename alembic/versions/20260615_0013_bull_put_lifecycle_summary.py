"""add bull put lifecycle summary fields

Revision ID: 20260615_0013
Revises: 20260615_0012
Create Date: 2026-06-15 23:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260615_0013"
down_revision: Union[str, None] = "20260615_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bull_put_spreads", sa.Column("lifecycle_warning_code", sa.String(length=80), nullable=True))
    op.add_column(
        "bull_put_spreads",
        sa.Column("manual_action_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("bull_put_spreads", sa.Column("latest_monitor_should_close", sa.Boolean(), nullable=True))
    op.add_column("bull_put_spreads", sa.Column("latest_close_order_status", sa.String(length=32), nullable=True))
    op.add_column("bull_put_spreads", sa.Column("next_monitor_after", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE bull_put_spreads
        SET
            lifecycle_warning_code = NULLIF(raw_payload #>> '{lifecycle,warning}', ''),
            manual_action_required = CASE
                WHEN NULLIF(raw_payload #>> '{lifecycle,warning}', '') IS NOT NULL THEN true
                WHEN lower(COALESCE(raw_payload #>> '{lifecycle,manual_action_required}', 'false')) = 'true' THEN true
                ELSE false
            END,
            latest_monitor_should_close = CASE lower(COALESCE(raw_payload #>> '{monitor,should_close}', ''))
                WHEN 'true' THEN true
                WHEN 'false' THEN false
                ELSE NULL
            END,
            latest_close_order_status = lower(NULLIF(raw_payload #>> '{lifecycle,close_order_state}', '')),
            next_monitor_after = CASE
                WHEN NULLIF(raw_payload #>> '{monitor,next_monitor_after}', '') IS NOT NULL
                THEN (raw_payload #>> '{monitor,next_monitor_after}')::timestamptz
                ELSE NULL
            END
        WHERE raw_payload IS NOT NULL
        """
    )

    op.create_index(
        op.f("ix_bull_put_spreads_lifecycle_warning_code"),
        "bull_put_spreads",
        ["lifecycle_warning_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bull_put_spreads_manual_action_required"),
        "bull_put_spreads",
        ["manual_action_required"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bull_put_spreads_latest_monitor_should_close"),
        "bull_put_spreads",
        ["latest_monitor_should_close"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bull_put_spreads_latest_close_order_status"),
        "bull_put_spreads",
        ["latest_close_order_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_bull_put_spreads_next_monitor_after"),
        "bull_put_spreads",
        ["next_monitor_after"],
        unique=False,
    )
    op.create_index(
        "ix_orders_account_status_updated",
        "orders",
        ["broker_account_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_bull_put_spreads_account_status_updated",
        "bull_put_spreads",
        ["external_account_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_proposals_account_status_strategy",
        "strategy_proposals",
        ["external_account_id", "status", "strategy_id"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_runs_account_created",
        "strategy_runs",
        ["external_account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_signals_account_created",
        "strategy_signals",
        ["external_account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_strategy_reviews_account_created",
        "strategy_reviews",
        ["external_account_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_market_events_scheduled_symbol_severity",
        "market_events",
        ["scheduled_at", "symbol", "severity"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_market_events_scheduled_symbol_severity", table_name="market_events")
    op.drop_index("ix_strategy_reviews_account_created", table_name="strategy_reviews")
    op.drop_index("ix_strategy_signals_account_created", table_name="strategy_signals")
    op.drop_index("ix_strategy_runs_account_created", table_name="strategy_runs")
    op.drop_index("ix_strategy_proposals_account_status_strategy", table_name="strategy_proposals")
    op.drop_index("ix_bull_put_spreads_account_status_updated", table_name="bull_put_spreads")
    op.drop_index("ix_orders_account_status_updated", table_name="orders")
    op.drop_index(op.f("ix_bull_put_spreads_next_monitor_after"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_latest_close_order_status"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_latest_monitor_should_close"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_manual_action_required"), table_name="bull_put_spreads")
    op.drop_index(op.f("ix_bull_put_spreads_lifecycle_warning_code"), table_name="bull_put_spreads")
    op.drop_column("bull_put_spreads", "next_monitor_after")
    op.drop_column("bull_put_spreads", "latest_close_order_status")
    op.drop_column("bull_put_spreads", "latest_monitor_should_close")
    op.drop_column("bull_put_spreads", "manual_action_required")
    op.drop_column("bull_put_spreads", "lifecycle_warning_code")

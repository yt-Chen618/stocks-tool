"""add nullable normalized market-event dedupe keys

Revision ID: 20261004_0023
Revises: 20261004_0022
Create Date: 2026-10-04 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261004_0023"
down_revision: Union[str, None] = "20261004_0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_order_intents_reconciliation_fair",
        "order_intents",
        [
            "external_account_id",
            "execution_mode",
            "state",
            "updated_at",
            "created_at",
            "id",
        ],
        unique=False,
    )
    op.add_column(
        "market_events",
        sa.Column("dedupe_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "uq_market_events_dedupe_key",
        "market_events",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
        sqlite_where=sa.text("dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_market_events_dedupe_key",
        table_name="market_events",
    )
    op.drop_column("market_events", "dedupe_key")
    op.drop_index(
        "ix_order_intents_reconciliation_fair",
        table_name="order_intents",
    )

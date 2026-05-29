"""add market events

Revision ID: 20260529_0010
Revises: 20260529_0009
Create Date: 2026-05-29 23:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260529_0010"
down_revision: Union[str, None] = "20260529_0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_market_events_event_type"), "market_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_market_events_scheduled_at"), "market_events", ["scheduled_at"], unique=False)
    op.create_index(op.f("ix_market_events_severity"), "market_events", ["severity"], unique=False)
    op.create_index(op.f("ix_market_events_source"), "market_events", ["source"], unique=False)
    op.create_index(op.f("ix_market_events_symbol"), "market_events", ["symbol"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_market_events_symbol"), table_name="market_events")
    op.drop_index(op.f("ix_market_events_source"), table_name="market_events")
    op.drop_index(op.f("ix_market_events_severity"), table_name="market_events")
    op.drop_index(op.f("ix_market_events_scheduled_at"), table_name="market_events")
    op.drop_index(op.f("ix_market_events_event_type"), table_name="market_events")
    op.drop_table("market_events")

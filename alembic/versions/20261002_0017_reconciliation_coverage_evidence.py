"""persist broker-history coverage for no-order reconciliation evidence

Revision ID: 20261002_0017
Revises: 20260711_0016
Create Date: 2026-10-02 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261002_0017"
down_revision: Union[str, None] = "20260711_0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing reconciliation counts were produced without a durable proof of
    # broker-history coverage.  Leave these fields NULL so old counts cannot
    # satisfy a later manual no-order resolution.
    op.add_column(
        "order_intents",
        sa.Column("reconciliation_coverage_start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "order_intents",
        sa.Column("reconciliation_coverage_end_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("order_intents", "reconciliation_coverage_end_at")
    op.drop_column("order_intents", "reconciliation_coverage_start_at")

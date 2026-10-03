"""add bull put history keyset index

Revision ID: 20261002_0019
Revises: 20261002_0018
Create Date: 2026-10-02 00:00:00
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20261002_0019"
down_revision: Union[str, None] = "20261002_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_bull_put_spreads_history_page",
        "bull_put_spreads",
        ["external_account_id", "execution_mode", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_bull_put_spreads_history_page", table_name="bull_put_spreads")

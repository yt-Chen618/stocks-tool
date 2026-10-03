"""add optional journal execution mode provenance

Revision ID: 20261004_0024
Revises: 20261004_0023
Create Date: 2026-10-04 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261004_0024"
down_revision: Union[str, None] = "20261004_0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "journal_entries",
        sa.Column("execution_mode", sa.String(length=16), nullable=True),
    )
    op.create_index(
        "ix_journal_entries_execution_mode",
        "journal_entries",
        ["execution_mode"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_journal_entries_execution_mode", table_name="journal_entries")
    op.drop_column("journal_entries", "execution_mode")

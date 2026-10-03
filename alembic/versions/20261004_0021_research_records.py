"""add durable research screens and immutable cases

Revision ID: 20261004_0021
Revises: 20261004_0020
Create Date: 2026-10-04 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20261004_0021"
down_revision: Union[str, None] = "20261004_0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "research_screens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False, server_default="paper"),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("symbols", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_account_id",
            "execution_mode",
            "name",
            name="uq_research_screens_account_mode_name",
        ),
    )
    op.create_index(
        "ix_research_screens_external_account_id",
        "research_screens",
        ["external_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_screens_execution_mode",
        "research_screens",
        ["execution_mode"],
        unique=False,
    )
    op.create_index(
        "ix_research_screens_account_mode_updated",
        "research_screens",
        ["external_account_id", "execution_mode", "updated_at", "id"],
        unique=False,
    )

    op.create_table(
        "research_cases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("screen_id", sa.String(length=36), nullable=True),
        sa.Column("external_account_id", sa.String(length=64), nullable=False),
        sa.Column("execution_mode", sa.String(length=16), nullable=False, server_default="paper"),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("next_action", sa.String(length=1000), nullable=True),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("universe", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("symbols", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("primary_symbol", sa.String(length=32), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data_quality", sa.String(length=32), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("proposal_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("advisor_run_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["screen_id"], ["research_screens.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_research_cases_screen_id",
        "research_cases",
        ["screen_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_cases_external_account_id",
        "research_cases",
        ["external_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_research_cases_execution_mode",
        "research_cases",
        ["execution_mode"],
        unique=False,
    )
    op.create_index(
        "ix_research_cases_as_of",
        "research_cases",
        ["as_of"],
        unique=False,
    )
    op.create_index(
        "ix_research_cases_primary_symbol",
        "research_cases",
        ["primary_symbol"],
        unique=False,
    )
    op.create_index(
        "ix_research_cases_account_mode_as_of",
        "research_cases",
        ["external_account_id", "execution_mode", "as_of", "id"],
        unique=False,
    )
    op.create_index(
        "ix_research_cases_screen_as_of",
        "research_cases",
        ["screen_id", "as_of", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_research_cases_screen_as_of", table_name="research_cases")
    op.drop_index("ix_research_cases_account_mode_as_of", table_name="research_cases")
    op.drop_index("ix_research_cases_as_of", table_name="research_cases")
    op.drop_index("ix_research_cases_primary_symbol", table_name="research_cases")
    op.drop_index("ix_research_cases_execution_mode", table_name="research_cases")
    op.drop_index("ix_research_cases_external_account_id", table_name="research_cases")
    op.drop_index("ix_research_cases_screen_id", table_name="research_cases")
    op.drop_table("research_cases")
    op.drop_index("ix_research_screens_account_mode_updated", table_name="research_screens")
    op.drop_index("ix_research_screens_execution_mode", table_name="research_screens")
    op.drop_index("ix_research_screens_external_account_id", table_name="research_screens")
    op.drop_table("research_screens")

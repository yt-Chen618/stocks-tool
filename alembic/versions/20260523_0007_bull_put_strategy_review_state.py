"""add bull put strategy review state

Revision ID: 20260523_0007
Revises: 20260523_0006
Create Date: 2026-05-23 13:40:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260523_0007"
down_revision: Union[str, None] = "20260523_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bull_put_strategy_runtime",
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "bull_put_strategy_runtime",
        sa.Column("last_review_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "bull_put_strategy_runtime",
        sa.Column("last_review_summary", sa.Text(), nullable=True),
    )
    op.create_index(
        op.f("ix_bull_put_strategy_runtime_last_review_at"),
        "bull_put_strategy_runtime",
        ["last_review_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_bull_put_strategy_runtime_last_review_at"), table_name="bull_put_strategy_runtime")
    op.drop_column("bull_put_strategy_runtime", "last_review_summary")
    op.drop_column("bull_put_strategy_runtime", "last_review_status")
    op.drop_column("bull_put_strategy_runtime", "last_review_at")

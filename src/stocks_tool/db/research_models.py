"""SQLAlchemy records for the durable research bounded context.

The JSON columns use PostgreSQL JSONB in production and generic JSON on
SQLite, which keeps focused repository tests inexpensive without changing the
stored shape used by the application.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stocks_tool.db.base import Base


_JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ResearchScreenRecord(Base):
    __tablename__ = "research_screens"
    __table_args__ = (
        UniqueConstraint(
            "external_account_id",
            "execution_mode",
            "name",
            name="uq_research_screens_account_mode_name",
        ),
        Index(
            "ix_research_screens_account_mode_updated",
            "external_account_id",
            "execution_mode",
            "updated_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="paper")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    configuration: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    symbols: Mapped[list] = mapped_column(_JSON_TYPE, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchCaseRecord(Base):
    __tablename__ = "research_cases"
    __table_args__ = (
        Index(
            "ix_research_cases_account_mode_as_of",
            "external_account_id",
            "execution_mode",
            "as_of",
            "id",
        ),
        Index("ix_research_cases_screen_as_of", "screen_id", "as_of", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    screen_id: Mapped[str | None] = mapped_column(
        ForeignKey("research_screens.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="paper")
    title: Mapped[str | None] = mapped_column(String(160))
    notes: Mapped[str | None] = mapped_column(Text)
    next_action: Mapped[str | None] = mapped_column(String(1000))
    configuration: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    universe: Mapped[dict | list] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    symbols: Mapped[list] = mapped_column(_JSON_TYPE, nullable=False, default=list)
    primary_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    data_quality: Mapped[str] = mapped_column(String(32), nullable=False)
    warnings: Mapped[list] = mapped_column(_JSON_TYPE, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    proposal_ids: Mapped[list] = mapped_column(_JSON_TYPE, nullable=False, default=list)
    advisor_run_ids: Mapped[list] = mapped_column(_JSON_TYPE, nullable=False, default=list)
    # Cases are append-only.  This timestamp is an audit timestamp and is not
    # an ``updated_at`` projection; there is deliberately no update method.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

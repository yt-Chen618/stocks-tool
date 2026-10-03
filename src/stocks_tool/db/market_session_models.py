"""SQLAlchemy persistence for immutable market-session comparisons."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import Date, DateTime, ForeignKey, Index, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stocks_tool.db.base import Base


_JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class MarketSessionComparisonRecord(Base):
    __tablename__ = "market_session_comparisons"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_market_session_comparisons_idempotency_key"),
        Index(
            "ix_market_session_comparisons_account_mode_created",
            "external_account_id",
            "execution_mode",
            "created_at",
            "id",
        ),
        Index(
            "ix_market_session_comparisons_account_mode_symbol",
            "external_account_id",
            "execution_mode",
            "symbol",
            "created_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default="paper")
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    currency: Mapped[str | None] = mapped_column(String(8))
    account_currency: Mapped[str | None] = mapped_column(String(8))
    quote_currency: Mapped[str | None] = mapped_column(String(8))
    pre_open_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    baseline_session_date: Mapped[date | None] = mapped_column(Date, index=True)
    target_trading_day: Mapped[date | None] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    data_quality: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    reason_codes: Mapped[list] = mapped_column(_JSON_TYPE, nullable=False, default=list)
    reason_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    field_explanations: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    baseline_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    regular_close_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    after_hours_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    pre_to_regular_close_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    regular_close_to_after_hours_pct: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    baseline_evidence: Mapped[dict | None] = mapped_column(_JSON_TYPE)
    regular_close_evidence: Mapped[dict | None] = mapped_column(_JSON_TYPE)
    post_market_evidence: Mapped[dict | None] = mapped_column(_JSON_TYPE)
    raw_evidence: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    evidence_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

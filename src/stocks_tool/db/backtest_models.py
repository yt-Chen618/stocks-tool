"""SQLAlchemy persistence models for the isolated backtesting subsystem.

These tables intentionally have no relationships to orders, executions,
broker accounts, or strategy ledgers.  The migration creates the same tables
for production PostgreSQL; importing this module is enough for SQLAlchemy's
metadata-based tests to see them.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from stocks_tool.db.base import Base


class BacktestTimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class BacktestDatasetRecord(BacktestTimestampMixin, Base):
    __tablename__ = "backtest_datasets"
    __table_args__ = (
        UniqueConstraint("name", "root_path", name="uq_backtest_datasets_name_root"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    root_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    provider: Mapped[str] = mapped_column(String(160), nullable=False)
    license: Mapped[str] = mapped_column(String(512), nullable=False)
    provenance: Mapped[str] = mapped_column(String(1024), nullable=False)
    symbols: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    declared_start: Mapped[date] = mapped_column(Date, nullable=False)
    declared_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    manifest_payload: Mapped[dict | None] = mapped_column(JSONB)
    manifest_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    data_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    validation_payload: Mapped[dict | None] = mapped_column(JSONB)


class BacktestRunRecord(BacktestTimestampMixin, Base):
    __tablename__ = "backtest_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_backtest_runs_idempotency_key"),
        Index("ix_backtest_runs_state_created", "state", "created_at"),
        Index("ix_backtest_runs_dataset_state", "dataset_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("backtest_datasets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbols: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    initial_cash: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    fee_model: Mapped[dict] = mapped_column(JSONB, nullable=False)
    slippage_model: Mapped[dict] = mapped_column(JSONB, nullable=False)
    lifecycle_model: Mapped[dict] = mapped_column(JSONB, nullable=False)
    run_manifest: Mapped[dict] = mapped_column(JSONB, nullable=False)
    code_version: Mapped[str] = mapped_column(String(160), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(120), nullable=False)
    engine_image_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    data_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    process_identity: Mapped[dict | None] = mapped_column(JSONB)
    lease_owner: Mapped[str | None] = mapped_column(String(128), index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    result_summary: Mapped[dict | None] = mapped_column(JSONB)


class BacktestResultRecord(Base):
    __tablename__ = "backtest_results"
    __table_args__ = (UniqueConstraint("run_id", name="uq_backtest_results_run_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("backtest_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    semantic_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metrics_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    trades_payload: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    equity_curve_payload: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BacktestLeaseRecord(Base):
    __tablename__ = "backtest_leases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

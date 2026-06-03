from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from stocks_tool.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class UserRecord(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class BrokerAccountRecord(TimestampMixin, Base):
    __tablename__ = "broker_accounts"
    __table_args__ = (
        UniqueConstraint("broker", "external_account_id", name="uq_broker_accounts_broker_external_account_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    broker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD", server_default="USD")
    options_level: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    auto_reconcile_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    account_sync_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="idle",
        server_default="idle",
    )
    account_last_sync_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_last_sync_error: Mapped[str | None] = mapped_column(Text)
    orders_sync_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="idle",
        server_default="idle",
    )
    orders_last_sync_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    orders_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    orders_last_sync_error: Mapped[str | None] = mapped_column(Text)

    user: Mapped[UserRecord | None] = relationship()


class MarketEventRecord(TimestampMixin, Base):
    __tablename__ = "market_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="medium",
        server_default="medium",
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)


class WatchlistRecord(TimestampMixin, Base):
    __tablename__ = "watchlists"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    user: Mapped[UserRecord | None] = relationship()
    items: Mapped[list[WatchlistItemRecord]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
    )


class WatchlistItemRecord(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "symbol", name="uq_watchlist_items_watchlist_symbol"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    watchlist_id: Mapped[str] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    watchlist: Mapped[WatchlistRecord] = relationship(back_populates="items")


class TradePlanRecord(TimestampMixin, Base):
    __tablename__ = "trade_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    structure: Mapped[str] = mapped_column(String(32), nullable=False)
    bias: Mapped[str] = mapped_column(String(16), nullable=False)
    catalyst_type: Mapped[str] = mapped_column(String(32), nullable=False)
    thesis: Mapped[str] = mapped_column(Text, nullable=False)
    entry_minimum: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    entry_maximum: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    take_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    invalidation: Mapped[str] = mapped_column(Text, nullable=False)
    holding_period_days: Mapped[int] = mapped_column(Integer, nullable=False)
    max_account_risk_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    estimated_max_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    option_underlying_symbol: Mapped[str | None] = mapped_column(String(32))
    option_expiration_date: Mapped[date | None] = mapped_column(Date)
    option_strike: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    option_right: Mapped[str | None] = mapped_column(String(8))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    context_payload: Mapped[dict | None] = mapped_column(JSONB)

    user: Mapped[UserRecord | None] = relationship()
    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class AccountSnapshotRecord(Base):
    __tablename__ = "account_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    broker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD", server_default="USD")
    cash_balance: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    net_liquidation: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    buying_power: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    day_trade_buying_power: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    options_level: Mapped[str | None] = mapped_column(String(32))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()
    positions: Mapped[list[PositionSnapshotRecord]] = relationship(
        back_populates="account_snapshot",
        cascade="all, delete-orphan",
    )


class PositionSnapshotRecord(Base):
    __tablename__ = "position_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    account_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("account_snapshots.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    average_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    market_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    option_underlying_symbol: Mapped[str | None] = mapped_column(String(32))
    option_expiration_date: Mapped[date | None] = mapped_column(Date)
    option_strike: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    option_right: Mapped[str | None] = mapped_column(String(8))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

    account_snapshot: Mapped[AccountSnapshotRecord] = relationship(back_populates="positions")


class OrderRecord(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    trade_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_plans.id", ondelete="SET NULL"),
        index=True,
    )
    broker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_order_id: Mapped[str | None] = mapped_column(String(128), index=True)
    client_order_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_type: Mapped[str | None] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    time_in_force: Mapped[str] = mapped_column(String(16), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    stop_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="created", server_default="created")
    option_underlying_symbol: Mapped[str | None] = mapped_column(String(32))
    option_expiration_date: Mapped[date | None] = mapped_column(Date)
    option_strike: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    option_right: Mapped[str | None] = mapped_column(String(8))
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()
    trade_plan: Mapped[TradePlanRecord | None] = relationship()
    executions: Mapped[list["ExecutionRecord"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )


class ExecutionRecord(TimestampMixin, Base):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    broker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_order_id: Mapped[str | None] = mapped_column(String(128), index=True)
    external_execution_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

    order: Mapped[OrderRecord] = relationship(back_populates="executions")


class BullPutSpreadRecord(TimestampMixin, Base):
    __tablename__ = "bull_put_spreads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    broker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strategy_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        default="paper_bull_put_v1",
        server_default="paper_bull_put_v1",
    )
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    underlying_symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    contracts: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    long_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    long_strike: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    short_symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    short_strike: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    long_entry_order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    short_entry_order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    long_exit_order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    short_exit_order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    entry_long_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    entry_short_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    entry_net_credit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    max_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    max_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    break_even: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    account_risk_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    exit_reason: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)
    entry_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class BullPutStrategyRuntimeRecord(TimestampMixin, Base):
    __tablename__ = "bull_put_strategy_runtime"
    __table_args__ = (
        UniqueConstraint("external_account_id", "strategy_id", name="uq_bull_put_strategy_runtime_account_strategy"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    strategy_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        default="paper_bull_put_v1",
        server_default="paper_bull_put_v1",
    )
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    auto_entry_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    manual_pause: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    kill_switch_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    paused_symbols: Mapped[list[str] | None] = mapped_column(JSONB)
    current_session_date: Mapped[date | None] = mapped_column(Date, index=True)
    daily_entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    daily_realized_pnl: Mapped[Decimal] = mapped_column(
        Numeric(18, 4),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_scan_result: Mapped[str | None] = mapped_column(String(32))
    last_scan_symbol: Mapped[str | None] = mapped_column(String(32))
    last_skip_reason: Mapped[str | None] = mapped_column(Text)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_action: Mapped[str | None] = mapped_column(Text)
    last_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_review_status: Mapped[str | None] = mapped_column(String(32))
    last_review_summary: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class PreOpenAssessmentRunRecord(TimestampMixin, Base):
    __tablename__ = "pre_open_assessment_runs"
    __table_args__ = (
        UniqueConstraint(
            "external_account_id",
            "strategy_id",
            "target_session_date",
            name="uq_pre_open_assessment_runs_account_strategy_session_date",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    strategy_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        default="pre_open_put_check_v1",
        server_default="pre_open_put_check_v1",
    )
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    assessment_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    checkpoints_payload: Mapped[list | None] = mapped_column(JSONB)
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    review_summary: Mapped[str | None] = mapped_column(Text)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    review_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class StrategyProposalRecord(TimestampMixin, Base):
    __tablename__ = "strategy_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    proposed_action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    thesis: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        index=True,
        default="pending",
        server_default="pending",
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    expected_max_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    expected_max_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    source: Mapped[str | None] = mapped_column(String(64))
    source_run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    candidate_payload: Mapped[dict | None] = mapped_column(JSONB)
    risk_payload: Mapped[dict | None] = mapped_column(JSONB)
    checks: Mapped[list[str] | None] = mapped_column(JSONB)

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class StrategyRunRecord(TimestampMixin, Base):
    __tablename__ = "strategy_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    run_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), index=True)
    trade_plan_id: Mapped[str | None] = mapped_column(String(36), index=True)
    order_id: Mapped[str | None] = mapped_column(String(36), index=True)
    spread_id: Mapped[str | None] = mapped_column(String(36), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    metrics_payload: Mapped[dict | None] = mapped_column(JSONB)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB)

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class StrategySignalRecord(Base):
    __tablename__ = "strategy_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), index=True)
    strength: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    summary: Mapped[str] = mapped_column(String(240), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(64))
    signal_payload: Mapped[dict | None] = mapped_column(JSONB)
    emitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class StrategyReviewRecord(TimestampMixin, Base):
    __tablename__ = "strategy_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    review_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str | None] = mapped_column(Text)
    parameter_name: Mapped[str | None] = mapped_column(String(64))
    current_value: Mapped[str | None] = mapped_column(String(120))
    suggested_value: Mapped[str | None] = mapped_column(String(120))
    run_id: Mapped[str | None] = mapped_column(String(36), index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), index=True)
    journal_entry_id: Mapped[str | None] = mapped_column(String(36), index=True)
    metrics_payload: Mapped[dict | None] = mapped_column(JSONB)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class StrategyAdvisorRunRecord(TimestampMixin, Base):
    __tablename__ = "strategy_advisor_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    broker_account_id: Mapped[str | None] = mapped_column(
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        index=True,
    )
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    execution_mode: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(64), index=True)
    model: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    context_format: Mapped[str | None] = mapped_column(String(32), index=True)
    context_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=10, server_default="10")
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_hit_tokens: Mapped[int | None] = mapped_column(Integer)
    cache_miss_tokens: Mapped[int | None] = mapped_column(Integer)
    proposal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    response_id: Mapped[str | None] = mapped_column(String(128), index=True)
    finish_reason: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    response_payload: Mapped[dict | None] = mapped_column(JSONB)
    raw_response: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)

    broker_account: Mapped[BrokerAccountRecord | None] = relationship()


class JournalEntryRecord(TimestampMixin, Base):
    __tablename__ = "journal_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    trade_plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("trade_plans.id", ondelete="SET NULL"),
        index=True,
    )
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"),
        index=True,
    )
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("executions.id", ondelete="SET NULL"),
        index=True,
    )
    external_account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entry_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[list[str] | None] = mapped_column(JSONB)

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

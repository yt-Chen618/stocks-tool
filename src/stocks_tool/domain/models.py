from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, Field

from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    CatalystType,
    ExecutionMode,
    MarketBias,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    PlanStatus,
    RiskStatus,
    TimeInForce,
    TradeStructure,
)


class PriceBand(BaseModel):
    minimum: Decimal | None = None
    maximum: Decimal | None = None


class OptionContractRef(BaseModel):
    underlying_symbol: str
    expiration_date: date
    strike: Decimal
    right: OptionRight


class PlanCandidate(BaseModel):
    symbol: str
    asset_type: AssetType = AssetType.STOCK
    catalyst_type: CatalystType
    thesis: str
    news_summary: str | None = None
    momentum_score: float = Field(ge=0, le=1)
    volatility_score: float = Field(ge=0, le=1)
    liquidity_score: float = Field(ge=0, le=1)
    catalyst_score: float = Field(ge=0, le=1)


class CandidateScore(BaseModel):
    candidate: PlanCandidate
    composite_score: float


class ResearchRankingRequest(BaseModel):
    candidates: list[PlanCandidate]


class DraftTradePlanRequest(BaseModel):
    symbol: str
    asset_type: AssetType = AssetType.STOCK
    preferred_structure: TradeStructure | None = None
    bias: MarketBias
    catalyst_type: CatalystType
    thesis: str
    entry: PriceBand
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    invalidation: str
    holding_period_days: int = Field(ge=1, le=90)
    max_account_risk_pct: Decimal = Field(default=Decimal("0.01"), gt=0)
    estimated_max_loss: Decimal | None = None
    option_contract: OptionContractRef | None = None
    notes: str | None = None


class TradePlan(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    asset_type: AssetType
    structure: TradeStructure
    bias: MarketBias
    thesis: str
    catalyst_type: CatalystType
    entry: PriceBand
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    invalidation: str
    holding_period_days: int
    max_account_risk_pct: Decimal
    estimated_max_loss: Decimal | None = None
    option_contract: OptionContractRef | None = None
    notes: str | None = None
    status: PlanStatus = PlanStatus.DRAFT
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PositionSnapshot(BaseModel):
    symbol: str
    asset_type: AssetType
    quantity: Decimal
    average_cost: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal
    raw_payload: dict | None = None


class AccountSnapshot(BaseModel):
    id: str | None = None
    broker: BrokerName
    account_id: str
    currency: str = "USD"
    cash_balance: Decimal
    net_liquidation: Decimal
    buying_power: Decimal
    day_trade_buying_power: Decimal | None = None
    options_level: str | None = None
    positions: list[PositionSnapshot] = Field(default_factory=list)
    raw_payload: dict | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskCheckResult(BaseModel):
    status: RiskStatus
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RiskEvaluationRequest(BaseModel):
    plan: TradePlan
    account: AccountSnapshot
    mode: ExecutionMode = ExecutionMode.PAPER


class OrderIntent(BaseModel):
    plan_id: str
    broker: str
    symbol: str
    side: OrderSide
    quantity: int = Field(gt=0)
    order_type: OrderType
    time_in_force: TimeInForce
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    mode: ExecutionMode
    option_contract: OptionContractRef | None = None


class OrderIntentRequest(BaseModel):
    plan: TradePlan
    broker: str = BrokerName.LONGBRIDGE.value
    quantity: int = Field(gt=0)
    mode: ExecutionMode = ExecutionMode.PAPER


class CreateOrderRequest(BaseModel):
    external_account_id: str
    broker: BrokerName = BrokerName.LONGBRIDGE
    symbol: str
    asset_type: AssetType = AssetType.STOCK
    side: OrderSide
    quantity: int = Field(gt=0)
    order_type: OrderType
    time_in_force: TimeInForce = TimeInForce.DAY
    mode: ExecutionMode = ExecutionMode.PAPER
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    option_contract: OptionContractRef | None = None
    trade_plan_id: str | None = None
    remark: str | None = Field(default=None, max_length=64)


class Order(BaseModel):
    id: str
    broker: BrokerName
    external_account_id: str
    trade_plan_id: str | None = None
    external_order_id: str | None = None
    client_order_id: str | None = None
    symbol: str
    asset_type: AssetType | None = None
    side: OrderSide
    quantity: int
    order_type: OrderType
    time_in_force: TimeInForce
    mode: ExecutionMode
    status: OrderStatus
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    option_contract: OptionContractRef | None = None
    raw_payload: dict | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class BrokerOrderSnapshot(BaseModel):
    external_order_id: str
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType
    time_in_force: TimeInForce
    mode: ExecutionMode
    status: OrderStatus
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    submitted_at: datetime | None = None
    raw_payload: dict | None = None


class ReplaceOrderRequest(BaseModel):
    quantity: int = Field(gt=0)
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    remark: str | None = Field(default=None, max_length=64)


class OrderSyncResult(BaseModel):
    broker: BrokerName
    external_account_id: str
    mode: ExecutionMode
    synced_orders: int
    created_orders: int
    updated_orders: int
    orders: list[Order] = Field(default_factory=list)


class BrokerCapability(BaseModel):
    name: str
    supported: bool
    notes: str


class BrokerProfile(BaseModel):
    name: BrokerName
    supported_modes: list[ExecutionMode]
    capabilities: list[BrokerCapability]


class BrokerConfigurationStatus(BaseModel):
    broker: BrokerName
    app_key_configured: bool
    app_secret_configured: bool
    paper_token_configured: bool
    live_token_configured: bool


class WatchlistItem(BaseModel):
    id: str
    symbol: str
    asset_type: AssetType
    notes: str | None = None
    created_at: datetime


class Watchlist(BaseModel):
    id: str
    name: str
    description: str | None = None
    is_default: bool = False
    items: list[WatchlistItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CreateWatchlistRequest(BaseModel):
    name: str
    description: str | None = None
    is_default: bool = False


class AddWatchlistItemRequest(BaseModel):
    symbol: str
    asset_type: AssetType
    notes: str | None = None


class BrokerAccount(BaseModel):
    id: str
    broker: BrokerName
    external_account_id: str
    display_name: str | None = None
    base_currency: str = "USD"
    options_level: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime


class CreateBrokerAccountRequest(BaseModel):
    broker: BrokerName
    external_account_id: str
    display_name: str | None = None
    base_currency: str = "USD"
    options_level: str | None = None
    is_active: bool = True


class SessionQuote(BaseModel):
    last_done: Decimal
    timestamp: datetime
    volume: int
    turnover: Decimal
    high: Decimal
    low: Decimal
    prev_close: Decimal


class SecurityQuoteSnapshot(BaseModel):
    symbol: str
    last_done: Decimal
    prev_close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    timestamp: datetime
    volume: int
    turnover: Decimal
    trade_status: str
    pre_market_quote: SessionQuote | None = None
    post_market_quote: SessionQuote | None = None
    overnight_quote: SessionQuote | None = None


class BrokerAccountSyncResult(BaseModel):
    broker: BrokerName
    mode: ExecutionMode
    external_account_id: str
    snapshot_id: str | None = None
    positions_synced: int
    account_snapshot: AccountSnapshot

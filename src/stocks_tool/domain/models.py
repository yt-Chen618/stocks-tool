from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, Field

from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    CatalystType,
    ExecutionMode,
    JournalEntryType,
    MarketBias,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    PlanStatus,
    ReconciliationStatus,
    RiskStatus,
    SpreadStatus,
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
    executed_quantity: int = 0
    executed_price: Decimal | None = None
    submitted_at: datetime | None = None
    updated_at: datetime | None = None
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


class Execution(BaseModel):
    id: str
    order_id: str
    broker: BrokerName
    external_account_id: str
    external_order_id: str | None = None
    external_execution_id: str | None = None
    symbol: str
    side: OrderSide
    quantity: int = Field(ge=0)
    price: Decimal | None = None
    executed_at: datetime | None = None
    raw_payload: dict | None = None
    created_at: datetime
    updated_at: datetime


class CreateJournalEntryRequest(BaseModel):
    external_account_id: str
    symbol: str
    entry_type: JournalEntryType
    title: str = Field(min_length=1, max_length=120)
    notes: str = Field(min_length=1)
    order_id: str | None = None
    trade_plan_id: str | None = None
    execution_id: str | None = None
    tags: list[str] = Field(default_factory=list)


class JournalEntry(BaseModel):
    id: str
    external_account_id: str
    symbol: str
    entry_type: JournalEntryType
    title: str
    notes: str
    order_id: str | None = None
    trade_plan_id: str | None = None
    execution_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


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
    auto_reconcile_enabled: bool = True
    account_sync_status: ReconciliationStatus = ReconciliationStatus.IDLE
    account_last_sync_attempt_at: datetime | None = None
    account_last_synced_at: datetime | None = None
    account_last_sync_error: str | None = None
    orders_sync_status: ReconciliationStatus = ReconciliationStatus.IDLE
    orders_last_sync_attempt_at: datetime | None = None
    orders_last_synced_at: datetime | None = None
    orders_last_sync_error: str | None = None
    created_at: datetime
    updated_at: datetime


class CreateBrokerAccountRequest(BaseModel):
    broker: BrokerName
    external_account_id: str
    display_name: str | None = None
    base_currency: str = "USD"
    options_level: str | None = None
    is_active: bool = True
    auto_reconcile_enabled: bool = True


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


class HistoricalPriceBar(BaseModel):
    symbol: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal
    raw_payload: dict | None = None


class OptionChainEntry(BaseModel):
    strike: Decimal
    call_symbol: str | None = None
    put_symbol: str | None = None
    standard: bool = True


class OptionMarketSnapshot(BaseModel):
    symbol: str
    underlying_symbol: str
    expiration_date: date
    strike: Decimal
    right: OptionRight
    last_done: Decimal
    prev_close: Decimal
    open: Decimal
    high: Decimal
    low: Decimal
    timestamp: datetime
    volume: int
    turnover: Decimal
    trade_status: str | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    open_interest: int | None = None
    implied_volatility: Decimal | None = None
    historical_volatility: Decimal | None = None
    delta: Decimal | None = None
    gamma: Decimal | None = None
    theta: Decimal | None = None
    vega: Decimal | None = None
    contract_multiplier: Decimal = Decimal("100")
    contract_size: Decimal | None = None
    raw_payload: dict | None = None


class BullPutSpreadCandidate(BaseModel):
    underlying_symbol: str
    expiration_date: date
    days_to_expiration: int
    width: Decimal
    short_put: OptionMarketSnapshot
    long_put: OptionMarketSnapshot
    short_mid: Decimal
    long_mid: Decimal
    mid_credit: Decimal
    conservative_credit: Decimal


class BullPutSpreadRiskSummary(BaseModel):
    width: Decimal
    contract_multiplier: Decimal
    contracts: int
    max_profit: Decimal
    max_loss: Decimal
    break_even: Decimal
    return_on_risk: Decimal | None = None
    account_risk_pct: Decimal | None = None
    status: RiskStatus
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class BullPutSpreadScanResult(BaseModel):
    strategy_id: str = "paper_bull_put_v1"
    symbol: str
    mode: ExecutionMode
    external_account_id: str
    scanned_at: datetime
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    underlying_quote: SecurityQuoteSnapshot | None = None
    selected_expiration_date: date | None = None
    days_to_expiration: int | None = None
    moving_average_20: Decimal | None = None
    moving_average_50: Decimal | None = None
    candidate: BullPutSpreadCandidate | None = None
    risk: BullPutSpreadRiskSummary | None = None


class ExecuteBullPutSpreadRequest(BaseModel):
    external_account_id: str
    symbol: str
    mode: ExecutionMode = ExecutionMode.PAPER
    as_of: datetime | None = None
    remark: str | None = Field(default=None, max_length=64)


class BullPutSpread(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_id: str = "paper_bull_put_v1"
    broker: BrokerName
    external_account_id: str
    mode: ExecutionMode
    underlying_symbol: str
    expiration_date: date
    contracts: int = Field(gt=0)
    width: Decimal
    long_symbol: str
    long_strike: Decimal
    short_symbol: str
    short_strike: Decimal
    status: SpreadStatus
    long_entry_order_id: str | None = None
    short_entry_order_id: str | None = None
    long_exit_order_id: str | None = None
    short_exit_order_id: str | None = None
    entry_long_price: Decimal | None = None
    entry_short_price: Decimal | None = None
    entry_net_credit: Decimal | None = None
    max_profit: Decimal | None = None
    max_loss: Decimal | None = None
    break_even: Decimal | None = None
    account_risk_pct: Decimal | None = None
    exit_reason: str | None = None
    raw_payload: dict | None = None
    entry_started_at: datetime | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None
    last_synced_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class BullPutSpreadMonitorResult(BaseModel):
    spread: BullPutSpread
    evaluated_at: datetime
    should_close: bool
    exit_reason: str | None = None
    current_underlying_price: Decimal | None = None
    estimated_exit_debit: Decimal | None = None
    estimated_pnl: Decimal | None = None
    days_to_expiration: int | None = None


class BullPutStrategyRuntimeState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_id: str = "paper_bull_put_v1"
    external_account_id: str
    mode: ExecutionMode
    auto_entry_enabled: bool = True
    manual_pause: bool = False
    kill_switch_active: bool = False
    paused_symbols: list[str] = Field(default_factory=list)
    current_session_date: date | None = None
    daily_entry_count: int = 0
    daily_realized_pnl: Decimal = Decimal("0")
    last_scan_at: datetime | None = None
    last_scan_result: str | None = None
    last_scan_symbol: str | None = None
    last_skip_reason: str | None = None
    last_action_at: datetime | None = None
    last_action: str | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UpdateBullPutStrategyRuntimeRequest(BaseModel):
    auto_entry_enabled: bool | None = None
    manual_pause: bool | None = None
    kill_switch_active: bool | None = None
    paused_symbols: list[str] | None = None


class BullPutStrategyScanRunResult(BaseModel):
    strategy_state: BullPutStrategyRuntimeState
    scanned_at: datetime
    executed: bool
    executed_spread: BullPutSpread | None = None
    previews: list[BullPutSpreadScanResult] = Field(default_factory=list)
    reason: str | None = None


class BrokerAccountSyncResult(BaseModel):
    broker: BrokerName
    mode: ExecutionMode
    external_account_id: str
    snapshot_id: str | None = None
    positions_synced: int
    account_snapshot: AccountSnapshot

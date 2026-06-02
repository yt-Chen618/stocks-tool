from __future__ import annotations

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
    MarketEventSeverity,
    MarketEventType,
    MarketBias,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    PlanStatus,
    ReconciliationStatus,
    RiskStatus,
    SpreadStatus,
    StrategyProposalStatus,
    StrategyReviewStatus,
    StrategyRunStatus,
    StrategySignalType,
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


class AccountSnapshotPositionSummary(BaseModel):
    symbol: str
    asset_type: AssetType
    quantity: Decimal
    average_cost: Decimal
    market_value: Decimal
    unrealized_pnl: Decimal


class AccountSnapshotSummary(BaseModel):
    account_id: str
    currency: str = "USD"
    cash_balance: Decimal
    net_liquidation: Decimal
    buying_power: Decimal
    positions: list[AccountSnapshotPositionSummary] = Field(default_factory=list)
    captured_at: datetime

    @classmethod
    def from_snapshot(cls, snapshot: AccountSnapshot) -> "AccountSnapshotSummary":
        return cls(
            account_id=snapshot.account_id,
            currency=snapshot.currency,
            cash_balance=snapshot.cash_balance,
            net_liquidation=snapshot.net_liquidation,
            buying_power=snapshot.buying_power,
            positions=[
                AccountSnapshotPositionSummary(
                    symbol=position.symbol,
                    asset_type=position.asset_type,
                    quantity=position.quantity,
                    average_cost=position.average_cost,
                    market_value=position.market_value,
                    unrealized_pnl=position.unrealized_pnl,
                )
                for position in snapshot.positions
            ],
            captured_at=snapshot.captured_at,
        )


class CreateMarketEventRequest(BaseModel):
    symbol: str | None = Field(default=None, max_length=32)
    event_type: MarketEventType
    title: str = Field(min_length=1, max_length=160)
    scheduled_at: datetime
    source: str | None = Field(default=None, max_length=64)
    severity: MarketEventSeverity = MarketEventSeverity.MEDIUM
    notes: str | None = None
    raw_payload: dict | None = None


class ImportMarketEventsRequest(BaseModel):
    events: list[CreateMarketEventRequest] = Field(default_factory=list)


class ImportMarketEventsFromProviderRequest(BaseModel):
    provider: str = Field(default="fmp", min_length=1, max_length=32)
    start: date
    end: date
    symbols: list[str] = Field(default_factory=list)


class MarketEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str | None = None
    event_type: MarketEventType
    title: str
    scheduled_at: datetime
    source: str | None = None
    severity: MarketEventSeverity = MarketEventSeverity.MEDIUM
    notes: str | None = None
    raw_payload: dict | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MarketEventImportResult(BaseModel):
    requested: int
    created: int
    skipped_duplicates: int
    events: list[MarketEvent] = Field(default_factory=list)


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


class CreateStrategyProposalRequest(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=64)
    external_account_id: str
    mode: ExecutionMode = ExecutionMode.PAPER
    symbol: str | None = Field(default=None, max_length=32)
    title: str = Field(min_length=1, max_length=160)
    proposed_action: str = Field(min_length=1, max_length=64)
    thesis: str | None = None
    rationale: str = Field(min_length=1)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    expected_max_loss: Decimal | None = Field(default=None, ge=0)
    expected_max_profit: Decimal | None = None
    approval_required: bool = True
    expires_at: datetime | None = None
    source: str | None = Field(default=None, max_length=64)
    source_run_id: str | None = Field(default=None, max_length=36)
    candidate_payload: dict | None = None
    risk_payload: dict | None = None
    checks: list[str] = Field(default_factory=list)


class StrategyProposal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_id: str
    external_account_id: str
    mode: ExecutionMode
    symbol: str | None = None
    title: str
    proposed_action: str
    thesis: str | None = None
    rationale: str
    status: StrategyProposalStatus = StrategyProposalStatus.PENDING
    confidence: Decimal | None = None
    expected_max_loss: Decimal | None = None
    expected_max_profit: Decimal | None = None
    approval_required: bool = True
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    expires_at: datetime | None = None
    source: str | None = None
    source_run_id: str | None = None
    candidate_payload: dict | None = None
    risk_payload: dict | None = None
    checks: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateStrategyRunRequest(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=64)
    external_account_id: str
    mode: ExecutionMode = ExecutionMode.PAPER
    run_type: str = Field(min_length=1, max_length=64)
    status: StrategyRunStatus = StrategyRunStatus.PLANNED
    symbol: str | None = Field(default=None, max_length=32)
    proposal_id: str | None = Field(default=None, max_length=36)
    trade_plan_id: str | None = Field(default=None, max_length=36)
    order_id: str | None = Field(default=None, max_length=36)
    spread_id: str | None = Field(default=None, max_length=36)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: str | None = None
    reason: str | None = None
    metrics_payload: dict | None = None
    raw_payload: dict | None = None


class StrategyRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_id: str
    external_account_id: str
    mode: ExecutionMode
    run_type: str
    status: StrategyRunStatus
    symbol: str | None = None
    proposal_id: str | None = None
    trade_plan_id: str | None = None
    order_id: str | None = None
    spread_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    summary: str | None = None
    reason: str | None = None
    metrics_payload: dict | None = None
    raw_payload: dict | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateStrategySignalRequest(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=64)
    external_account_id: str
    mode: ExecutionMode = ExecutionMode.PAPER
    signal_type: StrategySignalType
    symbol: str | None = Field(default=None, max_length=32)
    run_id: str | None = Field(default=None, max_length=36)
    proposal_id: str | None = Field(default=None, max_length=36)
    strength: Decimal | None = Field(default=None, ge=-1, le=1)
    summary: str = Field(min_length=1, max_length=240)
    detail: str | None = None
    source: str | None = Field(default=None, max_length=64)
    signal_payload: dict | None = None
    emitted_at: datetime | None = None


class StrategySignal(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_id: str
    external_account_id: str
    mode: ExecutionMode
    signal_type: StrategySignalType
    symbol: str | None = None
    run_id: str | None = None
    proposal_id: str | None = None
    strength: Decimal | None = None
    summary: str
    detail: str | None = None
    source: str | None = None
    signal_payload: dict | None = None
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CreateStrategyReviewRequest(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=64)
    external_account_id: str
    mode: ExecutionMode = ExecutionMode.PAPER
    review_type: str = Field(min_length=1, max_length=64)
    status: StrategyReviewStatus
    summary: str = Field(min_length=1)
    recommendation: str | None = None
    parameter_name: str | None = Field(default=None, max_length=64)
    current_value: str | None = Field(default=None, max_length=120)
    suggested_value: str | None = Field(default=None, max_length=120)
    run_id: str | None = Field(default=None, max_length=36)
    proposal_id: str | None = Field(default=None, max_length=36)
    journal_entry_id: str | None = Field(default=None, max_length=36)
    metrics_payload: dict | None = None
    reviewed_at: datetime | None = None


class StrategyReview(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_id: str
    external_account_id: str
    mode: ExecutionMode
    review_type: str
    status: StrategyReviewStatus
    summary: str
    recommendation: str | None = None
    parameter_name: str | None = None
    current_value: str | None = None
    suggested_value: str | None = None
    run_id: str | None = None
    proposal_id: str | None = None
    journal_entry_id: str | None = None
    metrics_payload: dict | None = None
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StrategyExperimentSnapshot(BaseModel):
    external_account_id: str | None = None
    proposals: list[StrategyProposal] = Field(default_factory=list)
    runs: list[StrategyRun] = Field(default_factory=list)
    signals: list[StrategySignal] = Field(default_factory=list)
    reviews: list[StrategyReview] = Field(default_factory=list)


class CoveredCallLifecycleTask(BaseModel):
    proposal_id: str
    proposal_title: str
    symbol: str | None = None
    task_type: str
    proposal_status: StrategyProposalStatus
    last_run_id: str | None = None
    last_run_type: str | None = None
    open_order_id: str | None = None
    close_order_id: str | None = None
    roll_buyback_order_id: str | None = None
    roll_sell_order_id: str | None = None
    open_status: str | None = None
    close_status: str | None = None
    buyback_status: str | None = None
    sell_status: str | None = None
    sequence_status: str | None = None
    last_refresh_status: str | None = None
    last_refresh_at: datetime | None = None
    order_submitted_at: datetime | None = None
    order_age_seconds: int | None = None
    stale_after_seconds: int | None = None
    is_stale: bool = False
    diagnostic: str | None = None
    suggested_action: str | None = None
    summary: str | None = None
    reason: str | None = None


class CoveredCallActivitySummary(BaseModel):
    external_account_id: str | None = None
    total_proposals: int = 0
    active_proposals: int = 0
    executed_positions: int = 0
    pending_rolls: int = 0
    close_runs: int = 0
    latest_activity_at: datetime | None = None


class CoveredCallMonitorSnapshot(BaseModel):
    proposal_id: str | None = None
    symbol: str | None = None
    action: str | None = None
    detail: str | None = None
    underlying_price: Decimal | None = None
    call_mark: Decimal | None = None
    estimated_open_pnl: Decimal | None = None
    premium_capture_pct: Decimal | None = None
    days_to_expiration: int | None = None
    emitted_at: datetime | None = None
    signal_id: str | None = None


class CoveredCallActivitySnapshot(BaseModel):
    external_account_id: str | None = None
    summary: CoveredCallActivitySummary = Field(default_factory=CoveredCallActivitySummary)
    lifecycle_tasks: list[CoveredCallLifecycleTask] = Field(default_factory=list)
    latest_monitor: CoveredCallMonitorSnapshot | None = None
    proposals: list[StrategyProposal] = Field(default_factory=list)
    runs: list[StrategyRun] = Field(default_factory=list)
    signals: list[StrategySignal] = Field(default_factory=list)
    reviews: list[StrategyReview] = Field(default_factory=list)


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


class CoveredCallCandidate(BaseModel):
    underlying_symbol: str
    expiration_date: date
    days_to_expiration: int
    contracts: int
    covered_shares: int
    share_quantity: Decimal
    average_cost: Decimal
    underlying_price: Decimal
    call_symbol: str
    call_strike: Decimal
    call_bid: Decimal
    call_ask: Decimal
    call_mid: Decimal
    premium_income: Decimal
    annualized_income_yield: Decimal | None = None
    if_called_return_pct: Decimal | None = None
    delta: Decimal | None = None
    open_interest: int | None = None
    volume: int = 0
    quote_timestamp: datetime


class CoveredCallRiskSummary(BaseModel):
    status: RiskStatus
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    max_income: Decimal
    max_assignment_profit: Decimal | None = None
    max_loss_if_zero: Decimal | None = None
    break_even: Decimal | None = None
    shares_not_covered: Decimal = Decimal("0")


class CoveredCallPreviewResult(BaseModel):
    strategy_id: str = "covered_call_v1"
    external_account_id: str
    mode: ExecutionMode
    evaluated_at: datetime
    eligible: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    symbol: str | None = None
    selected_expiration_date: date | None = None
    days_to_expiration: int | None = None
    candidate: CoveredCallCandidate | None = None
    risk: CoveredCallRiskSummary | None = None


class CoveredCallProposalResult(BaseModel):
    preview: CoveredCallPreviewResult
    proposal: StrategyProposal | None = None
    run: StrategyRun | None = None
    signal: StrategySignal | None = None


class ExecuteCoveredCallProposalRequest(BaseModel):
    limit_price: Decimal | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=64)


class CoveredCallExecutionResult(BaseModel):
    proposal: StrategyProposal
    order: Order
    run: StrategyRun | None = None
    signal: StrategySignal | None = None
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CoveredCallMonitorResult(BaseModel):
    strategy_id: str = "covered_call_v1"
    proposal_id: str
    external_account_id: str
    symbol: str
    evaluated_at: datetime
    candidate: CoveredCallCandidate
    underlying_price: Decimal
    call_mark: Decimal | None = None
    estimated_buyback_debit: Decimal | None = None
    estimated_open_pnl: Decimal | None = None
    premium_capture_pct: Decimal | None = None
    days_to_expiration: int
    action: str
    reasons: list[str] = Field(default_factory=list)
    signal: StrategySignal | None = None


class CreateCoveredCallRollProposalRequest(BaseModel):
    as_of: datetime | None = None
    min_new_expiration_date: date | None = None


class CoveredCallRollProposalResult(BaseModel):
    current_monitor: CoveredCallMonitorResult
    next_preview: CoveredCallPreviewResult
    proposal: StrategyProposal | None = None
    run: StrategyRun | None = None
    signal: StrategySignal | None = None


class ExecuteCoveredCallRollProposalRequest(BaseModel):
    buyback_limit_price: Decimal | None = Field(default=None, gt=0)
    sell_limit_price: Decimal | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=64)


class ContinueCoveredCallRollRequest(BaseModel):
    buyback_order_id: str = Field(min_length=1, max_length=36)
    sell_order_id: str | None = Field(default=None, min_length=1, max_length=36)
    sell_limit_price: Decimal | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=64)


class CoveredCallRollExecutionResult(BaseModel):
    proposal: StrategyProposal
    buyback_order: Order
    sell_order: Order | None = None
    run: StrategyRun | None = None
    signal: StrategySignal | None = None
    sequence_status: str
    reason: str | None = None
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CloseCoveredCallProposalRequest(BaseModel):
    limit_price: Decimal | None = Field(default=None, gt=0)
    remark: str | None = Field(default=None, max_length=64)


class CoveredCallCloseResult(BaseModel):
    proposal: StrategyProposal
    order: Order
    run: StrategyRun | None = None
    signal: StrategySignal | None = None
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


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
    candidate_token: str | None = None
    timing_ms: dict[str, int] = Field(default_factory=dict)


class BullPutStrategyReadinessCheck(BaseModel):
    name: str
    status: str
    detail: str
    blocking: bool = False


class BullPutStrategyReadinessResult(BaseModel):
    strategy_id: str = "paper_bull_put_v1"
    external_account_id: str
    mode: ExecutionMode
    evaluated_at: datetime
    ready: bool
    status: str
    checks: list[BullPutStrategyReadinessCheck] = Field(default_factory=list)
    previews: list[BullPutSpreadScanResult] = Field(default_factory=list)
    preferred_symbol: str | None = None
    next_action: str | None = None


class ExecuteBullPutSpreadRequest(BaseModel):
    external_account_id: str
    symbol: str
    mode: ExecutionMode = ExecutionMode.PAPER
    as_of: datetime | None = None
    candidate_token: str | None = Field(default=None, max_length=96)
    minimum_net_credit: Decimal | None = Field(default=None, gt=0)
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
    last_review_at: datetime | None = None
    last_review_status: str | None = None
    last_review_summary: str | None = None
    last_error: str | None = None
    holding_open_position: bool = False
    daily_entry_cap_reached: bool = False
    entry_block_reason: str | None = None
    next_action: str | None = None
    active_spread_count: int = 0
    open_spread_count: int = 0
    next_monitor_after: datetime | None = None
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


class BullPutStrategyReviewResult(BaseModel):
    strategy_state: BullPutStrategyRuntimeState
    evaluated_at: datetime
    review_status: str
    closed_spreads_considered: int
    lookback_days: int
    net_realized_pnl: Decimal | None = None
    take_profit_rate: Decimal | None = None
    stop_loss_rate: Decimal | None = None
    recommendation: str | None = None
    parameter_name: str | None = None
    current_value: str | None = None
    suggested_value: str | None = None
    journal_entry_id: str | None = None
    reviewed_spread_ids: list[str] = Field(default_factory=list)
    reason: str | None = None


class PreOpenProxySignal(BaseModel):
    key: str
    label: str
    symbol: str
    session_price: Decimal
    reference_price: Decimal
    change_pct: Decimal
    signal: str
    note: str | None = None


class PreOpenCheckpoint(BaseModel):
    label: str
    timing_label: str
    status: str
    detail: str


class DirectionalPutSnapshot(BaseModel):
    underlying_symbol: str
    expiration_date: date
    days_to_expiration: int
    strike: Decimal
    put_symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid_price: Decimal | None = None
    spread_width: Decimal | None = None
    spread_pct: Decimal | None = None
    distance_from_spot_pct: Decimal | None = None
    delta: Decimal | None = None
    implied_volatility: Decimal | None = None
    liquidity_label: str | None = None


class OptionChainLiquidStrike(BaseModel):
    strike: Decimal
    put_symbol: str
    open_interest: int | None = None
    volume: int | None = None
    delta: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid_price: Decimal | None = None
    spread_width: Decimal | None = None
    spread_pct: Decimal | None = None
    liquidity_label: str | None = None


class OptionChainExpiryAnalysis(BaseModel):
    expiration_date: date
    days_to_expiration: int
    atm_strike: Decimal
    atm_put_symbol: str
    atm_implied_volatility: Decimal | None = None
    atm_delta: Decimal | None = None
    atm_mid_price: Decimal | None = None
    put_skew_strike: Decimal | None = None
    put_skew_put_symbol: str | None = None
    put_skew_implied_volatility: Decimal | None = None
    put_skew_delta: Decimal | None = None
    put_skew_diff: Decimal | None = None
    median_spread_pct: Decimal | None = None
    tight_count: int = 0
    workable_count: int = 0
    wide_count: int = 0
    liquid_strikes: list[OptionChainLiquidStrike] = Field(default_factory=list)


class OptionChainAnalysis(BaseModel):
    underlying_symbol: str
    underlying_price: Decimal
    analyzed_at: datetime
    front_expiration: OptionChainExpiryAnalysis | None = None
    next_expiration: OptionChainExpiryAnalysis | None = None
    atm_iv_term_diff: Decimal | None = None
    term_structure_label: str | None = None
    sample_note: str | None = None


class PreOpenDownsideAssessment(BaseModel):
    analyzed_at: datetime
    session: str
    market_open: bool
    target_session_date: date
    minutes_to_regular_open: int | None = None
    next_regular_open_at: datetime | None = None
    downside_score: int
    regime: str
    plain_put_view: str
    preferred_vehicle: str | None = None
    trade_action: str
    trade_action_detail: str
    gap_chase_risk: str
    gap_chase_detail: str
    summary: str
    reasons: list[str] = Field(default_factory=list)
    checkpoints: list[PreOpenCheckpoint] = Field(default_factory=list)
    signals: list[PreOpenProxySignal] = Field(default_factory=list)
    put_snapshots: list[DirectionalPutSnapshot] = Field(default_factory=list)
    chain_analyses: list[OptionChainAnalysis] = Field(default_factory=list)
    freshness_status: str = "live"
    freshness_detail: str | None = None
    stale_reason: str | None = None
    source_run_id: str | None = None


class PreOpenReviewCheckpoint(BaseModel):
    key: str
    label: str
    timing_label: str
    scheduled_at: datetime
    captured_at: datetime | None = None
    status: str = "pending"
    qqq_change_pct: Decimal | None = None
    spy_change_pct: Decimal | None = None
    semis_change_pct: Decimal | None = None
    qqq_vs_spy_diff: Decimal | None = None
    semis_vs_qqq_diff: Decimal | None = None
    confirmation: str | None = None
    detail: str | None = None


class PreOpenAssessmentRun(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    strategy_id: str = "pre_open_put_check_v1"
    external_account_id: str
    target_session_date: date
    assessment: PreOpenDownsideAssessment
    checkpoints: list[PreOpenReviewCheckpoint] = Field(default_factory=list)
    review_status: str = "pending"
    review_summary: str | None = None
    last_reviewed_at: datetime | None = None
    review_completed_at: datetime | None = None
    raw_payload: dict | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PreOpenAssessmentCaptureResult(BaseModel):
    run: PreOpenAssessmentRun
    captured: bool
    reason: str | None = None


class PreOpenAssessmentReviewResult(BaseModel):
    run: PreOpenAssessmentRun | None = None
    reviewed: bool = False
    updated_checkpoint_keys: list[str] = Field(default_factory=list)
    reason: str | None = None


class BrokerAccountSyncResult(BaseModel):
    broker: BrokerName
    mode: ExecutionMode
    external_account_id: str
    snapshot_id: str | None = None
    positions_synced: int
    account_snapshot: AccountSnapshot

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


class AccountSnapshot(BaseModel):
    broker: BrokerName
    account_id: str
    currency: str = "USD"
    cash_balance: Decimal
    net_liquidation: Decimal
    buying_power: Decimal
    day_trade_buying_power: Decimal | None = None
    options_level: str | None = None
    positions: list[PositionSnapshot] = Field(default_factory=list)
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


from enum import Enum


class AssetType(str, Enum):
    STOCK = "stock"
    ETF = "etf"
    OPTION = "option"


class BrokerName(str, Enum):
    LONGBRIDGE = "longbridge"


class ReconciliationStatus(str, Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    SUCCESS = "success"
    ERROR = "error"


class JournalEntryType(str, Enum):
    PLAN = "plan"
    REVIEW = "review"
    NOTE = "note"


class CatalystType(str, Enum):
    EARNINGS = "earnings"
    FILING = "filing"
    RATING = "rating"
    MACRO = "macro"
    NEWS = "news"
    TECHNICAL = "technical"


class ExecutionMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class MarketBias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class OptionRight(str, Enum):
    CALL = "call"
    PUT = "put"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(str, Enum):
    CREATED = "created"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    CLOSED = "closed"


class RiskStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"


class TradeStructure(str, Enum):
    STOCK = "stock"
    LONG_CALL = "long_call"
    LONG_PUT = "long_put"
    BULL_PUT_SPREAD = "bull_put_spread"


class SpreadStatus(str, Enum):
    ENTRY_PENDING_LONG = "entry_pending_long"
    ENTRY_PENDING_SHORT = "entry_pending_short"
    OPEN = "open"
    EXIT_PENDING_SHORT = "exit_pending_short"
    EXIT_PENDING_LONG = "exit_pending_long"
    CLOSED = "closed"
    ENTRY_FAILED = "entry_failed"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"

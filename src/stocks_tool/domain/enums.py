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

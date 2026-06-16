from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeIntegrationError,
)


class BrokerGatewayFailureKind(str, Enum):
    CONFIGURATION = "configuration_error"
    DEPENDENCY = "dependency_error"
    TIMEOUT = "transient_timeout"
    CIRCUIT_OPEN = "circuit_open"
    RATE_LIMIT = "rate_limit"
    STALE_QUOTE = "stale_quote"
    BROKER_REJECTION = "broker_rejection"
    TRANSIENT = "transient_error"
    UNKNOWN = "unknown_error"


@dataclass(frozen=True)
class BrokerGatewayFailure:
    kind: BrokerGatewayFailureKind
    message: str
    retryable: bool


def classify_broker_exception(exc: Exception) -> BrokerGatewayFailure:
    message = str(exc)
    normalized = message.lower()
    if isinstance(exc, LongbridgeConfigurationError):
        return BrokerGatewayFailure(BrokerGatewayFailureKind.CONFIGURATION, message, retryable=False)
    if isinstance(exc, LongbridgeDependencyError):
        return BrokerGatewayFailure(BrokerGatewayFailureKind.DEPENDENCY, message, retryable=False)
    if "circuit is open" in normalized:
        return BrokerGatewayFailure(BrokerGatewayFailureKind.CIRCUIT_OPEN, message, retryable=True)
    if "timed out" in normalized or "timeout" in normalized:
        return BrokerGatewayFailure(BrokerGatewayFailureKind.TIMEOUT, message, retryable=True)
    if "rate limit" in normalized or "too many requests" in normalized:
        return BrokerGatewayFailure(BrokerGatewayFailureKind.RATE_LIMIT, message, retryable=True)
    if "stale quote" in normalized or "quote is stale" in normalized:
        return BrokerGatewayFailure(BrokerGatewayFailureKind.STALE_QUOTE, message, retryable=True)
    if "reject" in normalized or "rejected" in normalized:
        return BrokerGatewayFailure(BrokerGatewayFailureKind.BROKER_REJECTION, message, retryable=False)
    if isinstance(exc, LongbridgeIntegrationError):
        return BrokerGatewayFailure(BrokerGatewayFailureKind.TRANSIENT, message, retryable=True)
    return BrokerGatewayFailure(BrokerGatewayFailureKind.UNKNOWN, message, retryable=False)

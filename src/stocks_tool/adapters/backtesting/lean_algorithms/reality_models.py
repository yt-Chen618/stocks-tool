"""Small, dependency-free reality checks shared by the LEAN algorithms.

LEAN's built-in ``ImmediateFillModel`` uses the bid/ask side of a QuoteBar,
but it assumes that a market order can be filled in full.  The strategy code
also needs a strict quote contract before it asks LEAN to fill a leg.  This
module keeps those checks independent from ``AlgorithmImports`` so they can be
tested on the host and reused by the container runtime.

The module deliberately does not manufacture a midpoint, fall back to the
algorithm clock for a quote timestamp, or treat an absent quote size as
unlimited liquidity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo


LEAN_MARKET_TIMEZONE = ZoneInfo("America/New_York")


class RealityModelError(ValueError):
    """A quote cannot support the requested simulated execution."""


class QuoteFreshnessError(RealityModelError):
    """A quote is missing, from the future, or outside its allowed age."""


def _value(item: Any, *names: str) -> Any:
    for name in names:
        if isinstance(item, dict):
            value = item.get(name)
        else:
            value = getattr(item, name, None)
        if value is not None:
            return value
    return None


def _decimal(value: Any, *, field: str) -> Decimal:
    if value is None or value == "":
        raise RealityModelError(f"quote {field} is missing")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise RealityModelError(f"quote {field} is not numeric") from exc


def _time(value: Any, *, field: str, naive_timezone=timezone.utc) -> datetime:
    if value is None or value == "":
        raise QuoteFreshnessError(f"quote {field} is missing")
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise QuoteFreshnessError(f"quote {field} is invalid") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=naive_timezone)


def observed_at(contract_or_quote: Any) -> datetime | None:
    """Return the source observation time without substituting ``now``.

    A missing/zero timestamp is represented as ``None``. Callers selecting
    contracts must supply the real QuoteBar end time after rejecting fill-forward
    data: LEAN's per-slice OptionContract.Time alone does not prove freshness.
    """

    raw = _value(contract_or_quote, "timestamp", "time", "Time", "end_time", "EndTime")
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime) and raw == datetime.min:
        return None
    try:
        # LEAN's BaseContract.Time is a naive exchange-local DateTime.  The
        # canonical payload is UTC-aware, so localize that source timestamp
        # before comparing it with the algorithm's UTC clock.
        return _time(raw, field="timestamp", naive_timezone=LEAN_MARKET_TIMEZONE).astimezone(timezone.utc)
    except QuoteFreshnessError:
        return None


@dataclass(frozen=True)
class ExecutableQuote:
    """A top-of-book quote and its displayed executable size."""

    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    timestamp: datetime

    @classmethod
    def from_contract(cls, contract_or_quote: Any) -> "ExecutableQuote":
        timestamp = observed_at(contract_or_quote)
        if timestamp is None:
            raise QuoteFreshnessError("quote timestamp is unavailable")
        bid = _decimal(_value(contract_or_quote, "bid", "bid_price", "BidPrice"), field="bid")
        ask = _decimal(_value(contract_or_quote, "ask", "ask_price", "AskPrice"), field="ask")
        bid_size = _decimal(
            _value(contract_or_quote, "bid_size", "BidSize"),
            field="bid_size",
        )
        ask_size = _decimal(
            _value(contract_or_quote, "ask_size", "AskSize"),
            field="ask_size",
        )
        if bid <= 0 or ask <= 0 or ask < bid:
            raise RealityModelError("quote bid/ask must be positive and non-crossed")
        if bid_size <= 0 or ask_size <= 0:
            raise RealityModelError("quote bid/ask size must be positive")
        return cls(
            bid=bid,
            ask=ask,
            bid_size=bid_size,
            ask_size=ask_size,
            timestamp=timestamp,
        )

    def require_fresh(self, *, evaluated_at: datetime, max_age_seconds: int) -> None:
        reference = _time(evaluated_at, field="evaluated_at")
        if self.timestamp > reference:
            raise QuoteFreshnessError("quote timestamp is after the evaluation time")
        age = (reference - self.timestamp).total_seconds()
        if age > max_age_seconds:
            raise QuoteFreshnessError(
                f"quote is stale by {age:.3f}s; limit is {max_age_seconds}s"
            )
        if age < 0:
            raise QuoteFreshnessError("quote timestamp is after the evaluation time")

    def price_for(self, side: str) -> Decimal:
        normalized = str(side).strip().lower()
        if normalized == "buy":
            return self.ask
        if normalized == "sell":
            return self.bid
        raise RealityModelError(f"unsupported order side: {side}")

    def available_size_for(self, side: str) -> Decimal:
        normalized = str(side).strip().lower()
        if normalized == "buy":
            return self.ask_size
        if normalized == "sell":
            return self.bid_size
        raise RealityModelError(f"unsupported order side: {side}")

    def fill(self, side: str, requested_quantity: Decimal | int | str) -> tuple[Decimal, Decimal]:
        """Return ``(quantity, price)`` for one quote-backed fill attempt.

        The displayed side size caps the fill.  A caller that needs the rest
        must submit/keep the order open for a later quote; this method never
        pretends that the entire request traded at a midpoint.
        """

        requested = _decimal(requested_quantity, field="requested_quantity")
        if requested <= 0:
            raise RealityModelError("requested quantity must be positive")
        quantity = min(requested, self.available_size_for(side))
        return quantity, self.price_for(side)


def build_contract_quote_payload(contract: Any) -> dict[str, Any]:
    """Build a candidate payload using the contract's own observation time.

    This helper is intentionally separate from freshness enforcement: stale
    quotes can remain visible as rejected candidates with an honest timestamp,
    while the order path calls :meth:`ExecutableQuote.require_fresh` before a
    fill.
    """

    timestamp = observed_at(contract)
    return {
        "timestamp": timestamp,
        "bid": _value(contract, "bid", "bid_price", "BidPrice"),
        "ask": _value(contract, "ask", "ask_price", "AskPrice"),
        "bid_size": _value(contract, "bid_size", "BidSize"),
        "ask_size": _value(contract, "ask_size", "AskSize"),
    }


__all__ = [
    "ExecutableQuote",
    "QuoteFreshnessError",
    "RealityModelError",
    "build_contract_quote_payload",
    "observed_at",
]

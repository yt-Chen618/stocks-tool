"""Backtest event adapters for the same rules used by paper previews.

This module translates the stable fixture/event shape into pure domain
selections. It never invents strikes from spot. A fixture may either provide
the complete option chain (the preferred path) or provide an explicit,
already-selected candidate from a captured preview; the latter is kept for
backward-compatible fixture tests and is still validated for point-in-time
ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from stocks_tool.domain.backtesting import BacktestStrategy
from stocks_tool.domain.strategies.bull_put import (
    BullPutRules,
    bull_put_cap_reasons,
    select_bull_put_candidate,
)
from stocks_tool.domain.strategies.common import decimal, parse_datetime, value
from stocks_tool.domain.strategies.covered_call import CoveredCallRules, select_covered_call_candidate
from stocks_tool.domain.strategies.zero_dte import ZeroDteRules, select_zero_dte_candidate


class FutureInformationError(ValueError):
    """Raised when a fixture uses an event before it was available."""


@dataclass(frozen=True)
class StrategyIntent:
    timestamp: datetime
    strategy: BacktestStrategy
    symbol: str
    action: str
    legs: tuple[dict[str, Any], ...]
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


def assert_point_in_time(event: dict[str, Any], as_of: datetime) -> None:
    for key in ("available_at", "as_of"):
        raw = event.get(key)
        if raw is None:
            continue
        available = _parse_datetime(raw)
        if available > as_of:
            raise FutureInformationError(
                f"event {key} at {available.isoformat()} is after event timestamp {as_of.isoformat()}"
            )


def bull_put_intents(events: Iterable[dict[str, Any]]) -> list[StrategyIntent]:
    intents: list[StrategyIntent] = []
    for event in events:
        timestamp = _event_timestamp(event)
        assert_point_in_time(event, timestamp)
        if not _signal_allowed(event, {"bull_put", "open", "bull_put_open"}):
            continue
        symbol = _symbol(event)
        underlying_price = decimal(event.get("underlying_price"))
        if not symbol or underlying_price is None or underlying_price <= 0:
            continue
        quotes = _event_quotes(event)
        rules = _bull_put_rules(_parameters(event, "bull_put"))
        if quotes:
            selection = select_bull_put_candidate(
                symbol=symbol,
                underlying_price=underlying_price,
                expiration_dates=event.get("expiration_dates") or event.get("expirations"),
                quotes=quotes,
                evaluated_at=timestamp,
                rules=rules,
                bars=event.get("bars") or event.get("underlying_bars") or (),
                underlying={
                    "last_done": underlying_price,
                    "prev_close": event.get("prev_close", underlying_price),
                    "open": event.get("open", underlying_price),
                },
            )
            if selection is None:
                continue
            if bull_put_cap_reasons(
                event=event,
                width=selection.width,
                credit=selection.conservative_credit,
                rules=rules,
            ):
                continue
            intents.append(_bull_put_intent_from_selection(timestamp, selection, rules))
            continue

        # Explicit candidate fixtures represent a candidate selected by the
        # online preview. Do not infer a strike, expiration, or width when a
        # field is missing; older tests use this compact representation.
        if event.get("short_put_strike") is None or event.get("long_put_strike") is None:
            continue
        expiration = event.get("expiration")
        if expiration is None:
            continue
        short_strike = decimal(event.get("short_put_strike"))
        long_strike = decimal(event.get("long_put_strike"))
        if short_strike is None or long_strike is None or long_strike >= short_strike:
            continue
        quantity = max(1, _int(event.get("contracts"), rules.contracts_per_trade))
        intents.append(
            StrategyIntent(
                timestamp=timestamp,
                strategy=BacktestStrategy.BULL_PUT,
                symbol=symbol,
                action="open",
                legs=(
                    {"side": "sell", "right": "put", "symbol": event.get("short_put_symbol"), "strike": str(short_strike), "expiration": str(expiration), "quantity": quantity},
                    {"side": "buy", "right": "put", "symbol": event.get("long_put_symbol"), "strike": str(long_strike), "expiration": str(expiration), "quantity": quantity},
                ),
                reason="explicit point-in-time bull put candidate",
                metadata={"selection_source": "explicit_candidate", "width": str(short_strike - long_strike)},
            )
        )
    return intents


def covered_call_intents(events: Iterable[dict[str, Any]]) -> list[StrategyIntent]:
    intents: list[StrategyIntent] = []
    for event in events:
        timestamp = _event_timestamp(event)
        assert_point_in_time(event, timestamp)
        if not _signal_allowed(event, {"covered_call", "open", "covered_call_open"}):
            continue
        symbol = _symbol(event)
        shares = _int(event.get("shares"), 0)
        spot = decimal(event.get("underlying_price"))
        if not symbol or shares < 100 or spot is None or spot <= 0:
            continue
        quotes = _event_quotes(event)
        rules = _covered_call_rules(_parameters(event, "covered_call"))
        if quotes:
            selection = select_covered_call_candidate(
                symbol=symbol,
                underlying_price=spot,
                shares=shares,
                expiration_dates=event.get("expiration_dates") or event.get("expirations"),
                quotes=quotes,
                evaluated_at=timestamp,
                rules=rules,
            )
            if selection is None:
                continue
            quote = selection.quote
            intents.append(
                StrategyIntent(
                    timestamp=timestamp,
                    strategy=BacktestStrategy.COVERED_CALL,
                    symbol=symbol,
                    action="open",
                    legs=({
                        "side": "sell",
                        "right": "call",
                        "symbol": value(quote, "symbol"),
                        "strike": str(value(quote, "strike")),
                        "expiration": selection.expiration.isoformat(),
                        "quantity": selection.contracts,
                    },),
                    reason="point-in-time covered shares and call filters",
                    metadata={"selection_source": "shared_candidate_rules", "covered_shares": selection.covered_shares},
                )
            )
            continue

        strike = decimal(event.get("call_strike"))
        expiration = event.get("expiration")
        if strike is None or expiration is None:
            continue
        quantity = max(1, min(shares // 100, rules.max_contracts_per_symbol))
        intents.append(
            StrategyIntent(
                timestamp=timestamp,
                strategy=BacktestStrategy.COVERED_CALL,
                symbol=symbol,
                action="open",
                legs=({
                    "side": "sell", "right": "call", "strike": str(strike),
                    "expiration": str(expiration), "quantity": quantity,
                },),
                reason="explicit point-in-time covered shares and call candidate",
                metadata={"selection_source": "explicit_candidate"},
            )
        )
    return intents


def zero_dte_intents(events: Iterable[dict[str, Any]]) -> list[StrategyIntent]:
    """Return research signals and candidate lifecycle inputs only.

    The application still refuses Zero-DTE execution. A research intent may
    be settled by the fixture simulator so DNE, exercise, assignment, and
    resulting stock consequences are visible without touching the ledger.
    """

    intents: list[StrategyIntent] = []
    for event in events:
        timestamp = _event_timestamp(event)
        assert_point_in_time(event, timestamp)
        if not _signal_allowed(event, {"zero_dte", "research", "zero_dte_call", "zero_dte_put"}):
            continue
        symbol = _symbol(event)
        if not symbol:
            continue
        legs = event.get("legs")
        if not _event_quotes(event) and legs:
            expiration = event.get("expiration")
            if expiration is None or str(expiration) != _market_date(timestamp):
                continue
            intents.append(
                StrategyIntent(
                    timestamp=timestamp,
                    strategy=BacktestStrategy.ZERO_DTE,
                    symbol=symbol,
                    action="research_signal",
                    legs=tuple(dict(item) for item in legs),
                    reason="zero-DTE research-only signal; no broker lifecycle",
                    metadata={"selection_source": "explicit_candidate"},
                )
            )
            continue
        direction = _zero_dte_direction(event)
        spot = decimal(event.get("underlying_price"))
        if direction is None or spot is None or spot <= 0:
            continue
        selection = select_zero_dte_candidate(
            symbol=symbol,
            direction=direction,
            underlying_price=spot,
            evaluated_at=timestamp,
            quotes=_event_quotes(event),
            rules=_zero_dte_rules(_parameters(event, "zero_dte")),
        )
        if selection is None:
            continue
        quote = selection.quote
        intents.append(
            StrategyIntent(
                timestamp=timestamp,
                strategy=BacktestStrategy.ZERO_DTE,
                symbol=symbol,
                action="research_signal",
                legs=({
                    "side": "buy", "right": direction, "symbol": value(quote, "symbol"),
                    "strike": str(value(quote, "strike")), "expiration": selection.expiration.isoformat(),
                    "quantity": selection.contracts,
                },),
                reason="zero-DTE research-only candidate passed configured gates",
                metadata={"selection_source": "shared_candidate_rules", "premium_at_ask": str(selection.premium_at_ask)},
            )
        )
    return intents


def _bull_put_intent_from_selection(timestamp: datetime, selection: Any, rules: BullPutRules) -> StrategyIntent:
    short = selection.short_put
    long = selection.long_put
    quantity = rules.contracts_per_trade
    return StrategyIntent(
        timestamp=timestamp,
        strategy=BacktestStrategy.BULL_PUT,
        symbol=selection.symbol,
        action="open",
        legs=(
            {"side": "sell", "right": "put", "symbol": value(short, "symbol"), "strike": str(value(short, "strike")), "expiration": selection.expiration.isoformat(), "quantity": quantity},
            {"side": "buy", "right": "put", "symbol": value(long, "symbol"), "strike": str(value(long, "strike")), "expiration": selection.expiration.isoformat(), "quantity": quantity},
        ),
        reason="point-in-time bull put candidate passed shared trend, DTE, delta, liquidity, width, credit, and capacity rules",
        metadata={
            "selection_source": "shared_candidate_rules",
            "width": str(selection.width),
            "mid_credit": str(selection.mid_credit),
            "conservative_credit": str(selection.conservative_credit),
        },
    )


def _event_quotes(event: dict[str, Any]) -> list[Any]:
    raw = event.get("option_quotes") or event.get("quotes") or ()
    return list(raw) if isinstance(raw, (list, tuple)) else []


def _parameters(event: dict[str, Any], name: str) -> dict[str, Any]:
    raw = event.get("strategy_config") or event.get("parameters") or {}
    if not isinstance(raw, dict):
        return {}
    nested = raw.get(name)
    return nested if isinstance(nested, dict) else raw


def _dataclass_values(parameters: dict[str, Any], cls: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, field in cls.__dataclass_fields__.items():
        if name not in parameters:
            continue
        raw = parameters[name]
        if name.endswith(("_pct", "_ratio")) or "delta" in name or "credit" in name or "bid" in name or "premium" in name:
            parsed = decimal(raw)
            if parsed is not None:
                result[name] = parsed
        elif isinstance(raw, bool):
            result[name] = raw
        else:
            try:
                result[name] = int(raw)
            except (TypeError, ValueError):
                result[name] = raw
    return result


def _bull_put_rules(parameters: dict[str, Any]) -> BullPutRules:
    return BullPutRules(**_dataclass_values(parameters, BullPutRules))


def _covered_call_rules(parameters: dict[str, Any]) -> CoveredCallRules:
    return CoveredCallRules(**_dataclass_values(parameters, CoveredCallRules))


def _zero_dte_rules(parameters: dict[str, Any]) -> ZeroDteRules:
    return ZeroDteRules(**_dataclass_values(parameters, ZeroDteRules))


def _zero_dte_direction(event: dict[str, Any]) -> str | None:
    raw = event.get("direction") or event.get("right")
    if raw:
        normalized = str(getattr(raw, "value", raw)).lower()
        if normalized in {"call", "put"}:
            return normalized
    signal = str(event.get("signal") or "").lower()
    if "call" in signal:
        return "call"
    if "put" in signal:
        return "put"
    change = decimal(event.get("underlying_change_pct"))
    threshold = decimal(_parameters(event, "zero_dte").get("min_direction_change_pct"), None)
    threshold = threshold if threshold is not None else Decimal("0.30")
    if change is not None:
        if change >= threshold:
            return "call"
        if change <= -threshold:
            return "put"
    return None


def _signal_allowed(event: dict[str, Any], accepted: set[str]) -> bool:
    signal = event.get("signal")
    return signal is None or str(getattr(signal, "value", signal)).lower() in accepted


def _event_timestamp(event: dict[str, Any]) -> datetime:
    if "timestamp" not in event:
        raise ValueError("strategy event requires timestamp")
    return _parse_datetime(event["timestamp"])


def _parse_datetime(value_: Any) -> datetime:
    return parse_datetime(value_)


def _symbol(event: dict[str, Any]) -> str:
    return str(event.get("symbol") or event.get("underlying_symbol") or "").strip().upper()


def _int(value_: Any, default: int) -> int:
    try:
        return int(value_)
    except (TypeError, ValueError):
        return default


def _market_date(timestamp: datetime) -> str:
    from stocks_tool.domain.strategies.common import market_date

    return market_date(timestamp).isoformat()

"""Deterministic broker-free fixture simulator.

This is a software-validation adapter, not a replacement for LEAN's fill and
portfolio accounting.  It consumes the same candidate intents as the online
preview, applies explicit fees/slippage and independent leg fills, and models
the option lifecycle transitions needed to verify the strategy contract.
Formal historical runs still execute through the pinned LEAN container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from stocks_tool.adapters.backtesting.rules import (
    FutureInformationError,
    StrategyIntent,
    bull_put_intents,
    covered_call_intents,
    zero_dte_intents,
)
from stocks_tool.domain.backtesting import (
    BacktestResult,
    BacktestStrategy,
    BacktestTrade,
    FeeModel,
    LifecycleModel,
    SlippageModel,
    result_semantic_payload,
    semantic_hash,
)
from stocks_tool.domain.strategies.common import decimal, parse_datetime
from stocks_tool.domain.strategies.lifecycle import dividend_cash, settle_option_position, apply_split
from stocks_tool.domain.strategies.bull_put import BullPutRules, bull_put_exit_reason
from stocks_tool.domain.strategies.common import days_to_expiration


class SimulationDataError(ValueError):
    pass


@dataclass
class _OpenPosition:
    intent: StrategyIntent
    filled_legs: list[dict[str, Any]]
    opened_at: datetime
    settled: bool = False
    do_not_exercise: bool = False
    entry_credit: Decimal | None = None


@dataclass
class _LifecycleState:
    cash: Decimal
    initial_stock_acquisition_cost: Decimal = Decimal("0")
    stock_positions: dict[str, Decimal] = field(default_factory=dict)
    open_positions: list[_OpenPosition] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seeded_symbols: set[str] = field(default_factory=set)
    option_mark_unavailable: set[str] = field(default_factory=set)


def simulate_events(
    *,
    run_id: str,
    strategy: BacktestStrategy,
    events: Iterable[dict[str, Any]],
    initial_cash: Decimal,
    fee_model: FeeModel,
    slippage_model: SlippageModel,
    lifecycle_model: LifecycleModel,
    initial_stock_lots: Iterable[dict[str, Any]] | None = None,
) -> BacktestResult:
    if fee_model is None:
        raise SimulationDataError("formal simulations require an explicit fee model")
    if initial_cash <= 0:
        raise SimulationDataError("initial_cash must be positive")
    ordered = sorted((dict(event) for event in events), key=lambda event: _parse_time(event["timestamp"]))
    if strategy is BacktestStrategy.BULL_PUT:
        intents = bull_put_intents(ordered)
    elif strategy is BacktestStrategy.COVERED_CALL:
        intents = covered_call_intents(ordered)
    elif strategy is BacktestStrategy.ZERO_DTE:
        intents = zero_dte_intents(ordered)
    else:
        raise SimulationDataError(f"unsupported strategy {strategy!r}")

    intents_by_timestamp: dict[datetime, list[StrategyIntent]] = {}
    for intent in intents:
        intents_by_timestamp.setdefault(intent.timestamp, []).append(intent)

    state = _LifecycleState(cash=initial_cash)
    _seed_initial_stock_lots(state, initial_stock_lots or ())
    trades: list[BacktestTrade] = []
    curve: list[dict[str, Any]] = []
    fees_total = Decimal("0")
    slippage_total = Decimal("0")
    current_equity = initial_cash

    for event in ordered:
        timestamp = _parse_time(event["timestamp"])
        _assert_no_future_event(event, timestamp)
        _seed_stock_positions(state, event, strategy=strategy)
        event_warnings: list[str] = []
        for index, intent in enumerate(intents_by_timestamp.get(timestamp, ())):
            if _has_active_position(state, intent):
                state.warnings.append(f"duplicate_open_blocked:{intent.strategy.value}:{intent.symbol}")
                continue
            trade = _fill_intent(
                intent,
                event,
                fee_model,
                slippage_model,
                lifecycle_model,
                trade_index=len(trades) + index,
            )
            trades.append(trade)
            state.cash += trade.net_pnl
            fees_total += trade.fees
            slippage_total += trade.slippage
            filled = [leg for leg in trade.legs if leg.get("status") == "filled" and Decimal(str(leg.get("quantity", "0"))) > 0]
            if filled:
                state.open_positions.append(
                    _OpenPosition(
                        intent=intent,
                        filled_legs=filled,
                        opened_at=timestamp,
                        entry_credit=decimal(event.get("entry_net_credit")) or decimal(intent.metadata.get("conservative_credit")),
                    )
                )

        for raw_action in event.get("lifecycle_events", ()) or ():
            action = dict(raw_action) if isinstance(raw_action, dict) else {"type": str(raw_action)}
            action_time = _parse_time(action.get("timestamp", timestamp))
            if action_time > timestamp:
                raise FutureInformationError("lifecycle event timestamp is after its containing market event")
            assert_available_at(action, action_time)
            event_warnings.extend(
                _apply_lifecycle_action(
                    state=state,
                    strategy=strategy,
                    action=action,
                    event=event,
                    action_time=action_time,
                    lifecycle_model=lifecycle_model,
                )
            )
        auto_exit = _bull_put_auto_exit_action(state, event)
        if auto_exit is not None:
            event_warnings.extend(
                _apply_lifecycle_action(
                    state=state,
                    strategy=strategy,
                    action=auto_exit,
                    event=event,
                    action_time=timestamp,
                    lifecycle_model=lifecycle_model,
                )
            )
        option_value, mark_warnings, marks_complete = _mark_option_positions(state, event, lifecycle_model)
        event_warnings.extend(mark_warnings)
        if event_warnings:
            state.warnings.extend(event_warnings)
        current_equity = state.cash + _stock_market_value(state.stock_positions, event) + option_value
        curve.append({"timestamp": timestamp.isoformat(), "equity": str(current_equity), "quality": "complete" if marks_complete else "unavailable"})

    # An open position with no terminal event is intentionally retained and is
    # visible in the output warnings rather than silently treated as expired.
    for position in state.open_positions:
        if not position.settled:
            state.warnings.append(f"unsettled_position:{position.intent.symbol}")

    peak = initial_cash
    max_drawdown = Decimal("0")
    for point in curve:
        value_ = Decimal(point["equity"])
        if value_ > peak:
            peak = value_
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value_) / peak)
    marks_complete = not any(point.get("quality") == "unavailable" for point in curve)
    net_pnl = current_equity - initial_cash
    metrics = {
        "initial_cash": str(initial_cash),
        "initial_stock_acquisition_cost": str(state.initial_stock_acquisition_cost),
        "ending_equity": str(current_equity) if marks_complete else None,
        "net_pnl": str(net_pnl) if marks_complete else None,
        "total_return_pct": str(_pct(net_pnl, initial_cash)) if marks_complete else None,
        "max_drawdown_pct": str((max_drawdown * Decimal("100")).quantize(Decimal("0.000001"))) if marks_complete else None,
        "trade_count": len(trades),
        "fees": str(fees_total),
        "slippage": str(slippage_total),
        "lifecycle_warnings": len(set(state.warnings)),
        "lifecycle_transition_count": len(state.transitions),
        "stock_positions": {symbol: str(quantity) for symbol, quantity in sorted(state.stock_positions.items()) if quantity},
        "equity_mark_quality": "complete" if marks_complete else "unavailable_open_option_marks",
        "unrealized_option_liability": str(_unrealized_option_liability(state, ordered[-1] if ordered else {}, lifecycle_model)),
    }
    warnings = sorted(set(state.warnings))
    payload = {
        "metrics": metrics,
        "trades": [trade.model_dump(mode="json") for trade in trades],
        "equity_curve": curve,
        "warnings": warnings,
    }
    return BacktestResult(
        run_id=run_id,
        semantic_hash=semantic_hash(result_semantic_payload(payload)),
        metrics=metrics,
        trades=trades,
        equity_curve=curve,
        warnings=warnings,
        raw_payload={"lifecycle_transitions": state.transitions, "stock_positions": metrics["stock_positions"]},
    )


def _fill_intent(
    intent: StrategyIntent,
    event: dict[str, Any],
    fee_model: FeeModel,
    slippage_model: SlippageModel,
    lifecycle_model: LifecycleModel,
    *,
    trade_index: int,
) -> BacktestTrade:
    fills = event.get("fills") or {}
    filled_legs: list[dict[str, Any]] = []
    warnings: list[str] = []
    gross = Decimal("0")
    fees = Decimal("0")
    slippage = Decimal("0")
    for index, leg in enumerate(intent.legs):
        leg_name = str(leg.get("symbol") or f"leg-{index}")
        fill = fills.get(leg_name) or fills.get(str(index))
        required = decimal(leg.get("quantity"), Decimal("1")) or Decimal("1")
        if fill is None:
            warnings.append(f"partial_leg_unfilled:{leg_name}")
            filled_legs.append({**leg, "status": "unfilled", "quantity": "0"})
            continue
        quantity = decimal(fill.get("quantity", required), required) or Decimal("0")
        price = decimal(fill.get("price"), Decimal("0")) or Decimal("0")
        if quantity <= 0 or price < 0:
            raise SimulationDataError("fill quantity must be positive and price non-negative")
        if quantity > required:
            raise SimulationDataError(f"fill quantity exceeds requested leg quantity for {leg_name}")
        side = str(leg.get("side", "buy")).lower()
        sign = Decimal("1") if side == "sell" else Decimal("-1")
        multiplier = decimal(fill.get("contract_multiplier"), Decimal(str(lifecycle_model.contract_multiplier))) or Decimal("1")
        notional = price * quantity * multiplier
        gross += sign * notional
        leg_fee = fee_model.commission_per_contract * quantity + fee_model.exchange_fee_per_contract * quantity
        if leg_fee < fee_model.minimum_commission and quantity > 0:
            leg_fee = fee_model.minimum_commission
        fees += leg_fee + notional * fee_model.commission_rate
        leg_slippage = notional * slippage_model.basis_points / Decimal("10000")
        leg_slippage += slippage_model.fixed_per_contract * quantity
        slippage += leg_slippage
        status = "filled" if quantity == required else "partial"
        if status == "partial":
            warnings.append(f"partial_leg_fill:{leg_name}")
        filled_legs.append({**leg, "status": status, "quantity": str(quantity), "price": str(price)})
    if len(filled_legs) > 1 and any(leg["status"] != "filled" for leg in filled_legs):
        warnings.append("two_leg_execution_is_partial")
    net = gross - fees - slippage
    status = "research_only" if intent.action == "research_signal" else (
        "partial" if any(leg["status"] != "filled" for leg in filled_legs) else "filled"
    )
    return BacktestTrade(
        id=f"trade-{trade_index:06d}-{intent.timestamp.strftime('%Y%m%dT%H%M%S')}",
        timestamp=intent.timestamp,
        strategy=intent.strategy,
        symbol=intent.symbol,
        status=status,
        legs=filled_legs,
        gross_pnl=gross,
        fees=fees,
        slippage=slippage,
        net_pnl=net,
        warnings=warnings,
    )


def _bull_put_auto_exit_action(state: _LifecycleState, event: dict[str, Any]) -> dict[str, Any] | None:
    if not state.open_positions or not event.get("underlying_price"):
        return None
    for position in state.open_positions:
        if position.settled or position.intent.strategy is not BacktestStrategy.BULL_PUT:
            continue
        short = next((leg for leg in position.filled_legs if str(leg.get("side", "")).lower() == "sell" and str(leg.get("right", "")).lower() == "put"), None)
        long = next((leg for leg in position.filled_legs if str(leg.get("side", "")).lower() == "buy" and str(leg.get("right", "")).lower() == "put"), None)
        if short is None or long is None:
            continue
        expiration = short.get("expiration")
        if expiration is None:
            continue
        evaluated_at = _parse_time(event["timestamp"])
        dte = days_to_expiration(expiration, evaluated_at)
        exit_debit = _option_exit_debit(event, short, long)
        entry_credit = position.entry_credit or decimal(event.get("entry_net_credit"))
        rules_payload = event.get("strategy_config") or event.get("parameters") or {}
        if isinstance(rules_payload, dict) and isinstance(rules_payload.get("bull_put"), dict):
            rules_payload = rules_payload["bull_put"]
        rules_payload = rules_payload if isinstance(rules_payload, dict) else {}
        rules = BullPutRules(
            close_days_to_expiration=int(rules_payload.get("close_days_to_expiration", 7)),
            stop_loss_exit_multiple=decimal(rules_payload.get("stop_loss_exit_multiple"), Decimal("2.00")) or Decimal("2.00"),
            take_profit_exit_ratio=decimal(rules_payload.get("take_profit_exit_ratio"), Decimal("0.50")) or Decimal("0.50"),
            require_trend=False,
        )
        reason = bull_put_exit_reason(
            underlying_price=decimal(event.get("underlying_price"), Decimal("0")) or Decimal("0"),
            short_strike=decimal(short.get("strike"), Decimal("0")) or Decimal("0"),
            estimated_exit_debit=exit_debit,
            entry_credit=entry_credit,
            days_to_expiration=dte,
            rules=rules,
        )
        if reason is None:
            continue
        cash_delta = Decimal("0")
        if exit_debit is not None:
            quantity = decimal(short.get("quantity"), Decimal("0")) or Decimal("0")
            cash_delta = -exit_debit * quantity * Decimal("100")
        return {
            "type": "close",
            "symbol": position.intent.symbol,
            "reason": reason,
            "cash_delta": str(cash_delta),
            "order_sequence": ["short_exit_buy", "long_exit_sell"],
        }
    return None


def _option_exit_debit(event: dict[str, Any], short: dict[str, Any], long: dict[str, Any]) -> Decimal | None:
    marks = event.get("option_marks") if isinstance(event.get("option_marks"), dict) else {}
    quotes = event.get("option_quotes", ()) or event.get("quotes", ()) or ()
    for quote in quotes:
        if isinstance(quote, dict) and quote.get("symbol"):
            marks.setdefault(str(quote["symbol"]), quote)
    short_mark = _quote_mark(marks.get(str(short.get("symbol") or "")), side="sell")
    long_mark = _quote_mark(marks.get(str(long.get("symbol") or "")), side="buy")
    if short_mark is None or long_mark is None:
        return None
    return short_mark - long_mark


def _quote_mark(value: Any, *, side: str) -> Decimal | None:
    if isinstance(value, dict):
        mark = decimal(value.get("ask" if side == "sell" else "bid"))
        if mark is not None:
            return mark
        bid = decimal(value.get("bid"))
        ask = decimal(value.get("ask"))
        return (bid + ask) / Decimal("2") if bid is not None and ask is not None else None
    return decimal(value)


def _apply_lifecycle_action(
    *,
    state: _LifecycleState,
    strategy: BacktestStrategy,
    action: dict[str, Any],
    event: dict[str, Any],
    action_time: datetime,
    lifecycle_model: LifecycleModel,
) -> list[str]:
    action_type = str(action.get("type") or action.get("event") or "").lower().replace("-", "_")
    warnings: list[str] = []
    if action_type in {"dne", "do_not_exercise", "do_not_exercise_instruction"}:
        symbol = str(action.get("symbol") or event.get("symbol") or "").upper()
        for position in state.open_positions:
            if position.intent.symbol.upper() == symbol and not position.settled:
                position.do_not_exercise = True
        state.transitions.append({"timestamp": action_time.isoformat(), "type": "dne", "symbol": symbol})
        return warnings
    if action_type in {"cutoff", "market_cutoff", "zero_dte_cutoff"}:
        state.transitions.append({"timestamp": action_time.isoformat(), "type": "cutoff", "symbol": str(event.get("symbol") or "").upper()})
        warnings.append("zero_dte_cutoff_reached")
        return warnings
    if action_type in {"close", "close_position", "roll", "roll_position"}:
        symbol = str(action.get("symbol") or event.get("symbol") or "").upper()
        cash_delta = decimal(action.get("cash_delta"), Decimal("0")) or Decimal("0")
        state.cash += cash_delta
        closed = 0
        for position in state.open_positions:
            if position.settled or position.intent.symbol.upper() != symbol:
                continue
            position.settled = True
            closed += 1
        state.transitions.append(
            {
                "timestamp": action_time.isoformat(),
                "type": action_type,
                "symbol": symbol,
                "closed_positions": closed,
                "cash_delta": str(cash_delta),
                "reason": action.get("reason"),
                "order_sequence": action.get("order_sequence", ["short_exit_buy", "long_exit_sell"]),
            }
        )
        if action_type in {"roll", "roll_position"}:
            warnings.append("roll_requires_new_candidate_and_explicit_entry_fills")
        if closed == 0:
            warnings.append(f"close_without_open_position:{symbol}")
        return warnings
    if action_type in {"split", "stock_split"}:
        if not lifecycle_model.corporate_actions_enabled:
            warnings.append("corporate_action_disabled_lifecycle_model")
            return warnings
        symbol = str(action.get("symbol") or event.get("symbol") or "").upper()
        ratio = decimal(action.get("ratio"), Decimal("1")) or Decimal("1")
        if ratio <= 0:
            raise SimulationDataError("split ratio must be positive")
        state.stock_positions[symbol] = apply_split(state.stock_positions.get(symbol, Decimal("0")), ratio)
        state.transitions.append({"timestamp": action_time.isoformat(), "type": "split", "symbol": symbol, "ratio": str(ratio)})
        warnings.append("option_contract_adjustment_requires_engine_model")
        return warnings
    if action_type in {"dividend", "cash_dividend"}:
        if not lifecycle_model.corporate_actions_enabled:
            warnings.append("corporate_action_disabled_lifecycle_model")
            return warnings
        symbol = str(action.get("symbol") or event.get("symbol") or "").upper()
        amount = decimal(action.get("amount"), Decimal("0")) or Decimal("0")
        shares = state.stock_positions.get(symbol, Decimal("0"))
        state.cash += dividend_cash(shares, amount)
        state.transitions.append({"timestamp": action_time.isoformat(), "type": "dividend", "symbol": symbol, "amount": str(amount), "shares": str(shares)})
        return warnings
    if action_type in {"expiry", "expiration", "expire", "exercise", "assignment"}:
        if action_type in {"expiry", "expiration", "expire"} and not lifecycle_model.expiry_enabled:
            warnings.append("expiry_disabled_in_lifecycle_model")
            return warnings
        symbol = str(action.get("symbol") or event.get("symbol") or "").upper()
        underlying = decimal(action.get("underlying_price"), decimal(event.get("underlying_price")))
        if underlying is None:
            warnings.append("lifecycle_underlying_price_missing")
            return warnings
        for position in state.open_positions:
            if position.settled or position.intent.symbol.upper() != symbol:
                continue
            transition, cash_delta, stock_delta = _settle_position(
                position,
                strategy=strategy,
                action_type=action_type,
                underlying=underlying,
                lifecycle_model=lifecycle_model,
            )
            if transition is None:
                continue
            state.cash += cash_delta
            state.stock_positions[symbol] = state.stock_positions.get(symbol, Decimal("0")) + stock_delta
            position.settled = True
            state.transitions.append({"timestamp": action_time.isoformat(), **transition})
            warnings.extend(transition.get("warnings", ()))
        return warnings
    if action_type:
        warnings.append(f"unknown_lifecycle_event:{action_type}")
    return warnings


def _settle_position(
    position: _OpenPosition,
    *,
    strategy: BacktestStrategy,
    action_type: str,
    underlying: Decimal,
    lifecycle_model: LifecycleModel,
) -> tuple[dict[str, Any] | None, Decimal, Decimal]:
    settlement = settle_option_position(
        position.filled_legs,
        strategy=position.intent.strategy.value,
        underlying=underlying,
        do_not_exercise=position.do_not_exercise,
        exercise_enabled=lifecycle_model.exercise_enabled,
        assignment_enabled=lifecycle_model.assignment_enabled,
        contract_multiplier=lifecycle_model.contract_multiplier,
    )
    return (
        settlement.as_payload(
            strategy=position.intent.strategy.value,
            symbol=position.intent.symbol,
            action=action_type,
            underlying=underlying,
        ),
        settlement.cash_delta,
        settlement.stock_delta,
    )


def assert_available_at(action: dict[str, Any], action_time: datetime) -> None:
    available = action.get("available_at") or action.get("as_of")
    if available is not None and _parse_time(available) > action_time:
        raise FutureInformationError("lifecycle event available_at is after event timestamp")


def _assert_no_future_event(event: dict[str, Any], timestamp: datetime) -> None:
    available = event.get("available_at") or event.get("as_of")
    if available is not None and _parse_time(available) > timestamp:
        raise FutureInformationError("event availability is after event timestamp")


def _stock_market_value(positions: dict[str, Decimal], event: dict[str, Any]) -> Decimal:
    prices = event.get("underlying_prices")
    if isinstance(prices, dict):
        total = Decimal("0")
        for symbol, quantity in positions.items():
            price = decimal(prices.get(symbol))
            if price is not None:
                total += quantity * price
        return total
    symbol = str(event.get("symbol") or "").upper()
    price = decimal(event.get("underlying_price"))
    if not symbol or price is None:
        return Decimal("0")
    return positions.get(symbol, Decimal("0")) * price


def _has_active_position(state: _LifecycleState, intent: StrategyIntent) -> bool:
    return any(
        not position.settled
        and position.intent.strategy is intent.strategy
        and position.intent.symbol.upper() == intent.symbol.upper()
        for position in state.open_positions
    )


def _seed_initial_stock_lots(state: _LifecycleState, lots: Iterable[dict[str, Any]]) -> None:
    for raw_lot in lots:
        lot = raw_lot.model_dump(mode="json") if hasattr(raw_lot, "model_dump") else dict(raw_lot)
        symbol = str(lot.get("symbol") or "").strip().upper()
        quantity = decimal(lot.get("quantity"))
        price = decimal(lot.get("acquisition_price"))
        fee = decimal(lot.get("acquisition_fee"), Decimal("0")) or Decimal("0")
        if not symbol or quantity is None or quantity <= 0 or price is None or price <= 0:
            raise SimulationDataError("initial stock lots require positive symbol, quantity, and acquisition_price")
        state.cash -= quantity * price + fee
        state.initial_stock_acquisition_cost += quantity * price + fee
        state.stock_positions[symbol] = state.stock_positions.get(symbol, Decimal("0")) + quantity
        state.seeded_symbols.add(symbol)


def _mark_option_positions(
    state: _LifecycleState,
    event: dict[str, Any],
    lifecycle_model: LifecycleModel,
) -> tuple[Decimal, list[str], bool]:
    marks: dict[str, Any] = {}
    raw_marks = event.get("option_marks")
    if isinstance(raw_marks, dict):
        marks.update(raw_marks)
    for quote in event.get("option_quotes", ()) or event.get("quotes", ()) or ():
        if not isinstance(quote, dict):
            continue
        symbol = str(quote.get("symbol") or "")
        if symbol:
            marks[symbol] = quote
    total = Decimal("0")
    warnings: list[str] = []
    complete = True
    for position in state.open_positions:
        if position.settled:
            continue
        for leg in position.filled_legs:
            symbol = str(leg.get("symbol") or "")
            mark_item = marks.get(symbol)
            if mark_item is None:
                complete = False
                warning = f"option_mark_unavailable:{position.intent.symbol}"
                if warning not in state.option_mark_unavailable:
                    state.option_mark_unavailable.add(warning)
                    warnings.append(warning)
                continue
            if isinstance(mark_item, dict):
                side = str(leg.get("side", "buy")).lower()
                mark = decimal(mark_item.get("mark"))
                if mark is None:
                    mark = decimal(mark_item.get("bid" if side == "buy" else "ask"))
                if mark is None:
                    bid = decimal(mark_item.get("bid"))
                    ask = decimal(mark_item.get("ask"))
                    mark = (bid + ask) / Decimal("2") if bid is not None and ask is not None else None
            else:
                mark = decimal(mark_item)
            if mark is None or mark < 0:
                complete = False
                warning = f"option_mark_unavailable:{position.intent.symbol}"
                if warning not in state.option_mark_unavailable:
                    state.option_mark_unavailable.add(warning)
                    warnings.append(warning)
                continue
            quantity = decimal(leg.get("quantity"), Decimal("0")) or Decimal("0")
            multiplier = decimal(leg.get("contract_multiplier"), Decimal(str(lifecycle_model.contract_multiplier))) or Decimal("1")
            sign = Decimal("1") if str(leg.get("side", "buy")).lower() == "buy" else Decimal("-1")
            total += sign * mark * quantity * multiplier
    return total, warnings, complete


def _unrealized_option_liability(state: _LifecycleState, event: dict[str, Any], lifecycle_model: LifecycleModel) -> Decimal:
    value, _warnings, _complete = _mark_option_positions(state, event, lifecycle_model)
    return abs(value) if value < 0 else Decimal("0")


def _seed_stock_positions(state: _LifecycleState, event: dict[str, Any], *, strategy: BacktestStrategy) -> None:
    """Seed an explicitly supplied stock position once for lifecycle tests.

    The historical engine gets holdings from its portfolio model. Fixture
    events must state them explicitly; the simulator never assumes that a
    covered-call candidate owns shares merely because a call is present.
    """

    symbol = str(event.get("symbol") or event.get("underlying_symbol") or "").strip().upper()
    if not symbol or symbol in state.seeded_symbols:
        return
    lots = event.get("initial_stock_lots")
    if lots:
        _seed_initial_stock_lots(state, lots)
    elif event.get("initial_stock_positions") or event.get("stock_positions"):
        state.warnings.append(f"initial_stock_cost_missing:{symbol}")
    state.seeded_symbols.add(symbol)


def _parse_time(value_: Any) -> datetime:
    return parse_datetime(value_)


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (numerator / denominator * Decimal("100")).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

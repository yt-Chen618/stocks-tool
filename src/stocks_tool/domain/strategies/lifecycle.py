"""Pure option lifecycle transitions for research fixtures.

LEAN remains the authority for formal historical fills and portfolio
accounting. These functions give the offline software gate a deterministic,
engine-independent contract for DNE, expiry, exercise, assignment and stock
consequences.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from stocks_tool.domain.strategies.common import decimal


@dataclass(frozen=True)
class LifecycleSettlement:
    cash_delta: Decimal
    stock_delta: Decimal
    exercised: tuple[dict[str, str], ...]
    assigned: tuple[dict[str, str], ...]
    warnings: tuple[str, ...] = ()

    def as_payload(self, *, strategy: str, symbol: str, action: str, underlying: Decimal) -> dict[str, Any]:
        return {
            "type": "settlement",
            "strategy": strategy,
            "symbol": symbol,
            "action": action,
            "underlying_price": str(underlying),
            "cash_delta": str(self.cash_delta),
            "stock_delta": str(self.stock_delta),
            "exercised": list(self.exercised),
            "assigned": list(self.assigned),
            "warnings": list(self.warnings),
        }


def settle_option_position(
    legs: Iterable[dict[str, Any]],
    *,
    strategy: str,
    underlying: Decimal,
    do_not_exercise: bool = False,
    exercise_enabled: bool = True,
    assignment_enabled: bool = True,
    contract_multiplier: int | Decimal = 100,
) -> LifecycleSettlement:
    """Settle the filled option legs at expiry/assignment.

    Long ITM options exercise unless DNE is present. Short ITM options are
    assigned when assignment handling is enabled. Cash and share changes are
    returned separately so callers can mark the resulting stock position.
    """

    cash_delta = Decimal("0")
    stock_delta = Decimal("0")
    exercised: list[dict[str, str]] = []
    assigned: list[dict[str, str]] = []
    warnings: list[str] = []
    multiplier = decimal(contract_multiplier, Decimal("100")) or Decimal("100")
    for leg in legs:
        right = str(leg.get("right", "")).lower()
        strike = decimal(leg.get("strike"))
        quantity = decimal(leg.get("quantity"), Decimal("0")) or Decimal("0")
        if right not in {"call", "put"} or strike is None or quantity <= 0:
            continue
        side = str(leg.get("side", "buy")).lower()
        is_itm = underlying > strike if right == "call" else underlying < strike
        if not is_itm:
            continue
        shares = quantity * multiplier
        record = {"right": right, "quantity": str(quantity), "strike": str(strike)}
        if side == "buy":
            if do_not_exercise:
                warnings.append("long_option_dne")
                continue
            if not exercise_enabled:
                warnings.append("exercise_disabled_in_lifecycle_model")
                continue
            if right == "call":
                stock_delta += shares
                cash_delta -= strike * shares
            else:
                stock_delta -= shares
                cash_delta += strike * shares
            exercised.append(record)
            continue
        if not assignment_enabled:
            warnings.append("assignment_disabled_in_lifecycle_model")
            continue
        if right == "call":
            stock_delta -= shares
            cash_delta += strike * shares
        else:
            stock_delta += shares
            cash_delta -= strike * shares
        assigned.append(record)
    return LifecycleSettlement(
        cash_delta=cash_delta,
        stock_delta=stock_delta,
        exercised=tuple(exercised),
        assigned=tuple(assigned),
        warnings=tuple(warnings),
    )


def apply_split(quantity: Decimal, ratio: Decimal) -> Decimal:
    ratio = decimal(ratio)
    if ratio is None or ratio <= 0:
        raise ValueError("split ratio must be positive")
    return quantity * ratio


def dividend_cash(shares: Decimal, amount: Decimal) -> Decimal:
    return shares * amount

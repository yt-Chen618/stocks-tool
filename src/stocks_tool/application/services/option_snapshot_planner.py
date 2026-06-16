from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Sequence, TypeVar

from stocks_tool.domain.models import OptionChainEntry


T = TypeVar("T")


def chunked(items: Sequence[T], *, batch_size: int) -> list[list[T]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")
    return [list(items[index : index + batch_size]) for index in range(0, len(items), batch_size)]


def ranked_otm_call_symbols(
    *,
    chain: Iterable[OptionChainEntry],
    underlying_price: Decimal,
    min_otm_pct: Decimal,
    max_otm_pct: Decimal,
    limit: int,
) -> list[str]:
    if limit <= 0:
        return []
    min_strike = underlying_price * (Decimal("1") + min_otm_pct)
    max_strike = underlying_price * (Decimal("1") + max_otm_pct)
    candidates = [
        entry
        for entry in chain
        if entry.standard
        and entry.call_symbol
        and min_strike <= entry.strike <= max_strike
    ]
    target_strike = underlying_price * (Decimal("1") + min_otm_pct)
    ranked = sorted(
        candidates,
        key=lambda entry: (
            abs(entry.strike - target_strike),
            entry.strike,
        ),
    )
    return [entry.call_symbol for entry in ranked[:limit] if entry.call_symbol]

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import re
from zoneinfo import ZoneInfo

from stocks_tool.domain.models import AccountSnapshot, PositionSnapshot


_US_OPTION_SYMBOL = re.compile(
    r"^(?P<underlying>[A-Z0-9._-]+?)(?P<expiry>\d{6})(?P<right>[CP])(?P<strike>\d{6,8})\.US$",
    re.IGNORECASE,
)
_NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ParsedUsOptionSymbol:
    symbol: str
    underlying_symbol: str
    expiration_date: date
    right: str
    strike: Decimal


def parse_us_option_symbol(symbol: str) -> ParsedUsOptionSymbol | None:
    """Parse Longbridge's compact US option symbol without trusting asset_type."""

    normalized = symbol.strip().upper()
    match = _US_OPTION_SYMBOL.fullmatch(normalized)
    if match is None:
        return None
    try:
        expiration_date = datetime.strptime(match.group("expiry"), "%y%m%d").date()
    except ValueError:
        return None
    return ParsedUsOptionSymbol(
        symbol=normalized,
        underlying_symbol=f"{match.group('underlying').upper()}.US",
        expiration_date=expiration_date,
        right=match.group("right").upper(),
        strike=Decimal(match.group("strike")) / Decimal("1000"),
    )


def same_day_expiring_option_positions(
    snapshot: AccountSnapshot,
    *,
    as_of: datetime | date,
) -> list[tuple[PositionSnapshot, ParsedUsOptionSymbol]]:
    session_date = (
        as_of.astimezone(_NEW_YORK).date()
        if isinstance(as_of, datetime) and as_of.tzinfo is not None
        else as_of.date()
        if isinstance(as_of, datetime)
        else as_of
    )
    matches: list[tuple[PositionSnapshot, ParsedUsOptionSymbol]] = []
    for position in snapshot.positions:
        if position.quantity == 0:
            continue
        parsed = parse_us_option_symbol(position.symbol)
        if parsed is not None and parsed.expiration_date == session_date:
            matches.append((position, parsed))
    return matches

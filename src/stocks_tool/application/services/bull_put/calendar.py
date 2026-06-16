from __future__ import annotations

from datetime import date, datetime, time as datetime_time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo


def observed_fixed_holiday(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def nth_weekday_of_month(year: int, month: int, weekday: int, occurrence: int) -> date:
    current = date(year, month, 1)
    while current.weekday() != weekday:
        current += timedelta(days=1)
    current += timedelta(days=(occurrence - 1) * 7)
    return current


def last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    while current.weekday() != weekday:
        current -= timedelta(days=1)
    return current


def easter_sunday(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache
def us_options_holidays(year: int) -> frozenset[date]:
    holidays: set[date] = set()
    for fixed in (
        date(year, 1, 1),
        date(year, 6, 19),
        date(year, 7, 4),
        date(year, 12, 25),
    ):
        observed = observed_fixed_holiday(fixed)
        if observed.year == year:
            holidays.add(observed)
    next_new_year_observed = observed_fixed_holiday(date(year + 1, 1, 1))
    if next_new_year_observed.year == year:
        holidays.add(next_new_year_observed)
    holidays.add(nth_weekday_of_month(year, 1, 0, 3))
    holidays.add(nth_weekday_of_month(year, 2, 0, 3))
    holidays.add(easter_sunday(year) - timedelta(days=2))
    holidays.add(last_weekday_of_month(year, 5, 0))
    holidays.add(nth_weekday_of_month(year, 9, 0, 1))
    holidays.add(nth_weekday_of_month(year, 11, 3, 4))
    return frozenset(holidays)


def is_us_options_trading_day(local_date: date) -> bool:
    return local_date.weekday() < 5 and local_date not in us_options_holidays(local_date.year)


def next_us_options_trading_day(start_date: date) -> date:
    current = start_date
    while not is_us_options_trading_day(current):
        current += timedelta(days=1)
    return current


def session_date(as_of: datetime, *, market_timezone: ZoneInfo) -> date:
    return as_of.astimezone(market_timezone).date()


def market_session_label(as_of: datetime, *, market_timezone: ZoneInfo) -> str:
    local_time = as_of.astimezone(market_timezone)
    if local_time.weekday() >= 5:
        return "weekend"
    if not is_us_options_trading_day(local_time.date()):
        return "holiday"
    session_minutes = (local_time.hour * 60) + local_time.minute
    if session_minutes < 570:
        return "premarket"
    if session_minutes < 960:
        return "regular"
    return "postmarket"


def target_session_date(
    as_of: datetime,
    *,
    market_timezone: ZoneInfo,
    session: str | None = None,
) -> date:
    local_date = session_date(as_of, market_timezone=market_timezone)
    current_session = session or market_session_label(as_of, market_timezone=market_timezone)
    if current_session in {"premarket", "regular"} and is_us_options_trading_day(local_date):
        return local_date
    return next_us_options_trading_day(local_date + timedelta(days=1))


def next_regular_open_at(
    *,
    session: str,
    target_session_date: date,
    market_timezone: ZoneInfo,
) -> datetime | None:
    if session == "regular":
        return None
    return datetime.combine(
        target_session_date,
        datetime_time(hour=9, minute=30),
        tzinfo=market_timezone,
    ).astimezone(timezone.utc)


def minutes_to_regular_open(
    as_of: datetime,
    *,
    session: str,
    market_timezone: ZoneInfo,
) -> int | None:
    if session != "premarket":
        return None
    local_time = as_of.astimezone(market_timezone)
    open_minutes = (9 * 60) + 30
    session_minutes = (local_time.hour * 60) + local_time.minute
    return max(open_minutes - session_minutes, 0)

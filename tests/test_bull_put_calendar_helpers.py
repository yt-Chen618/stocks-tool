from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from stocks_tool.application.services.bull_put.calendar import (
    is_us_options_trading_day,
    market_session_label,
    minutes_to_regular_open,
    next_regular_open_at,
    next_us_options_trading_day,
    target_session_date,
    us_options_holidays,
)


NY = ZoneInfo("America/New_York")


def test_us_options_holidays_include_observed_dates() -> None:
    holidays = us_options_holidays(2026)

    assert date(2026, 5, 25) in holidays
    assert is_us_options_trading_day(date(2026, 5, 25)) is False
    assert next_us_options_trading_day(date(2026, 5, 25)) == date(2026, 5, 26)


def test_market_session_and_target_session_dates_use_exchange_calendar() -> None:
    premarket = datetime(2026, 5, 22, 12, 45, tzinfo=timezone.utc)
    holiday = datetime(2026, 5, 25, 13, 0, tzinfo=timezone.utc)

    assert market_session_label(premarket, market_timezone=NY) == "premarket"
    assert target_session_date(premarket, market_timezone=NY) == date(2026, 5, 22)
    assert market_session_label(holiday, market_timezone=NY) == "holiday"
    assert target_session_date(holiday, market_timezone=NY) == date(2026, 5, 26)


def test_next_regular_open_helpers() -> None:
    premarket = datetime(2026, 5, 22, 12, 45, tzinfo=timezone.utc)

    assert minutes_to_regular_open(premarket, session="premarket", market_timezone=NY) == 45
    assert minutes_to_regular_open(premarket, session="regular", market_timezone=NY) is None
    assert next_regular_open_at(
        session="premarket",
        target_session_date=date(2026, 5, 22),
        market_timezone=NY,
    ) == datetime(2026, 5, 22, 13, 30, tzinfo=timezone.utc)
    assert next_regular_open_at(
        session="regular",
        target_session_date=date(2026, 5, 22),
        market_timezone=NY,
    ) is None

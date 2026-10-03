from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from stocks_tool.application.services.market_session_comparison import MarketSessionComparisonService
from stocks_tool.db.base import Base
from stocks_tool.db.market_session_models import MarketSessionComparisonRecord
from stocks_tool.db.models import BrokerAccountRecord, UserRecord
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.market_session_comparisons import (
    CaptureMarketSessionComparisonRequest,
    MarketSessionComparison,
    MarketSessionComparisonIdempotencyConflictError,
)
from stocks_tool.domain.models import (
    HistoricalPriceBar,
    PreOpenDownsideAssessment,
    PreOpenAssessmentRun,
    PreOpenProxySignal,
    SecurityQuoteSnapshot,
    SessionQuote,
)
from stocks_tool.repositories.sqlalchemy_market_session_repository import (
    SQLAlchemyMarketSessionComparisonRepository,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


ACCOUNT = "LBPT10087357"
SESSION_DATE = date(2026, 10, 2)
BASELINE_AT = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
REGULAR_AT = datetime(2026, 10, 2, 20, 5, tzinfo=timezone.utc)
POST_AT = datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc)


def _run(symbol: str = "QQQ.US") -> PreOpenAssessmentRun:
    signal = PreOpenProxySignal(
        key="qqq",
        label="Nasdaq 100 ETF",
        symbol=symbol,
        session_price=Decimal("100"),
        reference_price=Decimal("99"),
        change_pct=Decimal("1.01"),
        signal="supportive",
    )
    assessment = PreOpenDownsideAssessment(
        analyzed_at=BASELINE_AT,
        session="premarket",
        market_open=False,
        target_session_date=SESSION_DATE,
        downside_score=1,
        regime="neutral",
        plain_put_view="wait",
        trade_action="wait",
        trade_action_detail="Wait for regular-session evidence.",
        gap_chase_risk="low",
        gap_chase_detail="No gap chase.",
        summary="Pre-open baseline.",
        signals=[signal],
    )
    return PreOpenAssessmentRun(
        id="pre-open-1",
        external_account_id=ACCOUNT,
        target_session_date=SESSION_DATE,
        assessment=assessment,
    )


def _quote(
    *,
    post: bool = True,
    timestamp: datetime = REGULAR_AT,
    post_timestamp: datetime = POST_AT,
) -> SecurityQuoteSnapshot:
    post_quote = (
        SessionQuote(
            last_done=Decimal("112"),
            timestamp=post_timestamp,
            volume=100,
            turnover=Decimal("11200"),
            high=Decimal("113"),
            low=Decimal("110"),
            prev_close=Decimal("110"),
        )
        if post
        else None
    )
    return SecurityQuoteSnapshot(
        symbol="QQQ.US",
        last_done=Decimal("110"),
        prev_close=Decimal("108"),
        open=Decimal("109"),
        high=Decimal("111"),
        low=Decimal("108"),
        timestamp=timestamp,
        volume=1000,
        turnover=Decimal("110000"),
        trade_status="Normal",
        post_market_quote=post_quote,
    )


class FakeComparisonRepository:
    def __init__(self, *, currency: str = "USD") -> None:
        self.currency = currency
        self.records = {}
        self.create_calls = 0

    def get_account_context(self, external_account_id: str):
        return ("broker-1", self.currency) if external_account_id == ACCOUNT else None

    def create_comparison(self, comparison):
        self.create_calls += 1
        self.records[comparison.id] = comparison
        return comparison

    def get_by_idempotency_key(self, idempotency_key: str):
        return next(
            (record for record in self.records.values() if record.idempotency_key == idempotency_key),
            None,
        )

    def get_comparison(self, comparison_id: str):
        return self.records.get(comparison_id)

    def list_comparisons(self, *, external_account_id, mode, symbol=None, limit=50, cursor=None):
        values = [
            record
            for record in self.records.values()
            if record.external_account_id == external_account_id and record.mode == mode
            and (symbol is None or record.symbol == symbol.upper())
        ]
        from stocks_tool.domain.market_session_comparisons import MarketSessionComparisonPage

        return MarketSessionComparisonPage(items=values[:limit], limit=limit, has_more=len(values) > limit)

    def latest_comparison(self, *, external_account_id, mode, symbol):
        values = [
            record for record in self.records.values()
            if record.external_account_id == external_account_id
            and record.mode == mode
            and record.symbol == symbol.upper()
        ]
        return values[-1] if values else None


class FakePreOpenRepository:
    def __init__(self, run: PreOpenAssessmentRun | None) -> None:
        self.run = run

    def get_run(self, run_id: str):
        return self.run if self.run is not None and self.run.id == run_id else None

    def list_runs(self, *, external_account_id=None, limit=20):
        return [self.run] if self.run is not None and self.run.external_account_id == external_account_id else []


class FakeMarketData:
    def __init__(self, *, quote: SecurityQuoteSnapshot, bars: list[HistoricalPriceBar], half_day: bool = False):
        self.quote = quote
        self.bars = bars
        self.half_day = half_day
        self.quote_calls = 0
        self.bar_calls = 0

    def get_us_market_calendar(self, local_date: date, mode: ExecutionMode):
        return True, self.half_day

    def get_quote(self, symbol: str, mode: ExecutionMode):
        self.quote_calls += 1
        return self.quote

    def get_recent_daily_bars(self, symbol: str, *, count: int, mode: ExecutionMode):
        self.bar_calls += 1
        return self.bars[:count]


def _bar(day: date = SESSION_DATE, close: str = "110") -> HistoricalPriceBar:
    return HistoricalPriceBar(
        symbol="QQQ.US",
        timestamp=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc).replace(hour=20),
        open=Decimal("109"),
        high=Decimal("111"),
        low=Decimal("108"),
        close=Decimal(close),
        volume=1000,
        turnover=Decimal("110000"),
    )


def _service(*, run=None, has_run=True, quote=None, bars=None, currency="USD", half_day=False, now=POST_AT):
    repository = FakeComparisonRepository(currency=currency)
    market_data = FakeMarketData(
        quote=quote or _quote(),
        bars=bars if bars is not None else [_bar()],
        half_day=half_day,
    )
    service = MarketSessionComparisonService(
        comparisons=repository,
        pre_open_runs=FakePreOpenRepository((run or _run()) if has_run else None),
        market_data=market_data,
        now=lambda: now,
    )
    return service, repository, market_data


def test_capture_computes_same_day_preopen_close_and_after_hours_changes() -> None:
    service, repository, market_data = _service()
    result = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US"))

    comparison = result.comparison
    assert result.captured is True
    assert comparison.status == "valid"
    assert comparison.baseline_price == Decimal("100")
    assert comparison.regular_close_price == Decimal("110")
    assert comparison.after_hours_price == Decimal("112")
    assert comparison.pre_to_regular_close_pct == Decimal("10.00")
    assert comparison.regular_close_to_after_hours_pct == Decimal("1.82")
    assert comparison.pre_open_run_id == "pre-open-1"
    assert comparison.raw_evidence["quote"]["post_market_quote"]["last_done"] == "112"
    assert repository.create_calls == 1
    assert market_data.quote_calls == 1


def test_missing_post_market_quote_is_partial_and_does_not_become_zero() -> None:
    service, _, _ = _service(quote=_quote(post=False))
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "partial"
    assert comparison.pre_to_regular_close_pct == Decimal("10.00")
    assert comparison.after_hours_price is None
    assert comparison.regular_close_to_after_hours_pct is None
    assert "post_market_quote_missing" in comparison.reason_codes


def test_wrong_provider_symbol_is_not_relabelled_as_requested_symbol() -> None:
    service, _, _ = _service(quote=_quote().model_copy(update={"symbol": "SPY.US"}))
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison
    assert comparison.status == "not_available"
    assert comparison.regular_close_price is None
    assert comparison.pre_to_regular_close_pct is None
    assert comparison.raw_evidence["quote"]["symbol"] == "SPY.US"
    assert comparison.reason_codes == ["quote_symbol_mismatch"]


def test_different_trading_day_is_unavailable_without_zero_filling() -> None:
    service, _, _ = _service(
        quote=_quote(post=True, post_timestamp=datetime(2026, 10, 5, 22, 0, tzinfo=timezone.utc)),
        bars=[_bar(day=date(2026, 10, 5))],
    )
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert comparison.pre_to_regular_close_pct is None
    assert comparison.regular_close_to_after_hours_pct is None
    assert "different_trading_day" in comparison.reason_codes


def test_missing_baseline_does_not_call_market_data_and_is_persisted_not_available() -> None:
    service, repository, market_data = _service(has_run=False)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert comparison.reason_codes == ["baseline_missing"]
    assert comparison.baseline_price is None
    assert market_data.quote_calls == 0
    assert repository.create_calls == 1


def test_duplicate_capture_returns_same_immutable_record_without_provider_call() -> None:
    service, repository, market_data = _service()
    request = CaptureMarketSessionComparisonRequest(symbol="QQQ.US", capture_key="session-key-1")
    first = service.capture(request)
    second = service.capture(request)

    assert first.comparison.id == second.comparison.id
    assert second.duplicate is True
    assert second.captured is False
    assert repository.create_calls == 1
    assert market_data.quote_calls == 1


def test_capture_key_is_scoped_and_missing_baseline_default_is_retryable() -> None:
    service, repository, _ = _service(has_run=False)
    first = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US"))
    second = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US"))

    assert first.comparison.id != second.comparison.id
    assert repository.create_calls == 2
    assert first.comparison.idempotency_key != second.comparison.idempotency_key
    assert first.comparison.raw_evidence["capture_request"]["symbol"] == "QQQ.US"


def test_exact_retry_preserves_auto_baseline_after_new_run_arrives() -> None:
    service, repository, market_data = _service()
    request = CaptureMarketSessionComparisonRequest(symbol="QQQ.US", capture_key="retry")
    first = service.capture(request)
    service.pre_open_runs.run = _run().model_copy(update={"id": "new-pre-open"})
    second = service.capture(request)
    assert second.duplicate and not second.captured
    assert second.comparison.id == first.comparison.id
    assert second.comparison.pre_open_run_id == "pre-open-1"
    assert repository.create_calls == market_data.quote_calls == 1


@pytest.mark.parametrize("change", [{"symbol": "SPY.US"}, {"pre_open_run_id": "different-run"}])
def test_reused_key_with_different_intent_conflicts_before_provider(change) -> None:
    service, _, market_data = _service()
    request = CaptureMarketSessionComparisonRequest(symbol="QQQ.US", capture_key="same-key")
    service.capture(request)
    with pytest.raises(MarketSessionComparisonIdempotencyConflictError):
        service.capture(request.model_copy(update=change))
    assert market_data.quote_calls == 1


def test_idempotency_key_is_bounded_at_maximum_request_lengths() -> None:
    request = CaptureMarketSessionComparisonRequest(
        external_account_id="a" * 64, symbol="s" * 32,
        pre_open_run_id="r" * 36, capture_key="k" * 120,
    )
    assert len(MarketSessionComparisonService._idempotency_key(request)) <= 180
    assert MarketSessionComparisonService._idempotency_key(request) == MarketSessionComparisonService._idempotency_key(request)


def test_no_key_means_new_capture_even_with_existing_baseline() -> None:
    service, repository, market_data = _service()
    request = CaptureMarketSessionComparisonRequest(symbol="QQQ.US")
    first, second = service.capture(request), service.capture(request)
    assert first.comparison.id != second.comparison.id
    assert repository.create_calls == market_data.quote_calls == 2


@pytest.mark.parametrize("same_request", [True, False])
def test_insert_race_rechecks_original_request_and_duplicate_status(same_request) -> None:
    service, repository, _ = _service()
    request = CaptureMarketSessionComparisonRequest(symbol="QQQ.US", capture_key="race")
    first = service.capture(request)
    repository.get_by_idempotency_key = lambda key: None
    repository.create_comparison = lambda proposed: first.comparison
    if same_request:
        result = service.capture(request)
        assert result.duplicate and not result.captured
        assert result.comparison.id == first.comparison.id
    else:
        with pytest.raises(MarketSessionComparisonIdempotencyConflictError):
            service.capture(request.model_copy(update={"symbol": "SPY.US"}))


@pytest.mark.parametrize(
    "session,market_open",
    [("regular", True), ("noon", True), ("postmarket", True)],
)
def test_saved_non_premarket_run_cannot_be_used_as_baseline(session: str, market_open: bool) -> None:
    base_run = _run()
    run = base_run.model_copy(
        update={
            "assessment": base_run.assessment.model_copy(
                update={"session": session, "market_open": market_open}
            )
        }
    )
    service, _, market_data = _service(run=run)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert comparison.reason_codes == ["baseline_not_preopen"]
    assert market_data.quote_calls == 0


def test_auto_baseline_skips_newer_intraday_assessment() -> None:
    service, _, _ = _service()
    valid = _run()
    intraday = valid.model_copy(update={
        "id": "intraday", "assessment": valid.assessment.model_copy(update={"session": "regular", "market_open": True}),
    })
    service.pre_open_runs.list_runs = lambda **kwargs: [intraday, valid]
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison
    assert comparison.pre_open_run_id == valid.id
    assert comparison.status == "valid"


def test_future_target_baseline_is_not_comparable() -> None:
    future_date = date(2026, 10, 5)
    future_run = _run().model_copy(
        update={
            "target_session_date": future_date,
            "assessment": _run().assessment.model_copy(
                update={
                    "target_session_date": future_date,
                    "analyzed_at": datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
                }
            ),
        }
    )
    service, _, market_data = _service(run=future_run)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert "baseline_future" in comparison.reason_codes
    assert market_data.quote_calls == 1


def test_preclose_capture_rejects_future_provider_quote_strictly() -> None:
    capture_now = datetime(2026, 10, 2, 19, 58, tzinfo=timezone.utc)  # 15:58 ET
    future_quote = _quote(
        post=True,
        timestamp=datetime(2026, 10, 2, 20, 2, tzinfo=timezone.utc),  # 16:02 ET
        post_timestamp=datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc),
    )
    service, _, _ = _service(quote=future_quote, now=capture_now)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert comparison.pre_to_regular_close_pct is None
    assert "capture_before_session_close" in comparison.reason_codes
    assert "future_evidence_timestamp" in comparison.reason_codes


def test_account_currency_is_kept_separate_from_quote_currency() -> None:
    service, _, _ = _service(currency="HKD")
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "valid"
    assert comparison.account_currency == "HKD"
    assert comparison.quote_currency == "USD"
    assert comparison.pre_to_regular_close_pct == Decimal("10.00")


def test_unknown_account_currency_is_preserved_without_blocking_same_quote_currency() -> None:
    service, _, _ = _service(currency=None)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "valid"
    assert comparison.account_currency is None


def test_naive_evidence_timestamps_are_unknown_and_never_verified() -> None:
    naive_quote = _quote(post=True).model_copy(update={"timestamp": REGULAR_AT.replace(tzinfo=None)})
    service, _, _ = _service(quote=naive_quote)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert comparison.pre_to_regular_close_pct is None
    assert "timestamp_timezone_unknown" in comparison.reason_codes


def test_half_day_calendar_uses_thirteen_et_close() -> None:
    quote = _quote(
        post=True,
        timestamp=datetime(2026, 10, 2, 18, 5, tzinfo=timezone.utc),
        post_timestamp=datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc),
    )
    service, _, _ = _service(quote=quote, half_day=True)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "valid"
    assert comparison.regular_close_evidence.session_close_at == datetime(2026, 10, 2, 17, 0, tzinfo=timezone.utc)


def test_observation_before_calendar_close_cannot_be_regular_close() -> None:
    quote = _quote(
        post=True,
        timestamp=datetime(2026, 10, 2, 18, 5, tzinfo=timezone.utc),
        post_timestamp=datetime(2026, 10, 2, 19, 0, tzinfo=timezone.utc),
    )
    service, _, _ = _service(quote=quote, now=datetime(2026, 10, 2, 19, 58, tzinfo=timezone.utc))
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert comparison.pre_to_regular_close_pct is None
    assert "regular_close_not_complete" in comparison.reason_codes


def test_post_prev_close_without_observation_time_cannot_be_verified_close() -> None:
    quote = _quote(post=True).model_copy(
        update={"post_market_quote": _quote(post=True).post_market_quote.model_copy(update={"timestamp": None})}
    )
    service, _, _ = _service(quote=quote)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert comparison.regular_close_price is None or comparison.pre_to_regular_close_pct is None
    assert "timestamp_timezone_unknown" in comparison.reason_codes


def test_future_provider_timestamp_is_not_accepted_as_current_evidence() -> None:
    future_quote = _quote(
        post=True,
        timestamp=datetime(2026, 10, 3, 20, 5, tzinfo=timezone.utc),
        post_timestamp=datetime(2026, 10, 3, 22, 0, tzinfo=timezone.utc),
    )
    service, _, _ = _service(quote=future_quote)
    comparison = service.capture(CaptureMarketSessionComparisonRequest(symbol="QQQ.US")).comparison

    assert comparison.status == "not_available"
    assert comparison.pre_to_regular_close_pct is None
    assert "future_evidence_timestamp" in comparison.reason_codes


def test_sqlalchemy_comparison_list_has_keyset_cursor() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[UserRecord.__table__, BrokerAccountRecord.__table__, MarketSessionComparisonRecord.__table__],
    )
    with Session(engine) as session:
        session.add(
            BrokerAccountRecord(
                id="broker-1",
                external_account_id=ACCOUNT,
                broker="longbridge",
                base_currency="USD",
            )
        )
        session.commit()
        repository = SQLAlchemyMarketSessionComparisonRepository(session)
        for index in range(3):
            repository.create_comparison(
                MarketSessionComparison(
                    external_account_id=ACCOUNT,
                    symbol="QQQ.US",
                    idempotency_key=f"cursor-{index}",
                    created_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
                )
            )
        first = repository.list_comparisons(
            external_account_id=ACCOUNT,
            mode=ExecutionMode.PAPER,
            limit=2,
        )
        second = repository.list_comparisons(
            external_account_id=ACCOUNT,
            mode=ExecutionMode.PAPER,
            limit=2,
            cursor=first.next_cursor,
        )
        assert first.has_more is True
        assert first.next_cursor
        assert len(second.items) == 1
        assert second.has_more is False

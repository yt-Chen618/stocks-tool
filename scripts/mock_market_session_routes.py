"""Synthetic market-session records for the isolated workbench demo.

The real comparison service computes these prices and quality decisions against
a frozen, explicitly fictional feed.  No database or broker is constructed.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from threading import Lock

from fastapi import HTTPException, Query, Response

from stocks_tool.application.services.market_session_comparison import MarketSessionComparisonService
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.market_session_comparisons import (
    CaptureMarketSessionComparisonRequest,
    MarketSessionComparisonPage,
)
from stocks_tool.domain.models import (
    PreOpenAssessmentRun,
    PreOpenDownsideAssessment,
    PreOpenProxySignal,
    SecurityQuoteSnapshot,
    SessionQuote,
)


def install_market_session_routes(app, state, paginate):
    records = {}
    lock = Lock()
    clock_tick = 0
    day = date(2026, 10, 2)
    baseline = PreOpenAssessmentRun(
        id="mock-session-preopen-0001",
        external_account_id=state.account_id,
        target_session_date=day,
        assessment=PreOpenDownsideAssessment(
            analyzed_at=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
            session="premarket", market_open=False, target_session_date=day,
            downside_score=0, regime="neutral", plain_put_view="wait", trade_action="wait",
            trade_action_detail="演示基准，仅用于观察时段变化。",
            gap_chase_risk="low", gap_chase_detail="合成样例，不代表实际风险。",
            summary="演示用的盘前观测，不是当前券商行情。",
            signals=[PreOpenProxySignal(
                key=symbol.split(".")[0].lower(), label=symbol, symbol=symbol,
                session_price=price, reference_price=price, change_pct=Decimal("0"), signal="neutral",
            ) for symbol, price in [("QQQ.US", Decimal("500")), ("SPY.US", Decimal("600"))]],
        ),
        created_at=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
        raw_payload={"source": "mock_market_session_baseline", "synthetic": True},
    )
    # Keep the older opening-only fixture stable, while making this separate
    # baseline inspectable through the existing pre-open run list.
    state.pre_open_runs.append(baseline.model_dump(mode="json"))

    def now():
        nonlocal clock_tick
        clock_tick += 1
        return datetime(2026, 10, 2, 22, 0, 30, tzinfo=timezone.utc) + timedelta(milliseconds=clock_tick)

    class Repository:
        def get_account_context(self, account):
            return ("mock-account-1", "USD") if account == state.account_id else None

        def create_comparison(self, comparison):
            with lock:
                prior = self.get_by_idempotency_key(comparison.idempotency_key)
                if prior is not None:
                    return prior
                value = comparison.model_copy(deep=True)
                value.source = "mock_market_session_capture"
                value.raw_evidence["synthetic"] = True
                value.reason_detail = "演示数据。" + value.reason_detail
                for evidence in (value.baseline_evidence, value.regular_close_evidence, value.post_market_evidence):
                    if evidence is not None:
                        evidence.source = "mock_" + evidence.source
                records[value.id] = value
                return value.model_copy(deep=True)

        def get_by_idempotency_key(self, key):
            value = next((row for row in records.values() if row.idempotency_key == key), None)
            return value.model_copy(deep=True) if value else None

        def get_comparison(self, key):
            value = records.get(key)
            return value.model_copy(deep=True) if value else None

        def list_comparisons(self, *, external_account_id, mode, symbol=None, limit=50, cursor=None):
            symbol = symbol.strip().upper() if symbol else None
            rows = [row.model_dump(mode="json") for row in records.values()
                    if row.external_account_id == external_account_id and row.mode == mode
                    and (symbol is None or row.symbol == symbol)]
            page = paginate(rows, resource="mock-market-session-comparisons",
                            scope={"account": external_account_id, "mode": mode.value, "symbol": symbol},
                            limit=limit, cursor=cursor)
            return MarketSessionComparisonPage.model_validate(page)

        def latest_comparison(self, *, external_account_id, mode, symbol):
            page = self.list_comparisons(external_account_id=external_account_id, mode=mode, symbol=symbol, limit=1)
            return page.items[0] if page.items else None

    class Baselines:
        def get_run(self, run_id):
            return baseline.model_copy(deep=True) if run_id == baseline.id else None

        def list_runs(self, *, external_account_id=None, limit=20):
            return [baseline.model_copy(deep=True)] if external_account_id in {None, state.account_id} else []

    class Feed:
        def get_us_market_calendar(self, local_date, mode):
            return local_date == day, False

        def get_recent_daily_bars(self, symbol, *, count, mode):
            return []

        def get_quote(self, symbol, mode):
            close, after = (Decimal("510"), Decimal("512")) if symbol == "QQQ.US" else (Decimal("612"), Decimal("606"))
            return SecurityQuoteSnapshot(
                symbol=symbol, last_done=close, prev_close=close, open=close,
                high=close, low=close, timestamp=datetime(2026, 10, 2, 20, 0, tzinfo=timezone.utc),
                volume=1000, turnover=close * 1000, trade_status="Normal",
                post_market_quote=SessionQuote(
                    last_done=after, prev_close=close, high=after, low=after, volume=100,
                    turnover=after * 100, timestamp=datetime(2026, 10, 2, 22, 0, tzinfo=timezone.utc),
                ),
            )

    service = MarketSessionComparisonService(comparisons=Repository(), pre_open_runs=Baselines(), market_data=Feed(), now=now)
    for symbol in ("QQQ.US", "SPY.US"):
        service.capture(CaptureMarketSessionComparisonRequest(
            external_account_id=state.account_id, symbol=symbol, pre_open_run_id=baseline.id,
            capture_key="mock-session-seed-" + symbol,
        ))

    def call(fn, *args, **kwargs):
        from stocks_tool.api.routes.market_session_comparisons import _raise_comparison_error
        try:
            return fn(*args, **kwargs)
        except HTTPException:
            raise
        except Exception as error:
            _raise_comparison_error(error)
            raise

    @app.get("/market-session-comparisons")
    def list_comparisons(external_account_id: str = state.account_id, mode: ExecutionMode = ExecutionMode.PAPER,
                         symbol: str | None = None, limit: int = Query(50, ge=1, le=100), cursor: str | None = None):
        return call(service.list, external_account_id=external_account_id, mode=mode, symbol=symbol, limit=limit, cursor=cursor)

    @app.get("/market-session-comparisons/latest")
    def latest(symbol: str, external_account_id: str = state.account_id, mode: ExecutionMode = ExecutionMode.PAPER):
        return call(service.latest, external_account_id=external_account_id, mode=mode, symbol=symbol)

    @app.get("/market-session-comparisons/{comparison_id}")
    def detail(comparison_id: str, external_account_id: str = state.account_id, mode: ExecutionMode = ExecutionMode.PAPER):
        return call(service.get, comparison_id, external_account_id=external_account_id, mode=mode)

    @app.post("/market-session-comparisons", status_code=201)
    def capture(request: CaptureMarketSessionComparisonRequest, response: Response):
        result = call(service.capture, request)
        if result.duplicate:
            response.status_code = 200
        return result

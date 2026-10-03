from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_research_workspace_service
from stocks_tool.application.services.research_workspace import (
    ResearchUniverseLimitError,
    ResearchWorkspaceService,
    calculate_technical_snapshot,
)
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    MarketEventType,
    SpreadStatus,
    StrategyProposalStatus,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    HistoricalPriceBar,
    MarketEvent,
    PositionSnapshot,
    ResearchTechnicalsResponse,
    SecurityQuoteSnapshot,
    StrategyProposal,
    Watchlist,
    WatchlistItem,
)
from stocks_tool.main import app


NOW = datetime(2026, 8, 10, 14, 30, tzinfo=timezone.utc)


def _bars(count: int, *, symbol: str = "QQQ.US") -> list[HistoricalPriceBar]:
    return [
        HistoricalPriceBar(
            symbol=symbol,
            timestamp=NOW - timedelta(days=count - index),
            open=Decimal(99 + index),
            high=Decimal(101 + index),
            low=Decimal(98 + index),
            close=Decimal(100 + index),
            volume=1000 + index,
            turnover=Decimal(2000 + index),
        )
        for index in range(count)
    ]


def _quote(symbol: str) -> SecurityQuoteSnapshot:
    return SecurityQuoteSnapshot(
        symbol=symbol,
        last_done=Decimal("165"),
        prev_close=Decimal("164"),
        open=Decimal("164.5"),
        high=Decimal("166"),
        low=Decimal("163"),
        timestamp=NOW,
        volume=10000,
        turnover=Decimal("1650000"),
        trade_status="Normal",
    )


def _watchlist(items: list[WatchlistItem]) -> Watchlist:
    return Watchlist(
        id="watch-1",
        name="Core",
        is_default=True,
        items=items,
        created_at=NOW,
        updated_at=NOW,
    )


def _service(
    *,
    watchlist: Watchlist | None = None,
    market_data=None,
    strategy_experiments=None,
    bull_put_spreads=None,
) -> ResearchWorkspaceService:
    watchlists = Mock()
    watchlists.list_watchlists.return_value = [watchlist] if watchlist else []
    watchlists.get_watchlist.side_effect = lambda watchlist_id: (
        watchlist if watchlist and watchlist.id == watchlist_id else None
    )
    snapshots = Mock()
    snapshots.get_latest_account_snapshot.return_value = AccountSnapshot(
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        cash_balance=Decimal("1000"),
        net_liquidation=Decimal("1500"),
        buying_power=Decimal("900"),
        positions=[
            PositionSnapshot(
                symbol="QQQ.US",
                asset_type=AssetType.ETF,
                quantity=Decimal("2"),
                average_cost=Decimal("450"),
                market_value=Decimal("930"),
                unrealized_pnl=Decimal("30"),
            )
        ],
        captured_at=NOW,
    )
    events = Mock()
    events.list_events.return_value = [
        MarketEvent(
            symbol="QQQ.US",
            event_type=MarketEventType.EARNINGS,
            title="Index constituent earnings window",
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=2),
        )
    ]
    spreads = bull_put_spreads or Mock()
    if bull_put_spreads is None:
        spreads.list_spreads.return_value = [
            SimpleNamespace(underlying_symbol="QQQ.US", status=SpreadStatus.OPEN)
        ]
    if strategy_experiments is None:
        strategy_experiments = Mock()
        strategy_experiments.list_proposals.return_value = []
    market_data = market_data or Mock()
    if not getattr(market_data.get_quotes, "side_effect", None):
        market_data.get_quotes.side_effect = lambda symbols, mode: {
            symbol: _quote(symbol) for symbol in symbols
        }
    return ResearchWorkspaceService(
        settings=Settings(_env_file=None),
        watchlists=watchlists,
        account_snapshots=snapshots,
        market_events=events,
        bull_put_spreads=spreads,
        strategy_experiments=strategy_experiments,
        market_data=market_data,
    )


def test_calculate_technicals_uses_prior_complete_20_bars() -> None:
    result = calculate_technical_snapshot("QQQ.US", _bars(66))

    assert result.status == "ok"
    assert result.return_20d_pct == pytest.approx(((165 / 145) - 1) * 100)
    assert result.return_60d_pct == pytest.approx(((165 / 105) - 1) * 100)
    assert result.sma20 == Decimal("155.5")
    assert result.sma50 == Decimal("140.5")
    assert result.close_above_sma20 is True
    assert result.sma20_above_sma50 is True
    assert result.realized_volatility_20d_pct is not None
    assert result.average_volume_20d == pytest.approx(1054.5)
    assert result.average_turnover_20d == Decimal("2054.5")


def test_calculate_technicals_marks_short_history_partial() -> None:
    result = calculate_technical_snapshot("QQQ.US", _bars(20))

    assert result.status == "partial"
    assert result.sma20 == Decimal("109.5")
    assert result.sma50 is None
    assert result.return_20d_pct is None
    assert "insufficient_history" in result.warning


def test_universe_deduplicates_sources_and_merges_context() -> None:
    watchlist = _watchlist(
        [
            WatchlistItem(
                id="item-1",
                symbol="qqq.us",
                asset_type=AssetType.ETF,
                notes="Core index",
                created_at=NOW,
            )
        ]
    )
    service = _service(watchlist=watchlist)

    response = service.get_universe(
        external_account_id="LBPT10087357",
        watchlist_id=None,
        mode=ExecutionMode.PAPER,
    )

    row = next(row for row in response.rows if row.symbol == "QQQ.US")
    assert response.watchlist_id == "watch-1"
    assert row.sources == ["watchlist", "position", "bull_put", "zero_dte", "bull_put_spread"]
    assert row.notes == "Core index"
    assert row.position_quantity == Decimal("2")
    assert row.quote is not None
    assert row.next_event is not None
    assert row.strategy_states == [
        "bull_put:configured",
        "zero_dte:preview_only",
        "bull_put:open",
    ]
    assert response.data_quality == "live"


def test_universe_read_path_handles_historical_dirty_watchlist_symbols() -> None:
    watchlist = _watchlist(
        [
            WatchlistItem(
                id="item-spaced",
                symbol=" qqq.us ",
                asset_type=AssetType.ETF,
                created_at=NOW,
            ),
            WatchlistItem(
                id="item-duplicate",
                symbol="QQQ.US",
                asset_type=AssetType.ETF,
                created_at=NOW,
            ),
            WatchlistItem(
                id="item-blank",
                symbol="   ",
                asset_type=AssetType.ETF,
                created_at=NOW,
            ),
        ]
    )
    service = _service(watchlist=watchlist)

    response = service.get_universe(
        external_account_id=None,
        watchlist_id=None,
        mode=ExecutionMode.PAPER,
    )

    assert "watchlist_symbol_normalized" in response.warnings
    assert "watchlist_duplicate_symbol" in response.warnings
    assert "watchlist_invalid_symbol" in response.warnings
    assert "" not in {row.symbol for row in response.rows}
    assert next(row for row in response.rows if row.symbol == "QQQ.US").sources.count("watchlist") == 1


def test_universe_excludes_terminal_spreads_but_keeps_unresolved_rollback() -> None:
    spreads = Mock()
    spreads.list_spreads.return_value = [
        SimpleNamespace(underlying_symbol="CLOSED.US", status=SpreadStatus.CLOSED),
        SimpleNamespace(underlying_symbol="FAILED.US", status=SpreadStatus.ENTRY_FAILED),
        SimpleNamespace(underlying_symbol="REVIEW.US", status=SpreadStatus.ROLLBACK_FAILED),
    ]
    service = _service(bull_put_spreads=spreads)

    response = service.get_universe(
        external_account_id="LBPT10087357",
        watchlist_id=None,
        mode=ExecutionMode.PAPER,
    )

    symbols = {row.symbol for row in response.rows}
    assert "CLOSED.US" not in symbols
    assert "FAILED.US" not in symbols
    assert "REVIEW.US" in symbols
    review = next(row for row in response.rows if row.symbol == "REVIEW.US")
    assert review.strategy_states == ["bull_put:rollback_failed"]


def test_universe_limit_fails_before_quote_call() -> None:
    items = [
        WatchlistItem(
            id=f"item-{index}",
            symbol=f"SYM{index}.US",
            asset_type=AssetType.STOCK,
            created_at=NOW,
        )
        for index in range(51)
    ]
    market_data = Mock()
    service = _service(watchlist=_watchlist(items), market_data=market_data)

    with pytest.raises(ResearchUniverseLimitError) as exc_info:
        service.get_universe(
            external_account_id=None,
            watchlist_id="watch-1",
            mode=ExecutionMode.PAPER,
        )

    assert exc_info.value.count >= 51
    market_data.get_quotes.assert_not_called()


def test_universe_without_account_or_watchlist_uses_configured_pools() -> None:
    service = _service()

    response = service.get_universe(
        external_account_id=None,
        watchlist_id=None,
        mode=ExecutionMode.PAPER,
    )

    assert response.watchlist_id is None
    assert "default_watchlist_unavailable" in response.warnings
    assert service.account_snapshots.get_latest_account_snapshot.call_count == 0
    assert {"QQQ.US", "SMH.US", "SOXL.US", "EWY.US"} <= {
        row.symbol for row in response.rows
    }
    qqq = next(row for row in response.rows if row.symbol == "QQQ.US")
    assert qqq.strategy_states == ["bull_put:configured", "zero_dte:preview_only"]


def test_universe_adds_proposal_context_without_expanding_proposal_only_symbols() -> None:
    strategy_experiments = Mock()
    strategy_experiments.list_proposals.return_value = [
        StrategyProposal(
            strategy_id="covered_call_v1",
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            symbol="qqq.us",
            title="QQQ covered call",
            proposed_action="sell_call",
            rationale="Existing position",
            status=StrategyProposalStatus.APPROVED,
        ),
        StrategyProposal(
            strategy_id="experimental_v1",
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            symbol="ONLYPROPOSAL.US",
            title="Proposal-only symbol",
            proposed_action="observe",
            rationale="Should not expand the universe",
        ),
    ]
    service = _service(strategy_experiments=strategy_experiments)

    response = service.get_universe(
        external_account_id="LBPT10087357",
        watchlist_id=None,
        mode=ExecutionMode.PAPER,
    )

    qqq = next(row for row in response.rows if row.symbol == "QQQ.US")
    assert "strategy_proposal" in qqq.sources
    assert "covered_call_v1:proposal:approved" in qqq.strategy_states
    assert "ONLYPROPOSAL.US" not in {row.symbol for row in response.rows}
    strategy_experiments.list_proposals.assert_called_once_with(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbols=["EWY.US", "QQQ.US", "SMH.US", "SOXL.US"],
        limit=None,
    )


def test_universe_continues_when_proposals_are_unavailable() -> None:
    strategy_experiments = Mock()
    strategy_experiments.list_proposals.side_effect = RuntimeError("database unavailable")
    service = _service(strategy_experiments=strategy_experiments)

    response = service.get_universe(
        external_account_id="LBPT10087357",
        watchlist_id=None,
        mode=ExecutionMode.PAPER,
    )

    assert response.rows
    assert "strategy_proposals_unavailable" in response.warnings


def test_universe_event_query_keeps_target_events_after_other_symbols() -> None:
    watchlist = _watchlist(
        [
            WatchlistItem(
                id="item-target",
                symbol="TARGET.US",
                asset_type=AssetType.STOCK,
                created_at=NOW,
            )
        ]
    )
    target_event = SimpleNamespace(
        symbol="TARGET.US",
        scheduled_at=NOW + timedelta(days=10),
    )
    events = [
        SimpleNamespace(
            symbol=f"OTHER{index}.US",
            scheduled_at=NOW + timedelta(days=1),
        )
        for index in range(500)
    ] + [target_event]
    service = _service(watchlist=watchlist)

    def list_events(**kwargs):
        candidates = events
        if kwargs.get("symbols") is not None:
            symbols = {symbol.upper() for symbol in kwargs["symbols"]}
            candidates = [
                event
                for event in events
                if event.symbol is None or event.symbol.upper() in symbols
            ]
        limit = kwargs["limit"]
        return candidates if limit is None else candidates[:limit]

    service.market_events.list_events.side_effect = list_events

    response = service.get_universe(
        external_account_id=None,
        watchlist_id=None,
        mode=ExecutionMode.PAPER,
    )

    target = next(row for row in response.rows if row.symbol == "TARGET.US")
    assert target.next_event is target_event
    assert service.market_events.list_events.call_args.kwargs["symbols"]
    assert service.market_events.list_events.call_args.kwargs["limit"] is None


def test_technicals_isolates_symbol_failure_and_history_uses_range_count() -> None:
    market_data = Mock()

    def get_bars(symbol, *, count, mode):
        if symbol == "BAD.US":
            raise RuntimeError("market data down")
        return _bars(count, symbol=symbol)

    market_data.get_recent_daily_bars.side_effect = get_bars
    service = _service(market_data=market_data)

    technicals = service.get_technicals(
        symbols=[" qqq.us ", "BAD.US"],
        mode=ExecutionMode.PAPER,
    )
    history = service.get_history(
        symbol="qqq.us",
        range_name="6m",
        mode=ExecutionMode.PAPER,
    )

    assert [result.status for result in technicals.results] == ["ok", "unavailable"]
    assert technicals.results[1].warning == "daily_bars_unavailable"
    assert len(history.bars) == 132
    assert history.bars[18].sma20 is None
    assert history.bars[19].sma20 is not None
    assert market_data.get_recent_daily_bars.call_args_list[-1].kwargs["count"] == 132


def test_research_api_enforces_batch_limit_and_explicit_universe_error() -> None:
    service = Mock()
    service.get_universe.side_effect = ResearchUniverseLimitError(51)
    app.dependency_overrides[get_research_workspace_service] = lambda: service
    client = TestClient(app)
    try:
        universe_response = client.get("/research/universe")
        params = [("symbols", f"SYM{index}.US") for index in range(11)]
        technicals_response = client.get("/research/technicals", params=params)
    finally:
        app.dependency_overrides.clear()

    assert universe_response.status_code == 422
    assert universe_response.json()["detail"] == {
        "code": "research_universe_limit_exceeded",
        "limit": 50,
        "count": 51,
    }
    assert technicals_response.status_code == 422
    assert technicals_response.json()["detail"]["code"] == "research_technicals_limit_exceeded"
    service.get_technicals.assert_not_called()


def test_research_api_expands_comma_separated_and_repeated_symbols() -> None:
    service = Mock()
    service.get_technicals.return_value = ResearchTechnicalsResponse(mode=ExecutionMode.PAPER)
    app.dependency_overrides[get_research_workspace_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/research/technicals",
            params=[("symbols", "qqq.us, smh.us"), ("symbols", "SOXL.US")],
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert service.get_technicals.call_args.kwargs == {
        "symbols": ["qqq.us", "smh.us", "SOXL.US"],
        "mode": ExecutionMode.PAPER,
    }

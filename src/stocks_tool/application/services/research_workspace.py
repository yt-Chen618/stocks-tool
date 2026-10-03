from __future__ import annotations

import math
import statistics
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import ExecutionMode, SpreadStatus
from stocks_tool.domain.models import (
    HistoricalPriceBar,
    ResearchHistoryPoint,
    ResearchHistoryResponse,
    ResearchTechnicalSnapshot,
    ResearchTechnicalsResponse,
    ResearchUniverseResponse,
    ResearchUniverseRow,
)
from stocks_tool.ports.broker_gateway import BrokerMarketDataGateway
from stocks_tool.ports.repository import (
    AccountSnapshotRepository,
    BullPutSpreadRepository,
    MarketEventRepository,
    StrategyExperimentRepository,
    WatchlistRepository,
)


RESEARCH_UNIVERSE_LIMIT = 50
RESEARCH_TECHNICALS_LIMIT = 10
HISTORY_BAR_COUNTS = {"3m": 66, "6m": 132, "1y": 252}
RESEARCH_ACTIVE_SPREAD_STATUSES = {
    SpreadStatus.ENTRY_PENDING_LONG,
    SpreadStatus.ENTRY_PENDING_SHORT,
    SpreadStatus.OPEN,
    SpreadStatus.EXIT_PENDING_SHORT,
    SpreadStatus.EXIT_PENDING_LONG,
    SpreadStatus.ROLLBACK_FAILED,
}


class ResearchWatchlistNotFoundError(ValueError):
    pass


class ResearchUniverseLimitError(ValueError):
    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(f"Research universe contains {count} symbols; maximum is {RESEARCH_UNIVERSE_LIMIT}.")


class ResearchWorkspaceService:
    def __init__(
        self,
        *,
        settings: Settings,
        watchlists: WatchlistRepository,
        account_snapshots: AccountSnapshotRepository,
        market_events: MarketEventRepository,
        bull_put_spreads: BullPutSpreadRepository,
        strategy_experiments: StrategyExperimentRepository,
        market_data: BrokerMarketDataGateway,
    ) -> None:
        self.settings = settings
        self.watchlists = watchlists
        self.account_snapshots = account_snapshots
        self.market_events = market_events
        self.bull_put_spreads = bull_put_spreads
        self.strategy_experiments = strategy_experiments
        self.market_data = market_data

    def get_universe(
        self,
        *,
        external_account_id: str | None,
        watchlist_id: str | None,
        mode: ExecutionMode,
    ) -> ResearchUniverseResponse:
        rows_by_symbol: dict[str, ResearchUniverseRow] = {}
        warnings: list[str] = []

        selected_watchlist = self._select_watchlist(watchlist_id)
        if selected_watchlist is None and watchlist_id is None:
            warnings.append("default_watchlist_unavailable")
        if selected_watchlist is not None:
            watchlist_id = selected_watchlist.id
            watchlist_symbols: set[str] = set()
            for item in selected_watchlist.items:
                raw_symbol = str(item.symbol or "")
                stripped_symbol = raw_symbol.strip()
                symbol = stripped_symbol.upper()
                if not symbol:
                    self._append_unique(warnings, "watchlist_invalid_symbol")
                    continue
                if raw_symbol != stripped_symbol:
                    self._append_unique(warnings, "watchlist_symbol_normalized")
                if symbol in watchlist_symbols:
                    self._append_unique(warnings, "watchlist_duplicate_symbol")
                watchlist_symbols.add(symbol)
                row = self._row(rows_by_symbol, symbol)
                row.asset_type = item.asset_type
                row.notes = item.notes
                self._append_unique(row.sources, "watchlist")

        if external_account_id:
            snapshot = self.account_snapshots.get_latest_account_snapshot(
                external_account_id=external_account_id,
                mode=mode,
                trusted_only=True,
            )
            if snapshot is None:
                warnings.append("account_snapshot_unavailable")
            else:
                for position in snapshot.positions:
                    row = self._row(rows_by_symbol, position.symbol)
                    row.asset_type = row.asset_type or position.asset_type
                    row.position_quantity = position.quantity
                    row.position_market_value = position.market_value
                    self._append_unique(row.sources, "position")

        bull_put_symbols = {
            self._normalize_symbol(symbol) for symbol in self.settings.bull_put_strategy.symbols
        }
        zero_dte_symbols = {
            self._normalize_symbol(symbol) for symbol in self.settings.zero_dte_lottery_strategy.symbols
        }
        for symbol in sorted(bull_put_symbols):
            row = self._row(rows_by_symbol, symbol)
            self._append_unique(row.sources, "bull_put")
            self._append_unique(row.strategy_states, "bull_put:configured")
        for symbol in sorted(zero_dte_symbols):
            row = self._row(rows_by_symbol, symbol)
            self._append_unique(row.sources, "zero_dte")
            self._append_unique(row.strategy_states, "zero_dte:preview_only")

        if external_account_id:
            for spread in self.bull_put_spreads.list_spreads(
                external_account_id=external_account_id,
                statuses=RESEARCH_ACTIVE_SPREAD_STATUSES,
                mode=mode,
            ):
                # Keep the invariant at the application boundary as a
                # defense for alternate repositories and test doubles. The
                # SQLAlchemy repository applies the same filter in SQL.
                if spread.status not in RESEARCH_ACTIVE_SPREAD_STATUSES:
                    continue
                row = self._row(rows_by_symbol, spread.underlying_symbol)
                self._append_unique(row.sources, "bull_put_spread")
                self._append_unique(row.strategy_states, f"bull_put:{spread.status.value}")

        if len(rows_by_symbol) > RESEARCH_UNIVERSE_LIMIT:
            raise ResearchUniverseLimitError(len(rows_by_symbol))

        symbols = sorted(rows_by_symbol)
        if external_account_id:
            try:
                proposals = self.strategy_experiments.list_proposals(
                    external_account_id=external_account_id,
                    mode=mode,
                    symbols=symbols,
                    limit=None,
                )
            except Exception:
                proposals = []
                warnings.append("strategy_proposals_unavailable")
            for proposal in proposals:
                if not proposal.symbol or proposal.mode != mode:
                    continue
                symbol = self._normalize_symbol(proposal.symbol)
                row = rows_by_symbol.get(symbol)
                if row is None:
                    continue
                self._append_unique(row.sources, "strategy_proposal")
                self._append_unique(
                    row.strategy_states,
                    f"{proposal.strategy_id}:proposal:{proposal.status.value}",
                )

        now = datetime.now(timezone.utc)
        try:
            events = self.market_events.list_events(
                symbols=symbols,
                start=now,
                end=now + timedelta(days=30),
                limit=None,
            )
        except Exception:
            events = []
            warnings.append("market_events_unavailable")
        global_events = [event for event in events if event.symbol is None]
        for symbol, row in rows_by_symbol.items():
            matching = global_events + [
                event for event in events if event.symbol and self._normalize_symbol(event.symbol) == symbol
            ]
            row.next_event = min(matching, key=lambda event: event.scheduled_at) if matching else None

        quotes = {}
        if symbols:
            try:
                quotes = self.market_data.get_quotes(symbols, mode)
            except Exception:
                warnings.append("batch_quotes_unavailable")
        quotes = {
            self._normalize_symbol(symbol): quote
            for symbol, quote in quotes.items()
            if self._normalize_symbol(symbol) in rows_by_symbol
        }
        for symbol, row in rows_by_symbol.items():
            row.quote = quotes.get(symbol)
            if row.quote is None:
                row.warnings.append("quote_unavailable")
            elif row.quote.warning_code:
                row.warnings.append(row.quote.warning_code)

        return ResearchUniverseResponse(
            mode=mode,
            external_account_id=external_account_id,
            watchlist_id=watchlist_id,
            data_quality=self._universe_data_quality(symbols, quotes),
            rows=list(rows_by_symbol.values()),
            warnings=warnings,
        )

    def get_technicals(
        self,
        *,
        symbols: Iterable[str],
        mode: ExecutionMode,
    ) -> ResearchTechnicalsResponse:
        normalized = self.normalize_symbols(symbols)
        results: list[ResearchTechnicalSnapshot] = []
        for symbol in normalized:
            try:
                bars = self.market_data.get_recent_daily_bars(symbol, count=66, mode=mode)
            except Exception:
                results.append(
                    ResearchTechnicalSnapshot(
                        symbol=symbol,
                        status="unavailable",
                        warning="daily_bars_unavailable",
                    )
                )
                continue
            results.append(calculate_technical_snapshot(symbol, bars))
        return ResearchTechnicalsResponse(mode=mode, results=results)

    def get_history(
        self,
        *,
        symbol: str,
        range_name: str,
        mode: ExecutionMode,
    ) -> ResearchHistoryResponse:
        normalized = self._normalize_symbol(symbol)
        try:
            bars = self.market_data.get_recent_daily_bars(
                normalized,
                count=HISTORY_BAR_COUNTS[range_name],
                mode=mode,
            )
        except Exception:
            return ResearchHistoryResponse(
                symbol=normalized,
                range=range_name,
                mode=mode,
                warnings=["daily_bars_unavailable"],
            )
        ordered = sorted(bars, key=lambda bar: bar.timestamp)
        points: list[ResearchHistoryPoint] = []
        closes: list[Decimal] = []
        for bar in ordered:
            closes.append(bar.close)
            points.append(
                ResearchHistoryPoint(
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    turnover=bar.turnover,
                    sma20=_decimal_mean(closes[-20:]) if len(closes) >= 20 else None,
                    sma50=_decimal_mean(closes[-50:]) if len(closes) >= 50 else None,
                )
            )
        warnings = [] if len(points) == HISTORY_BAR_COUNTS[range_name] else ["short_history"]
        return ResearchHistoryResponse(
            symbol=normalized,
            range=range_name,
            mode=mode,
            bars=points,
            warnings=warnings,
        )

    def _select_watchlist(self, watchlist_id: str | None):
        if watchlist_id:
            watchlist = self.watchlists.get_watchlist(watchlist_id)
            if watchlist is None:
                raise ResearchWatchlistNotFoundError(watchlist_id)
            return watchlist
        return next((watchlist for watchlist in self.watchlists.list_watchlists() if watchlist.is_default), None)

    @classmethod
    def normalize_symbols(cls, symbols: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for symbol in symbols:
            value = cls._normalize_symbol(symbol)
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        return symbol.strip().upper()

    @staticmethod
    def _row(rows: dict[str, ResearchUniverseRow], symbol: str) -> ResearchUniverseRow:
        normalized = ResearchWorkspaceService._normalize_symbol(symbol)
        if normalized not in rows:
            rows[normalized] = ResearchUniverseRow(symbol=normalized, sources=[], strategy_states=[])
        return rows[normalized]

    @staticmethod
    def _append_unique(values: list[str], value: str) -> None:
        if value not in values:
            values.append(value)

    @staticmethod
    def _universe_data_quality(symbols: list[str], quotes: dict[str, object]) -> str:
        if not symbols:
            return "empty"
        if not quotes:
            return "unavailable"
        if len(quotes) < len(symbols):
            return "partial"
        if any(getattr(quote, "data_quality", "live") != "live" for quote in quotes.values()):
            return "degraded"
        return "live"


def calculate_technical_snapshot(
    symbol: str,
    bars: list[HistoricalPriceBar],
) -> ResearchTechnicalSnapshot:
    ordered = sorted(bars, key=lambda bar: bar.timestamp)
    if not ordered:
        return ResearchTechnicalSnapshot(
            symbol=symbol,
            status="unavailable",
            warning="daily_bars_empty",
        )

    closes = [bar.close for bar in ordered]
    latest_close = closes[-1]
    sma20 = _decimal_mean(closes[-20:]) if len(closes) >= 20 else None
    sma50 = _decimal_mean(closes[-50:]) if len(closes) >= 50 else None
    return_20d_pct = _return_pct(latest_close, closes[-21]) if len(closes) >= 21 else None
    return_60d_pct = _return_pct(latest_close, closes[-61]) if len(closes) >= 61 else None

    realized_volatility = None
    if len(closes) >= 21 and all(close > 0 for close in closes[-21:]):
        log_returns = [
            math.log(float(current / previous))
            for previous, current in zip(closes[-21:-1], closes[-20:])
        ]
        if len(log_returns) >= 2:
            realized_volatility = statistics.stdev(log_returns) * math.sqrt(252) * 100

    average_volume = None
    average_turnover = None
    if len(ordered) >= 21:
        complete_bars = ordered[-21:-1]
        average_volume = sum(bar.volume for bar in complete_bars) / len(complete_bars)
        average_turnover = _decimal_mean([bar.turnover for bar in complete_bars])

    missing = []
    if return_20d_pct is None:
        missing.append("return_20d")
    if return_60d_pct is None:
        missing.append("return_60d")
    if sma50 is None:
        missing.append("sma50")
    if realized_volatility is None:
        missing.append("realized_volatility_20d")
    if average_volume is None:
        missing.append("average_20d")

    return ResearchTechnicalSnapshot(
        symbol=symbol,
        status="partial" if missing else "ok",
        warning=f"insufficient_history:{','.join(missing)}" if missing else None,
        latest_bar_at=ordered[-1].timestamp,
        return_20d_pct=return_20d_pct,
        return_60d_pct=return_60d_pct,
        sma20=sma20,
        sma50=sma50,
        close_above_sma20=latest_close > sma20 if sma20 is not None else None,
        sma20_above_sma50=sma20 > sma50 if sma20 is not None and sma50 is not None else None,
        realized_volatility_20d_pct=(
            round(realized_volatility, 6) if realized_volatility is not None else None
        ),
        average_volume_20d=average_volume,
        average_turnover_20d=average_turnover,
    )


def _decimal_mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values))


def _return_pct(current: Decimal, prior: Decimal) -> float | None:
    if prior == 0:
        return None
    return round(float((current / prior - Decimal("1")) * Decimal("100")), 6)

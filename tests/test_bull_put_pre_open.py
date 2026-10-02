from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from stocks_tool.adapters.brokers.longbridge import LongbridgeIntegrationError
from stocks_tool.application.services.bull_put.pre_open import BullPutPreOpenResearch
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import BrokerName
from stocks_tool.domain.models import BrokerAccount, SecurityQuoteSnapshot


class MemoryPreOpenRunRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[str, date, str], object] = {}

    def get_by_session_date(
        self,
        *,
        external_account_id: str,
        target_session_date: date,
        strategy_id: str = "pre_open_put_check_v1",
    ):
        return self.items.get((external_account_id, target_session_date, strategy_id))

    def list_runs(self, *, external_account_id: str | None = None, limit: int = 20):
        rows = [
            run
            for (account_id, _, _), run in self.items.items()
            if external_account_id is None or account_id == external_account_id
        ]
        return sorted(rows, key=lambda run: run.target_session_date, reverse=True)[:limit]

    def upsert_run(self, run):
        self.items[(run.external_account_id, run.target_session_date, run.strategy_id)] = run
        return run


def _quote(symbol: str, last_done: str, prev_close: str) -> SecurityQuoteSnapshot:
    price = Decimal(last_done)
    previous = Decimal(prev_close)
    return SecurityQuoteSnapshot(
        symbol=symbol,
        last_done=price,
        prev_close=previous,
        open=previous,
        high=max(price, previous),
        low=min(price, previous),
        timestamp=datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
        volume=100_000,
        turnover=price * Decimal("100000"),
        trade_status="Normal",
    )


def build_pre_open_research() -> tuple[BullPutPreOpenResearch, Mock, Mock]:
    settings = Settings(_env_file=None)
    account = BrokerAccount(
        id="broker-account-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        display_name="Longbridge Paper",
        base_currency="USD",
        options_level="Level 2",
        is_active=True,
        auto_reconcile_enabled=True,
        created_at=datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc),
    )
    broker_accounts = Mock()
    broker_accounts.get_by_external_account_id.return_value = account
    pre_open_runs = MemoryPreOpenRunRepository()
    adapter = Mock()
    quotes = {
        "SPY.US": _quote("SPY.US", "612", "615"),
        "QQQ.US": _quote("QQQ.US", "500", "504"),
        "SOXX.US": _quote("SOXX.US", "245", "249"),
        "USO.US": _quote("USO.US", "84", "82.5"),
        "TLT.US": _quote("TLT.US", "91.9", "92.8"),
    }
    adapter.get_quotes.side_effect = lambda symbols, mode: {
        symbol: quotes[symbol] for symbol in symbols if symbol in quotes
    }
    adapter.get_quote.side_effect = lambda symbol, mode: quotes[symbol]
    journal_writer = Mock()
    research = BullPutPreOpenResearch(
        settings=settings,
        broker_accounts=broker_accounts,
        pre_open_runs=pre_open_runs,
        longbridge_adapter=adapter,
        journal_writer=journal_writer,
    )
    return research, adapter, journal_writer


def test_pre_open_research_contract_builds_scored_macro_board_without_overlays() -> None:
    research, adapter, _ = build_pre_open_research()

    result = research.get_pre_open_downside_assessment(
        as_of=datetime(2026, 5, 26, 12, 20, tzinfo=timezone.utc),
        include_option_overlays=False,
    )

    assert result.downside_score >= 7
    assert result.regime == "broad_downside_risk"
    assert result.preferred_vehicle == "QQQ"
    assert result.freshness_status == "partial"
    assert result.put_snapshots == []
    assert result.chain_analyses == []
    assert result.checkpoints[0].label == "Macro pulse"
    assert result.checkpoints[0].status == "active"
    assert result.checkpoints[-1].status == "pending"
    adapter.list_option_expiry_dates.assert_not_called()


def test_pre_open_research_contract_persists_and_falls_back_through_injected_adapters() -> None:
    research, adapter, journal_writer = build_pre_open_research()

    captured = research.capture_pre_open_run(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 25, 12, 0, tzinfo=timezone.utc),
    )
    assert captured.captured is True
    assert journal_writer.called

    adapter.get_quotes.side_effect = LongbridgeIntegrationError(
        "Longbridge timed out while trying to load pre-open quotes."
    )
    fallback = research.get_pre_open_downside_assessment(
        external_account_id="LBPT10087357",
        as_of=datetime(2026, 5, 26, 12, 35, tzinfo=timezone.utc),
    )

    assert fallback.freshness_status == "stale"
    assert fallback.source_run_id == captured.run.id

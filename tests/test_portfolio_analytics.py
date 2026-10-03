from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.application.services.portfolio import (
    PortfolioAnalyticsService,
    PortfolioDataQuality,
    PortfolioEvidence,
    PortfolioLinks,
    StrategyExposure,
)
from stocks_tool.db.base import Base
from stocks_tool.db.models import AccountSnapshotRecord, BullPutSpreadRecord
from stocks_tool.db.models import (
    BrokerAccountRecord,
    ExecutionRecord,
    JournalEntryRecord,
    OrderRecord,
    PositionSnapshotRecord,
    StrategyProposalRecord,
    StrategyRunRecord,
)
from stocks_tool.domain.enums import ExecutionMode


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def snapshot(
    *,
    snapshot_id: str = "snapshot-1",
    captured_at: datetime | None = None,
    net_liquidation: str = "10000",
    provenance: str = "broker_sync",
    positions: list[SimpleNamespace] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=snapshot_id,
        captured_at=captured_at or datetime.now(timezone.utc),
        currency="USD",
        cash_balance=Decimal("4000"),
        net_liquidation=Decimal(net_liquidation),
        buying_power=Decimal("5000"),
        day_trade_buying_power=None,
        provenance=provenance,
        positions=positions or [],
    )


def stock_position(symbol: str = "QQQ.US", value: str = "6000") -> SimpleNamespace:
    return SimpleNamespace(
        id=f"position-{symbol}",
        symbol=symbol,
        asset_type="stock",
        quantity=Decimal("10"),
        average_cost=Decimal("500"),
        market_value=Decimal(value),
        unrealized_pnl=Decimal("10"),
        option_underlying_symbol=None,
        option_expiration_date=None,
        option_strike=None,
        option_right=None,
    )


def service() -> PortfolioAnalyticsService:
    return PortfolioAnalyticsService(Mock())


@pytest.fixture()
def sqlite_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            BrokerAccountRecord.__table__,
            AccountSnapshotRecord.__table__,
            PositionSnapshotRecord.__table__,
            BullPutSpreadRecord.__table__,
            StrategyProposalRecord.__table__,
            StrategyRunRecord.__table__,
            OrderRecord.__table__,
            ExecutionRecord.__table__,
            JournalEntryRecord.__table__,
        ],
    )
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def persisted_snapshot(
    *,
    account_id: str,
    mode: str | None,
    captured_at: datetime,
    value: str,
    currency: str = "USD",
    provenance: str = "broker_sync",
) -> AccountSnapshotRecord:
    return AccountSnapshotRecord(
        id=str(uuid4()),
        broker="longbridge",
        external_account_id=account_id,
        execution_mode=mode,
        provenance=provenance,
        currency=currency,
        cash_balance=Decimal(value),
        net_liquidation=Decimal(value),
        buying_power=Decimal(value),
        captured_at=captured_at,
    )


def test_analytics_exposes_nav_change_without_fabricating_investment_return() -> None:
    now = datetime.now(timezone.utc)
    first = snapshot(snapshot_id="first", captured_at=now - timedelta(days=1), net_liquidation="10000")
    last = snapshot(snapshot_id="last", captured_at=now, net_liquidation="11000")
    instance = service()
    instance._load_snapshots = Mock(
        return_value=(
            [first, last],
            2,
            2,
            PortfolioDataQuality(mode_scope_verified=True),
        )
    )
    instance._strategy_exposures = Mock(return_value=[])
    instance._activity_links = Mock(return_value=PortfolioLinks())
    instance._load_latest_snapshot = Mock(return_value=last)

    result = instance.get_analytics(external_account_id="LBPT10087357")

    assert result.change.net_liquidation_change == Decimal("1000")
    assert result.change.investment_return is None
    assert result.change.investment_return_unavailable.code == "cash_flow_history_unavailable"
    assert any(item.code == "fee_history_unavailable" for item in result.data_quality.unavailable)


def test_risk_returns_empty_read_model_when_account_snapshot_is_missing() -> None:
    instance = service()
    instance._load_latest_snapshot = Mock(return_value=None)
    instance._legacy_unscoped_snapshot_count = Mock(return_value=0)
    instance._strategy_exposures = Mock(return_value=[])
    instance._covered_share_reservations = Mock(return_value=([], []))
    instance._activity_links = Mock(return_value=PortfolioLinks())

    result = instance.get_risk(external_account_id="LBPT10087357", mode=ExecutionMode.PAPER)

    assert result.balance is None
    assert result.as_of is None
    assert result.data_quality.unavailable[0].code == "account_snapshot_unavailable"


def test_negative_nav_does_not_create_concentration_weight() -> None:
    record = snapshot(
        net_liquidation="-100",
        positions=[stock_position(value="500")],
    )
    instance = service()
    instance._load_latest_snapshot = Mock(return_value=record)
    instance._legacy_unscoped_snapshot_count = Mock(return_value=0)
    instance._strategy_exposures = Mock(return_value=[])
    instance._covered_share_reservations = Mock(return_value=([], []))
    instance._activity_links = Mock(return_value=PortfolioLinks())

    result = instance.get_risk(external_account_id="LBPT10087357")

    assert result.concentrations[0].weight_of_net_liquidation is None
    assert result.concentrations[0].risk_level == "unknown"
    assert result.concentrations[0].weight_unavailable.code == "non_positive_net_liquidation"


def bull_put_exposure(max_loss: str = "500") -> StrategyExposure:
    return StrategyExposure(
        strategy_id="paper_bull_put_v1",
        label="Bull Put spread",
        symbol="QQQ.US",
        known_max_loss=Decimal(max_loss),
        status="open",
    )


def test_known_bull_put_loss_ratio_requires_positive_usd_nav() -> None:
    record = snapshot(net_liquidation="-100", positions=[])
    instance = service()
    instance._load_latest_snapshot = Mock(return_value=record)
    instance._legacy_unscoped_snapshot_count = Mock(return_value=0)
    instance._strategy_exposures = Mock(return_value=[bull_put_exposure()])
    instance._covered_share_reservations = Mock(return_value=([], []))
    instance._activity_links = Mock(return_value=PortfolioLinks())

    result = instance.get_risk(external_account_id="LBPT10087357")

    assert result.known_max_loss.loss_currency == "USD"
    assert result.known_max_loss.nav_currency == "USD"
    assert result.known_max_loss.nav_ratio_pct is None
    assert result.known_max_loss.nav_ratio_unavailable.code == "nav_ratio_non_positive_or_unavailable"


def test_known_bull_put_loss_ratio_is_not_calculated_across_currency() -> None:
    record = snapshot(net_liquidation="10000", positions=[])
    record.currency = "HKD"
    instance = service()
    instance._load_latest_snapshot = Mock(return_value=record)
    instance._legacy_unscoped_snapshot_count = Mock(return_value=0)
    instance._strategy_exposures = Mock(return_value=[bull_put_exposure()])
    instance._covered_share_reservations = Mock(return_value=([], []))
    instance._activity_links = Mock(return_value=PortfolioLinks())

    result = instance.get_risk(external_account_id="LBPT10087357")

    assert result.known_max_loss.loss_currency == "USD"
    assert result.known_max_loss.nav_currency == "HKD"
    assert result.known_max_loss.nav_ratio_pct is None
    assert result.known_max_loss.nav_ratio_unavailable.code == "nav_currency_mismatch"


def test_known_bull_put_loss_ratio_is_unavailable_for_unknown_nav_currency() -> None:
    record = snapshot(net_liquidation="10000", positions=[])
    record.currency = ""
    instance = service()
    instance._load_latest_snapshot = Mock(return_value=record)
    instance._legacy_unscoped_snapshot_count = Mock(return_value=0)
    instance._strategy_exposures = Mock(return_value=[bull_put_exposure()])
    instance._covered_share_reservations = Mock(return_value=([], []))
    instance._activity_links = Mock(return_value=PortfolioLinks())

    result = instance.get_risk(external_account_id="LBPT10087357")

    assert result.known_max_loss.nav_currency is None
    assert result.known_max_loss.nav_ratio_pct is None
    assert result.known_max_loss.nav_ratio_unavailable.code == "nav_currency_unavailable"


def test_known_bull_put_loss_ratio_is_computed_once_by_backend() -> None:
    record = snapshot(net_liquidation="10000", positions=[])
    instance = service()
    instance._load_latest_snapshot = Mock(return_value=record)
    instance._legacy_unscoped_snapshot_count = Mock(return_value=0)
    instance._strategy_exposures = Mock(return_value=[bull_put_exposure("500")])
    instance._covered_share_reservations = Mock(return_value=([], []))
    instance._activity_links = Mock(return_value=PortfolioLinks())

    result = instance.get_risk(external_account_id="LBPT10087357")

    assert result.known_max_loss.loss_currency == "USD"
    assert result.known_max_loss.nav_currency == "USD"
    assert result.known_max_loss.nav_ratio_pct == Decimal("5.00")
    assert result.known_max_loss.nav_ratio_unavailable is None


def test_stale_snapshot_is_visible_as_a_warning() -> None:
    record = snapshot(captured_at=datetime.now(timezone.utc) - timedelta(days=2))
    instance = service()
    instance._load_latest_snapshot = Mock(return_value=record)
    instance._legacy_unscoped_snapshot_count = Mock(return_value=0)
    instance._strategy_exposures = Mock(return_value=[])
    instance._covered_share_reservations = Mock(return_value=([], []))
    instance._activity_links = Mock(return_value=PortfolioLinks())

    result = instance.get_risk(external_account_id="LBPT10087357")

    assert result.balance.stale is True
    assert "snapshot_stale" in result.data_quality.warnings


def test_mode_filter_is_present_and_option_metadata_is_not_dropped() -> None:
    instance = service()
    filters = instance._snapshot_filters("LBPT10087357", ExecutionMode.LIVE)
    assert "execution_mode" in str(filters[1])

    multiplier, units, unavailable = instance._option_contract_metadata(
        SimpleNamespace(quantity=Decimal("2")),
        symbol="QQQ260116C00500000.US",
        asset_type="option",
    )
    assert multiplier == Decimal("100")
    assert units == Decimal("200")
    assert unavailable is None

    unknown = instance._option_contract_metadata(
        SimpleNamespace(quantity=Decimal("2")),
        symbol="UNKNOWN_OPTION",
        asset_type="option",
    )
    assert unknown[0] is None
    assert unknown[1] is None
    assert unknown[2].code == "option_contract_metadata_unavailable"


def test_partial_history_remains_explicitly_bounded() -> None:
    now = datetime.now(timezone.utc)
    first = snapshot(snapshot_id="first", captured_at=now - timedelta(days=10))
    last = snapshot(snapshot_id="last", captured_at=now)
    instance = service()
    instance._load_snapshots = Mock(
        return_value=(
            [first, last],
            10001,
            10001,
            PortfolioDataQuality(
                snapshot_count=10001,
                snapshot_count_in_range=10001,
                chart_downsampled=True,
                warnings=["snapshot_history_bounded"],
                mode_scope_verified=True,
            ),
        )
    )
    instance._strategy_exposures = Mock(return_value=[])
    instance._activity_links = Mock(return_value=PortfolioLinks())
    instance._load_latest_snapshot = Mock(return_value=last)

    result = instance.get_analytics(external_account_id="LBPT10087357")

    assert result.data_quality.chart_downsampled is True
    assert "snapshot_history_bounded" in result.data_quality.warnings
    assert len(result.series) == 2


def test_sql_sampling_preserves_true_first_middle_last_and_latest_positions(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(10_005):
        value = "10000"
        if index == 5_002:
            value = "20000"
        if index == 10_004:
            value = "30000"
        rows.append(
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=start + timedelta(minutes=index),
                value=value,
            )
        )
    sqlite_session.add_all(rows)
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_analytics(
        external_account_id=account_id,
        max_points=3,
    )

    assert result.data_quality.snapshot_count == 10_005
    assert result.data_quality.snapshot_count_in_range == 10_005
    assert [point.net_liquidation for point in result.series] == [
        Decimal("10000"),
        Decimal("20000"),
        Decimal("30000"),
    ]
    assert result.latest.net_liquidation == Decimal("30000")
    assert result.series[-1].position_market_value == Decimal("0")


def test_sql_mode_and_provenance_scope_is_explicit(sqlite_session: Session) -> None:
    account_id = "LBPT10087357"
    now = datetime.now(timezone.utc)
    sqlite_session.add_all(
        [
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now - timedelta(minutes=2),
                value="10000",
            ),
            persisted_snapshot(
                account_id=account_id,
                mode="live",
                captured_at=now - timedelta(minutes=1),
                value="90000",
            ),
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now,
                value="11000",
                provenance="legacy_unknown",
            ),
        ]
    )
    sqlite_session.commit()

    paper = PortfolioAnalyticsService(sqlite_session).get_analytics(
        external_account_id=account_id,
        mode=ExecutionMode.PAPER,
    )
    live = PortfolioAnalyticsService(sqlite_session).get_analytics(
        external_account_id=account_id,
        mode=ExecutionMode.LIVE,
    )

    assert paper.data_quality.snapshot_count == 2
    assert paper.latest.net_liquidation == Decimal("11000")
    assert paper.data_quality.provenance_verified is False
    assert any(item.code == "snapshot_provenance_unavailable" for item in paper.data_quality.unavailable)
    assert live.data_quality.snapshot_count == 1
    assert live.latest.net_liquidation == Decimal("90000")


def test_sql_provenance_coverage_includes_older_unknown_rows(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    now = datetime.now(timezone.utc)
    sqlite_session.add_all(
        [
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now - timedelta(days=2),
                value="10000",
                provenance="legacy_unknown",
            ),
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now,
                value="11000",
                provenance="broker_sync",
            ),
        ]
    )
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_analytics(
        external_account_id=account_id,
    )

    assert result.data_quality.provenance_verified is False
    assert result.data_quality.provenance_counts == {"legacy_unknown": 1, "broker_sync": 1}
    assert result.data_quality.provenance_complete is False
    assert any(item.code == "snapshot_provenance_partial" for item in result.data_quality.unavailable)
    assert result.series[0].provenance == "legacy_unknown"
    assert result.series[-1].provenance == "broker_sync"


def test_sql_legacy_mode_rows_are_retained_but_excluded_from_paper_scope(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    now = datetime.now(timezone.utc)
    sqlite_session.add(
        persisted_snapshot(
            account_id=account_id,
            mode=None,
            captured_at=now,
            value="99999",
            provenance="legacy_unknown",
        )
    )
    sqlite_session.commit()

    analytics = PortfolioAnalyticsService(sqlite_session).get_analytics(
        external_account_id=account_id,
        mode=ExecutionMode.PAPER,
    )
    risk = PortfolioAnalyticsService(sqlite_session).get_risk(
        external_account_id=account_id,
        mode=ExecutionMode.PAPER,
    )

    assert analytics.latest is None
    assert analytics.data_quality.snapshot_count == 0
    assert analytics.data_quality.legacy_unscoped_snapshot_count == 1
    assert "snapshot_mode_unknown" in analytics.data_quality.warnings
    assert any(item.code == "snapshot_mode_unknown" for item in analytics.data_quality.unavailable)
    assert risk.balance is None
    assert risk.data_quality.legacy_unscoped_snapshot_count == 1
    assert any(item.code == "snapshot_mode_unknown" for item in risk.data_quality.unavailable)


def test_sql_paper_and_legacy_rows_do_not_mix_or_claim_zero_nav(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    now = datetime.now(timezone.utc)
    sqlite_session.add_all(
        [
            persisted_snapshot(
                account_id=account_id,
                mode=None,
                captured_at=now - timedelta(days=1),
                value="99999",
                provenance="legacy_unknown",
            ),
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now,
                value="10000",
            ),
        ]
    )
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_risk(
        external_account_id=account_id,
        mode=ExecutionMode.PAPER,
    )

    assert result.balance.net_liquidation == Decimal("10000")
    assert result.data_quality.legacy_unscoped_snapshot_count == 1
    assert result.known_max_loss.total is None
    assert result.known_max_loss.unavailable.code == "bull_put_no_active_exposure"


def test_sql_blank_currency_blocks_nav_change_and_marks_point_unknown(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    now = datetime.now(timezone.utc)
    sqlite_session.add_all(
        [
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now - timedelta(days=1),
                value="10000",
                currency="",
            ),
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now,
                value="11000",
                currency="",
            ),
        ]
    )
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_analytics(
        external_account_id=account_id,
    )

    assert result.change.net_liquidation_change is None
    assert result.change.investment_return_unavailable.code == "currency_unavailable"
    assert [point.currency for point in result.series] == [None, None]
    assert "currency_unavailable" in result.data_quality.warnings


def test_sql_invalid_covered_shares_are_explicitly_unavailable(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    now = datetime.now(timezone.utc)
    sqlite_session.add(
        persisted_snapshot(
            account_id=account_id,
            mode="paper",
            captured_at=now,
            value="10000",
        )
    )
    sqlite_session.add(
        StrategyProposalRecord(
            id="proposal-invalid-covered-shares",
            strategy_id="covered_call_v1",
            external_account_id=account_id,
            execution_mode="paper",
            title="Invalid coverage fixture",
            proposed_action="sell_covered_call",
            rationale="Fixture with missing covered share count.",
            status="pending",
            candidate_payload={"underlying_symbol": "QQQ.US", "call_symbol": "QQQ260116C00500000.US"},
        )
    )
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_risk(
        external_account_id=account_id,
    )

    reservation = result.covered_share_reservations[0]
    assert reservation.reserved_shares is None
    assert any(item.code == "covered_call_shares_unavailable" for item in reservation.unavailable)
    assert any(item.code == "covered_call_shares_unavailable" for item in result.covered_share_groups[0].unavailable)


def test_sql_risk_keeps_persisted_strategy_components_without_snapshot(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    sqlite_session.add(
        BullPutSpreadRecord(
            id="spread-without-snapshot",
            broker="longbridge",
            external_account_id=account_id,
            strategy_id="paper_bull_put_v1",
            execution_mode="paper",
            underlying_symbol="QQQ.US",
            expiration_date=date(2026, 12, 18),
            contracts=1,
            width=Decimal("5"),
            long_symbol="QQQ260000P00400000.US",
            long_strike=Decimal("400"),
            short_symbol="QQQ260000P00405000.US",
            short_strike=Decimal("405"),
            status="open",
            max_loss=Decimal("300"),
        )
    )
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_risk(
        external_account_id=account_id,
    )

    assert result.balance is None
    assert any(item.code == "concentration_unavailable" for item in result.data_quality.unavailable)
    assert len(result.strategy_exposures) == 1
    assert result.known_max_loss.scope == "bull_put"
    assert result.known_max_loss.total == Decimal("300")


def test_sql_orderless_journal_is_exposed_as_unscoped(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    sqlite_session.add(
        JournalEntryRecord(
            id="journal-orderless",
            external_account_id=account_id,
            symbol="QQQ.US",
            entry_type="note",
            title="Unscoped fixture",
            notes="No order or execution mode is linked.",
        )
    )
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_analytics(
        external_account_id=account_id,
    )

    assert result.links.journals == []
    assert result.links.journal_ids_unscoped == ["journal-orderless"]
    assert any(item.code == "journal_mode_unavailable" for item in result.links.unavailable)
    assert any(item.code == "journal_mode_unavailable" for item in result.data_quality.unavailable)


def test_sql_risk_marks_active_strategy_overflow_and_keeps_aggregate_explicit(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    now = datetime.now(timezone.utc)
    sqlite_session.add(
        persisted_snapshot(
            account_id=account_id,
            mode="paper",
            captured_at=now,
            value="10000",
        )
    )
    for index, max_loss in enumerate(("100", "200", "300")):
        sqlite_session.add(
            BullPutSpreadRecord(
                id=f"spread-{index}",
                broker="longbridge",
                external_account_id=account_id,
                strategy_id="paper_bull_put_v1",
                execution_mode="paper",
                underlying_symbol="QQQ.US",
                expiration_date=date(2026, 12, 18),
                contracts=1,
                width=Decimal("5"),
                long_symbol="QQQ260000P00400000.US",
                long_strike=Decimal("400"),
                short_symbol="QQQ260000P00405000.US",
                short_strike=Decimal("405"),
                status="open",
                max_loss=Decimal(max_loss),
            )
        )
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_risk(
        external_account_id=account_id,
        max_items=1,
    )

    assert len(result.strategy_exposures) == 1
    assert result.known_max_loss.total == Decimal("600")
    assert result.known_max_loss.unavailable.code == "active_risk_components_bounded"
    assert "active_risk_components_bounded" in result.data_quality.warnings


def test_sql_mixed_currency_history_does_not_calculate_cross_currency_nav_change(
    sqlite_session: Session,
) -> None:
    account_id = "LBPT10087357"
    now = datetime.now(timezone.utc)
    sqlite_session.add_all(
        [
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now - timedelta(days=1),
                value="10000",
                currency="USD",
            ),
            persisted_snapshot(
                account_id=account_id,
                mode="paper",
                captured_at=now,
                value="9000",
                currency="EUR",
            ),
        ]
    )
    sqlite_session.commit()

    result = PortfolioAnalyticsService(sqlite_session).get_analytics(
        external_account_id=account_id,
    )

    assert result.change.net_liquidation_change is None
    assert result.change.investment_return is None
    assert result.change.investment_return_unavailable.code == "mixed_currency_history"
    assert [point.currency for point in result.series] == ["USD", "EUR"]
    assert "mixed_currency_history" in result.data_quality.warnings


def test_historical_risk_is_rejected_without_point_in_time_strategy_records() -> None:
    with pytest.raises(ValueError, match="Historical portfolio risk"):
        service().get_risk(
            external_account_id="LBPT10087357",
            as_of=datetime.now(timezone.utc),
        )

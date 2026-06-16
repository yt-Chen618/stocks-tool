from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.application.services.covered_call.candidate import (
    build_candidate,
    build_risk_summary,
    days_to_expiration,
    monitor_action,
    proposal_confidence,
    quote_mid,
    safe_pct,
)
from stocks_tool.domain.enums import AssetType, BrokerName, ExecutionMode, OptionRight, RiskStatus
from stocks_tool.domain.models import (
    CoveredCallPreviewResult,
    OptionMarketSnapshot,
    PositionSnapshot,
)


NOW = datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc)
NY = ZoneInfo("America/New_York")


def _position(**updates) -> PositionSnapshot:
    base = PositionSnapshot(
        symbol="UNH.US",
        asset_type=AssetType.STOCK,
        quantity=Decimal("150"),
        average_cost=Decimal("410"),
        market_value=Decimal("61500"),
        unrealized_pnl=Decimal("1000"),
    )
    return base.model_copy(update=updates)


def _quote(**updates) -> OptionMarketSnapshot:
    base = OptionMarketSnapshot(
        symbol="UNH260717C430000.US",
        underlying_symbol="UNH.US",
        expiration_date=date(2026, 7, 17),
        strike=Decimal("430"),
        right=OptionRight.CALL,
        last_done=Decimal("4.10"),
        prev_close=Decimal("3.95"),
        open=Decimal("4.00"),
        high=Decimal("4.30"),
        low=Decimal("3.80"),
        timestamp=NOW,
        volume=200,
        turnover=Decimal("120000"),
        bid=Decimal("4.00"),
        ask=Decimal("4.20"),
        open_interest=800,
        delta=Decimal("0.25"),
    )
    return base.model_copy(update=updates)


def test_build_candidate_computes_income_and_return_metrics() -> None:
    candidate = build_candidate(
        position=_position(),
        quote=_quote(),
        underlying_price=Decimal("415"),
        contracts=1,
        evaluated_at=NOW,
        market_timezone=NY,
    )

    assert candidate.underlying_symbol == "UNH.US"
    assert candidate.covered_shares == 100
    assert candidate.call_mid == Decimal("4.10")
    assert candidate.premium_income == Decimal("400.00")
    assert candidate.if_called_return_pct == Decimal("5.85")
    assert candidate.annualized_income_yield == Decimal("10.95")


def test_build_risk_summary_warns_for_uncovered_shares_and_below_cost_strike() -> None:
    candidate = build_candidate(
        position=_position(),
        quote=_quote(strike=Decimal("405")),
        underlying_price=Decimal("415"),
        contracts=1,
        evaluated_at=NOW,
        market_timezone=NY,
    )

    risk = build_risk_summary(position=_position(), candidate=candidate)

    assert risk.status == RiskStatus.WARN
    assert risk.shares_not_covered == Decimal("50")
    assert any("below the current average cost" in warning for warning in risk.warnings)
    assert any("shares remain uncovered" in warning for warning in risk.warnings)
    assert risk.max_income == Decimal("400.00")
    assert risk.break_even == Decimal("406.00")


def test_monitor_action_prioritizes_take_profit_then_assignment_pressure() -> None:
    candidate = build_candidate(
        position=_position(quantity=Decimal("100")),
        quote=_quote(strike=Decimal("430")),
        underlying_price=Decimal("415"),
        contracts=1,
        evaluated_at=NOW,
        market_timezone=NY,
    )

    action, reasons = monitor_action(
        candidate=candidate,
        underlying_price=Decimal("420"),
        premium_capture_pct=Decimal("50"),
        days_to_expiration=20,
    )
    assert action == "consider_buyback_take_profit"
    assert reasons

    action, _ = monitor_action(
        candidate=candidate,
        underlying_price=Decimal("430"),
        premium_capture_pct=None,
        days_to_expiration=20,
    )
    assert action == "assignment_or_roll_review"


def test_proposal_confidence_uses_risk_and_liquidity() -> None:
    candidate = build_candidate(
        position=_position(quantity=Decimal("100")),
        quote=_quote(open_interest=800),
        underlying_price=Decimal("415"),
        contracts=1,
        evaluated_at=NOW,
        market_timezone=NY,
    )
    risk = build_risk_summary(position=_position(quantity=Decimal("100")), candidate=candidate)

    preview = CoveredCallPreviewResult(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        evaluated_at=NOW,
        eligible=True,
        candidate=candidate,
        risk=risk,
    )

    assert proposal_confidence(preview) == Decimal("0.68")


def test_small_calculation_helpers_are_stable() -> None:
    assert quote_mid(_quote(bid=Decimal("1.00"), ask=Decimal("1.10"))) == Decimal("1.05")
    assert safe_pct(Decimal("5"), Decimal("100")) == Decimal("5.00")
    assert days_to_expiration(
        expiry_date=date(2026, 7, 17),
        evaluated_at=NOW,
        market_timezone=NY,
    ) == 32

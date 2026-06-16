from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from stocks_tool.domain.enums import RiskStatus
from stocks_tool.domain.models import (
    CoveredCallCandidate,
    CoveredCallPreviewResult,
    CoveredCallRiskSummary,
    OptionMarketSnapshot,
    PositionSnapshot,
)


def days_to_expiration(
    *,
    expiry_date: date,
    evaluated_at: datetime,
    market_timezone: ZoneInfo,
) -> int:
    evaluated_date = evaluated_at.astimezone(market_timezone).date()
    return (expiry_date - evaluated_date).days


def quote_mid(quote: OptionMarketSnapshot) -> Decimal:
    if quote.bid is not None and quote.ask is not None:
        return ((quote.bid + quote.ask) / Decimal("2")).quantize(Decimal("0.01"))
    if quote.bid is not None:
        return quote.bid.quantize(Decimal("0.01"))
    if quote.ask is not None:
        return quote.ask.quantize(Decimal("0.01"))
    return Decimal("0")


def safe_pct(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return ((numerator / denominator) * Decimal("100")).quantize(Decimal("0.01"))


def annualize_income_yield(
    *,
    income_yield: Decimal | None,
    expiration_date: date,
    evaluated_at: datetime,
    market_timezone: ZoneInfo,
) -> Decimal | None:
    if income_yield is None:
        return None
    days = days_to_expiration(
        expiry_date=expiration_date,
        evaluated_at=evaluated_at,
        market_timezone=market_timezone,
    )
    if days <= 0:
        return None
    return ((income_yield / Decimal(days)) * Decimal("365")).quantize(Decimal("0.01"))


def build_candidate(
    *,
    position: PositionSnapshot,
    quote: OptionMarketSnapshot,
    underlying_price: Decimal,
    contracts: int,
    evaluated_at: datetime,
    market_timezone: ZoneInfo,
) -> CoveredCallCandidate:
    covered_shares = contracts * 100
    call_mid = quote_mid(quote)
    premium_income = (quote.bid or Decimal("0")) * Decimal(covered_shares)
    cost_basis = position.average_cost * Decimal(covered_shares)
    income_yield = safe_pct(premium_income, underlying_price * Decimal(covered_shares))
    assignment_profit = ((quote.strike - position.average_cost) * Decimal(covered_shares)) + premium_income
    if_called_return = safe_pct(assignment_profit, cost_basis)
    return CoveredCallCandidate(
        underlying_symbol=position.symbol.upper(),
        expiration_date=quote.expiration_date,
        days_to_expiration=days_to_expiration(
            expiry_date=quote.expiration_date,
            evaluated_at=evaluated_at,
            market_timezone=market_timezone,
        ),
        contracts=contracts,
        covered_shares=covered_shares,
        share_quantity=position.quantity,
        average_cost=position.average_cost,
        underlying_price=underlying_price,
        call_symbol=quote.symbol,
        call_strike=quote.strike,
        call_bid=quote.bid or Decimal("0"),
        call_ask=quote.ask or Decimal("0"),
        call_mid=call_mid,
        premium_income=premium_income.quantize(Decimal("0.01")),
        annualized_income_yield=annualize_income_yield(
            income_yield=income_yield,
            expiration_date=quote.expiration_date,
            evaluated_at=evaluated_at,
            market_timezone=market_timezone,
        ),
        if_called_return_pct=if_called_return,
        delta=quote.delta,
        open_interest=quote.open_interest,
        volume=quote.volume,
        quote_timestamp=quote.timestamp,
    )


def build_risk_summary(
    *,
    position: PositionSnapshot,
    candidate: CoveredCallCandidate,
) -> CoveredCallRiskSummary:
    warnings: list[str] = []
    if candidate.call_strike < position.average_cost:
        warnings.append("Selected call strike is below the current average cost and may lock in a realized loss if assigned.")
    shares_not_covered = position.quantity - Decimal(candidate.covered_shares)
    if shares_not_covered > 0:
        warnings.append(f"{shares_not_covered} shares remain uncovered by this one-contract proposal.")

    assignment_profit = (
        (candidate.call_strike - position.average_cost) * Decimal(candidate.covered_shares)
    ) + candidate.premium_income
    max_loss_if_zero = (position.average_cost * Decimal(candidate.covered_shares)) - candidate.premium_income
    break_even = position.average_cost - (candidate.premium_income / Decimal(candidate.covered_shares))
    return CoveredCallRiskSummary(
        status=RiskStatus.WARN if warnings else RiskStatus.PASS,
        warnings=warnings,
        max_income=candidate.premium_income,
        max_assignment_profit=assignment_profit.quantize(Decimal("0.01")),
        max_loss_if_zero=max_loss_if_zero.quantize(Decimal("0.01")),
        break_even=break_even.quantize(Decimal("0.01")),
        shares_not_covered=shares_not_covered,
    )


def monitor_action(
    *,
    candidate: CoveredCallCandidate,
    underlying_price: Decimal,
    premium_capture_pct: Decimal | None,
    days_to_expiration: int,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if premium_capture_pct is not None and premium_capture_pct >= Decimal("50"):
        reasons.append("At least 50% of the original premium is captured.")
        return "consider_buyback_take_profit", reasons
    if underlying_price >= candidate.call_strike:
        reasons.append("Underlying is trading at or above the short call strike.")
        return "assignment_or_roll_review", reasons
    if underlying_price >= candidate.call_strike * Decimal("0.995"):
        reasons.append("Underlying is within 0.5% of the short call strike.")
        return "watch_assignment_pressure", reasons
    if days_to_expiration <= 7:
        reasons.append("Covered call is inside the final 7 DTE management window.")
        return "expiration_week_review", reasons
    reasons.append("No take-profit, assignment-pressure, or expiration-week trigger is active.")
    return "hold", reasons


def proposal_confidence(preview: CoveredCallPreviewResult) -> Decimal:
    if preview.candidate is None or preview.risk is None:
        return Decimal("0")
    confidence = Decimal("0.60")
    if preview.risk.status == RiskStatus.PASS:
        confidence += Decimal("0.05")
    if preview.candidate.open_interest and preview.candidate.open_interest >= 500:
        confidence += Decimal("0.03")
    return min(confidence, Decimal("0.75"))

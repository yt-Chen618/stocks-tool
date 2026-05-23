from decimal import Decimal

from stocks_tool.core.config import BullPutSpreadStrategySettings, Settings
from stocks_tool.domain.enums import AssetType, ExecutionMode, RiskStatus
from stocks_tool.domain.models import (
    AccountSnapshot,
    BullPutSpreadCandidate,
    BullPutSpreadRiskSummary,
    RiskCheckResult,
    TradePlan,
)


class RiskService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate_trade_plan(
        self,
        plan: TradePlan,
        account: AccountSnapshot,
        mode: ExecutionMode,
    ) -> RiskCheckResult:
        reasons: list[str] = []
        warnings: list[str] = []
        status = RiskStatus.PASS

        if mode == ExecutionMode.LIVE and not self.settings.allow_live_trading:
            status = RiskStatus.BLOCK
            reasons.append("Live trading is disabled by environment configuration.")

        if plan.max_account_risk_pct > Decimal("0.02"):
            status = RiskStatus.BLOCK
            reasons.append("Plan risk cap exceeds the current architecture limit of 2%.")

        if plan.estimated_max_loss is not None and account.net_liquidation > 0:
            actual_risk_pct = plan.estimated_max_loss / account.net_liquidation
            if actual_risk_pct > plan.max_account_risk_pct:
                status = RiskStatus.BLOCK
                reasons.append(
                    "Estimated max loss exceeds the account risk percentage for this plan."
                )

        if plan.asset_type == AssetType.OPTION and not account.options_level:
            status = RiskStatus.BLOCK
            reasons.append("Option plan requires an account with options approval.")

        if account.buying_power <= Decimal("0"):
            status = RiskStatus.BLOCK
            reasons.append("Buying power is not available.")

        if plan.holding_period_days <= 1 and account.day_trade_buying_power is None:
            warnings.append("Intraday workflows need broker-specific day-trade checks.")

        if plan.asset_type == AssetType.OPTION and plan.option_contract is None:
            status = RiskStatus.BLOCK
            reasons.append("Option plan is missing a concrete option contract.")

        if status == RiskStatus.PASS and plan.estimated_max_loss is None:
            warnings.append("Estimated max loss is missing and should be calculated upstream.")

        return RiskCheckResult(
            status=status,
            reasons=reasons,
            warnings=warnings,
        )

    def evaluate_bull_put_candidate(
        self,
        *,
        candidate: BullPutSpreadCandidate,
        account: AccountSnapshot,
        strategy: BullPutSpreadStrategySettings,
    ) -> BullPutSpreadRiskSummary:
        reasons: list[str] = []
        warnings: list[str] = []
        status = RiskStatus.PASS

        max_profit = (
            candidate.mid_credit
            * candidate.short_put.contract_multiplier
            * strategy.contracts_per_trade
        )
        max_loss = (
            max(Decimal("0"), candidate.width - candidate.conservative_credit)
            * candidate.short_put.contract_multiplier
            * strategy.contracts_per_trade
        )
        break_even = candidate.short_put.strike - candidate.mid_credit
        return_on_risk = None
        if max_loss > 0:
            return_on_risk = max_profit / max_loss

        account_risk_pct = None
        if account.net_liquidation > 0:
            account_risk_pct = max_loss / account.net_liquidation
        else:
            status = RiskStatus.BLOCK
            reasons.append("Account net liquidation is unavailable for spread risk sizing.")

        if candidate.conservative_credit <= Decimal("0"):
            status = RiskStatus.BLOCK
            reasons.append("Spread conservative credit must remain positive.")

        if account.buying_power <= Decimal("0"):
            status = RiskStatus.BLOCK
            reasons.append("Buying power is not available.")
        elif max_loss > account.buying_power:
            status = RiskStatus.BLOCK
            reasons.append("Estimated max loss exceeds current account buying power.")

        if account_risk_pct is not None and account_risk_pct > strategy.architecture_max_account_risk_pct:
            status = RiskStatus.BLOCK
            reasons.append(
                "Estimated spread max loss exceeds the architecture risk cap for this strategy."
            )
        elif account_risk_pct is not None and account_risk_pct > strategy.per_trade_max_account_risk_pct:
            status = RiskStatus.BLOCK
            reasons.append(
                "Estimated spread max loss exceeds the per-trade account risk cap for this strategy."
            )

        if candidate.long_put.expiration_date != candidate.short_put.expiration_date:
            status = RiskStatus.BLOCK
            reasons.append("Bull put spread legs must share the same expiration date.")

        if candidate.long_put.strike >= candidate.short_put.strike:
            status = RiskStatus.BLOCK
            reasons.append("Bull put spread long leg strike must be lower than the short leg strike.")

        if candidate.width <= Decimal("0"):
            status = RiskStatus.BLOCK
            reasons.append("Bull put spread width must remain positive.")

        if status == RiskStatus.PASS and return_on_risk is not None and return_on_risk < Decimal("0.10"):
            warnings.append("Projected return on risk is below 10% for this spread.")

        return BullPutSpreadRiskSummary(
            width=candidate.width,
            contract_multiplier=candidate.short_put.contract_multiplier,
            contracts=strategy.contracts_per_trade,
            max_profit=max_profit,
            max_loss=max_loss,
            break_even=break_even,
            return_on_risk=return_on_risk,
            account_risk_pct=account_risk_pct,
            status=status,
            reasons=reasons,
            warnings=warnings,
        )


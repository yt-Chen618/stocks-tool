from decimal import Decimal

from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import AssetType, ExecutionMode, RiskStatus
from stocks_tool.domain.models import AccountSnapshot, RiskCheckResult, TradePlan


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


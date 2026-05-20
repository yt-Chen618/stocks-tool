from decimal import Decimal

from stocks_tool.domain.enums import PlanStatus, TradeStructure
from stocks_tool.domain.models import DraftTradePlanRequest, TradePlan


class PlannerService:
    def build_plan(self, request: DraftTradePlanRequest) -> TradePlan:
        structure = request.preferred_structure or self._infer_structure(request)
        estimated_max_loss = request.estimated_max_loss
        if estimated_max_loss is None and request.entry.maximum and request.stop_loss:
            estimated_max_loss = max(
                Decimal("0"),
                request.entry.maximum - request.stop_loss,
            )

        return TradePlan(
            symbol=request.symbol,
            asset_type=request.asset_type,
            structure=structure,
            bias=request.bias,
            thesis=request.thesis,
            catalyst_type=request.catalyst_type,
            entry=request.entry,
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            invalidation=request.invalidation,
            holding_period_days=request.holding_period_days,
            max_account_risk_pct=request.max_account_risk_pct,
            estimated_max_loss=estimated_max_loss,
            option_contract=request.option_contract,
            notes=request.notes,
            status=PlanStatus.DRAFT,
        )

    @staticmethod
    def _infer_structure(request: DraftTradePlanRequest) -> TradeStructure:
        if request.option_contract is not None:
            return (
                TradeStructure.LONG_CALL
                if request.option_contract.right.value == "call"
                else TradeStructure.LONG_PUT
            )
        return TradeStructure.STOCK


from stocks_tool.domain.enums import OrderSide, OrderType, TimeInForce
from stocks_tool.domain.models import OrderIntent, TradePlan


class ExecutionService:
    def build_order_intent(
        self,
        plan: TradePlan,
        broker: str,
        quantity: int,
        mode,
    ) -> OrderIntent:
        side = OrderSide.BUY if plan.bias.value == "bullish" else OrderSide.SELL
        return OrderIntent(
            plan_id=plan.id,
            broker=broker,
            symbol=plan.symbol,
            side=side,
            quantity=quantity,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            limit_price=plan.entry.maximum,
            mode=mode,
            option_contract=plan.option_contract,
        )


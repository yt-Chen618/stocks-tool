from stocks_tool.domain.models import TradePlan
from stocks_tool.ports.repository import TradePlanRepository


class InMemoryTradePlanRepository(TradePlanRepository):
    def __init__(self) -> None:
        self._plans: dict[str, TradePlan] = {}

    def save_plan(self, plan: TradePlan) -> TradePlan:
        self._plans[plan.id] = plan
        return plan

    def get_plan(self, plan_id: str) -> TradePlan | None:
        return self._plans.get(plan_id)

    def list_plans(self) -> list[TradePlan]:
        return sorted(
            self._plans.values(),
            key=lambda plan: plan.created_at,
            reverse=True,
        )

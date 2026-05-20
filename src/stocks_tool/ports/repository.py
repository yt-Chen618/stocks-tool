from abc import ABC, abstractmethod

from stocks_tool.domain.models import TradePlan


class TradePlanRepository(ABC):
    @abstractmethod
    def save_plan(self, plan: TradePlan) -> TradePlan:
        raise NotImplementedError

    @abstractmethod
    def get_plan(self, plan_id: str) -> TradePlan | None:
        raise NotImplementedError

    @abstractmethod
    def list_plans(self) -> list[TradePlan]:
        raise NotImplementedError


from abc import ABC, abstractmethod
from decimal import Decimal

from stocks_tool.domain.models import OptionContractRef


class MarketDataProvider(ABC):
    @abstractmethod
    async def get_last_price(self, symbol: str) -> Decimal:
        raise NotImplementedError

    @abstractmethod
    async def get_option_chain(self, symbol: str) -> list[OptionContractRef]:
        raise NotImplementedError


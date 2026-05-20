from abc import ABC, abstractmethod


class NewsProvider(ABC):
    @abstractmethod
    async def list_recent_items(self, symbol: str) -> list[dict[str, str]]:
        raise NotImplementedError


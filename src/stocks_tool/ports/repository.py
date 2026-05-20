from abc import ABC, abstractmethod

from stocks_tool.domain.enums import OrderStatus
from stocks_tool.domain.models import (
    AccountSnapshot,
    AddWatchlistItemRequest,
    BrokerAccount,
    CreateBrokerAccountRequest,
    CreateWatchlistRequest,
    Order,
    TradePlan,
    Watchlist,
)


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


class WatchlistRepository(ABC):
    @abstractmethod
    def create_watchlist(self, request: CreateWatchlistRequest) -> Watchlist:
        raise NotImplementedError

    @abstractmethod
    def list_watchlists(self) -> list[Watchlist]:
        raise NotImplementedError

    @abstractmethod
    def add_item(self, watchlist_id: str, request: AddWatchlistItemRequest) -> Watchlist | None:
        raise NotImplementedError


class BrokerAccountRepository(ABC):
    @abstractmethod
    def create_broker_account(self, request: CreateBrokerAccountRequest) -> BrokerAccount:
        raise NotImplementedError

    @abstractmethod
    def list_broker_accounts(self) -> list[BrokerAccount]:
        raise NotImplementedError

    @abstractmethod
    def get_by_external_account_id(
        self,
        external_account_id: str,
    ) -> BrokerAccount | None:
        raise NotImplementedError


class AccountSnapshotRepository(ABC):
    @abstractmethod
    def create_account_snapshot(self, snapshot: AccountSnapshot) -> AccountSnapshot:
        raise NotImplementedError

    @abstractmethod
    def list_account_snapshots(
        self,
        external_account_id: str | None = None,
    ) -> list[AccountSnapshot]:
        raise NotImplementedError


class OrderRepository(ABC):
    @abstractmethod
    def create_order(self, order: Order) -> Order:
        raise NotImplementedError

    @abstractmethod
    def get_order(self, order_id: str) -> Order | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_external_order_id(self, external_order_id: str) -> Order | None:
        raise NotImplementedError

    @abstractmethod
    def list_orders(
        self,
        external_account_id: str | None = None,
        status: OrderStatus | None = None,
    ) -> list[Order]:
        raise NotImplementedError

    @abstractmethod
    def update_order(self, order: Order) -> Order:
        raise NotImplementedError

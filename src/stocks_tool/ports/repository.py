from abc import ABC, abstractmethod
from datetime import date, datetime

from stocks_tool.domain.enums import (
    JournalEntryType,
    OrderStatus,
    ReconciliationStatus,
    SpreadStatus,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    AddWatchlistItemRequest,
    BrokerAccount,
    PreOpenAssessmentRun,
    BullPutSpread,
    BullPutStrategyRuntimeState,
    Execution,
    CreateWatchlistRequest,
    CreateBrokerAccountRequest,
    JournalEntry,
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

    @abstractmethod
    def update_account_sync_state(
        self,
        external_account_id: str,
        *,
        status: ReconciliationStatus,
        attempted_at: datetime | None = None,
        synced_at: datetime | None = None,
        error: str | None = None,
    ) -> BrokerAccount:
        raise NotImplementedError

    @abstractmethod
    def update_orders_sync_state(
        self,
        external_account_id: str,
        *,
        status: ReconciliationStatus,
        attempted_at: datetime | None = None,
        synced_at: datetime | None = None,
        error: str | None = None,
    ) -> BrokerAccount:
        raise NotImplementedError


class AccountSnapshotRepository(ABC):
    @abstractmethod
    def create_account_snapshot(self, snapshot: AccountSnapshot) -> AccountSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get_latest_account_snapshot(
        self,
        external_account_id: str,
    ) -> AccountSnapshot | None:
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


class ExecutionRepository(ABC):
    @abstractmethod
    def get_execution(self, execution_id: str) -> Execution | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_external_execution_id(self, external_execution_id: str) -> Execution | None:
        raise NotImplementedError

    @abstractmethod
    def list_executions(
        self,
        external_account_id: str | None = None,
        order_id: str | None = None,
    ) -> list[Execution]:
        raise NotImplementedError

    @abstractmethod
    def upsert_execution(self, execution: Execution) -> Execution:
        raise NotImplementedError


class JournalRepository(ABC):
    @abstractmethod
    def create_entry(self, entry: JournalEntry) -> JournalEntry:
        raise NotImplementedError

    @abstractmethod
    def list_entries(
        self,
        external_account_id: str | None = None,
        order_id: str | None = None,
        trade_plan_id: str | None = None,
        entry_type: JournalEntryType | None = None,
    ) -> list[JournalEntry]:
        raise NotImplementedError


class BullPutSpreadRepository(ABC):
    @abstractmethod
    def create_spread(self, spread: BullPutSpread) -> BullPutSpread:
        raise NotImplementedError

    @abstractmethod
    def get_spread(self, spread_id: str) -> BullPutSpread | None:
        raise NotImplementedError

    @abstractmethod
    def list_spreads(
        self,
        external_account_id: str | None = None,
        status: SpreadStatus | None = None,
    ) -> list[BullPutSpread]:
        raise NotImplementedError

    @abstractmethod
    def update_spread(self, spread: BullPutSpread) -> BullPutSpread:
        raise NotImplementedError


class BullPutStrategyRuntimeRepository(ABC):
    @abstractmethod
    def get_runtime_state(
        self,
        *,
        external_account_id: str,
        strategy_id: str = "paper_bull_put_v1",
    ) -> BullPutStrategyRuntimeState | None:
        raise NotImplementedError

    @abstractmethod
    def upsert_runtime_state(
        self,
        state: BullPutStrategyRuntimeState,
    ) -> BullPutStrategyRuntimeState:
        raise NotImplementedError


class PreOpenAssessmentRunRepository(ABC):
    @abstractmethod
    def get_run(self, run_id: str) -> PreOpenAssessmentRun | None:
        raise NotImplementedError

    @abstractmethod
    def get_by_session_date(
        self,
        *,
        external_account_id: str,
        target_session_date: date,
        strategy_id: str = "pre_open_put_check_v1",
    ) -> PreOpenAssessmentRun | None:
        raise NotImplementedError

    @abstractmethod
    def list_runs(
        self,
        *,
        external_account_id: str | None = None,
        limit: int = 20,
    ) -> list[PreOpenAssessmentRun]:
        raise NotImplementedError

    @abstractmethod
    def upsert_run(
        self,
        run: PreOpenAssessmentRun,
    ) -> PreOpenAssessmentRun:
        raise NotImplementedError

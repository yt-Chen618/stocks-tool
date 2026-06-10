from abc import ABC, abstractmethod
from datetime import date, datetime

from stocks_tool.domain.enums import (
    JournalEntryType,
    MarketEventType,
    OrderStatus,
    ReconciliationStatus,
    SpreadStatus,
    StrategyProposalStatus,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    AddWatchlistItemRequest,
    BrokerAccount,
    CreateMarketEventRequest,
    PreOpenAssessmentRun,
    BullPutSpread,
    BullPutStrategyRuntimeState,
    CreateStrategyProposalRequest,
    CreateStrategyReviewRequest,
    CreateStrategyRunRequest,
    CreateStrategySignalRequest,
    Execution,
    CreateWatchlistRequest,
    CreateBrokerAccountRequest,
    CreateStrategyAdvisorRunRequest,
    JournalEntry,
    MarketEvent,
    Order,
    StrategyAdvisorRun,
    StrategyProposal,
    StrategyReview,
    StrategyRun,
    StrategySignal,
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


class MarketEventRepository(ABC):
    @abstractmethod
    def create_event(self, request: CreateMarketEventRequest) -> MarketEvent:
        raise NotImplementedError

    @abstractmethod
    def list_events(
        self,
        *,
        symbol: str | None = None,
        event_type: MarketEventType | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> list[MarketEvent]:
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


class StrategyExperimentRepository(ABC):
    @abstractmethod
    def create_proposal(self, request: CreateStrategyProposalRequest) -> StrategyProposal:
        raise NotImplementedError

    @abstractmethod
    def get_proposal(self, proposal_id: str) -> StrategyProposal | None:
        raise NotImplementedError

    @abstractmethod
    def update_proposal_status(
        self,
        proposal_id: str,
        *,
        status: StrategyProposalStatus,
        approved_at: datetime | None = None,
        rejected_at: datetime | None = None,
    ) -> StrategyProposal:
        raise NotImplementedError

    @abstractmethod
    def list_proposals(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        status: StrategyProposalStatus | None = None,
        limit: int = 20,
    ) -> list[StrategyProposal]:
        raise NotImplementedError

    @abstractmethod
    def create_run(self, request: CreateStrategyRunRequest) -> StrategyRun:
        raise NotImplementedError

    @abstractmethod
    def list_runs(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategyRun]:
        raise NotImplementedError

    @abstractmethod
    def create_signal(self, request: CreateStrategySignalRequest) -> StrategySignal:
        raise NotImplementedError

    @abstractmethod
    def list_signals(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategySignal]:
        raise NotImplementedError

    @abstractmethod
    def create_review(self, request: CreateStrategyReviewRequest) -> StrategyReview:
        raise NotImplementedError

    @abstractmethod
    def list_reviews(
        self,
        *,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[StrategyReview]:
        raise NotImplementedError

    @abstractmethod
    def create_advisor_run(self, request: CreateStrategyAdvisorRunRequest) -> StrategyAdvisorRun:
        raise NotImplementedError

    @abstractmethod
    def update_advisor_run_response_payload(
        self,
        advisor_run_id: str,
        *,
        response_payload: dict,
    ) -> StrategyAdvisorRun:
        raise NotImplementedError

    @abstractmethod
    def mark_advisor_run_recorded(
        self,
        advisor_run_id: str,
        *,
        recorded_at: datetime,
        proposal_count: int,
        review_count: int,
        response_payload: dict | None = None,
    ) -> StrategyAdvisorRun:
        raise NotImplementedError

    @abstractmethod
    def list_advisor_runs(
        self,
        *,
        external_account_id: str | None = None,
        source: str | None = None,
        limit: int = 20,
    ) -> list[StrategyAdvisorRun]:
        raise NotImplementedError

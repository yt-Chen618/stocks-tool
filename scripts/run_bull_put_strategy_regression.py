from __future__ import annotations

import argparse
import hashlib
import json
import traceback
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

try:
    from regression_common import build_report, emit_report
except ModuleNotFoundError:
    from scripts.regression_common import build_report, emit_report

import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.application.services.bull_put_strategy import BullPutStrategyService
from stocks_tool.application.services.risk import RiskService
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    SpreadStatus,
)
from stocks_tool.domain.models import (
    AccountSnapshot,
    BrokerOrderIntent,
    BrokerAccount,
    BullPutSpread,
    BullPutStrategyRuntimeState,
    CreateOrderRequest,
    CreateJournalEntryRequest,
    HistoricalPriceBar,
    OptionChainEntry,
    OptionMarketSnapshot,
    Order,
    OrderSyncResult,
    PreparedTradeActionIntent,
    SecurityQuoteSnapshot,
    TradeActionIntent,
    TradingActionContext,
    TradingIntentReconciliationResult,
)
from stocks_tool.domain.enums import (
    AccountSnapshotProvenance,
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.application.services.orders import (
    TradingIntentConflictError,
    TradingIntentOutcomeUnknownError,
    TradingIntentRejectedError,
)


@dataclass
class InMemoryRuntimeRepository:
    state: BullPutStrategyRuntimeState | None = None

    def get_runtime_state(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        strategy_id: str = "paper_bull_put_v1",
    ) -> BullPutStrategyRuntimeState | None:
        if self.state is None:
            return None
        if (
            self.state.external_account_id != external_account_id
            or self.state.strategy_id != strategy_id
            or self.state.mode != mode
        ):
            return None
        return self.state

    def lock_for_entry(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        strategy_id: str = "paper_bull_put_v1",
    ) -> BullPutStrategyRuntimeState | None:
        return self.get_runtime_state(
            external_account_id=external_account_id,
            mode=mode,
            strategy_id=strategy_id,
        )

    def upsert_runtime_state(self, state: BullPutStrategyRuntimeState) -> BullPutStrategyRuntimeState:
        self.state = state
        return state


@dataclass
class InMemorySpreadRepository:
    items: dict[str, BullPutSpread]

    def create_spread(self, spread: BullPutSpread) -> BullPutSpread:
        self.items[spread.id] = spread
        return spread

    def get_spread(self, spread_id: str) -> BullPutSpread | None:
        return self.items.get(spread_id)

    def list_spreads(
        self,
        external_account_id: str | None = None,
        status: SpreadStatus | None = None,
        *,
        statuses: Collection[SpreadStatus] | None = None,
        mode: ExecutionMode | None = None,
        underlying_symbol: str | None = None,
    ) -> list[BullPutSpread]:
        rows = list(self.items.values())
        if external_account_id is not None:
            rows = [row for row in rows if row.external_account_id == external_account_id]
        if status is not None:
            rows = [row for row in rows if row.status == status]
        if statuses is not None:
            normalized_statuses = set(statuses)
            if not normalized_statuses:
                return []
            rows = [row for row in rows if row.status in normalized_statuses]
        if mode is not None:
            rows = [row for row in rows if row.mode == mode]
        if underlying_symbol is not None:
            normalized_symbol = underlying_symbol.strip().upper()
            rows = [row for row in rows if row.underlying_symbol == normalized_symbol]
        return sorted(rows, key=lambda row: (row.created_at, row.id), reverse=True)

    def update_spread(self, spread: BullPutSpread, **kwargs) -> BullPutSpread:
        self.items[spread.id] = spread
        return spread


@dataclass
class InMemoryPreOpenRunRepository:
    items: dict[tuple[str, date, str], object]

    def create_run(self, run):
        self.items[(run.external_account_id, run.target_session_date, run.strategy_id)] = run
        return run

    def get_by_session_date(
        self,
        *,
        external_account_id: str,
        target_session_date: date,
        strategy_id: str = "pre_open_put_check_v1",
    ):
        return self.items.get((external_account_id, target_session_date, strategy_id))

    def list_runs(
        self,
        *,
        external_account_id: str | None = None,
        limit: int = 20,
    ):
        rows = [
            run
            for (account_id, _, _), run in self.items.items()
            if external_account_id is None or account_id == external_account_id
        ]
        return sorted(rows, key=lambda run: run.created_at, reverse=True)[:limit]

    def update_run(self, run):
        self.items[(run.external_account_id, run.target_session_date, run.strategy_id)] = run
        return run

    def upsert_run(self, run):
        return self.update_run(run)


class InMemoryJournalService:
    def __init__(self) -> None:
        self.entries: list[CreateJournalEntryRequest] = []

    def create_entry(self, request: CreateJournalEntryRequest) -> CreateJournalEntryRequest:
        self.entries.append(request)
        return request


class StaticBrokerAccounts:
    def __init__(self, account: BrokerAccount) -> None:
        self.account = account

    def get_by_external_account_id(self, external_account_id: str) -> BrokerAccount | None:
        if external_account_id == self.account.external_account_id:
            return self.account
        return None

    def update_account_sync_state(self, external_account_id: str, **kwargs) -> None:
        if external_account_id != self.account.external_account_id:
            raise LookupError(f"Unknown account '{external_account_id}'.")

    def update_orders_sync_state(self, external_account_id: str, **kwargs) -> None:
        if external_account_id != self.account.external_account_id:
            raise LookupError(f"Unknown account '{external_account_id}'.")


class StaticSnapshots:
    def __init__(self, snapshot: AccountSnapshot) -> None:
        self.snapshot = snapshot

    def get_latest_account_snapshot(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        trusted_only: bool,
    ) -> AccountSnapshot | None:
        snapshots = self.list_account_snapshots(
            external_account_id=external_account_id,
            mode=mode,
            trusted_only=trusted_only,
        )
        return max(snapshots, key=lambda item: item.captured_at) if snapshots else None

    def list_account_snapshots(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        trusted_only: bool = False,
    ) -> list[AccountSnapshot]:
        if external_account_id is not None and external_account_id != self.snapshot.account_id:
            return []
        if mode is not None and self.snapshot.mode != mode:
            return []
        if trusted_only and self.snapshot.provenance is not AccountSnapshotProvenance.BROKER_SYNC:
            return []
        return [self.snapshot]

    def create_account_snapshot(
        self,
        snapshot: AccountSnapshot,
        *,
        provenance: AccountSnapshotProvenance,
    ) -> AccountSnapshot:
        self.snapshot = snapshot.model_copy(update={"provenance": provenance})
        return self.snapshot


class FakeAdapter:
    def __init__(self) -> None:
        self.exit_phase = False

    def get_quote(self, *, symbol: str, mode: ExecutionMode) -> SecurityQuoteSnapshot:
        if self.exit_phase:
            last_done = Decimal("501.25")
            quote_timestamp = datetime(2026, 5, 23, 15, 5, tzinfo=timezone.utc)
        else:
            last_done = Decimal("500.00")
            quote_timestamp = datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc)
        return SecurityQuoteSnapshot(
            symbol=symbol,
            last_done=last_done,
            prev_close=Decimal("498.00"),
            open=Decimal("499.00"),
            high=Decimal("502.00"),
            low=Decimal("497.00"),
            timestamp=quote_timestamp,
            volume=1_000_000,
            turnover=Decimal("500000000"),
            trade_status="Normal",
        )

    def build_account_snapshot(
        self,
        *,
        external_account_id: str,
        mode: ExecutionMode,
        currency: str,
        options_level: str | None,
    ) -> AccountSnapshot:
        return build_snapshot().model_copy(
            update={
                "account_id": external_account_id,
                "currency": currency,
                "options_level": options_level,
            }
        )

    def get_us_market_calendar(self, local_date: date, mode: ExecutionMode) -> tuple[bool, bool]:
        return True, False

    def get_recent_daily_bars(self, *, symbol: str, count: int, mode: ExecutionMode) -> list[HistoricalPriceBar]:
        start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        bars: list[HistoricalPriceBar] = []
        for offset in range(count):
            close = Decimal("400") + Decimal(offset)
            bars.append(
                HistoricalPriceBar(
                    symbol=symbol,
                    timestamp=start + timedelta(days=offset),
                    open=close - Decimal("1"),
                    high=close + Decimal("2"),
                    low=close - Decimal("2"),
                    close=close,
                    volume=1000 + offset,
                    turnover=close * Decimal("1000"),
                )
            )
        return bars

    def list_option_expiry_dates(self, *, symbol: str, mode: ExecutionMode) -> list[date]:
        return [date(2026, 6, 19)]

    def list_option_chain(self, *, symbol: str, expiry_date: date, mode: ExecutionMode) -> list[OptionChainEntry]:
        return [
            OptionChainEntry(strike=Decimal("470"), call_symbol="QQQ260619C470000.US", put_symbol="QQQ260619P470000.US", standard=True),
            OptionChainEntry(strike=Decimal("467"), call_symbol="QQQ260619C467000.US", put_symbol="QQQ260619P467000.US", standard=True),
            OptionChainEntry(strike=Decimal("464"), call_symbol="QQQ260619C464000.US", put_symbol="QQQ260619P464000.US", standard=True),
        ]

    def get_option_market_snapshots(self, *, symbols: list[str], mode: ExecutionMode) -> list[OptionMarketSnapshot]:
        timestamp = (
            datetime(2026, 5, 23, 15, 5, tzinfo=timezone.utc)
            if self.exit_phase
            else datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc)
        )
        price_map = {
            "QQQ260619P470000.US": Decimal("2.50"),
            "QQQ260619P467000.US": Decimal("1.05"),
            "QQQ260619P464000.US": Decimal("0.70"),
        }
        if self.exit_phase:
            price_map = {
                "QQQ260619P470000.US": Decimal("0.75"),
                "QQQ260619P467000.US": Decimal("0.35"),
                "QQQ260619P464000.US": Decimal("0.25"),
            }
        deltas = {
            "QQQ260619P470000.US": Decimal("-0.22"),
            "QQQ260619P467000.US": Decimal("-0.16"),
            "QQQ260619P464000.US": Decimal("-0.12"),
        }
        strikes = {
            "QQQ260619P470000.US": Decimal("470"),
            "QQQ260619P467000.US": Decimal("467"),
            "QQQ260619P464000.US": Decimal("464"),
        }
        snapshots: list[OptionMarketSnapshot] = []
        for symbol in symbols:
            snapshots.append(
                OptionMarketSnapshot(
                    symbol=symbol,
                    underlying_symbol="QQQ.US",
                    expiration_date=date(2026, 6, 19),
                    strike=strikes[symbol],
                    right=OptionRight.PUT,
                    last_done=price_map[symbol],
                    prev_close=price_map[symbol],
                    open=price_map[symbol],
                    high=price_map[symbol],
                    low=price_map[symbol],
                    timestamp=timestamp,
                    volume=1000,
                    turnover=price_map[symbol] * Decimal("1000"),
                    trade_status="Normal",
                    open_interest=500,
                    implied_volatility=Decimal("0.22"),
                    historical_volatility=Decimal("0.18"),
                    delta=deltas[symbol],
                    gamma=Decimal("0.01"),
                    theta=Decimal("-0.02"),
                    vega=Decimal("0.05"),
                )
            )
        return snapshots

    def get_best_bid_ask(self, *, symbol: str, mode: ExecutionMode) -> tuple[Decimal, Decimal]:
        if self.exit_phase:
            prices = {
                "QQQ260619P470000.US": (Decimal("0.70"), Decimal("0.80")),
                "QQQ260619P467000.US": (Decimal("0.30"), Decimal("0.40")),
                "QQQ260619P464000.US": (Decimal("0.20"), Decimal("0.30")),
            }
        else:
            prices = {
                "QQQ260619P470000.US": (Decimal("2.40"), Decimal("2.60")),
                "QQQ260619P467000.US": (Decimal("1.00"), Decimal("1.10")),
                "QQQ260619P464000.US": (Decimal("0.60"), Decimal("0.70")),
            }
        return prices[symbol]


class FakeOrderService:
    def __init__(self) -> None:
        self.counter = 0
        self.action_counter = 0
        self.child_counter = 0
        self.orders: dict[str, Order] = {}
        self.actions: dict[str, TradeActionIntent] = {}
        self.trading_intents: dict[str, BrokerOrderIntent] = {}
        self._action_by_key: dict[tuple[str, ExecutionMode, str], str] = {}
        self._child_by_key: dict[tuple[str, ExecutionMode, str], str] = {}
        self.exit_phase = False

    @staticmethod
    def _request_hash(payload: dict) -> str:
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def prepare_trade_action(
        self,
        *,
        external_account_id: str,
        broker: BrokerName,
        mode: ExecutionMode,
        idempotency_key: str,
        request_hash: str,
        action_context: TradingActionContext,
        request_payload: dict,
    ) -> PreparedTradeActionIntent:
        key = (external_account_id, mode, idempotency_key)
        existing_id = self._action_by_key.get(key)
        if existing_id is not None:
            existing = self.actions[existing_id]
            if existing.request_hash != request_hash:
                raise TradingIntentConflictError(existing.id)
            return PreparedTradeActionIntent(intent=existing, created=False)

        now = self._now()
        self.action_counter += 1
        action = TradeActionIntent(
            id=f"parent-action-{self.action_counter}",
            external_account_id=external_account_id,
            broker=broker,
            mode=mode,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            action=action_context.action,
            strategy_id=action_context.strategy_id,
            entity_id=action_context.entity_id,
            state=TradingIntentState.PREPARED,
            request_payload=request_payload,
            created_at=now,
            updated_at=now,
        )
        self.actions[action.id] = action
        self._action_by_key[key] = action.id
        return PreparedTradeActionIntent(intent=action, created=True)

    def get_trade_action(self, action_intent_id: str) -> TradeActionIntent | None:
        return self.actions.get(action_intent_id)

    def mark_trade_action_submitting(self, action_intent_id: str) -> TradeActionIntent:
        action = self.actions[action_intent_id]
        updated = action.model_copy(update={"state": TradingIntentState.SUBMITTING, "updated_at": self._now()})
        self.actions[action_intent_id] = updated
        return updated

    def complete_trade_action(self, action_intent_id: str, response_payload: dict) -> TradeActionIntent:
        action = self.actions[action_intent_id]
        updated = action.model_copy(
            update={
                "state": TradingIntentState.PERSISTED,
                "response_payload": response_payload,
                "last_error": None,
                "updated_at": self._now(),
            }
        )
        self.actions[action_intent_id] = updated
        return updated

    def mark_trade_action_unknown(self, action_intent_id: str, error: str) -> TradeActionIntent:
        action = self.actions[action_intent_id]
        updated = action.model_copy(
            update={"state": TradingIntentState.UNKNOWN, "last_error": error, "updated_at": self._now()}
        )
        self.actions[action_intent_id] = updated
        return updated

    def mark_trade_action_rejected(self, action_intent_id: str, error: str) -> TradeActionIntent:
        action = self.actions[action_intent_id]
        updated = action.model_copy(
            update={"state": TradingIntentState.REJECTED, "last_error": error, "updated_at": self._now()}
        )
        self.actions[action_intent_id] = updated
        return updated

    def list_trade_actions(self, *, external_account_id=None, mode=None, state=None, limit=100):
        rows = list(self.actions.values())
        if external_account_id is not None:
            rows = [row for row in rows if row.external_account_id == external_account_id]
        if mode is not None:
            rows = [row for row in rows if row.mode == mode]
        if state is not None:
            rows = [row for row in rows if row.state == state]
        return rows[:limit]

    def list_trading_intents(
        self,
        *,
        external_account_id=None,
        mode=None,
        state=None,
        limit=100,
    ) -> list[BrokerOrderIntent]:
        rows = list(self.trading_intents.values())
        if external_account_id is not None:
            rows = [row for row in rows if row.external_account_id == external_account_id]
        if mode is not None:
            rows = [row for row in rows if row.mode == mode]
        if state is not None:
            rows = [row for row in rows if row.state == state]
        return rows[:limit]

    def reconcile_unresolved_intents(
        self,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> TradingIntentReconciliationResult:
        unresolved = [
            intent
            for intent in self.list_trading_intents(
                external_account_id=external_account_id,
                mode=mode,
            )
            if intent.state
            in {
                TradingIntentState.PREPARED,
                TradingIntentState.SUBMITTING,
                TradingIntentState.UNKNOWN,
                TradingIntentState.BROKER_ACKNOWLEDGED,
            }
        ]
        return TradingIntentReconciliationResult(
            external_account_id=external_account_id,
            mode=mode,
            scanned_intents=len(unresolved),
            resolved_intents=0,
            unresolved_intents=len(unresolved),
        )

    def sync_today_orders(
        self,
        external_account_id: str,
        mode: ExecutionMode,
        symbol: str | None = None,
    ) -> OrderSyncResult:
        orders = self.list_orders(external_account_id=external_account_id, mode=mode, symbol=symbol)
        return OrderSyncResult(
            broker=BrokerName.LONGBRIDGE,
            external_account_id=external_account_id,
            mode=mode,
            synced_orders=len(orders),
            created_orders=0,
            updated_orders=len(orders),
            orders=orders,
        )

    def has_unresolved_intents(
        self,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        *,
        exclude_action_intent_id: str | None = None,
    ) -> bool:
        return any(
            intent.trade_action_intent_id != exclude_action_intent_id
            and intent.state
            in {
                TradingIntentState.PREPARED,
                TradingIntentState.SUBMITTING,
                TradingIntentState.UNKNOWN,
                TradingIntentState.BROKER_ACKNOWLEDGED,
            }
            for intent in self.list_trading_intents(
                external_account_id=external_account_id,
                mode=mode,
            )
        )

    def submit_order(
        self,
        request: CreateOrderRequest,
        *,
        idempotency_key: str | None = None,
        action_context: TradingActionContext | None = None,
        parent_action_intent_id: str | None = None,
    ) -> Order:
        idempotency_key = idempotency_key or f"internal-{self.counter + 1}"
        action_context = action_context or TradingActionContext(action="order_submit")
        request_payload = request.model_dump(mode="json")
        request_hash = self._request_hash(request_payload)
        child_key = (request.external_account_id, request.mode, idempotency_key)
        existing_id = self._child_by_key.get(child_key)
        if existing_id is not None:
            existing = self.trading_intents[existing_id]
            if existing.request_hash != request_hash:
                raise TradingIntentConflictError(existing.id)
            if existing.state == TradingIntentState.PERSISTED and existing.response_payload:
                return Order.model_validate(existing.response_payload).model_copy(update={"idempotent_replayed": True})
            if existing.state == TradingIntentState.REJECTED:
                raise TradingIntentRejectedError(existing.id, existing.last_error)
            raise TradingIntentOutcomeUnknownError(existing.id)

        now = self._now()
        self.child_counter += 1
        child_id = f"child-intent-{self.child_counter}"
        child = BrokerOrderIntent(
            id=child_id,
            trade_action_intent_id=parent_action_intent_id or "standalone-action",
            external_account_id=request.external_account_id,
            broker=request.broker,
            mode=request.mode,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=TradingOperation.SUBMIT,
            action=action_context.action,
            strategy_id=action_context.strategy_id,
            entity_id=action_context.entity_id,
            leg=action_context.leg,
            broker_marker=f"fake:{idempotency_key}",
            state=TradingIntentState.PREPARED,
            request_payload=request_payload,
            created_at=now,
            updated_at=now,
        )
        self.trading_intents[child_id] = child
        self._child_by_key[child_key] = child_id
        self.trading_intents[child_id] = child.model_copy(
            update={"state": TradingIntentState.SUBMITTING, "updated_at": self._now()}
        )

        try:
            self.counter += 1
            order_id = f"mock-order-{self.counter}"
            limit_price = request.limit_price
            if self.exit_phase and request.side == OrderSide.SELL and limit_price is None:
                limit_price = Decimal("0.30")
            order = Order(
                id=order_id,
                broker=BrokerName.LONGBRIDGE,
                external_account_id=request.external_account_id,
                external_order_id=f"remote-{order_id}",
                client_order_id=f"client-{order_id}",
                order_intent_id=child_id,
                symbol=request.symbol,
                asset_type=request.asset_type,
                side=request.side,
                quantity=request.quantity,
                order_type=request.order_type,
                time_in_force=request.time_in_force,
                mode=request.mode,
                status=OrderStatus.FILLED,
                executed_quantity=request.quantity,
                executed_price=limit_price,
                limit_price=limit_price,
                option_contract=request.option_contract,
                raw_payload={
                    "submission_request": request_payload,
                    "remote_order": {"executed_price": str(limit_price) if limit_price is not None else None},
                },
                submitted_at=now,
                created_at=now,
                updated_at=now,
            )
        except Exception as exc:
            self.trading_intents[child_id] = self.trading_intents[child_id].model_copy(
                update={"state": TradingIntentState.UNKNOWN, "last_error": str(exc), "updated_at": self._now()}
            )
            raise TradingIntentOutcomeUnknownError(child_id) from exc

        self.orders[order.id] = order
        self.trading_intents[child_id] = self.trading_intents[child_id].model_copy(
            update={
                "state": TradingIntentState.PERSISTED,
                "external_order_id": order.external_order_id,
                "response_payload": order.model_dump(mode="json"),
                "updated_at": self._now(),
            }
        )
        return order

    def list_orders(
        self,
        external_account_id: str | None = None,
        *,
        mode: ExecutionMode | None = None,
        symbol: str | None = None,
    ) -> list[Order]:
        rows = list(self.orders.values())
        if external_account_id is not None:
            rows = [row for row in rows if row.external_account_id == external_account_id]
        if mode is not None:
            rows = [row for row in rows if row.mode == mode]
        if symbol is not None:
            rows = [row for row in rows if row.symbol == symbol]
        return rows

    def refresh_order(self, order_id: str, **kwargs) -> Order:
        return self.orders[order_id]

    def get_order(self, order_id: str) -> Order | None:
        return self.orders.get(order_id)

    def cancel_order(
        self,
        order_id: str,
        *,
        idempotency_key: str | None = None,
        action_context: TradingActionContext | None = None,
        parent_action_intent_id: str | None = None,
    ) -> Order:
        order = self.orders[order_id].model_copy(update={"status": OrderStatus.CANCELED, "updated_at": self._now()})
        self.orders[order_id] = order
        return order


def build_account() -> BrokerAccount:
    now = datetime(2026, 5, 23, 14, 30, tzinfo=timezone.utc)
    return BrokerAccount(
        id="broker-account-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        display_name="Longbridge Paper",
        base_currency="USD",
        options_level="Level 2",
        is_active=True,
        auto_reconcile_enabled=True,
        created_at=now,
        updated_at=now,
    )


def build_snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        id="snapshot-1",
        broker=BrokerName.LONGBRIDGE,
        account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        provenance=AccountSnapshotProvenance.BROKER_SYNC,
        currency="USD",
        cash_balance=Decimal("25000"),
        net_liquidation=Decimal("50000"),
        buying_power=Decimal("25000"),
        options_level="Level 2",
        positions=[],
        captured_at=datetime(2026, 5, 23, 14, 35, tzinfo=timezone.utc),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the paper bull put strategy regression workflow.")
    parser.add_argument("--json-output", default=None, help="Optional path to write the rendered JSON report.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        settings = Settings(_env_file=None, bull_put_strategy={"entry_kill_switch_active": False})
        adapter = FakeAdapter()
        order_service = FakeOrderService()
        journal_service = InMemoryJournalService()
        spreads = InMemorySpreadRepository(items={})
        runtime_states = InMemoryRuntimeRepository()
        pre_open_runs = InMemoryPreOpenRunRepository(items={})
        service = BullPutStrategyService(
            settings=settings,
            broker_accounts=StaticBrokerAccounts(build_account()),
            account_snapshots=StaticSnapshots(build_snapshot()),
            spreads=spreads,
            runtime_states=runtime_states,
            pre_open_runs=pre_open_runs,
            order_service=order_service,
            longbridge_adapter=adapter,
            risk_service=RiskService(settings=settings),
            journal_service=journal_service,
        )

        scan_result = service.run_entry_scan(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            as_of=datetime(2026, 5, 22, 14, 45, tzinfo=timezone.utc),
            force=True,
        )
        if scan_result.executed_spread is None:
            raise RuntimeError(scan_result.reason or "Expected bull put scan to open a spread.")

        adapter.exit_phase = True
        order_service.exit_phase = True
        monitor_result = service.monitor_spread(
            scan_result.executed_spread.id,
            as_of=datetime(2026, 5, 23, 15, 5, tzinfo=timezone.utc),
        )
        for index in range(1, 20):
            seeded_spread = monitor_result.spread.model_copy(
                update={
                    "id": f"seed-closed-{index}",
                    "closed_at": datetime(2026, 5, 23, 15, 5, tzinfo=timezone.utc) - timedelta(days=index),
                    "updated_at": datetime(2026, 5, 23, 15, 5, tzinfo=timezone.utc) - timedelta(days=index),
                    "raw_payload": {},
                }
            )
            spreads.update_spread(seeded_spread)
        review_result = service.run_review(
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            as_of=datetime(2026, 5, 23, 16, 5, tzinfo=timezone.utc),
            force=True,
        )

        payload = {
            "checks": {
                "scan_executed": scan_result.executed,
                "spread_opened": scan_result.executed_spread.status == SpreadStatus.OPEN,
                "monitor_closed": monitor_result.spread.status == SpreadStatus.CLOSED,
                "daily_entry_count": scan_result.strategy_state.daily_entry_count == 1,
                "runtime_realized_pnl": runtime_states.state is not None and runtime_states.state.daily_realized_pnl == Decimal("80.00"),
                "journal_entries": len(journal_service.entries) >= 3,
                "review_generated": review_result.review_status == "suggested",
            },
            "scan": {
                "runtime_result": scan_result.strategy_state.last_scan_result,
                "spread_id": scan_result.executed_spread.id,
                "entry_credit": str(scan_result.executed_spread.entry_net_credit),
            },
            "monitor": {
                "status": monitor_result.spread.status.value,
                "exit_reason": monitor_result.exit_reason,
                "estimated_pnl": str(monitor_result.estimated_pnl),
            },
            "review": {
                "status": review_result.review_status,
                "parameter_name": review_result.parameter_name,
                "suggested_value": review_result.suggested_value,
            },
            "journal_titles": [entry.title for entry in journal_service.entries],
        }
        report = build_report(
            script="run_bull_put_strategy_regression.py",
            workflow="bull-put-paper-regression",
            status="passed",
            mode="paper",
            summary="Bull put scan, open, monitor, close, review, and journal workflow passed.",
            target="BullPutStrategyService",
            payload=payload,
        )
        emit_report(report, json_output=args.json_output)
    except Exception as exc:
        report = build_report(
            script="run_bull_put_strategy_regression.py",
            workflow="bull-put-paper-regression",
            status="failed",
            mode="paper",
            summary="Bull put strategy regression failed.",
            target="BullPutStrategyService",
            error="".join(traceback.format_exception_only(type(exc), exc)).strip(),
        )
        emit_report(report, json_output=args.json_output)
        raise SystemExit(1)


if __name__ == "__main__":
    main()

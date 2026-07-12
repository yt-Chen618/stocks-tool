import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from stocks_tool.core.config import Settings
from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeConfigurationError,
    LongbridgeDependencyError,
    LongbridgeOrderNotAcceptedError,
)
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderStatus,
    ReconciliationStatus,
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.domain.models import (
    BrokerOrderSnapshot,
    BrokerOrderIntent,
    CreateStrategyAuditEventRequest,
    CreateOrderRequest,
    Execution,
    Order,
    OrderSyncResult,
    PreparedBrokerOrderIntent,
    PreparedTradeActionIntent,
    ReplaceOrderRequest,
    ResolveTradingIntentRequest,
    TradeActionIntent,
    TradingIntentReconciliationResult,
    TradingActionContext,
)
from stocks_tool.ports.repository import (
    BrokerAccountRepository,
    ExecutionRepository,
    OrderRepository,
    StrategyAuditEventRepository,
    TradePlanRepository,
)
from stocks_tool.ports.broker_gateway import BrokerOrderGateway
from stocks_tool.ports.trading_intent_ledger import (
    TradeActionIntentConflictError,
    TradingIntentLedger,
)


logger = logging.getLogger(__name__)


class TradingIntentError(RuntimeError):
    def __init__(self, intent_id: str, message: str) -> None:
        super().__init__(message)
        self.intent_id = intent_id


class TradingIntentConflictError(TradingIntentError):
    def __init__(self, intent_id: str) -> None:
        super().__init__(intent_id, "Idempotency key was already used for a different request.")


class TradingIntentOutcomeUnknownError(TradingIntentError):
    def __init__(self, intent_id: str) -> None:
        super().__init__(intent_id, "Broker mutation outcome is unknown; do not retry with a new key.")


class TradingIntentRejectedError(TradingIntentError):
    def __init__(self, intent_id: str, message: str | None = None) -> None:
        super().__init__(intent_id, message or "Broker mutation was rejected.")


class OrderService:
    def __init__(
        self,
        settings: Settings,
        broker_accounts: BrokerAccountRepository,
        trade_plans: TradePlanRepository,
        orders: OrderRepository,
        executions: ExecutionRepository,
        longbridge_adapter: BrokerOrderGateway,
        audit_events: StrategyAuditEventRepository | None = None,
        intent_ledger: TradingIntentLedger | None = None,
    ) -> None:
        self.settings = settings
        self.broker_accounts = broker_accounts
        self.trade_plans = trade_plans
        self.orders = orders
        self.executions = executions
        self.longbridge_adapter = longbridge_adapter
        self.audit_events = audit_events
        self.intent_ledger = intent_ledger or getattr(orders, "trading_intent_ledger", None)

    def list_orders(
        self,
        external_account_id: str | None = None,
    ) -> list[Order]:
        return self.orders.list_orders(external_account_id=external_account_id)

    def get_order(self, order_id: str) -> Order | None:
        return self.orders.get_order(order_id)

    def list_trading_intents(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        state: TradingIntentState | None = None,
        limit: int = 100,
    ) -> list[BrokerOrderIntent]:
        if self.intent_ledger is None:
            return []
        return self.intent_ledger.list_intents(
            external_account_id=external_account_id,
            mode=mode,
            state=state,
            limit=limit,
        )

    def get_trading_intent(self, intent_id: str) -> BrokerOrderIntent | None:
        if self.intent_ledger is None:
            return None
        return self.intent_ledger.get_intent(intent_id)

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
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable; trade action is blocked.")
        try:
            return self.intent_ledger.prepare_action(
                external_account_id=external_account_id,
                broker=broker,
                mode=mode,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                action_context=action_context,
                request_payload=request_payload,
            )
        except TradeActionIntentConflictError as exc:
            raise TradingIntentConflictError(exc.intent_id) from exc

    def get_trade_action(self, action_intent_id: str) -> TradeActionIntent | None:
        if self.intent_ledger is None:
            return None
        return self.intent_ledger.get_action(action_intent_id)

    def list_trade_actions(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
        state: TradingIntentState | None = None,
        limit: int = 100,
    ) -> list[TradeActionIntent]:
        if self.intent_ledger is None:
            return []
        return self.intent_ledger.list_actions(
            external_account_id=external_account_id,
            mode=mode,
            state=state,
            limit=limit,
        )

    def mark_trade_action_submitting(self, action_intent_id: str) -> TradeActionIntent:
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable; trade action is blocked.")
        return self.intent_ledger.mark_action_submitting(action_intent_id)

    def complete_trade_action(
        self,
        action_intent_id: str,
        response_payload: dict,
    ) -> TradeActionIntent:
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable; trade action is blocked.")
        return self.intent_ledger.complete_action(action_intent_id, response_payload)

    def mark_trade_action_unknown(
        self,
        action_intent_id: str,
        error: str,
    ) -> TradeActionIntent:
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable; trade action is blocked.")
        return self.intent_ledger.mark_action_unknown(action_intent_id, error)

    def mark_trade_action_rejected(
        self,
        action_intent_id: str,
        error: str,
    ) -> TradeActionIntent:
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable; trade action is blocked.")
        return self.intent_ledger.mark_action_rejected(action_intent_id, error)

    def has_unresolved_intents(
        self,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
        *,
        exclude_action_intent_id: str | None = None,
    ) -> bool:
        if self.intent_ledger is None:
            return True
        return self.intent_ledger.has_unresolved_intents(
            external_account_id=external_account_id,
            mode=mode,
            exclude_action_intent_id=exclude_action_intent_id,
        )

    def resolve_trading_intent_no_order(
        self,
        intent_id: str,
        request: ResolveTradingIntentRequest,
    ) -> BrokerOrderIntent:
        if not request.confirm_paper_resolution:
            raise PermissionError("Explicit paper no-order resolution confirmation is required.")
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable.")
        return self.intent_ledger.resolve_no_order(
            intent_id,
            actor=request.actor,
            note=request.note,
        )

    def reconcile_unresolved_intents(
        self,
        external_account_id: str,
        mode: ExecutionMode = ExecutionMode.PAPER,
    ) -> TradingIntentReconciliationResult:
        if self.intent_ledger is None:
            return TradingIntentReconciliationResult(
                external_account_id=external_account_id,
                mode=mode,
                scanned_intents=0,
                resolved_intents=0,
                unresolved_intents=0,
                warnings=["Trading intent ledger is unavailable."],
            )

        unresolved_by_id = {}
        for state in (
            TradingIntentState.PREPARED,
            TradingIntentState.SUBMITTING,
            TradingIntentState.UNKNOWN,
            TradingIntentState.BROKER_ACKNOWLEDGED,
        ):
            for intent in self.intent_ledger.list_intents(
                external_account_id=external_account_id,
                mode=mode,
                state=state,
                limit=500,
            ):
                unresolved_by_id[intent.id] = intent
        intents = list(unresolved_by_id.values())
        if not intents:
            return TradingIntentReconciliationResult(
                external_account_id=external_account_id,
                mode=mode,
                scanned_intents=0,
                resolved_intents=0,
                unresolved_intents=0,
            )

        now = datetime.now(timezone.utc)
        try:
            remote_orders = self.longbridge_adapter.list_today_orders(mode=mode)
            remote_orders.extend(
                self.longbridge_adapter.list_history_orders(
                    mode=mode,
                    start_at=now - timedelta(days=7),
                    end_at=now,
                )
            )
        except Exception as exc:
            warning = f"Trading intent reconciliation could not load complete broker order history: {exc}"
            for intent in intents:
                self.intent_ledger.record_reconciliation_attempt(intent.id, warning)
            return TradingIntentReconciliationResult(
                external_account_id=external_account_id,
                mode=mode,
                scanned_intents=len(intents),
                resolved_intents=0,
                unresolved_intents=len(intents),
                warnings=[warning],
            )

        unique_remote_orders = {
            snapshot.external_order_id: snapshot
            for snapshot in remote_orders
            if snapshot.external_order_id
        }
        resolved_ids: list[str] = []
        warnings: list[str] = []
        for intent in intents:
            matches = [
                snapshot
                for snapshot in unique_remote_orders.values()
                if self._snapshot_matches_intent(intent, snapshot)
            ]
            if len(matches) != 1:
                warning = (
                    f"Intent {intent.id} matched {len(matches)} broker orders; "
                    "it remains unknown and no broker mutation was retried."
                )
                self.intent_ledger.record_reconciliation_attempt(
                    intent.id,
                    warning,
                    zero_match=len(matches) == 0,
                )
                warnings.append(warning)
                continue
            try:
                self._persist_reconciled_intent(intent, matches[0])
            except Exception as exc:
                warning = f"Intent {intent.id} reconciliation persistence failed: {exc}"
                current = self.intent_ledger.get_intent(intent.id)
                if current is not None and current.state == TradingIntentState.PERSISTED:
                    resolved_ids.append(intent.id)
                    continue
                self.intent_ledger.record_reconciliation_attempt(intent.id, warning)
                warnings.append(warning)
                continue
            resolved_ids.append(intent.id)

        return TradingIntentReconciliationResult(
            external_account_id=external_account_id,
            mode=mode,
            scanned_intents=len(intents),
            resolved_intents=len(resolved_ids),
            unresolved_intents=len(intents) - len(resolved_ids),
            resolved_intent_ids=resolved_ids,
            warnings=warnings,
        )

    def submit_order(
        self,
        request: CreateOrderRequest,
        *,
        idempotency_key: str | None = None,
        action_context: TradingActionContext | None = None,
        parent_action_intent_id: str | None = None,
    ) -> Order:
        if request.mode == ExecutionMode.LIVE and not self.settings.allow_live_trading:
            raise PermissionError("Live trading is disabled. Set `ALLOW_LIVE_TRADING=true` to enable it.")

        broker_account = self.broker_accounts.get_by_external_account_id(request.external_account_id)
        if broker_account is None:
            raise LookupError(
                f"No broker account was found for '{request.external_account_id}'."
            )
        if not broker_account.is_active:
            raise ValueError(f"Broker account '{request.external_account_id}' is inactive.")
        if broker_account.broker != request.broker:
            raise ValueError(
                f"Broker account '{request.external_account_id}' is not a {request.broker.value} account."
            )
        if request.trade_plan_id is not None and self.trade_plans.get_plan(request.trade_plan_id) is None:
            raise LookupError(f"Trade plan '{request.trade_plan_id}' was not found.")

        if request.broker != BrokerName.LONGBRIDGE:
            raise NotImplementedError(f"Broker '{request.broker.value}' is not supported yet.")

        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable; broker mutation is blocked.")

        action_context = action_context or TradingActionContext(action="order_submit")
        idempotency_key = idempotency_key or f"internal-{uuid4().hex}"
        request_payload = request.model_dump(mode="json")
        request_hash = self._request_hash(request_payload)
        broker_marker = self._broker_marker(
            external_account_id=request.external_account_id,
            mode=request.mode,
            idempotency_key=idempotency_key,
        )
        prepared = self.intent_ledger.prepare_intent(
            external_account_id=request.external_account_id,
            broker=request.broker,
            mode=request.mode,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=TradingOperation.SUBMIT,
            action_context=action_context,
            broker_marker=broker_marker,
            request_payload=request_payload,
            parent_action_intent_id=parent_action_intent_id,
        )
        replay = self._resolve_prepared_intent(prepared, request_hash=request_hash)
        if replay is not None:
            return replay

        intent_id = prepared.intent.id
        self.intent_ledger.mark_submitting(intent_id)
        broker_request = request.model_copy(
            update={"remark": self._remark_with_marker(broker_marker, request.remark)}
        )
        try:
            remote_snapshot = self.longbridge_adapter.submit_order(broker_request)
        except (LongbridgeConfigurationError, LongbridgeDependencyError) as exc:
            self.intent_ledger.mark_rejected(intent_id, str(exc))
            raise
        except LongbridgeOrderNotAcceptedError as exc:
            self.intent_ledger.mark_rejected(intent_id, str(exc))
            raise TradingIntentRejectedError(intent_id, str(exc)) from exc
        except Exception as exc:
            self._mark_unknown_safely(intent_id, exc)
            raise TradingIntentOutcomeUnknownError(intent_id) from exc

        try:
            self.intent_ledger.mark_broker_acknowledged(intent_id, remote_snapshot)
        except Exception as exc:
            self._mark_unknown_safely(
                intent_id,
                exc,
                known_external_order_id=remote_snapshot.external_order_id,
            )
            raise TradingIntentOutcomeUnknownError(intent_id) from exc

        try:
            order = self._build_submitted_order(
                request=request,
                remote_snapshot=remote_snapshot,
                order_intent_id=intent_id,
            )
            audit_event = self._build_order_audit_event(
                order,
                action="paper_order_submitted",
                before=None,
                after={"status": order.status.value},
                summary=f"{order.symbol} {order.side.value} paper order submitted.",
            )
            return self.intent_ledger.persist_broker_result(
                intent_id=intent_id,
                order=order,
                snapshot=remote_snapshot,
                audit_event=audit_event,
                create_order=True,
            )
        except Exception as exc:
            persisted = self.intent_ledger.get_intent(intent_id)
            if (
                persisted is not None
                and persisted.state == TradingIntentState.PERSISTED
                and persisted.response_payload
            ):
                return Order.model_validate(persisted.response_payload).model_copy(
                    update={"idempotent_replayed": True}
                )
            self._mark_unknown_safely(intent_id, exc)
            raise TradingIntentOutcomeUnknownError(intent_id) from exc

    def _submit_order_without_intent_ledger(self, request: CreateOrderRequest) -> Order:
        remote_snapshot = self.longbridge_adapter.submit_order(request)
        order = self._build_submitted_order(
            request=request,
            remote_snapshot=remote_snapshot,
            order_intent_id=None,
        )
        persisted_order = self.orders.create_order(order)
        self._sync_execution_from_snapshot(persisted_order, remote_snapshot)
        self._append_order_audit_event(
            persisted_order,
            action="paper_order_submitted",
            before=None,
            after={"status": persisted_order.status.value},
            summary=f"{persisted_order.symbol} {persisted_order.side.value} paper order submitted.",
        )
        return persisted_order

    @staticmethod
    def _build_submitted_order(
        *,
        request: CreateOrderRequest,
        remote_snapshot: BrokerOrderSnapshot,
        order_intent_id: str | None,
    ) -> Order:
        now = datetime.now(timezone.utc)
        return Order(
            id=str(uuid4()),
            broker=request.broker,
            external_account_id=request.external_account_id,
            trade_plan_id=request.trade_plan_id,
            external_order_id=remote_snapshot.external_order_id,
            client_order_id=f"local-{uuid4().hex[:24]}",
            order_intent_id=order_intent_id,
            symbol=remote_snapshot.symbol,
            asset_type=request.asset_type,
            side=remote_snapshot.side,
            quantity=remote_snapshot.quantity,
            order_type=remote_snapshot.order_type,
            time_in_force=remote_snapshot.time_in_force,
            mode=request.mode,
            status=remote_snapshot.status,
            executed_quantity=remote_snapshot.executed_quantity,
            executed_price=remote_snapshot.executed_price,
            limit_price=remote_snapshot.limit_price,
            stop_price=remote_snapshot.stop_price,
            option_contract=request.option_contract,
            raw_payload={
                "submission_request": request.model_dump(mode="json"),
                "remote_order": remote_snapshot.raw_payload,
            },
            submitted_at=remote_snapshot.submitted_at,
            created_at=now,
            updated_at=now,
        )

    def refresh_order(self, order_id: str) -> Order:
        order = self._get_order_or_raise(order_id)
        if order.external_order_id is None:
            raise ValueError(f"Order '{order_id}' has no broker order id to refresh.")
        if order.broker != BrokerName.LONGBRIDGE:
            raise NotImplementedError(f"Broker '{order.broker.value}' is not supported yet.")

        remote_snapshot = self.longbridge_adapter.get_order(
            external_order_id=order.external_order_id,
            mode=order.mode,
        )
        refreshed = self._merge_remote_snapshot(order, remote_snapshot)
        self._append_order_audit_event(
            refreshed,
            action="paper_order_refreshed",
            before={"status": order.status.value},
            after={"status": refreshed.status.value},
            summary=f"{refreshed.symbol} {refreshed.side.value} paper order refreshed.",
        )
        return refreshed

    def cancel_order(
        self,
        order_id: str,
        *,
        idempotency_key: str | None = None,
        action_context: TradingActionContext | None = None,
        parent_action_intent_id: str | None = None,
    ) -> Order:
        order = self._get_order_or_raise(order_id)
        if order.external_order_id is None:
            raise ValueError(f"Order '{order_id}' has no broker order id to cancel.")
        if order.broker != BrokerName.LONGBRIDGE:
            raise NotImplementedError(f"Broker '{order.broker.value}' is not supported yet.")
        if order.mode == ExecutionMode.LIVE and not self.settings.allow_live_trading:
            raise PermissionError(
                "Live trading is disabled. Set `ALLOW_LIVE_TRADING=true` to enable it."
            )

        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable; broker mutation is blocked.")

        action_context = action_context or TradingActionContext(action="order_cancel")
        idempotency_key = idempotency_key or f"internal-{uuid4().hex}"
        payload = {
            "operation": TradingOperation.CANCEL.value,
            "order_id": order.id,
            "external_order_id": order.external_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": order.quantity,
        }
        intent_id, replay = self._prepare_existing_order_intent(
            order=order,
            idempotency_key=idempotency_key,
            action_context=action_context,
            operation=TradingOperation.CANCEL,
            request_payload=payload,
            parent_action_intent_id=parent_action_intent_id,
        )
        if replay is not None:
            return replay
        assert intent_id is not None
        remote_snapshot = self._run_broker_mutation(
            intent_id,
            lambda: self.longbridge_adapter.cancel_order(
                external_order_id=order.external_order_id or "",
                mode=order.mode,
            ),
        )
        canceled = self._order_with_remote_snapshot(order, remote_snapshot)
        audit_event = self._build_order_audit_event(
            canceled,
            action="paper_order_canceled",
            before={"status": order.status.value},
            after={"status": canceled.status.value},
            summary=f"{canceled.symbol} {canceled.side.value} paper order cancel requested.",
        )
        return self._persist_durable_result(
            intent_id=intent_id,
            order=canceled,
            snapshot=remote_snapshot,
            audit_event=audit_event,
            create_order=False,
        )

    def replace_order(
        self,
        order_id: str,
        request: ReplaceOrderRequest,
        *,
        idempotency_key: str | None = None,
        action_context: TradingActionContext | None = None,
        parent_action_intent_id: str | None = None,
    ) -> Order:
        order = self._get_order_or_raise(order_id)
        if order.external_order_id is None:
            raise ValueError(f"Order '{order_id}' has no broker order id to replace.")
        if order.broker != BrokerName.LONGBRIDGE:
            raise NotImplementedError(f"Broker '{order.broker.value}' is not supported yet.")
        if order.mode == ExecutionMode.LIVE and not self.settings.allow_live_trading:
            raise PermissionError(
                "Live trading is disabled. Set `ALLOW_LIVE_TRADING=true` to enable it."
            )

        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable; broker mutation is blocked.")

        action_context = action_context or TradingActionContext(action="order_replace")
        idempotency_key = idempotency_key or f"internal-{uuid4().hex}"
        replacement_payload = request.model_dump(mode="json")
        payload = {
            "operation": TradingOperation.REPLACE.value,
            "order_id": order.id,
            "external_order_id": order.external_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": request.quantity,
            "limit_price": replacement_payload["limit_price"],
            "stop_price": replacement_payload["stop_price"],
            "replacement": replacement_payload,
        }
        intent_id, replay = self._prepare_existing_order_intent(
            order=order,
            idempotency_key=idempotency_key,
            action_context=action_context,
            operation=TradingOperation.REPLACE,
            request_payload=payload,
            parent_action_intent_id=parent_action_intent_id,
        )
        if replay is not None:
            return replay
        assert intent_id is not None
        marker = self._broker_marker(
            external_account_id=order.external_account_id,
            mode=order.mode,
            idempotency_key=idempotency_key,
        )
        remote_snapshot = self._run_broker_mutation(
            intent_id,
            lambda: self.longbridge_adapter.replace_order(
                external_order_id=order.external_order_id or "",
                quantity=request.quantity,
                limit_price=request.limit_price,
                stop_price=request.stop_price,
                remark=self._remark_with_marker(marker, request.remark),
                mode=order.mode,
            ),
        )
        replaced = order.model_copy(
            update={
                "quantity": request.quantity,
                "limit_price": request.limit_price,
                "stop_price": request.stop_price,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        replaced = self._order_with_remote_snapshot(replaced, remote_snapshot)
        audit_event = self._build_order_audit_event(
            replaced,
            action="paper_order_replaced",
            before={"status": order.status.value, "quantity": order.quantity},
            after={"status": replaced.status.value, "quantity": replaced.quantity},
            summary=f"{replaced.symbol} {replaced.side.value} paper order replaced.",
        )
        return self._persist_durable_result(
            intent_id=intent_id,
            order=replaced,
            snapshot=remote_snapshot,
            audit_event=audit_event,
            create_order=False,
        )

    def sync_today_orders(
        self,
        external_account_id: str,
        mode: ExecutionMode,
        symbol: str | None = None,
    ) -> OrderSyncResult:
        broker_account = self.broker_accounts.get_by_external_account_id(external_account_id)
        if broker_account is None:
            raise LookupError(
                f"No broker account was found for '{external_account_id}'."
            )
        if broker_account.broker != BrokerName.LONGBRIDGE:
            raise NotImplementedError(
                f"Broker '{broker_account.broker.value}' is not supported yet."
            )

        attempted_at = datetime.now(timezone.utc)
        self.broker_accounts.update_orders_sync_state(
            external_account_id,
            status=ReconciliationStatus.SYNCING,
            attempted_at=attempted_at,
            error=None,
        )

        try:
            remote_orders = self.longbridge_adapter.list_today_orders(
                mode=mode,
                symbol=symbol,
            )
            created_orders = 0
            updated_orders = 0
            persisted_orders: list[Order] = []
            for remote_snapshot in remote_orders:
                existing = self.orders.get_by_external_order_id(
                    remote_snapshot.external_order_id,
                    broker=BrokerName.LONGBRIDGE,
                    mode=mode,
                )
                if existing is None:
                    created_orders += 1
                    persisted_order = self.orders.create_order(
                        self._build_local_order(
                            external_account_id=external_account_id,
                            remote_snapshot=remote_snapshot,
                            mode=mode,
                        )
                    )
                    self._sync_execution_from_snapshot(persisted_order, remote_snapshot)
                    persisted_orders.append(persisted_order)
                else:
                    updated_orders += 1
                    persisted_orders.append(self._merge_remote_snapshot(existing, remote_snapshot))

            self.broker_accounts.update_orders_sync_state(
                external_account_id,
                status=ReconciliationStatus.SUCCESS,
                attempted_at=attempted_at,
                synced_at=datetime.now(timezone.utc),
                error=None,
            )
            return OrderSyncResult(
                broker=BrokerName.LONGBRIDGE,
                external_account_id=external_account_id,
                mode=mode,
                synced_orders=len(remote_orders),
                created_orders=created_orders,
                updated_orders=updated_orders,
                orders=persisted_orders,
            )
        except Exception as exc:
            self.broker_accounts.update_orders_sync_state(
                external_account_id,
                status=ReconciliationStatus.ERROR,
                attempted_at=attempted_at,
                error=str(exc),
            )
            raise

    def _prepare_existing_order_intent(
        self,
        *,
        order: Order,
        idempotency_key: str,
        action_context: TradingActionContext,
        operation: TradingOperation,
        request_payload: dict,
        parent_action_intent_id: str | None,
    ) -> tuple[str | None, Order | None]:
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable.")
        request_hash = self._request_hash(request_payload)
        prepared = self.intent_ledger.prepare_intent(
            external_account_id=order.external_account_id,
            broker=order.broker,
            mode=order.mode,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            operation=operation,
            action_context=action_context,
            broker_marker=self._broker_marker(
                external_account_id=order.external_account_id,
                mode=order.mode,
                idempotency_key=idempotency_key,
            ),
            request_payload=request_payload,
            target_order_id=order.id,
            parent_action_intent_id=parent_action_intent_id,
        )
        replay = self._resolve_prepared_intent(prepared, request_hash=request_hash)
        return (None, replay) if replay is not None else (prepared.intent.id, None)

    def _run_broker_mutation(
        self,
        intent_id: str,
        mutation: Callable[[], BrokerOrderSnapshot],
    ) -> BrokerOrderSnapshot:
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable.")
        self.intent_ledger.mark_submitting(intent_id)
        try:
            snapshot = mutation()
        except (LongbridgeConfigurationError, LongbridgeDependencyError) as exc:
            self.intent_ledger.mark_rejected(intent_id, str(exc))
            raise
        except LongbridgeOrderNotAcceptedError as exc:
            self.intent_ledger.mark_rejected(intent_id, str(exc))
            raise TradingIntentRejectedError(intent_id, str(exc)) from exc
        except Exception as exc:
            self._mark_unknown_safely(
                intent_id,
                exc,
                persist_exception_external_order_id=False,
            )
            raise TradingIntentOutcomeUnknownError(intent_id) from exc
        try:
            self.intent_ledger.mark_broker_acknowledged(intent_id, snapshot)
        except Exception as exc:
            self._mark_unknown_safely(
                intent_id,
                exc,
                known_external_order_id=snapshot.external_order_id,
            )
            raise TradingIntentOutcomeUnknownError(intent_id) from exc
        return snapshot

    def _persist_durable_result(
        self,
        *,
        intent_id: str,
        order: Order,
        snapshot: BrokerOrderSnapshot,
        audit_event: CreateStrategyAuditEventRequest | None,
        create_order: bool,
    ) -> Order:
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable.")
        try:
            return self.intent_ledger.persist_broker_result(
                intent_id=intent_id,
                order=order,
                snapshot=snapshot,
                audit_event=audit_event,
                create_order=create_order,
            )
        except Exception as exc:
            persisted = self.intent_ledger.get_intent(intent_id)
            if (
                persisted is not None
                and persisted.state == TradingIntentState.PERSISTED
                and persisted.response_payload
            ):
                return Order.model_validate(persisted.response_payload).model_copy(
                    update={"idempotent_replayed": True}
                )
            self._mark_unknown_safely(intent_id, exc)
            raise TradingIntentOutcomeUnknownError(intent_id) from exc

    @staticmethod
    def _snapshot_matches_intent(
        intent: BrokerOrderIntent,
        snapshot: BrokerOrderSnapshot,
    ) -> bool:
        if intent.operation == TradingOperation.CANCEL:
            expected_external_id = intent.request_payload.get("external_order_id")
            return bool(
                expected_external_id
                and snapshot.external_order_id == expected_external_id
                and snapshot.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
                and snapshot.executed_quantity == 0
            )
        payload = intent.request_payload
        if intent.operation == TradingOperation.REPLACE:
            expected_external_id = payload.get("external_order_id")
            if not expected_external_id or snapshot.external_order_id != expected_external_id:
                return False
            remark = snapshot.remark
            if not remark and snapshot.raw_payload:
                raw_remark = snapshot.raw_payload.get("remark")
                remark = str(raw_remark) if raw_remark is not None else None
            if not remark or intent.broker_marker not in remark:
                return False
            if int(payload.get("quantity") or 0) != snapshot.quantity:
                return False
            for field_name, actual in (
                ("limit_price", snapshot.limit_price),
                ("stop_price", snapshot.stop_price),
            ):
                expected = payload.get(field_name)
                if expected is None:
                    if actual is not None:
                        return False
                elif actual is None or Decimal(str(expected)) != actual:
                    return False
            return True
        if (
            intent.operation == TradingOperation.SUBMIT
            and intent.external_order_id
            and snapshot.external_order_id == intent.external_order_id
        ):
            return True
        remark = snapshot.remark
        if not remark and snapshot.raw_payload:
            raw_remark = snapshot.raw_payload.get("remark")
            remark = str(raw_remark) if raw_remark is not None else None
        if not remark or intent.broker_marker not in remark:
            return False
        if payload.get("symbol") and payload["symbol"] != snapshot.symbol:
            return False
        expected_side = payload.get("side")
        if expected_side and expected_side != snapshot.side.value:
            return False
        expected_quantity = payload.get("quantity")
        if expected_quantity is not None and int(expected_quantity) != snapshot.quantity:
            return False
        for field_name, actual in (
            ("limit_price", snapshot.limit_price),
            ("stop_price", snapshot.stop_price),
        ):
            expected = payload.get(field_name)
            if expected is not None and (actual is None or Decimal(str(expected)) != actual):
                return False
        return True

    def _persist_reconciled_intent(
        self,
        intent: BrokerOrderIntent,
        snapshot: BrokerOrderSnapshot,
    ) -> Order:
        if self.intent_ledger is None:
            raise RuntimeError("Trading intent ledger is unavailable.")
        create_order = intent.operation == TradingOperation.SUBMIT
        if create_order:
            request = CreateOrderRequest.model_validate(intent.request_payload)
            existing = self.orders.get_by_external_order_id(
                snapshot.external_order_id,
                broker=intent.broker,
                mode=intent.mode,
            )
            if existing is None:
                order = self._build_submitted_order(
                    request=request,
                    remote_snapshot=snapshot,
                    order_intent_id=intent.id,
                )
            else:
                order = self._order_with_remote_snapshot(existing, snapshot).model_copy(
                    update={"order_intent_id": intent.id}
                )
                create_order = False
        else:
            if not intent.target_order_id:
                raise ValueError(f"Intent '{intent.id}' has no target order id.")
            local_order = self._get_order_or_raise(intent.target_order_id)
            order = self._order_with_remote_snapshot(local_order, snapshot)
        audit_event = self._build_order_audit_event(
            order,
            action=f"paper_order_{intent.operation.value}_reconciled",
            before={"intent_state": intent.state.value},
            after={"status": order.status.value},
            summary=f"{order.symbol} broker mutation reconciled from intent {intent.id}.",
        )
        return self.intent_ledger.persist_broker_result(
            intent_id=intent.id,
            order=order,
            snapshot=snapshot,
            audit_event=audit_event,
            create_order=create_order,
            reconciled=True,
        )

    def _get_order_or_raise(self, order_id: str) -> Order:
        order = self.orders.get_order(order_id)
        if order is None:
            raise LookupError(f"Order '{order_id}' was not found.")
        return order

    def _merge_remote_snapshot(
        self,
        local_order: Order,
        remote_snapshot: BrokerOrderSnapshot,
    ) -> Order:
        refreshed_order = self._order_with_remote_snapshot(local_order, remote_snapshot)
        persisted_order = self.orders.update_order(refreshed_order)
        self._sync_execution_from_snapshot(persisted_order, remote_snapshot)
        return persisted_order

    @staticmethod
    def _order_with_remote_snapshot(
        local_order: Order,
        remote_snapshot: BrokerOrderSnapshot,
    ) -> Order:
        raw_payload = dict(local_order.raw_payload or {})
        raw_payload["remote_order"] = remote_snapshot.raw_payload
        raw_payload["refreshed_at"] = datetime.now(timezone.utc).isoformat()
        return local_order.model_copy(
            update={
                "external_order_id": remote_snapshot.external_order_id,
                "symbol": remote_snapshot.symbol,
                "side": remote_snapshot.side,
                "quantity": remote_snapshot.quantity,
                "order_type": remote_snapshot.order_type,
                "time_in_force": remote_snapshot.time_in_force,
                "status": remote_snapshot.status,
                "executed_quantity": remote_snapshot.executed_quantity,
                "executed_price": remote_snapshot.executed_price,
                "limit_price": remote_snapshot.limit_price,
                "stop_price": remote_snapshot.stop_price,
                "submitted_at": remote_snapshot.submitted_at,
                "raw_payload": raw_payload,
                "updated_at": datetime.now(timezone.utc),
            }
        )

    def _build_local_order(
        self,
        *,
        external_account_id: str,
        remote_snapshot: BrokerOrderSnapshot,
        mode: ExecutionMode,
    ) -> Order:
        now = datetime.now(timezone.utc)
        return Order(
            id=str(uuid4()),
            broker=BrokerName.LONGBRIDGE,
            external_account_id=external_account_id,
            trade_plan_id=None,
            external_order_id=remote_snapshot.external_order_id,
            client_order_id=f"import-{remote_snapshot.external_order_id}",
            symbol=remote_snapshot.symbol,
            asset_type=AssetType.STOCK,
            side=remote_snapshot.side,
            quantity=remote_snapshot.quantity,
            order_type=remote_snapshot.order_type,
            time_in_force=remote_snapshot.time_in_force,
            mode=mode,
            status=remote_snapshot.status,
            limit_price=remote_snapshot.limit_price,
            stop_price=remote_snapshot.stop_price,
            option_contract=None,
            raw_payload={
                "remote_order": remote_snapshot.raw_payload,
                "imported": True,
            },
            submitted_at=remote_snapshot.submitted_at,
            created_at=remote_snapshot.submitted_at or now,
            updated_at=now,
        )

    def _sync_execution_from_snapshot(
        self,
        order: Order,
        remote_snapshot: BrokerOrderSnapshot,
    ) -> None:
        if remote_snapshot.executed_quantity <= 0:
            return

        execution_scope = ":".join(
            (
                order.broker.value,
                order.mode.value,
                order.external_account_id,
                remote_snapshot.external_order_id or order.id,
            )
        )
        external_execution_id = (
            f"summary:v2:{hashlib.sha256(execution_scope.encode('utf-8')).hexdigest()[:40]}"
        )
        existing_execution = self.executions.get_by_external_execution_id(external_execution_id)
        now = datetime.now(timezone.utc)
        execution = Execution(
            id=existing_execution.id if existing_execution is not None else str(uuid4()),
            order_id=order.id,
            broker=order.broker,
            external_account_id=order.external_account_id,
            external_order_id=remote_snapshot.external_order_id,
            external_execution_id=external_execution_id,
            symbol=remote_snapshot.symbol,
            side=remote_snapshot.side,
            quantity=remote_snapshot.executed_quantity,
            price=remote_snapshot.executed_price,
            executed_at=remote_snapshot.updated_at or remote_snapshot.submitted_at,
            raw_payload={
                "source": "order_detail_summary",
                "remote_order": remote_snapshot.raw_payload,
            },
            created_at=existing_execution.created_at if existing_execution is not None else now,
            updated_at=now,
        )
        self.executions.upsert_execution(execution)

    @staticmethod
    def _request_hash(payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(canonical.encode("ascii")).hexdigest()

    @staticmethod
    def _broker_marker(
        *,
        external_account_id: str,
        mode: ExecutionMode,
        idempotency_key: str,
    ) -> str:
        material = f"{external_account_id}:{mode.value}:{idempotency_key}"
        return f"st:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"

    @staticmethod
    def _remark_with_marker(marker: str, remark: str | None) -> str:
        if not remark:
            return marker
        return f"{marker} {remark}"[:64]

    @staticmethod
    def _resolve_prepared_intent(
        prepared: PreparedBrokerOrderIntent,
        *,
        request_hash: str,
    ) -> Order | None:
        if prepared.intent.request_hash != request_hash:
            raise TradingIntentConflictError(prepared.intent.id)
        if prepared.created:
            return None
        if prepared.intent.state == TradingIntentState.PERSISTED and prepared.replayed_order is not None:
            return prepared.replayed_order
        if prepared.intent.state == TradingIntentState.REJECTED:
            raise TradingIntentRejectedError(prepared.intent.id, prepared.intent.last_error)
        if prepared.intent.state == TradingIntentState.RESOLVED_NO_ORDER:
            raise TradingIntentRejectedError(
                prepared.intent.id,
                "The prior broker mutation was resolved as having no broker order; use a new key.",
            )
        raise TradingIntentOutcomeUnknownError(prepared.intent.id)

    def _mark_unknown_safely(
        self,
        intent_id: str,
        exc: Exception,
        *,
        known_external_order_id: str | None = None,
        persist_exception_external_order_id: bool = True,
    ) -> None:
        if self.intent_ledger is None:
            return
        try:
            external_order_id = (
                (
                    getattr(exc, "external_order_id", None)
                    if persist_exception_external_order_id
                    else None
                )
                or known_external_order_id
            )
            if external_order_id is None:
                self.intent_ledger.mark_unknown(intent_id, str(exc))
            else:
                self.intent_ledger.mark_unknown(
                    intent_id,
                    str(exc),
                    external_order_id=str(external_order_id),
                )
        except Exception:
            logger.exception("Failed to mark trading intent '%s' unknown.", intent_id)

    @staticmethod
    def _build_order_audit_event(
        order: Order,
        *,
        action: str,
        before: dict | None,
        after: dict | None,
        summary: str,
    ) -> CreateStrategyAuditEventRequest | None:
        if order.mode != ExecutionMode.PAPER:
            return None
        warning_code = (
            f"order_{order.status.value}"
            if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
            else None
        )
        return CreateStrategyAuditEventRequest(
            external_account_id=order.external_account_id,
            mode=order.mode,
            actor="broker_gateway",
            source="orders",
            strategy="paper_order",
            action=action,
            before=before,
            after=after,
            order_ids=[order.id],
            warning_code=warning_code,
            summary=summary,
            payload={
                "symbol": order.symbol,
                "side": order.side.value,
                "status": order.status.value,
                "external_order_id": order.external_order_id,
            },
        )

    def _append_order_audit_event(
        self,
        order: Order,
        *,
        action: str,
        before: dict | None,
        after: dict | None,
        summary: str,
    ) -> None:
        if self.audit_events is None:
            return
        request = self._build_order_audit_event(
            order,
            action=action,
            before=before,
            after=after,
            summary=summary,
        )
        if request is None:
            return
        try:
            self.audit_events.create_event(request)
        except Exception:
            logger.exception("Failed to append order audit event '%s'.", action)

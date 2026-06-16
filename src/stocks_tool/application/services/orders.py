import logging
from datetime import datetime, timezone
from uuid import uuid4

from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import AssetType, BrokerName, ExecutionMode, ReconciliationStatus
from stocks_tool.domain.models import (
    BrokerOrderSnapshot,
    CreateStrategyAuditEventRequest,
    CreateOrderRequest,
    Execution,
    Order,
    OrderSyncResult,
    ReplaceOrderRequest,
)
from stocks_tool.ports.repository import (
    BrokerAccountRepository,
    ExecutionRepository,
    OrderRepository,
    StrategyAuditEventRepository,
    TradePlanRepository,
)
from stocks_tool.ports.broker_gateway import BrokerOrderGateway


logger = logging.getLogger(__name__)


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
    ) -> None:
        self.settings = settings
        self.broker_accounts = broker_accounts
        self.trade_plans = trade_plans
        self.orders = orders
        self.executions = executions
        self.longbridge_adapter = longbridge_adapter
        self.audit_events = audit_events

    def list_orders(
        self,
        external_account_id: str | None = None,
    ) -> list[Order]:
        return self.orders.list_orders(external_account_id=external_account_id)

    def get_order(self, order_id: str) -> Order | None:
        return self.orders.get_order(order_id)

    def submit_order(self, request: CreateOrderRequest) -> Order:
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

        remote_snapshot = self.longbridge_adapter.submit_order(request)
        now = datetime.now(timezone.utc)
        order = Order(
            id=str(uuid4()),
            broker=request.broker,
            external_account_id=request.external_account_id,
            trade_plan_id=request.trade_plan_id,
            external_order_id=remote_snapshot.external_order_id,
            client_order_id=f"local-{uuid4().hex[:24]}",
            symbol=remote_snapshot.symbol,
            asset_type=request.asset_type,
            side=remote_snapshot.side,
            quantity=remote_snapshot.quantity,
            order_type=remote_snapshot.order_type,
            time_in_force=remote_snapshot.time_in_force,
            mode=request.mode,
            status=remote_snapshot.status,
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

    def cancel_order(self, order_id: str) -> Order:
        order = self._get_order_or_raise(order_id)
        if order.external_order_id is None:
            raise ValueError(f"Order '{order_id}' has no broker order id to cancel.")
        if order.broker != BrokerName.LONGBRIDGE:
            raise NotImplementedError(f"Broker '{order.broker.value}' is not supported yet.")

        remote_snapshot = self.longbridge_adapter.cancel_order(
            external_order_id=order.external_order_id,
            mode=order.mode,
        )
        canceled = self._merge_remote_snapshot(order, remote_snapshot)
        self._append_order_audit_event(
            canceled,
            action="paper_order_canceled",
            before={"status": order.status.value},
            after={"status": canceled.status.value},
            summary=f"{canceled.symbol} {canceled.side.value} paper order cancel requested.",
        )
        return canceled

    def replace_order(self, order_id: str, request: ReplaceOrderRequest) -> Order:
        order = self._get_order_or_raise(order_id)
        if order.external_order_id is None:
            raise ValueError(f"Order '{order_id}' has no broker order id to replace.")
        if order.broker != BrokerName.LONGBRIDGE:
            raise NotImplementedError(f"Broker '{order.broker.value}' is not supported yet.")

        remote_snapshot = self.longbridge_adapter.replace_order(
            external_order_id=order.external_order_id,
            quantity=request.quantity,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            remark=request.remark,
            mode=order.mode,
        )
        replaced = order.model_copy(
            update={
                "quantity": request.quantity,
                "limit_price": request.limit_price,
                "stop_price": request.stop_price,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return self._merge_remote_snapshot(replaced, remote_snapshot)

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
                existing = self.orders.get_by_external_order_id(remote_snapshot.external_order_id)
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
        raw_payload = dict(local_order.raw_payload or {})
        raw_payload["remote_order"] = remote_snapshot.raw_payload
        raw_payload["refreshed_at"] = datetime.now(timezone.utc).isoformat()
        refreshed_order = local_order.model_copy(
            update={
                "external_order_id": remote_snapshot.external_order_id,
                "symbol": remote_snapshot.symbol,
                "side": remote_snapshot.side,
                "quantity": remote_snapshot.quantity,
                "order_type": remote_snapshot.order_type,
                "time_in_force": remote_snapshot.time_in_force,
                "status": remote_snapshot.status,
                "limit_price": remote_snapshot.limit_price,
                "stop_price": remote_snapshot.stop_price,
                "submitted_at": remote_snapshot.submitted_at,
                "raw_payload": raw_payload,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        persisted_order = self.orders.update_order(refreshed_order)
        self._sync_execution_from_snapshot(persisted_order, remote_snapshot)
        return persisted_order

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

        external_execution_id = (
            f"summary:{remote_snapshot.external_order_id}"
            if remote_snapshot.external_order_id
            else f"summary:{order.id}"
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

    def _append_order_audit_event(
        self,
        order: Order,
        *,
        action: str,
        before: dict | None,
        after: dict | None,
        summary: str,
    ) -> None:
        if self.audit_events is None or order.mode != ExecutionMode.PAPER:
            return
        warning_code = (
            f"order_{order.status.value}"
            if order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}
            else None
        )
        try:
            self.audit_events.create_event(
                CreateStrategyAuditEventRequest(
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
            )
        except Exception:
            logger.exception("Failed to append order audit event '%s'.", action)

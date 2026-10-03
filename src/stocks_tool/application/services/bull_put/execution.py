from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal

from stocks_tool.application.services.orders import OrderService
from stocks_tool.application.services.strategy_idempotency import strategy_order_identity
from stocks_tool.application.services.strategy_lifecycle import (
    bull_put_close_order_lifecycle_payload,
    bull_put_close_order_warning,
    bull_put_lifecycle_summary,
)
from stocks_tool.core.config import BullPutSpreadStrategySettings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    SpreadStatus,
    TimeInForce,
)
from stocks_tool.domain.models import (
    BullPutSpread,
    CreateOrderRequest,
    OptionContractRef,
    OptionMarketSnapshot,
    Order,
)
from stocks_tool.ports.broker_gateway import BrokerMarketDataGateway
from stocks_tool.ports.repository import BullPutSpreadRepository


class BullPutExecutionSupport:
    """Shared order, quote, lifecycle and CAS operations for Bull Put actions."""

    def __init__(
        self,
        *,
        strategy_settings: BullPutSpreadStrategySettings,
        orders: OrderService,
        spreads: BullPutSpreadRepository,
        market_data: BrokerMarketDataGateway,
    ) -> None:
        self.strategy_settings = strategy_settings
        self.orders = orders
        self.spreads = spreads
        self.market_data = market_data

    def update_spread(self, spread: BullPutSpread, **updates: object) -> BullPutSpread:
        if "raw_payload" in updates:
            updates.update(bull_put_lifecycle_summary(updates["raw_payload"]))
        next_spread = spread.model_copy(update=updates)
        return self.spreads.update_spread(next_spread, expected_version=spread.version)

    def build_leg_order_request(
        self,
        *,
        external_account_id: str,
        leg: OptionMarketSnapshot,
        side: OrderSide,
        quantity: int,
        mode: ExecutionMode,
        order_type: OrderType,
        limit_price: Decimal | None,
        remark: str | None,
    ) -> CreateOrderRequest:
        return CreateOrderRequest(
            external_account_id=external_account_id,
            broker=BrokerName.LONGBRIDGE,
            symbol=leg.symbol,
            asset_type=AssetType.OPTION,
            side=side,
            quantity=quantity,
            order_type=order_type,
            time_in_force=TimeInForce.DAY,
            mode=mode,
            limit_price=limit_price,
            option_contract=OptionContractRef(
                underlying_symbol=leg.underlying_symbol,
                expiration_date=leg.expiration_date,
                strike=leg.strike,
                right=leg.right,
            ),
            remark=remark,
        )

    def build_spread_leg_snapshot(
        self,
        spread: BullPutSpread,
        *,
        symbol: str,
        strike: Decimal,
    ) -> OptionMarketSnapshot:
        return OptionMarketSnapshot(
            symbol=symbol,
            underlying_symbol=spread.underlying_symbol,
            expiration_date=spread.expiration_date,
            strike=strike,
            right=OptionRight.PUT,
            last_done=Decimal("0"),
            prev_close=Decimal("0"),
            open=Decimal("0"),
            high=Decimal("0"),
            low=Decimal("0"),
            timestamp=datetime.now(timezone.utc),
            volume=0,
            turnover=Decimal("0"),
            contract_multiplier=Decimal("100"),
        )

    def with_top_of_book(
        self,
        quote: OptionMarketSnapshot,
        *,
        mode: ExecutionMode,
    ) -> OptionMarketSnapshot:
        if quote.bid is not None and quote.ask is not None:
            return quote
        bid, ask = self.market_data.get_best_bid_ask(symbol=quote.symbol, mode=mode)
        return quote.model_copy(update={"bid": bid, "ask": ask})

    def load_spread_leg_quotes(
        self,
        spread: BullPutSpread,
    ) -> tuple[OptionMarketSnapshot, OptionMarketSnapshot]:
        quotes = self.market_data.get_option_market_snapshots(
            symbols=[spread.short_symbol, spread.long_symbol],
            mode=spread.mode,
        )
        quotes_by_symbol = {quote.symbol: quote for quote in quotes}
        short_leg = quotes_by_symbol.get(spread.short_symbol)
        long_leg = quotes_by_symbol.get(spread.long_symbol)
        if short_leg is None or long_leg is None:
            raise LookupError(f"Could not load option quotes for spread '{spread.id}'.")
        return (
            self.with_top_of_book(short_leg, mode=spread.mode),
            self.with_top_of_book(long_leg, mode=spread.mode),
        )

    def await_terminal_or_fill(self, order: Order) -> Order:
        current = order
        if self.is_terminal(current) or self.is_filled(current):
            return current
        deadline = time.monotonic() + self.strategy_settings.entry_fill_timeout_seconds
        first_refresh = True
        while True:
            if not first_refresh and self.strategy_settings.entry_fill_poll_interval_seconds > 0:
                time.sleep(self.strategy_settings.entry_fill_poll_interval_seconds)
            first_refresh = False
            current = self.orders.refresh_order(current.id)
            if self.is_terminal(current) or self.is_filled(current):
                return current
            if time.monotonic() >= deadline:
                return current

    def cancel_if_working(
        self,
        order: Order,
        *,
        parent_action_intent_id: str | None = None,
        parent_entity_id: str | None = None,
    ) -> Order | None:
        if not self.is_working(order):
            return order
        idempotency_key, action_context = strategy_order_identity(
            strategy_id="paper_bull_put_v1",
            entity_id=order.id,
            action="bull_put_cancel",
            leg=order.symbol,
        )
        if parent_entity_id is not None:
            action_context = action_context.model_copy(update={"entity_id": parent_entity_id})
        return self.orders.cancel_order(
            order.id,
            idempotency_key=idempotency_key,
            action_context=action_context,
            parent_action_intent_id=parent_action_intent_id,
        )

    def lifecycle_payload_for_close_order_state(
        self,
        *,
        spread: BullPutSpread,
        status: SpreadStatus,
        short_exit_order: Order | None,
    ) -> dict | None:
        warning = bull_put_close_order_warning(
            spread_status=status,
            short_exit_order_id=spread.short_exit_order_id,
            short_exit_order_status=short_exit_order.status if short_exit_order is not None else None,
            short_symbol=spread.short_symbol,
            raw_payload=spread.raw_payload,
            exit_reason=spread.exit_reason,
        )
        return bull_put_close_order_lifecycle_payload(
            raw_payload=spread.raw_payload,
            warning=warning,
        )

    @staticmethod
    def effective_fill_price(order: Order | None) -> Decimal | None:
        if order is None:
            return None
        if order.status not in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}:
            return None
        raw_payload = order.raw_payload or {}
        remote_order = raw_payload.get("remote_order") or {}
        if remote_order.get("executed_price") is not None:
            return Decimal(str(remote_order["executed_price"]))
        if order.limit_price is not None:
            return order.limit_price
        return None

    @staticmethod
    def is_filled(order: Order | None) -> bool:
        return order is not None and order.status == OrderStatus.FILLED

    @staticmethod
    def is_working(order: Order | None) -> bool:
        return order is not None and order.status in {
            OrderStatus.CREATED,
            OrderStatus.SUBMITTED,
            OrderStatus.PARTIALLY_FILLED,
        }

    @staticmethod
    def is_terminal(order: Order | None) -> bool:
        return order is not None and order.status in {
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
        }

    @staticmethod
    def is_failed_or_expired_close_order(
        *,
        spread: BullPutSpread,
        order: Order | None,
    ) -> bool:
        if order is not None and order.status in {OrderStatus.CANCELED, OrderStatus.REJECTED}:
            return True
        status_text = str(spread.latest_close_order_status or "").strip().lower()
        return status_text in {"canceled", "cancelled", "rejected", "expired"}

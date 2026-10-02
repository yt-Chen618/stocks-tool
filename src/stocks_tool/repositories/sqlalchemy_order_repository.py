from collections.abc import Collection
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import exists, select, tuple_
from sqlalchemy.orm import Session, selectinload

from stocks_tool.db.models import BrokerAccountRecord, OrderRecord
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from stocks_tool.domain.models import OptionContractRef, Order
from stocks_tool.domain.pagination import (
    CursorPage,
    decode_cursor,
    encode_cursor,
    normalize_page_limit,
)
from stocks_tool.ports.repository import OrderRepository


class SQLAlchemyOrderRepository(OrderRepository):
    def __init__(self, session: Session, *, attach_intent_ledger: bool = True) -> None:
        self.session = session
        self.trading_intent_ledger = None
        if attach_intent_ledger:
            from stocks_tool.repositories.sqlalchemy_trading_intent_ledger import (
                SQLAlchemyTradingIntentLedger,
            )

            self.trading_intent_ledger = SQLAlchemyTradingIntentLedger(session)

    def create_order(self, order: Order) -> Order:
        record = OrderRecord(id=order.id or str(uuid4()))
        self.session.add(record)
        self._apply_order(record, order)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def get_order(self, order_id: str) -> Order | None:
        record = self.session.execute(
            select(OrderRecord)
            .options(selectinload(OrderRecord.broker_account))
            .where(OrderRecord.id == order_id)
        ).scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    def get_by_external_order_id(
        self,
        external_order_id: str,
        *,
        broker: BrokerName,
        mode: ExecutionMode,
    ) -> Order | None:
        record = self.session.execute(
            select(OrderRecord)
            .options(selectinload(OrderRecord.broker_account))
            .where(
                OrderRecord.external_order_id == external_order_id,
                OrderRecord.broker == broker.value,
                OrderRecord.execution_mode == mode.value,
            )
        ).scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    def list_orders(
        self,
        external_account_id: str | None = None,
        status: OrderStatus | None = None,
        *,
        broker: BrokerName | None = None,
        mode: ExecutionMode | None = None,
        symbol: str | None = None,
        symbols: Collection[str] | None = None,
        statuses: Collection[OrderStatus] | None = None,
        order_ids: Collection[str] | None = None,
        order_intent_ids: Collection[str] | None = None,
    ) -> list[Order]:
        query = select(OrderRecord).order_by(OrderRecord.created_at.desc(), OrderRecord.id.desc())
        query = query.options(selectinload(OrderRecord.broker_account))
        if external_account_id is not None:
            account_ids = select(BrokerAccountRecord.id).where(
                BrokerAccountRecord.external_account_id == external_account_id
            )
            query = query.where(OrderRecord.broker_account_id.in_(account_ids))
        if broker is not None:
            query = query.where(OrderRecord.broker == broker.value)
        if mode is not None:
            query = query.where(OrderRecord.execution_mode == mode.value)
        if status is not None:
            query = query.where(OrderRecord.status == status.value)
        if statuses is not None:
            normalized_statuses = [item.value for item in statuses]
            if not normalized_statuses:
                return []
            query = query.where(OrderRecord.status.in_(normalized_statuses))
        if symbol is not None:
            query = query.where(OrderRecord.symbol == symbol.strip().upper())
        if symbols is not None:
            normalized_symbols = [item.strip().upper() for item in symbols if item.strip()]
            if not normalized_symbols:
                return []
            query = query.where(OrderRecord.symbol.in_(normalized_symbols))
        if order_ids is not None:
            normalized_ids = [str(item) for item in order_ids if str(item)]
            if not normalized_ids:
                return []
            query = query.where(OrderRecord.id.in_(normalized_ids))
        if order_intent_ids is not None:
            normalized_intent_ids = [str(item) for item in order_intent_ids if str(item)]
            if not normalized_intent_ids:
                return []
            query = query.where(OrderRecord.order_intent_id.in_(normalized_intent_ids))
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

    def iter_orders(
        self,
        *,
        external_account_id: str | None = None,
        mode: ExecutionMode | None = None,
    ):
        query = select(OrderRecord).order_by(OrderRecord.created_at.desc(), OrderRecord.id.desc())
        query = query.options(selectinload(OrderRecord.broker_account))
        if external_account_id is not None:
            account_ids = select(BrokerAccountRecord.id).where(
                BrokerAccountRecord.external_account_id == external_account_id
            )
            query = query.where(OrderRecord.broker_account_id.in_(account_ids))
        if mode is not None:
            query = query.where(OrderRecord.execution_mode == mode.value)
        result = self.session.execute(
            query.execution_options(stream_results=True, yield_per=200)
        ).scalars()
        for record in result:
            yield self._to_domain(record)

    def list_orders_page(
        self,
        *,
        external_account_id: str | None = None,
        status: OrderStatus | None = None,
        mode: ExecutionMode | None = None,
        symbol: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> CursorPage[Order]:
        page_limit = normalize_page_limit(limit)
        normalized_symbol = symbol.strip().upper() if symbol is not None else None
        scope = {
            "external_account_id": external_account_id,
            "status": status.value if status is not None else None,
            "mode": mode.value if mode is not None else None,
            "symbol": normalized_symbol,
        }
        cursor_position: dict[str, object] | None = None
        if cursor is not None:
            cursor_position = decode_cursor(cursor, resource="orders", scope=scope)
        account_ids: list[str] | None = None
        if external_account_id is not None:
            account_ids = list(
                self.session.execute(
                    select(BrokerAccountRecord.id).where(
                        BrokerAccountRecord.external_account_id == external_account_id
                    )
                ).scalars()
            )
            if not account_ids:
                return CursorPage(items=[], next_cursor=None, has_more=False, limit=page_limit)
        query = select(OrderRecord.id).order_by(OrderRecord.created_at.desc(), OrderRecord.id.desc())
        if account_ids is not None:
            query = query.where(OrderRecord.broker_account_id.in_(account_ids))
        if status is not None:
            query = query.where(OrderRecord.status == status.value)
        if mode is not None:
            query = query.where(OrderRecord.execution_mode == mode.value)
        if normalized_symbol is not None:
            query = query.where(OrderRecord.symbol == normalized_symbol)
        if cursor_position is not None:
            try:
                created_at = datetime.fromisoformat(str(cursor_position["created_at"]))
                order_id = str(cursor_position["id"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("Invalid pagination cursor position.") from exc
            query = query.where(tuple_(OrderRecord.created_at, OrderRecord.id) < (created_at, order_id))
        record_ids = self.session.execute(query.limit(page_limit + 1)).scalars().all()
        has_more = len(record_ids) > page_limit
        record_ids = record_ids[:page_limit]
        if record_ids:
            record_by_id = {
                record.id: record
                for record in self.session.execute(
                    select(OrderRecord)
                    .options(selectinload(OrderRecord.broker_account))
                    .where(OrderRecord.id.in_(record_ids))
                ).scalars().all()
            }
            records = [record_by_id[record_id] for record_id in record_ids]
        else:
            records = []
        items = [self._to_domain(record) for record in records]
        next_cursor = None
        if has_more and records:
            last = records[-1]
            next_cursor = encode_cursor(
                resource="orders",
                scope=scope,
                position={"created_at": last.created_at.isoformat(), "id": last.id},
            )
        return CursorPage(
            items=items,
            next_cursor=next_cursor,
            has_more=has_more,
            limit=page_limit,
        )

    def has_working_orders(
        self,
        external_account_id: str,
        *,
        broker: BrokerName,
        mode: ExecutionMode,
        statuses: Collection[OrderStatus],
    ) -> bool:
        """Check for a matching order without materializing the order history."""
        matching_orders = (
            select(OrderRecord.id)
            .join(BrokerAccountRecord, OrderRecord.broker_account_id == BrokerAccountRecord.id)
            .where(BrokerAccountRecord.external_account_id == external_account_id)
        )
        matching_orders = matching_orders.where(
            BrokerAccountRecord.broker == broker.value,
            OrderRecord.execution_mode == mode.value,
        )
        status_values = [value.value for value in statuses]
        if not status_values:
            return False
        matching_orders = matching_orders.where(OrderRecord.status.in_(status_values))
        query = select(exists(matching_orders))
        return bool(self.session.execute(query).scalar_one())

    def update_order(self, order: Order) -> Order:
        record = self.session.get(OrderRecord, order.id)
        if record is None:
            raise ValueError(f"Order '{order.id}' was not found.")
        self._apply_order(record, order)
        self.session.commit()
        return self.get_order(record.id) or self._to_domain(record)

    @staticmethod
    def _resolve_broker_account_id(session: Session, order: Order) -> str | None:
        broker_account = session.execute(
            select(BrokerAccountRecord).where(
                BrokerAccountRecord.broker == order.broker.value,
                BrokerAccountRecord.external_account_id == order.external_account_id,
            )
        ).scalar_one_or_none()
        return broker_account.id if broker_account is not None else None

    def _apply_order(self, record: OrderRecord, order: Order) -> None:
        record.broker_account_id = self._resolve_broker_account_id(self.session, order)
        record.broker = order.broker.value
        record.trade_plan_id = order.trade_plan_id
        record.external_order_id = order.external_order_id
        record.client_order_id = order.client_order_id
        record.order_intent_id = order.order_intent_id
        record.symbol = order.symbol
        record.asset_type = order.asset_type.value if order.asset_type is not None else None
        record.side = order.side.value
        record.quantity = order.quantity
        record.order_type = order.order_type.value
        record.time_in_force = order.time_in_force.value
        record.execution_mode = order.mode.value
        record.limit_price = order.limit_price
        record.stop_price = order.stop_price
        record.status = order.status.value
        record.executed_quantity = order.executed_quantity
        record.executed_price = order.executed_price
        record.raw_payload = order.raw_payload
        record.submitted_at = order.submitted_at

        if order.option_contract is not None:
            record.option_underlying_symbol = order.option_contract.underlying_symbol
            record.option_expiration_date = order.option_contract.expiration_date
            record.option_strike = order.option_contract.strike
            record.option_right = order.option_contract.right.value
        else:
            record.option_underlying_symbol = None
            record.option_expiration_date = None
            record.option_strike = None
            record.option_right = None

    @staticmethod
    def _to_domain(record: OrderRecord) -> Order:
        option_contract = None
        if (
            record.option_underlying_symbol is not None
            and record.option_expiration_date is not None
            and record.option_strike is not None
            and record.option_right is not None
        ):
            option_contract = OptionContractRef(
                underlying_symbol=record.option_underlying_symbol,
                expiration_date=record.option_expiration_date,
                strike=Decimal(record.option_strike),
                right=OptionRight(record.option_right),
            )

        return Order(
            id=record.id,
            broker=BrokerName(record.broker),
            external_account_id=(
                record.broker_account.external_account_id
                if record.broker_account is not None
                else ""
            ),
            trade_plan_id=record.trade_plan_id,
            external_order_id=record.external_order_id,
            client_order_id=record.client_order_id,
            order_intent_id=record.order_intent_id,
            symbol=record.symbol,
            asset_type=AssetType(record.asset_type) if record.asset_type is not None else None,
            side=OrderSide(record.side),
            quantity=record.quantity,
            order_type=OrderType(record.order_type),
            time_in_force=TimeInForce(record.time_in_force),
            mode=ExecutionMode(record.execution_mode),
            status=OrderStatus(record.status),
            executed_quantity=record.executed_quantity,
            executed_price=Decimal(record.executed_price) if record.executed_price is not None else None,
            limit_price=Decimal(record.limit_price) if record.limit_price is not None else None,
            stop_price=Decimal(record.stop_price) if record.stop_price is not None else None,
            option_contract=option_contract,
            raw_payload=record.raw_payload,
            submitted_at=record.submitted_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
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
from stocks_tool.ports.repository import OrderRepository


class SQLAlchemyOrderRepository(OrderRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

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

    def get_by_external_order_id(self, external_order_id: str) -> Order | None:
        record = self.session.execute(
            select(OrderRecord)
            .options(selectinload(OrderRecord.broker_account))
            .where(OrderRecord.external_order_id == external_order_id)
        ).scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    def list_orders(
        self,
        external_account_id: str | None = None,
        status: OrderStatus | None = None,
    ) -> list[Order]:
        query = select(OrderRecord).order_by(OrderRecord.created_at.desc())
        query = query.options(selectinload(OrderRecord.broker_account))
        if external_account_id is not None:
            query = query.join(BrokerAccountRecord).where(
                BrokerAccountRecord.external_account_id == external_account_id
            )
        if status is not None:
            query = query.where(OrderRecord.status == status.value)
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

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
            symbol=record.symbol,
            asset_type=AssetType(record.asset_type) if record.asset_type is not None else None,
            side=OrderSide(record.side),
            quantity=record.quantity,
            order_type=OrderType(record.order_type),
            time_in_force=TimeInForce(record.time_in_force),
            mode=ExecutionMode(record.execution_mode),
            status=OrderStatus(record.status),
            limit_price=Decimal(record.limit_price) if record.limit_price is not None else None,
            stop_price=Decimal(record.stop_price) if record.stop_price is not None else None,
            option_contract=option_contract,
            raw_payload=record.raw_payload,
            submitted_at=record.submitted_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

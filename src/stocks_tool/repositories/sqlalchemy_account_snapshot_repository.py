from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from stocks_tool.db.models import (
    AccountSnapshotRecord,
    BrokerAccountRecord,
    PositionSnapshotRecord,
)
from stocks_tool.domain.enums import AssetType, BrokerName
from stocks_tool.domain.models import AccountSnapshot, PositionSnapshot
from stocks_tool.ports.repository import AccountSnapshotRepository


class SQLAlchemyAccountSnapshotRepository(AccountSnapshotRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_account_snapshot(self, snapshot: AccountSnapshot) -> AccountSnapshot:
        broker_account = self.session.execute(
            select(BrokerAccountRecord).where(
                BrokerAccountRecord.broker == snapshot.broker.value,
                BrokerAccountRecord.external_account_id == snapshot.account_id,
            )
        ).scalar_one_or_none()

        record = AccountSnapshotRecord(
            broker_account_id=broker_account.id if broker_account is not None else None,
            broker=snapshot.broker.value,
            external_account_id=snapshot.account_id,
            currency=snapshot.currency,
            cash_balance=snapshot.cash_balance,
            net_liquidation=snapshot.net_liquidation,
            buying_power=snapshot.buying_power,
            day_trade_buying_power=snapshot.day_trade_buying_power,
            options_level=snapshot.options_level,
            raw_payload=snapshot.raw_payload,
            captured_at=snapshot.captured_at,
        )
        self.session.add(record)
        self.session.flush()

        for position in snapshot.positions:
            self.session.add(
                PositionSnapshotRecord(
                    account_snapshot_id=record.id,
                    symbol=position.symbol,
                    asset_type=position.asset_type.value,
                    quantity=position.quantity,
                    average_cost=position.average_cost,
                    market_value=position.market_value,
                    unrealized_pnl=position.unrealized_pnl,
                    raw_payload=position.raw_payload,
                )
            )

        self.session.commit()

        refreshed = self.session.execute(
            select(AccountSnapshotRecord)
            .options(selectinload(AccountSnapshotRecord.positions))
            .where(AccountSnapshotRecord.id == record.id)
        ).scalars().unique().one()
        return self._to_domain(refreshed)

    def get_latest_account_snapshot(
        self,
        external_account_id: str,
    ) -> AccountSnapshot | None:
        query = (
            select(AccountSnapshotRecord)
            .options(selectinload(AccountSnapshotRecord.positions))
            .where(AccountSnapshotRecord.external_account_id == external_account_id)
            .order_by(AccountSnapshotRecord.captured_at.desc())
            .limit(1)
        )
        record = self.session.execute(query).scalars().unique().first()
        if record is None:
            return None
        return self._to_domain(record)

    def list_account_snapshots(
        self,
        external_account_id: str | None = None,
    ) -> list[AccountSnapshot]:
        query = (
            select(AccountSnapshotRecord)
            .options(selectinload(AccountSnapshotRecord.positions))
            .order_by(AccountSnapshotRecord.captured_at.desc())
        )
        if external_account_id is not None:
            query = query.where(AccountSnapshotRecord.external_account_id == external_account_id)

        records = self.session.execute(query).scalars().unique().all()
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _to_domain(record: AccountSnapshotRecord) -> AccountSnapshot:
        return AccountSnapshot(
            id=record.id,
            broker=BrokerName(record.broker),
            account_id=record.external_account_id,
            currency=record.currency,
            cash_balance=Decimal(record.cash_balance),
            net_liquidation=Decimal(record.net_liquidation),
            buying_power=Decimal(record.buying_power),
            day_trade_buying_power=(
                Decimal(record.day_trade_buying_power)
                if record.day_trade_buying_power is not None
                else None
            ),
            options_level=record.options_level,
            positions=[
                PositionSnapshot(
                    symbol=position.symbol,
                    asset_type=AssetType(position.asset_type),
                    quantity=Decimal(position.quantity),
                    average_cost=Decimal(position.average_cost),
                    market_value=Decimal(position.market_value),
                    unrealized_pnl=Decimal(position.unrealized_pnl),
                    raw_payload=position.raw_payload,
                )
                for position in sorted(record.positions, key=lambda value: value.symbol)
            ],
            raw_payload=record.raw_payload,
            captured_at=record.captured_at,
        )

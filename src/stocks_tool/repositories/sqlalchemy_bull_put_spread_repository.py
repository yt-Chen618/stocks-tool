from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.application.services.strategy_lifecycle import bull_put_lifecycle_summary
from stocks_tool.db.models import BrokerAccountRecord, BullPutSpreadRecord
from stocks_tool.domain.enums import BrokerName, ExecutionMode, SpreadStatus
from stocks_tool.domain.models import BullPutSpread
from stocks_tool.ports.repository import BullPutSpreadRepository


class SQLAlchemyBullPutSpreadRepository(BullPutSpreadRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_spread(self, spread: BullPutSpread) -> BullPutSpread:
        record = BullPutSpreadRecord(id=spread.id)
        self.session.add(record)
        self._apply_spread(record, spread)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def get_spread(self, spread_id: str) -> BullPutSpread | None:
        record = self.session.get(BullPutSpreadRecord, spread_id)
        if record is None:
            return None
        return self._to_domain(record)

    def list_spreads(
        self,
        external_account_id: str | None = None,
        status: SpreadStatus | None = None,
    ) -> list[BullPutSpread]:
        query = select(BullPutSpreadRecord).order_by(BullPutSpreadRecord.created_at.desc())
        if external_account_id is not None:
            query = query.where(BullPutSpreadRecord.external_account_id == external_account_id)
        if status is not None:
            query = query.where(BullPutSpreadRecord.status == status.value)
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

    def update_spread(self, spread: BullPutSpread) -> BullPutSpread:
        record = self.session.get(BullPutSpreadRecord, spread.id)
        if record is None:
            raise ValueError(f"Bull put spread '{spread.id}' was not found.")
        self._apply_spread(record, spread)
        self.session.commit()
        return self.get_spread(record.id) or self._to_domain(record)

    @staticmethod
    def _resolve_broker_account_id(session: Session, spread: BullPutSpread) -> str | None:
        broker_account = session.execute(
            select(BrokerAccountRecord).where(
                BrokerAccountRecord.broker == spread.broker.value,
                BrokerAccountRecord.external_account_id == spread.external_account_id,
            )
        ).scalar_one_or_none()
        return broker_account.id if broker_account is not None else None

    def _apply_spread(self, record: BullPutSpreadRecord, spread: BullPutSpread) -> None:
        record.broker_account_id = self._resolve_broker_account_id(self.session, spread)
        record.broker = spread.broker.value
        record.external_account_id = spread.external_account_id
        record.strategy_id = spread.strategy_id
        record.execution_mode = spread.mode.value
        record.underlying_symbol = spread.underlying_symbol
        record.expiration_date = spread.expiration_date
        record.contracts = spread.contracts
        record.width = spread.width
        record.long_symbol = spread.long_symbol
        record.long_strike = spread.long_strike
        record.short_symbol = spread.short_symbol
        record.short_strike = spread.short_strike
        record.status = spread.status.value
        record.long_entry_order_id = spread.long_entry_order_id
        record.short_entry_order_id = spread.short_entry_order_id
        record.long_exit_order_id = spread.long_exit_order_id
        record.short_exit_order_id = spread.short_exit_order_id
        record.entry_long_price = spread.entry_long_price
        record.entry_short_price = spread.entry_short_price
        record.entry_net_credit = spread.entry_net_credit
        record.max_profit = spread.max_profit
        record.max_loss = spread.max_loss
        record.break_even = spread.break_even
        record.account_risk_pct = spread.account_risk_pct
        record.exit_reason = spread.exit_reason
        record.raw_payload = spread.raw_payload
        if spread.raw_payload is not None:
            lifecycle_summary = bull_put_lifecycle_summary(spread.raw_payload)
        else:
            lifecycle_summary = {
                "lifecycle_warning_code": spread.lifecycle_warning_code,
                "manual_action_required": spread.manual_action_required,
                "latest_monitor_should_close": spread.latest_monitor_should_close,
                "latest_close_order_status": spread.latest_close_order_status,
                "next_monitor_after": spread.next_monitor_after,
            }
        record.lifecycle_warning_code = lifecycle_summary["lifecycle_warning_code"]
        record.manual_action_required = bool(lifecycle_summary["manual_action_required"])
        record.latest_monitor_should_close = lifecycle_summary["latest_monitor_should_close"]
        record.latest_close_order_status = lifecycle_summary["latest_close_order_status"]
        record.next_monitor_after = lifecycle_summary["next_monitor_after"]
        record.entry_started_at = spread.entry_started_at
        record.opened_at = spread.opened_at
        record.closed_at = spread.closed_at
        record.last_synced_at = spread.last_synced_at

    @staticmethod
    def _to_domain(record: BullPutSpreadRecord) -> BullPutSpread:
        return BullPutSpread(
            id=record.id,
            strategy_id=record.strategy_id,
            broker=BrokerName(record.broker),
            external_account_id=record.external_account_id,
            mode=ExecutionMode(record.execution_mode),
            underlying_symbol=record.underlying_symbol,
            expiration_date=record.expiration_date,
            contracts=record.contracts,
            width=Decimal(record.width),
            long_symbol=record.long_symbol,
            long_strike=Decimal(record.long_strike),
            short_symbol=record.short_symbol,
            short_strike=Decimal(record.short_strike),
            status=SpreadStatus(record.status),
            long_entry_order_id=record.long_entry_order_id,
            short_entry_order_id=record.short_entry_order_id,
            long_exit_order_id=record.long_exit_order_id,
            short_exit_order_id=record.short_exit_order_id,
            entry_long_price=Decimal(record.entry_long_price) if record.entry_long_price is not None else None,
            entry_short_price=Decimal(record.entry_short_price) if record.entry_short_price is not None else None,
            entry_net_credit=Decimal(record.entry_net_credit) if record.entry_net_credit is not None else None,
            max_profit=Decimal(record.max_profit) if record.max_profit is not None else None,
            max_loss=Decimal(record.max_loss) if record.max_loss is not None else None,
            break_even=Decimal(record.break_even) if record.break_even is not None else None,
            account_risk_pct=Decimal(record.account_risk_pct) if record.account_risk_pct is not None else None,
            exit_reason=record.exit_reason,
            lifecycle_warning_code=record.lifecycle_warning_code,
            manual_action_required=record.manual_action_required,
            latest_monitor_should_close=record.latest_monitor_should_close,
            latest_close_order_status=record.latest_close_order_status,
            next_monitor_after=record.next_monitor_after,
            raw_payload=record.raw_payload,
            entry_started_at=record.entry_started_at,
            opened_at=record.opened_at,
            closed_at=record.closed_at,
            last_synced_at=record.last_synced_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import TradePlanRecord
from stocks_tool.domain.enums import (
    AssetType,
    CatalystType,
    MarketBias,
    OptionRight,
    PlanStatus,
    TradeStructure,
)
from stocks_tool.domain.models import OptionContractRef, PriceBand, TradePlan
from stocks_tool.ports.repository import TradePlanRepository


class SQLAlchemyTradePlanRepository(TradePlanRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def save_plan(self, plan: TradePlan) -> TradePlan:
        record = self.session.get(TradePlanRecord, plan.id)
        if record is None:
            record = TradePlanRecord(id=plan.id)
            self.session.add(record)

        self._apply_plan(record, plan)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    def get_plan(self, plan_id: str) -> TradePlan | None:
        record = self.session.get(TradePlanRecord, plan_id)
        if record is None:
            return None
        return self._to_domain(record)

    def list_plans(self) -> list[TradePlan]:
        query = select(TradePlanRecord).order_by(TradePlanRecord.created_at.desc())
        records = self.session.execute(query).scalars().all()
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _apply_plan(record: TradePlanRecord, plan: TradePlan) -> None:
        record.symbol = plan.symbol
        record.asset_type = plan.asset_type.value
        record.structure = plan.structure.value
        record.bias = plan.bias.value
        record.catalyst_type = plan.catalyst_type.value
        record.thesis = plan.thesis
        record.entry_minimum = plan.entry.minimum
        record.entry_maximum = plan.entry.maximum
        record.stop_loss = plan.stop_loss
        record.take_profit = plan.take_profit
        record.invalidation = plan.invalidation
        record.holding_period_days = plan.holding_period_days
        record.max_account_risk_pct = plan.max_account_risk_pct
        record.estimated_max_loss = plan.estimated_max_loss
        record.notes = plan.notes
        record.status = plan.status.value
        record.created_at = plan.created_at

        if plan.option_contract is not None:
            record.option_underlying_symbol = plan.option_contract.underlying_symbol
            record.option_expiration_date = plan.option_contract.expiration_date
            record.option_strike = plan.option_contract.strike
            record.option_right = plan.option_contract.right.value
        else:
            record.option_underlying_symbol = None
            record.option_expiration_date = None
            record.option_strike = None
            record.option_right = None

    @staticmethod
    def _to_domain(record: TradePlanRecord) -> TradePlan:
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

        return TradePlan(
            id=record.id,
            symbol=record.symbol,
            asset_type=AssetType(record.asset_type),
            structure=TradeStructure(record.structure),
            bias=MarketBias(record.bias),
            thesis=record.thesis,
            catalyst_type=CatalystType(record.catalyst_type),
            entry=PriceBand(
                minimum=Decimal(record.entry_minimum) if record.entry_minimum is not None else None,
                maximum=Decimal(record.entry_maximum) if record.entry_maximum is not None else None,
            ),
            stop_loss=Decimal(record.stop_loss) if record.stop_loss is not None else None,
            take_profit=Decimal(record.take_profit) if record.take_profit is not None else None,
            invalidation=record.invalidation,
            holding_period_days=record.holding_period_days,
            max_account_risk_pct=Decimal(record.max_account_risk_pct),
            estimated_max_loss=Decimal(record.estimated_max_loss) if record.estimated_max_loss is not None else None,
            option_contract=option_contract,
            notes=record.notes,
            status=PlanStatus(record.status),
            created_at=record.created_at,
        )


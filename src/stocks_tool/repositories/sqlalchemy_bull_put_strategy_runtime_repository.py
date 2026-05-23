from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from stocks_tool.db.models import BrokerAccountRecord, BullPutStrategyRuntimeRecord
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import BullPutStrategyRuntimeState
from stocks_tool.ports.repository import BullPutStrategyRuntimeRepository


class SQLAlchemyBullPutStrategyRuntimeRepository(BullPutStrategyRuntimeRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_runtime_state(
        self,
        *,
        external_account_id: str,
        strategy_id: str = "paper_bull_put_v1",
    ) -> BullPutStrategyRuntimeState | None:
        record = self.session.execute(
            select(BullPutStrategyRuntimeRecord).where(
                BullPutStrategyRuntimeRecord.external_account_id == external_account_id,
                BullPutStrategyRuntimeRecord.strategy_id == strategy_id,
            )
        ).scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain(record)

    def upsert_runtime_state(
        self,
        state: BullPutStrategyRuntimeState,
    ) -> BullPutStrategyRuntimeState:
        record = self.session.get(BullPutStrategyRuntimeRecord, state.id)
        if record is None:
            record = self.session.execute(
                select(BullPutStrategyRuntimeRecord).where(
                    BullPutStrategyRuntimeRecord.external_account_id == state.external_account_id,
                    BullPutStrategyRuntimeRecord.strategy_id == state.strategy_id,
                )
            ).scalar_one_or_none()
        if record is None:
            record = BullPutStrategyRuntimeRecord(id=state.id)
            self.session.add(record)
        self._apply_state(record, state)
        self.session.commit()
        self.session.refresh(record)
        return self._to_domain(record)

    @staticmethod
    def _resolve_broker_account_id(session: Session, state: BullPutStrategyRuntimeState) -> str | None:
        broker_account = session.execute(
            select(BrokerAccountRecord).where(
                BrokerAccountRecord.external_account_id == state.external_account_id,
            )
        ).scalar_one_or_none()
        return broker_account.id if broker_account is not None else None

    def _apply_state(
        self,
        record: BullPutStrategyRuntimeRecord,
        state: BullPutStrategyRuntimeState,
    ) -> None:
        record.broker_account_id = self._resolve_broker_account_id(self.session, state)
        record.strategy_id = state.strategy_id
        record.external_account_id = state.external_account_id
        record.execution_mode = state.mode.value
        record.auto_entry_enabled = state.auto_entry_enabled
        record.manual_pause = state.manual_pause
        record.kill_switch_active = state.kill_switch_active
        record.paused_symbols = state.paused_symbols
        record.current_session_date = state.current_session_date
        record.daily_entry_count = state.daily_entry_count
        record.daily_realized_pnl = state.daily_realized_pnl
        record.last_scan_at = state.last_scan_at
        record.last_scan_result = state.last_scan_result
        record.last_scan_symbol = state.last_scan_symbol
        record.last_skip_reason = state.last_skip_reason
        record.last_action_at = state.last_action_at
        record.last_action = state.last_action
        record.last_review_at = state.last_review_at
        record.last_review_status = state.last_review_status
        record.last_review_summary = state.last_review_summary
        record.last_error = state.last_error

    @staticmethod
    def _to_domain(record: BullPutStrategyRuntimeRecord) -> BullPutStrategyRuntimeState:
        return BullPutStrategyRuntimeState(
            id=record.id,
            strategy_id=record.strategy_id,
            external_account_id=record.external_account_id,
            mode=ExecutionMode(record.execution_mode),
            auto_entry_enabled=record.auto_entry_enabled,
            manual_pause=record.manual_pause,
            kill_switch_active=record.kill_switch_active,
            paused_symbols=list(record.paused_symbols or []),
            current_session_date=record.current_session_date,
            daily_entry_count=record.daily_entry_count,
            daily_realized_pnl=Decimal(record.daily_realized_pnl),
            last_scan_at=record.last_scan_at,
            last_scan_result=record.last_scan_result,
            last_scan_symbol=record.last_scan_symbol,
            last_skip_reason=record.last_skip_reason,
            last_action_at=record.last_action_at,
            last_action=record.last_action,
            last_review_at=record.last_review_at,
            last_review_status=record.last_review_status,
            last_review_summary=record.last_review_summary,
            last_error=record.last_error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

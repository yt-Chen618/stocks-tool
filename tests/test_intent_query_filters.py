from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.application.services.orders import OrderService
from stocks_tool.core.config import Settings
from stocks_tool.db.base import Base
from stocks_tool.db.models import (
    BrokerAccountRecord,
    OrderIntentRecord,
    TradeActionIntentRecord,
)
from stocks_tool.domain.enums import (
    BrokerName,
    ExecutionMode,
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.repositories.sqlalchemy_trading_intent_ledger import (
    SQLAlchemyTradingIntentLedger,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


ACCOUNT_ID = "LBPT10087357"
NOW = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)


def test_intent_query_pushes_states_and_operation_without_changing_default_cap() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                BrokerAccountRecord(
                    id="broker-account-1",
                    broker=BrokerName.LONGBRIDGE.value,
                    external_account_id=ACCOUNT_ID,
                )
            )
            session.add(
                TradeActionIntentRecord(
                    id="action-1",
                    broker_account_id="broker-account-1",
                    external_account_id=ACCOUNT_ID,
                    broker=BrokerName.LONGBRIDGE.value,
                    execution_mode=ExecutionMode.PAPER.value,
                    idempotency_key="action-key-1",
                    request_hash="a" * 64,
                    action="order_submit",
                    state=TradingIntentState.UNKNOWN.value,
                    request_payload={},
                )
            )
            intents = []
            for index in range(620):
                is_matching = index == 0
                intents.append(
                    OrderIntentRecord(
                        id=f"intent-{index:04d}",
                        trade_action_intent_id="action-1",
                        broker_account_id="broker-account-1",
                        external_account_id=ACCOUNT_ID,
                        broker=BrokerName.LONGBRIDGE.value,
                        execution_mode=ExecutionMode.PAPER.value,
                        idempotency_key=f"intent-key-{index:04d}",
                        request_hash=(f"{index:064d}")[-64:],
                        operation=(
                            TradingOperation.SUBMIT.value
                            if is_matching or index % 2 == 0
                            else TradingOperation.CANCEL.value
                        ),
                        action="order_submit",
                        strategy_id="covered_call_v1",
                        entity_id="proposal-old-active",
                        broker_marker=f"marker-{index:04d}",
                        state=(
                            TradingIntentState.UNKNOWN.value
                            if is_matching or index % 3 == 0
                            else TradingIntentState.PERSISTED.value
                        ),
                        request_payload={},
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            session.add_all(intents)
            session.commit()

            ledger = SQLAlchemyTradingIntentLedger(session)
            filtered = ledger.list_intents(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                states={
                    TradingIntentState.PREPARED,
                    TradingIntentState.SUBMITTING,
                    TradingIntentState.BROKER_ACKNOWLEDGED,
                    TradingIntentState.UNKNOWN,
                },
                operation=TradingOperation.SUBMIT,
                limit=None,
            )
            capped = ledger.list_intents(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                state=TradingIntentState.UNKNOWN,
                limit=5,
            )
            service_filtered = OrderService(
                settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
                broker_accounts=None,
                trade_plans=None,
                orders=None,
                executions=None,
                longbridge_adapter=None,
                intent_ledger=ledger,
            ).list_trading_intents(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                states={
                    TradingIntentState.PREPARED,
                    TradingIntentState.SUBMITTING,
                    TradingIntentState.BROKER_ACKNOWLEDGED,
                    TradingIntentState.UNKNOWN,
                },
                operation=TradingOperation.SUBMIT,
                limit=None,
            )

            assert len(filtered) == 104
            assert all(intent.operation == TradingOperation.SUBMIT for intent in filtered)
            assert all(intent.state in {
                TradingIntentState.PREPARED,
                TradingIntentState.SUBMITTING,
                TradingIntentState.BROKER_ACKNOWLEDGED,
                TradingIntentState.UNKNOWN,
            } for intent in filtered)
            assert len(capped) == 5
            assert [intent.id for intent in service_filtered] == [intent.id for intent in filtered]
    finally:
        engine.dispose()

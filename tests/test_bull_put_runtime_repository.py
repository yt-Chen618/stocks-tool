from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import BrokerAccountRecord, BullPutStrategyRuntimeRecord
from stocks_tool.domain.enums import BrokerName, ExecutionMode
from stocks_tool.domain.models import BullPutStrategyRuntimeState
from stocks_tool.repositories.sqlalchemy_bull_put_strategy_runtime_repository import (
    SQLAlchemyBullPutStrategyRuntimeRepository,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def _state(mode: ExecutionMode, runtime_id: str) -> BullPutStrategyRuntimeState:
    return BullPutStrategyRuntimeState(
        id=runtime_id,
        external_account_id="LBPT10087357",
        mode=mode,
        daily_realized_pnl=Decimal("0"),
    )


def test_runtime_state_is_unique_and_locked_per_account_strategy_mode() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[BrokerAccountRecord.__table__, BullPutStrategyRuntimeRecord.__table__],
    )
    session = Session(engine, expire_on_commit=False)
    session.add(
        BrokerAccountRecord(
            id="broker-account-1",
            broker=BrokerName.LONGBRIDGE.value,
            external_account_id="LBPT10087357",
            display_name="Longbridge Paper",
            base_currency="USD",
        )
    )
    session.commit()
    repository = SQLAlchemyBullPutStrategyRuntimeRepository(session)

    paper = repository.upsert_runtime_state(_state(ExecutionMode.PAPER, "runtime-paper"))
    live = repository.upsert_runtime_state(_state(ExecutionMode.LIVE, "runtime-live"))

    assert repository.get_runtime_state(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    ).id == paper.id
    assert repository.get_runtime_state(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.LIVE,
    ).id == live.id
    assert repository.lock_for_entry(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
    ).id == paper.id

    with pytest.raises(ValueError, match="different account, strategy, or execution mode"):
        repository.upsert_runtime_state(
            _state(ExecutionMode.LIVE, "runtime-paper")
        )

    session.close()
    engine.dispose()

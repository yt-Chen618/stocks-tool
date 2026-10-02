from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import StrategyProposalRecord, StrategyRunRecord
from stocks_tool.domain.enums import (
    ExecutionMode,
    StrategyProposalStatus,
    StrategyRunStatus,
)
from stocks_tool.repositories.sqlalchemy_strategy_experiment_repository import (
    SQLAlchemyStrategyExperimentRepository,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


ACCOUNT_ID = "LBPT10087357"
NOW = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)


def test_covered_call_decision_filters_are_complete_beyond_display_caps() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            proposals = []
            for index in range(150):
                matching = index < 120
                proposals.append(
                    StrategyProposalRecord(
                        id=f"proposal-{index:04d}",
                        strategy_id="covered_call_v1" if matching else "other_strategy",
                        external_account_id=ACCOUNT_ID,
                        execution_mode=ExecutionMode.PAPER.value if matching else ExecutionMode.LIVE.value,
                        symbol="QQQ.US" if matching else "OTHER.US",
                        title="Covered call fixture",
                        proposed_action="sell_covered_call" if matching else "observe",
                        rationale="Query fixture",
                        status=StrategyProposalStatus.APPROVED.value if matching else StrategyProposalStatus.REJECTED.value,
                        created_at=NOW - timedelta(seconds=index),
                        updated_at=NOW - timedelta(seconds=index),
                    )
                )
            runs = [
                StrategyRunRecord(
                    id=f"run-{index:04d}",
                    strategy_id="covered_call_v1" if index < 520 else "other_strategy",
                    external_account_id=ACCOUNT_ID,
                    execution_mode=ExecutionMode.PAPER.value if index < 520 else ExecutionMode.LIVE.value,
                    run_type="open_lifecycle_refresh" if index < 520 else "other_run",
                    status=StrategyRunStatus.EXECUTED.value,
                    symbol="QQQ.US" if index < 520 else "OTHER.US",
                    proposal_id="proposal-target" if index < 520 else "other-proposal",
                    created_at=NOW - timedelta(seconds=index),
                    updated_at=NOW - timedelta(seconds=index),
                )
                for index in range(550)
            ]
            session.add_all([*proposals, *runs])
            session.commit()

            repository = SQLAlchemyStrategyExperimentRepository(session)
            matching_proposals = repository.list_proposals(
                external_account_id=ACCOUNT_ID,
                strategy_id="covered_call_v1",
                mode=ExecutionMode.PAPER,
                symbol="QQQ.US",
                statuses={StrategyProposalStatus.APPROVED},
                proposed_actions={"sell_covered_call"},
                limit=None,
            )
            matching_runs = repository.list_runs(
                external_account_id=ACCOUNT_ID,
                strategy_id="covered_call_v1",
                mode=ExecutionMode.PAPER,
                proposal_id="proposal-target",
                run_types={"open_lifecycle_refresh"},
                status=StrategyRunStatus.EXECUTED,
                limit=None,
            )

            assert len(matching_proposals) == 120
            assert len(matching_runs) == 520
            assert {proposal.mode for proposal in matching_proposals} == {ExecutionMode.PAPER}
            assert {run.proposal_id for run in matching_runs} == {"proposal-target"}
    finally:
        engine.dispose()

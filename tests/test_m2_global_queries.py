from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.application.services.strategy_experiments import StrategyExperimentService
from stocks_tool.application.services.operator_consistency import OperatorConsistencyService
from stocks_tool.db.base import Base
from stocks_tool.db.models import (
    BrokerAccountRecord,
    StrategyProposalRecord,
    StrategyRunRecord,
)
from stocks_tool.domain.enums import ExecutionMode, StrategyProposalStatus, StrategyRunStatus
from stocks_tool.domain.models import StrategyProposal
from stocks_tool.repositories.sqlalchemy_strategy_experiment_repository import (
    SQLAlchemyStrategyExperimentRepository,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


ACCOUNT_ID = "LBPT10087357"
NOW = datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc)


def test_covered_call_activity_summary_and_tasks_use_global_scope_with_display_limit() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            session.add(
                BrokerAccountRecord(
                    id="broker-account-1",
                    broker="longbridge",
                    external_account_id=ACCOUNT_ID,
                )
            )
            session.add(
                StrategyProposalRecord(
                    id="proposal-old-active",
                    strategy_id="covered_call_v1",
                    external_account_id=ACCOUNT_ID,
                    execution_mode=ExecutionMode.PAPER.value,
                    symbol="UNH.US",
                    title="Old active covered call",
                    proposed_action="sell_covered_call",
                    rationale="Global activity fixture",
                    status=StrategyProposalStatus.APPROVED.value,
                    created_at=NOW - timedelta(days=20),
                    updated_at=NOW - timedelta(days=20),
                )
            )
            for index in range(520):
                session.add(
                    StrategyProposalRecord(
                        id=f"proposal-history-{index:04d}",
                        strategy_id="covered_call_v1",
                        external_account_id=ACCOUNT_ID,
                        execution_mode=ExecutionMode.PAPER.value,
                        symbol="UNH.US",
                        title="Closed history",
                        proposed_action="sell_covered_call",
                        rationale="Display history fixture",
                        status=StrategyProposalStatus.CLOSED.value,
                        created_at=NOW - timedelta(minutes=index),
                        updated_at=NOW - timedelta(minutes=index),
                    )
                )
            session.add(
                StrategyProposalRecord(
                    id="proposal-live-active",
                    strategy_id="covered_call_v1",
                    external_account_id=ACCOUNT_ID,
                    execution_mode=ExecutionMode.LIVE.value,
                    symbol="UNH.US",
                    title="Live proposal",
                    proposed_action="sell_covered_call",
                    rationale="Mode isolation fixture",
                    status=StrategyProposalStatus.APPROVED.value,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                StrategyRunRecord(
                    id="run-old-active",
                    strategy_id="covered_call_v1",
                    external_account_id=ACCOUNT_ID,
                    execution_mode=ExecutionMode.PAPER.value,
                    run_type="open_lifecycle_refresh",
                    status=StrategyRunStatus.EXECUTED.value,
                    symbol="UNH.US",
                    proposal_id="proposal-old-active",
                    order_id="sell-order-old",
                    metrics_payload={
                        "order_id": "sell-order-old",
                        "sequence_status": "sell_submitted_waiting_fill",
                        "sell_status": "submitted",
                    },
                    created_at=NOW - timedelta(days=20),
                    updated_at=NOW - timedelta(days=20),
                )
            )
            for index in range(520):
                session.add(
                    StrategyRunRecord(
                        id=f"run-history-{index:04d}",
                        strategy_id="covered_call_v1",
                        external_account_id=ACCOUNT_ID,
                        execution_mode=ExecutionMode.PAPER.value,
                        run_type="proposal_close",
                        status=StrategyRunStatus.EXECUTED.value,
                        symbol="UNH.US",
                        proposal_id=f"proposal-history-{index:04d}",
                        created_at=NOW - timedelta(minutes=index),
                        updated_at=NOW - timedelta(minutes=index),
                    )
                )
            session.commit()

            broker_accounts = type("Accounts", (), {"get_by_external_account_id": lambda self, _: object()})()
            service = StrategyExperimentService(
                experiments=SQLAlchemyStrategyExperimentRepository(session),
                broker_accounts=broker_accounts,
            )
            activity = service.get_covered_call_activity(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                limit=1,
            )

            assert len(activity.proposals) == 1
            assert activity.summary.total_proposals == 521
            assert activity.summary.active_proposals == 1
            assert len(activity.lifecycle_tasks) == 1
            assert activity.lifecycle_tasks[0].proposal_id == "proposal-old-active"
    finally:
        engine.dispose()


def test_operator_consistency_limit_only_truncates_details_not_global_counts() -> None:
    proposals = [
        StrategyProposal(
            id=f"proposal-{index}",
            strategy_id="covered_call_v1",
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            symbol="UNH.US",
            title="Executed proposal",
            proposed_action="sell_covered_call",
            rationale="Global consistency fixture",
            status=StrategyProposalStatus.EXECUTED,
            created_at=NOW - timedelta(minutes=index),
            updated_at=NOW - timedelta(minutes=index),
        )
        for index in range(3)
    ]
    experiments = Mock()
    experiments.iter_proposals.return_value = proposals
    experiments.iter_runs.return_value = []
    experiments.iter_signals.return_value = []
    bull_put = Mock()
    bull_put.list_spreads.return_value = []
    orders = Mock()
    orders.list_orders.return_value = []
    report = OperatorConsistencyService(
        strategy_experiments=experiments,
        bull_put_strategy=bull_put,
        order_service=orders,
    ).get_summary(
        external_account_id=ACCOUNT_ID,
        mode=ExecutionMode.PAPER,
        strategy="covered_call_v1",
        limit=1,
    )

    assert report.status == "warn"
    assert report.check_count == 1
    assert report.warn_count == 1
    assert report.total_check_count == 3
    assert report.total_warn_count == 3
    assert report.truncated is True
    assert report.coverage_complete is True

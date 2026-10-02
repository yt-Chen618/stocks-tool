from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from stocks_tool.domain.enums import BrokerName, ExecutionMode, OrderStatus
from stocks_tool.repositories.sqlalchemy_order_repository import SQLAlchemyOrderRepository
from stocks_tool.repositories.sqlalchemy_scheduler_job_run_repository import (
    SQLAlchemySchedulerJobRunRepository,
)


def test_has_working_orders_is_scoped_and_bounded() -> None:
    session = Mock()
    session.execute.return_value.scalar_one.return_value = True
    repository = SQLAlchemyOrderRepository(session, attach_intent_ledger=False)

    assert repository.has_working_orders(
        "LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        statuses={OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED},
    ) is True

    statement = session.execute.call_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "EXISTS" in compiled.string.upper()
    assert compiled.params["external_account_id_1"] == "LBPT10087357"
    assert compiled.params["broker_1"] == BrokerName.LONGBRIDGE.value
    assert compiled.params["execution_mode_1"] == ExecutionMode.PAPER.value
    assert set(compiled.params["status_1"]) == {
        OrderStatus.SUBMITTED.value,
        OrderStatus.PARTIALLY_FILLED.value,
    }


def test_has_working_orders_with_empty_statuses_short_circuits() -> None:
    session = Mock()
    repository = SQLAlchemyOrderRepository(session, attach_intent_ledger=False)

    assert repository.has_working_orders(
        "LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        statuses=[],
    ) is False
    session.execute.assert_not_called()


def test_scheduler_lease_insert_race_reloads_committed_owner() -> None:
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    existing = SimpleNamespace(
        id="state-1",
        job_key="orders-sync",
        job_label="order reconciliation",
        external_account_id="LBPT10087357",
        last_run_id=None,
        last_status=None,
        last_started_at=None,
        last_completed_at=None,
        next_attempt_at=None,
        backoff_seconds=None,
        consecutive_failures=0,
        error_message=None,
        detail=None,
        lease_owner="other-worker",
        lease_acquired_at=now,
        lease_expires_at=datetime(2026, 10, 2, 12, 5, tzinfo=timezone.utc),
        created_at=now,
        updated_at=now,
    )
    empty_result = Mock()
    empty_result.scalar_one_or_none.return_value = None
    existing_result = Mock()
    existing_result.scalar_one_or_none.return_value = existing
    session = Mock()
    session.execute.side_effect = [empty_result, empty_result, existing_result]
    session.commit.side_effect = [
        IntegrityError("insert", {}, RuntimeError("duplicate key")),
        None,
    ]
    repository = SQLAlchemySchedulerJobRunRepository(session)

    state = repository.try_acquire_lease(
        external_account_id="LBPT10087357",
        job_key="orders-sync",
        job_label="order reconciliation",
        lease_owner="new-worker",
        lease_expires_at=datetime(2026, 10, 2, 12, 5, tzinfo=timezone.utc),
        now=now,
    )

    assert state.id == "state-1"
    assert state.lease_owner == "other-worker"
    session.rollback.assert_called_once()
    assert session.execute.call_count == 3


def test_scheduler_lease_rolls_back_initial_read_failure() -> None:
    session = Mock()
    session.execute.side_effect = RuntimeError("database unavailable")
    repository = SQLAlchemySchedulerJobRunRepository(session)

    with pytest.raises(RuntimeError, match="database unavailable"):
        repository.try_acquire_lease(
            external_account_id="LBPT10087357",
            job_key="orders-sync",
            job_label="order reconciliation",
            lease_owner="worker-a",
            lease_expires_at=datetime(2026, 10, 2, 12, 5, tzinfo=timezone.utc),
            now=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
        )

    session.rollback.assert_called_once()


def test_scheduler_lease_rolls_back_retry_read_failure() -> None:
    empty_result = Mock()
    empty_result.scalar_one_or_none.return_value = None
    session = Mock()
    session.execute.side_effect = [
        empty_result,
        empty_result,
        RuntimeError("retry database unavailable"),
    ]
    session.commit.side_effect = IntegrityError("insert", {}, RuntimeError("duplicate key"))
    repository = SQLAlchemySchedulerJobRunRepository(session)

    with pytest.raises(RuntimeError, match="retry database unavailable"):
        repository.try_acquire_lease(
            external_account_id="LBPT10087357",
            job_key="orders-sync",
            job_label="order reconciliation",
            lease_owner="worker-a",
            lease_expires_at=datetime(2026, 10, 2, 12, 5, tzinfo=timezone.utc),
            now=datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
        )

    assert session.rollback.call_count == 2

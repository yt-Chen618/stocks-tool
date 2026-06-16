from datetime import datetime, timezone

from stocks_tool.db.models import StrategyAuditEventRecord
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import CreateStrategyAuditEventRequest
from stocks_tool.repositories.sqlalchemy_strategy_audit_event_repository import (
    SQLAlchemyStrategyAuditEventRepository,
)


NOW = datetime(2026, 6, 16, 10, 0, tzinfo=timezone.utc)


class FakeScalarResult:
    def __init__(self, records: list[StrategyAuditEventRecord]) -> None:
        self.records = records

    def all(self) -> list[StrategyAuditEventRecord]:
        return self.records


class FakeExecuteResult:
    def __init__(self, records: list[StrategyAuditEventRecord]) -> None:
        self.records = records

    def scalars(self) -> FakeScalarResult:
        return FakeScalarResult(self.records)


class FakeSession:
    def __init__(self, records: list[StrategyAuditEventRecord]) -> None:
        self.records = records
        self.query = None

    def execute(self, query):
        self.query = query
        return FakeExecuteResult(self.records)


def _record() -> StrategyAuditEventRecord:
    record = StrategyAuditEventRecord(id="audit-1")
    record.external_account_id = "LBPT10087357"
    record.execution_mode = "paper"
    record.actor = "operator-a"
    record.source = "orders"
    record.strategy = "paper_order"
    record.action = "paper_order_submitted"
    record.before_payload = {"status": "created"}
    record.after_payload = {"status": "submitted"}
    record.order_ids = ["order-1"]
    record.proposal_id = None
    record.run_id = None
    record.warning_code = None
    record.summary = "Submitted."
    record.detail = None
    record.payload = {"symbol": "QQQ.US"}
    record.event_origin = "durable"
    record.emitted_at = NOW
    return record


def test_strategy_audit_event_repository_maps_request_to_domain(monkeypatch) -> None:
    repo = SQLAlchemyStrategyAuditEventRepository(FakeSession([]))
    monkeypatch.setattr(repo, "_resolve_broker_account_id", lambda external_account_id: "broker-account-1")
    record = StrategyAuditEventRecord(id="audit-1")

    repo._apply_request(
        record,
        CreateStrategyAuditEventRequest(
            id="audit-1",
            emitted_at=NOW,
            external_account_id="LBPT10087357",
            mode=ExecutionMode.PAPER,
            actor="operator-a",
            source="strategy_policy",
            strategy="paper_bull_put_v1",
            action="approve",
            before={"status": "pending"},
            after={"status": "approved"},
            proposal_id="proposal-1",
            summary="Approved.",
        ),
    )
    event = repo._to_domain(record)

    assert record.broker_account_id == "broker-account-1"
    assert event.id == "audit-1"
    assert event.mode == ExecutionMode.PAPER
    assert event.before == {"status": "pending"}
    assert event.after == {"status": "approved"}
    assert event.proposal_id == "proposal-1"
    assert event.event_origin == "durable"


def test_strategy_audit_event_repository_list_events_applies_filters() -> None:
    session = FakeSession([_record()])
    repo = SQLAlchemyStrategyAuditEventRepository(session)

    events = repo.list_events(
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        source="orders",
        strategy="paper_order",
        action="paper_order_submitted",
        warning_only=True,
        since=NOW,
        limit=25,
    )

    assert events[0].id == "audit-1"
    assert events[0].event_origin == "durable"
    compiled = str(session.query.compile(compile_kwargs={"literal_binds": True}))
    assert "strategy_audit_events.external_account_id = 'LBPT10087357'" in compiled
    assert "strategy_audit_events.execution_mode = 'paper'" in compiled
    assert "strategy_audit_events.source = 'orders'" in compiled
    assert "strategy_audit_events.strategy = 'paper_order'" in compiled
    assert "strategy_audit_events.action = 'paper_order_submitted'" in compiled
    assert "strategy_audit_events.warning_code IS NOT NULL" in compiled
    assert "strategy_audit_events.emitted_at >=" in compiled

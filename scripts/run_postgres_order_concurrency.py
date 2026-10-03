from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.application.services.orders import (  # noqa: E402
    OrderService,
    TradingIntentConflictError,
    TradingIntentOutcomeUnknownError,
)
from stocks_tool.application.services.order_authorization import OrderAuthorizationService  # noqa: E402
from stocks_tool.core.config import Settings, get_settings  # noqa: E402
from stocks_tool.application.services.strategy_advisor_intake import StrategyAdvisorIntakeService  # noqa: E402
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService  # noqa: E402
from stocks_tool.db.models import (  # noqa: E402
    BrokerAccountRecord,
    OrderIntentRecord,
    OrderRecord,
    SchedulerTaskStateRecord,
    StrategyAdvisorRunRecord,
    StrategyAuditEventRecord,
    StrategyProposalRecord,
    StrategyReviewRecord,
    StrategySignalRecord,
    TradeActionIntentRecord,
)
from stocks_tool.domain.enums import (  # noqa: E402
    AccountSnapshotProvenance,
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from stocks_tool.domain.models import (  # noqa: E402
    AccountSnapshot,
    BrokerOrderSnapshot,
    CreateOrderRequest,
    CreateStrategyAdvisorRunRequest,
    RecordStrategyAdvisorResponseRequest,
    StrategyAdvisorProposalDraft,
    StrategyAdvisorReviewDraft,
    SecurityQuoteSnapshot,
)
from stocks_tool.repositories.sqlalchemy_broker_account_repository import (  # noqa: E402
    SQLAlchemyBrokerAccountRepository,
)
from stocks_tool.repositories.sqlalchemy_account_snapshot_repository import (  # noqa: E402
    SQLAlchemyAccountSnapshotRepository,
)
from stocks_tool.repositories.sqlalchemy_execution_repository import (  # noqa: E402
    SQLAlchemyExecutionRepository,
)
from stocks_tool.repositories.sqlalchemy_order_repository import (  # noqa: E402
    SQLAlchemyOrderRepository,
)
from stocks_tool.repositories.sqlalchemy_strategy_audit_event_repository import (  # noqa: E402
    SQLAlchemyStrategyAuditEventRepository,
)
from stocks_tool.repositories.sqlalchemy_trade_plan_repository import (  # noqa: E402
    SQLAlchemyTradePlanRepository,
)
from stocks_tool.repositories.sqlalchemy_trading_intent_ledger import (  # noqa: E402
    SQLAlchemyTradingIntentLedger,
)
from stocks_tool.repositories.sqlalchemy_scheduler_job_run_repository import (  # noqa: E402
    SQLAlchemySchedulerJobRunRepository,
)
from stocks_tool.repositories.sqlalchemy_strategy_experiment_repository import (  # noqa: E402
    SQLAlchemyStrategyExperimentRepository,
)


ACCOUNT_ID = "LBPT10087357"
IDEMPOTENCY_KEY = "postgres-concurrent-order-0001"


class CountingBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.submit_calls = 0

    def submit_order(self, request: CreateOrderRequest) -> BrokerOrderSnapshot:
        with self._lock:
            self.submit_calls += 1
            call_number = self.submit_calls
        time.sleep(0.15)
        now = datetime.now(timezone.utc)
        return BrokerOrderSnapshot(
            external_order_id=f"mock-postgres-order-{call_number}",
            symbol=request.symbol,
            side=request.side,
            quantity=request.quantity,
            order_type=request.order_type,
            time_in_force=request.time_in_force,
            mode=request.mode,
            status=OrderStatus.SUBMITTED,
            limit_price=request.limit_price,
            stop_price=request.stop_price,
            executed_quantity=0,
            remark=request.remark,
            submitted_at=now,
            updated_at=now,
            raw_payload={"source": "p0-postgres-concurrency"},
        )

    def get_quote(self, *, symbol: str, mode: ExecutionMode) -> SecurityQuoteSnapshot:
        now = datetime.now(timezone.utc)
        return SecurityQuoteSnapshot(
            symbol=symbol,
            last_done=Decimal("321.00"),
            prev_close=Decimal("320.00"),
            open=Decimal("320.00"),
            high=Decimal("322.00"),
            low=Decimal("319.00"),
            timestamp=now,
            volume=1000,
            turnover=Decimal("321000"),
            trade_status="normal",
            data_quality="live",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate exact-once order submission against an isolated temporary PostgreSQL database."
    )
    parser.add_argument("--json-output")
    return parser.parse_args()


def _database_url(base_url: URL, database: str) -> str:
    return base_url.set(database=database).render_as_string(hide_password=False)


def _order_request(*, limit_price: Decimal = Decimal("321.00")) -> CreateOrderRequest:
    return CreateOrderRequest(
        external_account_id=ACCOUNT_ID,
        broker=BrokerName.LONGBRIDGE,
        symbol="UNH.US",
        asset_type=AssetType.STOCK,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        limit_price=limit_price,
        remark="p0-postgres",
    )


def _service(session: Session, database_url: str, broker: CountingBroker) -> OrderService:
    account_snapshots = SQLAlchemyAccountSnapshotRepository(session)
    authorization = OrderAuthorizationService(
        account_snapshots=account_snapshots,
        market_data=broker,
        max_snapshot_age_seconds=120,
        clock=lambda: datetime.now(timezone.utc),
    )
    return OrderService(
        settings=Settings(database_url=database_url),
        broker_accounts=SQLAlchemyBrokerAccountRepository(session),
        trade_plans=SQLAlchemyTradePlanRepository(session),
        orders=SQLAlchemyOrderRepository(session, attach_intent_ledger=False),
        executions=SQLAlchemyExecutionRepository(session),
        longbridge_adapter=broker,
        audit_events=SQLAlchemyStrategyAuditEventRepository(session),
        intent_ledger=SQLAlchemyTradingIntentLedger(session),
        order_authorization=authorization,
    )


def _run_migrations(database_url: str) -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = database_url
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Temporary PostgreSQL migration failed: "
            + (completed.stderr[-600:] or completed.stdout[-600:])
        )


def _run_concurrent_requests(database_url: str, broker: CountingBroker) -> list[str]:
    engine = create_engine(database_url, pool_pre_ping=True)
    barrier = threading.Barrier(2)

    def worker() -> str:
        with Session(engine, expire_on_commit=False, autoflush=False) as session:
            service = _service(session, database_url, broker)
            barrier.wait(timeout=10)
            try:
                order = service.submit_order(
                    _order_request(),
                    idempotency_key=IDEMPOTENCY_KEY,
                )
                return f"order:{order.id}"
            except TradingIntentOutcomeUnknownError as exc:
                return f"unknown:{exc.intent_id}"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(lambda _index: worker(), range(2)))
    finally:
        engine.dispose()


def _verify(database_url: str, broker: CountingBroker, outcomes: list[str]) -> dict:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False, autoflush=False) as session:
            order_count = session.scalar(select(func.count()).select_from(OrderRecord)) or 0
            intent_count = session.scalar(select(func.count()).select_from(OrderIntentRecord)) or 0
            action_count = session.scalar(select(func.count()).select_from(TradeActionIntentRecord)) or 0
            service = _service(session, database_url, broker)
            conflict_observed = False
            try:
                service.submit_order(
                    _order_request(limit_price=Decimal("322.00")),
                    idempotency_key=IDEMPOTENCY_KEY,
                )
            except TradingIntentConflictError:
                conflict_observed = True

        checks = {
            "broker_submit_calls": broker.submit_calls,
            "order_count": order_count,
            "order_intent_count": intent_count,
            "trade_action_intent_count": action_count,
            "different_payload_conflict": conflict_observed,
            "concurrent_outcomes": outcomes,
        }
        passed = (
            broker.submit_calls == 1
            and order_count == 1
            and intent_count == 1
            and action_count == 1
            and conflict_observed
            and len(outcomes) == 2
        )
        return {"status": "passed" if passed else "failed", **checks}
    finally:
        engine.dispose()


def _verify_scheduler_leases(database_url: str) -> dict:
    engine = create_engine(database_url, pool_pre_ping=True)
    acquired_counts = []
    try:
        for round_number in range(5):
            barrier = threading.Barrier(2)
            now = datetime.now(timezone.utc)

            def worker(owner: str) -> bool:
                with Session(engine, expire_on_commit=False, autoflush=False) as session:
                    repository = SQLAlchemySchedulerJobRunRepository(session)
                    barrier.wait(timeout=10)
                    state = repository.try_acquire_lease(
                        external_account_id=ACCOUNT_ID,
                        job_key=f"postgres-concurrent-lease-{round_number}",
                        job_label="PostgreSQL lease concurrency gate",
                        lease_owner=owner,
                        lease_expires_at=now + timedelta(minutes=1),
                        now=now,
                    )
                    return state.lease_owner == owner

            with ThreadPoolExecutor(max_workers=2) as executor:
                acquired_counts.append(sum(executor.map(worker, ("worker-a", "worker-b"))))
        with Session(engine) as session:
            state_count = session.scalar(
                select(func.count()).select_from(SchedulerTaskStateRecord).where(
                    SchedulerTaskStateRecord.job_key.like("postgres-concurrent-lease-%")
                )
            )
        return {
            "status": "passed" if acquired_counts == [1] * 5 and state_count == 5 else "failed",
            "acquired_per_round": acquired_counts,
            "state_rows": state_count,
        }
    finally:
        engine.dispose()


def _advisor_service(session: Session, database_url: str) -> StrategyAdvisorIntakeService:
    return StrategyAdvisorIntakeService(
        strategy_experiments=StrategyExperimentService(
            experiments=SQLAlchemyStrategyExperimentRepository(session),
            broker_accounts=SQLAlchemyBrokerAccountRepository(session),
            settings=Settings(_env_file=None, database_url=database_url),
            audit_events=SQLAlchemyStrategyAuditEventRepository(session),
        )
    )


def _verify_advisor_intake(database_url: str) -> dict:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        def new_request(summary: str) -> RecordStrategyAdvisorResponseRequest:
            with Session(engine, expire_on_commit=False, autoflush=False) as session:
                repository = SQLAlchemyStrategyExperimentRepository(session)
                advisor_run_id = str(uuid4())
                request = RecordStrategyAdvisorResponseRequest(
                    external_account_id=ACCOUNT_ID,
                    advisor_run_id=advisor_run_id,
                    proposals=[StrategyAdvisorProposalDraft(
                        strategy_id="covered_call_v1",
                        symbol="QQQ.US",
                        title="PostgreSQL advisor atomicity gate",
                        proposed_action="sell_covered_call",
                        rationale="Isolated test data; no broker actions.",
                    )],
                    reviews=[StrategyAdvisorReviewDraft(
                        strategy_id="covered_call_v1", summary=summary,
                    )],
                )
                repository.create_advisor_run(
                    CreateStrategyAdvisorRunRequest(
                        id=advisor_run_id,
                        external_account_id=ACCOUNT_ID,
                        source="deepseek",
                        mode=ExecutionMode.PAPER,
                        provider="deepseek",
                        status="succeeded",
                        context_format="compact_v1",
                        context_limit=10,
                        proposal_count=len(request.proposals),
                        review_count=len(request.reviews),
                        response_payload=request.model_dump(mode="json", exclude_none=True),
                    )
                )
                return request

        request = new_request("PostgreSQL advisor concurrency gate")
        barrier = threading.Barrier(2)

        def worker(_index: int) -> tuple[str, str]:
            with Session(engine, expire_on_commit=False, autoflush=False) as session:
                service = _advisor_service(session, database_url)
                barrier.wait(timeout=10)
                result = service.record_response(request)
                return result.proposals[0].id, result.reviews[0].id

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(worker, range(2)))

        def row_counts() -> dict[str, int]:
            with Session(engine) as session:
                return {
                    model.__tablename__: session.scalar(select(func.count()).select_from(model))
                    for model in (
                        StrategyProposalRecord, StrategyReviewRecord,
                        StrategySignalRecord, StrategyAuditEventRecord,
                    )
                }

        before_failure = row_counts()
        failure_request = new_request("postgres-failure-injection")
        with engine.begin() as connection:
            connection.exec_driver_sql("""
                CREATE FUNCTION reject_gate_review() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.summary = 'postgres-failure-injection' THEN
                        RAISE EXCEPTION 'injected advisor persistence failure';
                    END IF;
                    RETURN NEW;
                END $$
            """)
            connection.exec_driver_sql("""
                CREATE TRIGGER reject_gate_review BEFORE INSERT ON strategy_reviews
                FOR EACH ROW EXECUTE FUNCTION reject_gate_review()
            """)
        failure_observed = False
        with Session(engine, expire_on_commit=False, autoflush=False) as session:
            try:
                _advisor_service(session, database_url).record_response(failure_request)
            except Exception as exc:
                if "injected advisor persistence failure" not in str(exc):
                    raise
                failure_observed = True
        after_failure = row_counts()
        with Session(engine) as session:
            failure_run = session.get(StrategyAdvisorRunRecord, failure_request.advisor_run_id)
            failed_run_unrecorded = failure_run.recorded_at is None and failure_run.status == "succeeded"
        passed = (
            len(set(outcomes)) == 1
            and before_failure["strategy_proposals"] == 1
            and before_failure["strategy_reviews"] == 1
            and failure_observed
            and before_failure == after_failure
            and failed_run_unrecorded
        )
        return {
            "status": "passed" if passed else "failed",
            "concurrent_results_match": len(set(outcomes)) == 1,
            "row_counts": before_failure,
            "injected_failure_observed": failure_observed,
            "failed_batch_rolled_back": before_failure == after_failure,
            "failed_run_unrecorded": failed_run_unrecorded,
        }
    finally:
        engine.dispose()


def main() -> int:
    args = parse_args()
    base_url = make_url(get_settings().database_url)
    if not base_url.drivername.startswith("postgresql"):
        raise SystemExit("P0 concurrency validation requires a PostgreSQL DATABASE_URL.")

    database_name = f"p0_safety_{uuid4().hex[:12]}"
    admin_url = _database_url(base_url, "postgres")
    database_url = _database_url(base_url, database_name)
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    payload: dict
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        _run_migrations(database_url)
        temp_engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with Session(temp_engine) as session:
                session.add(
                    BrokerAccountRecord(
                        id=str(uuid4()),
                        broker=BrokerName.LONGBRIDGE.value,
                        external_account_id=ACCOUNT_ID,
                        is_active=True,
                    )
                )
                session.commit()
                SQLAlchemyAccountSnapshotRepository(session).create_account_snapshot(
                    AccountSnapshot(
                        broker=BrokerName.LONGBRIDGE,
                        account_id=ACCOUNT_ID,
                        mode=ExecutionMode.PAPER,
                        provenance=AccountSnapshotProvenance.BROKER_SYNC,
                        currency="USD",
                        cash_balance=Decimal("100000"),
                        net_liquidation=Decimal("100000"),
                        buying_power=Decimal("100000"),
                        positions=[],
                        captured_at=datetime.now(timezone.utc),
                        raw_payload={"source": "p0-concurrency-fixture"},
                    ),
                    provenance=AccountSnapshotProvenance.BROKER_SYNC,
                )
        finally:
            temp_engine.dispose()

        broker = CountingBroker()
        outcomes = _run_concurrent_requests(database_url, broker)
        payload = _verify(database_url, broker, outcomes)
        payload["scheduler_leases"] = _verify_scheduler_leases(database_url)
        payload["advisor_intake"] = _verify_advisor_intake(database_url)
        if any(payload[key]["status"] != "passed" for key in ("scheduler_leases", "advisor_intake")):
            payload["status"] = "failed"
    except Exception as exc:
        payload = {
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    finally:
        try:
            with admin_engine.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        finally:
            admin_engine.dispose()

    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

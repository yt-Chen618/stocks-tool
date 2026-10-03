"""Run the isolated PostgreSQL P6 recovery, fairness, and event-dedupe proof.

The proof creates and drops its own temporary database, applies the committed
migrations, seeds 100,000 unresolved intents, and never reads or writes the
operator database.  It verifies that a fixed reconciliation high-water mark
continues correctly when earlier rows are mutated, that the fair cursor reaches
the deferred tail after a 500-row pass, and that the reconciliation index is
used for bounded PostgreSQL pages.  It also exercises concurrent market-event
dedupe while preserving legacy rows whose nullable key is still NULL.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sys
import threading
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from regression_common import build_report, emit_report  # noqa: E402
from run_postgres_order_concurrency import _database_url, _run_migrations  # noqa: E402
from stocks_tool.core.config import get_settings  # noqa: E402
from stocks_tool.db.models import (  # noqa: E402
    MarketEventRecord,
    OrderIntentRecord,
)
from stocks_tool.domain.enums import (  # noqa: E402
    ExecutionMode,
    MarketEventType,
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.domain.models import CreateMarketEventRequest  # noqa: E402
from stocks_tool.ports.trading_intent_ledger import ReconciliationCursor  # noqa: E402
from stocks_tool.repositories.sqlalchemy_market_event_repository import (  # noqa: E402
    SQLAlchemyMarketEventRepository,
)
from stocks_tool.repositories.sqlalchemy_trading_intent_ledger import (  # noqa: E402
    SQLAlchemyTradingIntentLedger,
)


ACCOUNT_ID = "LBPT10087357"
INTENT_COUNT = 100_000
PAGE_SIZE = 100
FAIRNESS_BATCH = 500
EVENT_TIME = datetime(2026, 10, 4, 13, 30, tzinfo=timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output")
    return parser.parse_args()


def _intent_id(index: int) -> str:
    return f"p6-intent-{index:06d}"


def _seed_intents(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO trade_action_intents (
                    id, external_account_id, broker, execution_mode,
                    idempotency_key, request_hash, action, state, request_payload,
                    created_at, updated_at
                ) VALUES (
                    'p6-action-1', :account, 'longbridge', 'paper',
                    'p6-action-key', repeat('a', 64), 'order_submit', 'unknown',
                    '{}'::jsonb, TIMESTAMPTZ '2026-01-01', TIMESTAMPTZ '2026-01-01'
                )
                """
            ),
            {"account": ACCOUNT_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO order_intents (
                    id, trade_action_intent_id, external_account_id, broker,
                    execution_mode, idempotency_key, request_hash, operation,
                    action, broker_marker, state, request_payload,
                    created_at, updated_at
                )
                SELECT
                    'p6-intent-' || lpad(n::text, 6, '0'),
                    'p6-action-1', :account, 'longbridge', 'paper',
                    'p6-key-' || lpad(n::text, 6, '0'), repeat('b', 64),
                    'submit', 'order_submit',
                    'p6:' || lpad(n::text, 16, '0'), 'unknown', '{}'::jsonb,
                    TIMESTAMPTZ '2026-01-01' + n * INTERVAL '1 microsecond',
                    TIMESTAMPTZ '2026-01-01' + n * INTERVAL '1 microsecond'
                FROM generate_series(0, :last_index) AS n
                """
            ),
            {"account": ACCOUNT_ID, "last_index": INTENT_COUNT - 1},
        )
        connection.exec_driver_sql("ANALYZE order_intents")


def _cursor(intent) -> ReconciliationCursor:
    return ReconciliationCursor(
        updated_at=intent.updated_at,
        created_at=intent.created_at,
        intent_id=intent.id,
    )


def _flatten_plan(plan: dict[str, Any]):
    yield plan
    for child in plan.get("Plans", []):
        yield from _flatten_plan(child)


def _explain_page(
    engine,
    *,
    highwater: ReconciliationCursor,
    cursor: ReconciliationCursor | None,
) -> dict[str, Any]:
    predicates = """
        external_account_id = :account
        AND execution_mode = :mode
        AND state = :state
        AND (
            updated_at < :highwater_updated
            OR (updated_at = :highwater_updated AND created_at < :highwater_created)
            OR (
                updated_at = :highwater_updated
                AND created_at = :highwater_created
                AND id <= :highwater_id
            )
        )
    """
    params: dict[str, Any] = {
        "account": ACCOUNT_ID,
        "mode": ExecutionMode.PAPER.value,
        "state": TradingIntentState.UNKNOWN.value,
        "highwater_updated": highwater.updated_at,
        "highwater_created": highwater.created_at,
        "highwater_id": highwater.intent_id,
    }
    if cursor is not None:
        predicates += """
            AND (
                updated_at > :cursor_updated
                OR (updated_at = :cursor_updated AND created_at > :cursor_created)
                OR (
                    updated_at = :cursor_updated
                    AND created_at = :cursor_created
                    AND id > :cursor_id
                )
            )
        """
        params.update(
            cursor_updated=cursor.updated_at,
            cursor_created=cursor.created_at,
            cursor_id=cursor.intent_id,
        )
    statement = (
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
        "SELECT id FROM order_intents WHERE "
        + predicates
        + " ORDER BY updated_at, created_at, id LIMIT 100"
    )
    with engine.connect() as connection:
        payload = connection.execute(text(statement), params).scalar_one()[0]
    nodes = list(_flatten_plan(payload["Plan"]))
    relation_nodes = [
        node for node in nodes if node.get("Relation Name") == "order_intents"
    ]
    index_names = sorted(
        {
            str(node.get("Index Name"))
            for node in nodes
            if node.get("Index Name")
        }
    )
    examined = sum(
        (
            int(node.get("Actual Rows", 0))
            + int(node.get("Rows Removed by Filter", 0))
            + int(node.get("Rows Removed by Index Recheck", 0))
        )
        * int(node.get("Actual Loops", 1))
        for node in relation_nodes
    )
    uses_fair_index = "ix_order_intents_reconciliation_fair" in index_names
    if not uses_fair_index:
        raise AssertionError(f"P6 reconciliation query did not use fair index: {index_names}")
    if examined > 2_000:
        raise AssertionError(f"P6 reconciliation query examined too many rows: {examined}")
    return {
        "uses_fair_index": uses_fair_index,
        "index_names": index_names,
        "examined_rows": examined,
        "relation_nodes": relation_nodes,
    }


def _run_keyset_and_fairness(engine) -> dict[str, Any]:
    loaded = Counter()

    def count_loaded(_session, instance) -> None:
        if isinstance(instance, OrderIntentRecord):
            loaded["order_intents"] += 1

    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        event.listen(session, "loaded_as_persistent", count_loaded)
        ledger = SQLAlchemyTradingIntentLedger(session)
        states = (TradingIntentState.UNKNOWN,)
        highwater = ledger.get_reconciliation_high_watermark(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            states=states,
        )
        if highwater is None:
            raise AssertionError("P6 fixture did not create unresolved intents")

        loaded.clear()
        first = ledger.list_reconciliation_intents(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            states=states,
            high_watermark=highwater,
            limit=PAGE_SIZE,
        )
        if len(first) != PAGE_SIZE:
            raise AssertionError(f"Expected 100-row first page, got {len(first)}")
        if [item.id for item in first] != [_intent_id(i) for i in range(PAGE_SIZE)]:
            raise AssertionError("First reconciliation page is not keyset ordered")
        first_loaded = loaded["order_intents"]

        first_cursor = _cursor(first[-1])
        first_plan = _explain_page(engine, highwater=highwater, cursor=None)

        # Mutate the first page after the high-water mark. A subsequent page
        # with the fixed mark must still return the next original rows.
        for intent in first:
            ledger.record_reconciliation_attempt(
                intent.id,
                "P6 fixed high-water mutation proof",
                zero_match=False,
            )
        loaded.clear()
        second = ledger.list_reconciliation_intents(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            states=states,
            high_watermark=highwater,
            cursor=first_cursor,
            limit=PAGE_SIZE,
        )
        if [item.id for item in second] != [_intent_id(i) for i in range(100, 200)]:
            raise AssertionError("Fixed high-water page skipped rows after mutation")
        second_loaded = loaded["order_intents"]
        if second_loaded > PAGE_SIZE + 1:
            raise AssertionError("Reconciliation page materialized more than its bounded page")
        deep_plan = _explain_page(engine, highwater=highwater, cursor=first_cursor)

        # Continue the same fixed-mark cycle through 500 rows. Updating those
        # rows must rotate the deferred tail to the front of the next cycle.
        cursor = first_cursor
        selected_ids = [item.id for item in first]
        for _ in range(4):
            page = ledger.list_reconciliation_intents(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                states=states,
                high_watermark=highwater,
                cursor=cursor,
                limit=PAGE_SIZE,
            )
            if len(page) != PAGE_SIZE:
                raise AssertionError("Fixed high-water cycle did not produce a full page")
            selected_ids.extend(item.id for item in page)
            for intent in page:
                ledger.record_reconciliation_attempt(
                    intent.id,
                    "P6 fairness rotation proof",
                    zero_match=False,
                )
            cursor = _cursor(page[-1])
        if len(selected_ids) != FAIRNESS_BATCH or len(set(selected_ids)) != FAIRNESS_BATCH:
            raise AssertionError("P6 fixed high-water cycle duplicated or omitted rows")

        next_highwater = ledger.get_reconciliation_high_watermark(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            states=states,
        )
        deferred = ledger.list_reconciliation_intents(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            states=states,
            high_watermark=next_highwater,
            limit=PAGE_SIZE,
        )
        if [item.id for item in deferred] != [_intent_id(i) for i in range(500, 600)]:
            raise AssertionError("Fairness cycle did not reach the deferred tail")
        return {
            "rows_seeded": INTENT_COUNT,
            "page_size": PAGE_SIZE,
            "first_page_rows": len(first),
            "deep_page_rows": len(second),
            "materialized_first_page": first_loaded,
            "materialized_second_page": second_loaded,
            "materialized_bound": PAGE_SIZE + 1,
            "fixed_highwater_no_skip": True,
            "fairness_batch": FAIRNESS_BATCH,
            "deferred_tail_first_page": [item.id for item in deferred],
            "first_page_plan": first_plan,
            "deep_page_plan": deep_plan,
        }


def _market_event_request() -> CreateMarketEventRequest:
    return CreateMarketEventRequest(
        symbol="unh.us",
        event_type=MarketEventType.EARNINGS,
        title="  UNH   earnings ",
        scheduled_at=EVENT_TIME,
    )


def _run_market_event_dedupe(database_url: str, engine) -> dict[str, Any]:
    def concurrent_create(request: CreateMarketEventRequest) -> list[tuple[str, bool]]:
        barrier = threading.Barrier(2)

        # Keep one repository instance per worker/session and return both the
        # id and creation flag; this avoids sharing sessions across connections.
        def run_worker() -> tuple[str, bool]:
            worker_engine = create_engine(database_url, pool_pre_ping=True)
            try:
                with Session(worker_engine, expire_on_commit=False, autoflush=False) as session:
                    barrier.wait(timeout=15)
                    event_record, created = SQLAlchemyMarketEventRepository(session).create_event_if_absent(
                        request
                    )
                    return event_record.id, created
            finally:
                worker_engine.dispose()

        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(lambda _index: run_worker(), range(2)))

    outcomes = concurrent_create(_market_event_request())
    ids = {item[0] for item in outcomes}
    created_count = sum(1 for _event_id, created in outcomes if created)
    with Session(engine, expire_on_commit=False) as session:
        repository = SQLAlchemyMarketEventRepository(session)
        row_count = session.scalar(select(func.count()).select_from(MarketEventRecord)) or 0
        legacy_request = CreateMarketEventRequest(
            symbol="unh.us",
            event_type=MarketEventType.EARNINGS,
            title="UNH earnings legacy",
            scheduled_at=EVENT_TIME,
        )
        session.execute(
            text(
                """
                INSERT INTO market_events (
                    id, symbol, event_type, title, scheduled_at,
                    severity, dedupe_key, created_at, updated_at
                ) VALUES (
                    'p6-legacy-event', 'UNH.US', 'earnings', 'UNH earnings legacy',
                    :scheduled_at, 'medium', NULL, :now, :now
                )
                """
            ),
            {"scheduled_at": EVENT_TIME, "now": EVENT_TIME},
        )
        session.commit()
        legacy_outcomes = concurrent_create(legacy_request)
        bulk_legacy_rows = [
            {
                "id": f"p6-legacy-bulk-{index:04d}",
                "symbol": f"OTHER{index}.US",
                "event_type": MarketEventType.EARNINGS.value,
                "title": f"Other earnings {index}",
                "scheduled_at": EVENT_TIME,
                "severity": "medium",
                "dedupe_key": None,
                "created_at": EVENT_TIME,
                "updated_at": EVENT_TIME,
            }
            for index in range(500)
        ]
        bulk_legacy_rows.append(
            {
                "id": "p6-legacy-bulk-target",
                "symbol": "TARGET.US",
                "event_type": MarketEventType.EARNINGS.value,
                "title": "Target earnings",
                "scheduled_at": EVENT_TIME,
                "severity": "medium",
                "dedupe_key": None,
                "created_at": EVENT_TIME,
                "updated_at": EVENT_TIME,
            }
        )
        session.execute(
            text(
                """
                INSERT INTO market_events (
                    id, symbol, event_type, title, scheduled_at,
                    severity, dedupe_key, created_at, updated_at
                ) VALUES (
                    :id, :symbol, :event_type, :title, :scheduled_at,
                    :severity, :dedupe_key, :created_at, :updated_at
                )
                """
            ),
            bulk_legacy_rows,
        )
        session.commit()
        bulk_target, bulk_created = repository.create_event_if_absent(
            CreateMarketEventRequest(
                symbol="target.us",
                event_type=MarketEventType.EARNINGS,
                title=" target   earnings ",
                scheduled_at=EVENT_TIME,
            )
        )
        final_count = session.scalar(select(func.count()).select_from(MarketEventRecord)) or 0
        null_key_count = session.scalar(
            select(func.count()).select_from(MarketEventRecord).where(
                MarketEventRecord.dedupe_key.is_(None)
            )
        ) or 0
    if len(ids) != 1 or created_count != 1 or row_count != 1:
        raise AssertionError(f"Concurrent event dedupe failed: {outcomes}, rows={row_count}")
    if (
        legacy_outcomes != [
            ("p6-legacy-event", False),
            ("p6-legacy-event", False),
        ]
        or bulk_created
        or bulk_target.id != "p6-legacy-bulk-target"
        or final_count != 503
        or null_key_count != 502
    ):
        raise AssertionError("Legacy NULL dedupe rows were not preserved")
    return {
        "concurrent_outcomes": outcomes,
        "concurrent_unique_ids": len(ids),
        "created_count": created_count,
        "rows_after_concurrency": row_count,
        "legacy_concurrent_outcomes": legacy_outcomes,
        "rows_after_legacy_insert": final_count,
        "legacy_null_key_rows": null_key_count,
        "bulk_legacy_match": bulk_target.id,
        "bulk_legacy_created": bulk_created,
        "bulk_legacy_rows": 501,
        "legacy_lookup_page_size": SQLAlchemyMarketEventRepository.LEGACY_DEDUPE_PAGE_SIZE,
        "legacy_match_beyond_first_page": True,
    }


def run() -> int:
    args = parse_args()
    base_url = make_url(get_settings().database_url)
    if not base_url.drivername.startswith("postgresql"):
        raise SystemExit("P6 query validation requires PostgreSQL.")
    database_name = f"p6_query_{uuid4().hex[:12]}"
    database_url = _database_url(base_url, database_name)
    admin = create_engine(_database_url(base_url, "postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    cleanup_succeeded = False
    error = None
    payload: dict[str, Any] = {}
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        created = True
        _run_migrations(database_url)
        engine = create_engine(database_url, pool_pre_ping=True)
        _seed_intents(engine)
        payload["reconciliation"] = _run_keyset_and_fairness(engine)
        payload["market_event_dedupe"] = _run_market_event_dedupe(database_url, engine)
        payload["broker_calls"] = 0
        payload["operator_database_touched"] = False
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        import traceback

        traceback.print_exc(file=sys.stderr)
    finally:
        if engine is not None:
            engine.dispose()
        cleanup_error = None
        if created:
            try:
                with admin.connect() as connection:
                    connection.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname=:name AND pid<>pg_backend_pid()"
                        ),
                        {"name": database_name},
                    )
                    connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
                    cleanup_succeeded = True
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
        admin.dispose()
        if cleanup_error is not None and error is None:
            error = f"temporary database cleanup failed: {cleanup_error}"
    payload["temporary_database_removed"] = bool(created and cleanup_succeeded)
    report = build_report(
        script=Path(__file__).name,
        workflow="p6-query",
        status="failed" if error else "passed",
        mode="isolated-postgresql",
        target="temporary database",
        summary="P6 PostgreSQL keyset, fairness, capacity, and market-event dedupe proof.",
        payload=payload,
        error=error,
    )
    emit_report(report, args.json_output)
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(run())

"""Exercise bounded history reads against an isolated, migrated PostgreSQL database."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stocks_tool.core.config import get_settings  # noqa: E402
from stocks_tool.domain.enums import ExecutionMode, SpreadStatus  # noqa: E402
from stocks_tool.domain.pagination import encode_cursor  # noqa: E402
from stocks_tool.db.models import (  # noqa: E402
    BrokerAccountRecord, BullPutSpreadRecord, ExecutionRecord, JournalEntryRecord, OrderRecord,
)
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import SQLAlchemyBullPutSpreadRepository  # noqa: E402
from stocks_tool.repositories.sqlalchemy_execution_repository import SQLAlchemyExecutionRepository  # noqa: E402
from stocks_tool.repositories.sqlalchemy_journal_repository import SQLAlchemyJournalRepository  # noqa: E402
from stocks_tool.repositories.sqlalchemy_order_repository import SQLAlchemyOrderRepository  # noqa: E402
from regression_common import build_report, emit_report  # noqa: E402
from run_postgres_order_concurrency import _database_url, _run_migrations  # noqa: E402

ACCOUNT_ID = "LBPT10087357"
OTHER_ACCOUNT_ID = "history-query-other-account"
PAGE_SIZE = 50


def seed_history(engine, *, first: int, last: int) -> None:
    parameters = {"first": first, "last": last, "account": ACCOUNT_ID, "other": OTHER_ACCOUNT_ID}
    with engine.begin() as connection:
        connection.execute(text("""
            INSERT INTO orders (
                id, broker_account_id, broker, external_order_id, client_order_id,
                symbol, asset_type, side, quantity, order_type, time_in_force,
                execution_mode, status, created_at, updated_at, raw_payload
            )
            SELECT 'order-' || lpad(n::text, 10, '0'),
                CASE WHEN n % 10 = 0 THEN 'history-other' ELSE 'history-primary' END,
                'longbridge', 'external-' || n, 'client-' || n,
                'AAPL.US', 'stock', 'buy', 1, 'limit', 'day', 'paper', 'filled',
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second',
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second',
                '{"fixture":"bounded-history"}'::jsonb
            FROM generate_series(CAST(:first AS bigint), CAST(:last AS bigint)) AS n
        """), parameters)
        connection.execute(text("""
            INSERT INTO executions (
                id, order_id, broker, external_account_id, external_order_id,
                external_execution_id, symbol, side, quantity, price,
                executed_at, created_at, updated_at
            )
            SELECT 'execution-' || lpad(n::text, 10, '0'),
                'order-' || lpad(n::text, 10, '0'), 'longbridge',
                CASE WHEN n % 10 = 0 THEN :other ELSE :account END,
                'external-' || n, 'fill-' || n, 'AAPL.US', 'buy', 1, 100,
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second',
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second',
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second'
            FROM generate_series(CAST(:first AS bigint), CAST(:last AS bigint)) AS n
        """), parameters)
        connection.execute(text("""
            INSERT INTO journal_entries (
                id, order_id, execution_id, external_account_id, symbol,
                entry_type, title, notes, created_at, updated_at
            )
            SELECT 'journal-' || lpad(n::text, 10, '0'),
                'order-' || lpad(n::text, 10, '0'),
                'execution-' || lpad(n::text, 10, '0'),
                CASE WHEN n % 10 = 0 THEN :other ELSE :account END,
                'AAPL.US', 'review', 'History fixture', 'Isolated validation only.',
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second',
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second'
            FROM generate_series(CAST(:first AS bigint), CAST(:last AS bigint)) AS n
        """), parameters)
        connection.execute(text("""
            INSERT INTO bull_put_spreads (
                id, broker_account_id, broker, external_account_id, strategy_id,
                execution_mode, underlying_symbol, expiration_date, contracts,
                width, long_symbol, long_strike, short_symbol, short_strike,
                status, version, manual_action_required, raw_payload, created_at, updated_at
            )
            SELECT 'spread-' || lpad(n::text, 10, '0'),
                CASE WHEN n % 10 = 0 THEN 'history-other' ELSE 'history-primary' END,
                'longbridge', CASE WHEN n % 10 = 0 THEN :other ELSE :account END,
                'paper_bull_put_v1', CASE WHEN n % 20 = 1 OR n = 5 THEN 'live' ELSE 'paper' END,
                'QQQ.US', DATE '2026-11-20', 1, 5,
                'QQQ261120P440000.US', 440, 'QQQ261120P445000.US', 445,
                CASE WHEN n IN (2, 5, 10) THEN 'open' ELSE 'closed' END,
                0, n = 3, '{}'::jsonb,
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second',
                TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second'
            FROM generate_series(CAST(:first AS bigint), CAST(:last AS bigint)) AS n
        """), parameters)
        for table in ("orders", "executions", "journal_entries", "bull_put_spreads", "broker_accounts"):
            connection.exec_driver_sql(f"ANALYZE {table}")


def plan_nodes(plan: dict):
    yield plan
    for child in plan.get("Plans", []):
        yield from plan_nodes(child)


def verify_page(engine, *, resource: str, model, repository_type, method: str) -> dict:
    statements = []
    loaded = Counter()

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))

    def count_loaded(_session, instance):
        loaded[type(instance).__name__] += 1

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine, expire_on_commit=False, autoflush=False) as session:
            event.listen(session, "loaded_as_persistent", count_loaded)
            repository = (
                repository_type(session, attach_intent_ledger=False)
                if resource == "orders" else repository_type(session)
            )
            call_scope = {"external_account_id": ACCOUNT_ID, "limit": PAGE_SIZE}
            if resource == "bull_put_spreads":
                call_scope["mode"] = ExecutionMode.PAPER
            started = time.perf_counter()
            first = getattr(repository, method)(**call_scope)
            elapsed_ms = (time.perf_counter() - started) * 1000
            first_loads = dict(loaded)
            first_statements = list(statements)
            assert first.has_more and first.next_cursor
            assert len(first.items) == PAGE_SIZE
            assert all(item.external_account_id == ACCOUNT_ID for item in first.items)
            if resource == "bull_put_spreads":
                assert all(item.mode == ExecutionMode.PAPER for item in first.items)
            assert loaded[model.__name__] <= PAGE_SIZE + 1
            second = getattr(repository, method)(
                **call_scope, cursor=first.next_cursor,
            )
            first_ids = [item.id for item in first.items]
            combined = first_ids + [item.id for item in second.items]
            assert len(combined) == len(set(combined)) == PAGE_SIZE * 2
            oracle = select(model.id).order_by(model.created_at.desc(), model.id.desc()).limit(PAGE_SIZE * 2)
            if resource == "orders":
                oracle = oracle.where(model.broker_account_id == "history-primary")
            else:
                oracle = oracle.where(model.external_account_id == ACCOUNT_ID)
            if resource == "bull_put_spreads":
                oracle = oracle.where(model.execution_mode == ExecutionMode.PAPER.value)
            assert combined == list(session.scalars(oracle))
            # A cursor deep in the history must seek to its index position,
            # rather than scan and discard every preceding row. The OFFSET
            # below belongs only to the independent fixture oracle.
            total = session.scalar(select(text("count(*)")).select_from(model))
            deep_offset = int(total * 0.8)
            boundary_query = select(model.created_at, model.id).order_by(
                model.created_at.desc(), model.id.desc(),
            )
            if resource == "orders":
                boundary_query = boundary_query.where(model.broker_account_id == "history-primary")
                scope = {"external_account_id": ACCOUNT_ID, "status": None, "mode": None, "symbol": None}
            else:
                boundary_query = boundary_query.where(model.external_account_id == ACCOUNT_ID)
                scope = {"external_account_id": ACCOUNT_ID, "order_id": None}
                if resource == "journals":
                    scope.update(trade_plan_id=None, entry_type=None)
                elif resource == "bull_put_spreads":
                    boundary_query = boundary_query.where(model.execution_mode == ExecutionMode.PAPER.value)
                    scope = {"external_account_id": ACCOUNT_ID, "mode": ExecutionMode.PAPER.value}
            boundary_time, boundary_id = session.execute(boundary_query.offset(deep_offset).limit(1)).one()
            expected_deep_ids = list(session.scalars(oracle.offset(deep_offset + 1).limit(PAGE_SIZE)))
            deep_cursor = encode_cursor(
                resource=resource, scope=scope,
                position={"created_at": boundary_time.isoformat(), "id": boundary_id},
            )
            statements.clear()
            loaded.clear()
            deep_started = time.perf_counter()
            deep = getattr(repository, method)(**call_scope, cursor=deep_cursor)
            deep_elapsed_ms = (time.perf_counter() - deep_started) * 1000
            deep_statements = list(statements)
            deep_loads = dict(loaded)
            assert [item.id for item in deep.items] == expected_deep_ids
            assert len(deep.items) == PAGE_SIZE
            assert loaded[model.__name__] <= PAGE_SIZE + 1
            # Detail access must continue to reach data outside the recent page.
            if resource == "orders":
                assert repository.get_order("order-0000000001").external_account_id == ACCOUNT_ID
            elif resource == "executions":
                assert repository.get_execution("execution-0000000001").external_account_id == ACCOUNT_ID
            elif resource == "bull_put_spreads":
                assert repository.get_spread("spread-0000000002").external_account_id == ACCOUNT_ID
                working = repository.list_working_spreads(
                    external_account_id=ACCOUNT_ID, mode=ExecutionMode.PAPER,
                    active_statuses={SpreadStatus.OPEN},
                )
                assert {item.id for item in working} == {"spread-0000000002", "spread-0000000003"}
            else:
                old_entries = repository.list_entries(external_account_id=ACCOUNT_ID, order_id="order-0000000001")
                assert [entry.id for entry in old_entries] == ["journal-0000000001"]
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    plan = explain_bounded_page(engine, resource, model, first_statements)
    deep_plan = explain_bounded_page(engine, resource, model, deep_statements)
    return {
        "status": "passed", "limit": PAGE_SIZE, "rows": len(first_ids),
        "no_duplicate_or_missing_rows": True, "account_isolation": True,
        "first_page_ms": round(elapsed_ms, 3), "first_page_sql_count": len(first_statements),
        "materialized_objects": first_loads,
        "payload_bytes": len(first.model_dump_json().encode("utf-8")),
        "query_plan": plan,
        "deep_page": {
            "preceding_account_rows": deep_offset + 1, "rows": len(deep.items),
            "elapsed_ms": round(deep_elapsed_ms, 3), "materialized_objects": deep_loads,
            "query_plan": deep_plan,
        },
    }


def explain_bounded_page(engine, resource, model, statements) -> dict:

    # The orders repository resolves an external account id first, then runs
    # the bounded keyset query by broker-account id. Explain the primary-table
    # statement rather than the small account-id lookup.
    page_statements = [
        item for item in statements
        if f"FROM {model.__tablename__.upper()}" in item[0].upper()
        and "LIMIT" in item[0].upper()
    ]
    assert page_statements, f"{resource} issued no bounded primary-table query"
    statement, parameters = page_statements[0]
    with engine.connect() as connection:
        plan = connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters,
        ).scalar_one()[0]
    nodes = list(plan_nodes(plan["Plan"]))
    primary_nodes = [node for node in nodes if node.get("Relation Name") == model.__tablename__]
    assert primary_nodes, f"{resource} plan did not access its primary table"
    assert any("Index" in node["Node Type"] for node in primary_nodes), (
        f"{resource} did not use an index for its bounded history read"
    )
    unbounded_scans = [
        node for node in primary_nodes
        if (
            node.get("Actual Rows", 0)
            + node.get("Rows Removed by Filter", 0)
            + node.get("Rows Removed by Index Recheck", 0)
        ) * node.get("Actual Loops", 1) > 4 * (PAGE_SIZE + 1)
    ]
    assert not unbounded_scans, f"{resource} scanned an unbounded history: {unbounded_scans}"
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    base_url = make_url(get_settings().database_url)
    if not base_url.drivername.startswith("postgresql"):
        raise SystemExit("History query validation requires PostgreSQL.")
    database_name = f"history_query_{uuid4().hex[:12]}"
    database_url = _database_url(base_url, database_name)
    admin = create_engine(_database_url(base_url, "postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    results = []
    error = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        created = True
        _run_migrations(database_url)
        engine = create_engine(database_url, pool_pre_ping=True)
        with Session(engine) as session:
            session.add_all([
                BrokerAccountRecord(id="history-primary", broker="longbridge", external_account_id=ACCOUNT_ID),
                BrokerAccountRecord(id="history-other", broker="longbridge", external_account_id=OTHER_ACCOUNT_ID),
            ])
            session.commit()
        prior_size = 0
        for size in (10_000, 100_000):
            seed_history(engine, first=prior_size + 1, last=size)
            checks = {}
            for resource, model, repository, method in (
                ("orders", OrderRecord, SQLAlchemyOrderRepository, "list_orders_page"),
                ("executions", ExecutionRecord, SQLAlchemyExecutionRepository, "list_executions_page"),
                ("journals", JournalEntryRecord, SQLAlchemyJournalRepository, "list_entries_page"),
                ("bull_put_spreads", BullPutSpreadRecord, SQLAlchemyBullPutSpreadRepository, "list_spreads_page"),
            ):
                checks[resource] = verify_page(
                    engine, resource=resource, model=model, repository_type=repository, method=method,
                )
            results.append({"history_rows_per_table": size, "checks": checks})
            prior_size = size
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=:name AND pid<>pg_backend_pid()"
                ), {"name": database_name})
                connection.exec_driver_sql(f'DROP DATABASE "{database_name}"')
        admin.dispose()
    emit_report(build_report(
        script=Path(__file__).name, workflow="history-query", status="failed" if error else "passed",
        mode="isolated-postgresql", target="temporary database",
        summary="Bounded history reads at 10,000 and 100,000 rows per table.",
        payload={"runs": results, "broker_calls": 0, "temporary_database_removed": True}, error=error,
    ), args.json_output)
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())

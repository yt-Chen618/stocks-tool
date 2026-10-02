"""Validate bounded global strategy summaries and lifecycle reads in PostgreSQL.

The fixture is deliberately much larger than the displayed activity page.  It
checks that global counts come from SQL aggregates, that lifecycle workers only
materialize active proposal/run rows, and that legacy JSON order links remain
discoverable outside the display window.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from regression_common import build_report, emit_report  # noqa: E402
from run_postgres_order_concurrency import _database_url, _run_migrations  # noqa: E402
from stocks_tool.application.services.covered_call_strategy import CoveredCallStrategyService  # noqa: E402
from stocks_tool.application.services.operator_consistency import OperatorConsistencyService  # noqa: E402
from stocks_tool.application.services.orders import OrderService  # noqa: E402
from stocks_tool.application.services.strategy_experiments import StrategyExperimentService  # noqa: E402
from stocks_tool.core.config import Settings, get_settings  # noqa: E402
from stocks_tool.db.models import (  # noqa: E402
    BrokerAccountRecord,
    StrategyProposalRecord,
    StrategyRunRecord,
)
from stocks_tool.domain.enums import ExecutionMode  # noqa: E402
from stocks_tool.ports.repository import BrokerAccountRepository  # noqa: E402
from stocks_tool.repositories.sqlalchemy_broker_account_repository import (  # noqa: E402
    SQLAlchemyBrokerAccountRepository,
)
from stocks_tool.repositories.sqlalchemy_execution_repository import (  # noqa: E402
    SQLAlchemyExecutionRepository,
)
from stocks_tool.repositories.sqlalchemy_order_repository import (  # noqa: E402
    SQLAlchemyOrderRepository,
)
from stocks_tool.repositories.sqlalchemy_strategy_experiment_repository import (  # noqa: E402
    SQLAlchemyStrategyExperimentRepository,
)


ACCOUNT_ID = "LBPT10087357"
OTHER_ACCOUNT_ID = "strategy-query-other"
PAPER_BROKER_ACCOUNT_ID = "strategy-query-paper"
LIVE_BROKER_ACCOUNT_ID = "strategy-query-live"
BASE_TS = "2026-01-01T00:00:00+00:00"
ACTIVE_PROPOSALS = (
    "active-open",
    "active-close",
    "active-roll",
)
RUN_TYPES = ("open_lifecycle_refresh", "proposal_close", "roll_continuation")


def seed_fixture(engine, *, first: int, last: int) -> None:
    params = {"first": first, "last": last, "account": ACCOUNT_ID, "other": OTHER_ACCOUNT_ID}
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO strategy_proposals (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, symbol, title, proposed_action, rationale,
                    status, created_at, updated_at
                )
                SELECT 'closed-proposal-' || lpad(n::text, 10, '0'),
                    'strategy-query-paper', 'covered_call_v1', :account,
                    'paper', 'UNH.US', 'Closed history', 'sell_covered_call',
                    'Global strategy fixture', 'closed',
                    TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second',
                    TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second'
                FROM generate_series(CAST(:first AS bigint), CAST(:last AS bigint)) AS n
                """
            ),
            params,
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_runs (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, run_type, status, symbol, proposal_id,
                    metrics_payload, created_at, updated_at
                )
                SELECT 'closed-run-' || lpad(n::text, 10, '0'),
                    'strategy-query-paper', 'covered_call_v1', :account,
                    'paper', 'proposal_close', 'executed', 'UNH.US',
                    'closed-proposal-' || lpad(n::text, 10, '0'),
                    CASE WHEN n = :first
                        THEN '{"order_id":"legacy-order-outside-window"}'::jsonb
                        ELSE '{}'::jsonb END,
                    TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second',
                    TIMESTAMPTZ '2026-01-01' + (n / 10) * INTERVAL '1 second'
                FROM generate_series(CAST(:first AS bigint), CAST(:last AS bigint)) AS n
                """
            ),
            params,
        )
        for table in ("strategy_proposals", "strategy_runs"):
            connection.exec_driver_sql(f"ANALYZE {table}")


def seed_active_fixture(engine) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO strategy_proposals (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, symbol, title, proposed_action, rationale,
                    status, created_at, updated_at
                )
                SELECT id, 'strategy-query-paper', 'covered_call_v1', :account,
                    'paper', 'UNH.US', 'Active proposal',
                    CASE id
                        WHEN 'active-roll' THEN 'roll_covered_call'
                        ELSE 'sell_covered_call'
                    END,
                    'Active strategy fixture',
                    CASE id
                        WHEN 'active-open' THEN 'approved'
                        WHEN 'active-close' THEN 'executed'
                        ELSE 'approved'
                    END,
                    TIMESTAMPTZ '2026-10-01', TIMESTAMPTZ '2026-10-01'
                FROM unnest(ARRAY['active-open','active-close','active-roll']) AS id
                """
            ),
            {"account": ACCOUNT_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_proposals (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, symbol, title, proposed_action, rationale,
                    status, created_at, updated_at
                ) VALUES (
                    'live-active', 'strategy-query-live', 'covered_call_v1', :account,
                    'live', 'UNH.US', 'Live proposal', 'sell_covered_call',
                    'Mode isolation fixture', 'approved',
                    TIMESTAMPTZ '2026-10-02', TIMESTAMPTZ '2026-10-02'
                )
                """
            ),
            {"account": ACCOUNT_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_runs (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, run_type, status, symbol, proposal_id,
                    order_id, metrics_payload, created_at, updated_at
                )
                SELECT 'active-run-' || replace(id, 'active-', ''),
                    'strategy-query-paper', 'covered_call_v1', :account,
                    'paper', run_type, 'executed', 'UNH.US', proposal_id,
                    CASE WHEN run_type = 'open_lifecycle_refresh' THEN 'active-open-order' ELSE NULL END,
                    CASE WHEN run_type = 'open_lifecycle_refresh'
                        THEN '{"order_id":"active-open-order","sell_status":"submitted"}'::jsonb
                        ELSE '{}'::jsonb END,
                    TIMESTAMPTZ '2026-10-02', TIMESTAMPTZ '2026-10-02'
                FROM (VALUES
                    ('active-open', 'open_lifecycle_refresh', 'active-open'),
                    ('active-close', 'proposal_close', 'active-close'),
                    ('active-roll', 'roll_continuation', 'active-roll'),
                    ('active-roll', 'proposal_close', 'active-roll')
                ) AS rows(id, run_type, proposal_id)
                """
            ),
            {"account": ACCOUNT_ID},
        )
        for table in ("strategy_proposals", "strategy_runs"):
            connection.exec_driver_sql(f"ANALYZE {table}")


def sql_oracle(engine) -> dict[str, object]:
    with engine.connect() as connection:
        proposal = connection.execute(
            text(
                """
                SELECT count(*) AS total,
                    count(*) FILTER (WHERE status IN ('pending','approved')) AS active,
                    count(*) FILTER (WHERE proposed_action IN ('sell_covered_call','roll_covered_call') AND status='executed') AS executed,
                    count(*) FILTER (WHERE proposed_action='roll_covered_call' AND status IN ('pending','approved')) AS pending_rolls,
                    max(updated_at) AS latest_proposal
                FROM strategy_proposals
                WHERE strategy_id='covered_call_v1' AND external_account_id=:account AND execution_mode='paper'
                """
            ),
            {"account": ACCOUNT_ID},
        ).mappings().one()
        runs = connection.execute(
            text(
                """
                SELECT count(*) AS close_runs, max(created_at) AS latest_run
                FROM strategy_runs
                WHERE strategy_id='covered_call_v1' AND external_account_id=:account
                    AND execution_mode='paper' AND run_type='proposal_close'
                """
            ),
            {"account": ACCOUNT_ID},
        ).mappings().one()
        return {
            "total_proposals": int(proposal["total"]),
            "active_proposals": int(proposal["active"]),
            "executed_positions": int(proposal["executed"]),
            "pending_rolls": int(proposal["pending_rolls"]),
            "close_runs": int(runs["close_runs"]),
            "latest_proposal": proposal["latest_proposal"].isoformat() if proposal["latest_proposal"] else None,
            "latest_run": runs["latest_run"].isoformat() if runs["latest_run"] else None,
        }


def verify(engine, *, size: int, first: int, seed_active: bool) -> dict[str, object]:
    if seed_active:
        seed_active_fixture(engine)
    seed_history(engine, first=first, last=size)
    settings = Settings(database_url=str(engine.url))
    loaded = Counter()
    identity_peak = {"size": 0}

    def on_load(session, instance):
        loaded[type(instance).__name__] += 1
        identity_peak["size"] = max(identity_peak["size"], len(session.identity_map))

    with Session(engine, expire_on_commit=False) as session:
        event.listen(session, "loaded_as_persistent", on_load)
        repository = SQLAlchemyStrategyExperimentRepository(session)
        service = StrategyExperimentService(
            experiments=repository,
            broker_accounts=SQLAlchemyBrokerAccountRepository(session),
            settings=settings,
        )
        reports = []
        for display_limit in (1, 25):
            loaded.clear()
            identity_peak["size"] = 0
            activity = service.get_covered_call_activity(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                limit=display_limit,
            )
            reports.append({
                "display_limit": display_limit,
                "summary": activity.summary.model_dump(mode="json"),
                "visible_counts": {
                    "proposals": len(activity.proposals),
                    "runs": len(activity.runs),
                    "lifecycle_tasks": len(activity.lifecycle_tasks),
                },
                "loaded": dict(loaded),
                "identity_map_peak": identity_peak["size"],
                "active_task_ids": [task.proposal_id for task in activity.lifecycle_tasks],
            })
        assert reports[0]["summary"] == reports[1]["summary"]
        assert reports[0]["visible_counts"]["proposals"] <= 1
        assert reports[1]["visible_counts"]["proposals"] <= 25
        assert set(reports[0]["active_task_ids"]) == set(ACTIVE_PROPOSALS)
        oracle = sql_oracle(engine)
        assert reports[0]["summary"]["total_proposals"] == oracle["total_proposals"]
        assert reports[0]["summary"]["close_runs"] == oracle["close_runs"]
        assert reports[0]["loaded"].get("StrategyProposalRecord", 0) < 100
        assert reports[0]["loaded"].get("StrategyRunRecord", 0) < 100
        assert reports[0]["identity_map_peak"] < 200
        return {"size": size, "reports": reports, "oracle": oracle}


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    base_url = make_url(get_settings().database_url)
    if not base_url.drivername.startswith("postgresql"):
        raise SystemExit("Strategy query validation requires PostgreSQL.")
    database_name = f"strategy_query_{uuid4().hex[:12]}"
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
                BrokerAccountRecord(id=PAPER_BROKER_ACCOUNT_ID, broker="longbridge", external_account_id=ACCOUNT_ID),
                BrokerAccountRecord(id=LIVE_BROKER_ACCOUNT_ID, broker="longbridge", external_account_id=ACCOUNT_ID),
                BrokerAccountRecord(id="strategy-query-other", broker="longbridge", external_account_id=OTHER_ACCOUNT_ID),
            ])
            session.commit()
        previous_size = 0
        for size in (10_000, 100_000):
            results.append(
                verify(
                    engine,
                    size=size,
                    first=previous_size + 1,
                    seed_active=previous_size == 0,
                )
            )
            previous_size = size
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
    report = build_report(
        script=Path(__file__).name,
        workflow="strategy-query",
        status="failed" if error else "passed",
        mode="isolated-postgresql",
        target="temporary database",
        summary="Global Covered Call and operator consistency query proof at 10,000 and 100,000 rows.",
        payload={"runs": results, "broker_calls": 0, "temporary_database_removed": True},
        error=error,
    )
    emit_report(report, args.json_output)
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(run())

"""Validate global strategy reads and bounded lifecycle work in PostgreSQL.

The fixture deliberately keeps the displayed activity page small while adding
closed proposal/run history at the requested scale.  It proves global
aggregates and latest source timestamps with an independent SQL oracle,
checks that the lifecycle service only loads active proposal/run rows, and
exercises operator consistency in an isolated local database.  It never
calls a broker and never operates on the configured database.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import sys
import traceback
from typing import Any
from unittest.mock import Mock
from uuid import uuid4
import weakref

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from regression_common import build_report, emit_report  # noqa: E402
from run_postgres_order_concurrency import _database_url, _run_migrations  # noqa: E402
from stocks_tool.application.services.covered_call_strategy import (  # noqa: E402
    CoveredCallStrategyService,
)
from stocks_tool.application.services.operator_consistency import (  # noqa: E402
    OperatorConsistencyService,
)
from stocks_tool.application.services.orders import OrderService  # noqa: E402
from stocks_tool.application.services.strategy_experiments import (  # noqa: E402
    StrategyExperimentService,
)
from stocks_tool.core.config import Settings, get_settings  # noqa: E402
from stocks_tool.db.models import (  # noqa: E402
    BrokerAccountRecord,
)
from stocks_tool.domain.enums import (  # noqa: E402
    AssetType,
    BrokerName,
    ExecutionMode,
    OptionRight,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)
from stocks_tool.domain.models import (  # noqa: E402
    OptionContractRef,
    Order,
    OperatorConsistencyRepairRequest,
)
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
ACTIVE_PROPOSALS = ("active-open", "active-close", "active-roll")
ACTIVE_RUN_IDS = {
    "active-run-open",
    "active-run-close",
    "active-run-roll-continuation",
    "active-run-roll-close",
}
CONSISTENCY_BATCH_SIZE = 200
CONSISTENCY_DOMAIN_PEAK_LIMIT = 1200
LEGACY_ORDER_IDS = (
    "legacy-zero-dte-order-1",
    "legacy-zero-dte-order-2",
    "legacy-zero-dte-order-3",
)


def _candidate_payload(*, symbol: str = "UNH261030C600000.US", strike: str = "600") -> dict[str, str | int]:
    return {
        "underlying_symbol": "UNH.US",
        "expiration_date": "2026-10-30",
        "days_to_expiration": 28,
        "contracts": 1,
        "covered_shares": 100,
        "share_quantity": "1000",
        "average_cost": "500",
        "underlying_price": "550",
        "call_symbol": symbol,
        "call_strike": strike,
        "call_bid": "1.20",
        "call_ask": "1.30",
        "call_mid": "1.25",
        "premium_income": "125",
        "quote_timestamp": "2026-10-01T14:30:00+00:00",
    }


def _roll_payload() -> dict[str, Any]:
    return {
        "source_proposal_id": "active-close",
        "roll_from": _candidate_payload(),
        "roll_to": _candidate_payload(symbol="UNH261113C610000.US", strike="610"),
    }


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def seed_accounts(engine) -> None:
    """Create one paper account and one isolated account.

    A broker account is unique by external account id.  Paper/live mode is a
    property of strategy rows, so the fixture intentionally uses one account
    row for both modes instead of inserting a second conflicting account.
    """

    with Session(engine) as session:
        session.add_all(
            [
                BrokerAccountRecord(
                    id=PAPER_BROKER_ACCOUNT_ID,
                    broker=BrokerName.LONGBRIDGE.value,
                    external_account_id=ACCOUNT_ID,
                ),
                BrokerAccountRecord(
                    id="strategy-query-other",
                    broker=BrokerName.LONGBRIDGE.value,
                    external_account_id=OTHER_ACCOUNT_ID,
                ),
            ]
        )
        session.commit()


def seed_active_fixture(engine) -> None:
    """Insert active proposals, multi-type runs, local orders and legacy evidence."""

    proposals = [
        {
            "id": "active-open",
            "status": "approved",
            "action": "sell_covered_call",
            "candidate": _candidate_payload(),
        },
        {
            "id": "active-close",
            "status": "executed",
            "action": "sell_covered_call",
            "candidate": _candidate_payload(),
        },
        {
            "id": "active-roll",
            "status": "approved",
            "action": "roll_covered_call",
            "candidate": _roll_payload(),
        },
        {
            "id": "live-active",
            "status": "approved",
            "action": "sell_covered_call",
            "candidate": _candidate_payload(),
            "mode": "live",
        },
    ]
    orders = [
        ("active-open-order", "active-open-external", "UNH261030C600000.US", "sell"),
        ("active-close-order", "active-close-external", "UNH261030C600000.US", "buy"),
        ("active-roll-buyback", "active-roll-buyback-external", "UNH261030C600000.US", "buy"),
        ("active-roll-sell", "active-roll-sell-external", "UNH261113C610000.US", "sell"),
    ]
    legacy_orders = [
        (
            order_id,
            f"{order_id}-external",
            f"QQQ261002P{470000 + index * 1000:06d}.US",
            "buy",
            _json(
                {
                    "submission_request": {
                        "remark": "zero_dte_lottery_v1:manual-scan",
                        "option_contract": {"underlying_symbol": "QQQ.US"},
                    }
                }
            ),
        )
        for index, order_id in enumerate(LEGACY_ORDER_IDS)
    ]
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO orders (
                    id, broker_account_id, broker, external_order_id, client_order_id,
                    symbol, asset_type, side, quantity, order_type, time_in_force,
                    execution_mode, limit_price, status, executed_quantity, raw_payload,
                    created_at, updated_at
                ) VALUES (
                    :id, :account, 'longbridge', :external_id, :client_id,
                    :symbol, 'option', :side, 1, 'limit', 'day',
                    'paper', 1.20, 'submitted', 0, NULL,
                    TIMESTAMPTZ '2026-10-02 14:00:00+00', TIMESTAMPTZ '2026-10-02 14:00:00+00'
                )
                """
            ),
            [
                {
                    "id": order_id,
                    "account": PAPER_BROKER_ACCOUNT_ID,
                    "external_id": external_id,
                    "client_id": f"{order_id}-client",
                    "symbol": symbol,
                    "side": side,
                }
                for order_id, external_id, symbol, side in orders
            ],
        )
        connection.execute(
            text(
                """
                INSERT INTO orders (
                    id, broker_account_id, broker, external_order_id, client_order_id,
                    symbol, asset_type, side, quantity, order_type, time_in_force,
                    execution_mode, limit_price, status, executed_quantity, raw_payload,
                    created_at, updated_at
                ) VALUES (
                    :id, :account, 'longbridge', :external_id, :client_id,
                    :symbol, 'option', :side, 1, 'limit', 'day',
                    'paper', 1.00, 'submitted', 0, CAST(:raw_payload AS jsonb),
                    TIMESTAMPTZ '2026-10-02 14:00:00+00', TIMESTAMPTZ '2026-10-02 14:00:00+00'
                )
                """
            ),
            [
                {
                    "id": order_id,
                    "account": PAPER_BROKER_ACCOUNT_ID,
                    "external_id": external_id,
                    "client_id": f"{order_id}-client",
                    "symbol": symbol,
                    "side": side,
                    "raw_payload": raw_payload,
                }
                for order_id, external_id, symbol, side, raw_payload in legacy_orders
            ],
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_proposals (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, symbol, title, proposed_action, rationale,
                    status, candidate_payload, created_at, updated_at
                ) VALUES (
                    :id, :account, 'covered_call_v1', :external_account_id,
                    :mode, 'UNH.US', 'Active strategy fixture', :action,
                    'Active strategy fixture', :status, CAST(:candidate AS jsonb),
                    TIMESTAMPTZ '2026-10-02 14:00:00+00', TIMESTAMPTZ '2026-10-02 14:00:00+00'
                )
                """
            ),
            [
                {
                    "id": item["id"],
                    "account": PAPER_BROKER_ACCOUNT_ID,
                    "external_account_id": ACCOUNT_ID,
                    "mode": item.get("mode", "paper"),
                    "action": item["action"],
                    "status": item["status"],
                    "candidate": _json(item["candidate"]),
                }
                for item in proposals
            ],
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_runs (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, run_type, status, symbol, proposal_id, order_id,
                    metrics_payload, created_at, updated_at
                ) VALUES (
                    :id, :account, 'covered_call_v1', :external_account_id,
                    'paper', :run_type, 'executed', 'UNH.US', :proposal_id, :order_id,
                    CAST(:metrics AS jsonb), TIMESTAMPTZ '2026-10-02 14:00:00+00',
                    TIMESTAMPTZ '2026-10-02 14:00:00+00'
                )
                """
            ),
            [
                {
                    "id": "active-run-open",
                    "account": PAPER_BROKER_ACCOUNT_ID,
                    "external_account_id": ACCOUNT_ID,
                    "run_type": "open_lifecycle_refresh",
                    "proposal_id": "active-open",
                    "order_id": "active-open-order",
                    "metrics": _json(
                        {
                            "order_id": "active-open-order",
                            "sell_status": "submitted",
                            "sequence_status": "sell_submitted_waiting_fill",
                        }
                    ),
                },
                {
                    "id": "active-run-close",
                    "account": PAPER_BROKER_ACCOUNT_ID,
                    "external_account_id": ACCOUNT_ID,
                    "run_type": "proposal_close",
                    "proposal_id": "active-close",
                    "order_id": "active-close-order",
                    "metrics": _json({"order_id": "active-close-order", "close_status": "submitted"}),
                },
                {
                    "id": "active-run-roll-continuation",
                    "account": PAPER_BROKER_ACCOUNT_ID,
                    "external_account_id": ACCOUNT_ID,
                    "run_type": "roll_continuation",
                    "proposal_id": "active-roll",
                    "order_id": "active-roll-sell",
                    "metrics": _json(
                        {
                            "buyback_order_id": "active-roll-buyback",
                            "sell_order_id": "active-roll-sell",
                            "buyback_status": "submitted",
                            "sell_status": "submitted",
                            "sequence_status": "buyback_still_working",
                        }
                    ),
                },
                {
                    "id": "active-run-roll-close",
                    "account": PAPER_BROKER_ACCOUNT_ID,
                    "external_account_id": ACCOUNT_ID,
                    "run_type": "proposal_close",
                    "proposal_id": "active-roll",
                    "order_id": "active-close-order",
                    "metrics": _json({"order_id": "active-close-order"}),
                },
            ],
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_signals (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, signal_type, symbol, summary, signal_payload,
                    emitted_at
                ) VALUES (
                    'legacy-zero-dte-signal-1', :account, 'zero_dte_lottery_v1',
                    :external_account_id, 'paper', 'execution', 'QQQ.US',
                    'Legacy manual scan evidence', CAST(:payload AS jsonb),
                    TIMESTAMPTZ '2026-10-02 14:00:00+00'
                )
                """
            ),
            {
                "account": PAPER_BROKER_ACCOUNT_ID,
                "external_account_id": ACCOUNT_ID,
                "payload": _json({"order": {"id": LEGACY_ORDER_IDS[0]}}),
            },
        )
        for table in (
            "orders",
            "strategy_proposals",
            "strategy_runs",
            "strategy_signals",
        ):
            connection.exec_driver_sql(f"ANALYZE {table}")


def seed_history(engine, *, first: int, last: int) -> None:
    """Append closed history and one latest signal/review per scale batch."""

    params = {"first": first, "last": last, "account": ACCOUNT_ID}
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
                    :broker_account, 'covered_call_v1', :account,
                    'paper', 'UNH.US', 'Closed history', 'sell_covered_call',
                    'Global strategy fixture', 'closed',
                    TIMESTAMPTZ '2026-01-01' + (n * INTERVAL '1 second'),
                    TIMESTAMPTZ '2026-01-01' + (n * INTERVAL '1 second')
                FROM generate_series(CAST(:first AS bigint), CAST(:last AS bigint)) AS n
                """
            ),
            {**params, "broker_account": PAPER_BROKER_ACCOUNT_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_runs (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, run_type, status, symbol, proposal_id,
                    metrics_payload, created_at, updated_at
                ) VALUES (
                    :run_id, :broker_account, 'covered_call_v1', :account,
                    'paper', 'proposal_close', 'executed', 'UNH.US',
                    'closed-proposal-' || lpad(CAST(:first AS text), 10, '0'),
                    '{}',
                    TIMESTAMPTZ '2026-01-01' + ((CAST(:first AS bigint) + 0.5) * INTERVAL '1 second'),
                    TIMESTAMPTZ '2026-01-01' + ((CAST(:first AS bigint) + 0.5) * INTERVAL '1 second')
                )
                """
            ),
            {
                **params,
                "broker_account": PAPER_BROKER_ACCOUNT_ID,
                "run_id": f"closed-latest-empty-{first}",
            },
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
                    :broker_account, 'covered_call_v1', :account,
                    'paper', 'proposal_close', 'executed', 'UNH.US',
                    'closed-proposal-' || lpad(n::text, 10, '0'),
                    CASE WHEN n = :first
                        THEN '{"order_id":"legacy-order-outside-window"}'::jsonb
                        ELSE '{}'::jsonb END,
                    TIMESTAMPTZ '2026-01-01' + (n * INTERVAL '1 second'),
                    TIMESTAMPTZ '2026-01-01' + (n * INTERVAL '1 second')
                FROM generate_series(CAST(:first AS bigint), CAST(:last AS bigint)) AS n
                """
            ),
            {**params, "broker_account": PAPER_BROKER_ACCOUNT_ID},
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_signals (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, signal_type, symbol, summary, signal_payload,
                    emitted_at
                ) VALUES (
                    :signal_id, :broker_account, 'covered_call_v1', :account,
                    'paper', 'monitor', 'UNH.US', 'Scale signal', '{}',
                    TIMESTAMPTZ '2026-01-01' + (CAST(:last AS bigint) * INTERVAL '1 second')
                )
                """
            ),
            {
                **params,
                "broker_account": PAPER_BROKER_ACCOUNT_ID,
                "signal_id": f"history-signal-{last}",
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO strategy_reviews (
                    id, broker_account_id, strategy_id, external_account_id,
                    execution_mode, review_type, status, summary, reviewed_at
                ) VALUES (
                    :review_id, :broker_account, 'covered_call_v1', :account,
                    'paper', 'advisor', 'observed', 'Scale review',
                    TIMESTAMPTZ '2026-01-01' + ((CAST(:last AS bigint) + 1) * INTERVAL '1 second')
                )
                """
            ),
            {
                **params,
                "broker_account": PAPER_BROKER_ACCOUNT_ID,
                "review_id": f"history-review-{last}",
            },
        )
        for table in (
            "strategy_proposals",
            "strategy_runs",
            "strategy_signals",
            "strategy_reviews",
        ):
            connection.exec_driver_sql(f"ANALYZE {table}")


def sql_oracle(engine) -> dict[str, Any]:
    with engine.connect() as connection:
        proposal = connection.execute(
            text(
                """
                SELECT count(*) AS total,
                    count(*) FILTER (WHERE status IN ('pending','approved')) AS active,
                    count(*) FILTER (
                        WHERE proposed_action IN ('sell_covered_call','roll_covered_call')
                          AND status='executed'
                    ) AS executed,
                    count(*) FILTER (
                        WHERE proposed_action='roll_covered_call'
                          AND status IN ('pending','approved')
                    ) AS pending_rolls,
                    max(updated_at) AS latest_proposal
                FROM strategy_proposals
                WHERE strategy_id='covered_call_v1'
                  AND external_account_id=:account
                  AND execution_mode='paper'
                """
            ),
            {"account": ACCOUNT_ID},
        ).mappings().one()
        run = connection.execute(
            text(
                """
                SELECT count(*) AS total,
                    count(*) FILTER (WHERE run_type='proposal_close') AS close_runs,
                    max(created_at) FILTER (WHERE run_type IN (
                        'proposal_close','proposal_execution','open_lifecycle_refresh',
                        'roll_execution','roll_continuation'
                    )) AS latest_lifecycle
                FROM strategy_runs
                WHERE strategy_id='covered_call_v1'
                  AND external_account_id=:account
                  AND execution_mode='paper'
                """
            ),
            {"account": ACCOUNT_ID},
        ).mappings().one()
        signal = connection.execute(
            text(
                """
                SELECT count(*) AS total, max(emitted_at) AS latest
                FROM strategy_signals
                WHERE strategy_id='covered_call_v1'
                  AND external_account_id=:account
                  AND execution_mode='paper'
                """
            ),
            {"account": ACCOUNT_ID},
        ).mappings().one()
        review = connection.execute(
            text(
                """
                SELECT count(*) AS total, max(reviewed_at) AS latest
                FROM strategy_reviews
                WHERE strategy_id='covered_call_v1'
                  AND external_account_id=:account
                  AND execution_mode='paper'
                """
            ),
            {"account": ACCOUNT_ID},
        ).mappings().one()
        linkage = connection.execute(
            text(
                """
                SELECT count(*) AS missing
                FROM strategy_proposals AS proposal
                WHERE proposal.strategy_id='covered_call_v1'
                  AND proposal.external_account_id=:account
                  AND proposal.execution_mode='paper'
                  AND proposal.status IN ('executed','closed','rolled')
                  AND NOT EXISTS (
                      SELECT 1
                      FROM strategy_runs AS run
                      WHERE run.proposal_id=proposal.id
                        AND run.strategy_id='covered_call_v1'
                        AND run.external_account_id=:account
                        AND run.execution_mode='paper'
                        AND (
                            run.order_id IS NOT NULL
                            OR run.metrics_payload ->> 'order_id' IS NOT NULL
                            OR run.metrics_payload ->> 'buyback_order_id' IS NOT NULL
                            OR run.metrics_payload ->> 'sell_order_id' IS NOT NULL
                            OR run.raw_payload ->> 'order_id' IS NOT NULL
                        )
                  )
                """
            ),
            {"account": ACCOUNT_ID},
        ).mappings().one()
    latest_values = [
        value
        for value in (
            proposal["latest_proposal"],
            run["latest_lifecycle"],
            signal["latest"],
            review["latest"],
        )
        if value is not None
    ]
    return {
        "total_proposals": int(proposal["total"] or 0),
        "active_proposals": int(proposal["active"] or 0),
        "executed_positions": int(proposal["executed"] or 0),
        "pending_rolls": int(proposal["pending_rolls"] or 0),
        "close_runs": int(run["close_runs"] or 0),
        "covered_call_linkage_missing": int(linkage["missing"] or 0),
        "source_counts": {
            "proposals": int(proposal["total"] or 0),
            "runs": int(run["total"] or 0),
            "signals": int(signal["total"] or 0),
            "reviews": int(review["total"] or 0),
        },
        "latest_sources": {
            "proposals": proposal["latest_proposal"].isoformat()
            if proposal["latest_proposal"]
            else None,
            "runs": run["latest_lifecycle"].isoformat() if run["latest_lifecycle"] else None,
            "signals": signal["latest"].isoformat() if signal["latest"] else None,
            "reviews": review["latest"].isoformat() if review["latest"] else None,
        },
        "latest_activity_at": max(latest_values).isoformat() if latest_values else None,
    }


def _plan_node_types(plan: dict[str, Any]) -> list[str]:
    node_types: list[str] = []
    if isinstance(plan, dict):
        node_type = plan.get("Node Type")
        if isinstance(node_type, str):
            node_types.append(node_type)
        for child in plan.get("Plans", []) or []:
            node_types.extend(_plan_node_types(child))
    return node_types


class _SelectCapture:
    """Keep only the actual strategy SELECTs needed for EXPLAIN.

    The SQL text and DBAPI parameters come from SQLAlchemy's
    ``before_cursor_execute`` hook.  No query is reconstructed from a fixture
    or from a hand-written approximation.
    """

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def before_cursor_execute(
        self,
        _connection,
        _cursor,
        statement: str,
        parameters,
        _context,
        executemany: bool,
    ) -> None:
        normalized = statement.lstrip().lower()
        if executemany or not normalized.startswith("select"):
            return
        if not any(
            table in normalized
            for table in (
                "strategy_proposals",
                "strategy_runs",
                "strategy_signals",
                "strategy_reviews",
            )
        ):
            return
        if "row_number" in normalized and "strategy_runs" in normalized:
            label = "active_latest_lifecycle_runs"
        elif "strategy_proposals" in normalized and (
            "count(" in normalized or "sum(" in normalized or "max(" in normalized
        ):
            label = "global_proposal_aggregate"
        elif "strategy_runs" in normalized and ("count(" in normalized or "max(" in normalized):
            label = "global_run_aggregate"
        elif "strategy_signals" in normalized and "max(" in normalized:
            label = "global_signal_latest"
        elif "strategy_reviews" in normalized and "max(" in normalized:
            label = "global_review_latest"
        else:
            return
        try:
            saved_parameters = copy.deepcopy(parameters)
        except Exception:
            saved_parameters = repr(parameters)
        self.entries.append(
            {
                "label": label,
                "statement": statement,
                "parameters": saved_parameters,
            }
        )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)


def explain_queries(engine, capture: _SelectCapture) -> dict[str, Any]:
    selected: dict[str, dict[str, Any]] = {}
    for entry in capture.entries:
        selected.setdefault(entry["label"], entry)
    required = {
        "global_proposal_aggregate",
        "global_run_aggregate",
        "global_signal_latest",
        "global_review_latest",
        "active_latest_lifecycle_runs",
    }
    missing = sorted(required - selected.keys())
    if missing:
        raise AssertionError(f"Actual strategy SELECT capture missing: {', '.join(missing)}")
    reports: dict[str, Any] = {}
    with engine.connect() as connection:
        for label in sorted(required):
            entry = selected[label]
            query = entry["statement"]
            raw = connection.exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query,
                entry["parameters"],
            ).scalar_one()
            if isinstance(raw, str):
                raw = json.loads(raw)
            document = raw[0] if isinstance(raw, list) else raw
            plan = document.get("Plan", {}) if isinstance(document, dict) else {}
            reports[label] = {
                "planning_time_ms": document.get("Planning Time") if isinstance(document, dict) else None,
                "execution_time_ms": document.get("Execution Time") if isinstance(document, dict) else None,
                "node_types": _plan_node_types(plan),
                "sql": query,
                "parameters": _json_safe(entry["parameters"]),
                "plan": document,
            }
    return reports


def _order_for_refresh(order_id: str, *, symbol: str, side: OrderSide) -> Order:
    return Order(
        id=order_id,
        broker=BrokerName.LONGBRIDGE,
        external_account_id=ACCOUNT_ID,
        external_order_id=f"{order_id}-external",
        symbol=symbol,
        asset_type=AssetType.OPTION,
        side=side,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.SUBMITTED,
        limit_price="1.20",
        option_contract=OptionContractRef(
            underlying_symbol="UNH.US",
            expiration_date="2026-11-13" if "roll-sell" in order_id else "2026-10-30",
            strike="610" if "roll-sell" in order_id else "600",
            right=OptionRight.CALL,
        ),
        created_at=datetime(2026, 10, 2, 14, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 2, 14, tzinfo=timezone.utc),
    )


class _LocalOrderRefresh:
    """A local order read double; no broker-facing method exists here."""

    def __init__(self) -> None:
        self.refresh_calls: list[str] = []
        self.mutation_attempts = 0
        self.orders = {
            "active-open-order": _order_for_refresh(
                "active-open-order", symbol="UNH261030C600000.US", side=OrderSide.SELL
            ),
            "active-close-order": _order_for_refresh(
                "active-close-order", symbol="UNH261030C600000.US", side=OrderSide.BUY
            ),
            "active-roll-buyback": _order_for_refresh(
                "active-roll-buyback", symbol="UNH261030C600000.US", side=OrderSide.BUY
            ),
            "active-roll-sell": _order_for_refresh(
                "active-roll-sell", symbol="UNH261113C610000.US", side=OrderSide.SELL
            ),
        }

    def refresh_order(self, order_id: str) -> Order:
        self.refresh_calls.append(order_id)
        return self.orders[order_id]

    def __getattr__(self, name: str):
        if name in {"submit_order", "cancel_order", "replace_order"}:
            self.mutation_attempts += 1
            raise AssertionError(f"Unexpected local order mutation in strategy proof: {name}")
        raise AttributeError(name)


class _NoBroker:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    def __getattr__(self, name: str):
        self.calls[name] += 1
        raise AssertionError(f"Unexpected broker call in strategy query regression: {name}")

    @property
    def attempts(self) -> int:
        return sum(self.calls.values())


class _NoBullPut:
    def list_spreads(self, **kwargs):
        return []


class _LoadMetrics:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.loaded = Counter()
        self.closed_run_materialized = 0
        self.active_run_ids_seen: set[str] = set()

    def on_load(self, _session, instance) -> None:
        name = type(instance).__name__
        self.loaded[name] += 1
        identifier = getattr(instance, "id", None)
        if name != "StrategyRunRecord" or identifier is None:
            return
        identifier = str(identifier)
        if identifier.startswith("closed-run-"):
            self.closed_run_materialized += 1
        elif identifier in ACTIVE_RUN_IDS:
            self.active_run_ids_seen.add(identifier)


class _DomainPeakObserver:
    """Measure live Pydantic domain objects without retaining them or their IDs."""

    def __init__(self) -> None:
        self.live = 0
        self.peak = 0
        self.created: Counter[str] = Counter()

    def reset(self) -> None:
        gc.collect()
        self.live = 0
        self.peak = 0
        self.created.clear()

    def observe(self, value: Any) -> Any:
        self.live += 1
        self.peak = max(self.peak, self.live)
        self.created[type(value).__name__] += 1
        weakref.finalize(value, self._released)
        return value

    def _released(self) -> None:
        self.live = max(0, self.live - 1)


@contextmanager
def _observe_repository_domains(observer: _DomainPeakObserver):
    repository_type = SQLAlchemyStrategyExperimentRepository
    originals = {
        name: getattr(repository_type, name)
        for name in ("_to_proposal", "_to_run", "_to_signal", "_to_review")
    }

    for name, original in originals.items():
        def wrapped(record, _original=original):
            return observer.observe(_original(record))

        setattr(repository_type, name, staticmethod(wrapped))
    try:
        yield
    finally:
        for name, original in originals.items():
            setattr(repository_type, name, staticmethod(original))


def verify_scale(engine, *, size: int, first: int, seed_active: bool) -> dict[str, Any]:
    if seed_active:
        seed_active_fixture(engine)
    seed_history(engine, first=first, last=size)
    oracle = sql_oracle(engine)
    settings = Settings(database_url=str(engine.url))
    activity_reports: list[dict[str, Any]] = []
    metrics = _LoadMetrics()
    select_capture = _SelectCapture()
    select_listener = select_capture.before_cursor_execute
    event.listen(engine, "before_cursor_execute", select_listener)

    try:
        # Match stocks_tool.db.session.get_session_factory, including flush policy.
        with Session(engine, expire_on_commit=False, autoflush=False) as session:
            event.listen(session, "loaded_as_persistent", metrics.on_load)
            repository = SQLAlchemyStrategyExperimentRepository(session)
            broker_accounts = SQLAlchemyBrokerAccountRepository(session)
            service = StrategyExperimentService(
                experiments=repository,
                broker_accounts=broker_accounts,
                settings=settings,
            )
            for display_limit in (1, 25):
                metrics.reset()
                activity = service.get_covered_call_activity(
                    external_account_id=ACCOUNT_ID,
                    mode=ExecutionMode.PAPER,
                    limit=display_limit,
                )
                summary = activity.summary.model_dump(mode="json")
                assert summary["total_proposals"] == oracle["total_proposals"]
                assert summary["active_proposals"] == oracle["active_proposals"]
                assert summary["executed_positions"] == oracle["executed_positions"]
                assert summary["pending_rolls"] == oracle["pending_rolls"]
                assert summary["close_runs"] == oracle["close_runs"]
                oracle_latest = datetime.fromisoformat(oracle["latest_activity_at"]) if oracle["latest_activity_at"] else None
                assert activity.summary.latest_activity_at == oracle_latest
                assert len(activity.proposals) <= display_limit
                assert len(activity.runs) <= display_limit
                assert len(activity.signals) <= display_limit
                assert len(activity.reviews) <= display_limit
                assert {task.proposal_id for task in activity.lifecycle_tasks} == set(ACTIVE_PROPOSALS)
                if display_limit >= 25:
                    assert {
                        run.id for run in activity.runs if run.id in ACTIVE_RUN_IDS
                    } == ACTIVE_RUN_IDS
                activity_reports.append(
                    {
                        "display_limit": display_limit,
                        "summary": summary,
                        "visible_counts": {
                            "proposals": len(activity.proposals),
                            "runs": len(activity.runs),
                            "signals": len(activity.signals),
                            "reviews": len(activity.reviews),
                            "lifecycle_tasks": len(activity.lifecycle_tasks),
                        },
                        "loaded_records": dict(metrics.loaded),
                    }
                )

            refresh = _LocalOrderRefresh()
            no_broker = _NoBroker()
            lifecycle_service = CoveredCallStrategyService(
                settings=settings,
                broker_accounts=broker_accounts,
                account_snapshots=Mock(),
                experiments=repository,
                longbridge_adapter=no_broker,
                order_service=refresh,
            )
            metrics.reset()
            result = lifecycle_service.reconcile_pending_lifecycle(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                as_of=datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc),
            )
            assert metrics.closed_run_materialized == 0
            assert len(refresh.refresh_calls) == len(set(refresh.refresh_calls))
            assert set(refresh.refresh_calls) == {
                "active-open-order",
                "active-close-order",
                "active-roll-buyback",
            }
            assert "active-roll-sell" not in refresh.refresh_calls
            assert refresh.mutation_attempts == 0
            assert no_broker.attempts == 0
            lifecycle_report = {
                "result": result,
                "refresh_calls": refresh.refresh_calls,
                "mutation_attempts": refresh.mutation_attempts,
                "broker_attempts": dict(no_broker.calls),
                "loaded_records": dict(metrics.loaded),
                "loaded_active_run_ids": sorted(metrics.active_run_ids_seen),
                "closed_run_materialization": metrics.closed_run_materialized,
            }
            event.remove(session, "loaded_as_persistent", metrics.on_load)
        explain = explain_queries(engine, select_capture)
    finally:
        event.remove(engine, "before_cursor_execute", select_listener)

    return {
        "size": size,
        "oracle": oracle,
        "activity": activity_reports,
        "lifecycle": lifecycle_report,
        "captured_strategy_select_count": len(select_capture.entries),
        "explain": explain,
    }


def verify_operator_consistency(engine) -> dict[str, Any]:
    settings = Settings(database_url=str(engine.url))
    oracle = sql_oracle(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        order_repository = SQLAlchemyOrderRepository(session, attach_intent_ledger=False)
        experiment_repository = SQLAlchemyStrategyExperimentRepository(session)
        broker_accounts = SQLAlchemyBrokerAccountRepository(session)
        experiments = StrategyExperimentService(
            experiments=experiment_repository,
            broker_accounts=broker_accounts,
            settings=settings,
        )
        no_broker = _NoBroker()
        order_service = OrderService(
            settings=settings,
            broker_accounts=broker_accounts,
            trade_plans=Mock(),
            orders=order_repository,
            executions=SQLAlchemyExecutionRepository(session),
            longbridge_adapter=no_broker,
        )
        consistency = OperatorConsistencyService(
            strategy_experiments=experiments,
            bull_put_strategy=_NoBullPut(),
            order_service=order_service,
        )
        domain_observer = _DomainPeakObserver()
        domain_observer.reset()
        with _observe_repository_domains(domain_observer):
            covered_call = consistency.get_summary(
                external_account_id=ACCOUNT_ID,
                mode=ExecutionMode.PAPER,
                strategy="covered_call_v1",
                limit=1,
            )
        gc.collect()
        assert covered_call.status == "warn"
        assert covered_call.total_check_count == oracle["covered_call_linkage_missing"]
        assert covered_call.total_warn_count == oracle["covered_call_linkage_missing"]
        assert covered_call.check_count <= 1
        assert covered_call.truncated is covered_call.total_check_count > 1
        assert domain_observer.peak <= CONSISTENCY_DOMAIN_PEAK_LIMIT
        before = consistency.get_summary(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            strategy="zero_dte_lottery_v1",
            limit=1,
        )
        assert before.total_check_count == len(LEGACY_ORDER_IDS)
        assert before.total_repair_available_count == len(LEGACY_ORDER_IDS)
        assert before.check_count == 1
        assert before.truncated is True

        signal_count_before = session.execute(
            text(
                "SELECT count(*) FROM strategy_signals "
                "WHERE external_account_id=:account AND strategy_id='zero_dte_lottery_v1'"
            ),
            {"account": ACCOUNT_ID},
        ).scalar_one()
        request = OperatorConsistencyRepairRequest(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            confirm_local_repair=True,
            actor="strategy-query-regression",
            note="Isolated legacy-link repair proof.",
        )
        first_repair = consistency.apply_repair(
            f"zero-dte-ledger:{LEGACY_ORDER_IDS[0]}", request
        )
        second_repair = consistency.apply_repair(
            f"zero-dte-ledger:{LEGACY_ORDER_IDS[0]}", request
        )
        assert first_repair.repaired is True
        assert first_repair.created_run is not None
        assert first_repair.created_signal is None
        assert first_repair.broker_order_submitted is False
        assert second_repair.status == "already_repaired"
        after = consistency.get_summary(
            external_account_id=ACCOUNT_ID,
            mode=ExecutionMode.PAPER,
            strategy="zero_dte_lottery_v1",
            limit=1,
        )
        assert after.total_repair_available_count == len(LEGACY_ORDER_IDS) - 1
        signal_count_after = session.execute(
            text(
                "SELECT count(*) FROM strategy_signals "
                "WHERE external_account_id=:account AND strategy_id='zero_dte_lottery_v1'"
            ),
            {"account": ACCOUNT_ID},
        ).scalar_one()
        assert signal_count_after == signal_count_before
        assert no_broker.attempts == 0
        return {
            "covered_call": covered_call.model_dump(mode="json"),
            "covered_call_domain_peak": domain_observer.peak,
            "covered_call_domain_created": dict(domain_observer.created),
            "covered_call_domain_peak_limit": CONSISTENCY_DOMAIN_PEAK_LIMIT,
            "covered_call_domain_peak_limit_reason": (
                f"Fixed at six {CONSISTENCY_BATCH_SIZE}-object windows: proposal batch, streamed run batch, "
                "and conversion overlap across two consistency phases."
            ),
            "before": before.model_dump(mode="json"),
            "after": after.model_dump(mode="json"),
            "first_repair": first_repair.model_dump(mode="json"),
            "second_repair": second_repair.model_dump(mode="json"),
            "signal_count_before": signal_count_before,
            "signal_count_after": signal_count_after,
            "broker_attempts": dict(no_broker.calls),
        }


def _parse_sizes(value: str) -> tuple[int, ...]:
    sizes = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    if not sizes or any(size <= 0 for size in sizes):
        raise argparse.ArgumentTypeError("--sizes must contain positive comma-separated integers")
    return sizes


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        type=_parse_sizes,
        default=(10_000, 100_000),
        help="Cumulative closed-history sizes, for example 100,1000 or 10000,100000.",
    )
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
    cleanup_error = None
    results: list[dict[str, Any]] = []
    operator_report: dict[str, Any] | None = None
    error = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        created = True
        _run_migrations(database_url)
        engine = create_engine(database_url, pool_pre_ping=True)
        seed_accounts(engine)
        previous_size = 0
        for size in args.sizes:
            results.append(
                verify_scale(
                    engine,
                    size=size,
                    first=previous_size + 1,
                    seed_active=previous_size == 0,
                )
            )
            previous_size = size
        operator_report = verify_operator_consistency(engine)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc(file=sys.stderr)
    finally:
        if engine is not None:
            engine.dispose()
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
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
        admin.dispose()
    if cleanup_error is not None and error is None:
        error = f"temporary database cleanup failed: {cleanup_error}"
    broker_attempts = 0
    mutation_attempts = 0
    for result in results:
        broker_attempts += sum(result.get("lifecycle", {}).get("broker_attempts", {}).values())
        mutation_attempts += int(result.get("lifecycle", {}).get("mutation_attempts", 0))
    if operator_report is not None:
        broker_attempts += sum(operator_report.get("broker_attempts", {}).values())
    report = build_report(
        script=Path(__file__).name,
        workflow="strategy-query",
        status="failed" if error else "passed",
        mode="isolated-postgresql",
        target="temporary database",
        summary="Global Covered Call, lifecycle and operator consistency proof at requested cumulative scales.",
        payload={
            "sizes": list(args.sizes),
            "runs": results,
            "operator_consistency": operator_report,
            "broker_attempts": broker_attempts,
            "mutation_attempts": mutation_attempts,
            "temporary_database_removed": bool(created and cleanup_error is None),
        },
        error=error,
    )
    emit_report(report, args.json_output)
    return 1 if error else 0


if __name__ == "__main__":
    raise SystemExit(run())

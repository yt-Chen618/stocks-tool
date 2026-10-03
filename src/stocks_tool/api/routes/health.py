from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from stocks_tool.adapters.brokers.longbridge import LongbridgeBrokerAdapter
from stocks_tool.api.dependencies import get_longbridge_adapter
from stocks_tool.core.config import get_settings
from stocks_tool.db.session import get_engine


router = APIRouter(tags=["health"])


def _expected_alembic_heads() -> list[str] | None:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        repository_root = Path(__file__).resolve().parents[4]
        config = Config(str(repository_root / "alembic.ini"))
        config.set_main_option("script_location", str(repository_root / "alembic"))
        return list(ScriptDirectory.from_config(config).get_heads())
    except Exception:
        # A missing local migration checkout should not expose a traceback from
        # a health route.  The database revision is still useful evidence.
        return None


@router.get("/health")
def healthcheck() -> dict[str, str | bool]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "execution_mode": settings.execution_mode.value,
        "live_trading_enabled": settings.allow_live_trading,
    }


@router.get("/health/live")
def liveness() -> dict[str, str | bool]:
    """Report that the process can answer requests without touching dependencies."""

    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "process": "alive",
    }


def _database_readiness() -> tuple[dict[str, Any], dict[str, Any]]:
    """Check connectivity and Alembic state using a local DB connection only."""

    try:
        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar_one_or_none()
        if not revision:
            return (
                {"status": "ok"},
                {"status": "unknown", "reason_code": "schema_revision_missing"},
            )
        expected_heads = _expected_alembic_heads()
        if expected_heads and str(revision) not in expected_heads:
            return (
                {"status": "ok"},
                {
                    "status": "outdated",
                    "revision": str(revision),
                    "expected_heads": expected_heads,
                    "reason_code": "schema_outdated",
                },
            )
        return (
            {"status": "ok"},
            {
                "status": "ok",
                "revision": str(revision),
                "expected_heads": expected_heads,
            },
        )
    except Exception:
        # Readiness is an operator-facing endpoint. Do not return a driver
        # message because it may include a URL, username, or other secret.
        return (
            {"status": "unavailable", "reason_code": "database_unavailable"},
            {"status": "unknown", "reason_code": "schema_unavailable"},
        )


def _as_utc_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _scheduler_readiness(request: Request) -> dict[str, Any]:
    settings = get_settings()
    if not settings.reconciliation_scheduler_enabled:
        return {
            "status": "disabled",
            "healthy": True,
            "enabled": False,
            "heartbeat_at": None,
        }

    scheduler = getattr(request.app.state, "reconciliation_scheduler", None)
    heartbeat_status = getattr(scheduler, "heartbeat_status", None)
    if callable(heartbeat_status):
        try:
            reported = heartbeat_status()
            if isinstance(reported, dict):
                return dict(reported)
        except Exception:
            return {
                "status": "unknown",
                "healthy": False,
                "enabled": True,
                "reason_code": "scheduler_heartbeat_unavailable",
                "heartbeat_at": None,
            }

    heartbeat_value = getattr(request.app.state, "scheduler_heartbeat_at", None)
    if heartbeat_value is None and scheduler is not None:
        heartbeat_value = getattr(scheduler, "heartbeat_at", None)
    heartbeat_at = _as_utc_datetime(heartbeat_value)
    if scheduler is None or heartbeat_at is None:
        return {
            "status": "not_running",
            "healthy": False,
            "enabled": True,
            "reason_code": "scheduler_heartbeat_missing",
            "heartbeat_at": heartbeat_at.isoformat() if heartbeat_at else None,
        }

    now = datetime.now(timezone.utc)
    max_age_seconds = max(30, settings.reconciliation_poll_interval_seconds * 3)
    age_seconds = max(0.0, (now - heartbeat_at).total_seconds())
    healthy = age_seconds <= max_age_seconds
    return {
        "status": "healthy" if healthy else "stale",
        "healthy": healthy,
        "enabled": True,
        "heartbeat_at": heartbeat_at.isoformat(),
        "age_seconds": round(age_seconds, 3),
        "max_age_seconds": max_age_seconds,
        "reason_code": None if healthy else "scheduler_heartbeat_stale",
    }


def _cached_quarantine_readiness() -> dict[str, Any]:
    """Read local quarantine state only when the adapter already exists.

    Calling the dependency factory when its LRU cache is empty would construct
    an adapter. Construction is harmless, but readiness must never make a
    broker session appear initialized, so this intentionally checks the cache
    first and reports an explicit not-initialized state.
    """

    try:
        if get_longbridge_adapter.cache_info().currsize == 0:
            return {
                "status": "not_initialized",
                "broker_session_initialized": False,
                "pending_count": None,
            }
        adapter = get_longbridge_adapter()
        if not isinstance(adapter, LongbridgeBrokerAdapter):
            return {
                "status": "unknown",
                "broker_session_initialized": False,
                "reason_code": "broker_runtime_unavailable",
                "pending_count": None,
            }
        runtime = adapter.get_market_data_runtime_status()
        pending_count = runtime.sdk_quarantine.pending_count
        return {
            "status": "blocked" if pending_count else "clear",
            "broker_session_initialized": any(
                session.context_initialized for session in runtime.sessions
            ),
            "pending_count": pending_count,
            "oldest_duration_seconds": runtime.sdk_quarantine.oldest_duration_seconds,
            "reason_code": "sdk_timeout_quarantine" if pending_count else None,
        }
    except Exception:
        return {
            "status": "unknown",
            "broker_session_initialized": False,
            "reason_code": "broker_runtime_unavailable",
            "pending_count": None,
        }


def _ready_payload(request: Request) -> dict[str, Any]:
    settings = get_settings()
    database, schema = _database_readiness()
    scheduler = _scheduler_readiness(request)
    quarantine = _cached_quarantine_readiness()

    read_only_usable = database["status"] == "ok" and schema["status"] == "ok"
    read_only_reasons = []
    if not read_only_usable:
        read_only_reasons.extend(
            code
            for code in (database.get("reason_code"), schema.get("reason_code"))
            if code
        )
    if scheduler.get("status") in {"stale", "not_running", "unknown"}:
        read_only_reasons.append(str(scheduler.get("reason_code") or "scheduler_unavailable"))

    trade_reasons: list[str] = []
    if not read_only_usable:
        trade_reasons.append("read_only_dependencies_unavailable")
    if scheduler.get("status") in {"stale", "not_running", "unknown"}:
        trade_reasons.append("scheduler_unavailable")
    if quarantine.get("pending_count"):
        trade_reasons.append("sdk_timeout_quarantine")
    if not quarantine.get("broker_session_initialized"):
        trade_reasons.append("broker_session_not_initialized")
    if settings.execution_mode.value == "live" and not settings.allow_live_trading:
        trade_reasons.append("live_trading_disabled")
    # Infrastructure readiness is not account/action authorization.  The
    # actual order path still checks account mode, current broker evidence,
    # strategy controls, intent state, and recovery posture immediately before
    # a mutation, so this global endpoint must never become a green light.
    trade_reasons.append("account_authorization_not_evaluated")

    trade_ready = False
    metrics = getattr(request.app.state, "observability_metrics", None)
    return {
        "status": "ready" if read_only_usable else "not_ready",
        "request_id": getattr(getattr(request, "state", None), "request_id", None),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "database": database,
            "schema": schema,
            "scheduler": scheduler,
            "sdk_quarantine": quarantine,
        },
        "read_only": {
            "usable": read_only_usable,
            "status": "usable" if read_only_usable else "unavailable",
            "reason_codes": sorted(set(read_only_reasons)),
        },
        "trade_readiness": {
            "ready": trade_ready,
            "status": "requires_account_authorization",
            "reason_codes": sorted(set(trade_reasons)),
            "broker_session_initialized": bool(
                quarantine.get("broker_session_initialized")
            ),
            "execution_mode": settings.execution_mode.value,
        },
        "execution_controls": {
            "paper_first": settings.execution_mode.value == "paper",
            "live_trading_enabled": settings.allow_live_trading,
            "bull_put_entry_kill_switch_active": settings.bull_put_strategy.entry_kill_switch_active,
            "zero_dte_auto_execute_enabled": settings.zero_dte_lottery_strategy.auto_execute_enabled,
            "zero_dte_execution_locked": not settings.zero_dte_lottery_strategy.auto_execute_enabled,
        },
        "observability": {
            "latency": metrics.snapshot() if metrics is not None else None,
        },
    }


@router.get("/health/ready")
def readiness(request: Request) -> JSONResponse:
    payload = _ready_payload(request)
    return JSONResponse(
        status_code=200 if payload["read_only"]["usable"] else 503,
        content=payload,
    )

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from stocks_tool.adapters.brokers.longbridge import LongbridgeDependencyError
from stocks_tool.api.routes import (
    account_snapshots,
    backtests,
    broker_accounts,
    brokers,
    executions,
    health,
    journals,
    market_events,
    market_session_comparisons,
    ops,
    orders,
    plans,
    portfolio,
    research,
    research_records,
    strategies,
    ui,
    watchlists,
)
from stocks_tool.core.config import get_settings
from stocks_tool.core.observability import (
    ObservabilityMiddleware,
    RollingLatencyMetrics,
    redact_text,
    sanitize_http_detail,
    stable_error_code,
)
from stocks_tool.db.session import get_session_factory
from stocks_tool.api.dependencies import get_longbridge_adapter
from stocks_tool.application.services.reconciliation import (
    ReconciliationCoordinator,
    ReconciliationScheduler,
)
from stocks_tool.application.services.backtesting import BacktestDispatcher
from stocks_tool.adapters.backtesting.engine_lock import LEAN_ENGINE_IMAGE_DIGEST, LEAN_ENGINE_VERSION


logger = logging.getLogger(__name__)

_DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 10.0


async def _await_shutdown_task(
    task: asyncio.Task | None,
    *,
    label: str,
    timeout_seconds: float,
) -> bool:
    """Wait for a task without cancelling an in-flight broker call.

    The reconciliation worker may be waiting on a synchronous SDK mutation.
    Cancelling the asyncio wrapper cannot cancel that call, and calling it a
    failed mutation would invite an unsafe retry.  A timeout therefore leaves
    the outcome unknown and returns control to application shutdown.
    """

    if task is None:
        return True
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=max(0.1, timeout_seconds))
    except asyncio.TimeoutError:
        logger.error(
            "%s did not stop before the bounded shutdown deadline; any in-flight broker "
            "mutation remains UNKNOWN and must be reconciled before retrying.",
            label,
        )
        return False
    except asyncio.CancelledError:
        raise
    except Exception as error:
        # The scheduler itself records task failures.  Shutdown must not turn a
        # timed-out/unknown broker mutation into a new retryable failure record.
        logger.error(
            "%s stopped with an unexpected local task error code=%s detail=%s",
            label,
            stable_error_code(error),
            redact_text(error),
        )
        return False
    return True


async def _prewarm_longbridge_market_data(settings) -> None:
    adapter = get_longbridge_adapter()
    symbols = [
        symbol.strip()
        for symbol in settings.longbridge_market_data_prewarm_symbols.split(",")
        if symbol.strip()
    ]
    try:
        if settings.longbridge_market_data_prewarm_delay_seconds:
            await asyncio.sleep(settings.longbridge_market_data_prewarm_delay_seconds)
        await asyncio.to_thread(
            adapter.prewarm_market_data,
            mode=settings.execution_mode,
            symbols=symbols,
        )
    except Exception as error:
        logger.warning(
            "Longbridge market-data prewarm failed; startup remains available "
            "code=%s detail=%s",
            stable_error_code(error),
            redact_text(error),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = None
    scheduler_task = None
    backtest_dispatcher = None
    backtest_dispatcher_task = None
    prewarm_task = None
    shutdown_timeout_seconds = float(
        getattr(settings, "shutdown_timeout_seconds", _DEFAULT_SHUTDOWN_TIMEOUT_SECONDS)
    )
    app.state.scheduler_started_at = None
    app.state.scheduler_heartbeat_at = None
    app.state.scheduler_shutdown = {"status": "not_started"}
    app.state.backtest_dispatcher_shutdown = {"status": "not_started"}
    app.state.longbridge_market_data_prewarm_shutdown = {"status": "not_started"}

    if settings.longbridge_market_data_prewarm_enabled:
        configuration = get_longbridge_adapter().get_configuration_status()
        token_ready = (
            configuration.paper_token_configured
            if settings.execution_mode.value == "paper"
            else configuration.live_token_configured
        )
        if configuration.app_key_configured and configuration.app_secret_configured and token_ready:
            prewarm_task = asyncio.create_task(_prewarm_longbridge_market_data(settings))

    if (
        settings.reconciliation_scheduler_enabled
        and not getattr(app.state, "disable_reconciliation_scheduler", False)
    ):
        try:
            scheduler = ReconciliationScheduler(
                coordinator=ReconciliationCoordinator(
                    settings=settings,
                    session_factory=get_session_factory(),
                    longbridge_adapter=get_longbridge_adapter(),
                ),
                poll_interval_seconds=settings.reconciliation_poll_interval_seconds,
            )
            scheduler_task = asyncio.create_task(scheduler.run())
            app.state.scheduler_started_at = datetime.now(timezone.utc)
            app.state.scheduler_shutdown = {
                "status": "running",
                "started_at": app.state.scheduler_started_at.isoformat(),
            }
        except LongbridgeDependencyError:
            scheduler = None
            scheduler_task = None
            app.state.scheduler_shutdown = {"status": "dependency_unavailable"}

    app.state.reconciliation_scheduler = scheduler
    app.state.reconciliation_scheduler_task = scheduler_task
    app.state.longbridge_market_data_prewarm_task = prewarm_task

    if (
        settings.backtest_dispatcher_enabled
        and not getattr(app.state, "disable_backtest_dispatcher", False)
    ):
        try:
            backtest_dispatcher = BacktestDispatcher(
                session_factory=get_session_factory(),
                allowed_data_root=settings.backtest_data_root,
                result_root=settings.backtest_result_root,
                engine_image_digest=settings.lean_image_digest or LEAN_ENGINE_IMAGE_DIGEST,
                engine_version=LEAN_ENGINE_VERSION,
                poll_interval_seconds=settings.backtest_dispatcher_poll_interval_seconds,
                lease_ttl_seconds=settings.backtest_dispatcher_lease_ttl_seconds,
            )
            backtest_dispatcher_task = asyncio.create_task(backtest_dispatcher.run())
            app.state.backtest_dispatcher_shutdown = {"status": "running"}
        except Exception as error:
            logger.warning("Backtest dispatcher unavailable at startup code=%s", type(error).__name__)
            backtest_dispatcher = None
            backtest_dispatcher_task = None
            app.state.backtest_dispatcher_shutdown = {"status": "dependency_unavailable"}

    try:
        yield
    finally:
        if backtest_dispatcher is not None and backtest_dispatcher_task is not None:
            await backtest_dispatcher.stop()
            stopped = await _await_shutdown_task(
                backtest_dispatcher_task,
                label="backtest dispatcher",
                timeout_seconds=shutdown_timeout_seconds,
            )
            app.state.backtest_dispatcher_shutdown = {
                "status": "stopped" if stopped else "timed_out_unknown",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        if scheduler is not None and scheduler_task is not None:
            await scheduler.stop()
            stopped = await _await_shutdown_task(
                scheduler_task,
                label="reconciliation scheduler",
                timeout_seconds=shutdown_timeout_seconds,
            )
            app.state.scheduler_shutdown = {
                "status": "stopped" if stopped else "timed_out_unknown",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        if prewarm_task is not None:
            stopped = await _await_shutdown_task(
                prewarm_task,
                label="Longbridge market-data prewarm",
                timeout_seconds=shutdown_timeout_seconds,
            )
            app.state.longbridge_market_data_prewarm_shutdown = {
                "status": "stopped" if stopped else "timed_out_unknown",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        scheduler_pending = scheduler_task is not None and not scheduler_task.done()
        prewarm_pending = prewarm_task is not None and not prewarm_task.done()
        if get_longbridge_adapter.cache_info().currsize and not (scheduler_pending or prewarm_pending):
            get_longbridge_adapter().close()
            get_longbridge_adapter.cache_clear()
        elif scheduler_pending or prewarm_pending:
            logger.warning(
                "Leaving Longbridge adapter resources open because a timed-out task may "
                "still be using them; broker mutation outcome remains UNKNOWN."
            )


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.observability_metrics = RollingLatencyMetrics()
    app.add_middleware(ObservabilityMiddleware)

    @app.exception_handler(HTTPException)
    async def _safe_http_exception_handler(request: Request, error: HTTPException) -> JSONResponse:
        # Preserve all existing ``detail`` shapes (including structured
        # idempotency errors), while removing credential-like substrings and
        # relying on the middleware response header for correlation.
        return JSONResponse(
            status_code=error.status_code,
            headers=error.headers,
            content={
                "detail": sanitize_http_detail(error.detail),
            },
        )

    static_dir = Path(__file__).parent / "ui" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(ui.router)
    app.include_router(health.router)
    app.include_router(research.router)
    app.include_router(plans.router)
    app.include_router(strategies.router)
    app.include_router(market_events.router)
    app.include_router(market_session_comparisons.router)
    app.include_router(ops.router)
    app.include_router(watchlists.router)
    app.include_router(broker_accounts.router)
    app.include_router(account_snapshots.router)
    app.include_router(brokers.router)
    app.include_router(executions.router)
    app.include_router(journals.router)
    app.include_router(orders.router)
    app.include_router(research_records.router)
    app.include_router(portfolio.router)
    app.include_router(backtests.router)
    return app


app = create_app()

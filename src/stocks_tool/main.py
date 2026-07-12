import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from stocks_tool.adapters.brokers.longbridge import LongbridgeDependencyError
from stocks_tool.api.routes import (
    account_snapshots,
    broker_accounts,
    brokers,
    executions,
    health,
    journals,
    market_events,
    ops,
    orders,
    plans,
    research,
    strategies,
    ui,
    watchlists,
)
from stocks_tool.core.config import get_settings
from stocks_tool.db.session import get_session_factory
from stocks_tool.api.dependencies import get_longbridge_adapter
from stocks_tool.application.services.reconciliation import (
    ReconciliationCoordinator,
    ReconciliationScheduler,
)


logger = logging.getLogger(__name__)


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
    except Exception:
        logger.warning("Longbridge market-data prewarm failed; startup remains available.", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    scheduler = None
    scheduler_task = None
    prewarm_task = None

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
        except LongbridgeDependencyError:
            scheduler = None
            scheduler_task = None

    app.state.reconciliation_scheduler = scheduler
    app.state.reconciliation_scheduler_task = scheduler_task
    app.state.longbridge_market_data_prewarm_task = prewarm_task

    try:
        yield
    finally:
        if scheduler is not None and scheduler_task is not None:
            await scheduler.stop()
            await scheduler_task
        if prewarm_task is not None:
            await prewarm_task
        if get_longbridge_adapter.cache_info().currsize:
            get_longbridge_adapter().close()
            get_longbridge_adapter.cache_clear()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    static_dir = Path(__file__).parent / "ui" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(ui.router)
    app.include_router(health.router)
    app.include_router(research.router)
    app.include_router(plans.router)
    app.include_router(strategies.router)
    app.include_router(market_events.router)
    app.include_router(ops.router)
    app.include_router(watchlists.router)
    app.include_router(broker_accounts.router)
    app.include_router(account_snapshots.router)
    app.include_router(brokers.router)
    app.include_router(executions.router)
    app.include_router(journals.router)
    app.include_router(orders.router)
    return app


app = create_app()

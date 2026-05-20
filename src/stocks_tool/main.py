from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from stocks_tool.api.routes import (
    account_snapshots,
    broker_accounts,
    brokers,
    health,
    orders,
    plans,
    research,
    ui,
    watchlists,
)
from stocks_tool.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    static_dir = Path(__file__).parent / "ui" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(ui.router)
    app.include_router(health.router)
    app.include_router(research.router)
    app.include_router(plans.router)
    app.include_router(watchlists.router)
    app.include_router(broker_accounts.router)
    app.include_router(account_snapshots.router)
    app.include_router(brokers.router)
    app.include_router(orders.router)
    return app


app = create_app()

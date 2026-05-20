from fastapi import FastAPI

from stocks_tool.api.routes import brokers, health, plans, research
from stocks_tool.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.include_router(health.router)
    app.include_router(research.router)
    app.include_router(plans.router)
    app.include_router(brokers.router)
    return app


app = create_app()


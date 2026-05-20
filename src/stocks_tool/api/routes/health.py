from fastapi import APIRouter

from stocks_tool.core.config import get_settings

router = APIRouter(tags=["health"])


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


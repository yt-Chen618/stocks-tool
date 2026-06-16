from fastapi import APIRouter

from stocks_tool.api.routes.strategy_routes import (
    advisor,
    bull_put,
    covered_call,
    experiment,
    pre_open,
    zero_dte,
)

router = APIRouter(prefix="/strategies", tags=["strategies"])

router.include_router(zero_dte.router)
router.include_router(covered_call.router)
router.include_router(experiment.router)
router.include_router(advisor.router)
router.include_router(pre_open.router)
router.include_router(bull_put.router)

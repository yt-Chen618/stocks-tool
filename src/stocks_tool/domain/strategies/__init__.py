"""Pure strategy rules shared by the paper preview and offline research paths.

The modules in this package deliberately know nothing about FastAPI, SQLAlchemy,
Longbridge, or the LEAN runtime.  Application services adapt broker/domain
models to these small functions; backtesting adapters use the same functions
for fixture events.  Keeping the acceptance gates here prevents the preview
and historical paths from quietly drifting apart.
"""

from stocks_tool.domain.strategies.common import (
    MARKET_TIMEZONE,
    days_to_expiration,
    is_option_quote_fresh,
    is_timestamp_fresh,
    is_tradeable_long_leg,
    moving_average,
    option_quote_liquidity_reasons,
    passes_top_of_book,
    select_nearest_expiration,
)
from stocks_tool.domain.strategies.bull_put import (
    BullPutRules,
    BullPutSelection,
    bull_put_cap_reasons,
    bull_put_exit_reason,
    bull_put_trend_reasons,
    select_bull_put_candidate,
    width_for_underlying_price,
)
from stocks_tool.domain.strategies.covered_call import (
    CoveredCallRules,
    CoveredCallSelection,
    is_covered_call_quote_candidate,
    select_covered_call_candidate,
)
from stocks_tool.domain.strategies.zero_dte import (
    ZeroDteRules,
    ZeroDteSelection,
    select_zero_dte_candidate,
)
from stocks_tool.domain.strategies.lifecycle import (
    LifecycleSettlement,
    apply_split,
    dividend_cash,
    settle_option_position,
)

__all__ = [
    "MARKET_TIMEZONE",
    "BullPutRules",
    "BullPutSelection",
    "bull_put_cap_reasons",
    "bull_put_exit_reason",
    "CoveredCallRules",
    "CoveredCallSelection",
    "is_covered_call_quote_candidate",
    "ZeroDteRules",
    "ZeroDteSelection",
    "LifecycleSettlement",
    "apply_split",
    "bull_put_trend_reasons",
    "days_to_expiration",
    "is_option_quote_fresh",
    "is_timestamp_fresh",
    "is_tradeable_long_leg",
    "moving_average",
    "option_quote_liquidity_reasons",
    "passes_top_of_book",
    "select_bull_put_candidate",
    "select_covered_call_candidate",
    "select_nearest_expiration",
    "select_zero_dte_candidate",
    "settle_option_position",
    "dividend_cash",
    "width_for_underlying_price",
]

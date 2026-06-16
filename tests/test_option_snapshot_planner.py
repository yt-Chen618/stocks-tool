from decimal import Decimal

import pytest

from stocks_tool.application.services.option_snapshot_planner import chunked, ranked_otm_call_symbols
from stocks_tool.domain.models import OptionChainEntry


def test_ranked_otm_call_symbols_filters_sorts_and_limits_candidates() -> None:
    symbols = ranked_otm_call_symbols(
        chain=[
            OptionChainEntry(strike=Decimal("98"), call_symbol="ITM.US"),
            OptionChainEntry(strike=Decimal("102"), call_symbol="C102.US"),
            OptionChainEntry(strike=Decimal("104"), call_symbol="C104.US"),
            OptionChainEntry(strike=Decimal("106"), call_symbol="C106.US"),
            OptionChainEntry(strike=Decimal("110"), call_symbol="C110.US", standard=False),
            OptionChainEntry(strike=Decimal("112"), call_symbol="C112.US"),
        ],
        underlying_price=Decimal("100"),
        min_otm_pct=Decimal("0.02"),
        max_otm_pct=Decimal("0.12"),
        limit=3,
    )

    assert symbols == ["C102.US", "C104.US", "C106.US"]


def test_chunked_splits_symbols_into_fixed_size_batches() -> None:
    assert chunked(["A", "B", "C", "D", "E"], batch_size=2) == [["A", "B"], ["C", "D"], ["E"]]


def test_chunked_rejects_non_positive_batch_size() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        chunked(["A"], batch_size=0)

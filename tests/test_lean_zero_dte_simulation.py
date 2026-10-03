from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _run_probe(tmp_path: Path, body: str) -> str:
    """Load the canonical LEAN module with a small AlgorithmImports stub."""

    stub_root = tmp_path / "stubs"
    stub_root.mkdir()
    (stub_root / "AlgorithmImports.py").write_text(
        """
class QCAlgorithm:
    def on_order_event(self, _event):
        return None
class PythonData: pass
class FeeModel: pass
class SlippageModel: pass
class ImmediateFillModel: pass
class _Namespace:
    Utc = object()
    Daily = object()
    Minute = object()
    LocalFile = object()
    Csv = object()
    OPTION = object()
TimeZones = Resolution = SubscriptionTransportMedium = FileFormat = SecurityType = _Namespace()
class OrderStatus:
    FILLED = "filled"
    CANCELED = "canceled"
    INVALID = "invalid"
class OrderDirection:
    BUY = "buy"
    SELL = "sell"
""",
        encoding="utf-8",
    )
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stocks_tool"
        / "adapters"
        / "backtesting"
        / "lean_algorithms"
        / "algorithms.py"
    )
    probe = stub_root / "probe.py"
    probe.write_text(
        f"""
import importlib.util
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

source = sys.argv[1]
spec = importlib.util.spec_from_file_location("canonical_lean_algorithms", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

{body}
""",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join([str(stub_root), str(source.parents[4])])
    result = subprocess.run(
        [sys.executable, str(probe), str(source)],
        cwd=stub_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_zero_dte_entry_and_partial_exit_keep_real_position_state(tmp_path: Path) -> None:
    output = _run_probe(
        tmp_path,
        """
algorithm = object.__new__(module.StocksToolZeroDteResearchAlgorithm)
algorithm._active_positions = {}
algorithm._partial_positions = {}
algorithm._entered_symbols = set()
algorithm._blocked_symbols = set()
algorithm._entry_cutoff_cancel_requested = set()
algorithm._exit_requested = set()
algorithm._late_entry_fill_events = 0
algorithm._pending_groups = {}
algorithm._pending_orders = {101: ("zero_dte_entry-000001", "option_entry")}

entry = {
    "id": "zero_dte_entry-000001",
    "kind": "zero_dte_entry",
    "symbol": "QQQ",
    "metadata": {
        "option_symbol": "QQQ 0DTE C 400",
        "strike": Decimal("400"),
        "right": "call",
        "expiration": date(2024, 1, 2),
        "contracts": 2,
        "entry_premium_at_ask": Decimal("120.00"),
        "entry_price": Decimal("0.60"),
        "status": "entry_pending",
    },
    "legs": {
        "option_entry": {
            "order_id": 101,
            "target_quantity": 2,
            "filled_quantity": Decimal("2"),
            "status": module.OrderStatus.FILLED,
        }
    },
    "state": "filled",
}
module.StocksToolZeroDteResearchAlgorithm._on_zero_dte_entry_group(algorithm, entry)
assert algorithm._active_positions["QQQ"]["status"] == "open"
assert algorithm._active_positions["QQQ"]["contracts"] == 2
assert algorithm._pending_groups == {}

algorithm._pending_groups = {"zero_dte_exit-000002": {"symbol": "QQQ"}}
algorithm._pending_orders = {202: ("zero_dte_exit-000002", "option_exit")}
exit_group = {
    "id": "zero_dte_exit-000002",
    "kind": "zero_dte_exit",
    "symbol": "QQQ",
    "metadata": {"position": algorithm._active_positions["QQQ"], "reason": "market_cutoff", "quantity": 2},
    "legs": {
        "option_exit": {
            "order_id": 202,
            "target_quantity": 2,
            "filled_quantity": Decimal("1"),
            "status": module.OrderStatus.CANCELED,
        }
    },
    "state": "partial_terminal",
}
module.StocksToolZeroDteResearchAlgorithm._on_zero_dte_exit_group(algorithm, exit_group)
assert algorithm._active_positions["QQQ"]["contracts"] == 1
assert algorithm._active_positions["QQQ"]["status"] == "partial_exit_manual_action"
assert "QQQ" in algorithm._blocked_symbols
print("ok")
""",
    )
    assert output == "ok"


def test_zero_dte_cutoff_and_shared_premium_rules_are_explicit(tmp_path: Path) -> None:
    output = _run_probe(
        tmp_path,
        """
algorithm = object.__new__(module.StocksToolZeroDteResearchAlgorithm)
algorithm._lifecycle = {"market_cutoff": "15:45 America/New_York"}
algorithm._params = {
    "max_premium_per_trade": "125",
    "contracts_per_trade": "2",
    "delta_target": "0.24",
}
algorithm.get_parameter = lambda _name: None
algorithm._now = lambda: datetime(2024, 1, 2, 20, 46, tzinfo=timezone.utc)
rules = module.StocksToolZeroDteResearchAlgorithm._zero_dte_rules(algorithm)
assert rules.max_premium_per_trade == Decimal("125")
assert rules.contracts_per_trade == 2
assert rules.delta_target == Decimal("0.24")
assert module.StocksToolZeroDteResearchAlgorithm._market_cutoff_text(algorithm) == "15:45:00 America/New_York"
assert module.StocksToolZeroDteResearchAlgorithm._cutoff_reached(algorithm)
assert not module.StocksToolZeroDteResearchAlgorithm._cutoff_reached(
    algorithm,
    {"expiration": date(2024, 1, 3)},
)
assert module.StocksToolZeroDteResearchAlgorithm._cutoff_reached(
    algorithm,
    {"expiration": date(2024, 1, 1)},
)

class EarlyCloseHours:
    def get_next_market_close(self, _local_time, _extended):
        return datetime(2024, 1, 2, 13, 0)

class EarlyCloseExchange:
    hours = EarlyCloseHours()

early_security = SimpleNamespace(exchange=EarlyCloseExchange(), local_time=datetime(2024, 1, 2, 12, 59))
algorithm._now = lambda: datetime(2024, 1, 2, 18, 1, tzinfo=timezone.utc)
assert module.StocksToolZeroDteResearchAlgorithm._cutoff_reached(
    algorithm,
    {"expiration": date(2024, 1, 2)},
    security=early_security,
)
print("ok")
""",
    )
    assert output == "ok"


def test_zero_dte_on_data_submits_simulated_entry_then_cutoff_exit(tmp_path: Path) -> None:
    output = _run_probe(
        tmp_path,
        """
algorithm = object.__new__(module.StocksToolZeroDteResearchAlgorithm)
algorithm._params = {
    "max_premium_per_trade": "125",
    "contracts_per_trade": "2",
    "max_trades_per_day": "1",
    "min_direction_change_pct": "0.30",
}
algorithm.get_parameter = lambda _name: None
algorithm._lifecycle = {"market_cutoff": "16:00 America/New_York"}
algorithm._equities = {"QQQ": "QQQ-EQUITY"}
algorithm._options = {"QQQ": SimpleNamespace(symbol="QQQ-OPTION-CHAIN")}
algorithm.securities = {
    "QQQ-EQUITY": SimpleNamespace(has_data=True, price=Decimal("101")),
}
algorithm.time = datetime(2024, 1, 2, 10, 0)
algorithm._now = lambda: datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
algorithm._previous_daily_close = {"QQQ": Decimal("100")}
algorithm._last_daily_close = {"QQQ": Decimal("100")}
algorithm._last_observed_date = {"QQQ": date(2024, 1, 2)}
algorithm._entry_date = None
algorithm._entries_today = 0
algorithm._entered_symbols = set()
algorithm._active_positions = {}
algorithm._partial_positions = {}
algorithm._exit_requested = set()
algorithm._entry_cutoff_cancel_requested = set()
algorithm._late_entry_fill_events = 0
algorithm._blocked_symbols = set()
algorithm._pending_groups = {}
algorithm._quality = {
    "daily_bars_seen": 0,
    "valid_candidate_checks": 0,
    "option_quotes_seen": 0,
    "missing_greeks": 0,
}
submitted = []
algorithm._read_chain = lambda _data, _option: [{
    "symbol": "QQQ240102C101",
    "expiration_date": date(2024, 1, 2),
    "strike": Decimal("101"),
    "right": "call",
    "delta": Decimal("0.22"),
    "open_interest": 200,
    "volume": 20,
    "bid": Decimal("0.50"),
    "ask": Decimal("0.60"),
    "timestamp": datetime(2024, 1, 2, 14, 59, tzinfo=timezone.utc),
    "contract_multiplier": Decimal("100"),
    "contract": SimpleNamespace(symbol="QQQ240102C101"),
}]
algorithm._new_order_group = lambda **kwargs: submitted.append(kwargs) or f"group-{len(submitted)}"
module.StocksToolZeroDteResearchAlgorithm.on_data(algorithm, SimpleNamespace())
assert submitted[0]["kind"] == "zero_dte_entry"
assert submitted[0]["legs"][0]["quantity"] == 2
assert submitted[0]["metadata"]["max_loss"] == Decimal("120.00")
assert "premium_cap=125" in submitted[0]["legs"][0]["tag"]

algorithm._active_positions["QQQ"] = {
    **submitted[0]["metadata"],
    "status": "open",
}
algorithm._entered_symbols = {"QQQ"}
algorithm._now = lambda: datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc)
module.StocksToolZeroDteResearchAlgorithm._manage_zero_dte_positions(algorithm)
assert submitted[1]["kind"] == "zero_dte_exit"
assert submitted[1]["legs"][0]["quantity"] == -2
assert submitted[1]["metadata"]["reason"] == "market_cutoff"
print("ok")
""",
    )
    assert output == "ok"


def test_zero_dte_warmup_never_orders_and_first_live_day_uses_completed_close(tmp_path: Path) -> None:
    output = _run_probe(
        tmp_path,
        """
algorithm = object.__new__(module.StocksToolZeroDteResearchAlgorithm)
algorithm._params = {
    "max_premium_per_trade": "125",
    "contracts_per_trade": "1",
    "max_trades_per_day": "1",
    "min_direction_change_pct": "0.30",
}
algorithm.get_parameter = lambda _name: None
algorithm._lifecycle = {"market_cutoff": "16:00 America/New_York"}
algorithm._equities = {"QQQ": "QQQ-EQUITY"}
algorithm._options = {"QQQ": SimpleNamespace(symbol="QQQ-OPTION-CHAIN")}
algorithm.securities = {"QQQ-EQUITY": SimpleNamespace(has_data=True, price=Decimal("101"))}
algorithm.time = datetime(2024, 1, 2, 10, 0)
algorithm._now = lambda: datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc)
algorithm._last_daily_close = {"QQQ": None}
algorithm._previous_daily_close = {"QQQ": None}
algorithm._last_daily_bar_date = {"QQQ": None}
algorithm._last_observed_date = {"QQQ": None}
algorithm._entry_date = None
algorithm._entries_today = 0
algorithm._entered_symbols = set()
algorithm._active_positions = {}
algorithm._partial_positions = {}
algorithm._exit_requested = set()
algorithm._entry_cutoff_cancel_requested = set()
algorithm._blocked_symbols = set()
algorithm._pending_groups = {}
algorithm._quality = {
    "daily_bars_seen": 0,
    "valid_candidate_checks": 0,
    "option_quotes_seen": 0,
    "missing_greeks": 0,
}
submitted = []
algorithm._new_order_group = lambda **kwargs: submitted.append(kwargs) or f"group-{len(submitted)}"

# The warmup slice is allowed to update daily state, but never reaches chain
# selection or the order-group path.
algorithm.is_warming_up = True
algorithm._read_chain = lambda *_args: (_ for _ in ()).throw(AssertionError("warmup read chain"))
module.StocksToolZeroDteResearchAlgorithm.on_data(algorithm, SimpleNamespace())
assert submitted == []

class Bar:
    def __init__(self, close, end_time):
        self.close = close
        self.end_time = end_time

module.StocksToolZeroDteResearchAlgorithm._on_zero_dte_daily_bar(
    algorithm, "QQQ", Bar(100, datetime(2024, 1, 1, 16, 0))
)
module.StocksToolZeroDteResearchAlgorithm._on_zero_dte_daily_bar(
    algorithm, "QQQ", Bar(101, datetime(2024, 1, 2, 16, 0))
)
assert algorithm._previous_daily_close["QQQ"] == Decimal("100")

algorithm.is_warming_up = False
algorithm._read_chain = lambda _data, _option: [{
    "expiration_date": date(2024, 1, 2),
    "strike": Decimal("101"),
    "right": "call",
    "delta": Decimal("0.22"),
    "open_interest": 200,
    "volume": 20,
    "bid": Decimal("0.50"),
    "ask": Decimal("0.60"),
    "timestamp": datetime(2024, 1, 2, 14, 59, tzinfo=timezone.utc),
    "contract_multiplier": Decimal("100"),
    "contract": SimpleNamespace(symbol="QQQ240102C101"),
}]
module.StocksToolZeroDteResearchAlgorithm.on_data(algorithm, SimpleNamespace())
assert submitted and submitted[0]["kind"] == "zero_dte_entry"
print("ok")
""",
    )
    assert output == "ok"


def test_zero_dte_partial_entry_is_canceled_at_cutoff_and_late_fill_cannot_activate(tmp_path: Path) -> None:
    output = _run_probe(
        tmp_path,
        """
algorithm = object.__new__(module.StocksToolZeroDteResearchAlgorithm)
algorithm._lifecycle = {"market_cutoff": "16:00 America/New_York"}
algorithm._params = {}
algorithm.get_parameter = lambda _name: None
algorithm._now = lambda: datetime(2024, 1, 2, 21, 0, tzinfo=timezone.utc)
algorithm._equities = {"QQQ": "QQQ-EQUITY"}
algorithm.securities = {"QQQ-EQUITY": SimpleNamespace()}
algorithm._active_positions = {}
algorithm._partial_positions = {}
algorithm._entered_symbols = set()
algorithm._blocked_symbols = set()
algorithm._entry_cutoff_cancel_requested = set()
algorithm._exit_requested = set()
algorithm._late_entry_fill_events = 0
algorithm._order_events = []
algorithm._pending_groups = {
    "zero_dte_entry-000001": {
        "id": "zero_dte_entry-000001",
        "kind": "zero_dte_entry",
        "symbol": "QQQ",
        "metadata": {
            "option_symbol": "QQQ 0DTE C 400",
            "expiration": date(2024, 1, 2),
            "contracts": 2,
            "entry_premium_at_ask": Decimal("120"),
            "entry_price": Decimal("0.60"),
        },
        "legs": {
            "option_entry": {
                "order_id": 77,
                "target_quantity": 2,
                "filled_quantity": Decimal("1"),
                "status": "partially_filled",
            }
        },
        "state": "partial",
    }
}
algorithm._pending_orders = {77: ("zero_dte_entry-000001", "option_entry")}
class Transactions:
    def __init__(self):
        self.calls = []
    def get_order_ticket(self, _order_id):
        return None
    def cancel_order(self, order_id, tag):
        self.calls.append((order_id, tag))
transactions = Transactions()
algorithm.transactions = transactions
submitted = []
algorithm._new_order_group = lambda **kwargs: submitted.append(kwargs) or f"group-{len(submitted)}"
module.StocksToolZeroDteResearchAlgorithm._manage_zero_dte_positions(algorithm)
assert transactions.calls and transactions.calls[0][0] == 77
assert algorithm._active_positions == {}
assert "QQQ" in algorithm._entry_cutoff_cancel_requested

# A final fill racing with the cancel is retained for accounting but cannot
# transition the pending entry into an active strategy position.
module.StocksToolZeroDteResearchAlgorithm.on_order_event(
    algorithm,
    SimpleNamespace(order_id=77, status="filled", fill_quantity=1, symbol="QQQ 0DTE C 400", message=""),
)
assert algorithm._active_positions == {}
assert algorithm._pending_groups["zero_dte_entry-000001"]["legs"]["option_entry"]["filled_quantity"] == 2
assert algorithm._late_entry_fill_events == 1

group = algorithm._pending_groups["zero_dte_entry-000001"]
group["state"] = "partial_terminal"
group["legs"]["option_entry"]["status"] = module.OrderStatus.CANCELED
module.StocksToolZeroDteResearchAlgorithm._on_zero_dte_entry_group(algorithm, group)
assert algorithm._active_positions == {}
assert algorithm._partial_positions["QQQ"]["contracts"] == 2
assert algorithm._partial_positions["QQQ"]["status"] == "cutoff_partial"
assert submitted[0]["kind"] == "zero_dte_exit"
assert submitted[0]["legs"][0]["quantity"] == -2
print("ok")
""",
    )
    assert output == "ok"


def test_zero_dte_lifecycle_event_settles_active_position(tmp_path: Path) -> None:
    output = _run_probe(
        tmp_path,
        """
algorithm = object.__new__(module.StocksToolZeroDteResearchAlgorithm)
algorithm._active_positions = {
    "QQQ": {"option_symbol": "QQQ 0DTE C 400", "contracts": 1, "status": "open"}
}
algorithm._partial_positions = {}
algorithm._entered_symbols = {"QQQ"}
algorithm._exit_requested = {"QQQ"}
algorithm._order_events = []
algorithm._lifecycle_events = []
algorithm._assignment_events = []
algorithm._exercise_events = []
algorithm._late_entry_fill_events = 0
module.StocksToolZeroDteResearchAlgorithm.on_order_event(
    algorithm,
    SimpleNamespace(
        order_id=99,
        symbol="QQQ 0DTE C 400",
        status="submitted",
        fill_quantity=0,
        is_assignment=False,
        message="Option assignment notification",
    ),
)
assert "QQQ" in algorithm._active_positions
module.StocksToolZeroDteResearchAlgorithm.on_assignment_order_event(
    algorithm,
    SimpleNamespace(
        symbol="QQQ 0DTE C 400",
        status="filled",
        fill_quantity=-1,
        is_assignment=True,
        message="Option assignment",
    ),
)
assert algorithm._active_positions == {}
assert algorithm._entered_symbols == set()
assert algorithm._exit_requested == set()
assert len(algorithm._assignment_events) >= 1
print("ok")
""",
    )
    assert output == "ok"


def test_chain_reader_uses_real_quote_bar_instead_of_refreshed_contract_time(tmp_path: Path) -> None:
    output = _run_probe(
        tmp_path,
        """
algorithm = object.__new__(module._StrategyAlgorithm)
algorithm._quality = {"option_quotes_seen": 0, "missing_greeks": 0}
algorithm.time = datetime(2024, 1, 2, 10, 0)
algorithm._contract_payload = lambda contract, _now: {"contract": contract, "delta": Decimal("0")}
option_security = SimpleNamespace(symbol="OPTION-CHAIN")
class Chain(list):
    pass
chain = Chain([SimpleNamespace(symbol=name, time=algorithm.time) for name in ("copied", "real", "missing")])
chain.quote_bars = {
    "copied": SimpleNamespace(is_fill_forward=True, end_time=algorithm.time),
    "real": SimpleNamespace(is_fill_forward=False, end_time=datetime(2024, 1, 2, 9, 59)),
}
data = SimpleNamespace(option_chains={"OPTION-CHAIN": chain})
quotes = module._StrategyAlgorithm._read_chain(algorithm, data, option_security)
assert len(quotes) == 1
assert quotes[0]["contract"].symbol == "real"
assert quotes[0]["timestamp"] == datetime(2024, 1, 2, 14, 59, tzinfo=timezone.utc)
assert algorithm._quality["option_quotes_seen"] == 1
assert module._StrategyAlgorithm._is_fill_forward_data(SimpleNamespace(is_fill_forward=True))
assert not module._StrategyAlgorithm._is_fill_forward_data(SimpleNamespace(IsFillForward=False))
print("ok")
""",
    )
    assert output == "ok"

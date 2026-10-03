from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_first_leg_immediate_fill_cannot_activate_before_second_leg_is_submitted(tmp_path: Path) -> None:
    """Regression for a synchronous callback during multi-leg submission."""

    stub_root = tmp_path / "stubs"
    stub_root.mkdir()
    (stub_root / "AlgorithmImports.py").write_text(
        """
class QCAlgorithm: pass
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
        """
import importlib.util
import sys
from types import SimpleNamespace

source = sys.argv[1]
spec = importlib.util.spec_from_file_location("canonical_lean_algorithms", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class FakeAlgorithm(module._StrategyAlgorithm):
    def __init__(self):
        self._group_sequence = 0
        self._pending_groups = {}
        self._pending_orders = {}
        self._orphan_order_events = {}
        self._unhedged_groups = {}
        self._blocked_symbols = set()
        self.activated = False
        self.calls = 0

    def _on_probe_group(self, group):
        self.activated = True

    def market_order(self, symbol, quantity, *, asynchronous, tag):
        self.calls += 1
        order_id = self.calls
        if order_id == 1:
            self.on_order_event(SimpleNamespace(order_id=order_id, status="filled", fill_quantity=1))
            return SimpleNamespace(order_id=order_id)
        raise RuntimeError("second leg rejected before submission")

algorithm = FakeAlgorithm()
try:
    algorithm._new_order_group(
        kind="probe",
        symbol="SPY",
        legs=[
            {"name": "protective", "symbol": "LONG", "quantity": 1},
            {"name": "short", "symbol": "SHORT", "quantity": -1},
        ],
        metadata={},
    )
except RuntimeError:
    pass
assert algorithm.activated is False
assert algorithm.calls == 2
assert "SPY" in algorithm._blocked_symbols
print("ok")
""",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(stub_root), str(source.parents[4])]
    )
    result = subprocess.run(
        [sys.executable, str(probe), str(source)],
        cwd=stub_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"

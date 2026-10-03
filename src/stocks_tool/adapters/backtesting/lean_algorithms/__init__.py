"""Actual LEAN algorithm sources used by the local backtest runner.

The registry is intentionally explicit.  The public backtest request maps to
one of these algorithm classes and a checked-in source file; it never maps a
strategy to a generic signal loop or to a synthetic performance shortcut.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class LeanAlgorithmSpec:
    strategy: str
    algorithm_type: str
    source_name: str = "algorithms.py"
    research_only: bool = False

    @property
    def source_path(self) -> Path:
        return _ROOT / self.source_name


_SPECS = {
    "bull_put": LeanAlgorithmSpec(
        strategy="bull_put",
        algorithm_type="StocksToolBullPutAlgorithm",
    ),
    "covered_call": LeanAlgorithmSpec(
        strategy="covered_call",
        algorithm_type="StocksToolCoveredCallAlgorithm",
    ),
    "zero_dte": LeanAlgorithmSpec(
        strategy="zero_dte",
        algorithm_type="StocksToolZeroDteResearchAlgorithm",
        research_only=True,
    ),
}


def algorithm_spec(strategy: Any) -> LeanAlgorithmSpec:
    normalized = str(getattr(strategy, "value", strategy)).strip().lower()
    spec = _SPECS[normalized]
    try:
        from stocks_tool.domain.backtesting import BacktestStrategy

        return LeanAlgorithmSpec(
            strategy=BacktestStrategy(normalized),
            algorithm_type=spec.algorithm_type,
            source_name=spec.source_name,
            research_only=spec.research_only,
        )
    except (ImportError, ModuleNotFoundError):
        return spec


def algorithm_source(strategy: Any) -> str:
    return algorithm_spec(strategy).source_path.read_text(encoding="utf-8")


def algorithm_manifest(strategy: Any, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = algorithm_spec(strategy)
    return {
        "strategy": getattr(spec.strategy, "value", spec.strategy),
        "algorithm_type": spec.algorithm_type,
        "source": spec.source_name,
        "source_sha256": __import__("hashlib").sha256(spec.source_path.read_bytes()).hexdigest(),
        "research_only": spec.research_only,
        "parameters": dict(parameters or {}),
        "future_information_policy": "current_slice_only",
    }


__all__ = ["LeanAlgorithmSpec", "algorithm_manifest", "algorithm_source", "algorithm_spec"]

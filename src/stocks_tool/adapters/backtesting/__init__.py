"""Offline backtesting adapters.

Adapters in this package are intentionally broker-free.  The production
adapter launches a pinned LEAN container with a network namespace disabled;
the pure simulator and fixture reader are used by unit tests and local
software checks only.
"""

from stocks_tool.adapters.backtesting.lean_data import LeanDataAdapter
from stocks_tool.adapters.backtesting.lean_algorithms import (
    LeanAlgorithmSpec,
    algorithm_manifest,
    algorithm_source,
    algorithm_spec,
)
from stocks_tool.adapters.backtesting.lean_staging import (
    LeanStagingError,
    LeanStagingResult,
    stage_registered_dataset,
)

from stocks_tool.adapters.backtesting.lean import (
    DEFAULT_LEAN_IMAGE_REPOSITORY,
    LeanExecutionContext,
    LeanExecutionError,
    LeanLauncher,
    LeanLauncherConfig,
)

__all__ = [
    "DEFAULT_LEAN_IMAGE_REPOSITORY",
    "LeanExecutionContext",
    "LeanExecutionError",
    "LeanLauncher",
    "LeanLauncherConfig",
    "LeanDataAdapter",
    "LeanAlgorithmSpec",
    "algorithm_manifest",
    "algorithm_source",
    "algorithm_spec",
    "LeanStagingError",
    "LeanStagingResult",
    "stage_registered_dataset",
]

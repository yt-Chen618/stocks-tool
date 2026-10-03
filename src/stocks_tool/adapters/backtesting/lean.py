"""Run the open-source LEAN Engine as an isolated local Docker process.

This adapter deliberately launches the official LEAN image directly instead of
using the paid/cloud LEAN CLI.  The request file written by the application is
translated into the config contract consumed by the image entrypoint.  The
algorithm runtime, config, and dataset are read-only mounts; only the result
directory is writable.  Docker is the process owner, so cancellation always
inspects the labelled container before it stops or removes anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from stocks_tool.adapters.backtesting.engine_lock import (
    LEAN_ENGINE_IMAGE_DIGEST,
    LEAN_ENGINE_IMAGE_REPOSITORY,
    is_full_digest,
)
from stocks_tool.domain.backtesting import canonical_json
from stocks_tool.adapters.backtesting.lean_staging import stage_registered_dataset


DEFAULT_LEAN_IMAGE_REPOSITORY = LEAN_ENGINE_IMAGE_REPOSITORY
# The checked-in registry is the sole runtime source. Mounting a second
# inert runtime algorithms.py made it possible for source identity and
# execution to drift apart.
LEAN_RUNTIME_PATH = Path(__file__).resolve().parent / "lean_algorithms"
LEAN_RUNTIME_MOUNT = "/stocks-tool-runtime"
LEAN_SOURCE_PATH = Path(__file__).resolve().parents[3]
LEAN_SOURCE_MOUNT = "/stocks-tool-source"
LEAN_ALGORITHM_REGISTRY_MOUNT = f"{LEAN_SOURCE_MOUNT}/stocks_tool/adapters/backtesting/lean_algorithms"
LEAN_ALGORITHM_ENTRYPOINT_MOUNT = "/stocks-tool-algorithm.py"
LEAN_DATA_MOUNT = "/Lean/Data"
LEAN_CONFIG_PATH = "/Lean/Launcher/bin/Debug/config.json"
LEAN_RESULT_MOUNT = "/Results"
LEAN_RESULT_SUFFIX = ".json"
LEAN_OWNER_LABEL = "stocks-tool"
LEAN_CONTAINER_LABEL = "stocks-tool.backtest"

# These names are the small contract between the application and the checked-
# in Python runtime.  Strategy workers can replace a strategy class body
# without changing the launcher or config shape.
LEAN_ALGORITHM_TYPES: dict[str, str] = {
    "fixture": "StocksToolFixtureAlgorithm",
    "bull_put": "StocksToolBullPutAlgorithm",
    "covered_call": "StocksToolCoveredCallAlgorithm",
    "zero_dte": "StocksToolZeroDteResearchAlgorithm",
}
LEAN_ALGORITHM_SOURCES: dict[str, str] = {
    "bull_put": "algorithms.py",
    "covered_call": "algorithms.py",
    "zero_dte": "algorithms.py",
}
LEAN_RESERVED_PARAMETER_KEYS = frozenset(
    {
        "canonical_manifest",
        "start_date",
        "end_date",
        "symbols",
        "initial_cash",
        "formal",
        "stocks_tool_parameters",
        "stocks_tool_fee_model",
        "stocks_tool_slippage_model",
        "stocks_tool_lifecycle_model",
        "stocks_tool_initial_stock_lots",
        "stocks_tool_run_id",
        "stocks_tool_config_path",
    }
)
LEAN_ALGORITHM_FILE = "algorithms.py"


class LeanExecutionError(RuntimeError):
    """A safe, operator-facing LEAN execution failure."""


@dataclass(frozen=True)
class LeanLauncherConfig:
    image_repository: str = DEFAULT_LEAN_IMAGE_REPOSITORY
    image_digest: str | None = LEAN_ENGINE_IMAGE_DIGEST
    docker_binary: str = "docker"
    timeout_seconds: int = 86_400
    memory_limit: str = "4g"
    cpus: str = "2"
    pids_limit: int = 512
    runtime_path: Path = LEAN_RUNTIME_PATH
    tmpfs_size: str = "512m"
    docker_command_timeout_seconds: int = 30

    def image_ref(self, digest: str | None = None) -> str:
        selected = digest or self.image_digest
        if not selected or not is_full_digest(selected):
            raise LeanExecutionError("formal LEAN runs require a verified full image digest")
        if not self.image_repository or any(character.isspace() for character in self.image_repository):
            raise LeanExecutionError("LEAN image repository is invalid")
        return f"{self.image_repository}@{selected}"


@dataclass(frozen=True)
class LeanExecutionContext:
    run_id: str
    dataset_path: Path
    config_path: Path
    result_path: Path
    image_digest: str
    labels: dict[str, str] = field(default_factory=dict)
    runtime_path: Path | None = None
    source_path: Path | None = None
    algorithm_file: str = LEAN_ALGORITHM_FILE
    algorithm_type_name: str | None = None


@dataclass
class LeanProcess:
    process: subprocess.Popen[str]
    container_name: str
    command: list[str]
    run_id: str
    labels: dict[str, str]


class LeanLauncher:
    """Auditable Docker launcher with a finite, restart-safe lifecycle."""

    def __init__(
        self,
        config: LeanLauncherConfig | None = None,
        *,
        popen: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
        run_command: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.config = config or LeanLauncherConfig()
        self._popen = popen
        self._run_command = run_command
        self._processes: dict[str, LeanProcess] = {}

    def build_command(self, context: LeanExecutionContext) -> list[str]:
        """Build the command used by the official LEAN image entrypoint.

        The image entrypoint is already ``dotnet
        QuantConnect.Lean.Launcher.dll``. LEAN reads its config from the
        standard path inside that image; invented ``--config`` and
        ``--results`` arguments would fail before an algorithm is loaded.
        """

        dataset_path = _require_directory(context.dataset_path, "dataset path")
        config_path = _require_file(context.config_path, "LEAN request config path")
        result_path = Path(context.result_path).resolve()
        result_path.mkdir(parents=True, exist_ok=True)
        dataset_mount_path = dataset_path
        staged = None
        manifest_path = result_path / "lean-data-manifest.json"
        if manifest_path.is_file():
            staged = stage_registered_dataset(dataset_path, manifest_path, result_path)
            dataset_mount_path = staged.root
        runtime_path = _require_runtime_path(context.runtime_path or self.config.runtime_path)
        source_path = _require_source_path(context.source_path or LEAN_SOURCE_PATH)
        request = _read_request_config(config_path)
        if staged is not None and bool(request.get("formal", True)) and str(request.get("strategy", "fixture")).lower() != "fixture":
            unsupported = {
                warning.split(":", 1)[0]
                for warning in staged.warnings
                if warning.startswith(("minute_equity_unavailable", "option_files_unavailable", "option_quote_unavailable", "corporate_actions_not_staged", "security_master_not_staged", "future_information_rejected"))
            }
            if unsupported:
                raise LeanExecutionError(
                    "formal LEAN run blocked by unsupported staged dataset inputs: " + ", ".join(sorted(unsupported))
                )
        _host_algorithm_source(request, source_path)
        algorithm_entrypoint = self._write_algorithm_entrypoint(context, request, source_path)
        algorithm_file = runtime_path / context.algorithm_file
        if not algorithm_file.is_file():
            raise LeanExecutionError(f"LEAN algorithm file is missing: {algorithm_file.name}")
        if not is_full_digest(context.image_digest):
            raise LeanExecutionError("formal LEAN runs require a verified full image digest")
        safe_run_id = _safe_run_id(context.run_id)
        labels = {
            **{str(key): str(value) for key, value in context.labels.items()},
            "stocks-tool.backtest": "true",
            "stocks-tool.owner": LEAN_OWNER_LABEL,
            "stocks-tool.run-id": safe_run_id,
        }
        name = self.container_name(safe_run_id)
        container_user = _docker_user_spec()
        cache_target = "/tmp/lean-cache" if container_user is not None else "/root/.cache"
        local_share_target = "/tmp/lean-local-share" if container_user is not None else "/root/.local/share"
        command = [
            self.config.docker_binary,
            "run",
            "--pull",
            "never",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(self.config.pids_limit),
            "--memory",
            self.config.memory_limit,
            "--cpus",
            self.config.cpus,
            "--tmpfs",
            _tmpfs_mount_option("/tmp", self.config.tmpfs_size, mode="1777"),
            "--tmpfs",
            _tmpfs_mount_option(cache_target, "256m", mode="0700"),
            "--tmpfs",
            _tmpfs_mount_option(local_share_target, "128m", mode="0700"),
            "--env",
            "HOME=/tmp/lean-home",
            "--env",
            "DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1",
            "--env",
            "DOTNET_CLI_TELEMETRY_OPTOUT=1",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
        ]
        if container_user is not None:
            # On Linux, cap-drop ALL removes root's DAC_OVERRIDE capability.
            # Running as the host owner keeps bind-mounted temporary result
            # directories writable without weakening the read-only/security
            # boundary. Windows Docker Desktop keeps its existing root path.
            user_index = command.index("--pids-limit")
            command[user_index:user_index] = ["--user", container_user]
        for key, value in sorted(labels.items()):
            command.extend(["--label", f"{key}={value}"])
        data_mounts = _data_mounts(dataset_mount_path, staged=dataset_mount_path != dataset_path)
        for mount in data_mounts:
            command.extend(["--mount", mount])
        command.extend(
            [
                "--mount",
                _bind_mount(runtime_path, LEAN_RUNTIME_MOUNT, read_only=True),
                "--mount",
                _bind_mount(source_path, LEAN_SOURCE_MOUNT, read_only=True),
                "--mount",
                _bind_mount(algorithm_entrypoint, LEAN_ALGORITHM_ENTRYPOINT_MOUNT, read_only=True),
                "--mount",
                _bind_mount(config_path, LEAN_CONFIG_PATH, read_only=True),
                "--mount",
                _bind_mount(result_path, LEAN_RESULT_MOUNT, read_only=False),
                self.config.image_ref(context.image_digest),
            ]
        )
        return command

    def build_lean_config(self, context: LeanExecutionContext) -> dict[str, Any]:
        """Translate a stocks-tool request into the official LEAN config."""

        request = _read_request_config(Path(context.config_path))

        strategy = str(request.get("strategy", "fixture")).strip().lower()
        manifest = request.get("algorithm_manifest") if isinstance(request.get("algorithm_manifest"), dict) else {}
        requested_algorithm_type = str(
            request.get("algorithm_type_name")
            or manifest.get("algorithm_type")
            or request.get("algorithm")
            or ""
        ).strip()
        if requested_algorithm_type == strategy:
            requested_algorithm_type = ""
        algorithm_type = context.algorithm_type_name or requested_algorithm_type or LEAN_ALGORITHM_TYPES.get(strategy)
        if not algorithm_type or not _is_identifier(algorithm_type):
            raise LeanExecutionError(f"unknown LEAN algorithm class for strategy: {strategy}")
        if strategy not in LEAN_ALGORITHM_TYPES and not context.algorithm_type_name and not request.get("algorithm_type_name"):
            raise LeanExecutionError(f"unsupported LEAN strategy: {strategy}")

        start_date = str(request.get("start_date", "2020-01-01"))
        end_date = str(request.get("end_date", "2026-09-30"))
        symbols = _normalise_symbols(request.get("symbols", []))
        parameters = request.get("parameters")
        if not isinstance(parameters, dict):
            parameters = {}
        parameters = dict(parameters)
        reserved = sorted(
            key for key in parameters
            if str(key).lower().startswith("stocks_tool_") or str(key).lower() in LEAN_RESERVED_PARAMETER_KEYS
        )
        if reserved:
            raise LeanExecutionError("strategy parameters may not override reserved LEAN keys: " + ", ".join(reserved))
        user_parameters = dict(parameters)
        parameters["start_date"] = start_date
        parameters["end_date"] = end_date
        parameters["symbols"] = ",".join(symbols)
        parameters["initial_cash"] = str(request.get("initial_cash", "100000"))
        parameters["formal"] = str(bool(request.get("formal", True))).lower()
        parameters["stocks_tool_run_id"] = _safe_run_id(context.run_id)
        parameters["stocks_tool_config_path"] = LEAN_CONFIG_PATH
        parameters["stocks_tool_parameters"] = json.dumps(user_parameters, sort_keys=True, separators=(",", ":"), default=str)
        parameters["stocks_tool_fee_model"] = json.dumps(request.get("fee_model") if isinstance(request.get("fee_model"), dict) else {}, sort_keys=True, separators=(",", ":"), default=str)
        parameters["stocks_tool_slippage_model"] = json.dumps(request.get("slippage_model") if isinstance(request.get("slippage_model"), dict) else {}, sort_keys=True, separators=(",", ":"), default=str)
        parameters["stocks_tool_lifecycle_model"] = json.dumps(request.get("lifecycle_model") if isinstance(request.get("lifecycle_model"), dict) else {}, sort_keys=True, separators=(",", ":"), default=str)
        parameters["stocks_tool_initial_stock_lots"] = json.dumps(request.get("initial_stock_lots") if isinstance(request.get("initial_stock_lots"), list) else [], sort_keys=True, separators=(",", ":"), default=str)
        parameters["canonical_manifest"] = f"{LEAN_RESULT_MOUNT}/lean-data-manifest.json"

        algorithm_location = self._algorithm_location(context, request, strategy)
        return {
            "environment": "backtesting",
            "stocks-tool-strategy": strategy,
            "algorithm-type-name": algorithm_type,
            "algorithm-language": "Python",
            "algorithm-location": algorithm_location,
            "data-folder": LEAN_DATA_MOUNT,
            "results-destination-folder": LEAN_RESULT_MOUNT,
            "canonical-manifest": f"{LEAN_RESULT_MOUNT}/lean-data-manifest.json",
            "object-store-root": "/tmp/stocks-tool-object-store",
            "debugging": False,
            "debug-mode": False,
            "close-automatically": True,
            "show-missing-data-logs": True,
            "maximum-data-points-per-chart-series": 1_000_000,
            "maximum-chart-series": 30,
            "symbol-minute-limit": 10_000,
            "symbol-second-limit": 10_000,
            "symbol-tick-limit": 10_000,
            "job-user-id": "0",
            "api-access-token": "",
            "job-organization-id": "",
            "algorithm-id": _safe_run_id(context.run_id),
            "backtest-name": _safe_run_id(context.run_id),
            "parameters": json.dumps(parameters, sort_keys=True, separators=(",", ":"), default=str),
            "python-additional-paths": [LEAN_RUNTIME_MOUNT, LEAN_SOURCE_MOUNT],
            "log-handler": "QuantConnect.Logging.CompositeLogHandler",
            "messaging-handler": "QuantConnect.Messaging.Messaging",
            "job-queue-handler": "QuantConnect.Queues.JobQueue",
            "api-handler": "QuantConnect.Api.Api",
            "map-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider",
            "factor-file-provider": "QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider",
            "data-provider": "QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider",
            "data-channel-provider": "DataChannelProvider",
            "object-store": "QuantConnect.Lean.Engine.Storage.LocalObjectStore",
            "environments": {
                "backtesting": {
                    "live-mode": False,
                    "setup-handler": "QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler",
                    "result-handler": "QuantConnect.Lean.Engine.Results.BacktestingResultHandler",
                    "data-feed-handler": "QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed",
                    "real-time-handler": "QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler",
                    "history-provider": [
                        "QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider"
                    ],
                    "transaction-handler": "QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler",
                }
            },
        }

    def _algorithm_location(
        self,
        context: LeanExecutionContext,
        request: Mapping[str, Any],
        strategy: str,
    ) -> str:
        return LEAN_ALGORITHM_ENTRYPOINT_MOUNT

    def _write_algorithm_entrypoint(
        self,
        context: LeanExecutionContext,
        request: Mapping[str, Any],
        source_root: Path,
    ) -> Path:
        strategy = str(request.get("strategy", "fixture")).strip().lower()
        manifest = request.get("algorithm_manifest") if isinstance(request.get("algorithm_manifest"), dict) else {}
        class_name = str(
            context.algorithm_type_name
            or request.get("algorithm_type_name")
            or manifest.get("algorithm_type")
            or request.get("algorithm")
            or LEAN_ALGORITHM_TYPES.get(strategy)
            or ""
        ).strip()
        if class_name == strategy:
            class_name = LEAN_ALGORITHM_TYPES.get(strategy, "")
        if not _is_identifier(class_name):
            raise LeanExecutionError(f"unknown LEAN algorithm class for strategy: {strategy}")
        source = _host_algorithm_source(request, source_root)
        if source is None:
            source_name = "algorithms.py"
        else:
            source_name = source.name
        # The canonical source is loaded by file path, avoiding the host
        # package initializer (which imports FastAPI/Pydantic) in the image.
        content = "\n".join(
            [
                "from importlib.util import module_from_spec, spec_from_file_location",
                "_spec = spec_from_file_location('_stocks_tool_canonical', '/stocks-tool-source/stocks_tool/adapters/backtesting/lean_algorithms/" + source_name + "')",
                "_canonical = module_from_spec(_spec)",
                "_spec.loader.exec_module(_canonical)",
                f"class {class_name}(_canonical.{class_name}):",
                "    pass",
                "",
            ]
        )
        path = Path(context.result_path).resolve() / "stocks-tool-algorithm.py"
        path.write_text(content, encoding="utf-8")
        return path

    def container_name(self, run_id: str) -> str:
        safe = _safe_run_id(run_id)
        return f"stocks-tool-backtest-{safe[:50]}"

    def start(self, context: LeanExecutionContext) -> LeanProcess:
        command = self.build_command(context)
        self._write_engine_config(context)
        if shutil.which(command[0]) is None:
            raise LeanExecutionError("docker executable is unavailable; formal run was not started")
        self._ensure_local_image(context.image_digest)
        safe_run_id = _safe_run_id(context.run_id)
        labels = _container_labels(command)
        existing = self.inspect_owned_container(safe_run_id)
        if existing is not None:
            raise LeanExecutionError(f"an owned LEAN container already exists for run {safe_run_id}")
        process = self._popen(
            command,
            cwd=str(Path(context.result_path).resolve()),
            env=safe_docker_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
        )
        running = LeanProcess(
            process=process,
            container_name=self.container_name(safe_run_id),
            command=command,
            run_id=safe_run_id,
            labels=labels,
        )
        self._processes[safe_run_id] = running
        return running

    def _ensure_local_image(self, digest: str) -> None:
        image_ref = self.config.image_ref(digest)
        command = [self.config.docker_binary, "image", "inspect", image_ref]
        try:
            result = self._run_command(
                command,
                env=safe_docker_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                timeout=self.config.docker_command_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LeanExecutionError("Docker image inspection did not complete") from exc
        if result.returncode != 0:
            raise LeanExecutionError("pinned LEAN image is not available locally; explicit provisioning is required")

    def wait(self, running: LeanProcess) -> tuple[int, str, str]:
        try:
            stdout, stderr = running.process.communicate(timeout=self.config.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            self.cancel(running.run_id)
            raise LeanExecutionError("LEAN process exceeded the finite timeout") from exc
        finally:
            self._processes.pop(running.run_id, None)
        return int(running.process.returncode or 0), stdout or "", stderr or ""

    def cancel(self, run_id: str) -> bool:
        """Stop and remove only the labelled container owned by this adapter."""

        safe_run_id = _safe_run_id(run_id)
        running = self._processes.get(safe_run_id)
        container_name = running.container_name if running else self.container_name(safe_run_id)
        inspected = self.inspect_owned_container(safe_run_id)
        container_handled = False
        if inspected is not None:
            self._docker_control(["stop", "--time", "10", container_name], expected_name=container_name)
            remaining = self.inspect_owned_container(safe_run_id)
            if remaining is not None:
                self._docker_control(["rm", "--force", container_name], expected_name=container_name)
            container_handled = self.inspect_owned_container(safe_run_id) is None

        process_handled = False
        if running is not None:
            process = running.process
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            process_handled = True
            self._processes.pop(safe_run_id, None)
        return container_handled or process_handled

    def inspect_owned_container(self, run_id: str) -> dict[str, Any] | None:
        """Return a labelled container identity, including after host restart."""

        safe_run_id = _safe_run_id(run_id)
        name = self.container_name(safe_run_id)
        result = self._docker_control(["inspect", name], expected_name=name, allow_missing=True)
        if result is None:
            return None
        try:
            payload = json.loads(result.stdout)
            item = payload[0] if isinstance(payload, list) and payload else None
        except (ValueError, TypeError, IndexError):
            return None
        if not isinstance(item, dict):
            return None
        labels = ((item.get("Config") or {}).get("Labels") or {})
        if not isinstance(labels, dict):
            return None
        if (
            str(labels.get(LEAN_CONTAINER_LABEL)) != "true"
            or str(labels.get("stocks-tool.owner")) != LEAN_OWNER_LABEL
            or str(labels.get("stocks-tool.run-id")) != safe_run_id
        ):
            return None
        state = item.get("State") if isinstance(item.get("State"), dict) else {}
        return {
            "id": item.get("Id"),
            "name": str(item.get("Name", name)).lstrip("/"),
            "status": state.get("Status"),
            "running": bool(state.get("Running")),
            "labels": {str(key): str(value) for key, value in labels.items()},
        }

    def process_identity(
        self,
        context: LeanExecutionContext,
        running: LeanProcess | None = None,
    ) -> dict[str, Any]:
        command = running.command if running is not None else self.build_command(context)
        safe_run_id = _safe_run_id(context.run_id)
        return {
            "kind": "docker",
            "run_id": safe_run_id,
            "container_name": running.container_name if running else self.container_name(safe_run_id),
            "image_digest": context.image_digest,
            "owner_label": LEAN_OWNER_LABEL,
            "command_sha256": hashlib.sha256(canonical_json(command).encode("utf-8")).hexdigest(),
            "pid": running.process.pid if running else None,
        }

    def run(self, context: LeanExecutionContext) -> dict[str, Any]:
        expected_path = self.expected_result_path(context)
        if expected_path.exists():
            raise LeanExecutionError("LEAN result path already contains the expected result file")
        running = self.start(context)
        returncode, stdout, stderr = self.wait(running)
        self._persist_engine_logs(context, stdout, stderr)
        if returncode != 0:
            raise LeanExecutionError(_safe_engine_error(stderr or stdout or "LEAN exited with a non-zero status"))
        if not expected_path.is_file():
            raise LeanExecutionError(
                f"LEAN completed without its expected result file {expected_path.name}; ambiguous JSON output is rejected"
            )
        try:
            payload = json.loads(expected_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise LeanExecutionError("LEAN result file is not valid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise LeanExecutionError("LEAN result payload must be an object")
        engine_config = _read_request_config(context.config_path)
        strategy = _strategy_from_engine_config(engine_config)
        return normalize_lean_result(payload, run_id=context.run_id, strategy=strategy)

    @staticmethod
    def _persist_engine_logs(context: LeanExecutionContext, stdout: str, stderr: str) -> None:
        result_root = Path(context.result_path).resolve()
        (result_root / "lean-stdout.log").write_text(stdout or "", encoding="utf-8")
        (result_root / "lean-stderr.log").write_text(stderr or "", encoding="utf-8")

    def expected_result_path(self, context: LeanExecutionContext) -> Path:
        return Path(context.result_path).resolve() / f"{_safe_run_id(context.run_id)}{LEAN_RESULT_SUFFIX}"

    def _write_engine_config(self, context: LeanExecutionContext) -> Path:
        path = Path(context.config_path).resolve()
        config = self.build_lean_config(context)
        path.write_text(json.dumps(config, indent=2, sort_keys=True), encoding="utf-8")
        return path

    def _docker_control(
        self,
        arguments: Sequence[str],
        *,
        expected_name: str,
        allow_missing: bool = False,
    ) -> subprocess.CompletedProcess[str] | None:
        command = [self.config.docker_binary, *arguments]
        try:
            result = self._run_command(
                command,
                env=safe_docker_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                timeout=self.config.docker_command_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if allow_missing:
                # A missing daemon response is not evidence that the owned
                # container is gone.  Refuse to fall back to terminating only
                # the Docker CLI, because the attached container can survive
                # that process on Windows/Docker Desktop.
                raise LeanExecutionError("Docker inspection unavailable; owned container cleanup was not attempted") from exc
            raise LeanExecutionError("Docker control command did not complete") from exc
        if result.returncode == 0:
            return result
        missing = "no such object" in (result.stderr or "").lower() or "not found" in (result.stderr or "").lower()
        if allow_missing and missing:
            return None
        if arguments and arguments[0] in {"stop", "rm"} and missing:
            return None
        raise LeanExecutionError(f"Docker control command failed for owned container {expected_name}")


def normalize_lean_result(
    payload: dict[str, Any],
    *,
    run_id: str | None = None,
    strategy: str | None = None,
) -> dict[str, Any]:
    """Normalize official LEAN JSON without inventing observations."""

    if _has_stable_result_shape(payload):
        result = dict(payload)
        events = result.setdefault("events", _extract_lean_events(payload, run_id=run_id, strategy=strategy))
        warnings = list(result.setdefault("warnings", []))
        if events and "provider_order_events_normalized" not in warnings:
            warnings.append("provider_order_events_normalized")
        result["warnings"] = warnings
        return result

    statistics = _case_insensitive_mapping(payload, "statistics") or {}
    metrics: dict[str, Any] = {}
    equity_curve = _extract_equity_curve(payload)
    key_map = {
        "drawdown": "max_drawdown_pct",
        "sharpe ratio": "sharpe_ratio",
        "total trades": "trade_count",
        "total fees": "fees",
        "compounding annual return": "cagr",
        "probability of ruin": "probability_of_ruin",
        "start equity": "start_equity",
        "end equity": "end_equity",
    }
    for source, target in key_map.items():
        value = _case_insensitive_value(statistics, source)
        if value is not None:
            metrics[target] = _coerce_metric(value)

    # LEAN's current provider payload calls the percentage field ``Net
    # Profit`` while older result payloads may expose ``Total Net Profit`` as
    # an absolute amount.  Keep the units separate: when both equity anchors
    # exist, the absolute PnL is derived from them; a percent string is only a
    # return percentage.
    start_equity = metrics.get("start_equity")
    end_equity = metrics.get("end_equity")
    if _is_number(start_equity) and _is_number(end_equity):
        metrics["net_pnl"] = end_equity - start_equity
    else:
        legacy_net_profit = _case_insensitive_value(statistics, "total net profit")
        if legacy_net_profit is not None and not _is_percent_text(legacy_net_profit):
            metrics["net_pnl"] = _coerce_metric(legacy_net_profit)

    net_profit = _case_insensitive_value(statistics, "net profit")
    if _is_percent_text(net_profit):
        metrics["total_return_pct"] = _coerce_metric(net_profit)
    initial_cash, initial_stock_fees, has_initial_lots = _initial_lot_accounting(payload)
    if initial_cash is not None:
        metrics["initial_cash"] = initial_cash
    if has_initial_lots:
        metrics["initial_stock_fees"] = initial_stock_fees
        curve_start = equity_curve[0].get("equity") if equity_curve else None
        curve_end = equity_curve[-1].get("equity") if equity_curve else None
        if _is_number(curve_start):
            metrics["start_equity"] = curve_start
            start_equity = curve_start
        if _is_number(curve_end):
            metrics["end_equity"] = curve_end
            end_equity = curve_end
        provider_fees = metrics.get("fees")
        if _is_number(provider_fees):
            metrics["fees"] = provider_fees + initial_stock_fees
        if _is_number(initial_cash) and _is_number(end_equity):
            # The request's initial_cash is total starting capital.  LEAN's
            # Start Equity is post-inventory initialization because cash was
            # reduced by the acquisition cost and fee; use total starting
            # capital for economic PnL so the acquisition fee is included once.
            metrics["net_pnl"] = end_equity - initial_cash
            metrics["net_pnl_baseline"] = "initial_cash"
            if initial_cash > 0:
                metrics["total_return_pct"] = metrics["net_pnl"] / initial_cash * 100
        # Provider statistics were calculated before the seeded holding had a
        # reliable time-zero mark (the artifact reports Start Equity=89999 and
        # Return=11.28%).  Do not expose those start-sensitive values as if
        # they were valid.  Max drawdown is recomputed from the normalized
        # curve and explicitly uses its marked time-zero NAV as the baseline.
        metrics["cagr"] = None
        metrics["sharpe_ratio"] = None
        metrics["probability_of_ruin"] = None
        metrics["max_drawdown_baseline"] = "time_zero_marked_equity"
        metrics["max_drawdown_pct"] = _max_drawdown_pct(equity_curve)
    metrics["provider_statistics"] = statistics
    events = _extract_lean_events(payload, run_id=run_id, strategy=strategy)
    warnings = [
        "lean_provider_payload_normalized",
        "raw_metrics_are_provider_defined",
        "provider_orders_retained_in_raw_payload",
    ]
    if events:
        warnings.append("provider_order_events_normalized")
    if has_initial_lots:
        warnings.extend(
            [
                "initial_stock_provider_start_metrics_invalidated",
                "time_zero_marked_equity_drawdown_baseline",
            ]
        )
        if metrics["max_drawdown_pct"] is None:
            warnings.append("max_drawdown_unavailable_without_equity_curve")
    return {
        "metrics": metrics,
        "trades": [],
        "equity_curve": equity_curve,
        "events": events,
        "warnings": warnings,
        "raw_payload": payload,
    }


def _strategy_from_engine_config(config: Mapping[str, Any]) -> str | None:
    value = str(config.get("stocks-tool-strategy") or "").strip().lower()
    if value:
        return value
    algorithm = str(config.get("algorithm-type-name") or "").lower()
    for strategy, class_name in LEAN_ALGORITHM_TYPES.items():
        if class_name.lower() == algorithm:
            return strategy
    return None


def _initial_lot_accounting(payload: Mapping[str, Any]) -> tuple[Any, float, bool]:
    """Read the request echo used to account for pre-existing stock lots."""
    configuration = _case_insensitive_mapping(payload, "algorithmConfiguration") or {}
    parameters = _case_insensitive_value(configuration, "parameters")
    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except (TypeError, ValueError):
            parameters = {}
    if not isinstance(parameters, Mapping):
        return None, 0.0, False
    initial_cash = _coerce_metric(_case_insensitive_value(parameters, "initial_cash"))
    if not _is_number(initial_cash):
        initial_cash = None
    raw_lots = _case_insensitive_value(parameters, "stocks_tool_initial_stock_lots")
    if isinstance(raw_lots, str):
        try:
            raw_lots = json.loads(raw_lots)
        except (TypeError, ValueError):
            raw_lots = []
    if not isinstance(raw_lots, list) or not raw_lots:
        return initial_cash, 0.0, False
    fees = 0.0
    for lot in raw_lots:
        if not isinstance(lot, Mapping):
            continue
        fee = _coerce_metric(_case_insensitive_value(lot, "acquisition_fee"))
        if _is_number(fee):
            fees += float(fee)
    return initial_cash, fees, True


def _extract_lean_events(
    payload: Mapping[str, Any],
    *,
    run_id: str | None,
    strategy: str | None,
) -> list[dict[str, Any]]:
    """Expose provider order/fill/leg/lifecycle events without inventing PnL."""

    orders = _case_insensitive_value(payload, "orders")
    if not isinstance(orders, Mapping):
        return []
    events: list[dict[str, Any]] = []
    for raw_id, raw_order in orders.items():
        if not isinstance(raw_order, Mapping):
            continue
        order_id = str(_case_insensitive_value(raw_order, "id") or raw_id)
        symbol = str(_case_insensitive_value(raw_order, "symbol") or "")
        base = {
            "run_id": run_id,
            "strategy": strategy,
            "order_id": order_id,
            "symbol": symbol,
            "status": _case_insensitive_value(raw_order, "status"),
            "order_type": _case_insensitive_value(raw_order, "type"),
            "direction": _case_insensitive_value(raw_order, "direction"),
            "quantity": _case_insensitive_value(raw_order, "quantity"),
            "filled_quantity": _case_insensitive_value(raw_order, "fillquantity")
            or _case_insensitive_value(raw_order, "filledquantity"),
            "average_fill_price": _case_insensitive_value(raw_order, "averagefillprice")
            or _case_insensitive_value(raw_order, "fillprice"),
            "timestamp": _case_insensitive_value(raw_order, "time"),
        }
        events.append({"kind": "order", **base})
        legs = _case_insensitive_value(raw_order, "legs")
        if isinstance(legs, list):
            for index, leg in enumerate(legs):
                if isinstance(leg, Mapping):
                    events.append({"kind": "leg", "leg_index": index, **base, "leg": dict(leg)})
        order_events = _case_insensitive_value(raw_order, "orderevents") or _case_insensitive_value(raw_order, "events")
        if isinstance(order_events, Mapping):
            order_events = list(order_events.values())
        if not isinstance(order_events, list):
            order_events = []
        for event in order_events:
            if not isinstance(event, Mapping):
                continue
            text = " ".join(
                str(_case_insensitive_value(event, key) or "")
                for key in ("status", "message", "type", "order_event_type")
            ).lower()
            kind = "fill" if any(token in text for token in ("fill", "partial")) else "lifecycle"
            if any(token in text for token in ("assign", "exercise", "expire", "expiry", "assignment")):
                kind = "exercise_assignment_expiry"
            events.append({"kind": kind, **base, "event": dict(event)})
    return events


def safe_docker_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build the host Docker CLI environment without broker/model secrets."""

    source = source or os.environ
    allowed = {
        "PATH",
        "PATHEXT",
        "COMSPEC",
        "SYSTEMROOT",
        "WINDIR",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS_VERIFY",
        "DOCKER_API_VERSION",
    }
    result = {key: str(source[key]) for key in allowed if key in source and str(source[key])}
    result.setdefault("LC_ALL", "C.UTF-8")
    result.setdefault("LANG", "C.UTF-8")
    return result


def _bind_mount(source: Path, target: str, *, read_only: bool) -> str:
    # Docker 29 requires mount options to be explicit key=value fields.
    option = "readonly=true" if read_only else "readonly=false"
    return f"type=bind,src={source},dst={target},{option}"


def _docker_user_spec(
    *,
    host_os: str | None = None,
    uid: int | None = None,
    gid: int | None = None,
) -> str | None:
    """Return a same-owner Docker user for POSIX bind mounts only."""

    if (host_os or os.name) != "posix":
        return None
    resolve_uid = getattr(os, "getuid", None)
    resolve_gid = getattr(os, "getgid", None)
    if uid is None and callable(resolve_uid):
        uid = int(resolve_uid())
    if gid is None and callable(resolve_gid):
        gid = int(resolve_gid())
    if uid is None or gid is None or uid < 0 or gid < 0:
        return None
    return f"{uid}:{gid}"


def _tmpfs_mount_option(path: str, size: str, *, mode: str) -> str:
    owner = _docker_user_spec()
    if owner is None:
        return f"{path}:rw,nosuid,nodev,size={size}"
    uid, gid = owner.split(":", 1)
    return f"{path}:rw,nosuid,nodev,size={size},uid={uid},gid={gid},mode={mode}"


def _data_mounts(path: Path, *, staged: bool) -> list[str]:
    mounts: list[str] = []
    # These are the only run-owned LEAN data roots.  Keep the engine's
    # built-in static metadata (market-hours, symbol-properties, and similar)
    # visible, while mounting each generated asset tree once as a whole.
    asset_roots = ("equity", "option", "custom")
    if staged:
        # Mount each run-owned asset subtree once.  Per-file mounts make a
        # multi-year dataset exceed Windows' command-line limit and, more
        # seriously, leave unregistered image data visible through gaps.  The
        # image's static metadata remains available because these mounts cover
        # only generated asset trees.  A mounted equity/option root also
        # intentionally hides any image-provided data missing from the staged
        # manifest, such as default map/factor or market files.
        if not any((path / name).is_dir() for name in asset_roots):
            raise LeanExecutionError("LEAN staging produced no mountable asset trees")
        for name in asset_roots:
            child = path / name
            if child.exists() and not child.is_dir():
                raise LeanExecutionError(f"LEAN staging asset root is not a directory: {name}")
            # Empty roots are deliberate: they prevent image-provided data
            # for an unregistered asset class from leaking into the run.
            child.mkdir(parents=True, exist_ok=True)
            mounts.append(_bind_mount(child, f"{LEAN_DATA_MOUNT}/{name}", read_only=True))
        return mounts
    # Keep the image's built-in market-hours and symbol-properties databases;
    # overlay only the generated asset/custom-data trees from this run.
    for name in asset_roots:
        child = path / name
        if child.is_dir():
            mounts.append(_bind_mount(child, f"{LEAN_DATA_MOUNT}/{name}", read_only=True))
    if not mounts:
        return [_bind_mount(path, LEAN_DATA_MOUNT, read_only=True)]
    return mounts


def _require_directory(path: Path, label: str) -> Path:
    original = Path(path)
    if original.is_symlink():
        raise LeanExecutionError(f"{label} may not be a symlink")
    value = original.resolve()
    if not value.is_dir():
        raise LeanExecutionError(f"{label} must be an existing directory")
    return value


def _require_file(path: Path, label: str) -> Path:
    original = Path(path)
    if original.is_symlink():
        raise LeanExecutionError(f"{label} may not be a symlink")
    value = original.resolve()
    if not value.is_file():
        raise LeanExecutionError(f"{label} must be an existing regular file")
    return value


def _require_runtime_path(path: Path) -> Path:
    value = _require_directory(Path(path), "LEAN runtime path")
    if not (value / LEAN_ALGORITHM_FILE).is_file():
        raise LeanExecutionError(f"LEAN runtime path must contain {LEAN_ALGORITHM_FILE}")
    return value


def _require_source_path(path: Path) -> Path:
    value = _require_directory(Path(path), "LEAN strategy source path")
    source_root = LEAN_SOURCE_PATH.resolve()
    try:
        value.relative_to(source_root)
    except ValueError as exc:
        raise LeanExecutionError("LEAN strategy source path must remain inside the application source root") from exc
    if any(candidate.name.lower().startswith(".env") for candidate in value.rglob(".env*")):
        raise LeanExecutionError("LEAN strategy source path may not contain environment files")
    return value


def _read_request_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise LeanExecutionError("LEAN request config is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise LeanExecutionError("LEAN request config must be a JSON object")
    return value


def _host_algorithm_source(
    request: Mapping[str, Any],
    source_root: Path,
) -> Path | None:
    strategy = str(request.get("strategy", "fixture")).strip().lower()
    if strategy == "fixture":
        return None
    manifest = request.get("algorithm_manifest") if isinstance(request.get("algorithm_manifest"), dict) else {}
    source_name = str(request.get("algorithm_source") or manifest.get("source") or LEAN_ALGORITHM_SOURCES.get(strategy) or "").strip()
    if not source_name or Path(source_name).name != source_name or Path(source_name).suffix.lower() != ".py":
        raise LeanExecutionError(f"LEAN strategy source is invalid for {strategy}")
    root = Path(source_root).resolve()
    package_root = root / "stocks_tool" if (root / "stocks_tool").is_dir() else root
    registry_root = package_root / "adapters" / "backtesting" / "lean_algorithms"
    candidate = registry_root / source_name
    if not candidate.is_file() or candidate.is_symlink():
        raise LeanExecutionError(f"LEAN strategy source is missing: {source_name}")
    return candidate


def _safe_run_id(value: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise LeanExecutionError("LEAN run id is required")
    safe = "".join(character if character.isalnum() or character in "._-" else "-" for character in raw)
    safe = safe.strip(".-")
    if not safe:
        raise LeanExecutionError("LEAN run id is invalid")
    return safe[:80]


def _is_identifier(value: str) -> bool:
    return value.isidentifier()


def _normalise_symbols(value: Any) -> list[str]:
    if isinstance(value, str):
        values = value.replace(",", " ").split()
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return list(dict.fromkeys(str(item).strip().upper() for item in values if str(item).strip()))


def _container_labels(command: Sequence[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for index, value in enumerate(command):
        if value == "--label" and index + 1 < len(command):
            key, separator, label_value = command[index + 1].partition("=")
            if separator:
                labels[key] = label_value
    return labels


def _safe_engine_error(value: str) -> str:
    # Docker/LEAN logs may contain provider details, but never echo an
    # unbounded log or host environment values into the API error field.
    return " ".join(str(value).split())[-4000:]


def _case_insensitive_mapping(value: Any, key: str) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    for candidate, item in value.items():
        if str(candidate).lower() == key.lower() and isinstance(item, Mapping):
            return {str(k): v for k, v in item.items()}
    return None


def _case_insensitive_value(value: Mapping[str, Any], key: str) -> Any:
    for candidate, item in value.items():
        if str(candidate).lower() == key.lower():
            return item
    return None


def _has_stable_result_shape(payload: Mapping[str, Any]) -> bool:
    return all(key in payload for key in ("metrics", "trades", "equity_curve"))


def _extract_equity_curve(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    charts = _case_insensitive_mapping(payload, "charts") or {}
    for chart_key, chart in charts.items():
        if "strategy equity" not in str(chart_key).lower() or not isinstance(chart, Mapping):
            continue
        series = _case_insensitive_mapping(chart, "series") or {}
        for series_key, series_item in series.items():
            if "equity" not in str(series_key).lower() or not isinstance(series_item, Mapping):
                continue
            values = _case_insensitive_value(series_item, "values")
            if isinstance(values, list):
                return [_normalize_equity_point(item) for item in values if _is_equity_point(item)]
    return []


def _coerce_metric(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    try:
        negative_parentheses = text.startswith("(") and text.endswith(")")
        if negative_parentheses:
            text = text[1:-1].strip()
        negative_sign = text.startswith("-")
        if text[:1] in {"-", "+"}:
            text = text[1:].strip()
        if text.endswith("%"):
            number = float(text[:-1].strip())
            return -number if negative_parentheses or negative_sign else number
        text = re.sub(r"^[\$€£¥]\s*", "", text)
        number = float(text)
        number = -number if negative_parentheses or negative_sign else number
        return int(number) if number.is_integer() else number
    except ValueError:
        return value


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _max_drawdown_pct(equity_curve: Sequence[Mapping[str, Any]]) -> float | None:
    values = [
        float(point["equity"])
        for point in equity_curve
        if isinstance(point, Mapping) and _is_number(point.get("equity"))
    ]
    if not values or values[0] <= 0:
        return None
    peak = values[0]
    maximum = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            maximum = max(maximum, (peak - value) / peak * 100)
    return maximum


def _is_percent_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip().endswith("%")


def _is_equity_point(value: Any) -> bool:
    return isinstance(value, Mapping) or (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) >= 2
    )


def _normalize_equity_point(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        timestamp = next(
            (
                candidate
                for candidate in (
                    _case_insensitive_value(value, "timestamp"),
                    _case_insensitive_value(value, "time"),
                    _case_insensitive_value(value, "date"),
                    _case_insensitive_value(value, "x"),
                )
                if candidate is not None
            ),
            None,
        )
        equity = next(
            (
                candidate
                for candidate in (
                    _case_insensitive_value(value, "equity"),
                    _case_insensitive_value(value, "value"),
                    _case_insensitive_value(value, "y"),
                    _case_insensitive_value(value, "close"),
                )
                if candidate is not None
            ),
            None,
        )
        normalized = dict(value)
    else:
        timestamp = value[0]
        if len(value) >= 5:
            equity = value[4]
            normalized = {
                "open": value[1],
                "high": value[2],
                "low": value[3],
                "close": value[4],
            }
        else:
            equity = value[1]
            normalized = {}
    normalized["timestamp"] = _normalize_equity_timestamp(timestamp)
    normalized["equity"] = _coerce_metric(equity)
    return normalized


def _normalize_equity_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if abs(timestamp) >= 100_000_000_000:
            timestamp /= 1_000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value).strip()
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        return _normalize_equity_timestamp(numeric)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

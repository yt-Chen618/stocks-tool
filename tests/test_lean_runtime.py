from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from stocks_tool.adapters.backtesting.engine_lock import (
    LEAN_ENGINE_IMAGE_DIGEST,
    LEAN_ENGINE_IMAGE_TAG,
    LEAN_ENGINE_METADATA_URL,
    LEAN_ENGINE_SOURCE_URL,
    LEAN_ENGINE_VERSION,
    is_full_digest,
)
from stocks_tool.adapters.backtesting.lean import (
    LEAN_CONFIG_PATH,
    LEAN_ALGORITHM_REGISTRY_MOUNT,
    LEAN_ALGORITHM_ENTRYPOINT_MOUNT,
    LEAN_DATA_MOUNT,
    LEAN_RUNTIME_MOUNT,
    LEAN_RESULT_MOUNT,
    LEAN_SOURCE_MOUNT,
    LeanExecutionContext,
    LeanExecutionError,
    LeanLauncher,
    LeanLauncherConfig,
    _docker_user_spec,
    _data_mounts,
    normalize_lean_result,
    safe_docker_environment,
)


def _context(tmp_path: Path, *, strategy: str = "fixture", run_id: str = "run-1") -> LeanExecutionContext:
    data = tmp_path / "data"
    data.mkdir()
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "strategy": strategy,
                "symbols": ["SPY"],
                "start_date": "2024-01-01",
                "end_date": "2024-01-05",
                "initial_cash": "100000",
                "parameters": {},
            }
        ),
        encoding="utf-8",
    )
    return LeanExecutionContext(
        run_id=run_id,
        dataset_path=data,
        config_path=request,
        result_path=tmp_path / "results",
        image_digest=LEAN_ENGINE_IMAGE_DIGEST,
    )


def _mount_target(mount: str) -> str:
    return next(part.removeprefix("dst=") for part in mount.split(",") if part.startswith("dst="))


def test_staged_data_mounts_are_fixed_asset_root_count_even_with_many_files(tmp_path: Path) -> None:
    dataset = tmp_path / "staged"
    for name in ("equity", "option", "custom"):
        root = dataset / name
        root.mkdir(parents=True)
        for index in range(200):
            (root / f"registered-{index}.csv").write_text("fixture\n", encoding="utf-8")

    mounts = _data_mounts(dataset, staged=True)

    assert len(mounts) == 3
    assert [_mount_target(mount) for mount in mounts] == [
        f"{LEAN_DATA_MOUNT}/equity",
        f"{LEAN_DATA_MOUNT}/option",
        f"{LEAN_DATA_MOUNT}/custom",
    ]
    assert all("readonly=true" in mount for mount in mounts)
    assert all("registered-" not in mount for mount in mounts)


def test_staged_asset_root_hides_unregistered_image_data_when_map_or_factor_is_missing(tmp_path: Path) -> None:
    dataset = tmp_path / "staged"
    (dataset / "equity" / "usa" / "daily").mkdir(parents=True)
    (dataset / "equity" / "usa" / "daily" / "spy.zip").write_bytes(b"fixture")

    mounts = _data_mounts(dataset, staged=True)

    assert len(mounts) == 3
    assert [_mount_target(mount) for mount in mounts] == [
        f"{LEAN_DATA_MOUNT}/equity",
        f"{LEAN_DATA_MOUNT}/option",
        f"{LEAN_DATA_MOUNT}/custom",
    ]
    assert f"dst={LEAN_DATA_MOUNT}," not in "|".join(mounts)
    assert "map_files" not in "|".join(mounts)
    assert "factor_files" not in "|".join(mounts)
    assert (dataset / "option").is_dir()
    assert (dataset / "custom").is_dir()


def test_staged_data_mounts_fail_closed_without_an_asset_root(tmp_path: Path) -> None:
    (tmp_path / "stocks-tool-staging.json").write_text("{}", encoding="utf-8")

    with pytest.raises(LeanExecutionError, match="no mountable asset trees"):
        _data_mounts(tmp_path, staged=True)


def test_official_image_lock_is_full_digest():
    assert LEAN_ENGINE_IMAGE_TAG == "18100"
    assert LEAN_ENGINE_VERSION == "18100"
    assert is_full_digest(LEAN_ENGINE_IMAGE_DIGEST)
    assert LEAN_ENGINE_SOURCE_URL == "https://github.com/QuantConnect/Lean"
    assert LEAN_ENGINE_METADATA_URL.endswith("/quantconnect/lean/tags/18100")


def test_build_command_mounts_real_algorithm_config_data_and_output(tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path)
    command = launcher.build_command(context)

    assert command[command.index("--network") + 1] == "none"
    assert command[command.index("--pull") + 1] == "never"
    assert "--read-only" in command
    assert "--env-file" not in command
    assert "--config" not in command
    assert "--results-destination-folder" not in command
    assert any(LEAN_DATA_MOUNT in value and value.endswith(",readonly=true") for value in command)
    assert any(LEAN_RUNTIME_MOUNT in value and value.endswith(",readonly=true") for value in command)
    assert any(LEAN_SOURCE_MOUNT in value and value.endswith(",readonly=true") for value in command)
    assert any(LEAN_CONFIG_PATH in value and value.endswith(",readonly=true") for value in command)
    assert any(LEAN_RESULT_MOUNT in value and value.endswith(",readonly=false") for value in command)
    assert any(f"quantconnect/lean@{LEAN_ENGINE_IMAGE_DIGEST}" == value for value in command)
    assert any("stocks-tool.owner=stocks-tool" in value for value in command)


def test_docker_user_spec_is_posix_only_and_preserves_host_owner():
    assert _docker_user_spec(host_os="posix", uid=1001, gid=1002) == "1001:1002"
    assert _docker_user_spec(host_os="nt", uid=1001, gid=1002) is None


def test_build_command_can_run_as_host_uid_with_owned_tmpfs(monkeypatch, tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path)
    monkeypatch.setattr(
        "stocks_tool.adapters.backtesting.lean._docker_user_spec",
        lambda: "1001:1002",
    )
    command = launcher.build_command(context)
    user_index = command.index("--user")
    assert command[user_index + 1] == "1001:1002"
    tmpfs = [command[index + 1] for index, value in enumerate(command) if value == "--tmpfs"]
    assert "/tmp:rw,nosuid,nodev,size=512m,uid=1001,gid=1002,mode=1777" in tmpfs
    assert "/tmp/lean-cache:rw,nosuid,nodev,size=256m,uid=1001,gid=1002,mode=0700" in tmpfs
    assert "/tmp/lean-local-share:rw,nosuid,nodev,size=128m,uid=1001,gid=1002,mode=0700" in tmpfs
    assert "--cap-drop" in command and "ALL" in command
    assert "--network" in command and command[command.index("--network") + 1] == "none"


def test_build_lean_config_uses_valid_class_and_no_credentials(tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path, strategy="covered_call")
    config = launcher.build_lean_config(context)

    assert config["algorithm-type-name"] == "StocksToolCoveredCallAlgorithm"
    assert config["algorithm-language"] == "Python"
    assert config["algorithm-location"] == LEAN_ALGORITHM_ENTRYPOINT_MOUNT
    assert config["environment"] == "backtesting"
    assert config["python-additional-paths"] == [LEAN_RUNTIME_MOUNT, LEAN_SOURCE_MOUNT]
    assert config["api-access-token"] == ""
    assert config["job-user-id"] == "0"
    assert json.loads(config["parameters"])["stocks_tool_config_path"] == LEAN_CONFIG_PATH
    assert config["environments"]["backtesting"]["live-mode"] is False


def test_fixture_uses_authoritative_registry_source(tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path, strategy="fixture")
    config = launcher.build_lean_config(context)
    assert config["algorithm-location"] == LEAN_ALGORITHM_ENTRYPOINT_MOUNT


def test_lifecycle_fixture_algorithm_is_selected_through_canonical_entrypoint(tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path, strategy="fixture")
    context.config_path.write_text(
        json.dumps(
            {
                "strategy": "fixture",
                "algorithm_type_name": "StocksToolLifecycleFixtureAlgorithm",
                "parameters": {"lifecycle_scenario": "split_dividend"},
            }
        ),
        encoding="utf-8",
    )
    config = launcher.build_lean_config(context)
    assert config["algorithm-type-name"] == "StocksToolLifecycleFixtureAlgorithm"
    assert config["algorithm-location"] == LEAN_ALGORITHM_ENTRYPOINT_MOUNT


def test_authoritative_algorithm_source_imports_without_host_app_stack(tmp_path):
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
""",
        encoding="utf-8",
    )
    source = Path(__file__).resolve().parents[1] / "src" / "stocks_tool" / "adapters" / "backtesting" / "lean_algorithms" / "algorithms.py"
    probe = stub_root / "probe.py"
    probe.write_text(
        """
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('canonical_lean_algorithms', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert module.StocksToolBullPutAlgorithm
assert module.StocksToolCoveredCallAlgorithm
assert module.StocksToolZeroDteResearchAlgorithm
assert module.StocksToolLifecycleFixtureAlgorithm
assert not any(name.split('.')[0] in {'pydantic', 'fastapi', 'sqlalchemy'} for name in sys.modules)
print('ok')
""",
        encoding="utf-8",
    )
    result = __import__("subprocess").run(
        [__import__("sys").executable, str(probe), str(source)],
        cwd=str(stub_root),
        env={
            "PATH": str(Path(__import__("sys").executable).parent),
            "PYTHONPATH": __import__("os").pathsep.join((str(stub_root), str(source.parents[4]))),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_formal_algorithm_uses_lean_utc_clock_for_quote_evaluation():
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stocks_tool"
        / "adapters"
        / "backtesting"
        / "lean_algorithms"
        / "algorithms.py"
    ).read_text(encoding="utf-8")
    assert "current = self.utc_time" in source
    assert 'ZoneInfo("America/New_York")' in source


def test_build_lean_config_rejects_unknown_strategy(tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path, strategy="made_up")
    with pytest.raises(LeanExecutionError, match="unknown LEAN algorithm class"):
        launcher.build_lean_config(context)


def test_build_lean_config_rejects_reserved_strategy_parameter_overrides(tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path, strategy="bull_put")
    context.config_path.write_text(
        json.dumps(
            {
                "strategy": "bull_put",
                "symbols": ["SPY"],
                "parameters": {
                    "stocks_tool_fee_model": {"name": "attacker"},
                    "canonical_manifest": "attacker.json",
                    "stocks_tool_config_path": "attacker.json",
                },
                "fee_model": {"name": "fees", "commission_per_contract": "0.65"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(LeanExecutionError, match="reserved LEAN keys"):
        launcher.build_lean_config(context)


def test_build_lean_config_binds_manifest_fee_model_over_user_parameter(tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path, strategy="bull_put")
    context.config_path.write_text(
        json.dumps(
            {
                "strategy": "bull_put",
                "symbols": ["SPY"],
                "parameters": {"min_dte": 28},
                "fee_model": {"name": "fees", "commission_per_contract": "0.65"},
                "slippage_model": {"name": "slippage", "basis_points": "5"},
            }
        ),
        encoding="utf-8",
    )
    config = launcher.build_lean_config(context)
    parameters = json.loads(config["parameters"])
    assert json.loads(parameters["stocks_tool_fee_model"])["commission_per_contract"] == "0.65"
    assert json.loads(parameters["stocks_tool_slippage_model"])["basis_points"] == "5"


def test_build_command_rejects_strategy_source_outside_application_root(tmp_path):
    launcher = LeanLauncher()
    context = _context(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    context = context.__class__(
        **{
            **context.__dict__,
            "source_path": outside,
        }
    )
    with pytest.raises(LeanExecutionError, match="inside the application source root"):
        launcher.build_command(context)


def test_start_rejects_missing_local_image_without_pull(tmp_path, monkeypatch):
    context = _context(tmp_path)
    calls = []

    def run_command(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "No such image")

    launcher = LeanLauncher(run_command=run_command, popen=lambda *_args, **_kwargs: pytest.fail("docker run must not start"))
    monkeypatch.setattr("shutil.which", lambda _binary: "docker")
    with pytest.raises(LeanExecutionError, match="not available locally"):
        launcher.start(context)
    assert calls[0][1:3] == ["image", "inspect"]
    assert "--pull" not in calls[0]


def test_normalize_official_lean_result_preserves_raw_payload():
    payload = {
        "Statistics": {
            "Total Net Profit": "12.50",
            "Drawdown": "4.00%",
            "Total Trades": "3",
        },
        "Charts": {
            "Strategy Equity": {
                "Series": {
                    "Equity": {
                        "Values": [{"x": 1, "y": 100000}, {"x": 2, "y": 100012.5}]
                    }
                }
            }
        },
        "Orders": {"1": {"Status": "Filled"}},
    }
    result = normalize_lean_result(payload)
    assert result["metrics"]["net_pnl"] == 12.5
    assert result["metrics"]["max_drawdown_pct"] == 4.0
    assert result["metrics"]["trade_count"] == 3
    assert len(result["equity_curve"]) == 2
    assert result["raw_payload"] == payload
    assert result["events"][0]["kind"] == "order"
    assert "provider_orders_retained_in_raw_payload" in result["warnings"]


def test_normalize_lean_18100_artifact_keeps_return_units_and_equity_curve():
    artifact = Path(__file__).parent / "fixtures" / "lean-18100-result.json"
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    result = normalize_lean_result(payload, run_id="lean-smoke", strategy="fixture")

    assert result["metrics"]["net_pnl"] == 0
    assert result["metrics"]["total_return_pct"] == 0
    assert result["metrics"]["fees"] == 0
    assert len(result["equity_curve"]) == 6
    first = result["equity_curve"][0]
    assert first["timestamp"] == "2024-01-01T05:00:00Z"
    assert first["equity"] == 100000
    assert all(isinstance(point["timestamp"], str) for point in result["equity_curve"])
    assert all(isinstance(point["equity"], (int, float)) for point in result["equity_curve"])
    assert result["raw_payload"] == payload


def test_normalize_equity_array_and_currency_metric() -> None:
    result = normalize_lean_result(
        {
            "Statistics": {"Start Equity": "1000", "End Equity": "1100", "Net Profit": "10%", "Total Fees": "$1,234.50"},
            "Charts": {
                "Strategy Equity": {
                    "Series": {
                        "Equity": {
                            "Values": [[0, 1000, 1010, 990, 1005], [1000, 1005, 1020, 1000, 1015]]
                        }
                    }
                }
            },
        }
    )

    assert result["metrics"]["net_pnl"] == 100
    assert result["metrics"]["total_return_pct"] == 10
    assert result["metrics"]["fees"] == 1234.5
    assert result["equity_curve"] == [
        {
            "open": 1000,
            "high": 1010,
            "low": 990,
            "close": 1005,
            "timestamp": "1970-01-01T00:00:00Z",
            "equity": 1005,
        },
        {
            "open": 1005,
            "high": 1020,
            "low": 1000,
            "close": 1015,
            "timestamp": "1970-01-01T00:16:40Z",
            "equity": 1015,
        },
    ]


def test_normalize_covered_call_initial_lot_uses_total_cash_baseline_and_fee() -> None:
    result = normalize_lean_result(
        {
            "Statistics": {
                "Start Equity": "99999",
                "End Equity": "100149",
                "Net Profit": "0%",
                "Total Fees": "$0.00",
            },
            "algorithmConfiguration": {
                "parameters": {
                    "initial_cash": "100000",
                    "stocks_tool_initial_stock_lots": json.dumps(
                        [{"symbol": "SPY", "quantity": 100, "acquisition_price": "100", "acquisition_fee": "1"}]
                    ),
                }
            },
        }
    )

    assert result["metrics"]["start_equity"] == 99999
    assert result["metrics"]["initial_cash"] == 100000
    assert result["metrics"]["initial_stock_fees"] == 1
    assert result["metrics"]["fees"] == 1
    assert result["metrics"]["net_pnl"] == 149
    assert result["metrics"]["net_pnl_baseline"] == "initial_cash"
    assert result["metrics"]["total_return_pct"] == 0.149
    assert result["metrics"]["cagr"] is None
    assert result["metrics"]["sharpe_ratio"] is None
    assert result["metrics"]["probability_of_ruin"] is None
    assert result["metrics"]["max_drawdown_pct"] is None
    assert "initial_stock_provider_start_metrics_invalidated" in result["warnings"]


def test_normalize_covered_call_uses_time_zero_curve_as_start_nav() -> None:
    result = normalize_lean_result(
        {
            "Statistics": {"Start Equity": "89999", "End Equity": "100149", "Net Profit": "0%", "Total Fees": "$0.00"},
            "algorithmConfiguration": {
                "parameters": {
                    "initial_cash": "100000",
                    "stocks_tool_initial_stock_lots": json.dumps(
                        [{"symbol": "SPY", "quantity": 100, "acquisition_price": "100", "acquisition_fee": "1"}]
                    ),
                }
            },
            "Charts": {
                "Strategy Equity": {
                    "Series": {"Equity": {"Values": [[1, 99999, 99999, 99999, 99999], [2, 100149, 100149, 100149, 100149]]}}
                }
            },
        }
    )

    assert result["metrics"]["start_equity"] == 99999
    assert result["metrics"]["end_equity"] == 100149
    assert result["metrics"]["net_pnl"] == 149
    assert result["metrics"]["fees"] == 1


def test_seeded_max_drawdown_uses_marked_time_zero_curve_baseline() -> None:
    result = normalize_lean_result(
        {
            "Statistics": {"Start Equity": "89999", "End Equity": "99900", "Drawdown": "0%"},
            "algorithmConfiguration": {
                "parameters": {
                    "initial_cash": "100000",
                    "stocks_tool_initial_stock_lots": json.dumps(
                        [{"symbol": "SPY", "quantity": 100, "acquisition_price": "100", "acquisition_fee": "1"}]
                    ),
                }
            },
            "Charts": {
                "Strategy Equity": {
                    "Series": {"Equity": {"Values": [[1, 99999, 99999, 99999, 99999], [2, 99000, 99000, 99000, 99000]]}}
                }
            },
        }
    )

    assert result["metrics"]["max_drawdown_pct"] == pytest.approx(0.99900999, rel=1e-6)
    assert result["metrics"]["max_drawdown_baseline"] == "time_zero_marked_equity"


def test_normalize_lean_result_exposes_fill_leg_and_lifecycle_events():
    result = normalize_lean_result(
        {
            "Statistics": {},
            "Orders": {
                "7": {
                    "Symbol": "SPY 240119C00500000",
                    "Status": "Filled",
                    "OrderEvents": [
                        {"Status": "PartialFill", "FillPrice": 1.25},
                        {"Status": "Assignment", "Message": "assigned"},
                    ],
                    "Legs": [{"Symbol": "SPY", "Quantity": 1}],
                }
            },
        },
        run_id="run-7",
        strategy="covered_call",
    )
    assert {event["kind"] for event in result["events"]} == {
        "order",
        "fill",
        "exercise_assignment_expiry",
        "leg",
    }
    assert all(event["run_id"] == "run-7" for event in result["events"])


def test_result_contract_rejects_ambiguous_json(tmp_path, monkeypatch):
    launcher = LeanLauncher()
    context = _context(tmp_path)
    result_root = context.result_path
    result_root.mkdir()
    (result_root / "other.json").write_text("{}", encoding="utf-8")

    class FinishedProcess:
        pid = 101
        returncode = 0

        def communicate(self, timeout):
            return "", ""

        def poll(self):
            return 0

    monkeypatch.setattr(launcher, "start", lambda _context: type("P", (), {"run_id": "run-1", "process": FinishedProcess()})())
    monkeypatch.setattr(launcher, "wait", lambda _running: (0, "", ""))
    with pytest.raises(LeanExecutionError, match="expected result file"):
        launcher.run(context)


def test_safe_docker_environment_keeps_context_but_drops_secrets():
    env = safe_docker_environment(
        {
            "PATH": "path",
            "SYSTEMROOT": "C:\\Windows",
            "USERPROFILE": "C:\\Users\\test",
            "DOCKER_CONTEXT": "desktop-linux",
            "LONGBRIDGE_APP_KEY": "secret",
            "DEEPSEEK_API_KEY": "secret",
            "BROKER_PASSWORD": "secret",
        }
    )
    assert env["PATH"] == "path"
    assert env["SYSTEMROOT"] == "C:\\Windows"
    assert env["USERPROFILE"] == "C:\\Users\\test"
    assert env["DOCKER_CONTEXT"] == "desktop-linux"
    assert "LONGBRIDGE_APP_KEY" not in env
    assert "DEEPSEEK_API_KEY" not in env
    assert "BROKER_PASSWORD" not in env


def test_cancel_only_controls_owned_container_after_restart(tmp_path):
    calls: list[list[str]] = []
    inspect_count = 0

    def run_command(command, **_kwargs):
        nonlocal inspect_count
        calls.append(command)
        if command[1:3] == ["inspect", "stocks-tool-backtest-run-1"]:
            inspect_count += 1
            if inspect_count <= 2:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        [
                            {
                                "Id": "container-id",
                                "Name": "/stocks-tool-backtest-run-1",
                                "Config": {
                                    "Labels": {
                                        "stocks-tool.backtest": "true",
                                        "stocks-tool.owner": "stocks-tool",
                                        "stocks-tool.run-id": "run-1",
                                    }
                                },
                                "State": {"Status": "running", "Running": True},
                            }
                        ]
                    ),
                    "",
                )
            return subprocess.CompletedProcess(command, 1, "", "No such object")
        return subprocess.CompletedProcess(command, 0, "", "")

    launcher = LeanLauncher(run_command=run_command)
    assert launcher.cancel("run-1") is True
    assert [call[1] for call in calls] == ["inspect", "stop", "inspect", "rm", "inspect"]
    assert all("stocks-tool-backtest-run-1" in call for call in calls)


def test_cancel_does_not_touch_foreign_container(tmp_path):
    calls: list[list[str]] = []

    def run_command(command, **_kwargs):
        calls.append(command)
        if command[1] == "inspect":
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    [
                        {
                            "Config": {
                                "Labels": {
                                    "stocks-tool.backtest": "true",
                                    "stocks-tool.owner": "someone-else",
                                    "stocks-tool.run-id": "run-1",
                                }
                            },
                            "State": {"Running": True},
                        }
                    ]
                ),
                "",
            )
        raise AssertionError("foreign containers must never receive stop/rm")

    launcher = LeanLauncher(run_command=run_command)
    assert launcher.cancel("run-1") is False
    assert len(calls) == 1


def test_cancel_refuses_cli_only_cleanup_when_docker_inspection_fails():
    class RunningProcess:
        pid = 9
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            return 0

        def kill(self):
            self.terminated = True

    process = RunningProcess()

    def run_command(_command, **_kwargs):
        raise subprocess.TimeoutExpired("docker", 30)

    launcher = LeanLauncher(run_command=run_command)
    launcher._processes["run-1"] = type(
        "Owned",
        (),
        {
            "process": process,
            "container_name": "stocks-tool-backtest-run-1",
            "command": [],
            "run_id": "run-1",
            "labels": {},
        },
    )()
    with pytest.raises(LeanExecutionError, match="inspection unavailable"):
        launcher.cancel("run-1")
    assert process.terminated is False


def test_offline_smoke_reaches_run_path_after_image_inspection(tmp_path, monkeypatch):
    """The available-image branch must exercise the real command contract."""

    import scripts.lean_offline_smoke as smoke

    output = tmp_path / "smoke.json"
    calls: list[list[str]] = []

    def fake_docker(binary, arguments):
        command = [binary, *arguments]
        calls.append(command)
        if arguments[0] == "info":
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"ServerVersion": "29.4.3", "OSType": "linux", "Architecture": "x86_64"}),
                "",
            )
        assert arguments[:2] == ["image", "inspect"]
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                [
                    {
                        "Id": "sha256:fixture-image",
                        "RepoDigests": [f"quantconnect/lean@{LEAN_ENGINE_IMAGE_DIGEST}"],
                        "Config": {"Labels": {"org.opencontainers.image.version": "18100"}},
                    }
                ]
            ),
            "",
        )

    class StubLauncher(LeanLauncher):
        last = None

        def __init__(self, config):
            super().__init__(config)
            StubLauncher.last = self
            self.context = None
            self.command = None

        def run(self, context):
            self.context = context
            self.command = self.build_command(context)
            self._write_engine_config(context)
            expected = self.expected_result_path(context)
            expected.write_text(
                '{"Statistics":{},"RuntimeStatistics":{"Fixture Rows":"2"},"Charts":{"Fixture":{"Series":{"Value":{"Values":[[1,100],[2,101]]}}}}}',
                encoding="utf-8",
            )
            return normalize_lean_result(json.loads(expected.read_text(encoding="utf-8")))

        def inspect_owned_container(self, _run_id):
            return None

    monkeypatch.setattr(smoke, "_run_docker", fake_docker)
    monkeypatch.setattr(smoke, "LeanLauncher", StubLauncher)
    monkeypatch.setattr("sys.argv", ["lean_offline_smoke.py", "--output", str(output)])

    assert smoke.main() == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "SUCCEEDED"
    assert report["engine_version_observed"] == "18100"
    assert report["command_security"] == {
        "broker_credentials_absent": True,
        "data_mount_read_only": True,
        "env_file_absent": True,
        "network_disabled": True,
        "pull_disabled": True,
        "read_only_root": True,
        "result_mount_writable": True,
        "runtime_mount_read_only": True,
        "source_mount_read_only": True,
    }
    assert [call[1:3] for call in calls] == [["info", "--format"], ["image", "inspect"]]
    assert StubLauncher.last is not None
    assert "--network" in StubLauncher.last.command
    assert StubLauncher.last.context is not None
    assert not StubLauncher.last.context.dataset_path.parent.exists()

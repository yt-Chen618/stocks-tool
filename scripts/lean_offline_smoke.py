"""Run the checked-in custom-data algorithm in the pinned LEAN image.

The smoke gate never pulls an image, downloads data, reads ``.env``, calls a
broker, or writes the trading ledger.  It creates a tiny explicit fixture in a
temporary directory, mounts every input read-only, and records ``BLOCKED_ENV``
when Docker cannot access the already-provisioned official image.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.adapters.backtesting.engine_lock import (  # noqa: E402
    LEAN_ENGINE_IMAGE_DIGEST,
    LEAN_ENGINE_METADATA_OBSERVED,
    LEAN_ENGINE_METADATA_URL,
    LEAN_ENGINE_SOURCE_URL,
    LEAN_ENGINE_VERSION,
)
from stocks_tool.adapters.backtesting.lean import (  # noqa: E402
    LEAN_DATA_MOUNT,
    LEAN_RUNTIME_MOUNT,
    LEAN_RESULT_MOUNT,
    LEAN_SOURCE_MOUNT,
    LeanExecutionContext,
    LeanExecutionError,
    LeanLauncher,
    LeanLauncherConfig,
    safe_docker_environment,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real offline LEAN fixture smoke gate")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "lean-offline-smoke.json")
    parser.add_argument("--docker", default="docker")
    parser.add_argument("--image-digest", default=os.environ.get("LEAN_IMAGE_DIGEST", LEAN_ENGINE_IMAGE_DIGEST))
    parser.add_argument("--registered-fixture", action="store_true", help="stage canonical minute/equity/option fixture inputs before running")
    parser.add_argument("--partial-fill-fixture", action="store_true", help="run the registered two-leg partial-fill fixture")
    parser.add_argument("--lifecycle-fixture", action="store_true", help="run a real LEAN corporate-action or option-assignment fixture")
    parser.add_argument(
        "--lifecycle-scenario",
        choices=("split_dividend", "covered_call_assignment", "long_call_exercise"),
        default="split_dividend",
        help="lifecycle fixture scenario to qualify",
    )
    args = parser.parse_args()

    report: dict[str, Any] = {
        "script": "scripts/lean_offline_smoke.py",
        "status": "BLOCKED_ENV",
        "mode": (
            f"lifecycle_{args.lifecycle_scenario}"
            if args.lifecycle_fixture
            else "partial_fill_fixture"
            if args.partial_fill_fixture
            else "registered_fixture"
            if args.registered_fixture
            else "offline_fixture"
        ),
        "lifecycle_scenario": args.lifecycle_scenario if args.lifecycle_fixture else None,
        "network": "none",
        "broker_calls": False,
        "ledger_writes": False,
        "image_repository": "quantconnect/lean",
        "image_digest": args.image_digest,
        "engine_version": LEAN_ENGINE_VERSION,
        "engine_source": LEAN_ENGINE_SOURCE_URL,
        "image_metadata": LEAN_ENGINE_METADATA_URL,
        "image_metadata_observed": LEAN_ENGINE_METADATA_OBSERVED,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not _valid_digest(args.image_digest):
        report.update({"status": "BLOCKED_ENV", "reason": "image_digest_is_not_a_full_sha256"})
        return _finish(report, args.output, 3)
    if args.lifecycle_fixture and (args.registered_fixture or args.partial_fill_fixture):
        report.update({"status": "FAILED", "reason": "fixture_modes_are_mutually_exclusive"})
        return _finish(report, args.output, 2)
    if args.partial_fill_fixture and not args.registered_fixture:
        report.update({"status": "FAILED", "reason": "partial_fill_fixture_requires_registered_fixture"})
        return _finish(report, args.output, 2)

    docker_info = _run_docker(args.docker, ["info", "--format", "{{json .}}"])
    if docker_info.returncode != 0:
        report.update({"reason": "docker_unavailable", "docker_error": _compact(docker_info.stderr)})
        return _finish(report, args.output, 3)
    try:
        docker_info_payload = json.loads(docker_info.stdout)
    except (TypeError, ValueError):
        docker_info_payload = {}
    report["docker"] = {
        "server_version": docker_info_payload.get("ServerVersion"),
        "os": docker_info_payload.get("OSType"),
        "architecture": docker_info_payload.get("Architecture"),
    }

    image_ref = f"quantconnect/lean@{args.image_digest}"
    image_inspect = _run_docker(args.docker, ["image", "inspect", image_ref])
    if image_inspect.returncode != 0:
        report.update(
            {
                "reason": "official_image_not_provisioned_or_unreachable",
                "image_ref": image_ref,
                "docker_error": _compact(image_inspect.stderr),
                "next_step": "Provision the verified official image locally, then rerun this smoke gate.",
            }
        )
        return _finish(report, args.output, 3)

    try:
        image_payload = json.loads(image_inspect.stdout)
        image = image_payload[0] if isinstance(image_payload, list) and image_payload else {}
    except (TypeError, ValueError):
        image = {}
    image_labels = image.get("Config", {}).get("Labels", {}) if isinstance(image, dict) else {}
    report["image"] = {
        "id": image.get("Id"),
        "repo_digests": image.get("RepoDigests", []),
        "labels": image_labels,
    }
    report["engine_version_observed"] = (
        image_labels.get("org.opencontainers.image.version")
        if isinstance(image_labels, dict)
        else None
    ) or LEAN_ENGINE_VERSION

    run_id = f"lean-smoke-{uuid.uuid4().hex}"
    launcher = LeanLauncher(
        LeanLauncherConfig(
            docker_binary=args.docker,
            image_digest=args.image_digest,
        )
    )
    with tempfile.TemporaryDirectory(prefix="stocks-tool-lean-smoke-") as temporary:
        root = Path(temporary)
        data_root = root / "data"
        result_root = root / "results"
        result_root.mkdir(parents=True)
        if args.lifecycle_fixture:
            data_root.mkdir(parents=True, exist_ok=True)
            if args.lifecycle_scenario == "split_dividend":
                # This fixture deliberately mounts the documented native LEAN
                # factor-file contract.  The factor rows encode one 2:1 split
                # and a $1 cash dividend; the algorithm then proves LEAN
                # emitted both events and transformed the held shares.
                daily_root = data_root / "equity" / "usa" / "daily"
                factor_root = data_root / "equity" / "usa" / "factor_files"
                map_root = data_root / "equity" / "usa" / "map_files"
                daily_root.mkdir(parents=True)
                factor_root.mkdir(parents=True)
                map_root.mkdir(parents=True)
                with zipfile.ZipFile(daily_root / "spy.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr(
                        "spy.csv",
                        "20240102 00:00,1000000,1010000,990000,1000000,1000\n"
                        "20240103 00:00,500000,510000,490000,500000,2000\n"
                        "20240104 00:00,250000,260000,240000,250000,2000\n"
                        "20240105 00:00,240000,260000,230000,250000,1800\n",
                    )
                (factor_root / "spy.csv").write_text(
                    "20240102,0.9600000,0.5000000,100\n"
                    "20240103,0.9600000,0.5000000,50\n"
                    "20240104,0.9600000,0.5000000,25\n"
                    "20240105,0.9600000,0.5000000,25\n"
                    "20501231,1,1,0\n",
                    encoding="utf-8",
                )
                (map_root / "spy.csv").write_text(
                    "20240101,spy,P\n20501231,spy,P\n",
                    encoding="utf-8",
                )
                report["lifecycle_input"] = {
                    "format": "native_lean_factor_file",
                    "files": [
                        "equity/usa/daily/spy.zip",
                        "equity/usa/factor_files/spy.csv",
                        "equity/usa/map_files/spy.csv",
                    ],
                    "split_ratio": "2:1",
                    "cash_dividend": "1.00",
                }
            else:
                (data_root / "underlying_minute.csv").write_text(
                    "symbol,resolution,timestamp,open,high,low,close,volume,available_at\n"
                    "SPY,minute,2024-01-02T14:30:00Z,100,100.5,99.5,100,1000,2024-01-02T14:30:00Z\n"
                    "SPY,minute,2024-01-03T14:30:00Z,102,102.5,101.5,102,1000,2024-01-03T14:30:00Z\n"
                    "SPY,minute,2024-01-04T14:30:00Z,104,104.5,103.5,104,1000,2024-01-04T14:30:00Z\n"
                    "SPY,minute,2024-01-05T14:30:00Z,105,105.5,104.5,105,1000,2024-01-05T14:30:00Z\n",
                    encoding="utf-8",
                )
                (data_root / "option_quotes.csv").write_text(
                    "underlying,expiration,strike,right,date,bid,ask,bid_size,ask_size,volume,open_interest,delta,available_at\n"
                    "SPY,2024-01-05,100,call,2024-01-02T14:30:00Z,5.00,5.10,10,10,10,100,0.80,2024-01-02T14:30:00Z\n"
                    "SPY,2024-01-05,100,call,2024-01-03T14:30:00Z,5.00,5.05,10,10,10,100,0.90,2024-01-03T14:30:00Z\n"
                    "SPY,2024-01-05,100,call,2024-01-04T14:30:00Z,5.00,5.02,10,10,10,100,0.98,2024-01-04T14:30:00Z\n"
                    "SPY,2024-01-05,100,call,2024-01-05T14:30:00Z,5.00,5.00,10,10,10,100,1.00,2024-01-05T14:30:00Z\n",
                    encoding="utf-8",
                )
                (data_root / "option_trades.csv").write_text(
                    "underlying,expiration,strike,right,date,price,volume,available_at\n"
                    "SPY,2024-01-05,100,call,2024-01-02T14:30:00Z,5.05,10,2024-01-02T14:30:00Z\n"
                    "SPY,2024-01-05,100,call,2024-01-03T14:30:00Z,5.02,10,2024-01-03T14:30:00Z\n"
                    "SPY,2024-01-05,100,call,2024-01-04T14:30:00Z,5.01,10,2024-01-04T14:30:00Z\n"
                    "SPY,2024-01-05,100,call,2024-01-05T14:30:00Z,5.00,10,2024-01-05T14:30:00Z\n",
                    encoding="utf-8",
                )
                lifecycle_files = [
                    {"source": "underlying_minute.csv", "category": "underlying_bars"},
                    {"source": "option_quotes.csv", "category": "option_quotes"},
                    {"source": "option_trades.csv", "category": "option_trades"},
                ]
            if args.lifecycle_scenario != "split_dividend":
                (result_root / "lean-data-manifest.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "lean-local-v1",
                            "fixture": True,
                            "files": lifecycle_files,
                        },
                        sort_keys=True,
                    ),
                    encoding="utf-8",
                )
        elif args.registered_fixture:
            (data_root).mkdir(parents=True, exist_ok=True)
            (data_root / "underlying_minute.csv").write_text(
                "symbol,resolution,timestamp,open,high,low,close,volume,available_at\n"
                "SPY,minute,2024-01-02T14:30:00Z,100,101,99.5,100.5,1000,2024-01-02T14:30:00Z\n"
                "SPY,minute,2024-01-02T14:31:00Z,100.5,101.5,100,101,1200,2024-01-02T14:31:00Z\n"
                "SPY,minute,2024-01-02T15:01:00Z,101,101.5,100.5,101.25,1200,2024-01-02T15:01:00Z\n"
                "SPY,minute,2024-01-03T14:30:00Z,101,102,100.5,101.5,1100,2024-01-03T14:30:00Z\n",
                encoding="utf-8",
            )
            if args.partial_fill_fixture:
                option_quote_csv = (
                    "underlying,expiration,strike,right,date,bid,ask,bid_size,ask_size,volume,open_interest,delta,available_at\n"
                    "SPY,2024-02-16,100,call,2024-01-02T15:00:00Z,1.20,1.30,2,2,25,100,0.22,2024-01-02T15:00:00Z\n"
                    "SPY,2024-02-16,105,call,2024-01-02T15:00:00Z,0.90,1.00,2,1,20,80,0.18,2024-01-02T15:00:00Z\n"
                )
            else:
                option_quote_csv = (
                    "underlying,expiration,strike,right,date,bid,ask,bid_size,ask_size,volume,open_interest,delta,available_at\n"
                    "SPY,2024-02-16,100,call,2024-01-02T15:00:00Z,1.20,1.30,25,30,25,100,0.22,2024-01-02T15:00:00Z\n"
                    "SPY,2024-02-16,105,call,2024-01-02T15:00:00Z,0.90,1.00,20,22,20,80,0.18,2024-01-02T15:00:00Z\n"
                )
            (data_root / "option_quotes.csv").write_text(option_quote_csv, encoding="utf-8")
            (data_root / "option_trades.csv").write_text(
                "underlying,expiration,strike,right,date,price,volume,available_at\n"
                "SPY,2024-02-16,100,call,2024-01-02T15:00:00Z,1.25,10,2024-01-02T15:00:00Z\n"
                "SPY,2024-02-16,105,call,2024-01-02T15:00:00Z,0.95,8,2024-01-02T15:00:00Z\n",
                encoding="utf-8",
            )
            (result_root / "lean-data-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": "lean-local-v1",
                        "fixture": True,
                        "files": [
                            {"source": "underlying_minute.csv", "category": "underlying_bars"},
                            {"source": "option_quotes.csv", "category": "option_quotes"},
                            {"source": "option_trades.csv", "category": "option_trades"},
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        else:
            custom_root = data_root / "custom"
            custom_root.mkdir(parents=True)
            (custom_root / "stocks-tool-fixture.csv").write_text(
                "timestamp,value\n"
                "2024-01-02 00:00:00,100.00\n"
                "2024-01-03 00:00:00,101.50\n"
                "2024-01-04 00:00:00,99.25\n"
                "2024-01-05 00:00:00,102.75\n",
                encoding="utf-8",
            )
        request_path = root / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "strategy": "fixture",
                    "algorithm_type_name": (
                        "StocksToolLifecycleFixtureAlgorithm"
                        if args.lifecycle_fixture
                        else "StocksToolPartialFillFixtureAlgorithm"
                        if args.partial_fill_fixture
                        else "StocksToolFixtureAlgorithm"
                    ),
                    "symbols": ["SPY" if (args.registered_fixture or args.lifecycle_fixture) else "STKFIX"],
                    "start_date": "2024-01-02" if (args.registered_fixture or args.lifecycle_fixture) else "2024-01-01",
                    "end_date": "2024-01-08" if args.lifecycle_fixture else "2024-01-02" if args.registered_fixture else "2024-01-05",
                    "initial_cash": "100000",
                    "parameters": (
                        {"lifecycle_scenario": args.lifecycle_scenario}
                        if args.lifecycle_fixture
                        else {"registered_fixture": "true"}
                        if args.registered_fixture and not args.partial_fill_fixture
                        else {}
                    ),
                    "formal": False if (args.partial_fill_fixture or args.lifecycle_fixture) else True,
                    "fee_model": (
                        {"name": "explicit_zero_cost_fixture"}
                        if (args.partial_fill_fixture or args.lifecycle_fixture)
                        else {}
                    ),
                    "slippage_model": (
                        {"name": "zero_slippage_fixture"}
                        if (args.partial_fill_fixture or args.lifecycle_fixture)
                        else {}
                    ),
                    "lifecycle_model": (
                        {"name": "explicit_options_lifecycle"}
                        if (args.partial_fill_fixture or args.lifecycle_fixture)
                        else {}
                    ),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        context = LeanExecutionContext(
            run_id=run_id,
            dataset_path=data_root,
            config_path=request_path,
            result_path=result_root,
            image_digest=args.image_digest,
        )
        command = launcher.build_command(context)
        report["command_security"] = {
            "network_disabled": command[command.index("--network") + 1] == "none",
            "pull_disabled": command[command.index("--pull") + 1] == "never",
            "read_only_root": "--read-only" in command,
            "result_mount_writable": any(
                LEAN_RESULT_MOUNT in value and value.endswith(",readonly=false") for value in command
            ),
            "data_mount_read_only": any(
                LEAN_DATA_MOUNT in value and value.endswith(",readonly=true") for value in command
            ),
            "runtime_mount_read_only": any(
                LEAN_RUNTIME_MOUNT in value and value.endswith(",readonly=true") for value in command
            ),
            "source_mount_read_only": any(
                LEAN_SOURCE_MOUNT in value and value.endswith(",readonly=true") for value in command
            ),
            "env_file_absent": "--env-file" not in command,
            "broker_credentials_absent": not any(
                token.lower().endswith(("_key", "_token", "_secret", "_password")) for token in command
            ),
        }
        run_failed = False
        payload: dict[str, Any] = {}
        try:
            payload = launcher.run(context)
        except LeanExecutionError as exc:
            report.update({"status": "FAILED", "reason": _compact(str(exc))})
            run_failed = True
        finally:
            preserved = _preserve_run_results(result_root, args.output.parent, run_id)
            if preserved is not None:
                report["preserved_artifact_dir"] = str(preserved)
            try:
                orphan = launcher.inspect_owned_container(run_id)
                if orphan is not None:
                    launcher.cancel(run_id)
                    report["owned_container_cleanup"] = "reaped"
                else:
                    report["owned_container_cleanup"] = "none_remaining"
            except LeanExecutionError:
                report["owned_container_cleanup"] = "unverified_docker_unavailable"

        if run_failed:
            return _finish(report, args.output, 4)

        expected = launcher.expected_result_path(context)
        raw_payload = payload.get("raw_payload") if isinstance(payload.get("raw_payload"), dict) else {}
        runtime_statistics = raw_payload.get("runtimeStatistics") or raw_payload.get("RuntimeStatistics") or {}
        fixture_rows = _numeric_runtime_stat(runtime_statistics, "Fixture Rows")
        fixture_points = _chart_point_count(raw_payload, "Fixture")
        registered_equity_rows = _numeric_runtime_stat(runtime_statistics, "Registered Equity Rows")
        registered_option_rows = _numeric_runtime_stat(runtime_statistics, "Registered Option Rows")
        registered_option_contracts = _text_runtime_stat(runtime_statistics, "Registered Option Contracts")
        registered_option_contract_ids = sorted(
            item.strip() for item in registered_option_contracts.split(",") if item.strip() and item.strip() != "none"
        )
        partial_state = _text_runtime_stat(runtime_statistics, "Fixture Partial Group State")
        partial_active = _text_runtime_stat(runtime_statistics, "Fixture Partial Active")
        partial_short_submitted = _text_runtime_stat(runtime_statistics, "Fixture Partial Short Submitted")
        partial_long_filled = _text_runtime_stat(runtime_statistics, "Fixture Partial Long Filled")
        lifecycle_split_events = _numeric_runtime_stat(runtime_statistics, "Split Events")
        lifecycle_split_warning_events = _numeric_runtime_stat(runtime_statistics, "Split Warning Events")
        lifecycle_split_occurred_events = _numeric_runtime_stat(runtime_statistics, "Split Occurred Events")
        lifecycle_dividend_events = _numeric_runtime_stat(runtime_statistics, "Dividend Events")
        lifecycle_assignment_events = _numeric_runtime_stat(runtime_statistics, "Assignment Events")
        lifecycle_exercise_events = _numeric_runtime_stat(runtime_statistics, "Exercise Events")
        lifecycle_final_shares = _text_runtime_stat(runtime_statistics, "Final Equity Shares")
        lifecycle_final_option_quantity = _text_runtime_stat(runtime_statistics, "Final Option Quantity")
        lifecycle_final_cash = _text_runtime_stat(runtime_statistics, "Final Cash")
        lifecycle_final_shares_value = _numeric_runtime_stat(runtime_statistics, "Final Equity Shares")
        lifecycle_final_option_quantity_value = _numeric_runtime_stat(runtime_statistics, "Final Option Quantity")
        lifecycle_split_factors = _text_runtime_stat(runtime_statistics, "Split Factors")
        lifecycle_split_occurred_factors = _text_runtime_stat(runtime_statistics, "Split Occurred Factors")
        lifecycle_dividend_distributions = _text_runtime_stat(runtime_statistics, "Dividend Distributions")
        lifecycle_assignment_symbols = _text_runtime_stat(runtime_statistics, "Assignment Symbols")
        lifecycle_contract_multiplier = _text_runtime_stat(runtime_statistics, "Lifecycle Contract Multiplier")
        lifecycle_event_payload = _text_runtime_stat(runtime_statistics, "Lifecycle Events")
        if args.lifecycle_fixture and args.lifecycle_scenario == "split_dividend" and (
            lifecycle_split_occurred_events < 1
            or lifecycle_dividend_events < 1
            or lifecycle_final_shares_value != 200
            or "0.5" not in lifecycle_split_occurred_factors
            or "1.0" not in lifecycle_dividend_distributions
        ):
            report.update(
                {
                    "status": "FAILED",
                    "reason": "split_dividend_lifecycle_fixture_not_consumed",
                    "lifecycle_split_events": lifecycle_split_events,
                    "lifecycle_split_warning_events": lifecycle_split_warning_events,
                    "lifecycle_split_occurred_events": lifecycle_split_occurred_events,
                    "lifecycle_dividend_events": lifecycle_dividend_events,
                    "lifecycle_final_shares": lifecycle_final_shares,
                    "lifecycle_final_cash": lifecycle_final_cash,
                    "lifecycle_split_factors": lifecycle_split_factors,
                    "lifecycle_split_occurred_factors": lifecycle_split_occurred_factors,
                    "lifecycle_dividend_distributions": lifecycle_dividend_distributions,
                    "lifecycle_event_payload": lifecycle_event_payload,
                }
            )
            return _finish(report, args.output, 4)
        if args.lifecycle_fixture and args.lifecycle_scenario == "covered_call_assignment" and (
            lifecycle_assignment_events < 1
            or lifecycle_final_shares_value != 0
            or lifecycle_final_option_quantity_value != 0
            or lifecycle_contract_multiplier != "100"
            or lifecycle_assignment_symbols in {"", "none"}
        ):
            report.update(
                {
                    "status": "FAILED",
                    "reason": "covered_call_assignment_lifecycle_fixture_not_consumed",
                    "lifecycle_assignment_events": lifecycle_assignment_events,
                    "lifecycle_final_shares": lifecycle_final_shares,
                    "lifecycle_final_option_quantity": lifecycle_final_option_quantity,
                    "lifecycle_final_cash": lifecycle_final_cash,
                    "lifecycle_assignment_symbols": lifecycle_assignment_symbols,
                    "lifecycle_contract_multiplier": lifecycle_contract_multiplier,
                    "lifecycle_event_payload": lifecycle_event_payload,
                }
            )
            return _finish(report, args.output, 4)
        if args.lifecycle_fixture and args.lifecycle_scenario == "long_call_exercise" and (
            lifecycle_exercise_events < 1
            or lifecycle_final_shares_value != 100
            or lifecycle_final_option_quantity_value != 0
            or lifecycle_contract_multiplier != "100"
        ):
            report.update(
                {
                    "status": "FAILED",
                    "reason": "long_call_exercise_lifecycle_fixture_not_consumed",
                    "lifecycle_exercise_events": lifecycle_exercise_events,
                    "lifecycle_final_shares": lifecycle_final_shares,
                    "lifecycle_final_option_quantity": lifecycle_final_option_quantity,
                    "lifecycle_final_cash": lifecycle_final_cash,
                    "lifecycle_contract_multiplier": lifecycle_contract_multiplier,
                    "lifecycle_event_payload": lifecycle_event_payload,
                }
            )
            return _finish(report, args.output, 4)
        if args.partial_fill_fixture and (
            partial_state not in {"partial", "partial_terminal"}
            or partial_active.lower() != "false"
            or partial_short_submitted.lower() != "false"
            or partial_long_filled not in {"1", "1.0", "1.000000"}
        ):
            report.update(
                {
                    "status": "FAILED",
                    "reason": "partial_fill_fixture_did_not_preserve_pending_unhedged_state",
                    "fixture_partial_group_state": partial_state,
                    "fixture_partial_active": partial_active,
                    "fixture_partial_short_submitted": partial_short_submitted,
                    "fixture_partial_long_filled": partial_long_filled,
                }
            )
            return _finish(report, args.output, 4)
        if not args.partial_fill_fixture and not args.lifecycle_fixture and (fixture_rows <= 0 or fixture_points <= 0 or (
            args.registered_fixture
            and (
                registered_equity_rows <= 0
                or registered_option_rows <= 0
                or len(set(registered_option_contract_ids)) != 2
            )
        )):
            report.update(
                {
                    "status": "FAILED",
                    "reason": "fixture_data_was_not_observed_by_lean_algorithm",
                    "fixture_rows": fixture_rows,
                    "fixture_points": fixture_points,
                    "registered_equity_rows": registered_equity_rows,
                    "registered_option_rows": registered_option_rows,
                    "registered_option_contracts": registered_option_contract_ids,
                }
            )
            return _finish(report, args.output, 4)
        report.update(
            {
                "status": "SUCCEEDED",
                "run_id": run_id,
                "expected_result": expected.name,
                "metrics": payload.get("metrics", {}),
                "equity_points": len(payload.get("equity_curve", [])),
                "fixture_rows": fixture_rows,
                "fixture_points": fixture_points,
                "registered_equity_rows": registered_equity_rows,
                "registered_option_rows": registered_option_rows,
                "registered_option_contracts": registered_option_contract_ids,
                "fixture_partial_group_state": partial_state,
                "fixture_partial_active": partial_active,
                "fixture_partial_short_submitted": partial_short_submitted,
                "fixture_partial_long_filled": partial_long_filled,
                "lifecycle_split_events": lifecycle_split_events,
                "lifecycle_split_warning_events": lifecycle_split_warning_events,
                "lifecycle_split_occurred_events": lifecycle_split_occurred_events,
                "lifecycle_dividend_events": lifecycle_dividend_events,
                "lifecycle_assignment_events": lifecycle_assignment_events,
                "lifecycle_exercise_events": lifecycle_exercise_events,
                "lifecycle_final_shares": lifecycle_final_shares,
                "lifecycle_final_option_quantity": lifecycle_final_option_quantity,
                "lifecycle_final_cash": lifecycle_final_cash,
                "lifecycle_split_factors": lifecycle_split_factors,
                "lifecycle_split_occurred_factors": lifecycle_split_occurred_factors,
                "lifecycle_dividend_distributions": lifecycle_dividend_distributions,
                "lifecycle_assignment_symbols": lifecycle_assignment_symbols,
                "lifecycle_contract_multiplier": lifecycle_contract_multiplier,
                "lifecycle_event_payload": lifecycle_event_payload,
                "warnings": payload.get("warnings", []),
            }
        )
        marker = result_root / "lean-data-staged" / "stocks-tool-staging.json"
        if marker.is_file():
            report["staged_data"] = json.loads(marker.read_text(encoding="utf-8"))
        return _finish(report, args.output, 0)


def _run_docker(binary: str, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [binary, *arguments],
            env=safe_docker_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess([binary, *arguments], 1, "", str(exc))


def _valid_digest(value: str) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == 71 and all(
        character in "0123456789abcdef" for character in value[7:].lower()
    )


def _compact(value: str | None) -> str:
    return " ".join(str(value or "").split())[-2000:]


def _numeric_runtime_stat(statistics: object, key: str) -> int:
    if not isinstance(statistics, dict):
        return 0
    for candidate, value in statistics.items():
        if str(candidate).lower() == key.lower():
            try:
                return int(float(str(value).replace(",", "")))
            except (TypeError, ValueError):
                return 0
    return 0


def _text_runtime_stat(statistics: object, key: str) -> str:
    if not isinstance(statistics, dict):
        return ""
    for candidate, value in statistics.items():
        if str(candidate).lower() == key.lower():
            return str(value or "")
    return ""


def _chart_point_count(payload: dict[str, Any], chart_name: str) -> int:
    charts = payload.get("charts") or payload.get("Charts") or {}
    if not isinstance(charts, dict):
        return 0
    chart = next((value for key, value in charts.items() if str(key).lower() == chart_name.lower()), None)
    if not isinstance(chart, dict):
        return 0
    series = chart.get("series") or chart.get("Series") or {}
    if not isinstance(series, dict):
        return 0
    return sum(
        len((value.get("values") or value.get("Values") or []))
        for value in series.values()
        if isinstance(value, dict)
    )


def _finish(report: dict[str, Any], output: Path, exit_code: int) -> int:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


def _preserve_run_results(result_root: Path, output_parent: Path, run_id: str) -> Path | None:
    if not result_root.is_dir():
        return None
    destination = Path(output_parent).resolve() / f"lean-offline-smoke-{run_id}"
    try:
        shutil.copytree(result_root, destination)
    except (OSError, shutil.Error):
        return None
    return destination


if __name__ == "__main__":
    raise SystemExit(main())

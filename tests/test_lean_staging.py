from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from stocks_tool.adapters.backtesting.lean import LeanExecutionContext, LeanExecutionError, LeanLauncher
from stocks_tool.adapters.backtesting.lean_staging import stage_registered_dataset
from stocks_tool.adapters.backtesting.engine_lock import LEAN_ENGINE_IMAGE_DIGEST


def test_registered_fixture_is_converted_to_consumable_lean_inputs(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "underlying_bars.csv").write_text(
        "symbol,date,open,high,low,close,volume,available_at\n"
        "SPY.US,2024-01-02,100,101,99,100.5,1000,2024-01-02T21:00:00Z\n"
        "SPY.US,2024-01-03,100.5,102,100,101.5,1100,2024-01-03T21:00:00Z\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    manifest = result_root / "lean-data-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "lean-local-v1",
                "fixture": True,
                "files": [{"source": "underlying_bars.csv", "category": "underlying_bars"}],
            }
        ),
        encoding="utf-8",
    )

    staged = stage_registered_dataset(dataset, manifest, result_root)

    fixture = staged.root / "custom" / "stocks-tool-fixture.csv"
    assert staged.fixture_consumed is True
    assert fixture.read_text(encoding="utf-8").splitlines() == [
        "timestamp,value",
        "2024-01-02 00:00:00,100.5",
        "2024-01-03 00:00:00,101.5",
    ]
    equity_zip = staged.root / "equity" / "usa" / "daily" / "spy.zip"
    assert equity_zip.is_file()
    with zipfile.ZipFile(equity_zip) as archive:
        assert archive.namelist() == ["spy.csv"]
        content = archive.read("spy.csv").decode("utf-8")
    assert "20240102 00:00,1000000,1010000,990000,1005000,1000" in content
    neutral_factor = staged.root / "equity" / "usa" / "factor_files" / "spy.csv"
    neutral_map = staged.root / "equity" / "usa" / "map_files" / "spy.csv"
    assert neutral_factor.read_text(encoding="utf-8").splitlines() == [
        "20240102,1,1,0",
        "20501231,1,1,0",
    ]
    assert neutral_map.read_text(encoding="utf-8").splitlines() == [
        "20240102,spy,P",
        "20501231,spy,P",
    ]

    request = tmp_path / "request.json"
    request.write_text(
        json.dumps({"strategy": "fixture", "symbols": ["STKFIX"], "parameters": {}}),
        encoding="utf-8",
    )
    context = LeanExecutionContext(
        run_id="registered-fixture",
        dataset_path=dataset,
        config_path=request,
        result_path=result_root,
        image_digest=LEAN_ENGINE_IMAGE_DIGEST,
    )
    command = LeanLauncher().build_command(context)
    staged_mounts = [value for value in command if "dst=/Lean/Data/" in value]
    assert staged_mounts
    assert all("lean-data-staged" in value for value in staged_mounts)


def test_registered_option_rows_are_staged_to_native_minute_files_and_universe(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "option_quotes.csv").write_text(
        "underlying,expiration,strike,right,date,bid,ask,bid_size,ask_size,volume,open_interest,delta,available_at\n"
        "SPY.US,2024-02-16,500,call,2024-01-02T15:00:00Z,1.20,1.30,25,30,999,100,-0.22,2024-01-02T15:00:00Z\n"
        "SPY.US,2024-02-16,505,call,2024-01-02T15:00:00Z,0.90,1.00,20,22,888,80,-0.18,2024-01-02T15:00:00Z\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    manifest = result_root / "lean-data-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "lean-local-v1",
                "files": [{"source": "option_quotes.csv", "category": "option_quotes"}],
            }
        ),
        encoding="utf-8",
    )

    staged = stage_registered_dataset(dataset, manifest, result_root)
    quote_zip = staged.root / "option" / "usa" / "minute" / "spy" / "20240102_quote_american.zip"
    universe = staged.root / "option" / "usa" / "universes" / "spy" / "20240102.csv"
    assert quote_zip.is_file()
    assert universe.is_file()
    with zipfile.ZipFile(quote_zip) as archive:
        assert archive.namelist() == [
            "20240102_spy_minute_quote_american_call_5000000_20240216.csv",
            "20240102_spy_minute_quote_american_call_5050000_20240216.csv",
        ]
        assert archive.read(archive.namelist()[0]).decode("utf-8").startswith("36000000,12000,12000,12000,12000,25,13000")
    assert "20240216,500,C" in universe.read_text(encoding="utf-8")
    assert "option_quote_size_unavailable" not in staged.warnings


def test_formal_strategy_blocks_when_only_daily_equity_is_registered(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "underlying_bars.csv").write_text(
        "symbol,date,open,high,low,close,volume,available_at\n"
        "SPY,2024-01-02,100,101,99,100,1000,2024-01-02T21:00:00Z\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    (result_root / "lean-data-manifest.json").write_text(
        json.dumps({"files": [{"source": "underlying_bars.csv", "category": "underlying_bars"}]}),
        encoding="utf-8",
    )
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"strategy": "bull_put", "formal": True, "symbols": ["SPY"]}), encoding="utf-8")
    context = LeanExecutionContext(
        run_id="formal-daily-only",
        dataset_path=dataset,
        config_path=request,
        result_path=result_root,
        image_digest=LEAN_ENGINE_IMAGE_DIGEST,
    )
    with pytest.raises(LeanExecutionError, match="minute_equity_unavailable"):
        LeanLauncher().build_command(context)


def test_future_available_bar_is_rejected_from_fixture_bridge(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "underlying_bars.csv").write_text(
        "symbol,date,close,available_at\n"
        "SPY,2024-01-02,100,2030-01-01T00:00:00Z\n"
        "SPY,2024-01-03,101,2024-01-03T21:00:00Z\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    manifest = result_root / "lean-data-manifest.json"
    manifest.write_text(json.dumps({"files": [{"source": "underlying_bars.csv", "category": "underlying_bars"}]}), encoding="utf-8")
    staged = stage_registered_dataset(dataset, manifest, result_root)
    assert "future_information_rejected:underlying_bars:1" in staged.warnings
    assert staged.root.joinpath("custom", "stocks-tool-fixture.csv").read_text(encoding="utf-8").splitlines() == [
        "timestamp,value",
        "2024-01-03 00:00:00,101",
    ]


def test_minute_underlying_rows_produce_minute_zip_and_daily_warmup_zip(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "underlying_minute.csv").write_text(
        "symbol,resolution,timestamp,open,high,low,close,volume,available_at\n"
        "SPY,minute,2024-01-02T14:30:00Z,100,101,99.5,100.5,1000,2024-01-02T14:30:00Z\n"
        "SPY,minute,2024-01-02T14:31:00Z,100.5,101.5,100,101,1200,2024-01-02T14:31:00Z\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    manifest = result_root / "lean-data-manifest.json"
    manifest.write_text(json.dumps({"files": [{"source": "underlying_minute.csv", "category": "underlying_bars"}]}), encoding="utf-8")
    staged = stage_registered_dataset(dataset, manifest, result_root)
    minute_zip = staged.root / "equity" / "usa" / "minute" / "spy" / "20240102_trade.zip"
    daily_zip = staged.root / "equity" / "usa" / "daily" / "spy.zip"
    assert minute_zip.is_file()
    assert daily_zip.is_file()
    with zipfile.ZipFile(minute_zip) as archive:
        assert archive.namelist() == ["20240102_spy_minute_trade.csv"]
        assert len(archive.read(archive.namelist()[0]).decode("utf-8").splitlines()) == 2


def test_minute_equity_does_not_fabricate_quote_from_trade_close_or_volume(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "underlying_minute.csv").write_text(
        "symbol,resolution,timestamp,open,high,low,close,volume,available_at\n"
        "SPY,minute,2024-01-02T14:30:00Z,100,101,99.5,100.5,1000,2024-01-02T14:30:00Z\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    manifest = result_root / "lean-data-manifest.json"
    manifest.write_text(
        json.dumps({"files": [{"source": "underlying_minute.csv", "category": "underlying_bars"}]}),
        encoding="utf-8",
    )

    staged = stage_registered_dataset(dataset, manifest, result_root)

    quote = staged.root / "equity" / "usa" / "minute" / "spy" / "20240102_quote.zip"
    assert not quote.exists()
    assert "equity_quote_unavailable" in staged.warnings


def test_split_dividend_and_security_master_are_staged_to_factor_and_map_files(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "underlying_bars.csv").write_text(
        "symbol,date,open,high,low,close,volume,available_at\n"
        "SPY,2024-01-02,100,101,99,100,1000,2024-01-02T21:00:00Z\n"
        "SPY,2024-01-03,50,51,49,50,2000,2024-01-03T21:00:00Z\n"
        "SPY,2024-01-04,50,52,49,51,2100,2024-01-04T21:00:00Z\n",
        encoding="utf-8",
    )
    (dataset / "corporate_actions.csv").write_text(
        "symbol,date,action,ratio,distribution,available_at\n"
        "SPY,2024-01-03,split,2,,2024-01-02T21:00:00Z\n"
        "SPY,2024-01-04,dividend,,0.25,2024-01-03T21:00:00Z\n",
        encoding="utf-8",
    )
    (dataset / "security_master.csv").write_text(
        "symbol,effective_start,security_type,mapped_symbol,available_at\n"
        "SPY,2024-01-02,equity,SPY,2024-01-01T21:00:00Z\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    manifest = result_root / "lean-data-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {"source": "underlying_bars.csv", "category": "underlying_bars"},
                    {"source": "corporate_actions.csv", "category": "corporate_actions"},
                    {"source": "security_master.csv", "category": "security_master"},
                ]
            }
        ),
        encoding="utf-8",
    )

    staged = stage_registered_dataset(dataset, manifest, result_root)

    factor = staged.root / "equity" / "usa" / "factor_files" / "spy.csv"
    mapping = staged.root / "equity" / "usa" / "map_files" / "spy.csv"
    assert factor.is_file()
    assert mapping.is_file()
    factor_lines = factor.read_text(encoding="utf-8").splitlines()
    assert factor_lines == [
        "20240102,0.9950000,0.5000000,100",
        "20240103,0.9950000,1.0000000,50",
        "20501231,1,1,0",
    ]
    assert mapping.read_text(encoding="utf-8").splitlines() == ["20240102,spy,P", "20501231,spy,P"]
    assert "corporate_actions_not_staged" not in staged.warnings
    assert "security_master_not_staged" not in staged.warnings
    assert "corporate_actions_staged:1" in staged.warnings
    assert "security_master_staged:1" in staged.warnings


def test_unsupported_corporate_action_fails_closed_with_a_specific_warning(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "underlying_bars.csv").write_text(
        "symbol,date,close\nSPY,2024-01-02,100\n",
        encoding="utf-8",
    )
    (dataset / "corporate_actions.csv").write_text(
        "symbol,date,action,available_at\nSPY,2024-01-02,merger,2024-01-01T21:00:00Z\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    manifest = result_root / "lean-data-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {"source": "underlying_bars.csv", "category": "underlying_bars"},
                    {"source": "corporate_actions.csv", "category": "corporate_actions"},
                ]
            }
        ),
        encoding="utf-8",
    )

    staged = stage_registered_dataset(dataset, manifest, result_root)

    assert any(warning.startswith("corporate_actions_not_staged:unsupported:") for warning in staged.warnings)


def test_multiple_actions_use_prior_close_once_and_preserve_security_master_ticker_transition(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "underlying_bars.csv").write_text(
        "symbol,date,close\n"
        "ABC,2024-01-02,100\n"
        "ABC,2024-01-03,50\n"
        "ABC,2024-01-04,52\n",
        encoding="utf-8",
    )
    (dataset / "corporate_actions.csv").write_text(
        "symbol,date,action,ratio,distribution\n"
        "ABC,2024-01-03,split,2,\n"
        "ABC,2024-01-03,dividend,,1\n"
        "ABC,2024-01-04,dividend,,0.25\n",
        encoding="utf-8",
    )
    (dataset / "security_master.csv").write_text(
        "symbol,effective_start,security_type,mapped_symbol\n"
        "ABC,2024-01-02,equity,ABC\n"
        "ABC,2024-01-04,equity,XYZ\n",
        encoding="utf-8",
    )
    result_root = tmp_path / "results"
    result_root.mkdir()
    manifest = result_root / "lean-data-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {"source": "underlying_bars.csv", "category": "underlying_bars"},
                    {"source": "corporate_actions.csv", "category": "corporate_actions"},
                    {"source": "security_master.csv", "category": "security_master"},
                ]
            }
        ),
        encoding="utf-8",
    )

    staged = stage_registered_dataset(dataset, manifest, result_root)

    factor = staged.root / "equity" / "usa" / "factor_files" / "abc.csv"
    mapping = staged.root / "equity" / "usa" / "map_files" / "abc.csv"
    assert factor.read_text(encoding="utf-8").splitlines() == [
        "20240102,0.9850500,0.5000000,100",
        "20240103,0.9950000,1.0000000,50",
        "20501231,1,1,0",
    ]
    assert mapping.read_text(encoding="utf-8").splitlines() == [
        "20240102,abc,P",
        "20240104,xyz,P",
        "20501231,xyz,P",
    ]

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import shutil
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.adapters.backtesting.engine_lock import LEAN_ENGINE_IMAGE_DIGEST
from stocks_tool.adapters.backtesting.lean import LeanExecutionContext, LeanLauncher, LeanLauncherConfig
from stocks_tool.domain.backtesting import result_semantic_payload, semantic_hash


ROOT = Path(__file__).resolve().parents[1]
def write_zip(path: Path, entries: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            archive.writestr(name, content)


def scaled(value: str | float) -> int:
    return int(round(float(value) * 10000))


def prepare_dataset(root: Path) -> None:
    equity_daily = root / "equity" / "usa" / "daily"
    equity_minute = root / "equity" / "usa" / "minute" / "spy"
    factor_root = root / "equity" / "usa" / "factor_files"
    map_root = root / "equity" / "usa" / "map_files"
    option_minute = root / "option" / "usa" / "minute" / "spy"
    option_universe = root / "option" / "usa" / "universes" / "spy"
    for path in (equity_daily, equity_minute, factor_root, map_root, option_minute, option_universe):
        path.mkdir(parents=True, exist_ok=True)

    # 65 rising sessions satisfy Bull Put's 60-bar warmup and trend gate.
    sessions: list[date] = []
    cursor = date(2023, 12, 1)
    while cursor <= date(2024, 3, 4):
        if cursor.weekday() < 5:
            sessions.append(cursor)
        cursor += timedelta(days=1)
    daily_lines = []
    for index, session in enumerate(sessions):
        close = 100 + index * 0.15
        daily_lines.append(
            f"{session.strftime('%Y%m%d')} 00:00,{scaled(close - 0.3)},{scaled(close + 0.2)},{scaled(close - 0.4)},{scaled(close)},10000"
        )
    write_zip(equity_daily / "spy.zip", {"spy.csv": "\n".join(daily_lines) + "\n"})
    (factor_root / "spy.csv").write_text("20230101,1,1,0\n20501231,1,1,0\n", encoding="utf-8")
    (map_root / "spy.csv").write_text("20230101,spy,P\n20501231,spy,P\n", encoding="utf-8")

    # Final evaluation session: spot 110 versus the prior daily close near 100.
    minute_lines = "34200000,1100000,1100000,1100000,1100000,1000\n"
    minute_lines += "34260000,1100000,1100000,1100000,1100000,1000\n"
    minute_lines += "34320000,1100000,1100000,1100000,1100000,1000\n"
    quote_lines = "34200000,1099000,1099000,1099000,1099000,1000,1101000,1101000,1101000,1101000,1000\n"
    quote_lines += "34260000,1099000,1099000,1099000,1099000,1000,1101000,1101000,1101000,1101000,1000\n"
    quote_lines += "34320000,1099000,1099000,1099000,1099000,1000,1101000,1101000,1101000,1101000,1000\n"
    for date_text in ("20240229", "20240301", "20240304"):
        write_zip(equity_minute / f"{date_text}_trade.zip", {f"{date_text}_spy_minute_trade.csv": minute_lines})
        write_zip(equity_minute / f"{date_text}_quote.zip", {f"{date_text}_spy_minute_quote.csv": quote_lines})

    contracts = [
        # Bull Put: short 106 put, protective long 104 put, 28 DTE.  The
        # fixed engine's actual Greeks place the 106 short leg at about
        # -0.18, inside the configured band; the lower 104 leg supplies the
        # required two-dollar protection width.
        {"expiry": "20240401", "strike": "106", "right": "P", "delta": "-0.22", "bid": "0.70", "ask": "0.75", "volume": "20", "oi": "500"},
        {"expiry": "20240401", "strike": "104", "right": "P", "delta": "-0.10", "bid": "0.20", "ask": "0.21", "volume": "20", "oi": "500"},
        # Covered Call: 4.1% OTM at the 110.5 fixture spot, 28 DTE.
        {"expiry": "20240401", "strike": "115", "right": "C", "delta": "0.30", "bid": "2.00", "ask": "2.05", "volume": "20", "oi": "500"},
        # Zero-DTE research signal: same-day call just above the 110.5 spot.
        # The lower synthetic premium gives LEAN's native option model a
        # delta inside the shared 0.15-0.30 selector band.
        {"expiry": "20240301", "strike": "111", "right": "C", "delta": "0.22", "bid": "0.15", "ask": "0.18", "volume": "20", "oi": "500"},
    ]
    for data_date in ("20240229", "20240301", "20240304"):
        quote_entries: dict[str, str] = {}
        trade_entries: dict[str, str] = {}
        open_interest_entries: dict[str, str] = {}
        universe_lines = [
            "#expiry,strike,right,open,high,low,close,volume,open_interest,implied_volatility,delta,gamma,vega,theta,rho"
        ]
        for contract in contracts:
            expiry = contract["expiry"]
            strike = contract["strike"]
            right = contract["right"]
            strike_decimal = float(strike)
            scale = int(round(strike_decimal * 10000))
            universe_lines.append(
                ",".join(
                    [
                        expiry,
                        strike,
                        right,
                        contract["bid"],
                        contract["ask"],
                        contract["bid"],
                        contract["ask"],
                        contract["volume"],
                        contract["oi"],
                        "0.25",
                        contract["delta"],
                        "0.01",
                        "0.10",
                        "-0.02",
                        "0.01",
                    ]
                )
            )
            prefix = f"{data_date}_spy_minute"
            quote_name = f"{prefix}_quote_american_{'put' if right == 'P' else 'call'}_{scale}_{expiry}.csv"
            trade_name = f"{prefix}_trade_american_{'put' if right == 'P' else 'call'}_{scale}_{expiry}.csv"
            oi_name = f"{prefix}_openinterest_american_{'put' if right == 'P' else 'call'}_{scale}_{expiry}.csv"
            milliseconds = 34200000
            bid = scaled(contract["bid"])
            ask = scaled(contract["ask"])
            quote_entries[quote_name] = (
                f"{milliseconds},{bid},{bid},{bid},{bid},20,{ask},{ask},{ask},{ask},20\n"
                f"34260000,{bid},{bid},{bid},{bid},20,{ask},{ask},{ask},{ask},20\n"
                f"34320000,{bid},{bid},{bid},{bid},20,{ask},{ask},{ask},{ask},20\n"
            )
            trade_entries[trade_name] = (
                f"{milliseconds},{bid},{bid},{bid},{bid},20\n"
                f"34260000,{bid},{bid},{bid},{bid},20\n"
                f"34320000,{bid},{bid},{bid},{bid},20\n"
            )
            open_interest_entries[oi_name] = (
                f"{milliseconds},{contract['oi']}\n"
                f"34260000,{contract['oi']}\n"
                f"34320000,{contract['oi']}\n"
            )
        write_zip(option_minute / f"{data_date}_quote_american.zip", quote_entries)
        write_zip(option_minute / f"{data_date}_trade_american.zip", trade_entries)
        write_zip(option_minute / f"{data_date}_openinterest_american.zip", open_interest_entries)
        (option_universe / f"{data_date}.csv").write_text("\n".join(universe_lines) + "\n", encoding="utf-8")

    # Canonical CSVs are kept beside the native files so the launcher exercises
    # the registered-dataset staging adapter and its LEAN Universe conversion.
    daily_csv = ["symbol,date,open,high,low,close,volume,available_at"]
    daily_csv.extend(
        f"SPY,{session.isoformat()},{close - 0.3:.4f},{close + 0.2:.4f},{close - 0.4:.4f},{close:.4f},10000,{session.isoformat()}T21:00:00Z"
        for index, session in enumerate(sessions)
        for close in (100 + index * 0.15,)
    )
    (root / "underlying_bars.csv").write_text("\n".join(daily_csv) + "\n", encoding="utf-8")
    minute_csv = ["symbol,resolution,timestamp,open,high,low,close,volume,bid,ask,bid_size,ask_size,available_at"]
    for date_text, close in (("2024-02-29", 109.8), ("2024-03-01", 110.5), ("2024-03-04", 116.0)):
        minute_csv.append(
            f"SPY,minute,{date_text}T14:30:00Z,{close},{close + 0.1},{close - 0.1},{close},1000,{close - 0.1},{close + 0.1},1000,1000,{date_text}T14:30:00Z"
        )
        minute_csv.append(
            f"SPY,minute,{date_text}T14:31:00Z,{close + 0.1},{close + 0.2},{close},{close + 0.1},1000,{close},{close + 0.2},1000,1000,{date_text}T14:31:00Z"
        )
        minute_csv.append(
            f"SPY,minute,{date_text}T14:32:00Z,{close + 0.1},{close + 0.2},{close},{close + 0.1},1000,{close},{close + 0.2},1000,1000,{date_text}T14:32:00Z"
        )
    (root / "underlying_minute.csv").write_text("\n".join(minute_csv) + "\n", encoding="utf-8")
    quote_csv = ["underlying,expiration,strike,right,date,bid,ask,bid_size,ask_size,volume,open_interest,implied_volatility,delta,gamma,vega,theta,rho,available_at"]
    trade_csv = ["underlying,expiration,strike,right,date,price,volume,available_at"]
    for date_text in ("2024-02-28", "2024-02-29", "2024-03-01", "2024-03-04"):
        for minute in ("14:30", "14:31", "14:32"):
            for contract in contracts:
                expiry_text = "2024-03-01" if contract["expiry"] == "20240301" else "2024-04-01"
                right_text = "put" if contract["right"] == "P" else "call"
                observed = f"{date_text}T{minute}:00Z"
                bid = Decimal(contract["bid"])
                ask = Decimal(contract["ask"])
                if date_text == "2024-03-04":
                    if contract["right"] == "P" and contract["strike"] == "106":
                        bid, ask = Decimal("0.30"), Decimal("0.35")
                    elif contract["right"] == "P" and contract["strike"] == "104":
                        bid, ask = Decimal("0.20"), Decimal("0.21")
                    elif contract["right"] == "C" and contract["strike"] == "115":
                        bid, ask = Decimal("6.00"), Decimal("6.10")
                quote_csv.append(
                    f"SPY,{expiry_text},{contract['strike']},{right_text},{observed},{bid},{ask},20,20,{contract['volume']},{contract['oi']},0.25,{contract['delta']},0.01,0.10,-0.02,0.01,{observed}"
                )
                trade_csv.append(
                    f"SPY,{expiry_text},{contract['strike']},{right_text},{observed},{bid},{contract['volume']},{observed}"
                )
    (root / "option_quotes.csv").write_text("\n".join(quote_csv) + "\n", encoding="utf-8")
    (root / "option_trades.csv").write_text("\n".join(trade_csv) + "\n", encoding="utf-8")


def request_for(strategy: str, result_root: Path) -> Path:
    request = {
        "strategy": strategy,
        "symbols": ["SPY"],
        "start_date": "2024-03-01",
        "end_date": "2024-03-04",
        "initial_cash": "100000",
        "formal": False,
        "fee_model": {"name": "explicit_zero_cost_fixture"},
        "slippage_model": {"name": "zero_slippage_fixture"},
        "lifecycle_model": {"name": "explicit_options_lifecycle", "market_cutoff": "09:32 America/New_York"},
        "initial_stock_lots": (
            [{"symbol": "SPY", "quantity": 100, "acquisition_price": "100", "acquisition_fee": "1"}]
            if strategy == "covered_call"
            else []
        ),
        "parameters": {
            "min_option_quote_age_seconds": 1800,
            "min_open_interest": 100,
            "min_volume": 10,
            "contracts_per_trade": 1,
            "max_new_spreads_per_day": 1,
        },
    }
    path = result_root / "request.json"
    path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
    (result_root / "lean-data-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "lean-local-v1",
                "fixture": True,
                "files": [
                    {"source": "underlying_bars.csv", "category": "underlying_bars"},
                    {"source": "underlying_minute.csv", "category": "underlying_bars"},
                    {"source": "option_quotes.csv", "category": "option_quotes"},
                    {"source": "option_trades.csv", "category": "option_trades"},
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


ALGORITHM_TYPES = {
    "bull_put": "StocksToolBullPutAlgorithm",
    "covered_call": "StocksToolCoveredCallAlgorithm",
    "zero_dte": "StocksToolZeroDteResearchAlgorithm",
}
EXPECTED_ORDERS = {"bull_put": 4, "covered_call": 2, "zero_dte": 2}
SOURCE_FILES = (
    "src/stocks_tool/adapters/backtesting/lean_algorithms/algorithms.py",
    "src/stocks_tool/adapters/backtesting/lean_staging.py",
    "src/stocks_tool/adapters/backtesting/lean.py",
    "src/stocks_tool/adapters/backtesting/lean_algorithms/reality_models.py",
    "src/stocks_tool/domain/strategies/common.py",
    "src/stocks_tool/domain/strategies/bull_put.py",
    "src/stocks_tool/domain/strategies/covered_call.py",
    "src/stocks_tool/domain/strategies/zero_dte.py",
    "scripts/lean_strategy_smoke.py",
)
REQUIRED_TAG_PREFIXES = {
    "bull_put": (
        "stocks-tool bull_put_entry_protective:long_protective",
        "stocks-tool bull_put_entry_short:short_entry",
        "stocks-tool bull put close short:",
        "stocks-tool bull put close long:",
    ),
    "covered_call": (
        "stocks-tool covered_call_entry:call_entry",
        "stocks-tool covered call close/roll",
    ),
    "zero_dte": (
        "stocks-tool zero-dte entry:call:premium_cap=150",
        "stocks-tool zero-dte close:market_cutoff",
    ),
}


def _source_identity() -> dict[str, str]:
    identity = {}
    for relative in SOURCE_FILES:
        source = ROOT / relative
        if not source.is_file():
            raise RuntimeError(f"source identity file is missing: {relative}")
        identity[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
    return identity


def _semantic_projection(payload: dict) -> dict:
    projection = result_semantic_payload(payload)
    for trade in projection.get("trades", []) or []:
        trade.pop("run_id", None)
        trade.pop("id", None)
    for event in projection.get("events", []) or []:
        if isinstance(event, dict):
            event.pop("run_id", None)
    return projection


def _safe_remove_temp_run(run_root: Path) -> None:
    """Remove only the run directory created by this script."""

    resolved = run_root.resolve()
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if resolved.parent != temp_parent or not resolved.name.startswith("stocks-tool-"):
        raise RuntimeError(f"refusing to remove unexpected temporary run path: {resolved}")
    shutil.rmtree(resolved, ignore_errors=True)
    if resolved.exists():
        raise RuntimeError(f"temporary run cleanup failed: {resolved}")


def _copy_run_artifact(result_root: Path, artifact_root: Path, strategy: str, attempt: int) -> Path:
    artifact_dir = artifact_root / f"{strategy}-attempt-{attempt}"
    suffix = 2
    while artifact_dir.exists():
        artifact_dir = artifact_root / f"{strategy}-attempt-{attempt}-{suffix}"
        suffix += 1
    shutil.copytree(result_root, artifact_dir)
    return artifact_dir


def _filled_order(item: dict) -> bool:
    status = item.get("status")
    return status in (3, "3", "filled", "FILLED") and bool(item.get("lastFillTime"))


def _order_quantity(item: dict) -> Decimal:
    return Decimal(str(item.get("quantity", "0")))


def _order_direction(item: dict) -> str:
    direction = item.get("direction")
    if direction in (0, "0", "buy", "BUY"):
        return "buy"
    if direction in (1, "1", "sell", "SELL"):
        return "sell"
    return str(direction)


def _order_symbol(item: dict) -> str:
    symbol = item.get("symbol")
    if isinstance(symbol, dict):
        return str(symbol.get("value") or symbol.get("permtick") or symbol.get("id") or "")
    return str(symbol or "")


def _qualify_orders(strategy: str, raw_orders: object, *, checks: int, orders: int, stats: dict) -> tuple[dict, list[str]]:
    values = list(raw_orders.values()) if isinstance(raw_orders, dict) else list(raw_orders or [])
    filled = [item for item in values if isinstance(item, dict) and _filled_order(item)]
    option_filled = [item for item in filled if item.get("securityType") in (2, "2", "option", "OPTION")]
    details = [
        {
            "id": item.get("id"),
            "symbol": _order_symbol(item),
            "tag": str(item.get("tag") or ""),
            "status": item.get("status"),
            "direction": _order_direction(item),
            "quantity": str(_order_quantity(item)),
            "last_fill_time": item.get("lastFillTime"),
        }
        for item in sorted(filled, key=lambda row: int(row.get("id", 0)))
    ]
    net_by_symbol: dict[str, Decimal] = {}
    for item in option_filled:
        symbol = _order_symbol(item)
        net_by_symbol[symbol] = net_by_symbol.get(symbol, Decimal("0")) + _order_quantity(item)
    tags = [detail["tag"] for detail in details]
    required = REQUIRED_TAG_PREFIXES[strategy]
    tag_presence = {prefix: any(tag.startswith(prefix) for tag in tags) for prefix in required}
    pending = int(str(stats.get("Pending Order Groups", "0")))
    unhedged = int(str(stats.get("Unhedged Order Groups", "0")))
    option_net = {symbol: str(quantity) for symbol, quantity in sorted(net_by_symbol.items())}
    qualification = {
        "valid_candidate_checks": checks,
        "total_orders": orders,
        "filled_orders": len(filled),
        "filled_order_events": details,
        "filled_order_tags": tags,
        "pending_order_groups": pending,
        "unhedged_order_groups": unhedged,
        "expected_orders": EXPECTED_ORDERS[strategy],
        "option_order_count": len(option_filled),
        "option_net_quantities": option_net,
        "expected_flat_option_holdings": bool(option_filled) and all(value == 0 for value in net_by_symbol.values()),
        "required_tag_presence": tag_presence,
    }
    failures = []
    if checks < 1:
        failures.append(f"valid_candidate_checks={checks}")
    if orders < EXPECTED_ORDERS[strategy]:
        failures.append(f"total_orders={orders}")
    if len(filled) != EXPECTED_ORDERS[strategy]:
        failures.append(f"filled_orders={len(filled)}")
    if len(option_filled) != len(filled):
        failures.append("non_option_filled_order_present")
    if any(_order_quantity(item) == 0 for item in option_filled):
        failures.append("zero_quantity_filled_order")
    if any(
        (_order_direction(item) == "buy" and _order_quantity(item) < 0)
        or (_order_direction(item) == "sell" and _order_quantity(item) > 0)
        or _order_direction(item) not in {"buy", "sell"}
        for item in option_filled
    ):
        failures.append("filled_order_direction_quantity_mismatch")
    if not any(_order_quantity(item) > 0 for item in option_filled) or not any(_order_quantity(item) < 0 for item in option_filled):
        failures.append("missing_buy_or_sell_fill")
    if not qualification["expected_flat_option_holdings"]:
        failures.append(f"option_net_quantities={option_net}")
    if not all(tag_presence.values()):
        failures.append("required_entry_exit_tags_missing")
    if pending or unhedged:
        failures.append(f"pending={pending},unhedged={unhedged}")
    return qualification, failures


def _run_one(*, strategy: str, attempt: int, launcher: LeanLauncher, artifact_root: Path) -> dict:
    run_root = Path(tempfile.mkdtemp(prefix=f"stocks-tool-{strategy}-fixture-"))
    data_root = run_root / "data"
    result_root = run_root / "results"
    data_root.mkdir()
    result_root.mkdir()
    prepare_dataset(data_root)
    request_path = request_for(strategy, result_root)
    run_id = f"strategy-fixture-{strategy}-{attempt}"
    context = LeanExecutionContext(
        run_id=run_id,
        dataset_path=data_root,
        config_path=request_path,
        result_path=result_root,
        image_digest=LEAN_ENGINE_IMAGE_DIGEST,
    )
    try:
        try:
            payload = launcher.run(context)
        except Exception as exc:
            (result_root / "qualification-error.json").write_text(
                json.dumps({"strategy": strategy, "attempt": attempt, "error": str(exc)}, indent=2),
                encoding="utf-8",
            )
            artifact_dir = _copy_run_artifact(result_root, artifact_root, strategy, attempt)
            raise RuntimeError(f"{strategy} launcher failed; artifact_dir={artifact_dir}: {exc}") from exc
        raw = payload.get("raw_payload") if isinstance(payload, dict) else {}
        stats = raw.get("runtimeStatistics") or {}
        provider = (payload.get("metrics") or {}).get("provider_statistics") or {}
        checks = int(str(stats.get("valid_candidate_checks", "0")))
        orders = int(str(provider.get("Total Orders", "0")).split(" ", 1)[0])
        raw_orders = raw.get("orders") or {}
        qualification, failures = _qualify_orders(strategy, raw_orders, checks=checks, orders=orders, stats=stats)
        artifact_dir = _copy_run_artifact(result_root, artifact_root, strategy, attempt)
        if failures:
            raise RuntimeError(
                f"{strategy} qualification failed: {', '.join(failures)}, artifact_dir={artifact_dir}"
            )
        marker_path = result_root / "lean-data-staged" / "stocks-tool-staging.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.is_file() else {}
        semantic = _semantic_projection(payload)
        return {
            "strategy": strategy,
            "algorithm_type": ALGORITHM_TYPES[strategy],
            "status": "SUCCEEDED",
            "attempt": attempt,
            "run_id": run_id,
            "artifact_dir": str(artifact_dir),
            "image_digest": LEAN_ENGINE_IMAGE_DIGEST,
            "engine_version": (raw.get("serverStatistics") or {}).get("LEAN Version"),
            "source_identity": _source_identity(),
            "staging_manifest_hash": marker.get("source_manifest_hash"),
            "runtime_statistics": stats,
            "qualification": qualification,
            "semantic_hash": semantic_hash(semantic),
            "normalized": payload,
        }
    finally:
        _safe_remove_temp_run(run_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify canonical strategy candidates and orders in offline LEAN")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "professional-workbench-20261004" / "lean-strategy-smoke.json")
    parser.add_argument("--strategies", default="bull_put,covered_call,zero_dte")
    parser.add_argument("--no-repeat", action="store_true", help="skip the deterministic repeat run")
    args = parser.parse_args()
    strategies = [item.strip() for item in args.strategies.split(",") if item.strip()]
    invalid = sorted(set(strategies) - set(ALGORITHM_TYPES))
    if invalid:
        raise SystemExit(f"unknown strategy: {','.join(invalid)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    artifact_root = args.output.parent / "lean-strategy-smoke-runs"
    artifact_root.mkdir(parents=True, exist_ok=True)
    launcher = LeanLauncher(LeanLauncherConfig(timeout_seconds=600))
    source_identity_before = _source_identity()
    report = {
        "script": "scripts/lean_strategy_smoke.py",
        "status": "SUCCEEDED",
        "network": "none",
        "broker_calls": False,
        "ledger_writes": False,
        "image_digest": LEAN_ENGINE_IMAGE_DIGEST,
        "source_identity": source_identity_before,
        "source_identity_before": source_identity_before,
        "runs": [],
    }
    try:
        for strategy in strategies:
            report["runs"].append(_run_one(strategy=strategy, attempt=1, launcher=launcher, artifact_root=artifact_root))
        if not args.no_repeat:
            repeat_strategy = "bull_put" if "bull_put" in strategies else strategies[0]
            report["runs"].append(_run_one(strategy=repeat_strategy, attempt=2, launcher=launcher, artifact_root=artifact_root))
            first = next(item for item in report["runs"] if item["strategy"] == repeat_strategy and item["attempt"] == 1)
            second = next(item for item in report["runs"] if item["strategy"] == repeat_strategy and item["attempt"] == 2)
            report["repeat_check"] = {
                "strategy": repeat_strategy,
                "semantic_hash_equal": first["semantic_hash"] == second["semantic_hash"],
                "first": first["semantic_hash"],
                "second": second["semantic_hash"],
            }
            if not report["repeat_check"]["semantic_hash_equal"]:
                raise RuntimeError("same-input semantic result hash changed between runs")
    except Exception as exc:
        report["status"] = "FAILED"
        report["error"] = str(exc)
    source_identity_after = _source_identity()
    report["source_identity_after"] = source_identity_after
    report["source_identity_stable"] = source_identity_before == source_identity_after
    if not report["source_identity_stable"]:
        report["status"] = "FAILED"
        report["error"] = "source identity changed during qualification"
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output), "runs": len(report["runs"]), "error": report.get("error")}, indent=2))
    return 0 if report["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

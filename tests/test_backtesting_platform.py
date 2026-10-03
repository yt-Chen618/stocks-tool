from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from stocks_tool.adapters.backtesting.dataset import DatasetSecurityError
from stocks_tool.adapters.backtesting.lean_data import (
    inspect_lean_file,
    trusted_event_start_utc,
    trusted_session_close_utc,
    trusted_us_exchange_sessions,
    validate_session_coverage,
)
from stocks_tool.adapters.backtesting.lean_staging import _causal_rows
from stocks_tool.adapters.backtesting.simulator import simulate_events
from stocks_tool.db.base import Base
from stocks_tool.db import models as _models  # noqa: F401
from stocks_tool.db import backtest_models as _backtest_models  # noqa: F401
from stocks_tool.db.backtest_models import BacktestLeaseRecord, BacktestRunRecord
from stocks_tool.domain.backtesting import (
    BacktestCreate,
    BacktestState,
    BacktestStrategy,
    DatasetCategory,
    DatasetRegistration,
    FeeModel,
    LifecycleModel,
    SlippageModel,
    manifest_semantic_hash,
)
from stocks_tool.repositories.sqlalchemy_backtest_repository import SQLAlchemyBacktestRepository
from stocks_tool.application.services.backtesting import (
    BacktestDatasetConflictError,
    BacktestDispatcher,
    BacktestFreezeError,
    BacktestingService,
    _configuration_hash,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def session(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as value:
        yield value


def _write_dataset(root):
    headers = (
        "date,available_at,symbol,underlying,security_type,open,high,low,close,volume,bid,ask,"
        "price,expiration,strike,right,open_interest,session_open,session_close,action\n"
    )
    names = (
        "security_master.csv",
        "underlying_bars.csv",
        "option_quotes.csv",
        "option_trades.csv",
        "open_interest.csv",
        "calendar.csv",
        "corporate_actions.csv",
    )
    lines_by_name = {name: [headers] for name in names}
    for current in sorted(trusted_us_exchange_sessions(date(2020, 1, 1), date(2026, 9, 30))):
        if current:
            session_close = trusted_session_close_utc(current)
            event_start = trusted_event_start_utc(current)
            for name in names:
                availability = event_start if name in {"security_master.csv", "corporate_actions.csv"} else session_close
                lines_by_name[name].append(
                    f"{current.isoformat()},{availability.isoformat()},SPY,SPY,equity,1,2,0.5,1.5,100,1,2,1.5,2026-09-30,1,call,100,13:30,20:00,dividend\n"
                )
    for name, lines in lines_by_name.items():
        (root / name).write_text("".join(lines), encoding="utf-8")


def _registration(root):
    return DatasetRegistration(
        name="fixture",
        root_path=str(root),
        provider="official_lean_fixture",
        license="fixture-license",
        provenance="checked-in official LEAN sample fixture",
        symbols=["SPY"],
        declared_start=date(2020, 1, 1),
        declared_end=date(2026, 9, 30),
    )


def test_dataset_inspection_is_allowlisted_and_strict(tmp_path, session):
    allowed = tmp_path / "data"
    root = allowed / "fixture"
    root.mkdir(parents=True)
    _write_dataset(root)
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        engine_image_digest="sha256:" + "a" * 64,
    )
    summary = service.register_dataset(_registration(root))
    report = service.validate_dataset(summary.id)
    assert report.valid is True, report.errors + report.coverage_gaps
    assert summary.manifest_hash
    with pytest.raises(DatasetSecurityError):
        service.inspector.resolve_dataset_root(str(tmp_path / "outside"))
    outside = tmp_path / "outside-data"
    outside.mkdir()
    (outside / "underlying_bars.csv").write_text("date,symbol,value\n2020-01-01,SPY,1\n", encoding="utf-8")
    nested = root / "nested-link"
    try:
        nested.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("nested symlink creation is unavailable on this Windows host")
    _manifest, _hash, _warnings, errors = service.inspector.inspect(_registration(root), root=root)
    assert any("reparse_point_not_allowed" in error for error in errors)


def test_two_endpoint_coverage_is_blocked(tmp_path, session):
    allowed = tmp_path / "data"
    root = allowed / "sparse"
    root.mkdir(parents=True)
    headers = "date,available_at,symbol,underlying,security_type,open,high,low,close,volume,bid,ask,price,expiration,strike,right,open_interest,session_open,session_close,action\n"
    sparse = headers + "2020-01-01,2020-01-01T21:00:00+00:00,SPY,SPY,equity,1,1,1,1,1,1,1,1,2026-09-30,1,call,1,13:30,20:00,dividend\n2026-09-30,2026-09-30T21:00:00+00:00,SPY,SPY,equity,1,1,1,1,1,1,1,1,2026-09-30,1,call,1,13:30,20:00,dividend\n"
    for name in (
        "security_master.csv",
        "underlying_bars.csv",
        "option_quotes.csv",
        "option_trades.csv",
        "open_interest.csv",
        "calendar.csv",
        "corporate_actions.csv",
    ):
        (root / name).write_text(sparse, encoding="utf-8")
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        engine_image_digest="sha256:" + "a" * 64,
    )
    summary = service.register_dataset(_registration(root))
    report = service.validate_dataset(summary.id)
    assert report.valid is False
    assert report.coverage_gaps


def test_numeric_and_point_in_time_validation_checks_every_row(tmp_path):
    path = tmp_path / "underlying_bars.csv"
    path.write_text(
        "symbol,date,available_at,open,high,low,close,volume\n"
        "SPY,2024-01-02,2024-01-02T21:00:00Z,480,481,479,480.5,100\n"
        "SPY,2024-01-03,,NaN,481,479,480.5,100\n"
        "SPY,2024-01-04,not-a-time,480,479,481,480.5,-1\n",
        encoding="utf-8",
    )
    inspection = inspect_lean_file(path, DatasetCategory.UNDERLYING_BARS)
    assert inspection.data_file.schema_valid is False
    assert inspection.data_file.invalid_rows == 2
    assert inspection.data_file.row_error_count >= 3
    assert any("missing_or_invalid_available_at" in error for error in inspection.data_file.schema_errors)
    assert any("invalid_nonnegative_volume" in error for error in inspection.data_file.schema_errors)


def test_availability_after_bar_end_is_blocked(tmp_path):
    path = tmp_path / "underlying_bars.csv"
    path.write_text(
        "symbol,date,available_at,open,high,low,close,volume\n"
        "SPY,2024-01-02,2030-01-02T21:00:00Z,480,481,479,480.5,100\n",
        encoding="utf-8",
    )
    inspection = inspect_lean_file(path, DatasetCategory.UNDERLYING_BARS)
    assert inspection.data_file.schema_valid is False
    assert any("availability_after_bar_end" in error for error in inspection.data_file.schema_errors)


def test_event_availability_uses_effective_date_midnight_causal_cutoff(tmp_path):
    security = tmp_path / "security_master.csv"
    security.write_text(
        "symbol,security_type,effective_start,available_at\n"
        "SPY,equity,2024-01-02,2024-01-02T10:00:00-05:00\n",
        encoding="utf-8",
    )
    corporate = tmp_path / "corporate_actions.csv"
    corporate.write_text(
        "symbol,date,action,available_at\n"
        "SPY,2024-01-02,dividend,2024-01-02T10:00:00-05:00\n",
        encoding="utf-8",
    )
    security_result = inspect_lean_file(security, DatasetCategory.SECURITY_MASTER)
    corporate_result = inspect_lean_file(corporate, DatasetCategory.CORPORATE_ACTIONS)
    assert security_result.data_file.schema_valid is False
    assert corporate_result.data_file.schema_valid is False
    assert all("availability_after_bar_end" in error for error in security_result.data_file.schema_errors if "availability" in error)
    assert all("availability_after_bar_end" in error for error in corporate_result.data_file.schema_errors if "availability" in error)


def test_lean_staging_uses_the_same_causal_cutoff():
    accepted, rejected = _causal_rows(
        [
            {
                "symbol": "SPY",
                "date": "2024-01-02",
                "available_at": "2024-01-02T23:00:00Z",
                "close": "480",
            }
        ],
        "underlying_bars",
    )
    assert accepted == []
    assert rejected == 1


def test_supplied_sparse_calendar_cannot_define_expected_sessions(tmp_path):
    path = tmp_path / "calendar.csv"
    path.write_text(
        "date,session_open,session_close\n"
        "2024-01-02,09:30,16:00\n"
        "2024-01-05,09:30,16:00\n",
        encoding="utf-8",
    )
    inspection = inspect_lean_file(path, DatasetCategory.CALENDARS)
    gaps = validate_session_coverage(
        [inspection],
        requested_start=date(2024, 1, 1),
        requested_end=date(2024, 1, 5),
        symbols=["SPY"],
    )
    assert any("calendar_missing_trusted_session" in gap for gap in gaps)
    assert trusted_us_exchange_sessions(date(2024, 1, 1), date(2024, 1, 5)) == {
        date(2024, 1, 2),
        date(2024, 1, 3),
        date(2024, 1, 4),
        date(2024, 1, 5),
    }


def test_trusted_calendar_handles_new_year_saturday_and_carter_closure():
    assert date(2021, 12, 31) in trusted_us_exchange_sessions(date(2021, 12, 31), date(2022, 1, 3))
    assert date(2022, 1, 3) in trusted_us_exchange_sessions(date(2021, 12, 31), date(2022, 1, 3))
    sessions = trusted_us_exchange_sessions(date(2025, 1, 1), date(2025, 1, 10))
    assert date(2025, 1, 9) not in sessions
    assert date(2025, 1, 8) in sessions and date(2025, 1, 10) in sessions


def test_run_snapshot_is_stable_after_source_mutation(tmp_path, session):
    allowed = tmp_path / "data"
    root = allowed / "fixture"
    root.mkdir(parents=True)
    _write_dataset(root)
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        engine_image_digest="sha256:" + "a" * 64,
    )
    registration = _registration(root)
    manifest, data_hash, _warnings, errors = service.inspector.inspect(registration, root=root)
    assert not errors
    snapshot, snapshot_hash = service._stage_data_snapshot(
        dataset_root=root,
        registration=registration,
        manifest=manifest,
        expected_manifest_hash=manifest_semantic_hash(manifest),
        expected_data_hash=data_hash,
        run_id="snapshot-test",
    )
    original_snapshot = (snapshot / "underlying_bars.csv").read_bytes()
    with (root / "underlying_bars.csv").open("ab") as handle:
        handle.write(b"source mutation")
    assert (snapshot / "underlying_bars.csv").read_bytes() == original_snapshot
    assert snapshot_hash == data_hash


def test_worker_invalidates_result_when_run_snapshot_is_mutated(session, tmp_path):
    class MutatingLauncher:
        def process_identity(self, context):
            return {"kind": "docker", "run_id": context.run_id}

        def run(self, context):
            with (context.dataset_path / "underlying_bars.csv").open("ab") as handle:
                handle.write(b"mutation")
            return {"metrics": {}, "trades": [], "equity_curve": [], "warnings": []}

        def cancel(self, run_id):
            return True

    allowed = tmp_path / "data"
    root = allowed / "fixture"
    root.mkdir(parents=True)
    _write_dataset(root)
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        launcher=MutatingLauncher(),
        engine_image_digest="sha256:" + "a" * 64,
    )
    dataset = service.register_dataset(_registration(root).model_copy(update={"provider": "verified_vendor"}))
    run = service.create_backtest(
        BacktestCreate(
            dataset_id=dataset.id,
            strategy=BacktestStrategy.BULL_PUT,
            symbols=["SPY"],
            formal=False,
            fee_model=FeeModel(name="fees"),
            slippage_model=SlippageModel(name="slippage"),
        )
    )
    service._run_in_worker(run.id)
    assert service.get_backtest(run.id).state is BacktestState.BLOCKED_DATA


def test_freeze_configuration_hash_binds_initial_cash_and_lifecycle_inputs():
    base = {
        "strategy": "bull_put",
        "symbols": ["SPY"],
        "initial_cash": "100000",
        "parameters": {"width": 5},
        "fee_model": {"name": "fees"},
        "slippage_model": {"name": "slippage"},
        "lifecycle_model": {"name": "expiry"},
        "initial_stock_lots": [],
        "algorithm": {"source_sha256": "a" * 64},
    }
    assert _configuration_hash(base) != _configuration_hash({**base, "initial_cash": "100001"})
    assert _configuration_hash(base) != _configuration_hash({**base, "lifecycle_model": {"name": "assignment"}})


def test_formal_full_range_cannot_bypass_holdout_freeze():
    with pytest.raises(ValueError, match="freeze_source_run_id"):
        BacktestCreate(
            dataset_id="dataset",
            strategy=BacktestStrategy.BULL_PUT,
            symbols=["SPY"],
            fee_model=FeeModel(name="fees"),
            slippage_model=SlippageModel(name="slippage"),
        )


def test_dispatcher_stop_requests_cancel_for_active_run(session, tmp_path):
    class Launcher:
        cancelled: list[str] = []

        def cancel(self, run_id):
            self.cancelled.append(run_id)
            return True

    repo = SQLAlchemyBacktestRepository(session)
    dataset = repo.register_dataset(
        _registration(tmp_path / "unused").model_copy(update={"root_path": str(tmp_path / "unused")})
    )
    request = BacktestCreate(
        dataset_id=dataset.id,
        strategy=BacktestStrategy.BULL_PUT,
        symbols=["SPY"],
        fee_model=FeeModel(name="fees"),
        slippage_model=SlippageModel(name="slippage"),
        formal=False,
    )
    run, _ = repo.create_run(
        request,
        data_hash="d" * 64,
        run_manifest={"period_segment": "composite", "configuration_hash": "c" * 64},
        code_version="code",
        engine_version="engine",
        engine_image_digest="sha256:" + "a" * 64,
    )
    launcher = Launcher()
    dispatcher = BacktestDispatcher(
        session_factory=lambda: session,
        allowed_data_root=tmp_path,
        result_root=tmp_path / "results",
        launcher=launcher,
    )
    with dispatcher._active_lock:
        dispatcher._active_run_id = run.id
    asyncio.run(dispatcher.stop())
    assert launcher.cancelled == [run.id]


def test_heartbeat_loss_interrupt_is_ownership_cas(session, tmp_path):
    class Launcher:
        def __init__(self):
            self.cancelled: list[str] = []

        def cancel(self, run_id):
            self.cancelled.append(run_id)
            return True

    repo = SQLAlchemyBacktestRepository(session)
    dataset = repo.register_dataset(
        _registration(tmp_path / "unused").model_copy(update={"root_path": str(tmp_path / "unused")})
    )
    request = BacktestCreate(
        dataset_id=dataset.id,
        strategy=BacktestStrategy.BULL_PUT,
        symbols=["SPY"],
        fee_model=FeeModel(name="fees"),
        slippage_model=SlippageModel(name="slippage"),
        formal=False,
    )
    run, _ = repo.create_run(
        request,
        data_hash="d" * 64,
        run_manifest={"period_segment": "composite", "configuration_hash": "c" * 64},
        code_version="code",
        engine_version="engine",
        engine_image_digest="sha256:" + "a" * 64,
    )
    repo.mark_running(
        run.id,
        owner="owner-a",
        process_identity={"kind": "docker", "run_id": run.id},
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    launcher = Launcher()
    service = BacktestingService(
        repository=repo,
        allowed_data_root=tmp_path,
        result_root=tmp_path / "results",
        launcher=launcher,
        engine_image_digest="sha256:" + "a" * 64,
    )
    service._interrupt_after_heartbeat_loss(repo, run.id, "owner-a")
    assert launcher.cancelled == [run.id]
    assert repo.get_run(run.id).state is BacktestState.INTERRUPTED
    repo.get_run_record(run.id).state = BacktestState.RUNNING.value
    repo.get_run_record(run.id).lease_owner = "owner-b"
    session.commit()
    service._interrupt_after_heartbeat_loss(repo, run.id, "owner-a")
    assert repo.get_run(run.id).lease_owner == "owner-b"


def test_registered_identity_is_immutable_and_drift_blocks_new_run(tmp_path, session):
    allowed = tmp_path / "data"
    root = allowed / "fixture"
    root.mkdir(parents=True)
    _write_dataset(root)
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        engine_image_digest="sha256:" + "a" * 64,
    )
    dataset = service.register_dataset(_registration(root))
    request = BacktestCreate(
        dataset_id=dataset.id,
        strategy=BacktestStrategy.BULL_PUT,
        symbols=["SPY"],
        fee_model=FeeModel(name="fees"),
        slippage_model=SlippageModel(name="slippage"),
        formal=False,
        idempotency_key="before-drift",
    )
    original = service.create_backtest(request)
    original_hash = original.data_hash
    with (root / "underlying_bars.csv").open("a", encoding="utf-8") as handle:
        handle.write("2026-09-30,2026-09-30T21:00:00+00:00,SPY,SPY,equity,1,1,1,1,1,1,1,1,2026-09-30,1,call,1,13:30,20:00,dividend\n")
    with pytest.raises(BacktestDatasetConflictError):
        service.register_dataset(_registration(root))
    blocked = service.create_backtest(
        request.model_copy(update={"idempotency_key": "after-drift"})
    )
    assert blocked.state is BacktestState.BLOCKED_DATA
    assert original.data_hash == original_hash
    assert original.run_manifest["data_hash"] == original_hash


def test_blocked_data_is_persisted_and_does_not_start(session, tmp_path):
    allowed = tmp_path / "data"
    root = allowed / "incomplete"
    root.mkdir(parents=True)
    (root / "underlying_bars.csv").write_text("date,symbol,value\n2020-01-01,SPY,1\n", encoding="utf-8")
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        engine_image_digest="sha256:" + "a" * 64,
    )
    summary = service.register_dataset(_registration(root))
    request = BacktestCreate(
        dataset_id=summary.id,
        strategy=BacktestStrategy.BULL_PUT,
        symbols=["SPY"],
        fee_model=FeeModel(name="explicit-zero-cost-fixture"),
        slippage_model=SlippageModel(name="zero-slippage-fixture"),
        formal=False,
    )
    run = service.create_backtest(request)
    assert run.state is BacktestState.BLOCKED_DATA
    assert run.run_manifest["ledger_writes"] is False


def test_idempotency_and_global_lease(session, tmp_path):
    allowed = tmp_path / "data"
    root = allowed / "fixture"
    root.mkdir(parents=True)
    _write_dataset(root)
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        engine_image_digest="sha256:" + "a" * 64,
    )
    summary = service.register_dataset(_registration(root))
    request = BacktestCreate(
        dataset_id=summary.id,
        strategy=BacktestStrategy.BULL_PUT,
        symbols=["SPY"],
        fee_model=FeeModel(name="explicit-zero-cost-fixture"),
        slippage_model=SlippageModel(name="zero-slippage-fixture"),
        formal=False,
        idempotency_key="same-request",
    )
    first = service.create_backtest(request)
    second = service.create_backtest(request)
    assert first.id == second.id
    assert second.idempotent_replayed is True
    repo = SQLAlchemyBacktestRepository(session)
    assert repo.acquire_global_lease(owner="one", run_id=first.id) is True
    assert repo.acquire_global_lease(owner="two", run_id="other") is False
    assert repo.release_global_lease(owner="one", run_id=first.id) is True


def test_simulator_records_fees_slippage_partial_legs_and_semantic_hash():
    result = simulate_events(
        run_id="run-1",
        strategy=BacktestStrategy.BULL_PUT,
        events=[
            {
                "timestamp": "2024-01-02T15:00:00+00:00",
                "symbol": "SPY",
                "underlying_price": "480",
                "short_put_strike": "470",
                "long_put_strike": "465",
                "expiration": "2024-01-19",
                "fills": {"leg-0": {"quantity": 1, "price": "2.00"}},
            }
        ],
        initial_cash=Decimal("100000"),
        fee_model=FeeModel(name="commission", commission_per_contract=Decimal("0.65")),
        slippage_model=SlippageModel(name="bps", basis_points=Decimal("5")),
        lifecycle_model=LifecycleModel(),
    )
    assert result.metrics["trade_count"] == 1
    assert result.trades[0].status == "partial"
    assert result.trades[0].fees > 0
    assert len(result.semantic_hash) == 64


def test_simulator_rejects_future_information():
    with pytest.raises(ValueError, match="after event timestamp"):
        simulate_events(
            run_id="run-2",
            strategy=BacktestStrategy.COVERED_CALL,
            events=[
                {
                    "timestamp": "2024-01-02T15:00:00+00:00",
                    "available_at": "2024-01-02T15:01:00+00:00",
                    "symbol": "SPY",
                    "shares": 100,
                    "call_strike": "500",
                    "expiration": "2024-01-19",
                }
            ],
            initial_cash=Decimal("100000"),
            fee_model=FeeModel(name="fees"),
            slippage_model=SlippageModel(name="slippage"),
            lifecycle_model=LifecycleModel(),
        )


def test_lean_command_is_networkless_readonly_and_pinned(tmp_path):
    try:
        from stocks_tool.adapters.backtesting.lean import (
            LeanExecutionContext,
            LeanLauncher,
            LeanLauncherConfig,
        )
    except (ImportError, ModuleNotFoundError):
        pytest.skip("LEAN runtime adapter is supplied by the runtime integration slice")
    if not (LeanLauncherConfig().runtime_path / "algorithms.py").is_file():
        pytest.skip("checked-in LEAN algorithm runtime is not available yet")
    root = tmp_path / "data"
    root.mkdir()
    config = tmp_path / "config.json"
    config.write_text("{}", encoding="utf-8")
    launcher = LeanLauncher(LeanLauncherConfig(image_digest="sha256:" + "b" * 64))
    command = launcher.build_command(
        LeanExecutionContext(
            run_id="run-1",
            dataset_path=root,
            config_path=config,
            result_path=tmp_path / "results",
            image_digest="sha256:" + "b" * 64,
        )
    )
    assert "--network" in command and command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--env-file" not in command
    assert any("@sha256:" in value for value in command)


def test_worker_persists_isolated_result_without_ledger_writes(session, tmp_path):
    class FakeLauncher:
        def process_identity(self, context):
            return {"kind": "docker", "run_id": context.run_id}

        def run(self, context):
            (context.result_path / "backtest-result.json").write_text(
                '{"metrics":{"trade_count":0},"trades":[],"equity_curve":[],"warnings":[]}',
                encoding="utf-8",
            )
            return {"metrics": {"trade_count": 0}, "trades": [], "equity_curve": [], "warnings": []}

        def cancel(self, run_id):
            return True

    allowed = tmp_path / "data"
    root = allowed / "fixture"
    root.mkdir(parents=True)
    _write_dataset(root)
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        launcher=FakeLauncher(),
        engine_image_digest="sha256:" + "a" * 64,
    )
    dataset = service.register_dataset(_registration(root))
    run = service.create_backtest(
        BacktestCreate(
            dataset_id=dataset.id,
            strategy=BacktestStrategy.BULL_PUT,
            symbols=["SPY"],
            fee_model=FeeModel(name="fees"),
            slippage_model=SlippageModel(name="slippage"),
            formal=False,
        )
    )
    service._run_in_worker(run.id)
    final = service.get_backtest(run.id)
    assert final.state is BacktestState.SUCCEEDED
    assert final.result is not None
    assert final.run_manifest["broker_calls"] is False
    assert final.run_manifest["ledger_writes"] is False


def test_long_lived_dispatcher_uses_a_fresh_worker_session(tmp_path):
    class FakeLauncher:
        def process_identity(self, context):
            return {"kind": "docker", "run_id": context.run_id}

        def run(self, context):
            return {"metrics": {"trade_count": 0}, "trades": [], "equity_curve": [], "warnings": []}

        def cancel(self, run_id):
            return True

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'dispatcher.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    allowed = tmp_path / "data"
    root = allowed / "fixture"
    root.mkdir(parents=True)
    _write_dataset(root)
    with factory() as create_session:
        creator = BacktestingService(
            repository=SQLAlchemyBacktestRepository(create_session),
            allowed_data_root=allowed,
            result_root=tmp_path / "results",
            launcher=FakeLauncher(),
            session_factory=factory,
            engine_image_digest="sha256:" + "a" * 64,
        )
        dataset = creator.register_dataset(_registration(root))
        queued = creator.create_backtest(
            BacktestCreate(
                dataset_id=dataset.id,
                strategy=BacktestStrategy.BULL_PUT,
                symbols=["SPY"],
                fee_model=FeeModel(name="fees"),
                slippage_model=SlippageModel(name="slippage"),
                formal=False,
            )
        )
    dispatcher = BacktestDispatcher(
        session_factory=factory,
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        launcher=FakeLauncher(),
        engine_image_digest="sha256:" + "a" * 64,
        poll_interval_seconds=1,
        lease_ttl_seconds=30,
    )
    assert dispatcher.tick() == queued.id
    with factory() as read_session:
        final = SQLAlchemyBacktestRepository(read_session).get_run(queued.id)
    assert final is not None and final.state is BacktestState.SUCCEEDED


def test_formal_holdout_requires_matching_completed_validation_freeze(session, tmp_path):
    class FakeLauncher:
        def process_identity(self, context):
            return {"kind": "docker", "run_id": context.run_id}

        def run(self, context):
            return {"metrics": {"trade_count": 0}, "trades": [], "equity_curve": [], "warnings": []}

        def cancel(self, run_id):
            return True

    allowed = tmp_path / "data"
    root = allowed / "verified"
    root.mkdir(parents=True)
    _write_dataset(root)
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=allowed,
        result_root=tmp_path / "results",
        launcher=FakeLauncher(),
        engine_image_digest="sha256:" + "a" * 64,
    )
    registration = _registration(root).model_copy(update={"name": "verified", "provider": "verified_vendor"})
    dataset = service.register_dataset(registration)
    validation = service.create_backtest(
        BacktestCreate(
            dataset_id=dataset.id,
            strategy=BacktestStrategy.BULL_PUT,
            symbols=["SPY"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            fee_model=FeeModel(name="fees"),
            slippage_model=SlippageModel(name="slippage"),
            period_segment="validation",
        )
    )
    service._run_in_worker(validation.id)
    assert service.get_backtest(validation.id).state is BacktestState.SUCCEEDED
    holdout = service.create_backtest(
        BacktestCreate(
            dataset_id=dataset.id,
            strategy=BacktestStrategy.BULL_PUT,
            symbols=["SPY"],
            start_date=date(2025, 1, 1),
            end_date=date(2026, 9, 30),
            fee_model=FeeModel(name="fees"),
            slippage_model=SlippageModel(name="slippage"),
            period_segment="holdout",
            freeze_source_run_id=validation.id,
        )
    )
    assert holdout.state is BacktestState.QUEUED
    with pytest.raises(BacktestFreezeError, match="frozen validation run"):
        service.create_backtest(
            BacktestCreate(
                dataset_id=dataset.id,
                strategy=BacktestStrategy.BULL_PUT,
                symbols=["SPY"],
                start_date=date(2025, 1, 1),
                end_date=date(2026, 9, 30),
                parameters={"changed": True},
                fee_model=FeeModel(name="fees"),
                slippage_model=SlippageModel(name="slippage"),
                period_segment="holdout",
                freeze_source_run_id=validation.id,
            )
        )


def test_recovery_inspects_owned_container_before_interrupting_expired_run(session, tmp_path):
    class InspectingLauncher:
        def __init__(self):
            self.running = True

        def inspect_owned_container(self, run_id):
            return {"running": self.running, "id": "container-1"} if self.running else None

    repo = SQLAlchemyBacktestRepository(session)
    dataset = repo.register_dataset(
        _registration(tmp_path / "unused").model_copy(update={"root_path": str(tmp_path / "unused")})
    )
    request = BacktestCreate(
        dataset_id=dataset.id,
        strategy=BacktestStrategy.BULL_PUT,
        symbols=["SPY"],
        fee_model=FeeModel(name="fees"),
        slippage_model=SlippageModel(name="slippage"),
        formal=False,
    )
    run, _ = repo.create_run(
        request,
        data_hash="d" * 64,
        run_manifest={"period_segment": "composite", "configuration_hash": "c" * 64},
        code_version="code",
        engine_version="engine",
        engine_image_digest="sha256:" + "a" * 64,
    )
    now = datetime.now(timezone.utc)
    repo.acquire_global_lease(owner="old-owner", run_id=run.id, now=now - timedelta(seconds=20), ttl_seconds=1)
    repo.mark_running(
        run.id,
        owner="old-owner",
        process_identity={"kind": "docker", "run_id": run.id},
        lease_expires_at=now - timedelta(seconds=10),
    )
    launcher = InspectingLauncher()
    service = BacktestingService(
        repository=repo,
        allowed_data_root=tmp_path,
        result_root=tmp_path / "results",
        launcher=launcher,
        engine_image_digest="sha256:" + "a" * 64,
    )
    assert service.recover_stale_runs() == []
    assert repo.get_run(run.id).state is BacktestState.RUNNING
    record = session.get(BacktestRunRecord, run.id)
    lease = session.get(BacktestLeaseRecord, "global")
    record.lease_expires_at = now - timedelta(seconds=10)
    lease.expires_at = now - timedelta(seconds=10)
    session.commit()
    launcher.running = False
    recovered = service.recover_stale_runs()
    assert [item.id for item in recovered] == [run.id]
    assert repo.get_run(run.id).state is BacktestState.INTERRUPTED


def test_global_lease_heartbeat_prevents_second_owner_after_original_ttl(session):
    repo = SQLAlchemyBacktestRepository(session)
    now = datetime.now(timezone.utc)
    assert repo.acquire_global_lease(owner="one", run_id="run-one", now=now, ttl_seconds=1)
    assert repo.renew_global_lease(owner="one", run_id="run-one", now=now + timedelta(milliseconds=800), ttl_seconds=1)
    assert repo.acquire_global_lease(owner="two", run_id="run-two", now=now + timedelta(seconds=1.2), ttl_seconds=1) is False

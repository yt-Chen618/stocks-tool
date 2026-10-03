"""Operator CLI for the local-only backtesting subsystem.

The command never downloads data or calls Longbridge.  A missing or
insufficient local data set is reported as BLOCKED_DATA rather than being
silently replaced with synthetic historical results.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.adapters.backtesting.dataset import DatasetInspection
from stocks_tool.adapters.backtesting.engine_lock import LEAN_ENGINE_IMAGE_DIGEST
from stocks_tool.domain.backtesting import DatasetRegistration


def main() -> int:
    parser = argparse.ArgumentParser(description="Run offline stocks-tool backtest checks")
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="check local LEAN and data prerequisites")
    doctor.add_argument("--data-root", default=os.environ.get("BACKTEST_DATA_ROOT", "data/backtesting"))
    doctor.add_argument("--require-docker", action="store_true")
    sample = subparsers.add_parser("sample", help="inspect the explicitly provisioned official LEAN fixture")
    sample.add_argument("--data-root", default=os.environ.get("BACKTEST_DATA_ROOT", "data/backtesting"))
    register = subparsers.add_parser("register", help="register one local dataset in PostgreSQL")
    register.add_argument("request", type=Path, help="JSON DatasetRegistration payload")
    validate = subparsers.add_parser("validate", help="validate one registered dataset")
    validate.add_argument("dataset_id")
    validate.add_argument("--strategy", default=None)
    validate.add_argument("--start-date", default="2020-01-01")
    validate.add_argument("--end-date", default="2026-09-30")
    run = subparsers.add_parser("run", help="run and wait for a backtest, or explicitly queue it")
    run.add_argument("request", type=Path, help="JSON BacktestCreate payload")
    run.add_argument("--queue", action="store_true", help="persist queued state without waiting for execution")
    run.add_argument("--timeout-seconds", type=float, default=3600.0, help="synchronous wait limit")
    args = parser.parse_args()
    if args.command == "doctor":
        return _doctor(Path(args.data_root), args.require_docker)
    if args.command == "sample":
        return _sample(Path(args.data_root))
    if args.command == "register":
        return _register(args.request)
    if args.command == "validate":
        return _validate(args)
    if args.command == "run":
        return _run(args.request, queue=args.queue, timeout_seconds=args.timeout_seconds)
    return 2


def _doctor(data_root: Path, require_docker: bool) -> int:
    digest = os.environ.get("LEAN_IMAGE_DIGEST", LEAN_ENGINE_IMAGE_DIGEST)
    payload = {
        "command": "doctor",
        "status": "ok",
        "network": "disabled_by_launcher",
        "docker": shutil.which("docker") is not None,
        "data_root": str(data_root.resolve()),
        "data_root_exists": data_root.is_dir(),
        "image_digest_configured": bool(digest and digest.startswith("sha256:") and len(digest) == 71),
        "broker_calls": False,
        "ledger_writes": False,
    }
    if require_docker and not payload["docker"]:
        payload["status"] = "blocked_runtime"
    if not payload["data_root_exists"]:
        payload["status"] = "blocked_data"
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "ok" else 3


def _sample(data_root: Path) -> int:
    fixture = data_root / "official-lean-sample"
    if fixture.is_dir():
        inspector = DatasetInspection(allowed_root=data_root)
        registration = DatasetRegistration(
            name="official-lean-sample",
            root_path=str(fixture),
            provider="official_lean_fixture",
            license="official repository sample license; inspect before formal use",
            provenance="operator-provisioned official LEAN repository fixture",
            symbols=["SPY"],
        )
        manifest, data_hash, warnings, errors = inspector.inspect(registration, root=fixture)
        payload = {
            "command": "sample",
            "fixture": str(fixture.resolve()),
            "status": "ready_for_offline_smoke" if not errors else "blocked_data",
            "historical_success_claimed": False,
            "manifest": manifest.model_dump(mode="json"),
            "data_hash": data_hash,
            "warnings": warnings,
            "errors": errors,
            "next_step": "Run the pinned LEAN launcher smoke; do not interpret fixture output as historical performance.",
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if not errors else 3
    payload = {
        "command": "sample",
        "fixture": str(fixture.resolve()),
        "status": "blocked_data",
        "reason": "official LEAN fixture data is not provisioned in this checkout",
        "historical_success_claimed": False,
        "network": "disabled",
        "next_step": "Provision a reviewed official LEAN sample under the dedicated data root, then rerun validation.",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 3


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _service():
    from stocks_tool.db.session import get_session_factory
    from stocks_tool.repositories.sqlalchemy_backtest_repository import SQLAlchemyBacktestRepository
    from stocks_tool.application.services.backtesting import BacktestingService

    session = get_session_factory()()
    service = BacktestingService(
        repository=SQLAlchemyBacktestRepository(session),
        allowed_data_root=os.environ.get("BACKTEST_DATA_ROOT", "data/backtesting"),
        result_root=os.environ.get("BACKTEST_RESULT_ROOT", "artifacts/backtests/results"),
        engine_image_digest=os.environ.get("LEAN_IMAGE_DIGEST", LEAN_ENGINE_IMAGE_DIGEST),
        session_factory=get_session_factory(),
    )
    return service, session


def _register(path: Path) -> int:
    service, session = _service()
    try:
        summary = service.register_dataset(DatasetRegistration.model_validate(_read_json(path)))
        print(summary.model_dump_json(indent=2))
        return 0
    finally:
        session.close()


def _validate(args: argparse.Namespace) -> int:
    from datetime import date

    service, session = _service()
    try:
        report = service.validate_dataset(
            args.dataset_id,
            strategy=args.strategy,
            start_date=date.fromisoformat(args.start_date),
            end_date=date.fromisoformat(args.end_date),
        )
        print(report.model_dump_json(indent=2))
        return 0 if report.valid else 3
    finally:
        session.close()


def _run(path: Path, *, queue: bool, timeout_seconds: float) -> int:
    from stocks_tool.domain.backtesting import BacktestCreate
    from stocks_tool.repositories.sqlalchemy_backtest_repository import SQLAlchemyBacktestRepository

    service, session = _service()
    try:
        run = service.create_backtest(BacktestCreate.model_validate(_read_json(path)))
        if run.state.value not in {"queued", "running"}:
            print(run.model_dump_json(indent=2))
            return 0 if run.state.value == "succeeded" else 3
        if queue:
            print(run.model_dump_json(indent=2))
            return 0
        if not service.dispatch(run.id):
            print(service.get_backtest(run.id).model_dump_json(indent=2))
            return 3
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        while time.monotonic() < deadline:
            # Poll with a fresh session so the synchronous CLI never shares
            # the request session with the worker thread.
            with service.session_factory() as polling_session:
                current = SQLAlchemyBacktestRepository(polling_session).get_run(run.id)
            if current is None:
                print(json.dumps({"run_id": run.id, "status": "missing_after_dispatch"}, indent=2))
                return 3
            if current.state.value in {"succeeded", "failed", "cancelled", "interrupted", "blocked_data"}:
                print(current.model_dump_json(indent=2))
                return 0 if current.state.value == "succeeded" else 3
            time.sleep(0.25)
        service.cancel_backtest(run.id)
        with service.session_factory() as polling_session:
            timed_out = SQLAlchemyBacktestRepository(polling_session).get_run(run.id)
        if timed_out is None:
            return 3
        print(timed_out.model_dump_json(indent=2))
        return 3
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())

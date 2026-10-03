"""Application service for local-only data validation and LEAN runs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from stocks_tool.adapters.backtesting.dataset import DatasetInspection, DatasetSecurityError
from stocks_tool.adapters.backtesting.lean_algorithms import algorithm_manifest
from stocks_tool.adapters.backtesting.lean_data import (
    build_canonical_manifest,
    inspect_lean_file,
    trusted_us_exchange_sessions,
    validate_session_coverage,
)
from stocks_tool.adapters.backtesting.lean import (
    LeanExecutionContext,
    LeanExecutionError,
    LeanLauncher,
)
from stocks_tool.adapters.backtesting.engine_lock import (
    LEAN_ENGINE_IMAGE_DIGEST,
    LEAN_ENGINE_VERSION,
    is_full_digest,
)
from stocks_tool.domain.backtesting import (
    BACKTEST_DEFAULT_END,
    BACKTEST_DEFAULT_START,
    BACKTEST_SYMBOL_ALLOWLIST,
    BacktestCompareRequest,
    BacktestComparison,
    BacktestCreate,
    BacktestResult,
    BacktestRun,
    BacktestState,
    DatasetCategory,
    DatasetManifest,
    DatasetRegistration,
    DatasetStatus,
    DatasetSummary,
    DatasetValidationReport,
    manifest_semantic_hash,
    result_semantic_payload,
    semantic_hash,
)
from stocks_tool.repositories.sqlalchemy_backtest_repository import (
    BacktestDatasetConflictError,
    SQLAlchemyBacktestRepository,
)


logger = logging.getLogger(__name__)


class BacktestError(RuntimeError):
    pass


class BacktestNotFoundError(BacktestError):
    pass


class DatasetNotFoundError(BacktestError):
    pass


class BacktestDataBlockedError(BacktestError):
    pass


class BacktestFreezeError(BacktestError):
    """A formal holdout run does not match a completed validation freeze."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class BacktestingService:
    """Coordinates durable state, a single worker lease, and an offline runner."""

    def __init__(
        self,
        *,
        repository: SQLAlchemyBacktestRepository,
        allowed_data_root: str | Path,
        result_root: str | Path,
        launcher: Any | None = None,
        session_factory: Callable[[], Any] | None = None,
        engine_image_digest: str | None = LEAN_ENGINE_IMAGE_DIGEST,
        engine_version: str = LEAN_ENGINE_VERSION,
        source_root: str | Path | None = None,
        auto_start: bool = False,
        lease_ttl_seconds: int = 300,
    ) -> None:
        self.repository = repository
        self.inspector = DatasetInspection(allowed_root=Path(allowed_data_root))
        self.result_root = Path(result_root).resolve()
        self.result_root.mkdir(parents=True, exist_ok=True)
        self.launcher = launcher or LeanLauncher()
        self.session_factory = session_factory
        self.engine_image_digest = engine_image_digest
        self.engine_version = engine_version
        # This file lives under ``application/services``; the source package
        # root is two parents up so the hash includes domain and adapters.
        self.source_root = Path(source_root).resolve() if source_root else Path(__file__).resolve().parents[2]
        self.auto_start = auto_start
        self.lease_ttl_seconds = lease_ttl_seconds
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stocks-backtest")
        self._futures: dict[str, Future[Any]] = {}
        self._lock = threading.Lock()

    # Dataset lifecycle --------------------------------------------------
    def register_dataset(self, registration: DatasetRegistration) -> DatasetSummary:
        root = self.inspector.resolve_dataset_root(registration.root_path)
        normalized = registration.model_copy(update={"root_path": str(root)})
        manifest, data_hash, _warnings, errors = self.inspector.inspect(normalized, root=root)
        status = DatasetStatus.REGISTERED if not errors else DatasetStatus.BLOCKED_DATA
        return self.repository.register_dataset(
            normalized,
            manifest=manifest.model_dump(mode="json"),
            manifest_hash=manifest_semantic_hash(manifest),
            data_hash=data_hash,
            status=status,
        )

    def validate_dataset(
        self,
        dataset_id: str,
        *,
        strategy: str | None = None,
        start_date: date = BACKTEST_DEFAULT_START,
        end_date: date = BACKTEST_DEFAULT_END,
    ) -> DatasetValidationReport:
        record = self.repository.get_dataset_record(dataset_id)
        if record is None:
            raise DatasetNotFoundError(dataset_id)
        registration = DatasetRegistration(
            id=record.id,
            name=record.name,
            root_path=record.root_path,
            provider=record.provider,
            license=record.license,
            provenance=record.provenance,
            symbols=list(record.symbols or []),
            declared_start=record.declared_start,
            declared_end=record.declared_end,
        )
        root = self.inspector.resolve_dataset_root(record.root_path)
        manifest, data_hash, warnings, errors = self.inspector.inspect(registration, root=root)
        observed_manifest_hash = manifest_semantic_hash(manifest)
        observed_data_hash = data_hash
        registered_manifest_hash = record.manifest_hash or observed_manifest_hash
        registered_data_hash = record.data_hash or observed_data_hash
        if record.manifest_hash and record.manifest_hash != observed_manifest_hash:
            errors.append("dataset_manifest_identity_changed")
        if record.data_hash and record.data_hash != observed_data_hash:
            errors.append("dataset_data_identity_changed")
        required = self._required_categories(strategy)
        present = sorted({item.category for item in manifest.files}, key=lambda value: value.value)
        missing = [category for category in required if category not in present]
        inspections = []
        schema_errors: list[str] = []
        coverage_gaps: list[str] = []
        for item in manifest.files:
            try:
                inspection = inspect_lean_file(root / item.path, item.category)
            except Exception as exc:
                schema_errors.append(f"{item.path}:inspection_failed:{type(exc).__name__}")
                continue
            inspections.append(inspection)
            schema_errors.extend(f"{item.path}:{error}" for error in inspection.data_file.schema_errors)
            coverage_gaps.extend(f"{item.path}:{gap}" for gap in inspection.data_file.coverage_gaps)
        coverage_gaps.extend(
            validate_session_coverage(
                inspections,
                requested_start=start_date,
                requested_end=end_date,
                symbols=registration.symbols,
            )
        )
        all_dates = [
            value
            for item in manifest.files
            for value in (item.coverage_start, item.coverage_end)
            if value is not None
        ]
        coverage_start = min(all_dates) if all_dates else None
        coverage_end = max(all_dates) if all_dates else None
        trusted_sessions = trusted_us_exchange_sessions(start_date, end_date)
        expected_coverage_start = min(trusted_sessions) if trusted_sessions else start_date
        expected_coverage_end = max(trusted_sessions) if trusted_sessions else end_date
        if coverage_start is None or coverage_start > expected_coverage_start:
            errors.append("coverage_start_insufficient")
        if coverage_end is None or coverage_end < expected_coverage_end:
            errors.append("coverage_end_insufficient")
        # A union of files is not sufficient evidence: each time-varying
        # evidence family must span the requested period, otherwise a run
        # could silently switch to a different source halfway through.
        for category in required:
            category_files = [item for item in manifest.files if item.category is category]
            if category is DatasetCategory.SECURITY_MASTER:
                continue
            category_starts = [item.coverage_start for item in category_files if item.coverage_start]
            category_ends = [item.coverage_end for item in category_files if item.coverage_end]
            if not category_starts or min(category_starts) > expected_coverage_start:
                errors.append(f"coverage_start_insufficient:{category.value}")
            if not category_ends or max(category_ends) < expected_coverage_end:
                errors.append(f"coverage_end_insufficient:{category.value}")
        if not record.license.strip():
            errors.append("license_missing")
        if not record.provenance.strip():
            errors.append("provenance_missing")
        unsupported = sorted(set(registration.symbols) - BACKTEST_SYMBOL_ALLOWLIST)
        if unsupported:
            warnings.append("symbols_outside_first_batch:" + ",".join(unsupported))
        if missing:
            errors.append("required_categories_missing")
        if schema_errors:
            errors.append("canonical_schema_invalid")
        if coverage_gaps:
            errors.append("point_in_time_coverage_gaps")
        fixture = "fixture" in record.provider.lower() or "sample" in record.provider.lower()
        canonical_manifest_hash = None
        if not schema_errors and not coverage_gaps and not missing and not any(
            code.endswith("identity_changed") for code in errors
        ):
            canonical_path = self.result_root / "datasets" / dataset_id / "lean-manifest.json"
            try:
                _canonical, canonical_manifest_hash = build_canonical_manifest(
                    dataset_id=dataset_id,
                    dataset_root=root,
                    files=manifest.files,
                    output_path=canonical_path,
                    fixture=fixture,
                )
            except Exception as exc:
                errors.append(f"canonical_manifest_failed:{type(exc).__name__}")
        status = DatasetStatus.VALID if not errors else DatasetStatus.BLOCKED_DATA
        report = DatasetValidationReport(
            dataset_id=dataset_id,
            status=status,
            valid=not errors,
            manifest_hash=registered_manifest_hash,
            data_hash=registered_data_hash,
            categories_present=present,
            categories_required=required,
            missing_categories=missing,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            requested_start=start_date,
            requested_end=end_date,
            warnings=sorted(set(warnings)),
            errors=sorted(set(errors)),
            schema_errors=sorted(set(schema_errors)),
            coverage_gaps=sorted(set(coverage_gaps)),
            symbols_covered=sorted({symbol for item in manifest.files for symbol in item.symbols}),
            fixture=fixture,
            canonical_manifest_hash=canonical_manifest_hash,
            files=manifest.files,
        )
        self.repository.update_dataset_validation(dataset_id, report)
        return report

    @staticmethod
    def _required_categories(strategy: str | None) -> list[DatasetCategory]:
        # Every formal options strategy requires all evidence families.  A
        # dataset may be registered without a strategy, but validation is
        # intentionally strict so a later run cannot accidentally downgrade
        # the gate to equity-only bars.
        return [
            DatasetCategory.SECURITY_MASTER,
            DatasetCategory.UNDERLYING_BARS,
            DatasetCategory.OPTION_QUOTES,
            DatasetCategory.OPTION_TRADES,
            DatasetCategory.OPEN_INTEREST,
            DatasetCategory.CALENDARS,
            DatasetCategory.CORPORATE_ACTIONS,
        ]

    # Backtest lifecycle -----------------------------------------------
    def create_backtest(self, request: BacktestCreate) -> BacktestRun:
        dataset = self.repository.get_dataset(request.dataset_id)
        if dataset is None:
            raise DatasetNotFoundError(request.dataset_id)
        freeze_source = self._validate_holdout_freeze(request)
        report = self.validate_dataset(
            request.dataset_id,
            strategy=request.strategy.value,
            start_date=request.start_date,
            end_date=request.end_date,
        )
        if freeze_source is not None:
            if freeze_source.data_hash != report.data_hash:
                raise BacktestFreezeError(
                    "holdout_freeze_data_mismatch",
                    "The dataset identity differs from the frozen validation run.",
                )
            if freeze_source.engine_image_digest != (self.engine_image_digest or freeze_source.engine_image_digest):
                raise BacktestFreezeError(
                    "holdout_freeze_engine_mismatch",
                    "The pinned LEAN image differs from the frozen validation run.",
                )
        symbols = set(request.symbols)
        if dataset.symbols and not symbols.issubset(set(dataset.symbols)):
            report.errors.append("requested_symbols_not_in_dataset")
            report.valid = False
            report.status = DatasetStatus.BLOCKED_DATA
            self.repository.update_dataset_validation(request.dataset_id, report)
        if report.fixture and request.formal:
            report.errors.append("fixture_data_not_formal")
            report.valid = False
            report.status = DatasetStatus.BLOCKED_DATA
            self.repository.update_dataset_validation(request.dataset_id, report)
        server_digest = self.engine_image_digest if is_full_digest(self.engine_image_digest) else None
        server_code_version = self._source_hash()
        if freeze_source is not None and freeze_source.code_version != server_code_version:
            raise BacktestFreezeError(
                "holdout_freeze_code_mismatch",
                "The strategy source changed after the validation freeze.",
            )
        algorithm = algorithm_manifest(request.strategy, request.parameters)
        run_manifest = {
            "schema_version": "1",
            "dataset_id": request.dataset_id,
            "dataset_manifest_hash": report.manifest_hash,
            "data_hash": report.data_hash,
            "canonical_manifest_hash": report.canonical_manifest_hash,
            "strategy": request.strategy.value,
            "algorithm": algorithm,
            "algorithm_type": algorithm["algorithm_type"],
            "algorithm_source": algorithm["source"],
            "strategy_source": algorithm.get("strategy_source"),
            "symbols": request.symbols,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "initial_cash": str(request.initial_cash),
            "initial_stock_lots": [lot.model_dump(mode="json") for lot in request.initial_stock_lots],
            "parameters": request.parameters,
            "fee_model": request.fee_model.model_dump(mode="json"),
            "slippage_model": request.slippage_model.model_dump(mode="json"),
            "lifecycle_model": request.lifecycle_model.model_dump(mode="json"),
            "engine_version": self.engine_version,
            "engine_image_digest": server_digest,
            "code_version": server_code_version,
            "formal": request.formal,
            "research_only": request.research_only,
            "freeze_source_run_id": request.freeze_source_run_id,
            "freeze_configuration_hash": (
                freeze_source.run_manifest.get("configuration_hash") if freeze_source is not None else None
            ),
            "network": "disabled",
            "broker_calls": False,
            "ledger_writes": False,
            "future_information_policy": "reject",
        }
        run_manifest["configuration_hash"] = _configuration_hash(run_manifest)
        run_manifest["period_segment"] = (
            request.period_segment
            if request.period_segment != "composite"
            else _period_segment(request.start_date, request.end_date)
        )
        run_manifest["period_hash"] = semantic_hash(
            {
                "period_segment": run_manifest["period_segment"],
                "start_date": run_manifest["start_date"],
                "end_date": run_manifest["end_date"],
            }
        )
        state = BacktestState.QUEUED if report.valid else BacktestState.BLOCKED_DATA
        if state is BacktestState.QUEUED and not is_full_digest(server_digest):
            state = BacktestState.FAILED
        run, _replayed = self.repository.create_run(
            request,
            data_hash=report.data_hash,
            run_manifest=run_manifest,
            code_version=server_code_version,
            engine_version=self.engine_version,
            # A failed missing-lock record still needs a shape-valid value;
            # the run is terminal FAILED and can never be dispatched.
            engine_image_digest=server_digest or "sha256:" + "0" * 64,
            state=state,
        )
        if state is BacktestState.FAILED:
            run = self.repository.finish_run(
                run.id,
                state=BacktestState.FAILED,
                error="server has no configured verified LEAN image digest",
            ) or run
        elif state is BacktestState.QUEUED and self.auto_start and not run.idempotent_replayed:
            self.dispatch(run.id)
        return run

    def _validate_holdout_freeze(self, request: BacktestCreate) -> BacktestRun | None:
        freeze_required = request.period_segment == "holdout" or (
            request.formal and request.end_date >= date(2025, 1, 1)
        )
        if not freeze_required:
            return None
        if request.period_segment == "holdout" and not request.formal:
            raise BacktestFreezeError(
                "holdout_formal_required",
                "Holdout runs must be formal runs with an immutable validation freeze.",
            )
        source_id = request.freeze_source_run_id
        if not source_id:
            raise BacktestFreezeError(
                "holdout_freeze_source_required",
                "A holdout run must reference a completed validation run.",
            )
        source = self.repository.get_run(source_id)
        if source is None:
            raise BacktestFreezeError(
                "holdout_freeze_source_not_found",
                "The referenced validation run does not exist.",
            )
        if source.state is not BacktestState.SUCCEEDED:
            raise BacktestFreezeError(
                "holdout_freeze_source_not_succeeded",
                "The referenced validation run has not completed successfully.",
            )
        if source.start_date != date(2024, 1, 1) or source.end_date != date(2024, 12, 31):
            raise BacktestFreezeError(
                "holdout_freeze_source_period_invalid",
                "The freeze source must cover the frozen 2024 validation period.",
            )
        if request.period_segment == "holdout" and (
            request.start_date != date(2025, 1, 1) or request.end_date != date(2026, 9, 30)
        ):
            raise BacktestFreezeError(
                "holdout_period_invalid",
                "Formal holdout runs must cover 2025-01-01 through 2026-09-30.",
            )
        if request.period_segment == "composite" and (
            request.start_date != date(2020, 1, 1) or request.end_date != date(2026, 9, 30)
        ):
            raise BacktestFreezeError(
                "composite_period_invalid",
                "Formal composite runs covering holdout must cover 2020-01-01 through 2026-09-30.",
            )
        manifest = source.run_manifest or {}
        if manifest.get("period_segment") != "validation":
            raise BacktestFreezeError(
                "holdout_freeze_source_not_validation",
                "The freeze source must be a validation-period run.",
            )
        expected = _configuration_hash(
            {
                "strategy": request.strategy.value,
                "symbols": request.symbols,
                "initial_cash": str(request.initial_cash),
                "parameters": request.parameters,
                "fee_model": request.fee_model.model_dump(mode="json"),
                "slippage_model": request.slippage_model.model_dump(mode="json"),
                "lifecycle_model": request.lifecycle_model.model_dump(mode="json"),
                "initial_stock_lots": [lot.model_dump(mode="json") for lot in request.initial_stock_lots],
                "algorithm": algorithm_manifest(request.strategy, request.parameters),
            }
        )
        mismatches: list[str] = []
        if source.dataset_id != request.dataset_id:
            mismatches.append("dataset_id")
        if list(source.symbols) != list(request.symbols):
            mismatches.append("symbols")
        if source.run_manifest.get("configuration_hash") != expected:
            mismatches.append("configuration_hash")
        if source.run_manifest.get("algorithm") != algorithm_manifest(request.strategy, request.parameters):
            mismatches.append("algorithm")
        if mismatches:
            raise BacktestFreezeError(
                "holdout_freeze_mismatch",
                "Holdout settings differ from the frozen validation run: " + ", ".join(mismatches),
            )
        return source

    def dispatch(self, run_id: str) -> bool:
        run = self.repository.get_run(run_id)
        if run is None:
            raise BacktestNotFoundError(run_id)
        if run.state is not BacktestState.QUEUED:
            return False
        with self._lock:
            future = self._futures.get(run_id)
            if future and not future.done():
                return False
            self._futures[run_id] = self._executor.submit(self._run_in_worker, run_id)
        return True

    def dispatch_next(self) -> BacktestRun | None:
        candidates = self.repository.list_runs(state=BacktestState.QUEUED, limit=1)
        if not candidates:
            return None
        self.dispatch(candidates[0].id)
        return self.repository.get_run(candidates[0].id)

    def cancel_backtest(self, run_id: str) -> BacktestRun:
        run = self.repository.request_cancel(run_id)
        if run is None:
            raise BacktestNotFoundError(run_id)
        if run.state is BacktestState.RUNNING:
            identity = run.process_identity or {}
            if identity.get("run_id") == run_id and identity.get("kind") == "docker":
                self.launcher.cancel(run_id)
        return run

    def recover_stale_runs(self, *, requeue: bool = False) -> list[BacktestRun]:
        now = datetime.now(timezone.utc)
        recovered: list[BacktestRun] = []
        for run in self.repository.list_runs(state=BacktestState.RUNNING, limit=None):
            if run.lease_expires_at is None or _aware_datetime(run.lease_expires_at) >= now:
                continue
            try:
                owned = (
                    self.launcher.inspect_owned_container(run.id)
                    if hasattr(self.launcher, "inspect_owned_container")
                    else None
                )
            except Exception:
                # Docker inspection is an evidence boundary.  If it cannot be
                # completed, leave the state untouched so a second job cannot
                # be started on ambiguous process evidence.
                continue
            if owned is not None and bool(owned.get("running")):
                if run.lease_owner:
                    expires = now + timedelta(seconds=self.lease_ttl_seconds)
                    renewed = self.repository.renew_global_lease(
                        owner=run.lease_owner,
                        run_id=run.id,
                        now=now,
                        ttl_seconds=self.lease_ttl_seconds,
                    )
                    if renewed:
                        self.repository.heartbeat(
                            run.id,
                            owner=run.lease_owner,
                            lease_expires_at=expires,
                        )
                continue
            recovered_run = self.repository.recover_expired_run(
                run.id,
                now=now,
                requeue=requeue,
            )
            if recovered_run is not None:
                recovered.append(recovered_run)
        return recovered

    def get_backtest(self, run_id: str) -> BacktestRun:
        run = self.repository.get_run(run_id)
        if run is None:
            raise BacktestNotFoundError(run_id)
        return run

    def list_backtests(self, **filters: Any) -> list[BacktestRun]:
        return self.repository.list_runs(**filters)

    def compare_backtests(self, request: BacktestCompareRequest) -> BacktestComparison:
        rows = self.repository.compare(request)
        missing = sorted(set(request.run_ids) - {row["run_id"] for row in rows})
        return BacktestComparison(
            run_ids=request.run_ids,
            rows=rows,
            warnings=[f"run_not_found:{run_id}" for run_id in missing],
        )

    # Worker -------------------------------------------------------------
    def _run_in_worker(self, run_id: str) -> None:
        repository = self.repository
        session = None
        if self.session_factory is not None:
            session = self.session_factory()
            repository = SQLAlchemyBacktestRepository(session)
        owner = f"worker-{uuid.uuid4()}"
        try:
            if not repository.acquire_global_lease(
                owner=owner,
                run_id=run_id,
                ttl_seconds=self.lease_ttl_seconds,
            ):
                return
            run = repository.get_run(run_id)
            if run is None or run.state is not BacktestState.QUEUED:
                return
            record = repository.get_dataset_record(run.dataset_id)
            if record is None:
                repository.finish_run(run_id, state=BacktestState.FAILED, error="dataset disappeared")
                return
            try:
                dataset_path = self.inspector.resolve_dataset_root(record.root_path)
            except DatasetSecurityError as exc:
                repository.finish_run(run_id, state=BacktestState.BLOCKED_DATA, error=str(exc))
                return
            try:
                current_registration = DatasetRegistration(
                    id=record.id,
                    name=record.name,
                    root_path=record.root_path,
                    provider=record.provider,
                    license=record.license,
                    provenance=record.provenance,
                    symbols=list(record.symbols or []),
                    declared_start=record.declared_start,
                    declared_end=record.declared_end,
                )
                current_manifest, current_data_hash, _warnings, _errors = self.inspector.inspect(
                    current_registration,
                    root=dataset_path,
                )
                if (
                    run.data_hash != current_data_hash
                    or (record.manifest_hash and record.manifest_hash != manifest_semantic_hash(current_manifest))
                ):
                    repository.finish_run(
                        run_id,
                        state=BacktestState.BLOCKED_DATA,
                        error="dataset identity changed after run creation",
                    )
                    return
            except Exception:
                repository.finish_run(
                    run_id,
                    state=BacktestState.BLOCKED_DATA,
                    error="dataset could not be revalidated before launch",
                )
                return
            result_dir = self.result_root / run_id
            result_dir.mkdir(parents=True, exist_ok=True)
            try:
                snapshot_path, snapshot_data_hash = self._stage_data_snapshot(
                    dataset_root=dataset_path,
                    registration=current_registration,
                    manifest=current_manifest,
                    expected_manifest_hash=record.manifest_hash,
                    expected_data_hash=run.data_hash,
                    run_id=run_id,
                )
            except Exception as exc:
                repository.finish_run(
                    run_id,
                    state=BacktestState.BLOCKED_DATA,
                    error=f"run data snapshot failed: {type(exc).__name__}",
                )
                return
            try:
                algorithm_identity = self._verify_algorithm_identity(run)
            except BacktestDataBlockedError as exc:
                repository.finish_run(run_id, state=BacktestState.BLOCKED_DATA, error=str(exc))
                return
            # Stage a fresh canonical manifest beside the isolated result.
            # The source files remain read-only; only this run-local manifest
            # is writable by the worker/container.
            try:
                _staged_manifest, staged_manifest_hash = build_canonical_manifest(
                    dataset_id=run.dataset_id,
                    dataset_root=snapshot_path,
                    files=current_manifest.files,
                    output_path=result_dir / "lean-data-manifest.json",
                    fixture="fixture" in record.provider.lower() or "sample" in record.provider.lower(),
                )
            except Exception as exc:
                repository.finish_run(
                    run_id,
                    state=BacktestState.BLOCKED_DATA,
                    error=f"canonical LEAN manifest failed: {type(exc).__name__}",
                )
                return
            expected_manifest_hash = run.run_manifest.get("canonical_manifest_hash")
            if expected_manifest_hash and expected_manifest_hash != staged_manifest_hash:
                repository.finish_run(
                    run_id,
                    state=BacktestState.BLOCKED_DATA,
                    error="canonical LEAN manifest changed after run creation",
                )
                return
            config_path = result_dir / "lean-config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "strategy": run.strategy.value,
                        "algorithm": run.run_manifest.get("algorithm", {}).get("algorithm_type", run.run_manifest.get("algorithm_type", run.strategy.value)),
                        "algorithm_source": run.run_manifest.get("algorithm", {}).get("source", run.run_manifest.get("algorithm_source")),
                        "algorithm_manifest": run.run_manifest.get("algorithm", {}),
                        "start_date": run.start_date.isoformat(),
                        "end_date": run.end_date.isoformat(),
                        "formal": bool(run.run_manifest.get("formal", True)),
                        "symbols": run.symbols,
                        "initial_stock_lots": run.run_manifest.get("initial_stock_lots", []),
                        "parameters": {
                            **run.parameters,
                            "canonical_manifest": "/lean-results/lean-data-manifest.json",
                        },
                        "fee_model": run.fee_model.model_dump(mode="json"),
                        "slippage_model": run.slippage_model.model_dump(mode="json"),
                        "lifecycle_model": run.lifecycle_model.model_dump(mode="json"),
                        "canonical_manifest": "/lean-results/lean-data-manifest.json",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            context = LeanExecutionContext(
                run_id=run_id,
                dataset_path=snapshot_path,
                config_path=config_path,
                result_path=result_dir,
                image_digest=run.engine_image_digest,
                source_path=self.source_root,
            )
            identity = {"kind": "docker", "run_id": run_id, "owner": owner, "image_digest": run.engine_image_digest}
            identity.update(
                {
                    "data_snapshot_path": str(snapshot_path),
                    "data_snapshot_hash": snapshot_data_hash,
                    "algorithm_source": algorithm_identity.get("source"),
                    "algorithm_source_sha256": algorithm_identity.get("source_sha256"),
                }
            )
            if hasattr(self.launcher, "process_identity"):
                try:
                    identity.update(self.launcher.process_identity(context))
                    identity.update({"owner": owner, "run_id": run_id})
                except Exception:
                    pass
            lease_expires = datetime.now(timezone.utc) + timedelta(seconds=self.lease_ttl_seconds)
            if repository.mark_running(
                run_id,
                owner=owner,
                process_identity=identity,
                lease_expires_at=lease_expires,
            ) is None:
                return
            heartbeat_stop = threading.Event()
            heartbeat_lost = threading.Event()
            heartbeat_thread: threading.Thread | None = None

            if self.session_factory is not None:
                interval = max(0.1, min(30.0, self.lease_ttl_seconds / 3))

                def heartbeat_loop() -> None:
                    while not heartbeat_stop.wait(interval):
                        try:
                            with self.session_factory() as heartbeat_session:
                                heartbeat_repository = SQLAlchemyBacktestRepository(heartbeat_session)
                                next_expiry = datetime.now(timezone.utc) + timedelta(
                                    seconds=self.lease_ttl_seconds
                                )
                                renewed = heartbeat_repository.renew_global_lease(
                                    owner=owner,
                                    run_id=run_id,
                                    ttl_seconds=self.lease_ttl_seconds,
                                )
                                updated = heartbeat_repository.heartbeat(
                                    run_id,
                                    owner=owner,
                                    lease_expires_at=next_expiry,
                                )
                                if not (renewed and updated):
                                    heartbeat_lost.set()
                                    return
                        except Exception:
                            heartbeat_lost.set()
                            return

                heartbeat_thread = threading.Thread(
                    target=heartbeat_loop,
                    name=f"stocks-backtest-heartbeat-{run_id[:8]}",
                    daemon=True,
                )
                heartbeat_thread.start()

            def stop_heartbeat() -> None:
                heartbeat_stop.set()
                if heartbeat_thread is not None and heartbeat_thread is not threading.current_thread():
                    heartbeat_thread.join(timeout=max(1.0, min(10.0, self.lease_ttl_seconds)))

            try:
                payload = self.launcher.run(context)
                stop_heartbeat()
                if heartbeat_lost.is_set():
                    self._interrupt_after_heartbeat_loss(repository, run_id, owner)
                    return
                try:
                    self._verify_algorithm_identity(run)
                    self._verify_data_snapshot(
                        snapshot_path=snapshot_path,
                        registration=current_registration,
                        expected_manifest_hash=record.manifest_hash,
                        expected_data_hash=run.data_hash,
                    )
                except BacktestDataBlockedError as exc:
                    repository.finish_run(run_id, state=BacktestState.BLOCKED_DATA, error=str(exc), owner=owner)
                    return
                latest = repository.get_run(run_id)
                if latest is not None and latest.cancel_requested:
                    repository.finish_run(run_id, state=BacktestState.CANCELLED, owner=owner)
                else:
                    result = self._parse_result(run_id, payload)
                    repository.finish_run(run_id, state=BacktestState.SUCCEEDED, result=result, owner=owner)
            except BacktestDataBlockedError as exc:
                stop_heartbeat()
                if heartbeat_lost.is_set():
                    self._interrupt_after_heartbeat_loss(repository, run_id, owner)
                    return
                repository.finish_run(run_id, state=BacktestState.BLOCKED_DATA, error=str(exc), owner=owner)
            except LeanExecutionError as exc:
                stop_heartbeat()
                if heartbeat_lost.is_set():
                    self._interrupt_after_heartbeat_loss(repository, run_id, owner)
                    return
                latest = repository.get_run(run_id)
                final_state = BacktestState.CANCELLED if latest and latest.cancel_requested else BacktestState.FAILED
                repository.finish_run(run_id, state=final_state, error=str(exc), owner=owner)
            except Exception as exc:  # persist a safe terminal state; do not leak secrets
                stop_heartbeat()
                if heartbeat_lost.is_set():
                    self._interrupt_after_heartbeat_loss(repository, run_id, owner)
                    return
                repository.finish_run(
                    run_id,
                    state=BacktestState.FAILED,
                    error=f"backtest worker error: {type(exc).__name__}",
                    owner=owner,
                )
        finally:
            try:
                repository.release_global_lease(owner=owner, run_id=run_id)
            except Exception:
                pass
            if session is not None:
                session.close()

    def _interrupt_after_heartbeat_loss(
        self,
        repository: SQLAlchemyBacktestRepository,
        run_id: str,
        owner: str,
    ) -> None:
        """Stop only the owned process and CAS the run to INTERRUPTED."""

        cancel_error: str | None = None
        try:
            if hasattr(self.launcher, "cancel"):
                cancelled = self.launcher.cancel(run_id)
                if cancelled is False:
                    cancel_error = "owned_process_not_confirmed"
        except Exception as exc:
            cancel_error = type(exc).__name__
        detail = "lease heartbeat lost; owned process was stopped"
        if cancel_error:
            detail = f"lease heartbeat lost; owned process status unknown ({cancel_error})"
        # finish_run(owner=...) is an ownership CAS: a recovery worker that
        # adopted or cleared the lease cannot be overwritten by this worker.
        repository.finish_run(
            run_id,
            state=BacktestState.INTERRUPTED,
            error=detail,
            owner=owner,
        )

    @staticmethod
    def _parse_result(run_id: str, payload: dict[str, Any]) -> BacktestResult:
        payload = dict(payload)
        payload["run_id"] = run_id
        payload.pop("semantic_hash", None)
        payload["semantic_hash"] = "pending"
        raw_trades = payload.get("trades") or []
        normalized_trades: list[dict[str, Any]] = []
        warnings = list(payload.get("warnings") or [])
        for index, trade in enumerate(raw_trades):
            if not isinstance(trade, dict):
                warnings.append("provider_trade_schema_unavailable")
                continue
            required = {"timestamp", "strategy", "symbol", "status"}
            if not required.issubset(trade):
                # LEAN provider exports are retained in raw_payload by the
                # launcher, while the stable result contract stays honest.
                warnings.append("provider_trade_schema_unavailable")
                continue
            normalized_trades.append(trade)
        payload["trades"] = normalized_trades
        payload["warnings"] = sorted(set(warnings))
        result = BacktestResult.model_validate(payload)
        result.semantic_hash = semantic_hash(result_semantic_payload(result))
        return result

    def _stage_data_snapshot(
        self,
        *,
        dataset_root: Path,
        registration: DatasetRegistration,
        manifest: DatasetManifest,
        expected_manifest_hash: str | None,
        expected_data_hash: str | None,
        run_id: str,
    ) -> tuple[Path, str]:
        """Copy verified source files into an immutable run-local input root."""

        snapshot_root = self.result_root / "_snapshots" / run_id
        temporary_root = snapshot_root.with_name(snapshot_root.name + ".tmp")
        if temporary_root.exists():
            shutil.rmtree(temporary_root)
        if snapshot_root.exists():
            shutil.rmtree(snapshot_root)
        temporary_root.mkdir(parents=True, exist_ok=True)
        source_root = dataset_root.resolve(strict=True)
        for item in manifest.files:
            source = (source_root / item.path).resolve(strict=True)
            try:
                source.relative_to(source_root)
            except ValueError as exc:
                raise BacktestDataBlockedError(f"dataset snapshot source escapes root: {item.path}") from exc
            if not source.is_file() or source.is_symlink():
                raise BacktestDataBlockedError(f"dataset snapshot source is not a regular file: {item.path}")
            destination = temporary_root / item.path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        temporary_inspector = DatasetInspection(allowed_root=self.result_root)
        snapshot_manifest, snapshot_hash, _warnings, errors = temporary_inspector.inspect(
            registration.model_copy(update={"root_path": str(temporary_root)}),
            root=temporary_root,
        )
        if errors:
            raise BacktestDataBlockedError("run data snapshot failed validation")
        observed_manifest_hash = manifest_semantic_hash(snapshot_manifest)
        if expected_manifest_hash and observed_manifest_hash != expected_manifest_hash:
            raise BacktestDataBlockedError("run data snapshot manifest identity changed during copy")
        if expected_data_hash and snapshot_hash != expected_data_hash:
            raise BacktestDataBlockedError("run data snapshot content changed during copy")
        temporary_root.replace(snapshot_root)
        return snapshot_root, snapshot_hash

    def _verify_data_snapshot(
        self,
        *,
        snapshot_path: Path,
        registration: DatasetRegistration,
        expected_manifest_hash: str | None,
        expected_data_hash: str | None,
    ) -> None:
        inspector = DatasetInspection(allowed_root=self.result_root)
        manifest, data_hash, _warnings, errors = inspector.inspect(
            registration.model_copy(update={"root_path": str(snapshot_path)}),
            root=snapshot_path,
        )
        if errors:
            raise BacktestDataBlockedError("run data snapshot changed during execution")
        if expected_manifest_hash and manifest_semantic_hash(manifest) != expected_manifest_hash:
            raise BacktestDataBlockedError("run data snapshot manifest drifted during execution")
        if expected_data_hash and data_hash != expected_data_hash:
            raise BacktestDataBlockedError("run data snapshot content drifted during execution")

    def _verify_algorithm_identity(self, run: BacktestRun) -> dict[str, Any]:
        try:
            observed = algorithm_manifest(run.strategy, run.parameters)
        except (FileNotFoundError, KeyError, OSError) as exc:
            raise BacktestDataBlockedError("strategy algorithm source is unavailable") from exc
        expected = run.run_manifest.get("algorithm") or {}
        for key in ("strategy", "algorithm_type", "source", "source_sha256"):
            if expected.get(key) != observed.get(key):
                raise BacktestDataBlockedError(f"strategy algorithm identity changed: {key}")
        return observed

    def _source_hash(self) -> str:
        digest = hashlib.sha256()
        paths = [
            Path(__file__),
            self.source_root / "domain" / "backtesting.py",
            self.source_root / "adapters" / "backtesting" / "rules.py",
            self.source_root / "adapters" / "backtesting" / "simulator.py",
            self.source_root / "adapters" / "backtesting" / "lean_data.py",
            self.source_root / "adapters" / "backtesting" / "lean.py",
            self.source_root / "adapters" / "backtesting" / "lean_staging.py",
        ]
        strategy_root = self.source_root / "domain" / "strategies"
        if strategy_root.is_dir():
            paths.extend(strategy_root.glob("*.py"))
        algorithm_root = self.source_root / "adapters" / "backtesting" / "lean_algorithms"
        if algorithm_root.is_dir():
            paths.extend(algorithm_root.glob("*.py"))
        for path in sorted({path.resolve() for path in paths}):
            digest.update(str(path.name).encode("utf-8"))
            digest.update(b"\0")
            try:
                digest.update(path.read_bytes())
            except OSError:
                digest.update(b"missing")
            digest.update(b"\n")
        return digest.hexdigest()


class BacktestDispatcher:
    """Long-lived single-worker dispatcher for queued offline runs.

    Each tick opens a short-lived read session to choose one queued run, then
    the service worker opens its own session for the full run.  The dispatcher
    never reuses a request session and its stop signal is bounded by the
    application's shutdown task.
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Any],
        allowed_data_root: str | Path,
        result_root: str | Path,
        engine_image_digest: str | None = LEAN_ENGINE_IMAGE_DIGEST,
        engine_version: str = LEAN_ENGINE_VERSION,
        poll_interval_seconds: float = 5.0,
        lease_ttl_seconds: int = 300,
        launcher: Any | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.allowed_data_root = Path(allowed_data_root)
        self.result_root = Path(result_root)
        self.engine_image_digest = engine_image_digest
        self.engine_version = engine_version
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self.lease_ttl_seconds = lease_ttl_seconds
        self.launcher = launcher or LeanLauncher()
        self._stop_event = asyncio.Event()
        self._active_lock = threading.Lock()
        self._active_run_id: str | None = None

    def _service(self, session: Any) -> BacktestingService:
        return BacktestingService(
            repository=SQLAlchemyBacktestRepository(session),
            allowed_data_root=self.allowed_data_root,
            result_root=self.result_root,
            launcher=self.launcher,
            session_factory=self.session_factory,
            engine_image_digest=self.engine_image_digest,
            engine_version=self.engine_version,
            auto_start=False,
            lease_ttl_seconds=self.lease_ttl_seconds,
        )

    def tick(self) -> str | None:
        """Recover stale ownership and synchronously process at most one run."""

        with self.session_factory() as session:
            service = self._service(session)
            service.recover_stale_runs(requeue=False)
            queued = service.repository.list_runs(state=BacktestState.QUEUED, limit=1)
            run_id = queued[0].id if queued else None
        if run_id is None:
            return None
        if self._stop_event.is_set():
            return None
        # The request/read session is closed before this worker opens its own
        # session and executes the external process.
        with self._active_lock:
            if self._stop_event.is_set():
                return None
            self._active_run_id = run_id
        try:
            service._run_in_worker(run_id)
        finally:
            with self._active_lock:
                self._active_run_id = None
        return run_id

    async def run(self) -> None:
        self._stop_event.clear()
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception as error:
                logger.warning(
                    "Backtest dispatcher tick failed code=%s detail=%s",
                    type(error).__name__,
                    str(error)[:500],
                )
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop_event.set()
        with self._active_lock:
            active_run_id = self._active_run_id
        if not active_run_id:
            return

        def cancel_active() -> None:
            try:
                with self.session_factory() as session:
                    SQLAlchemyBacktestRepository(session).request_cancel(active_run_id)
            except Exception as error:
                logger.warning(
                    "Backtest dispatcher active-run database cancellation failed code=%s detail=%s",
                    type(error).__name__,
                    str(error)[:500],
                )
            try:
                if hasattr(self.launcher, "cancel"):
                    self.launcher.cancel(active_run_id)
            except Exception as error:
                logger.warning(
                    "Backtest dispatcher active-run container cancellation failed code=%s detail=%s",
                    type(error).__name__,
                    str(error)[:500],
                )

        try:
            await asyncio.wait_for(asyncio.to_thread(cancel_active), timeout=10.0)
        except asyncio.TimeoutError:
            logger.error("Backtest dispatcher active-run cancellation exceeded bounded shutdown timeout")


def _is_digest(value: str | None) -> bool:
    return bool(value and value.startswith("sha256:") and len(value) == 71 and all(c in "0123456789abcdef" for c in value[7:].lower()))


def _period_segment(start_date: date, end_date: date) -> str:
    if start_date == date(2020, 1, 1) and end_date == date(2023, 12, 31):
        return "development"
    if start_date == date(2024, 1, 1) and end_date == date(2024, 12, 31):
        return "validation"
    if start_date == date(2025, 1, 1) and end_date == date(2026, 9, 30):
        return "holdout"
    return "composite"


def _configuration_hash(value: dict[str, Any]) -> str:
    projection = {
        "strategy": value.get("strategy"),
        "symbols": value.get("symbols", []),
        "initial_cash": value.get("initial_cash"),
        "parameters": value.get("parameters", {}),
        "fee_model": value.get("fee_model", {}),
        "slippage_model": value.get("slippage_model", {}),
        "lifecycle_model": value.get("lifecycle_model", {}),
        "initial_stock_lots": value.get("initial_stock_lots", []),
        "algorithm": value.get("algorithm", {}),
    }
    return semantic_hash(projection)


def _aware_datetime(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

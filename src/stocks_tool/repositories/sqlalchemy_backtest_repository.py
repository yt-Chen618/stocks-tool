"""SQLAlchemy repository for the isolated backtest data model."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stocks_tool.db.backtest_models import (
    BacktestDatasetRecord,
    BacktestLeaseRecord,
    BacktestResultRecord,
    BacktestRunRecord,
)
from stocks_tool.domain.backtesting import (
    BacktestCompareRequest,
    BacktestCreate,
    BacktestResult,
    BacktestRun,
    BacktestState,
    DatasetRegistration,
    DatasetStatus,
    DatasetSummary,
    DatasetValidationReport,
    FeeModel,
    LifecycleModel,
    SlippageModel,
)


GLOBAL_LEASE_ID = "global"


class BacktestDatasetConflictError(ValueError):
    """A registered dataset identity may not be silently overwritten."""


class SQLAlchemyBacktestRepository:
    """Persistence boundary that never touches order or broker tables."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # Dataset operations -------------------------------------------------
    def register_dataset(
        self,
        registration: DatasetRegistration,
        *,
        manifest: dict | None = None,
        manifest_hash: str | None = None,
        data_hash: str | None = None,
        status: DatasetStatus = DatasetStatus.REGISTERED,
        validation: DatasetValidationReport | dict | None = None,
    ) -> DatasetSummary:
        existing = self.session.execute(
            select(BacktestDatasetRecord).where(
                BacktestDatasetRecord.name == registration.name,
                BacktestDatasetRecord.root_path == registration.root_path,
            )
        ).scalar_one_or_none()
        if existing is None:
            record = BacktestDatasetRecord(
                id=registration.id,
                name=registration.name,
                root_path=registration.root_path,
                provider=registration.provider,
                license=registration.license,
                provenance=registration.provenance,
                symbols=registration.symbols,
                declared_start=registration.declared_start,
                declared_end=registration.declared_end,
                status=status.value,
                manifest_payload=manifest,
                manifest_hash=manifest_hash,
                data_hash=data_hash,
                validation_payload=_as_json(validation),
            )
            self.session.add(record)
        else:
            record = existing
            same_identity = (
                record.provider == registration.provider
                and record.license == registration.license
                and record.provenance == registration.provenance
                and list(record.symbols or []) == list(registration.symbols)
                and record.declared_start == registration.declared_start
                and record.declared_end == registration.declared_end
                and record.manifest_hash == manifest_hash
                and record.data_hash == data_hash
            )
            if not same_identity:
                raise BacktestDatasetConflictError(
                    "dataset identity changed; register a new name/path for a new immutable version"
                )
            # Re-registration of identical content is an idempotent read.  A
            # validation report may be refreshed, but the manifest/data
            # identity and provenance remain untouched.
            if validation is not None:
                record.validation_payload = _as_json(validation)
        self.session.commit()
        self.session.refresh(record)
        return self._to_dataset(record)

    # A descriptive alias used by scripts and callers that use CRUD names.
    create_dataset = register_dataset

    def get_dataset(self, dataset_id: str) -> DatasetSummary | None:
        record = self.session.get(BacktestDatasetRecord, dataset_id)
        return self._to_dataset(record) if record is not None else None

    def get_dataset_record(self, dataset_id: str) -> BacktestDatasetRecord | None:
        return self.session.get(BacktestDatasetRecord, dataset_id)

    def list_datasets(
        self,
        *,
        status: DatasetStatus | None = None,
        limit: int | None = 100,
    ) -> list[DatasetSummary]:
        query = select(BacktestDatasetRecord).order_by(BacktestDatasetRecord.created_at.desc())
        if status is not None:
            query = query.where(BacktestDatasetRecord.status == status.value)
        if limit is not None:
            query = query.limit(limit)
        return [self._to_dataset(record) for record in self.session.execute(query).scalars().all()]

    def update_dataset_validation(
        self,
        dataset_id: str,
        report: DatasetValidationReport,
    ) -> DatasetSummary | None:
        record = self.session.get(BacktestDatasetRecord, dataset_id)
        if record is None:
            return None
        record.status = report.status.value
        # Validation may observe drift, but it never rewrites the immutable
        # identity used by existing runs.
        if record.manifest_hash is None:
            record.manifest_hash = report.manifest_hash
        if record.data_hash is None:
            record.data_hash = report.data_hash
        record.validation_payload = report.model_dump(mode="json", exclude_none=True)
        self.session.commit()
        self.session.refresh(record)
        return self._to_dataset(record)

    # Run operations -----------------------------------------------------
    def create_run(
        self,
        request: BacktestCreate,
        *,
        data_hash: str | None,
        run_manifest: dict,
        code_version: str,
        engine_version: str,
        engine_image_digest: str,
        state: BacktestState = BacktestState.QUEUED,
        run_id: str | None = None,
    ) -> tuple[BacktestRun, bool]:
        if request.idempotency_key:
            existing = self.session.execute(
                select(BacktestRunRecord).where(
                    BacktestRunRecord.idempotency_key == request.idempotency_key
                )
            ).scalar_one_or_none()
            if existing is not None:
                return self._to_run(existing, idempotent_replayed=True), True

        record = BacktestRunRecord(
            id=run_id,
            dataset_id=request.dataset_id,
            strategy=request.strategy.value,
            symbols=request.symbols,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_cash=request.initial_cash,
            state=state.value,
            parameters=request.parameters,
            fee_model=request.fee_model.model_dump(mode="json"),
            slippage_model=request.slippage_model.model_dump(mode="json"),
            lifecycle_model=request.lifecycle_model.model_dump(mode="json"),
            run_manifest=run_manifest,
            code_version=code_version,
            engine_version=engine_version,
            engine_image_digest=engine_image_digest,
            data_hash=data_hash,
            idempotency_key=request.idempotency_key,
            cancel_requested=False,
        )
        self.session.add(record)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            if request.idempotency_key:
                existing = self.session.execute(
                    select(BacktestRunRecord).where(
                        BacktestRunRecord.idempotency_key == request.idempotency_key
                    )
                ).scalar_one()
                return self._to_run(existing, idempotent_replayed=True), True
            raise
        self.session.refresh(record)
        return self._to_run(record), False

    def get_run(self, run_id: str) -> BacktestRun | None:
        record = self.session.get(BacktestRunRecord, run_id)
        return self._to_run(record) if record is not None else None

    def get_run_record(self, run_id: str) -> BacktestRunRecord | None:
        return self.session.get(BacktestRunRecord, run_id)

    def list_runs(
        self,
        *,
        state: BacktestState | None = None,
        dataset_id: str | None = None,
        limit: int | None = 100,
    ) -> list[BacktestRun]:
        query = select(BacktestRunRecord).order_by(BacktestRunRecord.created_at.desc())
        if state is not None:
            query = query.where(BacktestRunRecord.state == state.value)
        if dataset_id is not None:
            query = query.where(BacktestRunRecord.dataset_id == dataset_id)
        if limit is not None:
            query = query.limit(limit)
        return [self._to_run(record) for record in self.session.execute(query).scalars().all()]

    def mark_running(
        self,
        run_id: str,
        *,
        owner: str,
        process_identity: dict,
        lease_expires_at: datetime,
        started_at: datetime | None = None,
    ) -> BacktestRun | None:
        record = self.session.get(BacktestRunRecord, run_id)
        if record is None or record.state != BacktestState.QUEUED.value:
            return None
        record.state = BacktestState.RUNNING.value
        record.lease_owner = owner
        record.lease_expires_at = lease_expires_at
        record.process_identity = process_identity
        record.started_at = started_at or datetime.now(timezone.utc)
        record.error = None
        self.session.commit()
        self.session.refresh(record)
        return self._to_run(record)

    def heartbeat(self, run_id: str, *, owner: str, lease_expires_at: datetime) -> bool:
        record = self.session.get(BacktestRunRecord, run_id)
        if record is None or record.lease_owner != owner or record.state != BacktestState.RUNNING.value:
            return False
        record.lease_expires_at = lease_expires_at
        self.session.commit()
        return True

    def finish_run(
        self,
        run_id: str,
        *,
        state: BacktestState,
        result: BacktestResult | None = None,
        error: str | None = None,
        completed_at: datetime | None = None,
        owner: str | None = None,
    ) -> BacktestRun | None:
        record = self.session.get(BacktestRunRecord, run_id)
        if record is None:
            return None
        if owner is not None and (
            record.lease_owner != owner or record.state != BacktestState.RUNNING.value
        ):
            return None
        record.state = state.value
        record.error = error
        record.completed_at = completed_at or datetime.now(timezone.utc)
        record.lease_owner = None
        record.lease_expires_at = None
        if result is not None:
            existing = self.session.execute(
                select(BacktestResultRecord).where(BacktestResultRecord.run_id == run_id)
            ).scalar_one_or_none()
            payload = result.model_dump(mode="json", exclude_none=True)
            if existing is None:
                existing = BacktestResultRecord(
                    id=result.id,
                    run_id=run_id,
                    semantic_hash=result.semantic_hash,
                    metrics_payload=payload.get("metrics", {}),
                    trades_payload=payload.get("trades", []),
                    equity_curve_payload=payload.get("equity_curve", []),
                    warnings=payload.get("warnings", []),
                    raw_payload=payload,
                )
                self.session.add(existing)
            else:
                existing.semantic_hash = result.semantic_hash
                existing.metrics_payload = payload.get("metrics", {})
                existing.trades_payload = payload.get("trades", [])
                existing.equity_curve_payload = payload.get("equity_curve", [])
                existing.warnings = payload.get("warnings", [])
                existing.raw_payload = payload
            record.result_summary = {
                "result_id": result.id,
                "semantic_hash": result.semantic_hash,
                "metrics": payload.get("metrics", {}),
            }
        self.session.commit()
        self.session.refresh(record)
        return self._to_run(record)

    def request_cancel(self, run_id: str) -> BacktestRun | None:
        record = self.session.get(BacktestRunRecord, run_id)
        if record is None:
            return None
        if record.state == BacktestState.QUEUED.value:
            record.state = BacktestState.CANCELLED.value
            record.completed_at = datetime.now(timezone.utc)
        elif record.state == BacktestState.RUNNING.value:
            record.cancel_requested = True
        self.session.commit()
        self.session.refresh(record)
        return self._to_run(record)

    def recover_expired_runs(
        self,
        *,
        now: datetime | None = None,
        requeue: bool = False,
    ) -> list[BacktestRun]:
        now = now or datetime.now(timezone.utc)
        records = self.session.execute(
            select(BacktestRunRecord).where(
                BacktestRunRecord.state == BacktestState.RUNNING.value,
                BacktestRunRecord.lease_expires_at.is_not(None),
                BacktestRunRecord.lease_expires_at < now,
            )
        ).scalars().all()
        recovered: list[BacktestRun] = []
        for record in records:
            record.state = BacktestState.QUEUED.value if requeue else BacktestState.INTERRUPTED.value
            record.error = "worker lease expired; process identity is no longer trusted"
            record.completed_at = None if requeue else now
            record.lease_owner = None
            record.lease_expires_at = None
            recovered.append(self._to_run(record))
        if records:
            self.session.commit()
        return recovered

    def recover_expired_run(
        self,
        run_id: str,
        *,
        now: datetime | None = None,
        requeue: bool = False,
    ) -> BacktestRun | None:
        """Recover one run after an external process/container inspection."""

        now = now or datetime.now(timezone.utc)
        record = self.session.get(BacktestRunRecord, run_id)
        if record is None or record.state != BacktestState.RUNNING.value:
            return None
        if record.lease_expires_at is None or _aware(record.lease_expires_at) >= now:
            return None
        record.state = BacktestState.QUEUED.value if requeue else BacktestState.INTERRUPTED.value
        record.error = "worker lease expired; owned process was not found"
        record.completed_at = None if requeue else now
        record.lease_owner = None
        record.lease_expires_at = None
        self.session.commit()
        self.session.refresh(record)
        return self._to_run(record)

    # Global single-worker lease ----------------------------------------
    def acquire_global_lease(
        self,
        *,
        owner: str,
        run_id: str,
        now: datetime | None = None,
        ttl_seconds: int = 300,
    ) -> bool:
        now = now or datetime.now(timezone.utc)
        expires = now + timedelta(seconds=ttl_seconds)
        lease = self.session.execute(
            select(BacktestLeaseRecord)
            .where(BacktestLeaseRecord.id == GLOBAL_LEASE_ID)
            .with_for_update()
        ).scalar_one_or_none()
        if lease is None:
            lease = BacktestLeaseRecord(
                id=GLOBAL_LEASE_ID,
                owner=owner,
                run_id=run_id,
                acquired_at=now,
                heartbeat_at=now,
                expires_at=expires,
            )
            self.session.add(lease)
            try:
                self.session.commit()
                return True
            except IntegrityError:
                self.session.rollback()
                lease = self.session.execute(
                    select(BacktestLeaseRecord)
                    .where(BacktestLeaseRecord.id == GLOBAL_LEASE_ID)
                    .with_for_update()
                ).scalar_one_or_none()
        if lease is None:
            return False
        active = _aware(lease.expires_at) > now and lease.owner != owner
        if active:
            self.session.rollback()
            return False
        lease.owner = owner
        lease.run_id = run_id
        lease.acquired_at = now
        lease.heartbeat_at = now
        lease.expires_at = expires
        self.session.commit()
        return True

    def renew_global_lease(
        self,
        *,
        owner: str,
        run_id: str,
        now: datetime | None = None,
        ttl_seconds: int = 300,
    ) -> bool:
        now = now or datetime.now(timezone.utc)
        lease = self.session.execute(
            select(BacktestLeaseRecord).where(BacktestLeaseRecord.id == GLOBAL_LEASE_ID)
        ).scalar_one_or_none()
        if lease is None or lease.owner != owner or lease.run_id != run_id:
            return False
        lease.heartbeat_at = now
        lease.expires_at = now + timedelta(seconds=ttl_seconds)
        self.session.commit()
        return True

    def release_global_lease(self, *, owner: str, run_id: str) -> bool:
        lease = self.session.execute(
            select(BacktestLeaseRecord).where(BacktestLeaseRecord.id == GLOBAL_LEASE_ID)
        ).scalar_one_or_none()
        if lease is None or lease.owner != owner or lease.run_id != run_id:
            return False
        self.session.delete(lease)
        self.session.commit()
        return True

    def get_result(self, run_id: str) -> BacktestResult | None:
        result = self.session.execute(
            select(BacktestResultRecord).where(BacktestResultRecord.run_id == run_id)
        ).scalar_one_or_none()
        if result is None:
            return None
        payload = result.raw_payload or {
            "id": result.id,
            "run_id": result.run_id,
            "semantic_hash": result.semantic_hash,
            "metrics": result.metrics_payload,
            "trades": result.trades_payload,
            "equity_curve": result.equity_curve_payload,
            "events": [],
            "warnings": result.warnings,
            "created_at": result.created_at,
        }
        return BacktestResult.model_validate(payload)

    def compare(self, request: BacktestCompareRequest) -> list[dict]:
        rows: list[dict] = []
        for run_id in request.run_ids:
            record = self.session.get(BacktestRunRecord, run_id)
            if record is None:
                continue
            result = self.get_result(run_id)
            rows.append(
                {
                    "run_id": run_id,
                    "state": record.state,
                    "strategy": record.strategy,
                    "symbols": record.symbols,
                    "metrics": result.metrics if result else {},
                    "semantic_hash": result.semantic_hash if result else None,
                }
            )
        return rows

    # Conversion helpers -------------------------------------------------
    @staticmethod
    def _to_dataset(record: BacktestDatasetRecord) -> DatasetSummary:
        validation = None
        if record.validation_payload:
            validation = DatasetValidationReport.model_validate(record.validation_payload)
        return DatasetSummary(
            id=record.id,
            name=record.name,
            root_path=record.root_path,
            provider=record.provider,
            license=record.license,
            provenance=record.provenance,
            symbols=list(record.symbols or []),
            declared_start=record.declared_start,
            declared_end=record.declared_end,
            status=DatasetStatus(record.status),
            manifest_hash=record.manifest_hash,
            data_hash=record.data_hash,
            validation=validation,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _to_run(self, record: BacktestRunRecord, *, idempotent_replayed: bool = False) -> BacktestRun:
        result = self.get_result(record.id)
        return BacktestRun(
            id=record.id,
            dataset_id=record.dataset_id,
            strategy=record.strategy,
            symbols=list(record.symbols or []),
            start_date=record.start_date,
            end_date=record.end_date,
            initial_cash=record.initial_cash,
            state=record.state,
            parameters=record.parameters or {},
            fee_model=FeeModel.model_validate(record.fee_model),
            slippage_model=SlippageModel.model_validate(record.slippage_model),
            lifecycle_model=LifecycleModel.model_validate(record.lifecycle_model),
            run_manifest=record.run_manifest or {},
            code_version=record.code_version,
            engine_version=record.engine_version,
            engine_image_digest=record.engine_image_digest,
            data_hash=record.data_hash,
            process_identity=record.process_identity,
            lease_owner=record.lease_owner,
            lease_expires_at=record.lease_expires_at,
            cancel_requested=record.cancel_requested,
            started_at=record.started_at,
            completed_at=record.completed_at,
            error=record.error,
            result=result,
            created_at=record.created_at,
            updated_at=record.updated_at,
            idempotent_replayed=idempotent_replayed,
        )


def _as_json(value: object) -> dict | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)  # type: ignore[no-any-return]
    return value  # type: ignore[return-value]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value

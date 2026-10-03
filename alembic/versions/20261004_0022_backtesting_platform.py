"""add isolated offline backtesting platform tables

Revision ID: 20261004_0022
Revises: 20261004_0021
Create Date: 2026-10-04 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20261004_0022"
down_revision: Union[str, None] = "20261004_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_json = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "backtest_datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("root_path", sa.String(length=1024), nullable=False),
        sa.Column("provider", sa.String(length=160), nullable=False),
        sa.Column("license", sa.String(length=512), nullable=False),
        sa.Column("provenance", sa.String(length=1024), nullable=False),
        sa.Column("symbols", _json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("declared_start", sa.Date(), nullable=False),
        sa.Column("declared_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("manifest_payload", _json, nullable=True),
        sa.Column("manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("data_hash", sa.String(length=64), nullable=True),
        sa.Column("validation_payload", _json, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_datasets"),
        sa.UniqueConstraint("name", "root_path", name="uq_backtest_datasets_name_root"),
    )
    op.create_index("ix_backtest_datasets_status", "backtest_datasets", ["status"], unique=False)
    op.create_index("ix_backtest_datasets_manifest_hash", "backtest_datasets", ["manifest_hash"], unique=False)
    op.create_index("ix_backtest_datasets_data_hash", "backtest_datasets", ["data_hash"], unique=False)

    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column("symbols", _json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("initial_cash", sa.Numeric(precision=20, scale=6), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("parameters", _json, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fee_model", _json, nullable=False),
        sa.Column("slippage_model", _json, nullable=False),
        sa.Column("lifecycle_model", _json, nullable=False),
        sa.Column("run_manifest", _json, nullable=False),
        sa.Column("code_version", sa.String(length=160), nullable=False),
        sa.Column("engine_version", sa.String(length=120), nullable=False),
        sa.Column("engine_image_digest", sa.String(length=71), nullable=False),
        sa.Column("data_hash", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("process_identity", _json, nullable=True),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("result_summary", _json, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["backtest_datasets.id"], name="fk_backtest_runs_dataset_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_runs"),
        sa.UniqueConstraint("idempotency_key", name="uq_backtest_runs_idempotency_key"),
    )
    op.create_index("ix_backtest_runs_dataset_id", "backtest_runs", ["dataset_id"], unique=False)
    op.create_index("ix_backtest_runs_strategy", "backtest_runs", ["strategy"], unique=False)
    op.create_index("ix_backtest_runs_state", "backtest_runs", ["state"], unique=False)
    op.create_index("ix_backtest_runs_state_created", "backtest_runs", ["state", "created_at"], unique=False)
    op.create_index("ix_backtest_runs_dataset_state", "backtest_runs", ["dataset_id", "state"], unique=False)
    op.create_index("ix_backtest_runs_data_hash", "backtest_runs", ["data_hash"], unique=False)
    op.create_index("ix_backtest_runs_lease_owner", "backtest_runs", ["lease_owner"], unique=False)
    op.create_index("ix_backtest_runs_lease_expires_at", "backtest_runs", ["lease_expires_at"], unique=False)

    op.create_table(
        "backtest_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("semantic_hash", sa.String(length=64), nullable=False),
        sa.Column("metrics_payload", _json, nullable=False),
        sa.Column("trades_payload", _json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("equity_curve_payload", _json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("warnings", _json, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("raw_payload", _json, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["run_id"], ["backtest_runs.id"], name="fk_backtest_results_run_id", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_results"),
        sa.UniqueConstraint("run_id", name="uq_backtest_results_run_id"),
    )
    op.create_index("ix_backtest_results_run_id", "backtest_results", ["run_id"], unique=False)
    op.create_index("ix_backtest_results_semantic_hash", "backtest_results", ["semantic_hash"], unique=False)

    op.create_table(
        "backtest_leases",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("owner", sa.String(length=128), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_backtest_leases"),
    )
    op.create_index("ix_backtest_leases_run_id", "backtest_leases", ["run_id"], unique=False)
    op.create_index("ix_backtest_leases_expires_at", "backtest_leases", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_backtest_leases_expires_at", table_name="backtest_leases")
    op.drop_index("ix_backtest_leases_run_id", table_name="backtest_leases")
    op.drop_table("backtest_leases")
    op.drop_index("ix_backtest_results_semantic_hash", table_name="backtest_results")
    op.drop_index("ix_backtest_results_run_id", table_name="backtest_results")
    op.drop_table("backtest_results")
    op.drop_index("ix_backtest_runs_lease_expires_at", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_lease_owner", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_data_hash", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_dataset_state", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_state_created", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_state", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_strategy", table_name="backtest_runs")
    op.drop_index("ix_backtest_runs_dataset_id", table_name="backtest_runs")
    op.drop_table("backtest_runs")
    op.drop_index("ix_backtest_datasets_data_hash", table_name="backtest_datasets")
    op.drop_index("ix_backtest_datasets_manifest_hash", table_name="backtest_datasets")
    op.drop_index("ix_backtest_datasets_status", table_name="backtest_datasets")
    op.drop_table("backtest_datasets")

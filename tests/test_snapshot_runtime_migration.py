import importlib.util
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20261004_0020_snapshot_runtime_mode_provenance.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("snapshot_runtime_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RecordingOp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def test_snapshot_runtime_migration_is_additive_and_does_not_invent_legacy_mode(monkeypatch) -> None:
    migration = load_migration()
    recorder = RecordingOp()
    monkeypatch.setattr(migration, "op", recorder)

    migration.upgrade()

    assert migration.revision == "20261004_0020"
    assert migration.down_revision == "20261002_0019"
    update_statements = [
        str(args[0])
        for name, args, _kwargs in recorder.calls
        if name == "execute"
    ]
    assert any("provenance = 'legacy_unknown'" in statement for statement in update_statements)
    assert all("execution_mode" not in statement for statement in update_statements)

    unique_constraints = [
        args
        for name, args, _kwargs in recorder.calls
        if name == "create_unique_constraint"
    ]
    assert any(
        args[0] == "uq_bull_put_strategy_runtime_account_strategy_mode"
        and args[2] == ["external_account_id", "strategy_id", "execution_mode"]
        for args in unique_constraints
    )
    check_constraints = [
        args[0]
        for name, args, _kwargs in recorder.calls
        if name == "create_check_constraint"
    ]
    assert "ck_account_snapshots_execution_mode" in check_constraints
    assert "ck_account_snapshots_provenance" in check_constraints
    indexes = [
        args[0]
        for name, args, _kwargs in recorder.calls
        if name == "create_index"
    ]
    assert "ix_account_snapshots_mode_captured_id" in indexes


class ConflictResult:
    def mappings(self):
        return self

    def all(self):
        return [{"external_account_id": "LBPT10087357", "strategy_id": "paper_bull_put_v1", "row_count": 2}]


class ConflictOp(RecordingOp):
    def get_bind(self):
        return self

    def execute(self, _statement):
        return ConflictResult()


def test_downgrade_refuses_runtime_mode_collisions_before_destructive_steps(monkeypatch) -> None:
    migration = load_migration()
    recorder = ConflictOp()
    monkeypatch.setattr(migration, "op", recorder)

    import pytest

    with pytest.raises(RuntimeError, match="mode-specific Bull Put runtime"):
        migration.downgrade()

    assert [name for name, _args, _kwargs in recorder.calls] == []

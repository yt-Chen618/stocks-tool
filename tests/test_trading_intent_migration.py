import importlib.util
from pathlib import Path

import pytest


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "20260711_0016_trading_intent_ledger.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("trading_intent_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def mappings(self) -> "FakeResult":
        return self

    def all(self) -> list[dict]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return FakeResult(self.rows)


def test_duplicate_preflight_is_read_only_and_passes_for_unique_orders(monkeypatch) -> None:
    migration = load_migration()
    connection = FakeConnection([])
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    migration._assert_external_order_ids_are_unique()

    assert "SELECT broker, execution_mode, external_order_id" in str(connection.statement)
    assert "HAVING COUNT(*) > 1" in str(connection.statement)


def test_duplicate_preflight_aborts_with_duplicate_details(monkeypatch) -> None:
    migration = load_migration()
    connection = FakeConnection(
        [
            {
                "broker": "longbridge",
                "execution_mode": "paper",
                "external_order_id": "duplicate-123",
                "duplicate_count": 2,
            }
        ]
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: connection)

    with pytest.raises(RuntimeError, match="duplicate-123") as exc_info:
        migration._assert_external_order_ids_are_unique()

    assert "count=2" in str(exc_info.value)

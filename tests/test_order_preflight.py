from stocks_tool.application.services.order_preflight import (
    find_duplicate_external_order_ids,
)


class FakeMappingsResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def mappings(self) -> "FakeMappingsResult":
        return self

    def all(self) -> list[dict]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return FakeMappingsResult(self.rows)


def test_duplicate_external_order_id_preflight_returns_structured_rows() -> None:
    connection = FakeConnection(
        [
            {
                "broker": "longbridge",
                "execution_mode": "paper",
                "external_order_id": "duplicate-1",
                "duplicate_count": 2,
            }
        ]
    )

    duplicates = find_duplicate_external_order_ids(connection)

    assert [duplicate.to_dict() for duplicate in duplicates] == [
        {
            "broker": "longbridge",
            "execution_mode": "paper",
            "external_order_id": "duplicate-1",
            "duplicate_count": 2,
        }
    ]
    assert "HAVING COUNT(*) > 1" in str(connection.statement)

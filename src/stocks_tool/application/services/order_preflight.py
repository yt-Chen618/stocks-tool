from dataclasses import asdict, dataclass

from sqlalchemy import text
from sqlalchemy.engine import Connection


DUPLICATE_EXTERNAL_ORDER_IDS_SQL = text(
    """
    SELECT broker, execution_mode, external_order_id, COUNT(*) AS duplicate_count
    FROM orders
    WHERE external_order_id IS NOT NULL
    GROUP BY broker, execution_mode, external_order_id
    HAVING COUNT(*) > 1
    ORDER BY broker, execution_mode, external_order_id
    """
)


@dataclass(frozen=True)
class DuplicateExternalOrderId:
    broker: str
    execution_mode: str
    external_order_id: str
    duplicate_count: int

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def find_duplicate_external_order_ids(
    connection: Connection,
) -> list[DuplicateExternalOrderId]:
    rows = connection.execute(DUPLICATE_EXTERNAL_ORDER_IDS_SQL).mappings().all()
    return [
        DuplicateExternalOrderId(
            broker=str(row["broker"]),
            execution_mode=str(row["execution_mode"]),
            external_order_id=str(row["external_order_id"]),
            duplicate_count=int(row["duplicate_count"]),
        )
        for row in rows
    ]

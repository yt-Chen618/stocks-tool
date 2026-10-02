from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from stocks_tool.api.dependencies import get_bull_put_strategy_service
from stocks_tool.db.base import Base
from stocks_tool.db.models import BrokerAccountRecord, BullPutSpreadRecord
from stocks_tool.domain.enums import BrokerName, ExecutionMode, SpreadStatus
from stocks_tool.main import app
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import (
    SQLAlchemyBullPutSpreadRepository,
)

from tests.test_bull_put_spread_repository import _history_record
from tests.test_bull_put_strategy import build_service


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def _build_api_service():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    session.add(
        BrokerAccountRecord(
            id="broker-LBPT10087357",
            broker=BrokerName.LONGBRIDGE.value,
            external_account_id="LBPT10087357",
        )
    )
    session.add_all(
        [
            _history_record(
                spread_id="paper-0",
                account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                status=SpreadStatus.OPEN,
                created_at=datetime(2026, 10, 2, 14, 30, tzinfo=timezone.utc),
            ),
            _history_record(
                spread_id="paper-1",
                account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                status=SpreadStatus.CLOSED,
                created_at=datetime(2026, 10, 2, 14, 29, tzinfo=timezone.utc),
            ),
            _history_record(
                spread_id="paper-manual",
                account_id="LBPT10087357",
                mode=ExecutionMode.PAPER,
                status=SpreadStatus.CLOSED,
                created_at=datetime(2026, 10, 2, 14, 28, tzinfo=timezone.utc),
                manual_action_required=True,
            ),
        ]
    )
    session.commit()
    service, _, _, _ = build_service()
    service.spreads = SQLAlchemyBullPutSpreadRepository(session)
    return service, engine


def test_bull_put_history_page_and_legacy_detail_route_use_real_sqlite_repository() -> None:
    service, engine = _build_api_service()
    app.dependency_overrides[get_bull_put_strategy_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/strategies/bull-put/spreads/paged",
            params={"external_account_id": "LBPT10087357", "mode": "paper", "limit": 2},
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"]

        next_response = client.get(
            "/strategies/bull-put/spreads/paged",
            params={
                "external_account_id": "LBPT10087357",
                "mode": "paper",
                "limit": 2,
                "cursor": body["next_cursor"],
            },
        )
        assert next_response.status_code == 200
        next_body = next_response.json()
        assert {item["id"] for item in body["items"]}.isdisjoint(
            item["id"] for item in next_body["items"]
        )

        detail = client.get("/strategies/bull-put/spreads/paper-1")
        assert detail.status_code == 200
        assert detail.json()["id"] == "paper-1"
    finally:
        app.dependency_overrides.clear()
        session = service.spreads.session
        session.close()
        engine.dispose()


def test_working_spreads_route_keeps_active_and_manual_rows() -> None:
    service, engine = _build_api_service()
    app.dependency_overrides[get_bull_put_strategy_service] = lambda: service
    client = TestClient(app)
    try:
        response = client.get(
            "/strategies/bull-put/working-spreads",
            params={"external_account_id": "LBPT10087357"},
        )
        assert response.status_code == 200
        assert {item["id"] for item in response.json()} == {"paper-0", "paper-manual"}
    finally:
        app.dependency_overrides.clear()
        session = service.spreads.session
        session.close()
        engine.dispose()

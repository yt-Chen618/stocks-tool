from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.domain.enums import MarketEventType
from stocks_tool.domain.models import CreateMarketEventRequest
from stocks_tool.repositories.sqlalchemy_market_event_repository import (
    SQLAlchemyMarketEventRepository,
)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def test_list_events_filters_symbols_before_applying_limit() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 8, 10, 14, 30, tzinfo=timezone.utc)
    try:
        with Session(engine, expire_on_commit=False) as session:
            repository = SQLAlchemyMarketEventRepository(session)
            for index in range(2):
                repository.create_event(
                    CreateMarketEventRequest(
                        symbol=f"OTHER{index}.US",
                        event_type=MarketEventType.EARNINGS,
                        title=f"Other event {index}",
                        scheduled_at=now + timedelta(days=index),
                    )
                )
            repository.create_event(
                CreateMarketEventRequest(
                    symbol="TARGET.US",
                    event_type=MarketEventType.EARNINGS,
                    title="Target event",
                    scheduled_at=now + timedelta(days=10),
                )
            )

            events = repository.list_events(
                symbols=["TARGET.US"],
                start=now,
                end=now + timedelta(days=30),
                limit=1,
            )

            assert [event.symbol for event in events] == ["TARGET.US"]
    finally:
        engine.dispose()

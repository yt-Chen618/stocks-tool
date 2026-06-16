from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from stocks_tool.application.services.strategy_lifecycle import BULL_PUT_CLOSE_ORDER_WARNING
from stocks_tool.db.models import BullPutSpreadRecord
from stocks_tool.domain.enums import BrokerName, ExecutionMode, SpreadStatus
from stocks_tool.domain.models import BullPutSpread
from stocks_tool.repositories.sqlalchemy_bull_put_spread_repository import SQLAlchemyBullPutSpreadRepository


NOW = datetime(2026, 6, 15, 14, 45, tzinfo=timezone.utc)


def _spread(**updates) -> BullPutSpread:
    return BullPutSpread(
        id="spread-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        underlying_symbol="QQQ.US",
        expiration_date=date(2026, 6, 19),
        contracts=1,
        width=Decimal("2"),
        long_symbol="QQQ260619P448000.US",
        long_strike=Decimal("448"),
        short_symbol="QQQ260619P450000.US",
        short_strike=Decimal("450"),
        status=SpreadStatus.OPEN,
        short_exit_order_id="short-exit",
        created_at=NOW,
        updated_at=NOW,
        **updates,
    )


def test_bull_put_spread_repository_maps_lifecycle_summary_from_raw_payload(monkeypatch) -> None:
    repo = SQLAlchemyBullPutSpreadRepository(Mock())
    monkeypatch.setattr(
        SQLAlchemyBullPutSpreadRepository,
        "_resolve_broker_account_id",
        staticmethod(lambda session, spread: "broker-account-1"),
    )
    next_monitor_after = datetime(2026, 6, 15, 14, 50, tzinfo=timezone.utc)
    spread = _spread(
        raw_payload={
            "monitor": {
                "should_close": True,
                "next_monitor_after": next_monitor_after.isoformat(),
            },
            "lifecycle": {
                "warning": BULL_PUT_CLOSE_ORDER_WARNING,
                "manual_action_required": True,
                "close_order_state": "CANCELED",
            },
        }
    )
    record = BullPutSpreadRecord(id=spread.id)

    repo._apply_spread(record, spread)
    record.created_at = NOW
    record.updated_at = NOW
    domain = repo._to_domain(record)

    assert record.lifecycle_warning_code == BULL_PUT_CLOSE_ORDER_WARNING
    assert record.manual_action_required is True
    assert record.latest_monitor_should_close is True
    assert record.latest_close_order_status == "canceled"
    assert record.next_monitor_after == next_monitor_after
    assert domain.lifecycle_warning_code == BULL_PUT_CLOSE_ORDER_WARNING
    assert domain.manual_action_required is True
    assert domain.latest_monitor_should_close is True
    assert domain.latest_close_order_status == "canceled"
    assert domain.next_monitor_after == next_monitor_after


def test_bull_put_spread_repository_preserves_explicit_lifecycle_fields_without_raw_payload(monkeypatch) -> None:
    repo = SQLAlchemyBullPutSpreadRepository(Mock())
    monkeypatch.setattr(
        SQLAlchemyBullPutSpreadRepository,
        "_resolve_broker_account_id",
        staticmethod(lambda session, spread: "broker-account-1"),
    )
    spread = _spread(
        raw_payload=None,
        lifecycle_warning_code=BULL_PUT_CLOSE_ORDER_WARNING,
        manual_action_required=True,
        latest_monitor_should_close=True,
        latest_close_order_status="canceled",
        next_monitor_after=NOW,
    )
    record = BullPutSpreadRecord(id=spread.id)

    repo._apply_spread(record, spread)

    assert record.lifecycle_warning_code == BULL_PUT_CLOSE_ORDER_WARNING
    assert record.manual_action_required is True
    assert record.latest_monitor_should_close is True
    assert record.latest_close_order_status == "canceled"
    assert record.next_monitor_after == NOW

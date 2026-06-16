from datetime import datetime, timezone

from stocks_tool.application.services.strategy_lifecycle import (
    BULL_PUT_CLOSE_ORDER_WARNING,
    bull_put_close_order_lifecycle_payload,
    bull_put_close_order_warning,
    bull_put_lifecycle_summary,
)


def test_bull_put_close_order_warning_detects_failed_required_close_order() -> None:
    warning = bull_put_close_order_warning(
        spread_status="open",
        short_exit_order_id="short-exit",
        short_exit_order_status="canceled",
        short_symbol="QQQ260619P450000.US",
        raw_payload={"monitor": {"should_close": True, "exit_reason": "stop_loss"}},
        orders_by_id={"short-exit": {"status": "canceled", "symbol": "QQQ260619P450000.US", "side": "buy"}},
    )

    assert warning == {
        "code": BULL_PUT_CLOSE_ORDER_WARNING,
        "message": "Close order canceled / manual action needed",
        "detail": "Latest monitor still requires close, but the linked short-leg close order is no longer working.",
        "order_id": "short-exit",
        "order_status": "canceled",
        "exit_reason": "stop_loss",
        "manual_action_required": True,
    }


def test_bull_put_close_order_warning_ignores_working_replacement_close_order() -> None:
    warning = bull_put_close_order_warning(
        spread_status="open",
        short_exit_order_id="short-exit",
        short_exit_order_status="rejected",
        short_symbol="QQQ260619P450000.US",
        raw_payload={"monitor": {"should_close": True}},
        orders_by_id={
            "short-exit": {"status": "rejected", "symbol": "QQQ260619P450000.US", "side": "buy"},
            "replacement": {"status": "submitted", "symbol": "QQQ260619P450000.US", "side": "buy"},
        },
    )

    assert warning is None


def test_bull_put_close_order_warning_uses_normalized_lifecycle_fields() -> None:
    warning = bull_put_close_order_warning(
        spread_status="open",
        short_exit_order_id="short-exit",
        short_exit_order_status="canceled",
        latest_monitor_should_close=True,
        lifecycle_warning_code=BULL_PUT_CLOSE_ORDER_WARNING,
    )

    assert warning is not None
    assert warning["code"] == BULL_PUT_CLOSE_ORDER_WARNING
    assert warning["order_status"] == "canceled"
    assert warning["manual_action_required"] is True


def test_bull_put_close_order_lifecycle_payload_writes_and_clears_warning() -> None:
    warning = bull_put_close_order_warning(
        spread_status="open",
        short_exit_order_id="short-exit",
        short_exit_order_status="canceled",
        raw_payload={"monitor": {"should_close": True, "exit_reason": "strike_breach"}},
    )

    payload = bull_put_close_order_lifecycle_payload(
        raw_payload={"monitor": {"should_close": True, "exit_reason": "strike_breach"}},
        warning=warning,
    )
    assert payload is not None
    assert payload["lifecycle"]["warning"] == BULL_PUT_CLOSE_ORDER_WARNING
    assert payload["lifecycle"]["manual_action_required"] is True
    assert payload["lifecycle"]["close_order_id"] == "short-exit"
    assert payload["lifecycle"]["close_order_state"] == "canceled"

    cleared = bull_put_close_order_lifecycle_payload(
        raw_payload=payload,
        warning=None,
    )
    assert cleared == {"monitor": {"should_close": True, "exit_reason": "strike_breach"}}


def test_bull_put_lifecycle_summary_extracts_queryable_fields() -> None:
    next_monitor_after = datetime(2026, 6, 15, 14, 55, tzinfo=timezone.utc)

    summary = bull_put_lifecycle_summary(
        {
            "monitor": {
                "should_close": "true",
                "next_monitor_after": next_monitor_after.isoformat(),
            },
            "lifecycle": {
                "warning": BULL_PUT_CLOSE_ORDER_WARNING,
                "manual_action_required": True,
                "close_order_state": "CANCELED",
            },
        }
    )

    assert summary == {
        "lifecycle_warning_code": BULL_PUT_CLOSE_ORDER_WARNING,
        "manual_action_required": True,
        "latest_monitor_should_close": True,
        "latest_close_order_status": "canceled",
        "next_monitor_after": next_monitor_after,
    }


def test_bull_put_lifecycle_summary_clears_when_raw_payload_has_no_lifecycle_state() -> None:
    assert bull_put_lifecycle_summary({}) == {
        "lifecycle_warning_code": None,
        "manual_action_required": False,
        "latest_monitor_should_close": None,
        "latest_close_order_status": None,
        "next_monitor_after": None,
    }

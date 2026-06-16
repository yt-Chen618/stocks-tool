from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any


BULL_PUT_CLOSE_ORDER_WARNING = "close_order_canceled_manual_action_needed"
BULL_PUT_CLOSE_ORDER_DETAIL = (
    "Latest monitor still requires close, but the linked short-leg close order is no longer working."
)
FAILED_BULL_PUT_CLOSE_ORDER_STATUSES = frozenset({"canceled", "rejected"})
WORKING_BULL_PUT_CLOSE_ORDER_STATUSES = frozenset({"created", "submitted", "partially_filled"})


def bull_put_close_order_warning(
    *,
    spread_status: Any,
    short_exit_order_id: Any,
    short_exit_order_status: Any,
    short_symbol: Any = None,
    raw_payload: Mapping[str, Any] | None = None,
    exit_reason: Any = None,
    orders_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    latest_monitor_should_close: Any = None,
    lifecycle_warning_code: Any = None,
    manual_action_required: Any = None,
) -> dict[str, Any] | None:
    """Return the canonical manual-action warning for a failed bull-put close order."""
    if short_exit_order_id is None:
        return None
    order_status = _normalized_status(short_exit_order_status)
    if order_status not in FAILED_BULL_PUT_CLOSE_ORDER_STATUSES:
        return None
    if has_working_replacement_bull_put_close_order(
        short_symbol=short_symbol,
        short_exit_order_id=short_exit_order_id,
        orders_by_id=orders_by_id,
    ):
        return None

    payload = dict(raw_payload or {})
    monitor = _mapping_or_empty(payload.get("monitor"))
    lifecycle = _mapping_or_empty(payload.get("lifecycle"))
    monitor_requires_close = _normalized_status(spread_status) == "open" and (
        _truthy(monitor.get("should_close")) or _truthy(latest_monitor_should_close)
    )
    lifecycle_requires_action = (
        lifecycle.get("warning") == BULL_PUT_CLOSE_ORDER_WARNING
        or lifecycle.get("manual_action_required") is True
        or lifecycle_warning_code == BULL_PUT_CLOSE_ORDER_WARNING
        or _truthy(manual_action_required)
    )
    if not monitor_requires_close and not lifecycle_requires_action:
        return None

    order_id = str(short_exit_order_id)
    return {
        "code": BULL_PUT_CLOSE_ORDER_WARNING,
        "message": "Close order canceled / manual action needed",
        "detail": BULL_PUT_CLOSE_ORDER_DETAIL,
        "order_id": order_id,
        "order_status": order_status,
        "exit_reason": monitor.get("exit_reason") or lifecycle.get("exit_reason") or exit_reason,
        "manual_action_required": True,
    }


def bull_put_lifecycle_summary(raw_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = dict(raw_payload or {})
    monitor = _mapping_or_empty(payload.get("monitor"))
    lifecycle = _mapping_or_empty(payload.get("lifecycle"))
    warning_code = _str_or_none(lifecycle.get("warning"))
    return {
        "lifecycle_warning_code": warning_code,
        "manual_action_required": bool(warning_code) or _truthy(lifecycle.get("manual_action_required")),
        "latest_monitor_should_close": _optional_bool(monitor.get("should_close")),
        "latest_close_order_status": _normalized_status_or_none(lifecycle.get("close_order_state")),
        "next_monitor_after": _parse_datetime(monitor.get("next_monitor_after")),
    }


def has_working_replacement_bull_put_close_order(
    *,
    short_symbol: Any,
    short_exit_order_id: Any,
    orders_by_id: Mapping[str, Mapping[str, Any]] | None,
) -> bool:
    if not short_symbol or short_exit_order_id is None or not orders_by_id:
        return False
    close_order_id = str(short_exit_order_id)
    for order_id, order in orders_by_id.items():
        if str(order_id) == close_order_id:
            continue
        if _normalized_status(order.get("status")) not in WORKING_BULL_PUT_CLOSE_ORDER_STATUSES:
            continue
        if order.get("symbol") != short_symbol:
            continue
        if str(order.get("side") or "").lower() != "buy":
            continue
        return True
    return False


def bull_put_close_order_lifecycle_payload(
    *,
    raw_payload: Mapping[str, Any] | None,
    warning: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    payload = dict(raw_payload or {})
    lifecycle = dict(_mapping_or_empty(payload.get("lifecycle")))
    if warning is not None:
        lifecycle.update(
            {
                "warning": warning["code"],
                "manual_action_required": True,
                "close_order_id": warning["order_id"],
                "close_order_state": warning["order_status"],
                "exit_reason": warning.get("exit_reason"),
                "detail": warning["detail"],
            }
        )
        payload["lifecycle"] = lifecycle
        return payload

    if lifecycle.get("warning") != BULL_PUT_CLOSE_ORDER_WARNING:
        return None

    for key in (
        "warning",
        "manual_action_required",
        "close_order_id",
        "close_order_state",
        "exit_reason",
        "detail",
    ):
        lifecycle.pop(key, None)
    if lifecycle:
        payload["lifecycle"] = lifecycle
    else:
        payload.pop("lifecycle", None)
    return payload


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalized_status(value: Any) -> str:
    if hasattr(value, "value"):
        value = value.value
    return str(value or "").strip().lower()


def _normalized_status_or_none(value: Any) -> str | None:
    normalized = _normalized_status(value)
    return normalized or None


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if value is True or value is False:
        return value
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"

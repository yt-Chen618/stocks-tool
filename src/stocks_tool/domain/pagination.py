from __future__ import annotations

import base64
import binascii
import json
from typing import Generic, TypeVar

from pydantic import BaseModel, Field


ItemT = TypeVar("ItemT")


class CursorPage(BaseModel, Generic[ItemT]):
    """A bounded read page returned by an explicit paged endpoint.

    The legacy list endpoints deliberately keep their complete-list contract.
    CursorPage is used only by callers that opt into a paged read route.
    """

    items: list[ItemT] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False
    limit: int = Field(ge=1, le=100)


class CursorError(ValueError):
    """Raised when an opaque cursor is malformed or used with another query."""


def encode_cursor(
    *,
    resource: str,
    scope: dict[str, object],
    position: dict[str, object],
) -> str:
    payload = {
        "version": 1,
        "resource": resource,
        "scope": scope,
        "position": position,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(
    cursor: str,
    *,
    resource: str,
    scope: dict[str, object],
) -> dict[str, object]:
    if not cursor or len(cursor) > 4096:
        raise CursorError("Invalid pagination cursor.")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeEncodeError, UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise CursorError("Invalid pagination cursor.") from exc
    if not isinstance(payload, dict):
        raise CursorError("Invalid pagination cursor.")
    if payload.get("version") != 1 or payload.get("resource") != resource:
        raise CursorError("Pagination cursor does not match this resource.")
    if payload.get("scope") != scope:
        raise CursorError("Pagination cursor does not match this query.")
    position = payload.get("position")
    if not isinstance(position, dict):
        raise CursorError("Invalid pagination cursor position.")
    return position


def normalize_page_limit(limit: int | None, *, default: int = 50, maximum: int = 100) -> int:
    value = default if limit is None else limit
    if value < 1 or value > maximum:
        raise ValueError(f"Pagination limit must be between 1 and {maximum}.")
    return value

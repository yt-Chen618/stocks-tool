from datetime import datetime, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_watchlist_repository
from stocks_tool.domain.models import Watchlist
from stocks_tool.main import app
from stocks_tool.ports.repository import WatchlistItemConflictError


NOW = datetime(2026, 8, 10, 14, 30, tzinfo=timezone.utc)


def _watchlist() -> Watchlist:
    return Watchlist(
        id="watch-1",
        name="Research",
        description="Primary list",
        is_default=True,
        items=[],
        created_at=NOW,
        updated_at=NOW,
    )


def test_patch_watchlist_and_item_routes() -> None:
    repository = Mock()
    repository.update_watchlist.return_value = _watchlist()
    repository.update_item.return_value = _watchlist()
    app.dependency_overrides[get_watchlist_repository] = lambda: repository
    client = TestClient(app)
    try:
        watchlist_response = client.patch(
            "/watchlists/watch-1",
            json={"name": "Research", "is_default": True},
        )
        item_response = client.patch(
            "/watchlists/watch-1/items/item-1",
            json={"notes": "Watch the event window"},
        )
    finally:
        app.dependency_overrides.clear()

    assert watchlist_response.status_code == 200
    assert item_response.status_code == 200
    assert repository.update_watchlist.call_args.args[0] == "watch-1"
    assert repository.update_watchlist.call_args.args[1].name == "Research"
    assert repository.update_item.call_args.args[:2] == ("watch-1", "item-1")
    assert repository.update_item.call_args.args[2].notes == "Watch the event window"


def test_delete_watchlist_item_route_and_not_found() -> None:
    repository = Mock()
    repository.delete_item.side_effect = [True, False]
    app.dependency_overrides[get_watchlist_repository] = lambda: repository
    client = TestClient(app)
    try:
        deleted = client.delete("/watchlists/watch-1/items/item-1")
        missing = client.delete("/watchlists/watch-1/items/missing")
    finally:
        app.dependency_overrides.clear()

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert missing.status_code == 404


def test_patch_watchlist_rejects_empty_payload() -> None:
    repository = Mock()
    app.dependency_overrides[get_watchlist_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.patch("/watchlists/watch-1", json={})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    repository.update_watchlist.assert_not_called()


def test_patch_watchlist_rejects_blank_name() -> None:
    repository = Mock()
    app.dependency_overrides[get_watchlist_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.patch("/watchlists/watch-1", json={"name": "   "})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "Watchlist name cannot be blank."
    repository.update_watchlist.assert_not_called()


def test_create_watchlist_rejects_blank_name() -> None:
    repository = Mock()
    app.dependency_overrides[get_watchlist_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.post("/watchlists", json={"name": "   "})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "Watchlist name cannot be blank."
    repository.create_watchlist.assert_not_called()


def test_add_watchlist_item_maps_duplicate_symbol_to_conflict() -> None:
    repository = Mock()
    repository.add_item.side_effect = WatchlistItemConflictError("QQQ.US")
    app.dependency_overrides[get_watchlist_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.post(
            "/watchlists/watch-1/items",
            json={"symbol": " QQQ.US ", "asset_type": "etf"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json()["detail"] == "Watchlist already contains symbol QQQ.US."


def test_add_watchlist_item_rejects_blank_symbol_at_request_boundary() -> None:
    repository = Mock()
    app.dependency_overrides[get_watchlist_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.post(
            "/watchlists/watch-1/items",
            json={"symbol": "   ", "asset_type": "stock"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    repository.add_item.assert_not_called()

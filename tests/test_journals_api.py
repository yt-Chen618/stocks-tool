from datetime import datetime, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient

from stocks_tool.api.dependencies import get_journal_repository, get_journal_service
from stocks_tool.domain.enums import JournalEntryType
from stocks_tool.domain.models import JournalEntry
from stocks_tool.main import app


def build_journal_entry() -> JournalEntry:
    now = datetime(2026, 5, 22, 10, 40, tzinfo=timezone.utc)
    return JournalEntry(
        id="journal-123",
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        entry_type=JournalEntryType.REVIEW,
        title="Filled order review",
        notes="Held the entry plan and exited on schedule.",
        order_id="order-123",
        trade_plan_id="plan-123",
        execution_id="execution-123",
        tags=["filled", "discipline"],
        created_at=now,
        updated_at=now,
    )


def with_journal_dependencies(repository: Mock | None = None, service: Mock | None = None) -> TestClient:
    if repository is not None:
        app.dependency_overrides[get_journal_repository] = lambda: repository
    if service is not None:
        app.dependency_overrides[get_journal_service] = lambda: service
    return TestClient(app)


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def test_list_journals_filters_by_account_order_and_type() -> None:
    repository = Mock()
    repository.list_entries.return_value = [build_journal_entry()]

    client = with_journal_dependencies(repository=repository)
    try:
        response = client.get(
            "/journals",
            params={
                "external_account_id": "LBPT10087357",
                "order_id": "order-123",
                "entry_type": "review",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == "journal-123"
    assert body[0]["entry_type"] == "review"
    repository.list_entries.assert_called_once_with(
        external_account_id="LBPT10087357",
        order_id="order-123",
        trade_plan_id=None,
        entry_type=JournalEntryType.REVIEW,
    )


def test_create_journal_entry_returns_created_entry() -> None:
    service = Mock()
    service.create_entry.return_value = build_journal_entry()

    client = with_journal_dependencies(service=service)
    try:
        response = client.post(
            "/journals",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "entry_type": "review",
                "title": "Filled order review",
                "notes": "Held the entry plan and exited on schedule.",
                "order_id": "order-123",
                "execution_id": "execution-123",
                "tags": ["filled", "discipline"],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "journal-123"
    assert body["symbol"] == "UNH.US"
    assert body["entry_type"] == "review"
    request = service.create_entry.call_args.args[0]
    assert request.order_id == "order-123"
    assert request.entry_type == JournalEntryType.REVIEW


def test_create_journal_entry_maps_lookup_error_to_404() -> None:
    service = Mock()
    service.create_entry.side_effect = LookupError("Order 'missing-order' was not found.")

    client = with_journal_dependencies(service=service)
    try:
        response = client.post(
            "/journals",
            json={
                "external_account_id": "LBPT10087357",
                "symbol": "UNH.US",
                "entry_type": "note",
                "title": "Missing order note",
                "notes": "This order should fail lookup.",
                "order_id": "missing-order",
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Order 'missing-order' was not found."

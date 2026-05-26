from fastapi.testclient import TestClient

from stocks_tool.main import app


def test_dashboard_includes_holdings_and_order_sections() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Auto Reconciliation" in response.text
    assert "Account Sync" in response.text
    assert "Orders Sync" in response.text
    assert "Holdings Overview" in response.text
    assert "Current Holdings" in response.text
    assert "Pre-open Risk Board" in response.text
    assert "Risk Proxies" in response.text
    assert "QQQ / SPY Put Check" in response.text
    assert "Option Chain Analysis" in response.text
    assert "Opening Follow-through" in response.text
    assert "Longbridge Status" in response.text
    assert "Quick Quote" in response.text
    assert "Order Ticket" in response.text
    assert "Selected Order" in response.text
    assert "Execution Summary" in response.text
    assert "Latest Fill Snapshot" in response.text
    assert "Review Workflow" in response.text
    assert "Save Entry" in response.text
    assert "Bull Put Strategy" in response.text
    assert "Entry Status" in response.text
    assert "Latest Skip Reason" in response.text
    assert "Run Scan" in response.text
    assert "Run Review" in response.text
    assert "Latest Review" in response.text
    assert "Bull Put Monitor" in response.text
    assert "Bull Put Spreads" in response.text
    assert "Latest Exit Action" in response.text
    assert "Orders" in response.text
    assert "Positions" in response.text

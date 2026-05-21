from fastapi.testclient import TestClient

from stocks_tool.main import app


def test_dashboard_includes_holdings_and_order_sections() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert "Holdings Overview" in response.text
    assert "Current Holdings" in response.text
    assert "Order Ticket" in response.text
    assert "Selected Order" in response.text
    assert "Orders" in response.text
    assert "Positions" in response.text

from fastapi.testclient import TestClient

from stocks_tool.main import app


def test_dashboard_includes_holdings_and_order_sections() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert 'data-lang-option="zh"' in response.text
    assert 'data-lang-option="en"' in response.text
    assert "Auto Reconciliation" in response.text
    assert "Account Sync" in response.text
    assert "Orders Sync" in response.text
    assert "Strategy Center" in response.text
    assert "Holdings Overview" in response.text
    assert "Real-time Macro Board" in response.text
    assert "Load Live Macro" in response.text
    assert "Load Option Overlays" in response.text
    assert "Save Current Board" in response.text
    assert "Risk Proxies" in response.text
    assert "QQQ / SPY Put Check" in response.text
    assert "Option Chain Analysis" in response.text
    assert "Stored Opening Follow-through" in response.text
    assert "Execution Desk" in response.text
    assert "Order Ticket" in response.text
    assert "Selected Order" in response.text
    assert "Execution Summary" in response.text
    assert "Latest Fill Snapshot" in response.text
    assert "Review Workflow" in response.text
    assert "Save Entry" in response.text
    assert "Bull Put Strategy" in response.text
    assert "Strategy Experiment Bench" in response.text
    assert "Market Event Calendar" in response.text
    assert "Strategy Proposals" in response.text
    assert "Strategy Runs" in response.text
    assert "Signal Feed" in response.text
    assert "Review Feed" in response.text
    assert "Upcoming Events" in response.text
    assert "Entry Status" in response.text
    assert "Next Action" in response.text
    assert "Latest Skip Reason" in response.text
    assert "Run Scan" in response.text
    assert "Run Review" in response.text
    assert "Latest Review" in response.text
    assert "Bull Put Monitor" in response.text
    assert "Entry / Risk" in response.text
    assert "Monitor Mark" in response.text
    assert "PnL / Exit Distance" in response.text
    assert "Last Monitor" in response.text
    assert "Orders" in response.text
    assert "Positions" in response.text
    assert response.text.index("Bull Put Strategy") < response.text.index("Real-time Macro Board")
    assert "Watchlists" not in response.text
    assert "Longbridge Status" not in response.text
    assert "Quick Quote" not in response.text
    assert '/static/app.css?v=' in response.text
    assert '/static/app.js?v=' in response.text

from fastapi.testclient import TestClient

from stocks_tool.main import app


def test_dashboard_includes_holdings_and_order_sections() -> None:
    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert 'data-lang-option="zh"' in response.text
    assert 'data-lang-option="en"' in response.text
    assert 'data-workspace="research"' in response.text
    assert response.text.count('data-workspace-option=') == 5
    assert 'data-workspace-option="research"' in response.text
    assert 'data-workspace-option="strategy"' in response.text
    assert 'data-workspace-option="macro"' in response.text
    assert 'data-workspace-option="portfolio"' in response.text
    assert 'data-workspace-option="operations"' in response.text
    assert 'id="research-section"' in response.text
    assert 'id="research-table-view"' in response.text
    assert 'id="research-chart-view"' in response.text
    assert 'id="research-table-body"' in response.text
    assert 'id="research-chart-container"' in response.text
    assert 'id="research-watchlist-select"' in response.text
    assert 'id="manage-watchlist-button"' in response.text
    assert 'id="watchlist-dialog"' in response.text
    assert 'id="execution-drawer"' in response.text
    assert 'id="open-execution-drawer"' in response.text
    assert response.text.count('data-execution-tab=') == 4
    assert 'data-view-mode-option=' not in response.text
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
    assert "Lottery Strategy" in response.text
    assert "Preview Lottery" in response.text
    assert "Preview Only" in response.text
    assert "Force Scan" not in response.text
    assert "Strategy Experiment Bench" in response.text
    assert "Market Event Calendar" in response.text
    assert "Strategy Proposals" in response.text
    assert "Activity History" in response.text
    assert "Strategy Runs" in response.text
    assert "Signal Feed" in response.text
    assert "Review Feed" in response.text
    assert "DeepSeek Dry Run" in response.text
    assert "Load Context" in response.text
    assert "Run DeepSeek" in response.text
    assert "Record Output" in response.text
    assert "Upcoming Events" in response.text
    assert "Entry Status" in response.text
    assert "Next Action" in response.text
    assert "Latest Skip Reason" in response.text
    assert "Execute Preview" in response.text
    assert "Run Review" in response.text
    assert "Latest Review" in response.text
    assert "Bull Put Monitor" in response.text
    assert "Entry / Risk" in response.text
    assert "Monitor Mark" in response.text
    assert "PnL / Exit Distance" in response.text
    assert "Last Monitor" in response.text
    assert "Orders" in response.text
    assert "Positions" in response.text
    assert 'id="trade-confirm-dialog"' in response.text
    assert 'id="trade-confirm-details"' in response.text
    assert 'id="trade-confirm-accept"' in response.text
    assert 'id="desktop-trading-notice"' in response.text
    assert 'role="status"' in response.text
    assert 'aria-live="polite"' in response.text
    assert response.text.index("Bull Put Strategy") < response.text.index("Real-time Macro Board")
    assert "Manage Watchlist" in response.text
    assert "Longbridge Status" not in response.text
    assert "Quick Quote" not in response.text
    assert '/static/app.css?v=' in response.text
    assert '/static/workspace.css?v=' in response.text
    assert '/static/lifecycle-warning.js?v=' in response.text
    assert '/static/api-client.js?v=' in response.text
    assert '/static/formatters.js?v=' in response.text
    assert '/static/i18n.js?v=' in response.text
    assert '/static/state.js?v=' in response.text
    assert '/static/vendor/lightweight-charts-5.2.0.standalone.production.js?v=' in response.text
    assert '/static/chart-view.js?v=' in response.text
    assert '/static/research-view.js?v=' in response.text
    assert '/static/watchlist-view.js?v=' in response.text
    assert '/static/execution-drawer.js?v=' in response.text
    assert '/static/workspace-shell.js?v=' in response.text
    assert '/static/app.js?v=' in response.text


def test_app_alias_renders_the_same_workbench() -> None:
    client = TestClient(app)

    root = client.get("/")
    alias = client.get("/app")

    assert alias.status_code == 200
    assert alias.text == root.text

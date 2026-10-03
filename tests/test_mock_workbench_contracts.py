"""Keep safe-demo payloads aligned with the actual workbench read contracts."""

from pathlib import Path
import sys

from fastapi.testclient import TestClient


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mock_dashboard_server import create_app
from stocks_tool.application.services.portfolio import PortfolioAnalytics, PortfolioRisk
from stocks_tool.domain.research_records import ResearchCase, ResearchScreen, ResearchTimelineResponse


ACCOUNT = "LBPT10087357"


def test_demo_market_session_capture_is_immutable_paged_and_not_opening_followthrough():
    from stocks_tool.domain.market_session_comparisons import MarketSessionComparison, MarketSessionComparisonPage

    with TestClient(create_app()) as client:
        latest = MarketSessionComparison.model_validate(client.get(
            "/market-session-comparisons/latest",
            params={"external_account_id": ACCOUNT, "mode": "paper", "symbol": "QQQ.US"},
        ).json())
        assert latest.status == "valid"
        assert latest.pre_to_regular_close_pct == 2
        assert str(latest.regular_close_to_after_hours_pct) == "0.39"
        assert latest.regular_close_evidence.session_close_at.hour == 20
        assert latest.post_market_evidence.timestamp.hour == 22
        assert latest.source == "mock_market_session_capture"
        assert latest.raw_evidence["synthetic"] is True
        baselines = client.get("/strategies/pre-open-runs", params={"external_account_id": ACCOUNT}).json()
        assert any(row["id"] == latest.pre_open_run_id for row in baselines)
        payload = {"external_account_id": ACCOUNT, "mode": "paper", "symbol": "QQQ.US", "capture_key": "demo-comparison-retry"}
        saved = client.post("/market-session-comparisons", json=payload)
        replay = client.post("/market-session-comparisons", json=payload)
        assert saved.status_code == 201 and replay.status_code == 200
        assert saved.json()["comparison"]["id"] == replay.json()["comparison"]["id"]
        assert replay.json()["duplicate"] is True
        first = MarketSessionComparisonPage.model_validate(client.get(
            "/market-session-comparisons", params={"external_account_id": ACCOUNT, "symbol": "QQQ.US", "limit": 1},
        ).json())
        assert first.has_more and first.next_cursor
        second = MarketSessionComparisonPage.model_validate(client.get(
            "/market-session-comparisons", params={"external_account_id": ACCOUNT, "symbol": "QQQ.US", "limit": 1, "cursor": first.next_cursor},
        ).json())
        assert second.items[0].id != first.items[0].id
        missing = client.post("/market-session-comparisons", json={**payload, "symbol": "AAPL.US", "capture_key": "missing-demo-baseline"}).json()["comparison"]
        assert missing["status"] == "not_available"
        assert missing["pre_to_regular_close_pct"] is None
        assert missing["after_hours_price"] is None


def test_demo_chart_quote_and_explanation_share_the_same_observation():
    from mock_dashboard_fixtures import (
        build_mock_research_history, build_mock_research_technicals,
        build_mock_research_universe,
    )

    for row in build_mock_research_universe()["rows"]:
        technical = build_mock_research_technicals([row["symbol"]])["results"][0]
        for interval in ("3m", "6m", "1y"):
            bars = build_mock_research_history(row["symbol"], interval)["bars"]
            assert float(bars[-1]["close"]) == float(row["quote"]["last_done"])
            assert bars[-1]["timestamp"] == row["quote"]["timestamp"] == technical["latest_bar_at"]
            assert bars[-1]["sma20"] == technical["sma20"]
            assert bars[-1]["sma50"] == technical["sma50"]


def test_demo_portfolio_matches_contract_without_claiming_returns_or_complete_risk():
    with TestClient(create_app()) as client:
        analytics = PortfolioAnalytics.model_validate(client.get(
            "/portfolio/analytics", params={"external_account_id": ACCOUNT}
        ).json())
        risk = PortfolioRisk.model_validate(client.get(
            "/portfolio/risk", params={"external_account_id": ACCOUNT}
        ).json())
    assert len(analytics.series) == 5
    assert analytics.change.investment_return is None
    assert analytics.change.investment_return_unavailable.code == "cash_flow_history_unavailable"
    assert not analytics.data_quality.provenance_verified
    assert "mock_demo_data_not_market_evidence" in analytics.data_quality.warnings
    assert risk.known_max_loss.total is None
    assert risk.known_max_loss.unavailable is not None


def test_demo_saved_case_does_not_change_when_screen_is_edited():
    with TestClient(create_app()) as client:
        response = client.post("/research/screens", json={
            "external_account_id": ACCOUNT, "mode": "paper", "name": "趋势观察",
            "configuration": {"view": "chart", "filters": {"source": "watchlist"}},
            "symbols": ["QQQ.US"],
        })
        assert response.status_code == 201
        screen = ResearchScreen.model_validate(response.json())
        response = client.post("/research/cases", json={"screen_id": screen.id})
        assert response.status_code == 201
        case = ResearchCase.model_validate(response.json())
        client.patch(f"/research/screens/{screen.id}", json={"configuration": {"view": "table"}})
        reloaded = ResearchCase.model_validate(client.get(f"/research/cases/{case.id}").json())
        assert reloaded.configuration["view"] == "chart"
        assert reloaded.source == "mock_demo"
        assert reloaded.data_quality == "mock"
        assert client.get(f"/research/cases/{case.id}", params={"external_account_id": "other"}).status_code == 409


def test_demo_timeline_retains_scope_and_source_evidence():
    with TestClient(create_app()) as client:
        timeline = ResearchTimelineResponse.model_validate(client.get("/research/timeline").json())
        assert timeline.items
        assert all(item.source == "mock-ui" for item in timeline.items)
        assert "mock_demo_data_not_market_evidence" in timeline.warnings
        assert client.get("/portfolio/analytics", params={"external_account_id": ACCOUNT, "mode": "live"}).status_code == 404


def test_demo_capture_uses_current_selected_symbol_range_and_configuration():
    with TestClient(create_app()) as client:
        screen = client.post("/research/screens", json={
            "name": "多标的观察", "symbols": ["MOCK.US", "QQQ.US"],
            "configuration": {"selected_symbol": "MOCK.US", "history_range": "3m"},
        }).json()
        case = client.post("/research/cases", json={
            "screen_id": screen["id"], "next_action": "observe",
            "configuration": {"selected_symbol": "QQQ.US", "history_range": "1y"},
        }).json()
        assert case["primary_symbol"] == "QQQ.US"
        assert case["universe"]["history"]["range"] == "1y"
        assert case["next_action"] == "observe"
        assert client.get(f"/research/screens/{screen['id']}").json()["configuration"]["selected_symbol"] == "MOCK.US"
        assert client.get("/research/cases", params={"symbol": "qqq.us"}).json()["items"][0]["id"] == case["id"]
        assert client.get("/research/cases", params={"symbol": "AAPL.US"}).json()["items"] == []
        assert client.post(f"/research/screens/{screen['id']}/copy").status_code == 201


def test_demo_timeline_filters_dates_and_research_pages_are_bounded():
    with TestClient(create_app()) as client:
        for index in range(3):
            client.post("/research/screens", json={"name": f"screen-{index}"})
        first = client.get("/research/screens", params={"limit": 2}).json()
        second = client.get("/research/screens", params={"limit": 2, "cursor": first["next_cursor"]}).json()
        assert first["has_more"] and len(first["items"]) == 2
        assert not second["has_more"] and len(second["items"]) == 1
        assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}
        timeline = client.get("/research/timeline", params={"start": "2026-06-02T00:00:00Z", "end": "2026-06-04T00:00:00Z"}).json()
        assert len(timeline["items"]) == 1
        assert timeline["items"][0]["event_id"] == "mock-event-0002"


def test_demo_readiness_never_substitutes_a_different_symbol():
    with TestClient(create_app()) as client:
        result = client.get("/strategies/bull-put/readiness", params={"external_account_id": ACCOUNT, "symbol": "AAPL.US"}).json()
        assert result["ready"] is False
        assert result["preferred_symbol"] is None
        assert result["previews"] == []
        assert "AAPL.US" in result["next_action"]

"""Explicitly fictional, isolated fixtures for the professional-workbench demo.

The mock server has no production database or broker adapter.  Persistent-product
behavior is verified against the real repositories separately; these records live
only for the lifetime of this demo process.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query

from mock_dashboard_fixtures import (
    build_mock_research_history,
    build_mock_research_technicals,
    build_mock_research_universe,
    iso_now,
)
from stocks_tool.domain.pagination import CursorError, decode_cursor, encode_cursor
from stocks_tool.domain.models import ResearchRankingRequest, StrategyAdvisorAuditSnapshot
from stocks_tool.application.services.research import ResearchService


def install_workbench_routes(app: FastAPI, state: Any) -> None:
    screens: dict[str, dict] = {}
    cases: dict[str, dict] = {}
    backtests: dict[str, dict] = {}

    @app.post("/research/rank")
    def rank_research(request: ResearchRankingRequest):
        return ResearchService().rank_candidates(request.candidates)

    def require_scope(account: str, mode: str = "paper") -> None:
        if account != state.account_id or mode != "paper":
            raise HTTPException(404, detail={"code": "mock_account_scope_not_found"})

    def find(records: dict, record_id: str, account: str, mode: str) -> dict:
        row = records.get(record_id)
        if not row:
            raise HTTPException(404, detail={"code": "research_record_not_found"})
        if row["external_account_id"] != account or row["mode"] != mode:
            raise HTTPException(409, detail={"code": "research_scope_mismatch"})
        return row

    def page_rows(rows: list[dict], *, resource: str, scope: dict, limit: int, cursor: str | None) -> dict:
        ordered = sorted(rows, key=lambda row: (row["created_at"], row["id"]), reverse=True)
        if cursor:
            try:
                position = decode_cursor(cursor, resource=resource, scope=scope)
                boundary = (str(position["created_at"]), str(position["id"]))
            except (CursorError, KeyError, TypeError) as exc:
                raise HTTPException(422, detail={"code": "research_cursor_invalid"}) from exc
            ordered = [row for row in ordered if (row["created_at"], row["id"]) < boundary]
        items = ordered[:limit]
        has_more = len(ordered) > limit
        next_cursor = encode_cursor(resource=resource, scope=scope, position={
            "created_at": items[-1]["created_at"], "id": items[-1]["id"],
        }) if has_more else None
        return {"items": deepcopy(items), "limit": limit, "has_more": has_more, "next_cursor": next_cursor}

    from mock_market_session_routes import install_market_session_routes
    install_market_session_routes(app, state, page_rows)

    @app.get("/research/screens")
    def list_screens(external_account_id: str = state.account_id, mode: str = "paper", limit: int = Query(default=50, ge=1, le=100), cursor: str | None = None) -> dict:
        require_scope(external_account_id, mode)
        return page_rows(list(screens.values()), resource="mock-research-screens", scope={"account": external_account_id, "mode": mode}, limit=limit, cursor=cursor)

    @app.post("/research/screens", status_code=201)
    def create_screen(payload: dict) -> dict:
        require_scope(payload.get("external_account_id", state.account_id), payload.get("mode", "paper"))
        name = str(payload.get("name", "")).strip()
        if not name:
            raise HTTPException(422, detail={"code": "research_screen_name_required"})
        if any(row["name"].casefold() == name.casefold() for row in screens.values()):
            raise HTTPException(409, detail={"code": "research_screen_name_conflict"})
        now = iso_now()
        row = {
            "id": str(uuid4()), "external_account_id": state.account_id, "mode": "paper",
            "name": name, "description": payload.get("description"),
            "configuration": deepcopy(payload.get("configuration", {})),
            "symbols": deepcopy(payload.get("symbols", [])), "created_at": now, "updated_at": now,
        }
        screens[row["id"]] = row
        return deepcopy(row)

    @app.get("/research/screens/{screen_id}")
    def get_screen(screen_id: str, external_account_id: str = state.account_id, mode: str = "paper") -> dict:
        return deepcopy(find(screens, screen_id, external_account_id, mode))

    @app.patch("/research/screens/{screen_id}")
    def update_screen(screen_id: str, payload: dict, external_account_id: str = state.account_id, mode: str = "paper") -> dict:
        row = find(screens, screen_id, external_account_id, mode)
        for key in ("name", "description", "configuration", "symbols"):
            if key in payload:
                row[key] = deepcopy(payload[key])
        row["updated_at"] = iso_now()
        return deepcopy(row)

    @app.post("/research/screens/{screen_id}/copy", status_code=201)
    def copy_screen(screen_id: str, payload: dict | None = None, external_account_id: str = state.account_id, mode: str = "paper") -> dict:
        row = deepcopy(find(screens, screen_id, external_account_id, mode))
        payload = payload or {}
        row["name"] = payload.get("name") or f"{row['name']} copy"
        return create_screen(row)

    @app.get("/research/cases")
    def list_cases(external_account_id: str = state.account_id, mode: str = "paper", screen_id: str | None = None, symbol: str | None = None, limit: int = Query(default=50, ge=1, le=100), cursor: str | None = None) -> dict:
        require_scope(external_account_id, mode)
        rows = list(reversed(list(cases.values())))
        if screen_id:
            rows = [row for row in rows if row["screen_id"] == screen_id]
        if symbol:
            rows = [row for row in rows if symbol.strip().upper() in row["symbols"]]
        return page_rows(rows, resource="mock-research-cases", scope={"account": external_account_id, "mode": mode, "screen_id": screen_id, "symbol": symbol.strip().upper() if symbol else None}, limit=limit, cursor=cursor)

    @app.post("/research/cases", status_code=201)
    def capture_case(payload: dict) -> dict:
        account = payload.get("external_account_id") or state.account_id
        mode = payload.get("mode") or "paper"
        screen = find(screens, payload.get("screen_id", ""), account, mode)
        configuration = deepcopy(payload.get("configuration") or screen["configuration"])
        symbols = [str(symbol).strip().upper() for symbol in (payload.get("symbols") or screen["symbols"]) if str(symbol).strip()]
        universe = build_mock_research_universe(state.account_id)
        available_symbols = {item["symbol"] for item in universe["rows"]}
        symbols = symbols or list(available_symbols)
        primary = configuration.get("selected_symbol") or symbols[0]
        history_range = configuration.get("history_range", "3m")
        if primary not in available_symbols or history_range not in {"3m", "6m", "1y"}:
            raise HTTPException(422, detail={"code": "research_capture_selection_invalid"})
        proposal_ids = payload.get("proposal_ids", [])
        advisor_ids = payload.get("advisor_run_ids", [])
        if not set(proposal_ids).issubset({item["id"] for item in state.strategy_proposals}) or not set(advisor_ids).issubset({item["run_id"] for item in state.advisor_run_cards}):
            raise HTTPException(422, detail={"code": "research_reference_scope_invalid"})
        row = {
            "id": str(uuid4()), "screen_id": screen["id"], "external_account_id": account,
            "mode": mode, "configuration": configuration,
            "universe": {
                "research_universe": universe,
                "technicals": build_mock_research_technicals([primary]),
                "history": build_mock_research_history(primary, history_range),
                "technical_coverage": {"scope": "primary_symbol_only", "requested_symbols": [primary], "covered_symbols": [primary], "complete": len(symbols) == 1},
            }, "symbols": symbols, "primary_symbol": primary,
            "as_of": universe["generated_at"], "data_quality": "mock",
            "warnings": ["mock_demo_data_not_market_evidence"], "source": "mock_demo",
            "proposal_ids": deepcopy(proposal_ids),
            "advisor_run_ids": deepcopy(advisor_ids), "created_at": iso_now(),
            "title": payload.get("title") or screen["name"], "notes": payload.get("notes", ""),
            "next_action": payload.get("next_action"),
        }
        cases[row["id"]] = row
        return deepcopy(row)

    @app.get("/research/cases/{case_id}")
    def get_case(case_id: str, external_account_id: str = state.account_id, mode: str = "paper") -> dict:
        return deepcopy(find(cases, case_id, external_account_id, mode))

    @app.get("/research/timeline")
    def timeline(external_account_id: str = state.account_id, mode: str = "paper", start: datetime | None = None, end: datetime | None = None, symbols: list[str] = Query(default=[]), symbol: str | None = None, limit: int = Query(default=50, ge=1, le=100), cursor: str | None = None) -> dict:
        require_scope(external_account_id, mode)
        start = start or datetime(2026, 5, 1, tzinfo=timezone.utc)
        end = end or datetime(2026, 6, 30, 23, 59, 59, tzinfo=timezone.utc)
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start
        end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end
        if end < start or end - start > timedelta(days=366):
            raise HTTPException(422, detail={"code": "research_timeline_invalid"})
        symbols = sorted({item.strip().upper() for token in [*symbols, symbol or ""] for item in token.split(",") if item.strip()})
        rows = [deepcopy(event) for event in state.market_events if (not symbols or not event["symbol"] or event["symbol"] in symbols) and start <= datetime.fromisoformat(event["scheduled_at"].replace("Z", "+00:00")) <= end]
        page = page_rows(rows, resource="mock-research-timeline", scope={"account": external_account_id, "mode": mode, "start": start.isoformat(), "end": end.isoformat(), "symbols": symbols}, limit=limit, cursor=cursor)
        rows = page["items"]
        return {
            "external_account_id": external_account_id, "mode": mode,
            "start": start.isoformat(), "end": end.isoformat(),
            "generated_at": iso_now(), "symbols": symbols, "events": rows,
            "pre_open_links": [], "warnings": ["mock_demo_data_not_market_evidence"],
            "items": [{"kind": "market_event", "scheduled_at": row["scheduled_at"], "symbol": row["symbol"], "title": row["title"], "source": row["source"], "severity": row["severity"], "event_type": row["event_type"], "event_id": row["id"], "payload": row} for row in rows],
            "limit": limit, "next_cursor": page["next_cursor"], "has_more": page["has_more"],
        }

    def portfolio_payload(account: str, mode: str) -> dict:
        require_scope(account, mode)
        snapshot = state.snapshot
        captured = datetime.fromisoformat(snapshot["captured_at"].replace("Z", "+00:00"))
        nav = Decimal(snapshot["net_liquidation"])
        series = []
        for index, change in enumerate((Decimal("-3500"), Decimal("-1600"), Decimal("-2400"), Decimal("-800"), Decimal("0"))):
            series.append({
                "captured_at": (captured - timedelta(days=4-index)).isoformat(),
                "net_liquidation": str(nav + change), "cash_balance": snapshot["cash_balance"],
                "currency": snapshot["currency"],
                "provenance": "mock_demo",
                "buying_power": snapshot["buying_power"], "position_market_value": "4000",
                "snapshot_id": f"mock-nav-{index}", "source_snapshot_id": f"mock-nav-{index}",
            })
        latest = {
            "snapshot_id": snapshot["id"], "captured_at": snapshot["captured_at"],
            "currency": snapshot["currency"], "net_liquidation": snapshot["net_liquidation"],
            "cash_balance": snapshot["cash_balance"], "buying_power": snapshot["buying_power"],
            "position_market_value": "4000", "stale": True, "provenance": "mock_demo",
        }
        allocation = [{
            "symbol": position["symbol"], "asset_type": position["asset_type"],
            "market_value": position["market_value"], "unrealized_pnl": position["unrealized_pnl"],
            "quantity": str(position["quantity"]),
            "absolute_market_value": str(abs(Decimal(position["market_value"]))),
            "weight_of_net_liquidation": str(Decimal(position["market_value"]) / nav),
            "position_ids": [f"mock-position-{index}"],
        } for index, position in enumerate(snapshot["positions"])]
        missing = {"code": "cash_flow_history_unavailable", "reason": "Complete external cash-flow evidence is not available."}
        return {
            "external_account_id": account, "mode": mode, "currency": "USD", "as_of": snapshot["captured_at"],
            "latest": latest, "series": series, "allocation": allocation, "strategy_exposures": [],
            "change": {"from_at": series[0]["captured_at"], "to_at": series[-1]["captured_at"], "net_liquidation_change": "3500", "investment_return": None, "investment_return_unavailable": missing},
            "links": {"orders": [row["id"] for row in state.orders], "executions": [row["id"] for row in state.executions], "journals": [row["id"] for row in state.journals]},
            "evidence": {"as_of": snapshot["captured_at"], "snapshot_ids": [snapshot["id"]]},
            "data_quality": {"warnings": ["mock_demo_data_not_market_evidence", "snapshot_stale"], "unavailable": [missing, {"code": "fee_history_unavailable", "reason": "Fees are unknown."}, {"code": "greeks_unavailable", "reason": "Greeks are unknown."}], "snapshot_count": 5, "snapshot_count_in_range": 5, "snapshot_stale": True, "provenance_verified": False},
        }

    @app.get("/portfolio/analytics")
    def portfolio_analytics(external_account_id: str, mode: str = "paper") -> dict:
        return portfolio_payload(external_account_id, mode)

    @app.get("/portfolio/risk")
    def portfolio_risk(external_account_id: str, mode: str = "paper") -> dict:
        analytics = portfolio_payload(external_account_id, mode)
        return {
            "external_account_id": external_account_id, "mode": mode, "currency": "USD", "as_of": analytics["as_of"],
            "balance": analytics["latest"],
            "concentrations": [{"symbol": item["symbol"], "market_value": item["market_value"], "absolute_market_value": item["absolute_market_value"], "weight_of_net_liquidation": item["weight_of_net_liquidation"], "risk_level": "unknown", "source_position_ids": item["position_ids"]} for item in analytics["allocation"]],
            "known_max_loss": {"total": None, "components": [], "unavailable": {"code": "incomplete_risk_evidence", "reason": "The fixture does not contain complete risk evidence."}},
            "strategy_exposures": [], "covered_share_reservations": [], "covered_share_groups": [],
            "links": analytics["links"], "evidence": analytics["evidence"], "data_quality": analytics["data_quality"],
        }

    @app.get("/backtests/datasets")
    def backtest_datasets() -> list[dict]:
        # An empty registry is intentional: a mock quote fixture is not a
        # licensed options-history dataset.
        return []

    @app.get("/backtests")
    def list_backtests() -> list[dict]:
        return deepcopy(list(backtests.values()))

    @app.post("/backtests", status_code=422)
    def create_backtest(payload: dict) -> dict:
        raise HTTPException(422, detail={
            "code": "blocked_data", "message": "演示服务没有授权历史期权数据，不能生成真实回测结果。",
            "required_start": "2020-01-01", "required_end": "2026-09-30",
        })

    @app.post("/backtests/compare")
    def compare_backtests(payload: dict) -> dict:
        raise HTTPException(404, detail={"code": "backtest_not_found"})

    @app.get("/strategies/advisor/audit", response_model=StrategyAdvisorAuditSnapshot)
    def advisor_audit(external_account_id: str = state.account_id, source: str = "deepseek", limit: int = Query(default=10, ge=1, le=100)) -> dict:
        require_scope(external_account_id)
        runs = []
        for card in state.advisor_run_cards[:limit]:
            if source != card["source"]:
                continue
            runs.append({
                "advisor_run": {
                    "id": card["run_id"], "external_account_id": external_account_id,
                    "source": card["source"], "mode": "paper", "provider": card["provider"],
                    "model": card["model"], "status": card["status"],
                    "context_format": card["context_format"], "context_limit": 10,
                    "proposal_count": card["proposal_count"], "review_count": card["review_count"],
                    "completed_at": card["completed_at"], "recorded_at": card["recorded_at"],
                    "created_at": card["created_at"], "updated_at": card["recorded_at"],
                    **card["token_usage"],
                },
                "record_state": card["recordable_status"], "token_usage": deepcopy(card["token_usage"]),
                "comparison": None,
                "downstream_impact": {
                    "advisor_run_id": card["run_id"],
                    "proposal_ids": deepcopy(card["downstream_proposal_ids"]),
                    "review_ids": deepcopy(card["downstream_review_ids"]),
                    "proposal_status_counts": {}, "review_status_counts": {"draft": 1},
                },
                "checks": [{"name": "mock_fixture", "status": "warning", "detail": "本地演示记录；查看此页不会调用模型，也不能据此下单。", "blocking": False}],
            })
        return {"external_account_id": external_account_id, "source": source, "generated_at": iso_now(), "runs": runs}

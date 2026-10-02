from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


MOCK_ACCOUNT_ID = "LBPT10087357"
MOCK_SYMBOL = "MOCK.US"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_price(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.4f}"


def build_mock_account(account_id: str = MOCK_ACCOUNT_ID) -> dict[str, Any]:
    return {
        "id": "mock-account-1",
        "broker": "longbridge",
        "external_account_id": account_id,
        "display_name": "Longbridge Paper",
        "base_currency": "USD",
        "options_level": "level_1",
        "is_active": True,
        "auto_reconcile_enabled": True,
        "account_sync_status": "success",
        "account_last_sync_attempt_at": "2026-05-21T02:14:50Z",
        "account_last_synced_at": "2026-05-21T02:14:52Z",
        "account_last_sync_error": None,
        "orders_sync_status": "success",
        "orders_last_sync_attempt_at": "2026-05-21T02:14:53Z",
        "orders_last_synced_at": "2026-05-21T02:14:54Z",
        "orders_last_sync_error": None,
        "created_at": "2026-05-21T00:00:00Z",
        "updated_at": "2026-05-21T00:00:00Z",
    }


def build_mock_watchlists(symbol: str = MOCK_SYMBOL) -> list[dict[str, Any]]:
    return [
        {
            "id": "mock-watchlist-1",
            "name": "core-us",
            "description": "Mock research universe",
            "is_default": True,
            "items": [
                {
                    "id": "mock-watchlist-item-1",
                    "symbol": symbol,
                    "asset_type": "stock",
                    "notes": "ui regression seed",
                },
                {
                    "id": "mock-watchlist-item-2",
                    "symbol": "UNH.US",
                    "asset_type": "stock",
                    "notes": "real paper validation symbol",
                },
            ],
        }
    ]


def build_mock_research_universe(
    account_id: str = MOCK_ACCOUNT_ID,
    watchlist_id: str = "mock-watchlist-1",
) -> dict[str, Any]:
    mock_quote = build_mock_quote(MOCK_SYMBOL)
    mock_quote["data_quality"] = "live"
    qqq_quote = build_mock_quote("QQQ.US")
    qqq_quote.update({"last_done": "510.00", "prev_close": "505.00", "open": "506.00", "data_quality": "live"})
    return {
        "mode": "paper",
        "external_account_id": account_id,
        "watchlist_id": watchlist_id,
        "generated_at": iso_now(),
        "data_quality": "live",
        "rows": [
            {
                "symbol": MOCK_SYMBOL,
                "asset_type": "stock",
                "sources": ["watchlist", "position"],
                "notes": "ui regression seed",
                "position_quantity": "10",
                "position_market_value": "4000.00",
                "quote": mock_quote,
                "next_event": {
                    "event_type": "earnings",
                    "title": "Mock earnings window",
                    "scheduled_at": "2026-06-12T20:00:00Z",
                },
                "strategy_states": ["covered_call_active"],
                "warnings": [],
            },
            {
                "symbol": "QQQ.US",
                "asset_type": "etf",
                "sources": ["bull_put_pool", "zero_dte_pool"],
                "notes": "strategy research seed",
                "position_quantity": None,
                "position_market_value": None,
                "quote": qqq_quote,
                "next_event": None,
                "strategy_states": ["bull_put_ready", "zero_dte_preview_only"],
                "warnings": [],
            },
        ],
        "warnings": [],
    }


def build_mock_research_technicals(symbols: list[str]) -> dict[str, Any]:
    results = []
    for index, symbol in enumerate(symbols):
        results.append(
            {
                "symbol": symbol.upper(),
                "status": "ok",
                "warning": None,
                "latest_bar_at": "2026-06-10T20:00:00Z",
                "return_20d_pct": 4.2 - index,
                "return_60d_pct": 9.8 - index,
                "sma20": str(395 + index * 100),
                "sma50": str(388 + index * 100),
                "close_above_sma20": True,
                "sma20_above_sma50": True,
                "realized_volatility_20d_pct": 22.4 + index,
                "average_volume_20d": 1_250_000 + index * 100_000,
                "average_turnover_20d": str(500_000_000 + index * 50_000_000),
            }
        )
    return {"mode": "paper", "generated_at": iso_now(), "results": results}


def build_mock_research_history(symbol: str, range_value: str) -> dict[str, Any]:
    count = {"3m": 66, "6m": 132, "1y": 252}[range_value]
    start = datetime(2025, 6, 1, tzinfo=timezone.utc)
    bars = []
    closes: list[float] = []
    for index in range(count):
        close = 380.0 + index * 0.35
        closes.append(close)
        sma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else None
        sma50 = sum(closes[-50:]) / 50 if len(closes) >= 50 else None
        timestamp = start + timedelta(days=index)
        bars.append(
            {
                "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                "open": f"{close - 0.8:.2f}",
                "high": f"{close + 1.2:.2f}",
                "low": f"{close - 1.5:.2f}",
                "close": f"{close:.2f}",
                "volume": 1_000_000 + index * 1_000,
                "turnover": f"{close * (1_000_000 + index * 1_000):.2f}",
                "sma20": f"{sma20:.2f}" if sma20 is not None else None,
                "sma50": f"{sma50:.2f}" if sma50 is not None else None,
            }
        )
    return {
        "symbol": symbol.upper(),
        "range": range_value,
        "mode": "paper",
        "generated_at": iso_now(),
        "bars": bars,
        "warnings": [],
    }


def build_mock_configuration() -> dict[str, bool]:
    return {
        "app_key_configured": True,
        "app_secret_configured": True,
        "paper_token_configured": True,
        "live_token_configured": False,
    }


def build_mock_broker_profile(account_id: str = MOCK_ACCOUNT_ID) -> dict[str, Any]:
    return {
        "id": f"longbridge-paper-{account_id}",
        "broker": "longbridge",
        "name": "longbridge",
        "external_account_id": account_id,
        "mode": "paper",
        "supported_modes": ["paper", "live"],
        "capabilities": [
            {
                "name": "paper_trading",
                "supported": True,
                "notes": "Mock paper profile for dashboard regression.",
            }
        ],
        "readonly": False,
        "paper_guard": "config_declared",
        "configured": True,
        "credential_status": "ready",
        "notes": ["Paper guard is declared by local configuration."],
    }


def build_mock_paper_mandate(
    account_id: str = MOCK_ACCOUNT_ID,
    *,
    bull_put_auto_entry: bool = True,
    zero_dte_auto_execute: bool = False,
    manual_pause: bool = False,
    kill_switch: bool = False,
) -> dict[str, Any]:
    reason_codes: list[str] = []
    if manual_pause:
        reason_codes.append("manual_pause")
    if kill_switch:
        reason_codes.append("kill_switch")
    severity = "critical" if kill_switch else "warning" if manual_pause else None
    return {
        "external_account_id": account_id,
        "enabled_strategies": ["paper_bull_put_v1", "covered_call_v1", "zero_dte_lottery_v1"],
        "symbol_universe": ["QQQ.US", "SMH.US", "SOXL.US", "EWY.US"],
        "daily_caps": {"bull_put_new_spreads": 1, "zero_dte_lottery_trades": 1},
        "risk_caps": {
            "bull_put_daily_realized_loss_limit": "300",
            "zero_dte_max_premium_per_trade": "150",
        },
        "auto_switches": {
            "bull_put_auto_entry": bull_put_auto_entry,
            "zero_dte_auto_execute": zero_dte_auto_execute,
            "covered_call_auto_propose": False,
        },
        "manual_pause": manual_pause,
        "kill_switch": kill_switch,
        "reason_codes": reason_codes,
        "severity": severity,
        "expires_at": None,
    }


def build_mock_advisor_run_card(account_id: str = MOCK_ACCOUNT_ID) -> dict[str, Any]:
    return {
        "run_id": "mock-advisor-run-0001",
        "external_account_id": account_id,
        "source": "deepseek",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "status": "recorded",
        "playbook_id": "bull_put_v1",
        "context_format": "compact_v1",
        "context_hash": "mockcontext0123456789abcdef",
        "token_usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "cache_hit_tokens": 40,
            "cache_miss_tokens": 60,
        },
        "summary": "recorded; 0 proposal(s), 1 review(s); 0 proposal link(s), 1 review link(s).",
        "recorded": True,
        "recordable_status": "recorded",
        "impact_summary": "0 proposal link(s), 1 review link(s); advisor cannot submit orders.",
        "proposal_count": 0,
        "review_count": 1,
        "warnings": [],
        "downstream_proposal_ids": [],
        "downstream_review_ids": ["mock-review-0001"],
        "completed_at": "2026-05-29T14:52:00Z",
        "recorded_at": "2026-05-29T14:55:00Z",
        "created_at": "2026-05-29T14:52:00Z",
    }


def build_mock_quote(symbol: str = MOCK_SYMBOL) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "last_done": "400.000",
        "prev_close": "398.000",
        "open": "399.500",
        "high": "401.250",
        "low": "397.750",
        "timestamp": "2026-05-21T04:00:00Z",
        "volume": 1250000,
        "turnover": "500000000.000",
        "trade_status": "TradeStatus.Normal",
        "pre_market_quote": None,
        "post_market_quote": None,
        "overnight_quote": None,
    }

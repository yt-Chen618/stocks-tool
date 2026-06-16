from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.staticfiles import StaticFiles

from mock_dashboard_fixtures import (
    MOCK_ACCOUNT_ID,
    MOCK_SYMBOL,
    build_mock_account,
    build_mock_advisor_run_card,
    build_mock_broker_profile,
    build_mock_configuration,
    build_mock_paper_mandate,
    build_mock_quote,
    build_mock_watchlists,
    format_price,
    iso_now,
)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stocks_tool.api.routes import ui  # noqa: E402


MOCK_SCENARIOS = {
    "normal",
    "degraded-broker",
    "paused-mandate",
    "advisor-pending-record",
    "manual-action-required",
    "scheduler-backoff",
    "recover-eligible",
    "recover-rejected",
    "recover-already-working",
}


class MockDashboardState:
    def __init__(self, *, scenario: str = "normal") -> None:
        if scenario not in MOCK_SCENARIOS:
            raise ValueError(f"Unknown mock dashboard scenario '{scenario}'.")
        self.scenario = scenario
        self.account_id = MOCK_ACCOUNT_ID
        self.symbol = MOCK_SYMBOL
        self._order_counter = 1000
        self._journal_counter = 2000
        self._spread_counter = 3000
        self.account = build_mock_account(self.account_id)
        self.watchlists = build_mock_watchlists(self.symbol)
        self.configuration = build_mock_configuration()
        self.quote = build_mock_quote(self.symbol)
        self.broker_profile = build_mock_broker_profile(self.account_id)
        self.advisor_run_cards = [build_mock_advisor_run_card(self.account_id)]
        self.pre_open_assessment = {
            "analyzed_at": "2026-05-23T12:20:00Z",
            "session": "premarket",
            "market_open": False,
            "target_session_date": "2026-05-23",
            "minutes_to_regular_open": 70,
            "next_regular_open_at": "2026-05-23T13:30:00Z",
            "downside_score": 5,
            "regime": "broad_downside_risk",
            "plain_put_view": "reasonable",
            "preferred_vehicle": "QQQ",
            "trade_action": "wait_for_open_confirmation",
            "trade_action_detail": "Bias is bearish. Only press QQQ puts if QQQ and semis stay weak through the open.",
            "gap_chase_risk": "medium",
            "gap_chase_detail": "The bearish read is usable, but only if the first 5-15 minutes confirm that tech stays weaker than the broad market.",
            "summary": "Premarket tape is weak enough to justify a cautious long-put bias, with QQQ cleaner than SPY.",
            "reasons": [
                "QQQ is weaker than the previous close by more than 0.60%.",
                "Semiconductor beta is leading the weakness, which leans toward QQQ over SPY.",
                "Oil is firmer enough to keep inflation pressure on the tape.",
            ],
            "checkpoints": [
                {
                    "label": "Macro pulse",
                    "timing_label": "08:30 ET",
                    "status": "complete",
                    "detail": "Recheck futures, rates proxies, and any overnight macro shock before trusting the bearish read.",
                },
                {
                    "label": "Tape confirmation",
                    "timing_label": "09:15 ET",
                    "status": "active",
                    "detail": "Compare QQQ versus SPY and semis versus QQQ. If tech stops underperforming here, plain puts lose edge quickly.",
                },
                {
                    "label": "Opening print",
                    "timing_label": "09:30 ET",
                    "status": "pending",
                    "detail": "Do not chase the first print. Watch whether the gap extends or immediately attracts buyers.",
                },
                {
                    "label": "First 15 minutes",
                    "timing_label": "09:45 ET",
                    "status": "pending",
                    "detail": "If the opening bounce fails and QQQ remains the weak vehicle, the downside expression is cleaner.",
                },
            ],
            "signals": [
                {
                    "key": "spy",
                    "label": "S&P 500 ETF",
                    "symbol": "SPY.US",
                    "session_price": "576.4000",
                    "reference_price": "579.3000",
                    "change_pct": "-0.5006",
                    "signal": "bearish",
                    "note": "Broad index proxy is trading below the previous close.",
                },
                {
                    "key": "qqq",
                    "label": "Nasdaq 100 ETF",
                    "symbol": "QQQ.US",
                    "session_price": "497.1000",
                    "reference_price": "501.1000",
                    "change_pct": "-0.7982",
                    "signal": "bearish",
                    "note": "QQQ is underperforming SPY in the pre-open tape.",
                },
                {
                    "key": "semis",
                    "label": "Semiconductor Proxy",
                    "symbol": "SOXX.US",
                    "session_price": "240.2000",
                    "reference_price": "243.1000",
                    "change_pct": "-1.1930",
                    "signal": "bearish",
                    "note": "Semi proxy is weaker than both SPY and QQQ.",
                },
                {
                    "key": "oil",
                    "label": "Oil Proxy",
                    "symbol": "USO.US",
                    "session_price": "81.4500",
                    "reference_price": "80.1000",
                    "change_pct": "1.6854",
                    "signal": "bearish",
                    "note": "Higher oil tends to pressure inflation expectations.",
                },
                {
                    "key": "rates",
                    "label": "Rates Proxy",
                    "symbol": "TLT.US",
                    "session_price": "88.6000",
                    "reference_price": "89.0000",
                    "change_pct": "-0.4494",
                    "signal": "neutral",
                    "note": "Rates are not moving enough to add a separate warning.",
                },
            ],
            "put_snapshots": [
                {
                    "underlying_symbol": "SPY.US",
                    "expiration_date": "2026-05-30",
                    "days_to_expiration": 7,
                    "strike": "578.0000",
                    "put_symbol": "SPY260530P578000.US",
                    "bid": "2.1800",
                    "ask": "2.3200",
                    "mid_price": "2.2500",
                    "spread_width": "0.1400",
                    "spread_pct": "6.22",
                    "distance_from_spot_pct": "-0.2774",
                    "delta": "-0.2700",
                    "implied_volatility": "0.2120",
                    "liquidity_label": "workable",
                },
                {
                    "underlying_symbol": "QQQ.US",
                    "expiration_date": "2026-05-30",
                    "days_to_expiration": 7,
                    "strike": "498.0000",
                    "put_symbol": "QQQ260530P498000.US",
                    "bid": "3.6400",
                    "ask": "3.8400",
                    "mid_price": "3.7400",
                    "spread_width": "0.2000",
                    "spread_pct": "5.35",
                    "distance_from_spot_pct": "-0.1811",
                    "delta": "-0.2900",
                    "implied_volatility": "0.2480",
                    "liquidity_label": "workable",
                },
            ],
            "chain_analyses": [
                {
                    "underlying_symbol": "SPY.US",
                    "underlying_price": "576.4000",
                    "analyzed_at": "2026-05-23T12:20:00Z",
                    "front_expiration": {
                        "expiration_date": "2026-05-30",
                        "days_to_expiration": 7,
                        "atm_strike": "578.0000",
                        "atm_put_symbol": "SPY260530P578000.US",
                        "atm_implied_volatility": "0.2120",
                        "atm_delta": "-0.2700",
                        "atm_mid_price": "2.2500",
                        "put_skew_strike": "578.0000",
                        "put_skew_put_symbol": "SPY260530P578000.US",
                        "put_skew_implied_volatility": "0.2120",
                        "put_skew_delta": "-0.2700",
                        "put_skew_diff": "0.0000",
                        "median_spread_pct": "6.22",
                        "tight_count": 0,
                        "workable_count": 2,
                        "wide_count": 0,
                        "liquid_strikes": [
                            {
                                "strike": "578.0000",
                                "put_symbol": "SPY260530P578000.US",
                                "open_interest": 2100,
                                "volume": 5300,
                                "delta": "-0.2700",
                                "bid": "2.1800",
                                "ask": "2.3200",
                                "mid_price": "2.2500",
                                "spread_width": "0.1400",
                                "spread_pct": "6.22",
                                "liquidity_label": "workable"
                            }
                        ]
                    },
                    "next_expiration": {
                        "expiration_date": "2026-06-06",
                        "days_to_expiration": 14,
                        "atm_strike": "578.0000",
                        "atm_put_symbol": "SPY260606P578000.US",
                        "atm_implied_volatility": "0.2190",
                        "atm_delta": "-0.2900",
                        "atm_mid_price": "3.1200",
                        "put_skew_strike": "570.0000",
                        "put_skew_put_symbol": "SPY260606P570000.US",
                        "put_skew_implied_volatility": "0.2250",
                        "put_skew_delta": "-0.2300",
                        "put_skew_diff": "0.0060",
                        "median_spread_pct": "6.80",
                        "tight_count": 0,
                        "workable_count": 2,
                        "wide_count": 0,
                        "liquid_strikes": []
                    },
                    "atm_iv_term_diff": "0.0070",
                    "term_structure_label": "flat",
                    "sample_note": "Liquidity buckets use ATM/skew anchors plus the deepest open-interest puts for each expiry."
                },
                {
                    "underlying_symbol": "QQQ.US",
                    "underlying_price": "497.1000",
                    "analyzed_at": "2026-05-23T12:20:00Z",
                    "front_expiration": {
                        "expiration_date": "2026-05-30",
                        "days_to_expiration": 7,
                        "atm_strike": "498.0000",
                        "atm_put_symbol": "QQQ260530P498000.US",
                        "atm_implied_volatility": "0.2480",
                        "atm_delta": "-0.2900",
                        "atm_mid_price": "3.7400",
                        "put_skew_strike": "498.0000",
                        "put_skew_put_symbol": "QQQ260530P498000.US",
                        "put_skew_implied_volatility": "0.2480",
                        "put_skew_delta": "-0.2900",
                        "put_skew_diff": "0.0000",
                        "median_spread_pct": "5.35",
                        "tight_count": 0,
                        "workable_count": 2,
                        "wide_count": 0,
                        "liquid_strikes": [
                            {
                                "strike": "498.0000",
                                "put_symbol": "QQQ260530P498000.US",
                                "open_interest": 3200,
                                "volume": 6400,
                                "delta": "-0.2900",
                                "bid": "3.6400",
                                "ask": "3.8400",
                                "mid_price": "3.7400",
                                "spread_width": "0.2000",
                                "spread_pct": "5.35",
                                "liquidity_label": "workable"
                            }
                        ]
                    },
                    "next_expiration": {
                        "expiration_date": "2026-06-06",
                        "days_to_expiration": 14,
                        "atm_strike": "498.0000",
                        "atm_put_symbol": "QQQ260606P498000.US",
                        "atm_implied_volatility": "0.2580",
                        "atm_delta": "-0.3000",
                        "atm_mid_price": "5.0200",
                        "put_skew_strike": "490.0000",
                        "put_skew_put_symbol": "QQQ260606P490000.US",
                        "put_skew_implied_volatility": "0.2440",
                        "put_skew_delta": "-0.2200",
                        "put_skew_diff": "-0.0140",
                        "median_spread_pct": "5.95",
                        "tight_count": 0,
                        "workable_count": 2,
                        "wide_count": 0,
                        "liquid_strikes": []
                    },
                    "atm_iv_term_diff": "0.0100",
                    "term_structure_label": "flat",
                    "sample_note": "Liquidity buckets use ATM/skew anchors plus the deepest open-interest puts for each expiry."
                }
            ],
        }
        self.pre_open_runs = [
            {
                "id": "mock-preopen-run-0001",
                "strategy_id": "pre_open_put_check_v1",
                "external_account_id": self.account_id,
                "target_session_date": "2026-05-23",
                "assessment": deepcopy(self.pre_open_assessment),
                "checkpoints": [
                    {
                        "key": "open",
                        "label": "Opening Print",
                        "timing_label": "09:30 ET",
                        "scheduled_at": "2026-05-23T13:30:00Z",
                        "captured_at": "2026-05-23T13:30:20Z",
                        "status": "captured",
                        "qqq_change_pct": "-0.82",
                        "spy_change_pct": "-0.48",
                        "semis_change_pct": "-1.18",
                        "qqq_vs_spy_diff": "-0.34",
                        "semis_vs_qqq_diff": "-0.36",
                        "confirmation": "confirmed",
                        "detail": "The open kept QQQ and semis weaker than the broad tape.",
                    },
                    {
                        "key": "first_15",
                        "label": "First 15 Minutes",
                        "timing_label": "09:45 ET",
                        "scheduled_at": "2026-05-23T13:45:00Z",
                        "captured_at": "2026-05-23T13:45:18Z",
                        "status": "captured",
                        "qqq_change_pct": "-0.74",
                        "spy_change_pct": "-0.41",
                        "semis_change_pct": "-1.02",
                        "qqq_vs_spy_diff": "-0.33",
                        "semis_vs_qqq_diff": "-0.28",
                        "confirmation": "mixed",
                        "detail": "Broad downside held, but the move paused enough to keep the read from being one-way.",
                    },
                    {
                        "key": "first_30",
                        "label": "First 30 Minutes",
                        "timing_label": "10:00 ET",
                        "scheduled_at": "2026-05-23T14:00:00Z",
                        "captured_at": "2026-05-23T14:00:24Z",
                        "status": "captured",
                        "qqq_change_pct": "-0.96",
                        "spy_change_pct": "-0.57",
                        "semis_change_pct": "-1.31",
                        "qqq_vs_spy_diff": "-0.39",
                        "semis_vs_qqq_diff": "-0.35",
                        "confirmation": "confirmed",
                        "detail": "The first half hour kept the downside dispersion intact, so the bearish pre-open read held up.",
                    },
                ],
                "review_status": "confirmed",
                "review_summary": "Opening follow-through confirmed the bearish pre-open read across the key post-open checkpoints.",
                "last_reviewed_at": "2026-05-23T14:00:24Z",
                "review_completed_at": "2026-05-23T14:00:24Z",
                "raw_payload": {"source": "mock-preopen-seed"},
                "created_at": "2026-05-23T12:20:00Z",
                "updated_at": "2026-05-23T14:00:24Z",
            }
        ]
        self.snapshot = {
            "id": "mock-snapshot-1",
            "broker_account_id": "mock-account-1",
            "external_account_id": self.account_id,
            "currency": "USD",
            "cash_balance": "1912918.1200",
            "net_liquidation": "1916739.1200",
            "buying_power": "1915590.7800",
            "captured_at": "2026-05-21T02:14:52Z",
            "created_at": "2026-05-21T02:14:52Z",
            "positions": [
                {
                    "symbol": self.symbol,
                    "asset_type": "stock",
                    "quantity": 10,
                    "average_cost": "395.0000",
                    "market_value": "4000.0000",
                    "unrealized_pnl": "50.0000",
                }
            ],
        }
        self.orders = [
            self._build_order(
                local_order_id="mock-order-0001",
                external_order_id="mock-external-0001",
                quantity=1,
                limit_price=301.0,
                status_value="canceled",
                submitted_at="2026-05-20T20:07:13Z",
                updated_at="2026-05-20T20:07:19Z",
                remark="historical canceled seed",
            ),
            self._build_order(
                local_order_id="mock-order-0002",
                external_order_id="mock-external-0002",
                quantity=10,
                limit_price=389.24,
                status_value="filled",
                submitted_at="2026-05-20T19:53:15Z",
                updated_at="2026-05-20T19:53:15Z",
                remark="historical filled seed",
            ),
        ]
        self.executions = [
            {
                "id": "mock-execution-0001",
                "order_id": "mock-order-0002",
                "broker": "longbridge",
                "external_account_id": self.account_id,
                "external_order_id": "mock-external-0002",
                "external_execution_id": "summary:mock-external-0002",
                "symbol": self.symbol,
                "side": "buy",
                "quantity": 10,
                "price": "388.6500",
                "executed_at": "2026-05-20T19:53:15Z",
                "raw_payload": {"source": "order_detail_summary"},
                "created_at": "2026-05-20T19:53:15Z",
                "updated_at": "2026-05-20T19:53:15Z",
            }
        ]
        self.journals = [
            {
                "id": "mock-journal-0001",
                "external_account_id": self.account_id,
                "symbol": self.symbol,
                "entry_type": "review",
                "title": "Filled order review",
                "notes": "Held the entry plan and exited with the expected sizing.",
                "order_id": "mock-order-0002",
                "trade_plan_id": None,
                "execution_id": "mock-execution-0001",
                "tags": ["filled", "discipline"],
                "created_at": "2026-05-20T20:10:00Z",
                "updated_at": "2026-05-20T20:10:00Z",
            }
        ]
        self.market_events = [
            {
                "id": "mock-event-0001",
                "symbol": "UNH.US",
                "event_type": "earnings",
                "title": "UNH earnings window",
                "scheduled_at": "2026-06-01T13:30:00Z",
                "source": "mock-ui",
                "severity": "high",
                "notes": "Avoid opening fresh short-volatility premium without explicit approval.",
                "raw_payload": None,
                "created_at": "2026-05-29T14:00:00Z",
                "updated_at": "2026-05-29T14:00:00Z",
            },
            {
                "id": "mock-event-0002",
                "symbol": None,
                "event_type": "fomc",
                "title": "FOMC minutes",
                "scheduled_at": "2026-06-03T18:00:00Z",
                "source": "mock-ui",
                "severity": "medium",
                "notes": "Macro volatility window.",
                "raw_payload": None,
                "created_at": "2026-05-29T14:00:00Z",
                "updated_at": "2026-05-29T14:00:00Z",
            },
        ]
        self.strategy_proposals = [
            {
                "id": "mock-proposal-0001",
                "strategy_id": "paper_bull_put_v1",
                "external_account_id": self.account_id,
                "mode": "paper",
                "symbol": "QQQ.US",
                "title": "Locked QQQ bull put candidate",
                "proposed_action": "execute_locked_preview",
                "thesis": "Trend and risk filters produced an eligible paper spread candidate.",
                "rationale": "Use the existing preview lock and minimum credit guard before any paper execution.",
                "status": "pending",
                "confidence": "0.680000",
                "expected_max_loss": "248.0000",
                "expected_max_profit": "52.0000",
                "approval_required": True,
                "approved_at": None,
                "rejected_at": None,
                "expires_at": "2026-05-29T20:00:00Z",
                "source": "mock-ui",
                "source_run_id": None,
                "candidate_payload": {"short": "QQQ260626P708000.US", "long": "QQQ260626P705000.US"},
                "risk_payload": {"max_loss": "248.0000", "break_even": "707.4800"},
                "checks": ["candidate_token", "minimum_net_credit", "quote_freshness"],
                "created_at": "2026-05-29T14:45:00Z",
                "updated_at": "2026-05-29T14:45:00Z",
            }
        ]
        self.strategy_runs = [
            {
                "id": "mock-run-0001",
                "strategy_id": "paper_bull_put_v1",
                "external_account_id": self.account_id,
                "mode": "paper",
                "run_type": "monitor",
                "status": "reviewed",
                "symbol": "QQQ.US",
                "proposal_id": "mock-proposal-0001",
                "trade_plan_id": None,
                "order_id": None,
                "spread_id": "mock-spread-0001",
                "started_at": "2026-05-29T14:50:00Z",
                "completed_at": "2026-05-29T14:50:03Z",
                "summary": "Open paper spread monitor snapshot refreshed.",
                "reason": None,
                "metrics_payload": {"estimated_pnl": "-30.0000"},
                "raw_payload": None,
                "created_at": "2026-05-29T14:50:00Z",
                "updated_at": "2026-05-29T14:50:03Z",
            }
        ]
        self.strategy_signals = [
            {
                "id": "mock-signal-0001",
                "strategy_id": "paper_bull_put_v1",
                "external_account_id": self.account_id,
                "mode": "paper",
                "signal_type": "monitor",
                "symbol": "QQQ.US",
                "run_id": "mock-run-0001",
                "proposal_id": "mock-proposal-0001",
                "strength": "0.300000",
                "summary": "Open spread remains above short strike.",
                "detail": "Monitor snapshot did not request a close.",
                "source": "mock-ui",
                "signal_payload": {"should_close": False},
                "emitted_at": "2026-05-29T14:50:03Z",
                "created_at": "2026-05-29T14:50:03Z",
            }
        ]
        self.strategy_reviews = [
            {
                "id": "mock-review-0001",
                "strategy_id": "paper_bull_put_v1",
                "external_account_id": self.account_id,
                "mode": "paper",
                "review_type": "runtime",
                "status": "observed",
                "summary": "Paper strategy is monitoring one open spread.",
                "recommendation": "Do not add another correlated QQQ/SMH/SOXL spread while the current QQQ spread is open.",
                "parameter_name": None,
                "current_value": None,
                "suggested_value": None,
                "run_id": "mock-run-0001",
                "proposal_id": "mock-proposal-0001",
                "journal_entry_id": None,
                "metrics_payload": {"open_spread_count": 1},
                "reviewed_at": "2026-05-29T14:50:03Z",
                "created_at": "2026-05-29T14:50:03Z",
                "updated_at": "2026-05-29T14:50:03Z",
            }
        ]
        self.spreads = [
            {
                "id": "mock-spread-0001",
                "strategy_id": "paper_bull_put_v1",
                "broker": "longbridge",
                "external_account_id": self.account_id,
                "mode": "paper",
                "underlying_symbol": "QQQ.US",
                "expiration_date": "2026-06-19",
                "contracts": 1,
                "width": "3.0000",
                "long_symbol": "QQQ260619P467000.US",
                "long_strike": "467.0000",
                "short_symbol": "QQQ260619P470000.US",
                "short_strike": "470.0000",
                "status": "open",
                "long_entry_order_id": "mock-order-0003",
                "short_entry_order_id": "mock-order-0004",
                "long_exit_order_id": None,
                "short_exit_order_id": "mock-order-0001",
                "entry_long_price": "1.1000",
                "entry_short_price": "2.4000",
                "entry_net_credit": "1.3000",
                "max_profit": "130.0000",
                "max_loss": "170.0000",
                "break_even": "468.7000",
                "account_risk_pct": "0.003400",
                "exit_reason": None,
                "raw_payload": {
                    "source": "mock-seed",
                    "monitor": {
                        "evaluated_at": "2026-05-21T02:14:54Z",
                        "next_monitor_after": "2026-05-21T02:19:54Z",
                        "underlying_price": "501.2500",
                        "estimated_exit_debit": "1.6300",
                        "estimated_pnl": "-33.0000",
                        "days_to_expiration": 29,
                        "exit_reason": "stop_loss",
                        "should_close": True,
                        "take_profit_debit": "0.6500",
                        "stop_loss_debit": "2.6000",
                        "distance_to_take_profit_debit": "0.9500",
                        "distance_to_stop_loss_debit": "1.0000",
                        "short_strike_distance": "31.2500",
                    },
                    "lifecycle": {
                        "warning": "close_order_canceled_manual_action_needed",
                        "manual_action_required": True,
                        "close_order_id": "mock-order-0001",
                        "close_order_state": "canceled",
                        "exit_reason": "stop_loss",
                    },
                },
                "entry_started_at": "2026-05-20T19:45:00Z",
                "opened_at": "2026-05-20T19:46:00Z",
                "closed_at": None,
                "last_synced_at": "2026-05-21T02:14:54Z",
                "created_at": "2026-05-20T19:45:00Z",
                "updated_at": "2026-05-21T02:14:54Z",
            }
        ]
        self.runtime = {
            "id": "mock-runtime-0001",
            "strategy_id": "paper_bull_put_v1",
            "external_account_id": self.account_id,
            "mode": "paper",
            "auto_entry_enabled": True,
            "manual_pause": False,
            "kill_switch_active": False,
            "paused_symbols": [],
            "current_session_date": "2026-05-23",
            "daily_entry_count": 0,
            "daily_realized_pnl": "0.0000",
            "last_scan_at": None,
            "last_scan_result": None,
            "last_scan_symbol": None,
            "last_skip_reason": None,
            "last_action_at": "2026-05-21T02:14:54Z",
            "last_action": "Waiting for the first bull put scan.",
            "last_review_at": None,
            "last_review_status": None,
            "last_review_summary": None,
            "last_error": None,
            "holding_open_position": True,
            "daily_entry_cap_reached": False,
            "entry_block_reason": None,
            "next_action": "monitor_open_spread",
            "active_spread_count": 1,
            "open_spread_count": 1,
            "next_monitor_after": "2026-05-21T02:19:54Z",
            "created_at": "2026-05-21T02:14:54Z",
            "updated_at": "2026-05-21T02:14:54Z",
        }
        self.zero_dte_lottery_runtime = {
            "strategy_id": "zero_dte_lottery_v1",
            "external_account_id": self.account_id,
            "mode": "paper",
            "enabled": True,
            "auto_execute_enabled": False,
            "scan_interval_seconds": 900,
            "scan_window_start": "10:00 ET",
            "scan_window_end": "14:30 ET",
            "max_premium_per_trade": "150.00",
            "contracts_per_trade": 1,
            "max_trades_per_day": 1,
            "symbols": ["QQQ.US"],
        }
        self._apply_scenario()

    def _apply_scenario(self) -> None:
        if self.scenario not in {"normal", "manual-action-required", "recover-eligible"}:
            self._clear_manual_action_seed()
        if self.scenario == "degraded-broker":
            self.broker_profile["configured"] = False
            self.broker_profile["credential_status"] = "degraded"
            self.broker_profile["notes"] = ["Mock degraded broker profile for operator posture regression."]
            self.account["account_sync_status"] = "error"
            self.account["account_last_sync_error"] = "Mock broker account sync failed."
        elif self.scenario == "paused-mandate":
            self.runtime["auto_entry_enabled"] = False
            self.runtime["manual_pause"] = True
            self.runtime["last_action"] = "Manual pause is active."
        elif self.scenario == "advisor-pending-record":
            card = build_mock_advisor_run_card(self.account_id)
            card.update(
                {
                    "status": "succeeded",
                    "recorded": False,
                    "recordable_status": "dry_run_only",
                    "summary": "dry_run_only; 1 proposal(s), 0 review(s); advisor cannot submit orders.",
                    "impact_summary": "0 proposal link(s), 0 review link(s); advisor cannot submit orders.",
                    "proposal_count": 1,
                    "review_count": 0,
                    "warnings": ["Advisor output has not been recorded into proposals or reviews."],
                    "recorded_at": None,
                }
            )
            self.advisor_run_cards = [card]
        elif self.scenario == "scheduler-backoff":
            self.runtime["auto_entry_enabled"] = False
        elif self.scenario == "recover-rejected":
            self.runtime["auto_entry_enabled"] = False
        elif self.scenario == "recover-already-working":
            self.runtime["auto_entry_enabled"] = False
            self._set_order_status("mock-order-0001", "submitted")
            for spread in self.spreads:
                raw_payload = dict(spread.get("raw_payload") or {})
                monitor = dict(raw_payload.get("monitor") or {})
                monitor["should_close"] = True
                monitor["exit_reason"] = "stop_loss"
                raw_payload["monitor"] = monitor
                spread["raw_payload"] = raw_payload
                spread["latest_close_order_status"] = "submitted"
                spread["last_synced_at"] = "2026-05-21T02:14:54Z"

    def _clear_manual_action_seed(self) -> None:
        for spread in self.spreads:
            raw_payload = dict(spread.get("raw_payload") or {})
            raw_payload.pop("lifecycle", None)
            monitor = dict(raw_payload.get("monitor") or {})
            monitor["should_close"] = False
            monitor["exit_reason"] = None
            raw_payload["monitor"] = monitor
            spread["raw_payload"] = raw_payload
            spread["exit_reason"] = None

    def _set_order_status(self, order_id: str, status_value: str) -> None:
        for order in self.orders:
            if order["id"] == order_id:
                order["status"] = status_value
                order["updated_at"] = iso_now()
                return

    def paper_mandate(self) -> dict[str, Any]:
        return build_mock_paper_mandate(
            self.account_id,
            bull_put_auto_entry=bool(self.runtime.get("auto_entry_enabled")),
            zero_dte_auto_execute=bool(self.zero_dte_lottery_runtime.get("auto_execute_enabled")),
            manual_pause=bool(self.runtime.get("manual_pause")),
            kill_switch=bool(self.runtime.get("kill_switch_active")),
        )

    def lifecycle_warnings(self) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        for spread in self.spreads:
            lifecycle = ((spread.get("raw_payload") or {}).get("lifecycle") or {})
            if not lifecycle.get("manual_action_required"):
                continue
            warnings.append(
                {
                    "strategy_id": spread.get("strategy_id"),
                    "code": lifecycle.get("warning") or "manual_action_required",
                    "message": "Close order canceled / manual action needed",
                    "detail": "Review close workflow before leaving unattended.",
                    "manual_action_required": True,
                    "record_id": spread.get("id"),
                    "context": {
                        "spread_status": spread.get("status"),
                        "short_exit_order_id": spread.get("short_exit_order_id"),
                        "short_exit_order_status": lifecycle.get("close_order_state"),
                        "exit_reason": lifecycle.get("exit_reason"),
                    },
                }
            )
        return warnings

    def audit_events(self) -> list[dict[str, Any]]:
        advisor_card = self.advisor_run_cards[0] if self.advisor_run_cards else {}
        advisor_recorded = advisor_card.get("recorded") is True
        events = [
            {
                "id": "mock-audit-advisor-run",
                "emitted_at": "2026-05-29T14:55:00Z",
                "external_account_id": self.account_id,
                "mode": "paper",
                "actor": "advisor",
                "source": "deepseek",
                "strategy": "strategy_advisor",
                "action": "advisor_run_card_recorded" if advisor_recorded else "advisor_run_card_observed",
                "before": None,
                "after": None,
                "order_ids": [],
                "proposal_id": None,
                "run_id": "mock-advisor-run-0001",
                "warning_code": None if advisor_recorded else "advisor_pending_record",
                "summary": "Mock advisor run-card recorded." if advisor_recorded else "Mock advisor run-card is pending record.",
                "detail": None,
                "payload": {"provider": "deepseek", "model": "deepseek-v4-pro"},
                "event_origin": "durable",
            }
        ]
        for warning in self.lifecycle_warnings():
            events.append(
                {
                    "id": f"mock-audit-{warning['record_id']}",
                    "emitted_at": "2026-05-21T02:14:54Z",
                    "external_account_id": self.account_id,
                    "mode": "paper",
                    "actor": "local_system",
                    "source": "orders",
                    "strategy": "paper_bull_put_v1",
                    "action": "manual_action_warning",
                    "before": None,
                    "after": None,
                    "order_ids": [warning["context"]["short_exit_order_id"]],
                    "proposal_id": None,
                    "run_id": None,
                    "warning_code": warning["code"],
                    "summary": warning["message"],
                    "detail": warning["detail"],
                    "payload": warning["context"],
                    "event_origin": "durable",
                }
            )
        return events

    def audit_summary(self, *, external_account_id: str | None = None, mode: str | None = None, limit: int = 200) -> dict[str, Any]:
        events = self.audit_events()
        if external_account_id is not None:
            events = [event for event in events if event.get("external_account_id") == external_account_id]
        if mode is not None:
            events = [event for event in events if event.get("mode") == mode]
        events = events[:limit]
        groups: dict[tuple, dict[str, Any]] = {}
        for event in events:
            key = (
                event.get("external_account_id"),
                event.get("mode"),
                event.get("source"),
                event.get("action"),
                event.get("strategy"),
                event.get("warning_code"),
                event.get("event_origin"),
            )
            group = groups.setdefault(
                key,
                {
                    "external_account_id": event.get("external_account_id"),
                    "mode": event.get("mode"),
                    "source": event.get("source"),
                    "action": event.get("action"),
                    "strategy": event.get("strategy"),
                    "warning_code": event.get("warning_code"),
                    "event_origin": event.get("event_origin"),
                    "count": 0,
                    "latest_emitted_at": event.get("emitted_at"),
                },
            )
            group["count"] += 1
            if str(event.get("emitted_at")) > str(group.get("latest_emitted_at")):
                group["latest_emitted_at"] = event.get("emitted_at")
        return {
            "generated_at": iso_now(),
            "external_account_id": external_account_id,
            "mode": mode,
            "since": None,
            "limit": limit,
            "event_count": len(events),
            "warning_count": len([event for event in events if event.get("warning_code")]),
            "groups": sorted(groups.values(), key=lambda item: item["latest_emitted_at"], reverse=True),
        }

    def operator_status_snapshot(self) -> dict[str, Any]:
        lifecycle_warnings = self.lifecycle_warnings()
        audit_events = self.audit_events()
        warning_count = sum(1 for event in audit_events if event.get("warning_code"))
        scheduler_backoff = self.scenario == "scheduler-backoff"
        degraded_broker = self.scenario == "degraded-broker"
        advisor_pending = self.scenario == "advisor-pending-record"
        status_value = (
            "fail"
            if lifecycle_warnings
            else "warn"
            if scheduler_backoff or degraded_broker or advisor_pending or self.runtime.get("manual_pause") or self.runtime.get("auto_entry_enabled")
            else "pass"
        )
        reason = (
            f"{len(lifecycle_warnings)} strategy lifecycle warning(s) require operator review."
            if lifecycle_warnings
            else "Scheduler backoff is active for mock order reconciliation."
            if scheduler_backoff
            else "Broker profile is degraded in the mock scenario."
            if degraded_broker
            else "Advisor output is pending explicit Record Output."
            if advisor_pending
            else "Manual pause is active for the paper mandate."
            if self.runtime.get("manual_pause")
            else "Bull put auto-entry is enabled; verify this is intentional before leaving the app unattended."
            if self.runtime.get("auto_entry_enabled")
            else "All operator posture checks passed."
        )
        scheduler_summary = self._scheduler_summary(backoff=scheduler_backoff)
        return {
            "external_account_id": self.account_id,
            "mode": "paper",
            "generated_at": iso_now(),
            "status": status_value,
            "ready_for_unattended": status_value != "fail",
            "operator_posture_reason": reason,
            "checks": [
                {
                    "name": "scheduler_recent_runs",
                    "status": "warn" if scheduler_backoff else "pass",
                    "detail": scheduler_summary["status_detail"],
                    "reason_code": "scheduler_backoff" if scheduler_backoff else "scheduler_recent_runs_healthy",
                    "severity": "warning" if scheduler_backoff else "info",
                },
                {
                    "name": "lifecycle_warnings",
                    "status": "fail" if lifecycle_warnings else "pass",
                    "detail": reason,
                    "reason_code": "manual_action_required" if lifecycle_warnings else "no_manual_action_required",
                    "severity": "critical" if lifecycle_warnings else "info",
                },
            ],
            "controls": {
                "external_account_id": self.account_id,
                "execution_mode": "paper",
                "live_trading_enabled": False,
                "scheduler_enabled": True,
                "approval_required_for_execution": True,
                "llm_direct_execution_allowed": False,
                "paper_execution_allowed": True,
                "live_execution_allowed": False,
                "automation_controls": [],
                "permission_boundaries": [],
                "paper_mandate": self.paper_mandate(),
            },
            "broker_profiles": [deepcopy(self.broker_profile)],
            "paper_mandate": self.paper_mandate(),
            "audit_events": deepcopy(audit_events[:5]),
            "audit_summary": {
                "event_count": len(audit_events),
                "warning_count": warning_count,
                "by_action": {
                    "advisor_run_card_recorded": 1,
                    "manual_action_warning": warning_count,
                },
            },
            "bull_put_runtime": self._runtime_with_computed_fields(),
            "zero_dte_lottery_runtime": self.get_zero_dte_lottery_runtime(self.account_id),
            "active_bull_put_spread_count": len(
                [spread for spread in self.spreads if spread["status"] in {"open", "exit_pending_short", "exit_pending_long"}]
            ),
            "open_order_count": len([order for order in self.orders if order["status"] in {"created", "submitted", "partially_filled"}]),
            "lifecycle_warnings": lifecycle_warnings,
            "recent_scheduler_runs": [],
            "recent_scheduler_summaries": [scheduler_summary],
        }

    def _scheduler_summary(self, *, backoff: bool = False) -> dict[str, Any]:
        if backoff:
            return {
                "job_key": "orders-sync",
                "job_label": "order reconciliation",
                "external_account_id": self.account_id,
                "posture": "warn",
                "due_status": "backoff",
                "status_detail": "Backoff active after 2 consecutive failure(s): mock timeout.",
                "last_status": "backoff",
                "last_started_at": "2026-05-21T02:14:54Z",
                "last_completed_at": "2026-05-21T02:14:55Z",
                "next_attempt_at": "2026-05-21T02:29:55Z",
                "backoff_seconds": 900,
                "consecutive_failures": 2,
                "error_message": "mock timeout",
                "detail": "Transient broker failure; backing off for 900s.",
                "last_problem_at": "2026-05-21T02:14:54Z",
                "recent_run_count": 2,
                "recent_problem_count": 2,
            }
        return {
            "job_key": "bull-put-monitor",
            "job_label": "bull put monitor",
            "external_account_id": self.account_id,
            "posture": "pass",
            "due_status": "healthy",
            "status_detail": "Last scheduler run succeeded.",
            "last_status": "succeeded",
            "last_started_at": "2026-05-21T02:14:54Z",
            "last_completed_at": "2026-05-21T02:14:55Z",
            "next_attempt_at": None,
            "backoff_seconds": None,
            "consecutive_failures": 0,
            "error_message": None,
            "detail": "Mock scheduler monitor completed.",
            "last_problem_at": None,
            "recent_run_count": 1,
            "recent_problem_count": 0,
        }

    def _build_order(
        self,
        *,
        local_order_id: str,
        external_order_id: str,
        quantity: int,
        limit_price: float | None,
        status_value: str,
        submitted_at: str,
        updated_at: str,
        remark: str,
        stop_price: float | None = None,
    ) -> dict[str, Any]:
        return {
            "id": local_order_id,
            "broker": "longbridge",
            "external_account_id": self.account_id,
            "trade_plan_id": None,
            "external_order_id": external_order_id,
            "client_order_id": f"client-{local_order_id}",
            "symbol": self.symbol,
            "asset_type": "stock",
            "side": "buy",
            "quantity": quantity,
            "order_type": "limit" if limit_price is not None else "market",
            "time_in_force": "day",
            "mode": "paper",
            "status": status_value,
            "limit_price": format_price(limit_price),
            "stop_price": format_price(stop_price),
            "option_contract": None,
            "raw_payload": {
                "remote_order": {
                    "order_id": external_order_id,
                    "symbol": self.symbol,
                    "status": status_value.upper(),
                    "quantity": str(quantity),
                    "price": f"{limit_price:.2f}" if limit_price is not None else None,
                },
                "submission_request": {
                    "external_account_id": self.account_id,
                    "symbol": self.symbol,
                    "side": "buy",
                    "quantity": quantity,
                    "order_type": "limit" if limit_price is not None else "market",
                    "time_in_force": "day",
                    "mode": "paper",
                    "limit_price": f"{limit_price:.2f}" if limit_price is not None else None,
                    "remark": remark,
                },
            },
            "submitted_at": submitted_at,
            "created_at": submitted_at,
            "updated_at": updated_at,
        }

    def list_orders(self, external_account_id: str | None) -> list[dict[str, Any]]:
        if external_account_id and external_account_id != self.account_id:
            return []
        return deepcopy(sorted(self.orders, key=lambda item: item["updated_at"], reverse=True))

    def list_pre_open_runs(
        self,
        external_account_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.pre_open_runs
        if external_account_id is not None:
            rows = [row for row in rows if row["external_account_id"] == external_account_id]
        return deepcopy(rows[:limit])

    def capture_pre_open_run(self, external_account_id: str) -> dict[str, Any]:
        now = iso_now()
        target_session_date = self.pre_open_assessment.get("target_session_date", "2026-05-23")
        existing = next(
            (
                row
                for row in self.pre_open_runs
                if row["external_account_id"] == external_account_id
                and row["target_session_date"] == target_session_date
            ),
            None,
        )
        if existing is None:
            existing = {
                "id": f"mock-preopen-run-{len(self.pre_open_runs) + 1:04d}",
                "strategy_id": "pre_open_put_check_v1",
                "external_account_id": external_account_id,
                "target_session_date": target_session_date,
                "assessment": deepcopy(self.pre_open_assessment),
                "checkpoints": [],
                "review_status": "awaiting_open",
                "review_summary": None,
                "last_reviewed_at": None,
                "review_completed_at": None,
                "raw_payload": {"source": "mock-preopen-save"},
                "created_at": now,
                "updated_at": now,
            }
            self.pre_open_runs.insert(0, existing)
        else:
            existing["assessment"] = deepcopy(self.pre_open_assessment)
            existing["updated_at"] = now
        return {"run": deepcopy(existing), "captured": True, "reason": None}

    def get_order(self, order_id: str) -> dict[str, Any]:
        for order in self.orders:
            if order["id"] == order_id:
                return order
        raise KeyError(order_id)

    def submit_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._order_counter += 1
        now = iso_now()
        order = self._build_order(
            local_order_id=f"mock-order-{self._order_counter}",
            external_order_id=f"mock-external-{self._order_counter}",
            quantity=int(payload["quantity"]),
            limit_price=float(payload["limit_price"]) if payload.get("limit_price") is not None else None,
            stop_price=float(payload["stop_price"]) if payload.get("stop_price") is not None else None,
            status_value="submitted",
            submitted_at=now,
            updated_at=now,
            remark=str(payload.get("remark") or "mock submit"),
        )
        order["symbol"] = str(payload.get("symbol") or self.symbol).upper()
        order["side"] = str(payload.get("side") or "buy")
        order["order_type"] = str(payload.get("order_type") or "limit")
        order["time_in_force"] = str(payload.get("time_in_force") or "day")
        order["raw_payload"]["remote_order"]["symbol"] = order["symbol"]
        order["raw_payload"]["remote_order"]["side"] = order["side"].upper()
        order["raw_payload"]["remote_order"]["order_type"] = order["order_type"].upper()
        order["raw_payload"]["submission_request"].update(
            {
                "symbol": order["symbol"],
                "side": order["side"],
                "quantity": order["quantity"],
                "order_type": order["order_type"],
                "time_in_force": order["time_in_force"],
                "limit_price": f"{float(payload['limit_price']):.2f}" if payload.get("limit_price") is not None else None,
                "stop_price": f"{float(payload['stop_price']):.2f}" if payload.get("stop_price") is not None else None,
            }
        )
        self.orders.insert(0, order)
        return deepcopy(order)

    def replace_order(self, order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        order = self.get_order(order_id)
        if order["status"] not in {"created", "submitted", "partially_filled"}:
            raise ValueError("Only working orders can be replaced.")
        order["quantity"] = int(payload["quantity"])
        order["limit_price"] = format_price(float(payload["limit_price"])) if payload.get("limit_price") is not None else None
        order["stop_price"] = format_price(float(payload["stop_price"])) if payload.get("stop_price") is not None else None
        order["updated_at"] = iso_now()
        order["raw_payload"]["remote_order"]["status"] = "REPLACEDNOTREPORTED"
        order["raw_payload"]["remote_order"]["quantity"] = str(order["quantity"])
        order["raw_payload"]["remote_order"]["price"] = (
            f"{float(payload['limit_price']):.2f}" if payload.get("limit_price") is not None else None
        )
        if payload.get("remark") is not None:
            order["raw_payload"]["replace_request"] = {"remark": payload["remark"]}
        return deepcopy(order)

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        if order["status"] not in {"created", "submitted", "partially_filled"}:
            raise ValueError("Only working orders can be canceled.")
        order["status"] = "canceled"
        order["updated_at"] = iso_now()
        order["raw_payload"]["remote_order"]["status"] = "CANCELED"
        order["raw_payload"]["remote_order"]["last_done"] = (
            f"{float(order['limit_price']):.2f}" if order["limit_price"] is not None else None
        )
        return deepcopy(order)

    def list_executions(
        self,
        external_account_id: str | None = None,
        order_id: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.executions
        if external_account_id is not None:
            rows = [row for row in rows if row["external_account_id"] == external_account_id]
        if order_id is not None:
            rows = [row for row in rows if row["order_id"] == order_id]
        return deepcopy(rows)

    def list_journals(
        self,
        external_account_id: str | None = None,
        order_id: str | None = None,
        trade_plan_id: str | None = None,
        entry_type: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.journals
        if external_account_id is not None:
            rows = [row for row in rows if row["external_account_id"] == external_account_id]
        if order_id is not None:
            rows = [row for row in rows if row["order_id"] == order_id]
        if trade_plan_id is not None:
            rows = [row for row in rows if row["trade_plan_id"] == trade_plan_id]
        if entry_type is not None:
            rows = [row for row in rows if row["entry_type"] == entry_type]
        return deepcopy(sorted(rows, key=lambda item: item["updated_at"], reverse=True))

    def create_journal(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._journal_counter += 1
        now = iso_now()
        entry = {
            "id": f"mock-journal-{self._journal_counter}",
            "external_account_id": str(payload["external_account_id"]),
            "symbol": str(payload["symbol"]).upper(),
            "entry_type": str(payload["entry_type"]),
            "title": str(payload["title"]).strip(),
            "notes": str(payload["notes"]).strip(),
            "order_id": payload.get("order_id"),
            "trade_plan_id": payload.get("trade_plan_id"),
            "execution_id": payload.get("execution_id"),
            "tags": [str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()],
            "created_at": now,
            "updated_at": now,
        }
        self.journals.insert(0, entry)
        return deepcopy(entry)

    def strategy_experiment_snapshot(
        self,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        return {
            "external_account_id": external_account_id,
            "proposals": self.list_strategy_proposals(external_account_id, strategy_id, limit=limit),
            "runs": self.list_strategy_runs(external_account_id, strategy_id, limit=limit),
            "signals": self.list_strategy_signals(external_account_id, strategy_id, limit=limit),
            "reviews": self.list_strategy_reviews(external_account_id, strategy_id, limit=limit),
        }

    def covered_call_activity_snapshot(
        self,
        external_account_id: str | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        proposals = self.list_strategy_proposals(external_account_id, "covered_call_v1", limit=limit)
        runs = self.list_strategy_runs(external_account_id, "covered_call_v1", limit=limit)
        signals = self.list_strategy_signals(external_account_id, "covered_call_v1", limit=limit)
        reviews = self.list_strategy_reviews(external_account_id, "covered_call_v1", limit=limit)
        active_statuses = {"pending", "approved"}
        activity_times = [
            *(row["updated_at"] for row in proposals if row.get("updated_at")),
            *(row["created_at"] for row in runs if row.get("created_at")),
            *(row["emitted_at"] for row in signals if row.get("emitted_at")),
            *(row["reviewed_at"] for row in reviews if row.get("reviewed_at")),
        ]
        return {
            "external_account_id": external_account_id,
            "summary": {
                "external_account_id": external_account_id,
                "total_proposals": len(proposals),
                "active_proposals": sum(1 for row in proposals if row["status"] in active_statuses),
                "executed_positions": sum(
                    1
                    for row in proposals
                    if row["proposed_action"] == "sell_covered_call" and row["status"] == "executed"
                ),
                "pending_rolls": sum(
                    1
                    for row in proposals
                    if row["proposed_action"] == "roll_covered_call" and row["status"] in active_statuses
                ),
                "close_runs": sum(1 for row in runs if row["run_type"] == "proposal_close"),
                "latest_activity_at": max(activity_times) if activity_times else None,
            },
            "proposals": proposals,
            "runs": runs,
            "signals": signals,
            "reviews": reviews,
        }

    def list_strategy_proposals(
        self,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.strategy_proposals
        if external_account_id is not None:
            rows = [row for row in rows if row["external_account_id"] == external_account_id]
        if strategy_id is not None:
            rows = [row for row in rows if row["strategy_id"] == strategy_id]
        return deepcopy(sorted(rows, key=lambda item: item["updated_at"], reverse=True)[:limit])

    def list_strategy_runs(
        self,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.strategy_runs
        if external_account_id is not None:
            rows = [row for row in rows if row["external_account_id"] == external_account_id]
        if strategy_id is not None:
            rows = [row for row in rows if row["strategy_id"] == strategy_id]
        return deepcopy(sorted(rows, key=lambda item: item["created_at"], reverse=True)[:limit])

    def list_strategy_signals(
        self,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.strategy_signals
        if external_account_id is not None:
            rows = [row for row in rows if row["external_account_id"] == external_account_id]
        if strategy_id is not None:
            rows = [row for row in rows if row["strategy_id"] == strategy_id]
        return deepcopy(sorted(rows, key=lambda item: item["emitted_at"], reverse=True)[:limit])

    def list_strategy_reviews(
        self,
        external_account_id: str | None = None,
        strategy_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.strategy_reviews
        if external_account_id is not None:
            rows = [row for row in rows if row["external_account_id"] == external_account_id]
        if strategy_id is not None:
            rows = [row for row in rows if row["strategy_id"] == strategy_id]
        return deepcopy(sorted(rows, key=lambda item: item["reviewed_at"], reverse=True)[:limit])

    def list_market_events(
        self,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows = self.market_events
        if symbol is not None:
            normalized_symbol = symbol.upper()
            rows = [row for row in rows if row["symbol"] in {None, normalized_symbol}]
        return deepcopy(sorted(rows, key=lambda item: item["scheduled_at"])[:limit])

    def list_spreads(
        self,
        external_account_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self.spreads
        if external_account_id is not None:
            rows = [row for row in rows if row["external_account_id"] == external_account_id]
        if status is not None:
            rows = [row for row in rows if row["status"] == status]
        return deepcopy(sorted(rows, key=lambda item: item["updated_at"], reverse=True))

    def recover_close_eligibility(
        self,
        spread_id: str,
        *,
        external_account_id: str | None = None,
        mode: str = "paper",
    ) -> dict[str, Any]:
        spread = self.get_spread(spread_id)
        order = None
        if spread.get("short_exit_order_id"):
            try:
                order = self.get_order(str(spread["short_exit_order_id"]))
            except KeyError:
                order = None
        raw_payload = spread.get("raw_payload") if isinstance(spread.get("raw_payload"), dict) else {}
        monitor = raw_payload.get("monitor") if isinstance(raw_payload.get("monitor"), dict) else {}
        latest_should_close = bool(monitor.get("should_close")) or spread.get("latest_monitor_should_close") is True
        order_status = order.get("status") if isinstance(order, dict) else spread.get("latest_close_order_status")
        reasons: list[str] = []
        if mode != "paper":
            reasons.append("mode_not_paper")
        if spread.get("mode") != "paper":
            reasons.append("spread_not_paper")
        if external_account_id is not None and external_account_id != spread.get("external_account_id"):
            reasons.append("account_mismatch")
        if spread.get("status") != "open":
            reasons.append("spread_not_open")
        if not latest_should_close:
            reasons.append("close_not_required")
        if not spread.get("short_exit_order_id") or order is None:
            reasons.append("missing_short_close_order")
        elif order_status in {"created", "submitted", "partially_filled"}:
            reasons.append("working_replacement_exists")
        elif order_status not in {"canceled", "cancelled", "rejected", "expired"}:
            reasons.append("short_close_order_not_failed")
        return {
            "spread_id": spread["id"],
            "eligible": not reasons,
            "reasons": reasons,
            "external_account_id": spread["external_account_id"],
            "mode": spread.get("mode", "paper"),
            "latest_should_close": latest_should_close,
            "old_short_close_order_id": spread.get("short_exit_order_id"),
            "old_short_close_order_status": order_status,
            "working_replacement_order_id": order["id"] if isinstance(order, dict) and order_status in {"created", "submitted", "partially_filled"} else None,
            "max_debit_required_hint": monitor.get("estimated_exit_debit"),
        }

    def recover_close(self, spread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("confirm_paper_order") is not True:
            raise ValueError("Set confirm_paper_order=true before submitting a paper recovery order.")
        eligibility = self.recover_close_eligibility(
            spread_id,
            external_account_id=payload.get("external_account_id"),
            mode=str(payload.get("mode") or "paper"),
        )
        if not eligibility["eligible"]:
            raise ValueError(f"Recovery blocked: {', '.join(eligibility['reasons'])}.")
        spread = self.get_spread(spread_id)
        order = self.submit_order(
            {
                "external_account_id": spread["external_account_id"],
                "symbol": spread["short_symbol"],
                "asset_type": "option",
                "side": "buy",
                "quantity": spread["contracts"],
                "order_type": "limit",
                "time_in_force": "day",
                "mode": "paper",
                "limit_price": payload.get("max_debit") or eligibility.get("max_debit_required_hint") or "1.00",
                "remark": payload.get("note") or "mock recover close",
            }
        )
        spread["status"] = "exit_pending_short"
        spread["short_exit_order_id"] = order["id"]
        spread["latest_close_order_status"] = order["status"]
        spread["updated_at"] = iso_now()
        return deepcopy(spread)

    def get_runtime_state(self, external_account_id: str) -> dict[str, Any]:
        if external_account_id != self.account_id:
            raise KeyError(external_account_id)
        return self._runtime_with_computed_fields()

    def _runtime_with_computed_fields(self) -> dict[str, Any]:
        runtime = deepcopy(self.runtime)
        active_spreads = [
            spread
            for spread in self.spreads
            if spread["status"] in {"entry_pending_long", "entry_pending_short", "open", "exit_pending_short", "exit_pending_long"}
        ]
        open_spreads = [spread for spread in active_spreads if spread["status"] == "open"]
        runtime["holding_open_position"] = bool(open_spreads)
        runtime["daily_entry_cap_reached"] = int(runtime["daily_entry_count"]) >= 1
        runtime["active_spread_count"] = len(active_spreads)
        runtime["open_spread_count"] = len(open_spreads)
        runtime["next_monitor_after"] = (
            ((active_spreads[0].get("raw_payload") or {}).get("monitor") or {}).get("next_monitor_after")
            if active_spreads
            else None
        )
        if runtime["kill_switch_active"] or runtime["manual_pause"] or not runtime["auto_entry_enabled"]:
            runtime["next_action"] = "resolve_runtime_controls"
        elif active_spreads:
            runtime["next_action"] = "monitor_open_spread"
        elif runtime["daily_entry_cap_reached"]:
            runtime["next_action"] = "wait_next_session"
        else:
            runtime["next_action"] = "scan_for_entry"
        runtime["entry_block_reason"] = (
            "Bull put daily entry cap has already been reached for this account."
            if runtime["daily_entry_cap_reached"] and not active_spreads
            else None
        )
        return runtime

    def update_runtime_state(self, external_account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if external_account_id != self.account_id:
            raise KeyError(external_account_id)
        now = iso_now()
        if "auto_entry_enabled" in payload:
            self.runtime["auto_entry_enabled"] = bool(payload["auto_entry_enabled"])
        if "manual_pause" in payload:
            self.runtime["manual_pause"] = bool(payload["manual_pause"])
        if "kill_switch_active" in payload:
            self.runtime["kill_switch_active"] = bool(payload["kill_switch_active"])
        if "paused_symbols" in payload:
            self.runtime["paused_symbols"] = [
                str(symbol).strip().upper()
                for symbol in payload["paused_symbols"]
                if str(symbol).strip()
            ]
        self.runtime["last_action"] = "Updated bull put runtime controls."
        self.runtime["last_action_at"] = now
        self.runtime["updated_at"] = now
        return self._runtime_with_computed_fields()

    def get_zero_dte_lottery_runtime(self, external_account_id: str) -> dict[str, Any]:
        if external_account_id != self.account_id:
            raise KeyError(external_account_id)
        return deepcopy(self.zero_dte_lottery_runtime)

    def update_zero_dte_lottery_runtime(self, external_account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if external_account_id != self.account_id:
            raise KeyError(external_account_id)
        if "auto_execute_enabled" in payload:
            self.zero_dte_lottery_runtime["auto_execute_enabled"] = bool(payload["auto_execute_enabled"])
        return deepcopy(self.zero_dte_lottery_runtime)

    def zero_dte_lottery_preview(
        self,
        *,
        external_account_id: str,
        symbol: str = "QQQ.US",
        direction: str = "auto",
    ) -> dict[str, Any]:
        if external_account_id != self.account_id:
            raise KeyError(external_account_id)
        normalized_symbol = symbol.upper()
        selected_direction = "call" if direction == "auto" else direction
        evaluated_at = iso_now()
        return {
            "strategy_id": "zero_dte_lottery_v1",
            "external_account_id": external_account_id,
            "mode": "paper",
            "evaluated_at": evaluated_at,
            "eligible": True,
            "reasons": [],
            "warnings": [],
            "symbol": normalized_symbol,
            "direction": selected_direction,
            "selected_expiration_date": "2026-06-05",
            "days_to_expiration": 0,
            "max_premium_per_trade": "150.00",
            "underlying_price": "735.0000",
            "underlying_change_pct": "0.55",
            "candidate": {
                "underlying_symbol": normalized_symbol,
                "direction": selected_direction,
                "expiration_date": "2026-06-05",
                "days_to_expiration": 0,
                "contracts": 1,
                "option_symbol": "QQQ260605C736000.US" if selected_direction == "call" else "QQQ260605P734000.US",
                "strike": "736.0000" if selected_direction == "call" else "734.0000",
                "option_bid": "1.4000",
                "option_ask": "1.4500",
                "option_mid": "1.4300",
                "premium_at_ask": "145.00",
                "max_loss": "145.00",
                "underlying_price": "735.0000",
                "delta": "0.2200",
                "open_interest": 400,
                "volume": 25,
                "quote_timestamp": evaluated_at,
            },
        }

    def run_zero_dte_lottery_scan(
        self,
        *,
        external_account_id: str,
        symbol: str = "QQQ.US",
        direction: str = "auto",
        force: bool = False,
    ) -> dict[str, Any]:
        if external_account_id != self.account_id:
            raise KeyError(external_account_id)
        scanned_at = iso_now()
        if not force and not self.zero_dte_lottery_runtime["auto_execute_enabled"]:
            return {
                "strategy_id": "zero_dte_lottery_v1",
                "external_account_id": external_account_id,
                "mode": "paper",
                "scanned_at": scanned_at,
                "executed": False,
                "preview": None,
                "execution": None,
                "run": None,
                "signal": None,
                "reason": "Zero-DTE lottery auto-execution is disabled by configuration.",
            }
        preview = self.zero_dte_lottery_preview(
            external_account_id=external_account_id,
            symbol=symbol,
            direction=direction,
        )
        candidate = preview["candidate"]
        self._order_counter += 1
        order = self._build_order(
            local_order_id=f"mock-order-{self._order_counter}",
            external_order_id=f"mock-external-{self._order_counter}",
            quantity=1,
            limit_price=1.45,
            status_value="submitted",
            submitted_at=scanned_at,
            updated_at=scanned_at,
            remark="zero_dte_lottery_v1:manual-scan" if force else "zero_dte_lottery_v1:auto-scan",
        )
        order["symbol"] = candidate["option_symbol"]
        order["asset_type"] = "option"
        order["side"] = "buy"
        order["option_contract"] = {
            "underlying_symbol": candidate["underlying_symbol"],
            "expiration_date": candidate["expiration_date"],
            "strike": candidate["strike"],
            "right": candidate["direction"],
        }
        order["raw_payload"]["remote_order"]["symbol"] = order["symbol"]
        order["raw_payload"]["submission_request"].update(
            {
                "symbol": order["symbol"],
                "asset_type": "option",
                "side": "buy",
                "quantity": 1,
                "order_type": "limit",
                "mode": "paper",
                "limit_price": "1.45",
                "remark": order["raw_payload"]["submission_request"]["remark"],
            }
        )
        self.orders.insert(0, order)
        run = {
            "id": f"mock-run-zero-dte-{self._order_counter}",
            "strategy_id": "zero_dte_lottery_v1",
            "external_account_id": self.account_id,
            "mode": "paper",
            "run_type": "auto_scan",
            "status": "executed",
            "symbol": preview["symbol"],
            "proposal_id": None,
            "trade_plan_id": None,
            "order_id": order["id"],
            "spread_id": None,
            "started_at": scanned_at,
            "completed_at": scanned_at,
            "summary": f"Zero-DTE lottery paper order submitted for {order['symbol']}.",
            "reason": None,
            "metrics_payload": deepcopy(preview),
            "raw_payload": None,
            "created_at": scanned_at,
            "updated_at": scanned_at,
        }
        signal = {
            "id": f"mock-signal-zero-dte-{self._order_counter}",
            "strategy_id": "zero_dte_lottery_v1",
            "external_account_id": self.account_id,
            "mode": "paper",
            "signal_type": "execution",
            "symbol": preview["symbol"],
            "run_id": run["id"],
            "proposal_id": None,
            "strength": "0.200000",
            "summary": f"Zero-DTE lottery paper order submitted for {order['symbol']}.",
            "detail": None,
            "source": "zero_dte_lottery_v1",
            "signal_payload": deepcopy(preview),
            "emitted_at": scanned_at,
            "created_at": scanned_at,
        }
        self.strategy_runs.insert(0, run)
        self.strategy_signals.insert(0, signal)
        return {
            "strategy_id": "zero_dte_lottery_v1",
            "external_account_id": external_account_id,
            "mode": "paper",
            "scanned_at": scanned_at,
            "executed": True,
            "preview": preview,
            "execution": {
                "preview": preview,
                "order": deepcopy(order),
                "submitted_at": scanned_at,
            },
            "run": deepcopy(run),
            "signal": deepcopy(signal),
            "reason": None,
        }

    def run_entry_scan(self, external_account_id: str, *, force: bool) -> dict[str, Any]:
        if external_account_id != self.account_id:
            raise KeyError(external_account_id)
        now = iso_now()
        self.runtime["last_scan_at"] = now

        if self.runtime["kill_switch_active"]:
            self.runtime["last_scan_result"] = "skipped"
            self.runtime["last_skip_reason"] = "Bull put kill switch is active for this account."
            self.runtime["updated_at"] = now
            return {
                "strategy_state": self._runtime_with_computed_fields(),
                "scanned_at": now,
                "executed": False,
                "executed_spread": None,
                "previews": [],
                "reason": self.runtime["last_skip_reason"],
            }

        if self.runtime["manual_pause"]:
            self.runtime["last_scan_result"] = "skipped"
            self.runtime["last_skip_reason"] = "Bull put strategy is manually paused for this account."
            self.runtime["updated_at"] = now
            return {
                "strategy_state": self._runtime_with_computed_fields(),
                "scanned_at": now,
                "executed": False,
                "executed_spread": None,
                "previews": [],
                "reason": self.runtime["last_skip_reason"],
            }

        active_spreads = [spread for spread in self.spreads if spread["status"] in {"open", "exit_pending_short", "exit_pending_long"}]
        if active_spreads:
            self.runtime["last_scan_result"] = "skipped"
            self.runtime["last_skip_reason"] = "Bull put daily entry cap has already been reached for this account."
            self.runtime["updated_at"] = now
            return {
                "strategy_state": self._runtime_with_computed_fields(),
                "scanned_at": now,
                "executed": False,
                "executed_spread": None,
                "previews": [],
                "reason": self.runtime["last_skip_reason"],
            }

        self._spread_counter += 1
        spread_id = f"mock-spread-{self._spread_counter}"
        spread = {
            "id": spread_id,
            "strategy_id": "paper_bull_put_v1",
            "broker": "longbridge",
            "external_account_id": self.account_id,
            "mode": "paper",
            "underlying_symbol": "QQQ.US",
            "expiration_date": "2026-06-19",
            "contracts": 1,
            "width": "3.0000",
            "long_symbol": "QQQ260619P467000.US",
            "long_strike": "467.0000",
            "short_symbol": "QQQ260619P470000.US",
            "short_strike": "470.0000",
            "status": "open",
            "long_entry_order_id": None,
            "short_entry_order_id": None,
            "long_exit_order_id": None,
            "short_exit_order_id": None,
            "entry_long_price": "1.1000",
            "entry_short_price": "2.4000",
            "entry_net_credit": "1.3000",
            "max_profit": "130.0000",
            "max_loss": "170.0000",
            "break_even": "468.7000",
            "account_risk_pct": "0.003400",
            "exit_reason": None,
            "raw_payload": {
                "source": "mock-auto-scan",
                "force": force,
                "monitor": {
                    "evaluated_at": now,
                    "next_monitor_after": now,
                    "underlying_price": "501.2500",
                    "estimated_exit_debit": "1.6000",
                    "estimated_pnl": "-30.0000",
                    "days_to_expiration": 27,
                    "exit_reason": None,
                    "should_close": False,
                    "take_profit_debit": "0.6500",
                    "stop_loss_debit": "2.6000",
                    "distance_to_take_profit_debit": "0.9500",
                    "distance_to_stop_loss_debit": "1.0000",
                    "short_strike_distance": "31.2500",
                },
            },
            "entry_started_at": now,
            "opened_at": now,
            "closed_at": None,
            "last_synced_at": now,
            "created_at": now,
            "updated_at": now,
        }
        self.spreads.insert(0, spread)
        self.runtime["daily_entry_count"] = int(self.runtime["daily_entry_count"]) + 1
        self.runtime["last_scan_result"] = "executed"
        self.runtime["last_scan_symbol"] = "QQQ.US"
        self.runtime["last_skip_reason"] = None
        self.runtime["last_action"] = "Opened bull put spread for QQQ.US."
        self.runtime["last_action_at"] = now
        self.runtime["updated_at"] = now
        self.create_journal(
            {
                "external_account_id": self.account_id,
                "symbol": "QQQ.US",
                "entry_type": "plan",
                "title": "Bull put spread opened for QQQ.US",
                "notes": "Mock runtime scan opened a bull put spread for dashboard regression.",
                "tags": ["strategy", "bull-put", "entry", "paper"],
            }
        )
        return {
            "strategy_state": self._runtime_with_computed_fields(),
            "scanned_at": now,
            "executed": True,
            "executed_spread": deepcopy(spread),
            "previews": [],
            "reason": None,
        }

    def run_review(self, external_account_id: str, *, force: bool) -> dict[str, Any]:
        if external_account_id != self.account_id:
            raise KeyError(external_account_id)
        now = iso_now()
        summary = "Suggest tightening short delta target from 0.22 to 0.20 after repeated stop-loss exits."
        self.runtime["last_review_at"] = now
        self.runtime["last_review_status"] = "suggested"
        self.runtime["last_review_summary"] = summary
        self.runtime["last_action"] = summary
        self.runtime["last_action_at"] = now
        self.runtime["updated_at"] = now
        journal = self.create_journal(
            {
                "external_account_id": self.account_id,
                "symbol": "QQQ.US",
                "entry_type": "review",
                "title": "Bull put strategy review",
                "notes": summary,
                "tags": ["strategy", "bull-put", "review", "suggested", "paper"],
            }
        )
        return {
            "strategy_state": self._runtime_with_computed_fields(),
            "evaluated_at": now,
            "review_status": "suggested",
            "closed_spreads_considered": 20,
            "lookback_days": 30,
            "net_realized_pnl": "-420.0000",
            "take_profit_rate": "0.2500",
            "stop_loss_rate": "0.4000",
            "recommendation": summary,
            "parameter_name": "short_delta_target",
            "current_value": "0.22",
            "suggested_value": "0.20",
            "journal_entry_id": journal["id"],
            "reviewed_spread_ids": [spread["id"] for spread in self.spreads if spread["status"] == "closed"],
            "reason": None,
            "force": force,
        }

    def get_spread(self, spread_id: str) -> dict[str, Any]:
        for spread in self.spreads:
            if spread["id"] == spread_id:
                return spread
        raise KeyError(spread_id)

    def refresh_spread(self, spread_id: str) -> dict[str, Any]:
        spread = self.get_spread(spread_id)
        now = iso_now()
        spread["last_synced_at"] = now
        spread["updated_at"] = now
        return deepcopy(spread)

    def monitor_spread(self, spread_id: str) -> dict[str, Any]:
        spread = self.get_spread(spread_id)
        now = iso_now()
        should_close = spread["status"] in {"open", "exit_pending_short", "exit_pending_long"}
        raw_payload = dict(spread.get("raw_payload") or {})
        raw_payload["monitor"] = {
            "evaluated_at": now,
            "next_monitor_after": now,
            "underlying_price": "501.2500",
            "estimated_exit_debit": "0.5000",
            "estimated_pnl": "80.0000",
            "days_to_expiration": 27,
            "exit_reason": "take_profit" if should_close else spread.get("exit_reason"),
            "should_close": should_close,
            "take_profit_debit": "0.6500",
            "stop_loss_debit": "2.6000",
            "distance_to_take_profit_debit": "-0.1500",
            "distance_to_stop_loss_debit": "2.1000",
            "short_strike_distance": "31.2500",
        }
        spread["raw_payload"] = raw_payload
        if should_close:
            self._spread_counter += 1
            spread["status"] = "closed"
            spread["exit_reason"] = "take_profit"
            spread["short_exit_order_id"] = f"mock-spread-short-exit-{self._spread_counter}"
            spread["long_exit_order_id"] = f"mock-spread-long-exit-{self._spread_counter}"
            spread["closed_at"] = now
            self.runtime["daily_realized_pnl"] = "80.0000"
            self.runtime["last_action"] = f"Closed bull put spread for {spread['underlying_symbol']} via take profit."
            self.runtime["last_action_at"] = now
            self.runtime["updated_at"] = now
            self.create_journal(
                {
                    "external_account_id": self.account_id,
                    "symbol": spread["underlying_symbol"],
                    "entry_type": "review",
                    "title": f"Bull put spread closed for {spread['underlying_symbol']}",
                    "notes": "Mock spread monitor closed the spread via take profit.",
                    "tags": ["strategy", "bull-put", "close", "take-profit", "paper"],
                }
            )
        spread["last_synced_at"] = now
        spread["updated_at"] = now
        return {
            "spread": deepcopy(spread),
            "evaluated_at": now,
            "should_close": should_close,
            "exit_reason": spread["exit_reason"],
            "current_underlying_price": "501.2500",
            "estimated_exit_debit": "0.5000",
            "estimated_pnl": "80.0000",
            "days_to_expiration": 27,
        }


def create_app(*, scenario: str = "normal") -> FastAPI:
    state = MockDashboardState(scenario=scenario)
    app = FastAPI(title="Mock Stocks Tool Dashboard", docs_url="/docs", redoc_url=None)
    static_dir = ROOT / "src" / "stocks_tool" / "ui" / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.include_router(ui.router)

    @app.get("/broker-accounts")
    def broker_accounts() -> list[dict[str, Any]]:
        return [deepcopy(state.account)]

    @app.get("/brokers/profiles")
    def broker_profiles() -> list[dict[str, Any]]:
        return [deepcopy(state.broker_profile)]

    @app.get("/brokers/longbridge/profile")
    def longbridge_profile() -> dict[str, Any]:
        return deepcopy(state.broker_profile)

    @app.get("/watchlists")
    def watchlists() -> list[dict[str, Any]]:
        return deepcopy(state.watchlists)

    @app.get("/brokers/longbridge/configuration")
    def longbridge_configuration() -> dict[str, Any]:
        return deepcopy(state.configuration)

    @app.get("/brokers/longbridge/quote")
    def quote(symbol: str = Query(...), mode: str = Query("paper")) -> dict[str, Any]:
        data = deepcopy(state.quote)
        data["symbol"] = symbol.upper()
        data["mode"] = mode
        return data

    @app.get("/ops/unattended-status")
    def unattended_status(
        external_account_id: str = Query(...),
        mode: str = Query(default="paper"),
    ) -> dict[str, Any]:
        if external_account_id != state.account_id or mode != "paper":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mock operator status not found.")
        return state.operator_status_snapshot()

    @app.get("/ops/audit")
    def ops_audit(
        external_account_id: str | None = Query(default=None),
        mode: str | None = Query(default=None),
        source: str | None = Query(default=None),
        strategy: str | None = Query(default=None),
        action: str | None = Query(default=None),
        warning_only: bool = Query(default=False),
        since: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict[str, Any]]:
        _ = since
        if external_account_id is not None and external_account_id != state.account_id:
            return []
        events = state.audit_events()
        if mode is not None:
            events = [event for event in events if event.get("mode") == mode]
        if source is not None:
            events = [event for event in events if event.get("source") == source]
        if strategy is not None:
            events = [event for event in events if event.get("strategy") == strategy]
        if action is not None:
            events = [event for event in events if event.get("action") == action]
        if warning_only:
            events = [event for event in events if event.get("warning_code")]
        return deepcopy(events[:limit])

    @app.get("/ops/audit/summary")
    def ops_audit_summary(
        external_account_id: str | None = Query(default=None),
        mode: str | None = Query(default=None),
        since: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> dict[str, Any]:
        _ = since
        return state.audit_summary(external_account_id=external_account_id, mode=mode, limit=limit)

    @app.get("/strategies/pre-open-risk")
    def pre_open_risk(include_option_overlays: bool = Query(default=False)) -> dict[str, Any]:
        _ = include_option_overlays
        return deepcopy(state.pre_open_assessment)

    @app.get("/strategies/pre-open-runs")
    def pre_open_runs(
        external_account_id: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return state.list_pre_open_runs(external_account_id=external_account_id, limit=limit)

    @app.get("/strategies/experiment")
    def strategy_experiment(
        external_account_id: str | None = Query(default=None),
        strategy_id: str | None = Query(default=None),
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict[str, Any]:
        return state.strategy_experiment_snapshot(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )

    @app.get("/strategies/advisor/run-cards")
    def advisor_run_cards(
        external_account_id: str | None = Query(default=None),
        source: str | None = Query(default="deepseek"),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> list[dict[str, Any]]:
        if external_account_id is not None and external_account_id != state.account_id:
            return []
        rows = [row for row in state.advisor_run_cards if source is None or row.get("source") == source]
        return deepcopy(rows[:limit])

    @app.get("/strategies/advisor/playbooks")
    def advisor_playbooks() -> list[dict[str, Any]]:
        return [
            {
                "id": "bull_put_v1",
                "strategy_id": "paper_bull_put_v1",
                "title": "Bull Put Paper Workbench",
                "summary": "Review paper bull put spread posture and propose local records only.",
                "allowed_outputs": ["proposal", "review"],
                "hard_limits": ["Paper mode only.", "Cannot submit broker orders."],
            },
            {
                "id": "covered_call_v1",
                "strategy_id": "covered_call_v1",
                "title": "Covered Call Paper Workbench",
                "summary": "Review covered call proposal and lifecycle state.",
                "allowed_outputs": ["proposal", "review"],
                "hard_limits": ["Advisor output is advisory only."],
            },
            {
                "id": "zero_dte_lottery_v1",
                "strategy_id": "zero_dte_lottery_v1",
                "title": "Zero-DTE Lottery Guardrail Review",
                "summary": "Assess controls without arming direct execution.",
                "allowed_outputs": ["review"],
                "hard_limits": ["No direct order placement."],
            },
        ]

    @app.get("/strategies/covered-call/activity")
    def covered_call_activity(
        external_account_id: str | None = Query(default=None),
        limit: int = Query(default=12, ge=1, le=100),
    ) -> dict[str, Any]:
        return state.covered_call_activity_snapshot(
            external_account_id=external_account_id,
            limit=limit,
        )

    @app.get("/strategies/zero-dte-lottery/runtime")
    def zero_dte_lottery_runtime(
        external_account_id: str = Query(...),
        mode: str = Query(default="paper"),
    ) -> dict[str, Any]:
        _ = mode
        try:
            return state.get_zero_dte_lottery_runtime(external_account_id)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Zero-DTE lottery runtime for '{external_account_id}' was not found.",
            ) from error

    @app.post("/strategies/zero-dte-lottery/runtime/{external_account_id}")
    def update_zero_dte_lottery_runtime(
        external_account_id: str,
        payload: dict[str, Any],
        mode: str = Query(default="paper"),
    ) -> dict[str, Any]:
        _ = mode
        try:
            return state.update_zero_dte_lottery_runtime(external_account_id, payload)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Zero-DTE lottery runtime for '{external_account_id}' was not found.",
            ) from error

    @app.get("/strategies/zero-dte-lottery/preview")
    def zero_dte_lottery_preview(
        external_account_id: str = Query(...),
        symbol: str = Query(default="QQQ.US"),
        direction: str = Query(default="auto"),
        mode: str = Query(default="paper"),
    ) -> dict[str, Any]:
        _ = mode
        try:
            return state.zero_dte_lottery_preview(
                external_account_id=external_account_id,
                symbol=symbol,
                direction=direction,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Zero-DTE lottery runtime for '{external_account_id}' was not found.",
            ) from error

    @app.post("/strategies/zero-dte-lottery/runtime/{external_account_id}/scan")
    def scan_zero_dte_lottery(
        external_account_id: str,
        symbol: str = Query(default="QQQ.US"),
        direction: str = Query(default="auto"),
        mode: str = Query(default="paper"),
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        _ = mode
        try:
            return state.run_zero_dte_lottery_scan(
                external_account_id=external_account_id,
                symbol=symbol,
                direction=direction,
                force=force,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Zero-DTE lottery runtime for '{external_account_id}' was not found.",
            ) from error

    @app.get("/strategies/proposals")
    def strategy_proposals(
        external_account_id: str | None = Query(default=None),
        strategy_id: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return state.list_strategy_proposals(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )

    @app.get("/strategies/runs")
    def strategy_runs(
        external_account_id: str | None = Query(default=None),
        strategy_id: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return state.list_strategy_runs(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )

    @app.get("/strategies/signals")
    def strategy_signals(
        external_account_id: str | None = Query(default=None),
        strategy_id: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return state.list_strategy_signals(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )

    @app.get("/strategies/reviews")
    def strategy_reviews(
        external_account_id: str | None = Query(default=None),
        strategy_id: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        return state.list_strategy_reviews(
            external_account_id=external_account_id,
            strategy_id=strategy_id,
            limit=limit,
        )

    @app.get("/market-events")
    def market_events(
        symbol: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        return state.list_market_events(symbol=symbol, limit=limit)

    @app.post("/strategies/pre-open-runs/{external_account_id}/capture")
    def capture_pre_open_run(
        external_account_id: str,
        force: bool = Query(default=False),
        include_option_overlays: bool = Query(default=False),
    ) -> dict[str, Any]:
        _ = force, include_option_overlays
        return state.capture_pre_open_run(external_account_id)

    @app.get("/account-snapshots")
    def account_snapshots(external_account_id: str = Query(...)) -> list[dict[str, Any]]:
        if external_account_id != state.account_id:
            return []
        return [deepcopy(state.snapshot)]

    @app.get("/account-snapshots/latest")
    def latest_account_snapshot(external_account_id: str = Query(...)) -> dict[str, Any] | None:
        if external_account_id != state.account_id:
            return None
        return {
            "account_id": state.snapshot["external_account_id"],
            "currency": state.snapshot["currency"],
            "cash_balance": state.snapshot["cash_balance"],
            "net_liquidation": state.snapshot["net_liquidation"],
            "buying_power": state.snapshot["buying_power"],
            "positions": deepcopy(state.snapshot["positions"]),
            "captured_at": state.snapshot["captured_at"],
        }

    @app.get("/orders")
    def orders(external_account_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
        return state.list_orders(external_account_id)

    @app.get("/strategies/bull-put/spreads")
    def spreads(
        external_account_id: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        return state.list_spreads(external_account_id=external_account_id, status=status)

    @app.get("/strategies/bull-put/spreads/{spread_id}/recover-close/eligibility")
    def recover_close_eligibility(
        spread_id: str,
        external_account_id: str | None = Query(default=None),
        mode: str = Query(default="paper"),
    ) -> dict[str, Any]:
        try:
            return state.recover_close_eligibility(
                spread_id,
                external_account_id=external_account_id,
                mode=mode,
            )
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Spread '{spread_id}' was not found.") from error

    @app.get("/strategies/bull-put/runtime")
    def bull_put_runtime(
        external_account_id: str = Query(...),
    ) -> dict[str, Any]:
        try:
            return state.get_runtime_state(external_account_id)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Runtime state for '{external_account_id}' was not found.",
            ) from error

    @app.get("/executions")
    def executions(
        external_account_id: str | None = Query(default=None),
        order_id: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        return state.list_executions(external_account_id=external_account_id, order_id=order_id)

    @app.get("/journals")
    def journals(
        external_account_id: str | None = Query(default=None),
        order_id: str | None = Query(default=None),
        trade_plan_id: str | None = Query(default=None),
        entry_type: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        return state.list_journals(
            external_account_id=external_account_id,
            order_id=order_id,
            trade_plan_id=trade_plan_id,
            entry_type=entry_type,
        )

    @app.get("/orders/{order_id}")
    def get_order(order_id: str) -> dict[str, Any]:
        try:
            return deepcopy(state.get_order(order_id))
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' was not found.") from error

    @app.get("/strategies/bull-put/spreads/{spread_id}")
    def get_spread(spread_id: str) -> dict[str, Any]:
        try:
            return deepcopy(state.get_spread(spread_id))
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Spread '{spread_id}' was not found.") from error

    @app.post("/orders/submit", status_code=status.HTTP_201_CREATED)
    def submit_order(payload: dict[str, Any]) -> dict[str, Any]:
        return state.submit_order(payload)

    @app.post("/orders/{order_id}/refresh")
    def refresh_order(order_id: str) -> dict[str, Any]:
        try:
            return deepcopy(state.get_order(order_id))
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' was not found.") from error

    @app.post("/orders/{order_id}/replace")
    def replace_order(order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return state.replace_order(order_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' was not found.") from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    @app.post("/orders/{order_id}/cancel")
    def cancel_order(order_id: str) -> dict[str, Any]:
        try:
            return state.cancel_order(order_id)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Order '{order_id}' was not found.") from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    @app.post("/strategies/bull-put/spreads/{spread_id}/refresh")
    def refresh_spread(spread_id: str) -> dict[str, Any]:
        try:
            return state.refresh_spread(spread_id)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Spread '{spread_id}' was not found.") from error

    @app.post("/strategies/bull-put/spreads/{spread_id}/recover-close")
    def recover_close(spread_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return state.recover_close(spread_id, payload)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Spread '{spread_id}' was not found.") from error
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    @app.post("/strategies/bull-put/spreads/{spread_id}/monitor")
    def monitor_spread(spread_id: str) -> dict[str, Any]:
        try:
            return state.monitor_spread(spread_id)
        except KeyError as error:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Spread '{spread_id}' was not found.") from error

    @app.post("/strategies/bull-put/runtime/{external_account_id}")
    def update_bull_put_runtime(
        external_account_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return state.update_runtime_state(external_account_id, payload)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Runtime state for '{external_account_id}' was not found.",
            ) from error

    @app.post("/strategies/bull-put/runtime/{external_account_id}/scan")
    def scan_bull_put_runtime(
        external_account_id: str,
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            return state.run_entry_scan(external_account_id, force=force)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Runtime state for '{external_account_id}' was not found.",
            ) from error

    @app.post("/strategies/bull-put/runtime/{external_account_id}/review")
    def review_bull_put_runtime(
        external_account_id: str,
        force: bool = Query(default=False),
    ) -> dict[str, Any]:
        try:
            return state.run_review(external_account_id, force=force)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Runtime state for '{external_account_id}' was not found.",
            ) from error

    @app.post("/journals", status_code=status.HTTP_201_CREATED)
    def create_journal(payload: dict[str, Any]) -> dict[str, Any]:
        return state.create_journal(payload)

    @app.post("/brokers/longbridge/account-sync/{external_account_id}")
    def sync_account(external_account_id: str, mode: str = Query("paper")) -> dict[str, Any]:
        return {
            "external_account_id": external_account_id,
            "mode": mode,
            "snapshot_id": state.snapshot["id"],
            "positions_synced": len(state.snapshot["positions"]),
            "captured_at": state.snapshot["captured_at"],
        }

    @app.post("/orders/sync/longbridge/{external_account_id}")
    def sync_orders(external_account_id: str, mode: str = Query("paper")) -> dict[str, Any]:
        return {
            "external_account_id": external_account_id,
            "mode": mode,
            "orders_synced": len(state.orders),
        }

    return app


app = create_app()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve a mock Stocks Tool dashboard backend for UI regression.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument("--scenario", choices=sorted(MOCK_SCENARIOS), default="normal", help="Mock posture scenario.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(create_app(scenario=args.scenario), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

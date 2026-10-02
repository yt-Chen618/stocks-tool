"""Deterministic browser-module contract tests for bounded activity reads."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(source: str) -> dict:
    completed = subprocess.run(
        ["node", "--input-type=commonjs", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_cursor_page_decoder_rejects_unbounded_or_stalled_pages() -> None:
    result = run_node(
        r'''
        const fs = require("fs");
        const vm = require("vm");
        global.window = {};
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/api-client.js", "utf8"));
        const decode = window.StocksToolApiClient.decodeCursorPage;
        const valid = decode({items: [{id: "1"}], next_cursor: "2", has_more: true, limit: 2});
        const errors = [];
        for (const payload of [
          {items: [], next_cursor: null, has_more: true, limit: 2},
          {items: [{id: "1"}, {id: "2"}, {id: "3"}], next_cursor: null, has_more: false, limit: 2},
          {items: [], next_cursor: null, has_more: false, limit: 101},
        ]) {
          try { decode(payload); } catch (error) { errors.push(error.message); }
        }
        process.stdout.write(JSON.stringify({valid, error_count: errors.length}));
        ''',
    )
    assert result["valid"] == {"items": [{"id": "1"}], "cursor": "2", "hasMore": True, "limit": 2}
    assert result["error_count"] == 3


def test_account_loader_discards_stale_detail_and_page_success_or_error() -> None:
    result = run_node(
        r'''
        (async () => {
        const fs = require("fs");
        const vm = require("vm");
        global.window = {};
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/api-client.js", "utf8"));
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/account-loader.js", "utf8"));
        const decoder = window.StocksToolApiClient.decodeCursorPage;
        const state = {
          selectedAccountId: "A",
          accountLoadGeneration: 1,
          selectedOrderId: "old-order",
          orders: [],
          activityPages: {orders: {cursor: null, hasMore: false, loading: false, error: null}, executions: {}, journals: {}},
        };
        const pending = [];
        const fetchJson = (url) => new Promise((resolve, reject) => pending.push({url, resolve, reject}));
        const loader = window.StocksToolAccountLoader.createAccountLoader({
          state,
          fetchJson,
          decodeCursorPage: decoder,
          createOverlayStatus: (kind, detail, reason) => ({kind, detail, reason}),
          formatPanelLoadLabel: (key) => key,
          renderAccountOptions() {}, renderEmptyState() {}, renderAccountState() {},
          applyTradingSafetyState() {}, updateSyncButtons() {}, updateOrderTicketAvailability() {}, updatePreOpenButtons() {},
        });

        const detailRace = loader.ensureSelectedOrderDetail(null);
        state.selectedAccountId = "B";
        state.accountLoadGeneration = 2;
        pending.shift().resolve({id: "old-order", external_account_id: "A"});
        await detailRace;
        const detailDiscarded = state.selectedOrderDetail === undefined || state.selectedOrderDetail === null;

        state.selectedAccountId = "A";
        state.accountLoadGeneration = 3;
        state.selectedOrderId = "old-order";
        const pageSuccessRace = loader.loadActivityPage("orders");
        state.selectedAccountId = "B";
        state.accountLoadGeneration = 4;
        pending.shift().resolve({items: [{id: "old-order"}], next_cursor: null, has_more: false, limit: 25});
        const pageSuccess = await pageSuccessRace;
        const successDiscarded = pageSuccess.discarded === true && state.orders.length === 0;

        state.activityPages = {orders: {cursor: null, hasMore: false, loading: false, error: null}, executions: {}, journals: {}};
        state.selectedAccountId = "A";
        state.accountLoadGeneration = 5;
        const pageErrorRace = loader.loadActivityPage("orders");
        state.selectedAccountId = "B";
        state.accountLoadGeneration = 6;
        pending.shift().reject(new Error("stale request failed"));
        const pageError = await pageErrorRace;
        const errorDiscarded = pageError.discarded === true && state.activityPages.orders.error === null;
        process.stdout.write(JSON.stringify({detailDiscarded, successDiscarded, errorDiscarded}));
        })().catch((error) => { console.error(error); process.exit(1); });
        ''',
    )
    assert result == {"detailDiscarded": True, "successDiscarded": True, "errorDiscarded": True}

"""Deterministic browser-module contract tests for bounded activity reads."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


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
        pending.shift().resolve({items: [], next_cursor: null, has_more: false, limit: 25});
        pending.shift().resolve({items: [], next_cursor: null, has_more: false, limit: 25});
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


def test_account_loader_deduplicates_selected_order_request_set() -> None:
    result = run_node(
        r'''
        (async () => {
        const fs = require("fs");
        const vm = require("vm");
        global.window = {};
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/api-client.js", "utf8"));
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/account-loader.js", "utf8"));
        const state = {
          selectedAccountId: "A", accountLoadGeneration: 1, selectedOrderId: "order-1", orders: [],
          activityPages: {orders: {}, executions: {}, journals: {}},
          selectedOrderExecutions: [], selectedOrderJournals: [],
          selectedOrderExecutionPage: {}, selectedOrderJournalPage: {},
        };
        const pending = [];
        let calls = 0;
        const fetchJson = (url) => new Promise((resolve, reject) => {
          calls += 1;
          pending.push({url, resolve, reject});
        });
        const loader = window.StocksToolAccountLoader.createAccountLoader({
          state, fetchJson, decodeCursorPage: window.StocksToolApiClient.decodeCursorPage,
          createOverlayStatus: () => ({}), formatPanelLoadLabel: (key) => key,
          renderAccountOptions() {}, renderEmptyState() {}, renderAccountState() {},
          applyTradingSafetyState() {}, updateSyncButtons() {}, updateOrderTicketAvailability() {}, updatePreOpenButtons() {},
        });
        const first = loader.loadSelectedOrderDetails("order-1");
        const second = loader.loadSelectedOrderDetails("order-1");
        pending.shift().resolve({id: "order-1", external_account_id: "A"});
        pending.shift().resolve({items: [{id: "fill-1", order_id: "order-1"}], next_cursor: null, has_more: false, limit: 25});
        pending.shift().resolve({items: [{id: "journal-1", order_id: "order-1"}], next_cursor: null, has_more: false, limit: 25});
        const [firstResult, secondResult] = await Promise.all([first, second]);
        process.stdout.write(JSON.stringify({calls, first: firstResult.order?.id, second: secondResult.order?.id}));
        })().catch((error) => { console.error(error); process.exit(1); });
        ''',
    )
    assert result == {"calls": 3, "first": "order-1", "second": "order-1"}


def test_account_loader_renders_required_core_before_slow_auxiliary_panels() -> None:
    result = run_node(
        r'''
        (async () => {
        const fs = require("fs");
        const vm = require("vm");
        global.window = {};
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/api-client.js", "utf8"));
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/account-loader.js", "utf8"));
        const state = {
          selectedAccountId: "A", accountLoadGeneration: 0, accountContextId: "",
          accountListHealthy: true, selectedOrderId: "", orders: [], spreads: [], bullPutHistory: [],
          bullPutHistoryPage: {cursor: null, hasMore: false, loading: false, error: null},
          bullPutHistoryDetails: {}, bullPutHistoryDetailLoading: {}, bullPutHistoryDetailErrors: {},
          recoverCloseEligibility: {}, unknownMutationLocks: {}, unresolvedTradingIntents: [],
          activityPages: {orders: {}, executions: {}, journals: {}},
          selectedOrderExecutions: [], selectedOrderJournals: [], selectedOrderExecutionPage: {}, selectedOrderJournalPage: {},
        };
        const slow = [];
        let renders = 0;
        const fetchJson = (url) => {
          if (url.includes("zero-dte") || url.includes("run-cards") || url.includes("market-events") || url.includes("executions/paged") || url.includes("journals/paged") || url.includes("pre-open-runs")) {
            return new Promise((resolve, reject) => slow.push({url, resolve, reject}));
          }
          if (url.includes("account-snapshots/latest")) return Promise.resolve({captured_at: "now", positions: []});
          if (url.includes("orders/paged")) return Promise.resolve({items: [], next_cursor: null, has_more: false, limit: 25});
          if (url.includes("working-spreads")) return Promise.resolve([]);
          if (url.includes("bull-put/runtime")) return Promise.resolve({});
          if (url.includes("unattended-status")) return Promise.resolve({});
          if (url.includes("recovery-status")) return Promise.resolve({external_account_id: "A", mode: "paper", recovery_blocked: false, status: "clear"});
          if (url.includes("trading-intents") || url.includes("trade-actions")) return Promise.resolve([]);
          if (url.includes("strategies/experiment")) return Promise.resolve({proposals: [], runs: [], signals: [], reviews: []});
          if (url.includes("covered-call/activity")) return Promise.resolve({summary: {}, proposals: [], runs: [], signals: [], reviews: []});
          throw new Error(`Unexpected URL ${url}`);
        };
        const loader = window.StocksToolAccountLoader.createAccountLoader({
          state, fetchJson, decodeCursorPage: window.StocksToolApiClient.decodeCursorPage,
          createOverlayStatus: () => ({}), formatPanelLoadLabel: (key) => key,
          renderAccountOptions() {}, renderEmptyState() {}, renderAccountState() { renders += 1; },
          renderRecoveryLoading() {}, renderRecoveryStatus() {}, renderRecoveryError() {},
          applyTradingSafetyState() {}, updateSyncButtons() {}, updateOrderTicketAvailability() {}, updatePreOpenButtons() {},
        });
        const load = loader.loadAccountData();
        while (renders === 0) await new Promise((resolve) => setImmediate(resolve));
        const progressive = {renders, coreHealthy: state.coreDataHealthy, recovery: state.recoveryStatusState, slowRequests: slow.length};
        for (const pending of slow) {
          if (pending.url.includes("executions/paged") || pending.url.includes("journals/paged")) pending.resolve({items: [], next_cursor: null, has_more: false, limit: 25});
          else if (pending.url.includes("run-cards")) pending.resolve([]);
          else if (pending.url.includes("market-events")) pending.resolve([]);
          else if (pending.url.includes("pre-open-runs")) pending.resolve([]);
          else pending.resolve({});
        }
        await load;
        process.stdout.write(JSON.stringify({...progressive, finalRenders: renders}));
        })().catch((error) => { console.error(error); process.exit(1); });
        ''',
    )
    assert result["coreHealthy"] is True
    assert result["recovery"] == "ready"
    assert result["slowRequests"] >= 5
    assert result["renders"] == 1
    assert result["finalRenders"] >= 2


@pytest.mark.parametrize("terminal_state", ["persisted", "rejected", "resolved_no_order"])
def test_unknown_lock_cleanup_requires_exact_terminal_detail(terminal_state: str) -> None:
    result = run_node(
        r'''
        (async () => {
        const fs = require("fs");
        const vm = require("vm");
        const storage = new Map([["stocks-tool-idempotency:A:order-submit", "persisted"]]);
        global.window = {sessionStorage: {removeItem: (key) => storage.delete(key)}};
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/api-client.js", "utf8"));
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/account-loader.js", "utf8"));
        const state = {
          selectedAccountId: "A", accountLoadGeneration: 1,
          unknownMutationLocks: {A: [
            {id: "intent-a", external_account_id: "A", mode: "paper", action_key: "order-submit"},
            {id: "intent-b", external_account_id: "A", mode: "paper"},
          ]},
          terminalUnknownMutationIds: {},
        };
        const fetchJson = async (url) => {
          if (url.endsWith("/intent-a")) return {id: "intent-a", external_account_id: "A", mode: "paper", state: BACKEND_TERMINAL_STATE};
          if (url.endsWith("/intent-b")) return {id: "unrelated", external_account_id: "A", mode: "paper", state: "rejected"};
          throw Object.assign(new Error("not found"), {status: 404});
        };
        const loader = window.StocksToolAccountLoader.createAccountLoader({
          state, fetchJson, decodeCursorPage: window.StocksToolApiClient.decodeCursorPage,
          createOverlayStatus: () => ({}), formatPanelLoadLabel: (key) => key,
          renderAccountOptions() {}, renderEmptyState() {}, renderAccountState() {},
          applyTradingSafetyState() {}, updateSyncButtons() {}, updateOrderTicketAvailability() {}, updatePreOpenButtons() {},
        });
        const result = await loader.reconcileUnknownMutationLocks("A", 1);
        process.stdout.write(JSON.stringify({result, remaining: state.unknownMutationLocks.A, terminal: state.terminalUnknownMutationIds.A, keys: Array.from(storage.keys())}));
        })().catch((error) => { console.error(error); process.exit(1); });
        '''.replace("BACKEND_TERMINAL_STATE", json.dumps(terminal_state)),
    )
    assert result["result"]["cleared"] == ["intent-a"]
    assert [lock["id"] for lock in result["remaining"]] == ["intent-b"]
    assert result["terminal"] == ["intent-a"]
    assert result["keys"] == []


def test_unknown_intent_id_survives_reload_and_terminal_detail_clears_key() -> None:
    result = run_node(
        r'''
        (async () => {
        const fs = require("fs");
        const vm = require("vm");
        const storage = new Map([
          ["stocks-tool-idempotency:A:order-submit", JSON.stringify({key: "ui:order-submit:old", requestSignature: "A-request", accountId: "A", mode: "paper", actionKey: "order-submit", intentId: "intent-a"})],
          ["stocks-tool-idempotency:A:order-replay", JSON.stringify({key: "ui:order-replay:old", requestSignature: "A-replay", accountId: "A", mode: "paper", actionKey: "order-replay"})],
          ["stocks-tool-idempotency:B:order-submit", JSON.stringify({key: "ui:order-submit:foreign", requestSignature: "B-request", accountId: "B", mode: "paper", actionKey: "order-submit", intentId: "intent-b"})],
        ]);
        global.window = {sessionStorage: {
          length: 0,
          key: (index) => Array.from(storage.keys())[index] || null,
          getItem: (key) => storage.get(key) || null,
          setItem: (key, value) => { storage.set(key, value); },
          removeItem: (key) => storage.delete(key),
        }};
        Object.defineProperty(window.sessionStorage, "length", {get: () => storage.size});
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/api-client.js", "utf8"));
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/account-loader.js", "utf8"));
        const state = {selectedAccountId: "A", accountLoadGeneration: 1, accounts: [{external_account_id: "A"}, {external_account_id: "B"}], unknownMutationLocks: {}, terminalUnknownMutationIds: {}};
        const fetchJson = async (url) => {
          if (url.endsWith("/intent-a")) return {id: "intent-a", external_account_id: "A", mode: "paper", state: "resolved_no_order"};
          throw Object.assign(new Error("not found"), {status: 404});
        };
        const loader = window.StocksToolAccountLoader.createAccountLoader({
          state, fetchJson, decodeCursorPage: window.StocksToolApiClient.decodeCursorPage,
          createOverlayStatus: () => ({}), formatPanelLoadLabel: (key) => key,
          renderAccountOptions() {}, renderEmptyState() {}, renderAccountState() {},
          applyTradingSafetyState() {}, updateSyncButtons() {}, updateOrderTicketAvailability() {}, updatePreOpenButtons() {},
        });
        const rehydrated = loader.rehydrateUnknownMutationLocks("A");
        const cleanup = await loader.reconcileUnknownMutationLocks("A", 1);
        process.stdout.write(JSON.stringify({rehydrated: rehydrated.map((lock) => lock.id), cleared: cleanup.cleared, remaining: state.unknownMutationLocks.A || [], keys: Array.from(storage.keys())}));
        })().catch((error) => { console.error(error); process.exit(1); });
        ''',
    )
    assert result["rehydrated"] == ["intent-a"]
    assert result["cleared"] == ["intent-a"]
    assert result["remaining"] == []
    assert result["keys"] == ["stocks-tool-idempotency:A:order-replay", "stocks-tool-idempotency:B:order-submit"]


def test_live_pending_key_without_intent_id_does_not_create_stranded_lock() -> None:
    result = run_node(
        r'''
        const fs = require("fs");
        const vm = require("vm");
        const storage = new Map([["stocks-tool-idempotency:A:order-submit", JSON.stringify({key: "ui:order-submit:live", requestSignature: "A-request", accountId: "A", mode: "paper", actionKey: "order-submit"})]]);
        global.window = {sessionStorage: {
          key: (index) => Array.from(storage.keys())[index] || null,
          getItem: (key) => storage.get(key) || null,
          setItem: (key, value) => storage.set(key, value),
          removeItem: (key) => storage.delete(key),
        }};
        Object.defineProperty(window.sessionStorage, "length", {get: () => storage.size});
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/api-client.js", "utf8"));
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/account-loader.js", "utf8"));
        const state = {selectedAccountId: "A", accountLoadGeneration: 1, accounts: [{external_account_id: "A"}], unknownMutationLocks: {}, terminalUnknownMutationIds: {}};
        const loader = window.StocksToolAccountLoader.createAccountLoader({
          state, fetchJson: async () => { throw Object.assign(new Error("not found"), {status: 404}); },
          decodeCursorPage: window.StocksToolApiClient.decodeCursorPage,
          createOverlayStatus: () => ({}), formatPanelLoadLabel: (key) => key,
          renderAccountOptions() {}, renderEmptyState() {}, renderAccountState() {},
          applyTradingSafetyState() {}, updateSyncButtons() {}, updateOrderTicketAvailability() {}, updatePreOpenButtons() {},
        });
        const before = loader.rehydrateUnknownMutationLocks("A");
        storage.delete("stocks-tool-idempotency:A:order-submit");
        const after = loader.rehydrateUnknownMutationLocks("A");
        process.stdout.write(JSON.stringify({before, after, locks: state.unknownMutationLocks.A || []}));
        ''',
    )
    assert result == {"before": [], "after": [], "locks": []}

"""Pure M1 trading guard contract tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_node(source: str) -> dict:
    result = subprocess.run(
        ["node", "--input-type=commonjs", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_trading_guard_is_pure_account_mode_recovery_and_pending_gate() -> None:
    result = run_node(
        r'''
        const fs = require("fs");
        const vm = require("vm");
        global.window = {};
        vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/trading-safety.js", "utf8"));
        const evaluate = window.StocksToolTradingSafety.evaluateTradingSafety;
        const base = {
          accountId: "A",
          selectedAccountId: "A",
          mode: "paper",
          accountLoadGeneration: 4,
          coreDataHealthy: true,
          recoveryStatusState: "ready",
          recoveryStatus: {external_account_id: "A", mode: "paper", recovery_blocked: false},
          unresolvedTradingIntents: [],
          mobileBlocked: false,
          pendingActionKeys: new Set(),
          actionKey: "order-submit",
          businessDisabled: false,
        };
        const allowed = evaluate(base);
        const loading = evaluate({...base, recoveryStatusState: "loading"});
        const blocked = evaluate({...base, recoveryStatus: {...base.recoveryStatus, recovery_blocked: true}});
        const ownPending = evaluate({...base, pendingActionKeys: new Set(["order-submit"]), ignorePendingAction: true});
        const otherPending = evaluate({...base, pendingActionKeys: new Set(["other-action"]), actionKey: "other-action"});
        const changed = evaluate({...base, selectedAccountId: "B", expectedContext: {accountId: "A", mode: "paper", requestSignature: "old"}, requestSignature: "new"});
        const generationChanged = evaluate({...base, expectedContext: {accountId: "A", mode: "paper", requestSignature: "same", accountLoadGeneration: 4}, requestSignature: "same", accountLoadGeneration: 5});
        const businessDisabled = evaluate({...base, businessDisabled: true});
        process.stdout.write(JSON.stringify({
          allowed: !allowed.blocked,
          loading: loading.reasons,
          recoveryBlocked: blocked.reasons,
          ownPending: !ownPending.blocked,
          otherPending: otherPending.reasons,
          changed: changed.reasons,
          generationChanged: generationChanged.reasons,
          businessDisabled: businessDisabled.reasons,
        }));
        ''',
    )
    assert result["allowed"] is True
    assert "recovery_status_unavailable" in result["loading"]
    assert "recovery_blocked" in result["recoveryBlocked"]
    assert result["ownPending"] is True
    assert "pending_action" in result["otherPending"]
    assert "account_context_changed" in result["changed"]
    assert "request_signature_changed" in result["changed"]
    assert "account_context_changed" in result["generationChanged"]
    assert "business_disabled" in result["businessDisabled"]


def test_late_unknown_mutation_keeps_account_scoped_lock_and_idempotency_key() -> None:
    result = run_node(
        r'''
        (async () => {
          const fs = require("fs");
          const vm = require("vm");
          const listeners = [];
          const storage = new Map();
          global.window = {
            crypto: {randomUUID: () => "uuid-a"},
            innerWidth: 1440,
            matchMedia: () => ({matches: false, addEventListener() {}}),
            sessionStorage: {
              getItem: (key) => storage.get(key) || null,
              setItem: (key, value) => storage.set(key, value),
              removeItem: (key) => storage.delete(key),
            },
            StocksToolExecution: {setMobileReadonly() {}},
            StocksToolI18n: {TRANSLATIONS: {}},
            StocksToolFormatters: {},
          };
          global.document = {
            addEventListener: () => {},
            querySelectorAll: () => [],
            body: {},
          };
          vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/state.js", "utf8"));
          vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/trading-safety.js", "utf8"));
          vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/app.js", "utf8"));
          state.selectedAccountId = "A";
          state.accountLoadGeneration = 1;
          state.coreDataHealthy = true;
          state.recoveryStatusState = "ready";
          state.recoveryStatus = {external_account_id: "A", mode: "paper", recovery_blocked: false};
          const dialog = {
            returnValue: "confirm",
            addEventListener: (_name, callback) => listeners.push(callback),
            showModal: () => queueMicrotask(() => { dialog.returnValue = "confirm"; listeners.splice(0).forEach((callback) => callback()); }),
          };
          els.tradeConfirmDialog = dialog;
          els.tradeConfirmTitle = {textContent: ""};
          els.tradeConfirmSummary = {textContent: ""};
          els.tradeConfirmDetails = {innerHTML: ""};
          els.statusBanner = {textContent: "", className: "", classList: {remove() {}, add() {}}};
          let rejectOperation;
          let operationStarted = false;
          const mutation = runConfirmedBrokerMutation({
            actionKey: "order-submit",
            requestSignature: "A-request",
            confirmation: {title: "test", summary: "test", details: {}},
            statusElement: null,
          }, async () => {
            operationStarted = true;
            return new Promise((_resolve, reject) => { rejectOperation = reject; });
          });
          while (!operationStarted) await new Promise((resolve) => setImmediate(resolve));
          state.selectedAccountId = "B";
          state.accountLoadGeneration = 2;
          rejectOperation({code: "order_outcome_unknown", intentId: "unknown-a"});
          const outcome = await mutation;
          process.stdout.write(JSON.stringify({
            discarded: outcome.discarded === true,
            currentAccount: state.selectedAccountId,
            currentUnresolved: state.unresolvedTradingIntents,
            oldLocks: state.unknownMutationLocks?.A || [],
            pending: Array.from(state.pendingActionKeys),
            idempotencyKeys: Array.from(storage.keys()),
          }));
        })().catch((error) => { console.error(error); process.exit(1); });
        ''',
    )
    assert result["discarded"] is True
    assert result["currentAccount"] == "B"
    assert result["currentUnresolved"] == []
    assert result["oldLocks"][0]["id"] == "unknown-a"
    assert result["pending"] == []
    assert any(key.startswith("stocks-tool-idempotency:A:order-submit") for key in result["idempotencyKeys"])


def test_late_terminal_mutation_clears_original_scope_key() -> None:
    result = run_node(
        r'''
        (async () => {
          const fs = require("fs");
          const vm = require("vm");
          const listeners = [];
          const storage = new Map();
          global.window = {
            crypto: {randomUUID: () => "uuid-a"}, innerWidth: 1440,
            matchMedia: () => ({matches: false, addEventListener() {}}),
            sessionStorage: {getItem: (key) => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key)},
            StocksToolExecution: {setMobileReadonly() {}}, StocksToolI18n: {TRANSLATIONS: {}}, StocksToolFormatters: {},
          };
          global.document = {addEventListener: () => {}, querySelectorAll: () => [], body: {}};
          vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/state.js", "utf8"));
          vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/trading-safety.js", "utf8"));
          vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/app.js", "utf8"));
          state.selectedAccountId = "A"; state.accountLoadGeneration = 1; state.coreDataHealthy = true;
          state.recoveryStatusState = "ready"; state.recoveryStatus = {external_account_id: "A", mode: "paper", recovery_blocked: false};
          const dialog = {returnValue: "confirm", addEventListener: (_name, callback) => listeners.push(callback), showModal: () => queueMicrotask(() => { dialog.returnValue = "confirm"; listeners.splice(0).forEach((callback) => callback()); })};
          els.tradeConfirmDialog = dialog; els.tradeConfirmTitle = {textContent: ""}; els.tradeConfirmSummary = {textContent: ""}; els.tradeConfirmDetails = {innerHTML: ""};
          els.statusBanner = {textContent: "", className: "", classList: {remove() {}, add() {}}};
          let rejectOperation; let started = false;
          const mutation = runConfirmedBrokerMutation({actionKey: "order-submit", requestSignature: "A-request", confirmation: {title: "test", summary: "test", details: {}}, statusElement: null}, async () => {
            started = true;
            return new Promise((_resolve, reject) => { rejectOperation = reject; });
          });
          while (!started) await new Promise((resolve) => setImmediate(resolve));
          state.selectedAccountId = "B"; state.accountLoadGeneration = 2;
          rejectOperation({status: 409, message: "terminal"});
          const outcome = await mutation;
          process.stdout.write(JSON.stringify({discarded: outcome.discarded === true, keys: Array.from(storage.keys())}));
        })().catch((error) => { console.error(error); process.exit(1); });
        ''',
    )
    assert result["discarded"] is True
    assert result["keys"] == []

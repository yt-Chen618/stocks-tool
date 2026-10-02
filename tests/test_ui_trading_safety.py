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

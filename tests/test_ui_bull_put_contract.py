"""Native Bull Put view/account-loader contracts without a browser server."""

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


def test_bull_put_reads_are_scoped_paged_and_race_safe() -> None:
    result = run_node(
        r'''
        (async () => {
          const fs = require("fs");
          const vm = require("vm");
          global.window = {};
          vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/api-client.js", "utf8"));
          vm.runInThisContext(fs.readFileSync("src/stocks_tool/ui/static/account-loader.js", "utf8"));
          const state = {
            selectedAccountId: "A",
            accountLoadGeneration: 1,
            orders: [],
            spreads: [],
            bullPutHistory: [],
            bullPutHistoryPage: {cursor: null, hasMore: false, loading: false, error: null},
            bullPutHistoryDetails: {},
            bullPutHistoryDetailLoading: {},
            bullPutHistoryDetailErrors: {},
            recoverCloseEligibility: {},
            activityPages: {orders: {}, executions: {}, journals: {}},
          };
          const spread = (id, status = "open", account = "A") => ({id, external_account_id: account, mode: "paper", status, underlying_symbol: "QQQ.US"});
          const requests = [];
          const fetchJson = async (url) => {
            requests.push(url);
            if (url.includes("working-spreads")) return [spread("working-1")];
            if (url.includes("spreads/paged") && !url.includes("cursor=25")) return {items: [spread("closed-1", "closed")], next_cursor: "25", has_more: true, limit: 25};
            if (url.includes("spreads/paged") && url.includes("cursor=25")) return {items: [spread("closed-2", "closed")], next_cursor: null, has_more: false, limit: 25};
            if (url.includes("/spreads/closed-1?")) return spread("closed-1", "closed");
            if (url.includes("eligibility")) return {spread_id: "working-1", eligible: true, reasons: [], external_account_id: "A", mode: "paper"};
            throw new Error(`Unexpected URL ${url}`);
          };
          const loader = window.StocksToolAccountLoader.createAccountLoader({
            state, fetchJson, decodeCursorPage: window.StocksToolApiClient.decodeCursorPage,
            createOverlayStatus: () => ({}), formatPanelLoadLabel: (key) => key,
            renderAccountOptions() {}, renderEmptyState() {}, renderAccountState() {},
            applyTradingSafetyState() {}, updateSyncButtons() {}, updateOrderTicketAvailability() {}, updatePreOpenButtons() {},
          });
          await loader.loadWorkingSpreads();
          await loader.loadBullPutHistoryPage();
          await loader.loadBullPutHistoryPage({append: true});
          const detail = await loader.loadSpreadDetail("closed-1");
          const eligibility = await loader.loadSpreadEligibility("working-1");
          const pending = [];
          const deferredLoader = window.StocksToolAccountLoader.createAccountLoader({
            state, fetchJson: (url) => new Promise((resolve, reject) => pending.push({url, resolve, reject})),
            decodeCursorPage: window.StocksToolApiClient.decodeCursorPage,
            createOverlayStatus: () => ({}), formatPanelLoadLabel: (key) => key,
            renderAccountOptions() {}, renderEmptyState() {}, renderAccountState() {},
            applyTradingSafetyState() {}, updateSyncButtons() {}, updateOrderTicketAvailability() {}, updatePreOpenButtons() {},
          });
          state.selectedAccountId = "A";
          state.accountLoadGeneration = 7;
          state.recoverCloseEligibility = {};
          const race = deferredLoader.loadSpreadEligibility("working-1");
          state.selectedAccountId = "B";
          state.accountLoadGeneration = 8;
          pending.shift().resolve({spread_id: "working-1", eligible: true, reasons: [], external_account_id: "A", mode: "paper"});
          const raceResult = await race;
          process.stdout.write(JSON.stringify({
            working: state.spreads.map((item) => item.id),
            history: state.bullPutHistory.map((item) => item.id),
            detail: detail.detail?.id,
            eligibility: eligibility.eligibility?.spread_id,
            raceDiscarded: raceResult.discarded === true,
            oldEligibilityNotInstalled: state.recoverCloseEligibility["working-1"] === undefined,
            workingUrl: requests.find((url) => url.includes("working-spreads")),
            historyUrl: requests.find((url) => url.includes("spreads/paged")),
          }));
        })().catch((error) => { console.error(error); process.exit(1); });
        ''',
    )
    assert result["working"] == ["working-1"]
    assert result["history"] == ["closed-1", "closed-2"]
    assert result["detail"] == "closed-1"
    assert result["eligibility"] == "working-1"
    assert result["raceDiscarded"] is True
    assert result["oldEligibilityNotInstalled"] is True
    assert "working-spreads?external_account_id=A&mode=paper" in result["workingUrl"]
    assert "spreads/paged?external_account_id=A&mode=paper&limit=25" in result["historyUrl"]

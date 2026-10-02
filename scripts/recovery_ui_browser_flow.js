const path = require("node:path");
const {
  expectText,
  launchBrowserPage,
  resolveBrowserExecutable,
  sleep,
  waitFor,
  waitResponsiveSettled,
} = require("./browser_test_helpers");
const { runFrontendStateBrowserChecks } = require("./frontend_state_browser_checks");

const PRIMARY_ACCOUNT = "LBPT10087357";
const ALT_ACCOUNT = "LBPT10087357-ALT";

function recoveryIntentFixture(id, overrides = {}) {
  return {
    id,
    trade_action_intent_id: "recovery-parent-composite",
    external_account_id: PRIMARY_ACCOUNT,
    mode: "paper",
    operation: "submit",
    action: "bull_put_entry",
    strategy_id: "paper_bull_put_v1",
    entity_id: "recovery-spread-1",
    leg: "long_entry",
    state: "unknown",
    external_order_id: null,
    target_order_id: null,
    parent_action: "bull_put_execute",
    parent_state: "unknown",
    created_at: "2026-10-02T09:30:00Z",
    updated_at: "2026-10-02T09:31:00Z",
    reconciliation_attempts: 1,
    first_reconciled_at: "2026-10-02T09:30:10Z",
    last_reconciled_at: "2026-10-02T09:30:20Z",
    coverage_start_at: "2026-10-02T09:30:15Z",
    coverage_end_at: "2026-10-02T09:30:20Z",
    coverage_covers_intent: false,
    checks_satisfied: false,
    check_span_seconds: 10,
    reason_code: "reconciliation_coverage_incomplete",
    reason_detail: "Canonical detail retained for API evidence.",
    next_action: "Canonical next action retained for API evidence.",
    ...overrides,
  };
}

function richRecoveryFixture() {
  return {
    generated_at: "2026-10-02T09:32:00Z",
    external_account_id: PRIMARY_ACCOUNT,
    mode: "paper",
    status: "blocked",
    recovery_blocked: true,
    unresolved_count: 12,
    displayed_unresolved_count: 4,
    unknown_count: 5,
    displayed_unknown_count: 4,
    unresolved_parent_count: 1,
    displayed_parent_count: 1,
    unknown_parent_count: 1,
    displayed_unknown_parent_count: 1,
    truncated: true,
    primary_blocker: "reconciliation_coverage_incomplete",
    next_action: "Canonical next action retained for API evidence.",
    parents: [
      {
        id: "recovery-parent-composite",
        external_account_id: PRIMARY_ACCOUNT,
        mode: "paper",
        action: "bull_put_execute",
        strategy_id: "paper_bull_put_v1",
        entity_id: "recovery-spread-1",
        state: "unknown",
        child_count: 4,
        unresolved_child_count: 4,
        evidence_ready_child_count: 0,
        children_truncated: true,
        reason_code: "parent_action_persisted",
        next_action: "Canonical parent guidance.",
      },
    ],
    intents: [
      recoveryIntentFixture("recovery-child-coverage", {
        reason_code: "reconciliation_coverage_incomplete",
        coverage_covers_intent: false,
      }),
      recoveryIntentFixture("recovery-child-checks", {
        reason_code: "reconciliation_checks_pending",
        reconciliation_attempts: 2,
        coverage_covers_intent: true,
        check_span_seconds: 40,
      }),
      recoveryIntentFixture("recovery-child-span", {
        reason_code: "reconciliation_wait_window",
        reconciliation_attempts: 3,
        coverage_covers_intent: true,
        check_span_seconds: 45,
      }),
      recoveryIntentFixture("recovery-child-known-order", {
        reason_code: "external_order_id_present",
        external_order_id: "mock-external-order-known",
        reconciliation_attempts: 3,
        coverage_covers_intent: true,
        check_span_seconds: 61,
      }),
    ],
    sdk_quarantine: {
      available: true,
      pending_count: 1,
      oldest_started_at: "2026-10-02T09:31:18Z",
      oldest_duration_seconds: 42,
      next_action: "Canonical SDK quarantine guidance.",
    },
  };
}

function parentOnlyRecoveryFixture() {
  const fixture = clearRecoveryFixture(PRIMARY_ACCOUNT);
  fixture.status = "blocked";
  fixture.recovery_blocked = true;
  fixture.unresolved_parent_count = 1;
  fixture.displayed_parent_count = 1;
  fixture.unknown_parent_count = 1;
  fixture.displayed_unknown_parent_count = 1;
  fixture.primary_blocker = "order_outcome_unknown";
  fixture.next_action = "Canonical parent-only guidance.";
  fixture.parents = [
    {
      id: "recovery-parent-only-unknown",
      external_account_id: PRIMARY_ACCOUNT,
      mode: "paper",
      action: "order_submit",
      strategy_id: "paper_bull_put_v1",
      entity_id: "recovery-parent-only",
      state: "unknown",
      child_count: 0,
      unresolved_child_count: 0,
      evidence_ready_child_count: 0,
      children_truncated: false,
      reason_code: "order_outcome_unknown",
      next_action: "Canonical parent-only guidance.",
    },
  ];
  return fixture;
}

function sdkBlockedRecoveryFixture() {
  const fixture = clearRecoveryFixture();
  fixture.external_account_id = PRIMARY_ACCOUNT;
  fixture.status = "blocked";
  fixture.recovery_blocked = true;
  fixture.primary_blocker = "sdk_timeout_quarantine";
  fixture.next_action = "Canonical SDK quarantine guidance.";
  fixture.sdk_quarantine = {
    available: true,
    pending_count: 1,
    oldest_started_at: "2026-10-02T09:31:18Z",
    oldest_duration_seconds: 42,
    next_action: "Canonical SDK quarantine guidance.",
  };
  return fixture;
}

function clearRecoveryFixture(accountId = ALT_ACCOUNT) {
  return {
    generated_at: "2026-10-02T09:33:00Z",
    external_account_id: accountId,
    mode: "paper",
    status: "clear",
    recovery_blocked: false,
    unresolved_count: 0,
    displayed_unresolved_count: 0,
    unknown_count: 0,
    displayed_unknown_count: 0,
    unresolved_parent_count: 0,
    displayed_parent_count: 0,
    unknown_parent_count: 0,
    displayed_unknown_parent_count: 0,
    truncated: false,
    primary_blocker: null,
    next_action: "No recovery action is required.",
    parents: [],
    intents: [],
    sdk_quarantine: {
      available: true,
      pending_count: 0,
      oldest_started_at: null,
      oldest_duration_seconds: null,
      next_action: null,
    },
  };
}

function unavailableRecoveryFixture() {
  const fixture = sdkBlockedRecoveryFixture();
  fixture.sdk_quarantine = {
    available: false,
    pending_count: 0,
    oldest_started_at: null,
    oldest_duration_seconds: null,
    next_action: "Canonical unavailable SDK state.",
  };
  fixture.primary_blocker = "sdk_runtime_unavailable";
  return fixture;
}

function childIntentList() {
  const item = recoveryIntentFixture("recovery-child-coverage");
  return [{
    ...item,
    request_hash: "a".repeat(64),
    idempotency_key: "recovery-child-key",
    broker: "longbridge",
    broker_marker: "st:recovery0000001",
    request_payload: { symbol: "MOCK.US" },
    last_error: "mock unknown outcome",
  }];
}

function parentActionList(mode) {
  if (mode === "rich") {
    return [{
      id: "recovery-parent-composite",
      external_account_id: PRIMARY_ACCOUNT,
      broker: "longbridge",
      mode: "paper",
      idempotency_key: "recovery-parent-composite-key",
      request_hash: "b".repeat(64),
      action: "bull_put_execute",
      strategy_id: "paper_bull_put_v1",
      entity_id: "recovery-spread-1",
      state: "unknown",
      request_payload: { symbol: "MOCK.US" },
      response_payload: null,
      last_error: "mock unknown parent outcome",
      created_at: "2026-10-02T09:29:00Z",
      updated_at: "2026-10-02T09:31:00Z",
    }];
  }
  if (mode === "parent-only") {
    return [{
      id: "recovery-parent-only-unknown",
      external_account_id: PRIMARY_ACCOUNT,
      broker: "longbridge",
      mode: "paper",
      idempotency_key: "recovery-parent-only-key",
      request_hash: "b".repeat(64),
      action: "order_submit",
      strategy_id: "paper_bull_put_v1",
      entity_id: "recovery-parent-only",
      state: "unknown",
      request_payload: { symbol: "MOCK.US" },
      response_payload: null,
      last_error: "mock unknown parent outcome",
      created_at: "2026-10-02T09:29:00Z",
      updated_at: "2026-10-02T09:31:00Z",
    }];
  }
  return [];
}

function replaceAccountInUrl(rawUrl, accountId) {
  const url = new URL(rawUrl);
  if (url.searchParams.has("external_account_id")) {
    url.searchParams.set("external_account_id", accountId);
  }
  return url.toString();
}

function cloneFixtureAccountFields(value, fromAccount, toAccount) {
  if (Array.isArray(value)) {
    return value.map((item) => cloneFixtureAccountFields(item, fromAccount, toAccount));
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  const clone = {};
  for (const [key, item] of Object.entries(value)) {
    if ((key === "external_account_id" || key === "account_id") && item === fromAccount) {
      clone[key] = toAccount;
    } else {
      clone[key] = cloneFixtureAccountFields(item, fromAccount, toAccount);
    }
  }
  return clone;
}

async function fulfillJson(route, payload, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

async function main() {
  const [, , baseUrl, outputDirectory, playwrightCorePath, timeoutArg = "30000"] = process.argv;
  if (!baseUrl || !outputDirectory || !playwrightCorePath) {
    throw new Error("Usage: node recovery_ui_browser_flow.js <baseUrl> <outputDirectory> <playwrightCorePath> [timeoutMs]");
  }
  const timeoutMs = Number(timeoutArg);
  const { chromium } = require(playwrightCorePath);
  const executablePath = resolveBrowserExecutable();
  const { browser, page } = await launchBrowserPage(chromium, {
    browserOptions: {
      headless: true,
      ...(executablePath ? { executablePath } : {}),
    },
    pageOptions: { viewport: { width: 1440, height: 1200 } },
  });
  page.setDefaultTimeout(timeoutMs);
  page.on("dialog", (dialog) => dialog.dismiss());

  const recoveryRequests = [];
  const queryEvidence = [];
  const mutationRequests = [];
  let recoveryMode = "parent-only";
  let delayedRecovery = null;
  let delayedResolver = null;
  let syntheticOrders = null;
  let delayedOrdersPage = null;
  let delayedOrdersResolver = null;

  const releaseDelayedRecovery = () => {
    if (delayedResolver) {
      const resolver = delayedResolver;
      delayedResolver = null;
      resolver();
    }
  };

  const releaseDelayedOrders = () => {
    if (delayedOrdersResolver) {
      const resolver = delayedOrdersResolver;
      delayedOrdersResolver = null;
      resolver();
    }
  };

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    if (method !== "GET" && method !== "HEAD") {
      mutationRequests.push({ path: `${url.pathname}${url.search}`, method });
    }
    if (method === "GET" && ["/orders/paged", "/strategies/bull-put/working-spreads", "/strategies/bull-put/spreads/paged"].includes(url.pathname)) {
      queryEvidence.push({ path: url.pathname, query: Object.fromEntries(url.searchParams.entries()) });
    }

    if (url.pathname === "/ops/recovery-status" && method === "GET") {
      const accountId = url.searchParams.get("external_account_id") || PRIMARY_ACCOUNT;
      recoveryRequests.push({ accountId, mode: recoveryMode, at: Date.now() });
      if (delayedRecovery && delayedRecovery.accountId === accountId) {
        const outcome = delayedRecovery.outcome;
        delayedRecovery = null;
        await new Promise((resolve) => {
          delayedResolver = resolve;
        });
        if (outcome === "error") {
          await fulfillJson(route, { detail: "Mock recovery status failure." }, 503);
          return;
        }
      }
      if (recoveryMode === "error") {
        await fulfillJson(route, { detail: "Mock recovery status failure." }, 503);
      } else if (recoveryMode === "unavailable" || recoveryMode === "sdk-unavailable") {
        await fulfillJson(route, unavailableRecoveryFixture());
      } else if (recoveryMode === "parent-only") {
        await fulfillJson(route, parentOnlyRecoveryFixture());
      } else if (recoveryMode === "sdk-blocked") {
        await fulfillJson(route, sdkBlockedRecoveryFixture());
      } else if (accountId === ALT_ACCOUNT) {
        await fulfillJson(route, clearRecoveryFixture());
      } else if (recoveryMode === "clear") {
        await fulfillJson(route, clearRecoveryFixture(PRIMARY_ACCOUNT));
      } else {
        await fulfillJson(route, richRecoveryFixture());
      }
      return;
    }

    if (url.pathname === "/ops/trading-intents" && method === "GET") {
      const accountId = url.searchParams.get("external_account_id");
      await fulfillJson(route, accountId === ALT_ACCOUNT || !["parent-only", "rich"].includes(recoveryMode) ? [] : recoveryMode === "rich" ? childIntentList() : []);
      return;
    }
    if (url.pathname === "/ops/trade-actions" && method === "GET") {
      const accountId = url.searchParams.get("external_account_id");
      await fulfillJson(route, accountId === ALT_ACCOUNT ? [] : parentActionList(recoveryMode));
      return;
    }
    if (url.pathname === "/broker-accounts" && method === "GET") {
      const response = await route.fetch();
      const accounts = await response.json();
      accounts.push({
        ...accounts[0],
        id: "mock-account-alt",
        external_account_id: ALT_ACCOUNT,
        display_name: "Longbridge Paper Alt",
      });
      await fulfillJson(route, accounts);
      return;
    }
    if (url.pathname === "/orders/paged" && method === "GET") {
      const response = await route.fetch({ url: replaceAccountInUrl(request.url(), PRIMARY_ACCOUNT) });
      const payload = await response.json();
      if (!syntheticOrders) {
        const seeds = Array.isArray(payload.items) ? payload.items : [];
        if (!seeds.length) {
          throw new Error("Mock orders page returned no seed rows for pagination validation.");
        }
        syntheticOrders = Array.from({ length: 26 }, (_, index) => ({
          ...seeds[index % seeds.length],
          id: `recovery-page-order-${index + 1}`,
          external_order_id: `recovery-page-external-${index + 1}`,
          updated_at: `2026-10-02T09:${String(index).padStart(2, "0")}:00Z`,
        }));
      }
      const cursor = Number(url.searchParams.get("cursor") || "0");
      const limit = Number(url.searchParams.get("limit") || "25");
      if (delayedOrdersPage && delayedOrdersPage.accountId === (url.searchParams.get("external_account_id") || PRIMARY_ACCOUNT) && cursor === delayedOrdersPage.cursor) {
        delayedOrdersPage = null;
        await new Promise((resolve) => {
          delayedOrdersResolver = resolve;
        });
      }
      const items = syntheticOrders
        .slice(cursor, cursor + limit)
        .map((item) => url.searchParams.get("external_account_id") === ALT_ACCOUNT
          ? cloneFixtureAccountFields(item, PRIMARY_ACCOUNT, ALT_ACCOUNT)
          : item);
      const nextCursor = cursor + items.length < syntheticOrders.length ? String(cursor + items.length) : null;
      await fulfillJson(route, { items, next_cursor: nextCursor, has_more: nextCursor !== null, limit });
      return;
    }
    if (method === "GET" && /^\/orders\/[^/]+$/.test(url.pathname)) {
      const orderId = decodeURIComponent(url.pathname.split("/").pop());
      const accountId = url.searchParams.get("external_account_id") || PRIMARY_ACCOUNT;
      const source = syntheticOrders?.find((order) => order.id === orderId);
      if (source) {
        await fulfillJson(route, cloneFixtureAccountFields(source, PRIMARY_ACCOUNT, accountId));
        return;
      }
    }
    if (url.searchParams.get("external_account_id") === ALT_ACCOUNT) {
      const response = await route.fetch({ url: replaceAccountInUrl(request.url(), PRIMARY_ACCOUNT) });
      const contentType = response.headers()["content-type"] || "";
      if (contentType.includes("application/json")) {
        const payload = await response.json();
        await fulfillJson(route, cloneFixtureAccountFields(payload, PRIMARY_ACCOUNT, ALT_ACCOUNT), response.status());
      } else {
        await route.fulfill({ response });
      }
      return;
    }
    await route.fallback();
  });

  const screenshots = {};
  let paginationEvidence = null;
  let accountRaceEvidence = null;
  let failureEvidence = null;
  let languageEvidence = null;
  let reasonEvidence = null;
  let sdkEvidence = null;
  let tradingSafetyEvidence = null;
  let frontendStateEvidence = null;

  const runTradingSafetyDomChecks = async () => {
    recoveryMode = "rich";
    await page.evaluate(() => document.getElementById("refresh-dashboard")?.click());
    await expectText(page.locator("#operations-recovery-panel"), "券商历史覆盖不完整");
    const blockedNoButton = await page.evaluate(async () => {
      window.__m1MutationCalls = 0;
      const result = await window.runConfirmedBrokerMutation({
        actionKey: "m1-no-button-blocked",
        confirmation: { title: "M1 blocked", summary: "M1 blocked", details: {} },
        requestSignature: "blocked",
        statusElement: null,
      }, async () => { window.__m1MutationCalls += 1; return { ok: true }; });
      return { blocked: result.blocked === true, calls: window.__m1MutationCalls, dialogOpen: Boolean(document.querySelector("#trade-confirm-dialog[open]")) };
    });
    if (!blockedNoButton.blocked || blockedNoButton.calls !== 0 || blockedNoButton.dialogOpen) {
      throw new Error(`No-button recovery guard failed: ${JSON.stringify(blockedNoButton)}`);
    }

    recoveryMode = "clear";
    await page.evaluate(() => document.getElementById("refresh-dashboard")?.click());
    await expectText(page.locator("#operations-recovery-panel"), "无阻塞");

    const noButtonBusiness = await page.evaluate(async () => {
      window.__m1MutationCalls = 0;
      const result = await window.runConfirmedBrokerMutation({
        actionKey: "m1-recover-close-business",
        confirmation: { title: "M1 recovery business", summary: "M1 recovery business", details: {} },
        requestSignature: "recover-business",
        businessPredicate: () => false,
        businessBlockedMessage: "Recovery close is no longer eligible. No request was sent.",
        statusElement: null,
      }, async () => { window.__m1MutationCalls += 1; return { ok: true }; });
      return { blocked: result.blocked === true, calls: window.__m1MutationCalls, dialogOpen: Boolean(document.querySelector("#trade-confirm-dialog[open]")) };
    });
    if (!noButtonBusiness.blocked || noButtonBusiness.calls !== 0 || noButtonBusiness.dialogOpen) {
      throw new Error(`No-button business predicate failed: ${JSON.stringify(noButtonBusiness)}`);
    }
    const buttonBusiness = await page.evaluate(async () => {
      const button = document.getElementById("run-strategy-scan");
      button.dataset.businessDisabled = "true";
      window.__m1MutationCalls = 0;
      const result = await window.runConfirmedBrokerMutation({
        actionKey: "m1-button-business",
        button,
        confirmation: { title: "M1 button business", summary: "M1 button business", details: {} },
        requestSignature: "button-business",
        statusElement: null,
      }, async () => { window.__m1MutationCalls += 1; return { ok: true }; });
      delete button.dataset.businessDisabled;
      return { blocked: result.blocked === true, calls: window.__m1MutationCalls, dialogOpen: Boolean(document.querySelector("#trade-confirm-dialog[open]")) };
    });
    if (!buttonBusiness.blocked || buttonBusiness.calls !== 0 || buttonBusiness.dialogOpen) {
      throw new Error(`Button business predicate failed: ${JSON.stringify(buttonBusiness)}`);
    }

    const accountRaceStart = await page.evaluate(() => {
      window.__m1MutationCalls = 0;
      window.__m1AccountRacePromise = window.runConfirmedBrokerMutation({
        actionKey: "m1-account-race",
        confirmation: { title: "M1 account race", summary: "M1 account race", details: {} },
        requestSignature: "account-race",
        statusElement: null,
      }, async () => { window.__m1MutationCalls += 1; return { ok: true }; });
      return true;
    });
    if (!accountRaceStart) throw new Error("Could not start account race mutation.");
    await page.waitForSelector("#trade-confirm-dialog[open]");
    await page.evaluate(() => {
      const select = document.getElementById("account-select");
      select.value = "LBPT10087357-ALT";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await waitFor(() => page.locator("#account-select").inputValue().then((value) => value === ALT_ACCOUNT), timeoutMs, "account change during confirmation");
    await page.click("#trade-confirm-accept");
    const accountRaceResult = await page.evaluate(async () => window.__m1AccountRacePromise);
    if (accountRaceResult.executed || accountRaceResult.contextChanged !== true) {
      throw new Error(`Account-change confirmation recheck failed: ${JSON.stringify(accountRaceResult)}`);
    }

    await page.evaluate(() => {
      const select = document.getElementById("account-select");
      select.value = "LBPT10087357";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await waitFor(() => page.locator("#account-select").inputValue().then((value) => value === PRIMARY_ACCOUNT), timeoutMs, "primary account restore");
    recoveryMode = "clear";
    await page.evaluate(() => document.getElementById("refresh-dashboard")?.click());
    await expectText(page.locator("#operations-recovery-panel"), "无阻塞");

    const abaRaceStart = await page.evaluate(() => {
      window.__m1MutationCalls = 0;
      window.__m1AbaPromise = window.runConfirmedBrokerMutation({
        actionKey: "m1-a-b-a",
        confirmation: { title: "M1 A-B-A", summary: "M1 A-B-A", details: {} },
        requestSignature: "a-b-a",
        statusElement: null,
      }, async () => { window.__m1MutationCalls += 1; return { ok: true }; });
      return true;
    });
    if (!abaRaceStart) throw new Error("Could not start A-B-A mutation.");
    await page.waitForSelector("#trade-confirm-dialog[open]");
    await page.evaluate(() => {
      const select = document.getElementById("account-select");
      select.value = "LBPT10087357-ALT";
      select.dispatchEvent(new Event("change", { bubbles: true }));
      select.value = "LBPT10087357";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await waitFor(() => page.locator("#account-select").inputValue().then((value) => value === PRIMARY_ACCOUNT), timeoutMs, "A-B-A account restore");
    await page.click("#trade-confirm-accept");
    const abaResult = await page.evaluate(async () => window.__m1AbaPromise);
    if (abaResult.executed || abaResult.contextChanged !== true) {
      throw new Error(`A-B-A confirmation recheck failed: ${JSON.stringify(abaResult)}`);
    }

    const recoveryRaceStart = await page.evaluate(() => {
      window.__m1MutationCalls = 0;
      window.__m1RecoveryRacePromise = window.runConfirmedBrokerMutation({
        actionKey: "m1-recovery-race",
        confirmation: { title: "M1 recovery race", summary: "M1 recovery race", details: {} },
        requestSignature: "recovery-race",
        statusElement: null,
      }, async () => { window.__m1MutationCalls += 1; return { ok: true }; });
      return true;
    });
    if (!recoveryRaceStart) throw new Error("Could not start recovery race mutation.");
    await page.waitForSelector("#trade-confirm-dialog[open]");
    recoveryMode = "rich";
    await page.evaluate(() => document.getElementById("refresh-dashboard")?.click());
    await expectText(page.locator("#operations-recovery-panel"), "券商历史覆盖不完整");
    await page.click("#trade-confirm-accept");
    const recoveryRaceResult = await page.evaluate(async () => window.__m1RecoveryRacePromise);
    if (recoveryRaceResult.executed || recoveryRaceResult.contextChanged !== true) {
      throw new Error(`Recovery-change confirmation recheck failed: ${JSON.stringify(recoveryRaceResult)}`);
    }

    recoveryMode = "clear";
    await page.evaluate(() => document.getElementById("refresh-dashboard")?.click());
    await expectText(page.locator("#operations-recovery-panel"), "无阻塞");
    const signatureStart = await page.evaluate(() => {
      window.__m1MutationCalls = 0;
      window.__m1RequestSignature = "old-signature";
      window.__m1SignaturePromise = window.runConfirmedBrokerMutation({
        actionKey: "m1-signature-change",
        confirmation: { title: "M1 signature change", summary: "M1 signature change", details: {} },
        requestSignature: "old-signature",
        getRequestSignature: () => window.__m1RequestSignature,
        statusElement: null,
      }, async () => { window.__m1MutationCalls += 1; return { ok: true }; });
      return true;
    });
    if (!signatureStart) throw new Error("Could not start signature-change mutation.");
    await page.waitForSelector("#trade-confirm-dialog[open]");
    await page.evaluate(() => { window.__m1RequestSignature = "new-signature"; });
    await page.click("#trade-confirm-accept");
    const signatureResult = await page.evaluate(async () => window.__m1SignaturePromise);
    if (signatureResult.executed || signatureResult.contextChanged !== true) {
      throw new Error(`Request-signature confirmation recheck failed: ${JSON.stringify(signatureResult)}`);
    }

    await page.evaluate(() => {
      window.__m1MutationCalls = 0;
      window.__m1FirstPromise = window.runConfirmedBrokerMutation({
        actionKey: "m1-duplicate",
        confirmation: { title: "M1 duplicate", summary: "M1 duplicate", details: {} },
        requestSignature: "duplicate",
        statusElement: null,
      }, async () => {
        window.__m1MutationCalls += 1;
        return { ok: true };
      });
      return true;
    });
    await page.waitForSelector("#trade-confirm-dialog[open]");
    const duplicatePromise = page.evaluate(async () => window.runConfirmedBrokerMutation({
      actionKey: "m1-duplicate",
      confirmation: { title: "M1 duplicate", summary: "M1 duplicate", details: {} },
      requestSignature: "duplicate",
      statusElement: null,
    }, async () => { window.__m1MutationCalls += 1; return { ok: true }; }));
    await page.click("#trade-confirm-accept");
    const firstResult = await page.evaluate(async () => window.__m1FirstPromise);
    const duplicateResult = await duplicatePromise;
    if (duplicateResult.executed || duplicateResult.blocked !== true) {
      throw new Error(`Duplicate mutation was not blocked: ${JSON.stringify(duplicateResult)}`);
    }
    const duplicateCalls = await page.evaluate(() => window.__m1MutationCalls);
    if (!firstResult.executed || duplicateCalls !== 1) {
      throw new Error(`Duplicate mutation operation count was not exactly one: ${JSON.stringify({ firstResult, duplicateCalls })}`);
    }
    return {
      blockedWithoutButton: true,
      noButtonBusinessRejected: true,
      buttonBusinessRejected: true,
      accountChangeRejected: true,
      abaContextRejected: true,
      recoveryChangeRejected: true,
      signatureChangeRejected: true,
      duplicateOperationCount: duplicateCalls,
      ownPendingAllowed: true,
    };
  };

  try {
    await page.goto(baseUrl, { waitUntil: "load" });
    await page.waitForSelector("#account-select", { state: "attached" });
    await page.waitForSelector("#research-table-body tr", { state: "attached" });
    await expectText(page.locator("#research-table-body"), "MOCK.US");
    await page.waitForSelector("#operations-recovery-panel", { state: "attached" });
    await waitFor(
      () => page.locator("#operations-recovery-panel").innerText().then((text) => text.includes("订单结果未知")),
      timeoutMs,
      "parent-only recovery panel",
    );
    await page.locator("[data-workspace-option='operations']").click();
    await page.waitForFunction(() => document.body.dataset.workspace === "operations");
    await expectText(page.locator("#operations-recovery-panel"), "订单结果未知");
    const parentOnlyText = await page.locator("#operations-recovery-panel").innerText();
    if (parentOnlyText.includes("子意图证据") && !parentOnlyText.includes("没有未解决的订单意图")) {
      throw new Error("Parent-only fixture unexpectedly included child evidence.");
    }
    const assertBrokerGuard = async (blocked, label) => {
      const states = await page.locator("[data-broker-mutation='true']").evaluateAll((nodes) =>
        nodes.map((node) => ({ id: node.id, disabled: Boolean(node.disabled || node.getAttribute("aria-disabled") === "true") })),
      );
      if (states.length === 0) {
        throw new Error(`No broker mutation controls found while checking ${label}.`);
      }
      if (blocked && states.some((item) => !item.disabled)) {
        const panel = await page.locator("#operations-recovery-panel").innerText().catch(() => "");
        const status = await page.locator("#status-banner").innerText().catch(() => "");
        const titles = await page.locator("[data-broker-mutation='true']").evaluateAll((nodes) =>
          nodes.map((node) => ({ id: node.id, title: node.title, disabled: Boolean(node.disabled) })),
        );
        throw new Error(`${label} did not disable broker controls: ${JSON.stringify({ states, panel, status, titles })}`);
      }
      if (!blocked && states.every((item) => item.disabled)) {
        throw new Error(`${label} left every broker control disabled: ${JSON.stringify(states)}`);
      }
      return states;
    };
    await assertBrokerGuard(true, "parent-only unknown recovery");
    const parentOnlyEvidence = { parent_only: true, child_count_visible: 0, broker_gate_blocked: true };
    tradingSafetyEvidence = await runTradingSafetyDomChecks();
    frontendStateEvidence = await runFrontendStateBrowserChecks({
      page,
      timeoutMs,
      setRecoveryMode: (mode) => { recoveryMode = mode; },
      mutationRequests,
    });

    const refreshDashboardForMode = async (mode, expectedText) => {
      recoveryMode = mode;
      await page.click("#refresh-dashboard");
      await expectText(page.locator("#operations-recovery-panel"), expectedText);
      await expectText(page.locator("#research-table-body"), "MOCK.US");
    };

    await refreshDashboardForMode("rich", "券商历史覆盖不完整");
    await expectText(page.locator("#operations-recovery-panel"), "父动作还需要复核");
    await expectText(page.locator("#operations-recovery-panel"), "核对次数还不够");
    await expectText(page.locator("#operations-recovery-panel"), "核对时间窗口还不够");
    await expectText(page.locator("#operations-recovery-panel"), "已有券商订单记录");
    await expectText(page.locator("#operations-recovery-panel"), "SDK 超时调用仍在等待");
    const recoveryText = await page.locator("#operations-recovery-panel").innerText();
    if (!recoveryText.includes("12") || !recoveryText.includes("已显示 4")) {
      throw new Error(`Recovery totals did not preserve truncation evidence: ${recoveryText}`);
    }
    reasonEvidence = {
      coverage: recoveryText.includes("券商历史覆盖不完整"),
      checks: recoveryText.includes("核对次数还不够"),
      span: recoveryText.includes("核对时间窗口还不够"),
      knownExternalOrder: recoveryText.includes("已有券商订单记录"),
      parentOnlyUnknown: parentOnlyEvidence.parent_only,
      truncatedTotals: recoveryText.includes("12") && recoveryText.includes("已显示 4"),
    };

    await waitResponsiveSettled(page, 1440, timeoutMs);
    await page.screenshot({ path: path.join(outputDirectory, "recovery-rich-1440.png"), fullPage: true });
    screenshots.rich1440 = path.join(outputDirectory, "recovery-rich-1440.png");
    await page.setViewportSize({ width: 760, height: 1000 });
    await waitResponsiveSettled(page, 760, timeoutMs);
    await page.screenshot({ path: path.join(outputDirectory, "recovery-rich-760.png"), fullPage: true });
    screenshots.rich760 = path.join(outputDirectory, "recovery-rich-760.png");
    await page.setViewportSize({ width: 1440, height: 1200 });
    await waitResponsiveSettled(page, 1440, timeoutMs);

    await page.locator("[data-lang-option='en']").click();
    await expectText(page.locator("#operations-recovery-panel"), "Broker history is incomplete");
    await expectText(page.locator("#operations-recovery-panel"), "Wait for a history window");
    await page.locator("[data-lang-option='zh']").click();
    await expectText(page.locator("#operations-recovery-panel"), "券商历史覆盖不完整");
    languageEvidence = {
      chinese: true,
      english: true,
      canonical_codes_hidden: !(await page.locator("#operations-recovery-panel").innerText()).includes("reconciliation_coverage_incomplete"),
    };
    if (!languageEvidence.canonical_codes_hidden) {
      throw new Error("Canonical recovery codes must remain secondary tooltip data, not primary UI text.");
    }

    delayedRecovery = { accountId: PRIMARY_ACCOUNT, outcome: "success" };
    await page.click("#refresh-dashboard");
    await waitFor(() => delayedResolver !== null, timeoutMs, "delayed primary UI refresh recovery request");
    await page.selectOption("#account-select", ALT_ACCOUNT);
    await waitFor(() => page.locator("#account-select").inputValue().then((value) => value === ALT_ACCOUNT), timeoutMs, "alternate account selection");
    await expectText(page.locator("#operations-recovery-panel"), "无阻塞");
    releaseDelayedRecovery();
    await sleep(250);
    if ((await page.locator("#operations-recovery-panel").innerText()).includes("已阻塞")) {
      throw new Error("Late primary recovery response overwrote the alternate account panel.");
    }

    delayedRecovery = { accountId: ALT_ACCOUNT, outcome: "error" };
    await page.click("#refresh-dashboard");
    await waitFor(() => delayedResolver !== null, timeoutMs, "delayed alternate UI refresh recovery request");
    await page.selectOption("#account-select", PRIMARY_ACCOUNT);
    await waitFor(() => page.locator("#account-select").inputValue().then((value) => value === PRIMARY_ACCOUNT), timeoutMs, "primary account reselection");
    await expectText(page.locator("#operations-recovery-panel"), "券商历史覆盖不完整");
    releaseDelayedRecovery();
    await sleep(250);
    if (!(await page.locator("#operations-recovery-panel").innerText()).includes("券商历史覆盖不完整")) {
      throw new Error("Late alternate recovery failure overwrote the primary account panel.");
    }
    accountRaceEvidence = { stale_success_ignored: true, stale_failure_ignored: true, triggered_by_ui_refresh_and_account_select: true };

    recoveryMode = "sdk-unavailable";
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#operations-recovery-panel"), "SDK 运行状态暂时不可读");
    await assertBrokerGuard(true, "SDK unavailable recovery");
    sdkEvidence = { pending: true, unavailable: true };

    await refreshDashboardForMode("clear", "无阻塞");
    await assertBrokerGuard(false, "clear recovery state");
    await refreshDashboardForMode("sdk-blocked", "SDK 超时调用仍在等待");
    await assertBrokerGuard(true, "SDK pending recovery state");
    await refreshDashboardForMode("clear", "无阻塞");
    await assertBrokerGuard(false, "clear recovery state after SDK pending");
    recoveryMode = "error";
    await page.click("#refresh-dashboard");
    try {
      await waitFor(async () => {
        const text = await page.locator("#operations-recovery-panel").innerText();
        return text.includes("恢复状态暂时无法加载") || text.includes("Recovery status could not be loaded") || text.includes("Recovery status unavailable");
      }, timeoutMs, "recovery API error panel");
    } catch (error) {
      throw new Error(`${error.message}; panel=${JSON.stringify(await page.locator("#operations-recovery-panel").innerText())}; status=${JSON.stringify(await page.locator("#status-banner").innerText())}; recoveryRequests=${JSON.stringify(recoveryRequests.slice(-4))}`);
    }
    await expectText(page.locator("#research-table-body"), "MOCK.US");
    await assertBrokerGuard(true, "recovery API error");
    failureEvidence = { recovery_error_visible: true, research_still_healthy: true, broker_gate_still_blocked: true };
    await waitResponsiveSettled(page, 1440, timeoutMs);
    await page.screenshot({ path: path.join(outputDirectory, "recovery-error-1440.png"), fullPage: true });
    screenshots.error1440 = path.join(outputDirectory, "recovery-error-1440.png");

    // Verify a normal page and then a late page response cannot cross accounts.
    recoveryMode = "clear";
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#operations-recovery-panel"), "无阻塞");
    await page.click("#open-execution-drawer");
    await page.waitForSelector("#execution-drawer[open]");
    await page.click("button[data-execution-tab='orders']");
    await page.waitForSelector("#orders-load-more:not([hidden])");
    const beforeRows = await page.locator("#orders-body tr").count();
    await page.click("#orders-load-more");
    await waitFor(async () => (await page.locator("#orders-body tr").count()) > beforeRows, timeoutMs, "orders load-more page");
    const normalAfterRows = await page.locator("#orders-body tr").count();
    await page.click("#close-execution-drawer");
    await page.waitForSelector("#execution-drawer", { state: "hidden" });
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#operations-recovery-panel"), "无阻塞");
    await page.click("#open-execution-drawer");
    await page.waitForSelector("#execution-drawer[open]");
    await page.click("button[data-execution-tab='orders']");
    await page.waitForSelector("#orders-load-more:not([hidden])");
    delayedOrdersPage = { accountId: PRIMARY_ACCOUNT, cursor: 25 };
    await page.click("#orders-load-more");
    await waitFor(() => delayedOrdersResolver !== null, timeoutMs, "delayed orders pagination response");
    await page.click("#close-execution-drawer");
    await page.waitForSelector("#execution-drawer", { state: "hidden" });
    await page.selectOption("#account-select", ALT_ACCOUNT);
    await waitFor(() => page.locator("#account-select").inputValue().then((value) => value === ALT_ACCOUNT), timeoutMs, "alternate account for delayed pagination");
    releaseDelayedOrders();
    await sleep(300);
    await page.click("#open-execution-drawer");
    await page.waitForSelector("#execution-drawer[open]");
    await page.click("button[data-execution-tab='orders']");
    await waitFor(async () => (await page.locator("#orders-body tr").count()) > 0, timeoutMs, "alternate account orders page");
    const delayedRowsText = await page.locator("#orders-body").innerText();
    if (delayedRowsText.includes("recovery-page-order-26") || await page.locator("#orders-body [data-order-id='recovery-page-order-26']").count() > 0) {
      throw new Error("Late primary pagination response contaminated the alternate account DOM.");
    }
    paginationEvidence = { beforeRows, normalAfterRows, delayed_page_discarded: true, alternate_account: ALT_ACCOUNT };
    await waitResponsiveSettled(page, 1440, timeoutMs);
    await page.screenshot({ path: path.join(outputDirectory, "recovery-final-1440.png"), fullPage: true });
    screenshots.final1440 = path.join(outputDirectory, "recovery-final-1440.png");

    if (mutationRequests.length > 0) {
      throw new Error(`Broker mutation requests were observed: ${JSON.stringify(mutationRequests)}`);
    }
    const missingPaperMode = queryEvidence.filter((entry) => entry.query.mode !== "paper");
    if (missingPaperMode.length > 0) {
      throw new Error(`Paper-mode query contract was violated: ${JSON.stringify(missingPaperMode)}`);
    }
    return {
      rendered: true,
      recovery_requests: recoveryRequests,
      query_evidence: queryEvidence,
      reasons: reasonEvidence,
      language: languageEvidence,
      sdk: sdkEvidence,
      account_race: accountRaceEvidence,
      recovery_failure: failureEvidence,
      pagination: paginationEvidence,
      trading_safety: tradingSafetyEvidence,
      frontend_state: frontendStateEvidence,
      mutation_requests: mutationRequests,
      screenshots,
    };
  } finally {
    await browser.close();
  }
}

main().then((result) => {
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}).catch((error) => {
  console.error(error);
  process.exit(1);
});

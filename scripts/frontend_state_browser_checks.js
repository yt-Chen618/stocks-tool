const {
  expectText,
  sleep,
  waitFor,
} = require("./browser_test_helpers");

const PRIMARY_ACCOUNT = "LBPT10087357";
const ALT_ACCOUNT = "LBPT10087357-ALT";

async function selectAccount(page, accountId, timeoutMs) {
  await page.selectOption("#account-select", accountId);
  await waitFor(
    () => page.locator("#account-select").inputValue().then((value) => value === accountId),
    timeoutMs,
    `account selection ${accountId}`,
  );
  await expectText(page.locator("#operations-recovery-panel"), "无阻塞", timeoutMs);
  await expectText(page.locator("#research-table-body"), "MOCK.US", timeoutMs);
}

async function refreshClear(page, setRecoveryMode, timeoutMs) {
  setRecoveryMode("clear");
  await page.click("#refresh-dashboard");
  await expectText(page.locator("#operations-recovery-panel"), "无阻塞", timeoutMs);
  await expectText(page.locator("#research-table-body"), "MOCK.US", timeoutMs);
}

async function runFrontendStateBrowserChecks({ page, timeoutMs, setRecoveryMode, mutationRequests }) {
  const evidence = {};
  const initialMutationCount = mutationRequests.length;

  await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);

  let auxStartedResolve;
  let auxReleaseResolve;
  let auxFinishedResolve;
  let auxStarted = false;
  let auxFinished = false;
  const auxStartedPromise = new Promise((resolve) => { auxStartedResolve = resolve; });
  const auxFinishedPromise = new Promise((resolve) => { auxFinishedResolve = resolve; });
  const auxPattern = "**/strategies/zero-dte-lottery/runtime**";
  const delayedAuxRoute = async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    auxStarted = true;
    auxStartedResolve();
    await new Promise((resolve) => { auxReleaseResolve = resolve; });
    await route.fallback();
    auxFinished = true;
    auxFinishedResolve();
  };
  await page.route(auxPattern, delayedAuxRoute);
  try {
    await refreshClear(page, setRecoveryMode, timeoutMs);
    await auxStartedPromise;
    await waitFor(
      async () => (await page.locator("#orders-body tr").count()) > 0
        && (await page.locator("#research-table-body").innerText()).includes("MOCK.US"),
      timeoutMs,
      "core panels before auxiliary request release",
    );
    const coreBeforeAuxRelease = {
      orders_rows: await page.locator("#orders-body tr").count(),
      research_visible: (await page.locator("#research-table-body").innerText()).includes("MOCK.US"),
      auxiliary_started: auxStarted,
      auxiliary_finished_before_release: auxFinished,
    };
    if (!coreBeforeAuxRelease.orders_rows || !coreBeforeAuxRelease.research_visible || coreBeforeAuxRelease.auxiliary_finished_before_release) {
      throw new Error(`Core panels did not settle before auxiliary release: ${JSON.stringify(coreBeforeAuxRelease)}`);
    }
    auxReleaseResolve();
    await auxFinishedPromise;
    evidence.slow_auxiliary = { ...coreBeforeAuxRelease, auxiliary_finished_after_release: auxFinished };
  } finally {
    if (auxReleaseResolve) auxReleaseResolve();
    await page.unroute(auxPattern, delayedAuxRoute);
  }

  await page.click("#open-execution-drawer");
  await page.waitForSelector("#execution-drawer[open]");
  await page.click("button[data-execution-tab='orders']");
  const manageButton = page.locator("button[data-order-action='manage']").first();
  await manageButton.waitFor({ state: "visible" });
  const orderId = await manageButton.getAttribute("data-order-id");
  if (!orderId) throw new Error("M6 selected-order fixture did not expose an order id.");
  const detailRequests = [];
  const detailListener = (request) => {
    const url = new URL(request.url());
    if (url.pathname === `/orders/${orderId}` || (
      ["/executions/paged", "/journals/paged"].includes(url.pathname)
      && url.searchParams.get("order_id") === orderId
    )) {
      detailRequests.push(`${url.pathname}${url.search}`);
    }
  };
  page.on("request", detailListener);
  try {
    await manageButton.click();
    await manageButton.click();
    await waitFor(
      () => page.locator("#selected-order-card").innerText().then((text) => text.includes(orderId) || text.includes("UNH") || text.includes("MOCK")),
      timeoutMs,
      "selected order detail",
    );
    await sleep(250);
  } finally {
    page.off("request", detailListener);
  }
  const detailCounts = {
    order: detailRequests.filter((path) => path.startsWith(`/orders/${orderId}`)).length,
    executions: detailRequests.filter((path) => path.startsWith("/executions/paged")).length,
    journals: detailRequests.filter((path) => path.startsWith("/journals/paged")).length,
  };
  if (detailCounts.order !== 1 || detailCounts.executions !== 1 || detailCounts.journals !== 1) {
    throw new Error(`Repeated same-generation selection duplicated detail requests: ${JSON.stringify({ orderId, detailCounts, detailRequests })}`);
  }
  evidence.same_generation_detail_requests = { orderId, counts: detailCounts };

  await page.click("#close-execution-drawer");
  await page.waitForSelector("#execution-drawer", { state: "hidden" });
  await refreshClear(page, setRecoveryMode, timeoutMs);
  await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);
  await page.evaluate(() => {
    window.__m6ReleaseUnknown = null;
    window.__m6MutationOperationStarted = false;
    window.__m6MutationPromise = window.runConfirmedBrokerMutation({
      actionKey: "m6-late-unknown",
      requestSignature: "m6-late-unknown-signature",
      confirmation: { title: "M6 late unknown", summary: "M6 late unknown", details: {} },
      statusElement: null,
    }, async () => {
      window.__m6MutationOperationStarted = true;
      return new Promise((_resolve, reject) => {
        window.__m6ReleaseUnknown = () => reject({ code: "order_outcome_unknown", intentId: "m6-unknown-a" });
      });
    });
  });
  await page.waitForSelector("#trade-confirm-dialog[open]");
  await page.click("#trade-confirm-accept");
  await waitFor(() => page.evaluate(() => window.__m6MutationOperationStarted === true), timeoutMs, "late unknown operation start");
  await selectAccount(page, ALT_ACCOUNT, timeoutMs);
  await page.evaluate(() => window.__m6ReleaseUnknown?.());
  const lateUnknownResult = await page.evaluate(async () => window.__m6MutationPromise);
  if (lateUnknownResult.discarded !== true) {
    throw new Error(`Late A unknown operation was not discarded: ${JSON.stringify(lateUnknownResult)}`);
  }
  const bSuccess = await page.evaluate(() => {
    window.__m6MutationCalls = 0;
    window.__m6BPromise = window.runConfirmedBrokerMutation({
      actionKey: "m6-late-unknown",
      requestSignature: "m6-b-success-signature",
      confirmation: { title: "M6 B success", summary: "M6 B success", details: {} },
      statusElement: null,
    }, async () => { window.__m6MutationCalls += 1; return { ok: true }; });
    return true;
  });
  if (!bSuccess) throw new Error("Could not start B-scoped mutation.");
  await page.waitForSelector("#trade-confirm-dialog[open]");
  await page.click("#trade-confirm-accept");
  const bSuccessResult = await page.evaluate(async () => window.__m6BPromise);
  if (bSuccessResult.executed !== true || await page.evaluate(() => window.__m6MutationCalls) !== 1) {
    throw new Error(`B account incorrectly inherited A unknown lock: ${JSON.stringify(bSuccessResult)}`);
  }
  await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);
  const aBlockedResult = await page.evaluate(() => {
    window.__m6MutationCalls = 0;
    return window.runConfirmedBrokerMutation({
      actionKey: "m6-late-unknown",
      requestSignature: "m6-a-retry-signature",
      confirmation: { title: "M6 A retry", summary: "M6 A retry", details: {} },
      statusElement: null,
    }, async () => { window.__m6MutationCalls += 1; return { ok: true }; });
  });
  if (aBlockedResult.blocked !== true || await page.evaluate(() => window.__m6MutationCalls) !== 0) {
    throw new Error(`A account did not retain its unknown lock: ${JSON.stringify(aBlockedResult)}`);
  }
  evidence.late_unknown_scope = {
    discarded_on_A_response: true,
    B_operation_executed: true,
    A_retry_blocked: true,
    intent_id: "m6-unknown-a",
  };

  await page.reload({ waitUntil: "load" });
  await page.waitForSelector("#account-select", { state: "attached" });
  await expectText(page.locator("#research-table-body"), "MOCK.US", timeoutMs);
  await refreshClear(page, setRecoveryMode, timeoutMs);
  await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);
  await page.evaluate(() => {
    window.__m6ReleaseTerminal = null;
    window.__m6TerminalPromise = window.runConfirmedBrokerMutation({
      actionKey: "m6-terminal-4xx",
      requestSignature: "m6-terminal-signature",
      confirmation: { title: "M6 terminal", summary: "M6 terminal", details: {} },
      statusElement: null,
    }, async () => new Promise((_resolve, reject) => {
      window.__m6ReleaseTerminal = () => reject({ status: 400, code: "m6_terminal_fixture", message: "terminal fixture" });
    }));
  });
  await page.waitForSelector("#trade-confirm-dialog[open]");
  await page.click("#trade-confirm-accept");
  await waitFor(() => page.evaluate(() => typeof window.__m6ReleaseTerminal === "function"), timeoutMs, "terminal operation start");
  await selectAccount(page, ALT_ACCOUNT, timeoutMs);
  await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);
  await page.evaluate(() => window.setStatus?.("A-current-status", "success"));
  await page.evaluate(() => window.__m6ReleaseTerminal?.());
  const terminalResult = await page.evaluate(async () => window.__m6TerminalPromise);
  const currentStatus = await page.locator("#status-banner").innerText();
  const terminalKey = await page.evaluate(() => window.sessionStorage.getItem("stocks-tool-idempotency:LBPT10087357:m6-terminal-4xx"));
  if (terminalResult.discarded !== true || currentStatus !== "A-current-status" || terminalKey !== null) {
    throw new Error(`A->B->A terminal response was not isolated/cleared: ${JSON.stringify({ terminalResult, currentStatus, terminalKey })}`);
  }
  evidence.terminal_4xx_scope = {
    discarded_on_stale_response: true,
    current_status_preserved: true,
    original_idempotency_key_cleared: true,
  };

  if (mutationRequests.length !== initialMutationCount) {
    throw new Error(`M6 fake mutation checks observed HTTP mutation requests: ${JSON.stringify(mutationRequests.slice(initialMutationCount))}`);
  }
  evidence.mutation_requests_added = mutationRequests.length - initialMutationCount;
  return evidence;
}

module.exports = { runFrontendStateBrowserChecks };

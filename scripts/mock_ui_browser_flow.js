const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const [, , baseUrl, screenshotPath, playwrightCorePath, scenario = "normal"] = process.argv;
  if (!baseUrl || !screenshotPath || !playwrightCorePath) {
    throw new Error("Usage: node mock_ui_browser_flow.js <baseUrl> <screenshotPath> <playwrightCorePath>");
  }

  const { chromium } = require(playwrightCorePath);
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 2200 } });
  page.on("dialog", (dialog) => dialog.accept());
  const brokerMutationRequests = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && isBrokerMutationPath(url.pathname, url.search)) {
      brokerMutationRequests.push({
        path: `${url.pathname}${url.search}`,
        headers: request.headers(),
        postData: request.postData(),
      });
    }
  });
  let journalPanelText = "";
  let strategySkipText = "";
  let strategyReviewText = "";
  let lotteryPreviewText = "";
  let lotteryScanText = "";
  let preOpenAssessmentText = "";
  let preOpenRunText = "";
  let lifecycleWarningText = "";
  let operatorPostureText = "";

  try {
    await page.goto(baseUrl, { waitUntil: "load" });
    await page.waitForSelector("#account-select");
    await page.waitForSelector("#spreads-body tr");
    await page.waitForFunction(
      () => {
        const text = document.getElementById("status-banner")?.textContent || "";
        return text.includes("Dashboard updated") || text.includes("\u5de5\u4f5c\u53f0\u5df2\u66f4\u65b0");
      },
      { timeout: 10000 },
    );
    const initialViewMode = await page.evaluate(() => document.body.dataset.viewMode);
    const initialVisibleSecondaryPanels = await page.locator("[data-view-priority='secondary']:visible").count();
    if (initialViewMode !== "focus" || initialVisibleSecondaryPanels !== 0) {
      throw new Error("Dashboard must start in focus mode with secondary information hidden.");
    }
    await page.locator("[data-view-mode-option='all']").click();
    await page.waitForFunction(() => document.body.dataset.viewMode === "all");
    if ((await page.locator("[data-view-priority='secondary']:visible").count()) === 0) {
      throw new Error("All view must reveal secondary dashboard information.");
    }
    await expectText(page.locator("body"), "\u7b56\u7565\u4e2d\u5fc3");
    await expectText(page.locator("body"), "\u6267\u884c\u5de5\u4f5c\u53f0");
    await expectText(page.locator("body"), "\u5b9e\u65f6\u5b8f\u89c2\u677f");
    await page.locator("[data-lang-option='en']").click();
    await expectText(page.locator("body"), "Strategy Center");
    await expectText(page.locator("body"), "Real-time Macro Board");
    if (scenario !== "normal") {
      const posture = await runPostureScenarioAssertions(page, scenario);
      fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
      await page.screenshot({ path: screenshotPath, fullPage: true });
      process.stdout.write(JSON.stringify({ rendered: true, scenario, screenshot: screenshotPath, ...posture }, null, 2));
      return;
    }
    await expectText(page.locator("body"), "Risk Proxies");
    await expectText(page.locator("body"), "QQQ / SPY Put Check");
    await expectText(page.locator("body"), "Stored Opening Follow-through");
    await expectText(page.locator("body"), "Bull Put Strategy");
    await expectText(page.locator("#reconciliation-strip"), "Broker Profile");
    await expectText(page.locator("#reconciliation-strip"), "CONFIG_DECLARED");
    await expectText(page.locator("#reconciliation-strip"), "Scheduler Posture");
    await expectText(page.locator("#reconciliation-strip"), "Paper Mandate");
    await expectText(page.locator("#reconciliation-strip"), "3 Strategies");
    await expectText(page.locator("#reconciliation-strip"), "Manual Actions");
    await expectText(page.locator("#reconciliation-strip"), "Advisor Last Run");
    await expectText(page.locator("#reconciliation-strip"), "1 Warning");
    operatorPostureText = await page.locator("#reconciliation-strip").innerText();
    await expectText(page.locator("body"), "Lottery Strategy");
    await expectText(page.locator("body"), "Bull Put Monitor");
    await expectText(page.locator("body"), "Execution Desk");
    await expectText(page.locator("#strategy-runtime-strip"), "Entry Status");
    await expectText(page.locator("#zero-dte-lottery-strip"), "Preview Only");
    await expectText(page.locator("#strategy-experiment-strip"), "Active Proposals");
    await expectText(page.locator("#covered-call-activity-card"), "MSFT covered call lifecycle");
    await page.locator("#covered-call-activity-card [data-covered-call-action='reconcile-lifecycle']").click();
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Covered-call lifecycle refreshed read-only"),
    );
    await expectText(page.locator("#market-events-card"), "UNH earnings window");
    await expectText(page.locator("#spread-summary-strip"), "Active Spreads");
    await expectText(page.locator("#spread-summary-strip"), "Close order canceled / manual action needed");
    await expectText(page.locator("#spreads-body"), "MANUAL ACTION NEEDED");
    await expectText(page.locator("#spreads-body"), "Review close workflow before leaving unattended.");
    lifecycleWarningText = await page.locator("#spreads-body").innerText();
    await page.click("#preview-zero-dte-lottery");
    await page.waitForFunction(
      () => document.getElementById("zero-dte-lottery-result-card")?.innerText?.includes("Eligible Lottery Candidate"),
    );
    lotteryPreviewText = await page.locator("#zero-dte-lottery-result-card").innerText();
    if ((await page.locator("#run-zero-dte-lottery-scan").count()) !== 0) {
      throw new Error("Zero-DTE Force Scan must not be rendered.");
    }
    if (!(await page.locator("#zero-dte-lottery-auto-order").isDisabled())) {
      throw new Error("Zero-DTE auto order control must stay disabled.");
    }
    lotteryScanText = "Preview only; no execution control rendered.";
    await page.getByRole("button", { name: "Load Live Macro" }).click();
    await expectText(page.locator("#preopen-summary-strip"), "Board Status");
    await expectText(page.locator("#preopen-assessment-card"), "QQQ cleaner than SPY");
    await expectText(page.locator("#preopen-signals"), "Nasdaq 100 ETF");
    await expectText(page.locator("#preopen-puts"), "QQQ260530P498000.US");
    await expectText(page.locator("#preopen-run-review"), "Opening follow-through confirmed");
    await page.getByRole("button", { name: "Save Current Board" }).click();
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Stored macro board"),
    );
    preOpenAssessmentText = await page.locator("#preopen-assessment-card").innerText();
    preOpenRunText = await page.locator("#preopen-run-review").innerText();

    await clickRowButton(page, "#spreads-body tr", "QQQ.US", "Monitor");
    await confirmTradeDialog(page, "Confirm Bull Put monitor", "QQQ.US");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Take Profit"),
    );
    await page.waitForFunction(
      () => document.getElementById("spreads-body")?.innerText?.toLowerCase().includes("closed"),
    );

    await page.selectOption("#strategy-manual-pause", "true");
    await page.fill("#strategy-paused-symbols", "SMH.US");
    await page.click("#save-strategy-controls");
    await confirmTradeDialog(page, "Confirm Bull Put controls", "LBPT10087357");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("controls updated"),
    );
    await page.waitForFunction(
      () => document.getElementById("strategy-runtime-strip")?.innerText?.toLowerCase().includes("paused"),
    );
    strategySkipText = await page.locator("#strategy-runtime-strip").innerText();
    await page.selectOption("#strategy-manual-pause", "false");
    await page.click("#save-strategy-controls");
    await confirmTradeDialog(page, "Confirm Bull Put controls", "LBPT10087357");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("controls updated"),
    );
    await page.click("#run-strategy-scan");
    await page.waitForSelector("#trade-confirm-dialog[open]");
    await expectText(page.locator("#trade-confirm-dialog"), "QQQ260626P705000.US");
    await confirmTradeDialog(page, "Confirm Bull Put paper order", "$248.00");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("paper order opened"),
    );
    const bullPutExecution = brokerMutationRequests.find(
      (request) => request.path === "/strategies/bull-put/execute",
    );
    if (!bullPutExecution) {
      throw new Error("Confirmed Bull Put preview did not call the bound execute endpoint.");
    }
    const bullPutPayload = JSON.parse(bullPutExecution.postData || "{}");
    if (
      bullPutPayload.external_account_id !== "LBPT10087357" ||
      bullPutPayload.symbol !== "QQQ.US" ||
      bullPutPayload.candidate_token !== "mock-qqq-candidate-token" ||
      String(bullPutPayload.minimum_net_credit) !== "0.52" ||
      bullPutPayload.confirm_paper_order !== true
    ) {
      throw new Error(`Bull Put execution was not bound to the confirmed candidate: ${bullPutExecution.postData}`);
    }
    await expectText(page.locator("#spreads-body"), "705 / 708 puts");
    await page.click("#run-strategy-review");
    await page.waitForFunction(
      () => document.getElementById("strategy-review-card")?.innerText?.toLowerCase().includes("short delta target"),
    );
    strategyReviewText = await page.locator("#strategy-review-card").innerText();

    await clickFilledOrderManage(page);
    await expectText(page.locator("#selected-order-execution"), "Filled Qty");
    await expectText(page.locator("#selected-order-execution"), "388.65");

    await page.fill("#journal-title", "Browser regression review");
    await page.fill("#journal-tags", "browser, spread");
    await page.fill(
      "#journal-notes",
      "Browser regression validated spread monitor, execution summary, and journal workflow.",
    );
    await page.click("#submit-journal");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Journal entry saved"),
    );
    await expectText(page.locator("#selected-order-journal"), "Browser regression review");
    journalPanelText = await page.locator("#selected-order-journal").innerText();

    await page.fill("#order-symbol", "MOCK.US");
    await page.fill("#order-quantity", "1");
    await page.selectOption("#order-type", "limit");
    await page.fill("#order-limit-price", "320");
    const submitCountBeforeCancel = countMutationRequests(brokerMutationRequests, "/orders/submit");
    await page.click("#submit-order");
    await expectText(page.locator("#trade-confirm-dialog"), "Confirm paper order");
    await page.click("#trade-confirm-cancel");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Paper action canceled"),
    );
    if (countMutationRequests(brokerMutationRequests, "/orders/submit") !== submitCountBeforeCancel) {
      throw new Error("Canceling the native confirmation dialog must send no order request.");
    }

    await page.evaluate(() => {
      const button = document.getElementById("submit-order");
      button.click();
      button.click();
    });
    await page.waitForSelector("#trade-confirm-dialog[open]");
    if ((await page.locator("#submit-order").getAttribute("aria-busy")) !== "true") {
      throw new Error("Order submit must expose aria-busy while confirmation is pending.");
    }
    await confirmTradeDialog(page, "Confirm paper order", "Limit $320.00");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Order submitted"),
    );
    if (countMutationRequests(brokerMutationRequests, "/orders/submit") !== submitCountBeforeCancel + 1) {
      throw new Error("Double-click protection must submit exactly one order request.");
    }
    const pendingIdempotencyKeys = await page.evaluate(() =>
      Object.keys(sessionStorage).filter((key) => key.startsWith("stocks-tool-idempotency:")),
    );
    if (pendingIdempotencyKeys.length !== 0) {
      throw new Error(`Terminal order success must clear its idempotency key: ${pendingIdempotencyKeys.join(", ")}`);
    }

    await page.waitForSelector("#replace-order-form:not(.hidden)");
    await page.fill("#replace-quantity", "2");
    await page.fill("#replace-limit-price", "321");
    await page.click("#replace-order-form button[type='submit']");
    await confirmTradeDialog(page, "Confirm paper order replacement", "Limit $321.00");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("updated"),
    );
    await expectText(page.locator("#selected-order-card"), "x 2");

    await page.click("#selected-order-card button[data-selected-action='cancel']");
    await confirmTradeDialog(page, "Confirm paper order cancellation", "Cancel BUY 2 MOCK.US");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("canceled"),
    );
    await page.waitForFunction(
      () => document.getElementById("selected-order-card")?.innerText?.toLowerCase().includes("canceled"),
    );

    assertMutationHeaders(brokerMutationRequests);
    if (brokerMutationRequests.some((request) => request.path.includes("zero-dte-lottery") && request.path.includes("scan"))) {
      throw new Error("Zero-DTE preview-only UI must never request the scan endpoint.");
    }

    await page.setViewportSize({ width: 760, height: 1000 });
    await page.waitForFunction(() => document.getElementById("submit-order")?.disabled === true);
    const enabledMobileMutations = await page.locator("[data-broker-mutation='true']:not(:disabled)").count();
    if (enabledMobileMutations !== 0) {
      throw new Error(`Mobile viewport left ${enabledMobileMutations} broker mutation control(s) enabled.`);
    }
    if (!(await page.locator("#desktop-trading-notice").isVisible())) {
      throw new Error("Mobile viewport must show the desktop-required trading notice.");
    }
    await page.setViewportSize({ width: 1600, height: 2200 });
    await page.waitForFunction(() => document.getElementById("submit-order")?.disabled === false);
    await page.locator("[data-view-mode-option='focus']").click();
    await page.waitForFunction(() => document.body.dataset.viewMode === "focus");

    fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: true });

    const summary = await page.evaluate(() => {
      const spreadRow = document.querySelector("#spreads-body tr");
      return {
        selectedOrderText: document.getElementById("selected-order-card")?.innerText ?? "",
        statusBanner: document.getElementById("status-banner")?.textContent ?? "",
        spreadTable: spreadRow?.innerText ?? "",
        journalText: document.getElementById("selected-order-journal")?.innerText ?? "",
      };
    });

    process.stdout.write(
      JSON.stringify(
        {
          preOpen: {
            rendered: preOpenAssessmentText.includes("QQQ cleaner than SPY"),
            summary: preOpenAssessmentText,
          },
          preOpenRun: {
            rendered: preOpenRunText.includes("Opening follow-through confirmed"),
            summary: preOpenRunText,
          },
          spread: {
            monitorTriggered:
              summary.statusBanner.includes("canceled") || summary.spreadTable.toLowerCase().includes("closed"),
            tableRow: summary.spreadTable,
            lifecycleWarningRendered: lifecycleWarningText.toLowerCase().includes("manual action needed"),
            lifecycleWarning: lifecycleWarningText,
          },
          operator: {
            rendered:
              operatorPostureText.includes("Broker Profile") &&
              operatorPostureText.includes("Paper Mandate") &&
              operatorPostureText.includes("Advisor Last Run"),
            summary: operatorPostureText,
          },
          strategy: {
            manualPauseRendered: strategySkipText.toLowerCase().includes("paused"),
            skipReason: strategySkipText,
            reviewRendered: strategyReviewText.toLowerCase().includes("short delta target"),
            reviewSummary: strategyReviewText,
          },
          lottery: {
            previewRendered: lotteryPreviewText.includes("Eligible Lottery Candidate"),
            scanRendered: false,
            summary: lotteryScanText,
          },
          order: {
            selectedOrder: summary.selectedOrderText,
            finalStatusBanner: summary.statusBanner,
            mutationRequestCount: brokerMutationRequests.length,
            idempotencyHeadersPresent: brokerMutationRequests.every(
              (request) => Boolean(request.headers["idempotency-key"]),
            ),
            doubleClickSubmittedOnce: countMutationRequests(brokerMutationRequests, "/orders/submit") === 1,
            confirmationCancelSentNoRequest: submitCountBeforeCancel === 0,
          },
          mobile: {
            brokerActionsDisabled: true,
            desktopNoticeRendered: true,
          },
          journal: {
            rendered: journalPanelText.includes("Browser regression review"),
            latestPanel: journalPanelText,
          },
          screenshot: screenshotPath,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}

async function expectText(locator, text, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  let content = "";
  while (Date.now() < deadline) {
    try {
      content = await locator.innerText();
      if (content.includes(text)) {
        return;
      }
    } catch {
      // ignore and retry
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Expected text '${text}' to appear in locator content. Current content: ${content}`);
}

async function runPostureScenarioAssertions(page, scenario) {
  if (scenario === "unknown-intent") {
    await page.fill("#order-symbol", "MOCK.US");
    await page.fill("#order-quantity", "1");
    await page.selectOption("#order-type", "limit");
    await page.fill("#order-limit-price", "320");
    await page.click("#submit-order");
    await confirmTradeDialog(page, "Confirm paper order", "MOCK.US");
    await expectText(page.locator("#status-banner"), "Broker order outcome is unknown");
    if ((await page.locator("[data-broker-mutation='true']:not(:disabled)").count()) !== 0) {
      throw new Error("Unknown order outcome must lock every broker-writing action.");
    }
    const pendingKeys = await page.evaluate(() =>
      Object.keys(sessionStorage).filter((key) => key.startsWith("stocks-tool-idempotency:")),
    );
    if (pendingKeys.length !== 1) {
      throw new Error(`Unknown outcome must retain exactly one retry key; found ${pendingKeys.length}.`);
    }
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#status-banner"), "unresolved trading intent");
    if ((await page.locator("[data-broker-mutation='true']:not(:disabled)").count()) !== 0) {
      throw new Error("Reloaded unknown intent must keep broker-writing actions locked.");
    }
    return { brokerActionsDisabled: true, idempotencyKeyRetained: true, reloadStillBlocked: true };
  }

  if (scenario === "auxiliary-data-failure") {
    const before = await page.locator("#market-events-card").innerText();
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#status-banner"), "Auxiliary panels unavailable: Market events");
    const after = await page.locator("#market-events-card").innerText();
    if (before !== after) {
      throw new Error("Auxiliary refresh failure must preserve the prior Market Events panel.");
    }
    if ((await page.locator("#market-events-card").getAttribute("data-load-state")) !== "stale") {
      throw new Error("Auxiliary refresh failure must mark its panel stale.");
    }
    if (await page.locator("#submit-order").isDisabled()) {
      throw new Error("An auxiliary-only failure must not invalidate otherwise complete core data.");
    }
    return { stalePanel: "market-events", priorDataPreserved: true, globalTone: "warning" };
  }

  if (scenario === "core-data-failure") {
    const before = await page.locator("#orders-body").innerText();
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#status-banner"), "Core account data is stale: Orders");
    const after = await page.locator("#orders-body").innerText();
    if (before !== after) {
      throw new Error("Required-data refresh failure must preserve prior Orders data.");
    }
    if ((await page.locator("#orders-body").getAttribute("data-load-state")) !== "stale") {
      throw new Error("Required-data failure must mark the Orders panel stale.");
    }
    if (!(await page.locator("#submit-order").isDisabled())) {
      throw new Error("Required-data failure must disable broker-writing actions.");
    }
    if (!(await page.locator("#status-banner").getAttribute("class")).includes("error")) {
      throw new Error("Required-data failure must not render a global success state.");
    }
    return { stalePanel: "orders", priorDataPreserved: true, brokerActionsDisabled: true, globalTone: "error" };
  }

  if (scenario === "covered-call-data-failure") {
    const before = await page.locator("#covered-call-activity-card").innerText();
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#status-banner"), "Core account data is stale: Covered Call activity");
    const after = await page.locator("#covered-call-activity-card").innerText();
    if (!after.includes("MSFT covered call lifecycle") || !before.includes("MSFT covered call lifecycle")) {
      throw new Error("Covered Call refresh failure must preserve the prior proposal data.");
    }
    if ((await page.locator("#covered-call-activity-card").getAttribute("data-load-state")) !== "stale") {
      throw new Error("Covered Call failure must mark its panel stale.");
    }
    if ((await page.locator("[data-broker-mutation='true']:not(:disabled)").count()) !== 0) {
      throw new Error("Stale Covered Call data must disable every broker-writing action.");
    }
    return { stalePanel: "covered-call", priorDataPreserved: true, brokerActionsDisabled: true };
  }

  if (scenario === "accounts-data-failure") {
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#status-banner"), "Mock broker accounts failure");
    if ((await page.locator("[data-broker-mutation='true']:not(:disabled)").count()) !== 0) {
      throw new Error("Broker-account refresh failure must disable every broker-writing action.");
    }
    if (!(await page.locator("#status-banner").getAttribute("class")).includes("error")) {
      throw new Error("Broker-account refresh failure must render an error state.");
    }
    return { brokerAccountsHealthy: false, brokerActionsDisabled: true, globalTone: "error" };
  }

  const expectedText = {
    "degraded-broker": "Degraded",
    "paused-mandate": "Paused",
    "advisor-pending-record": "Dry Run Only",
    "manual-action-required": "MANUAL ACTION NEEDED",
    "scheduler-backoff": "Backoff active",
    "recover-eligible": "Recovery Eligible",
    "recover-rejected": "close_not_required",
    "recover-already-working": "mock-order-0001",
    "ledger-mismatch": "WARN",
    "repair-available": "1 Repair",
    "quote-cache-fallback": "quote cache fallback",
    "scheduler-lease-active": "Single-flight lease is active",
  }[scenario];
  if (!expectedText) {
    throw new Error(`No DOM assertion is defined for mock posture scenario '${scenario}'.`);
  }
  const postureLocator = scenario === "paused-mandate" ? page.locator("#reconciliation-strip") : page.locator("body");
  await expectTextInsensitive(postureLocator, expectedText);
  return { expectedText, matched: true };
}

async function expectTextInsensitive(locator, text, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  const expected = text.toLowerCase();
  let content = "";
  while (Date.now() < deadline) {
    try {
      content = await locator.innerText();
      if (content.toLowerCase().includes(expected)) {
        return;
      }
    } catch {
      // ignore and retry
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Expected text '${text}' to appear in locator content. Current content: ${content}`);
}

async function confirmTradeDialog(page, titleText, detailText) {
  await page.waitForSelector("#trade-confirm-dialog[open]");
  await expectText(page.locator("#trade-confirm-dialog"), titleText);
  if (detailText) {
    await expectText(page.locator("#trade-confirm-dialog"), detailText);
  }
  await page.click("#trade-confirm-accept");
  await page.waitForSelector("#trade-confirm-dialog", { state: "hidden" });
}

function isBrokerMutationPath(pathname, search) {
  if (pathname === "/orders/submit") return true;
  if (pathname === "/strategies/bull-put/execute") return true;
  if (/^\/orders\/[^/]+\/(replace|cancel)$/.test(pathname)) return true;
  if (/^\/strategies\/bull-put\/spreads\/[^/]+\/(monitor|recover-close)$/.test(pathname)) return true;
  if (pathname.includes("/strategies/bull-put/runtime/") && pathname.endsWith("/scan") && search.includes("force=true")) return true;
  return /^\/strategies\/covered-call\/proposals\/[^/]+\/(execute|monitor|close|roll-execute|roll-continue)$/.test(pathname);
}

function countMutationRequests(requests, pathPrefix) {
  return requests.filter((request) => request.path.startsWith(pathPrefix)).length;
}

function assertMutationHeaders(requests) {
  const keyPattern = /^[A-Za-z0-9._:-]{16,128}$/;
  for (const request of requests) {
    const key = request.headers["idempotency-key"] || "";
    if (!keyPattern.test(key)) {
      throw new Error(`Mutation request ${request.path} is missing a valid Idempotency-Key.`);
    }
    if (
      request.path === "/strategies/bull-put/execute" ||
      (request.path.includes("/strategies/bull-put/runtime/") && request.path.includes("force=true"))
    ) {
      if (request.headers["x-confirm-paper-order"] !== "true") {
        throw new Error("Bull Put force scan must include X-Confirm-Paper-Order: true.");
      }
    }
  }
}

async function clickRowButton(page, rowSelector, matchText, buttonText) {
  const rows = page.locator(rowSelector);
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    const row = rows.nth(index);
    const text = await row.innerText();
    if (!text.includes(matchText)) {
      continue;
    }
    await row.getByRole("button", { name: buttonText }).click();
    return;
  }
  throw new Error(`Could not find row '${matchText}' with button '${buttonText}'.`);
}

async function clickFilledOrderManage(page) {
  const rows = page.locator("#orders-body tr");
  const count = await rows.count();
  for (let index = 0; index < count; index += 1) {
    const row = rows.nth(index);
    const text = await row.innerText();
    if (!text.toLowerCase().includes("filled")) {
      continue;
    }
    await row.getByRole("button", { name: "Manage" }).click();
    return;
  }
  throw new Error("Could not find a filled order row to manage.");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

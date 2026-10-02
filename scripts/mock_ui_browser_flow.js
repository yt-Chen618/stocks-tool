const fs = require("node:fs");
const path = require("node:path");
const {
  createRequestObserver,
  expectText,
  expectTextInsensitive,
  isBrokerMutationPath,
  resolveBrowserExecutable,
} = require("./browser_test_helpers");

async function main() {
  const [, , baseUrl, screenshotPath, playwrightCorePath, scenario = "normal"] = process.argv;
  if (!baseUrl || !screenshotPath || !playwrightCorePath) {
    throw new Error("Usage: node mock_ui_browser_flow.js <baseUrl> <screenshotPath> <playwrightCorePath>");
  }

  const { chromium } = require(playwrightCorePath);
  const executablePath = resolveBrowserExecutable();
  const browser = await chromium.launch({
    headless: true,
    ...(executablePath ? { executablePath } : {}),
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
  page.on("dialog", (dialog) => dialog.accept());
  const requestObserver = createRequestObserver(page, {
    readPredicate: (request, url) => request.method() === "GET" && (
      url.pathname === "/strategies/bull-put/working-spreads" ||
      url.pathname === "/strategies/bull-put/spreads/paged" ||
      /^\/strategies\/bull-put\/spreads\/[^/]+$/.test(url.pathname) ||
      /\/strategies\/bull-put\/spreads\/[^/]+\/recover-close\/eligibility$/.test(url.pathname)
    ),
    mutationPredicate: (pathname, search, request) => request.method() === "POST" && isBrokerMutationPath(pathname, search),
  });
  const brokerMutationRequests = requestObserver.mutationRequests;
  const bullPutReadRequests = requestObserver.readRequests;
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
    await page.waitForSelector("#account-select", { state: "attached" });
    await page.waitForSelector("#spreads-body tr", { state: "attached" });
    await page.waitForSelector("#research-table-body tr");
    await page.waitForFunction(
      () => {
        const text = document.getElementById("status-banner")?.textContent || "";
        return text.includes("Dashboard updated") || text.includes("\u5de5\u4f5c\u53f0\u5df2\u66f4\u65b0");
      },
      { timeout: 10000 },
    );
    if ((await page.evaluate(() => document.body.dataset.workspace)) !== "research") {
      throw new Error("Workbench must start in the Research workspace.");
    }
    if (!(await page.locator("#research-section").isVisible())) {
      throw new Error("Default Research workspace must be visible.");
    }
    if ((await page.locator("[data-workspace-panel]:visible").count()) !== 1) {
      throw new Error("Exactly one workspace panel must be visible at a time.");
    }
    await expectText(page.locator("#research-table-body"), "MOCK.US");
    await expectText(page.locator("#research-table-body"), "QQQ.US");
    await page.waitForFunction(
      () => document.getElementById("research-min-return20")?.disabled === false,
    );

    const researchTab = page.locator("[data-workspace-option='research']");
    await researchTab.focus();
    await researchTab.press("ArrowDown");
    await page.waitForFunction(() => document.body.dataset.workspace === "strategy");
    if (!(await page.locator("[data-workspace-option='strategy']").evaluate((node) => node === document.activeElement))) {
      throw new Error("Sidebar ArrowDown must activate and focus the next workspace tab.");
    }
    await selectWorkspace(page, "research");
    await page.click("#sidebar-toggle");
    if ((await page.locator("#sidebar-toggle").getAttribute("aria-expanded")) !== "false") {
      throw new Error("Sidebar toggle must expose its collapsed state through aria-expanded.");
    }
    await page.click("#sidebar-toggle");

    await page.locator("[data-lang-option='en']").click();
    await expectText(page.locator("#research-section"), "Research Desk");

    await page.click("#manage-watchlist-button");
    await page.waitForSelector("#watchlist-dialog[open]");
    await page.fill("#watchlist-name", "core-us-regression");
    await page.fill("#watchlist-description", "Updated by browser regression");
    const watchlistPatch = page.waitForResponse(
      (response) => response.request().method() === "PATCH" && response.url().includes("/watchlists/mock-watchlist-1"),
    );
    await page.click("#watchlist-save");
    await watchlistPatch;
    await expectText(page.locator("#research-watchlist-select"), "core-us-regression");
    const notesInput = page.locator('[data-watchlist-item-notes="mock-watchlist-item-1"]');
    await notesInput.fill("updated regression note");
    const notesPatch = page.waitForResponse(
      (response) => response.request().method() === "PATCH" && response.url().includes("mock-watchlist-item-1"),
    );
    await page.click('[data-watchlist-action="save-notes"][data-item-id="mock-watchlist-item-1"]');
    await notesPatch;
    await page.fill("#watchlist-symbol", "aapl.us");
    await page.fill("#watchlist-notes", "temporary browser item");
    const addItemResponse = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().endsWith("/watchlists/mock-watchlist-1/items"),
    );
    await page.click("#watchlist-add-item");
    await addItemResponse;
    const addedWatchlistRow = page.locator("#watchlist-items-body tr", { hasText: "AAPL.US" });
    await addedWatchlistRow.waitFor();
    const removeItemResponse = page.waitForResponse(
      (response) => response.request().method() === "DELETE" && response.url().includes("/watchlists/mock-watchlist-1/items/"),
    );
    await addedWatchlistRow.locator('[data-watchlist-action="remove-item"]').click();
    await removeItemResponse;
    await page.waitForFunction(
      () => !document.getElementById("watchlist-items-body")?.textContent?.includes("AAPL.US"),
    );
    await page.click("#close-watchlist-dialog");
    await page.waitForSelector("#watchlist-dialog", { state: "hidden" });

    await page.locator("[data-research-columns='momentum']").click();
    await page.locator("[data-research-sort='return_20d_pct']").click();
    const selectedResearchRow = page.locator("#research-table-body tr[data-research-select='MOCK.US']");
    await selectedResearchRow.focus();
    await selectedResearchRow.press("Enter");
    if ((await selectedResearchRow.getAttribute("aria-selected")) !== "true") {
      throw new Error("Research rows must support keyboard selection.");
    }
    await page.locator("[data-research-view='chart']").click();
    await page.waitForSelector("#research-chart-view:not([hidden])");
    if (!(await page.locator("#research-table-view").isHidden())) {
      throw new Error("Chart view must hide the research table view.");
    }
    await page.locator("[data-chart-range='3m']").click();
    await expectText(page.locator("#research-chart-summary"), "66 daily bars");
    await page.locator("[data-chart-range='6m']").click();
    await expectText(page.locator("#research-chart-summary"), "132 daily bars");
    await page.fill("#research-search", "QQQ.US");
    await page.waitForFunction(
      () => window.StocksToolResearch?.getState?.().selectedSymbol === "QQQ.US",
    );
    const filteredTableSelection = page.locator(
      "#research-table-body tr[data-research-select='QQQ.US'][aria-selected='true']",
    );
    const filteredRailSelection = page.locator(
      "#research-symbol-list [data-research-select='QQQ.US'][aria-selected='true']",
    );
    if ((await filteredTableSelection.count()) !== 1 || (await filteredRailSelection.count()) !== 1) {
      throw new Error("Filtering out the selected symbol must synchronize table and symbol-rail selection.");
    }
    await expectText(page.locator("#research-chart-summary"), "QQQ.US");
    await expectText(page.locator("#research-chart-summary"), "132 daily bars");
    await page.locator("[data-research-view='table']").click();
    if (!(await filteredTableSelection.isVisible())) {
      throw new Error("The filtered replacement selection must remain visible in Screener view.");
    }
    await page.locator("[data-research-view='chart']").click();
    if (!(await filteredRailSelection.isVisible())) {
      throw new Error("The filtered replacement selection must remain visible in Chart view.");
    }
    await page.click("details.research-filters > summary");
    await page.click("#research-reset-filters");
    await page.waitForFunction(
      () => document.getElementById("research-search")?.value === "" &&
        document.querySelectorAll("#research-table-body tr[data-research-select]").length === 2,
    );
    await page.locator("#research-symbol-list [data-research-select='MOCK.US']").click();
    await expectText(page.locator("#research-chart-summary"), "MOCK.US");
    const ticketBeforeResearch = await readTicketDefaults(page);
    await page.click("#research-prepare-order");
    await page.waitForSelector("#execution-drawer[open]");
    if ((await page.locator("#order-symbol").inputValue()) !== "MOCK.US") {
      throw new Error("Research order preparation must transfer the selected symbol.");
    }
    await assertTicketDefaultsUnchanged(page, ticketBeforeResearch);
    await page.keyboard.press("Escape");
    await page.waitForSelector("#execution-drawer", { state: "hidden" });

    if (scenario !== "normal") {
      const posture = await runPostureScenarioAssertions(page, scenario);
      fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
      await page.screenshot({ path: screenshotPath, fullPage: true });
      process.stdout.write(JSON.stringify({ rendered: true, scenario, screenshot: screenshotPath, ...posture }, null, 2));
      return;
    }
    await selectWorkspace(page, "operations");
    await expectText(page.locator("#reconciliation-strip"), "Broker Profile");
    await expectText(page.locator("#reconciliation-strip"), "CONFIG_DECLARED");
    await expectText(page.locator("#reconciliation-strip"), "Scheduler Posture");
    await expectText(page.locator("#reconciliation-strip"), "Paper Mandate");
    await expectText(page.locator("#reconciliation-strip"), "3 Strategies");
    await expectText(page.locator("#reconciliation-strip"), "Manual Actions");
    await expectText(page.locator("#reconciliation-strip"), "Advisor Last Run");
    await expectText(page.locator("#reconciliation-strip"), "1 Warning");
    operatorPostureText = await page.locator("#reconciliation-strip").innerText();

    await selectWorkspace(page, "strategy");
    await selectStrategyTab(page, "bull-put");
    await expectText(page.locator("#strategy-section"), "Bull Put Strategy");
    await expectText(page.locator("#strategy-section"), "Bull Put Monitor");
    const initialEligibilityReads = bullPutReadRequests.filter((request) => request.pathname.endsWith("/recover-close/eligibility")).length;
    if (initialEligibilityReads !== 0) {
      throw new Error(`Initial Bull Put load must not issue recovery eligibility N+1 requests: ${initialEligibilityReads}`);
    }
    const workingRead = bullPutReadRequests.find((request) => request.pathname === "/strategies/bull-put/working-spreads");
    if (!workingRead || !workingRead.search.includes("external_account_id=LBPT10087357") || !workingRead.search.includes("mode=paper")) {
      throw new Error("Bull Put working-spreads read must be scoped to the selected paper account.");
    }
    const historyPageResponse = page.waitForResponse((response) => response.request().method() === "GET" && response.url().includes("/strategies/bull-put/spreads/paged"));
    await page.click("#bull-put-history-panel > summary");
    await historyPageResponse;
    await expectText(page.locator("#bull-put-history-body"), "QQQ.US");
    const historyDetailResponse = page.waitForResponse((response) => response.request().method() === "GET" && response.url().includes("/strategies/bull-put/spreads/mock-spread-closed-0001"));
    await page.locator("#bull-put-history-body tr[data-history-spread-id='mock-spread-closed-0001'] button[data-history-action='detail']").click();
    await historyDetailResponse;
    await expectText(page.locator("[data-history-detail-row='mock-spread-closed-0001']"), "Closed");
    await expectText(page.locator("[data-history-detail-row='mock-spread-closed-0001']"), "QQQ260619P467000.US");
    const currentRecoveryDetails = page.locator("#spreads-body details[data-recovery-details]").first();
    const recoveryEligibilityResponse = page.waitForResponse((response) => response.request().method() === "GET" && response.url().includes("/recover-close/eligibility"));
    await currentRecoveryDetails.locator("summary").click();
    await recoveryEligibilityResponse;
    if (bullPutReadRequests.filter((request) => request.pathname.endsWith("/recover-close/eligibility")).length !== 1) {
      throw new Error("Recovery eligibility must load only after the corresponding current spread is expanded.");
    }
    await expectText(page.locator("#strategy-runtime-strip"), "Entry Status");
    await selectStrategyTab(page, "zero-dte");
    await expectText(page.locator("#strategy-section"), "Lottery Strategy");
    await expectText(page.locator("#zero-dte-lottery-strip"), "Preview Only");
    await selectStrategyTab(page, "experiments");
    await expectText(page.locator("#strategy-experiment-strip"), "Active Proposals");
    await selectStrategyTab(page, "covered-call");
    await expectText(page.locator("#covered-call-activity-card"), "MSFT covered call lifecycle");
    await page.locator("#covered-call-activity-card [data-covered-call-action='reconcile-lifecycle']").click();
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Covered-call lifecycle refreshed read-only"),
    );
    await selectWorkspace(page, "macro");
    await expectText(page.locator("#macro-section"), "Risk Proxies");
    await expectText(page.locator("#macro-section"), "QQQ / SPY Put Check");
    await expectText(page.locator("#macro-section"), "Stored Opening Follow-through");
    await expectText(page.locator("#market-events-card"), "UNH earnings window");
    await selectWorkspace(page, "strategy");
    await selectStrategyTab(page, "bull-put");
    await expectText(page.locator("#spread-summary-strip"), "Active Spreads");
    await expectText(page.locator("#spread-summary-strip"), "Close order canceled / manual action needed");
    await expectText(page.locator("#spreads-body"), "MANUAL ACTION NEEDED");
    await expectText(page.locator("#spreads-body"), "Review close workflow before leaving unattended.");
    lifecycleWarningText = await page.locator("#spreads-body").innerText();
    await selectStrategyTab(page, "zero-dte");
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
    await selectWorkspace(page, "macro");
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

    await selectWorkspace(page, "strategy");
    await selectStrategyTab(page, "bull-put");
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

    await selectWorkspace(page, "portfolio");
    await expectText(page.locator("#portfolio-section"), "Holdings Overview");
    await page.click("#open-execution-drawer");
    await page.waitForSelector("#execution-drawer[open]");
    if (!(await page.locator("#execution-drawer").evaluate((node) => node.contains(document.activeElement)))) {
      throw new Error("Opening the execution drawer must move focus inside the modal.");
    }
    const ticketTab = page.locator("button[data-execution-tab='ticket']");
    await ticketTab.focus();
    await ticketTab.press("ArrowRight");
    if (!(await page.locator("button[data-execution-tab='orders']").evaluate((node) => node === document.activeElement))) {
      throw new Error("Execution tab ArrowRight must activate and focus the next tab.");
    }
    await page.keyboard.press("Escape");
    await page.waitForSelector("#execution-drawer", { state: "hidden" });
    if (!(await page.locator("#open-execution-drawer").evaluate((node) => node === document.activeElement))) {
      throw new Error("Closing the execution drawer with Escape must restore trigger focus.");
    }

    await openExecutionDrawer(page, "orders");
    await clickFilledOrderManage(page);
    await selectExecutionTab(page, "detail");
    await expectText(page.locator("#selected-order-execution"), "Filled Qty");
    await expectText(page.locator("#selected-order-execution"), "388.65");

    await selectExecutionTab(page, "journal");
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

    await selectExecutionTab(page, "ticket");
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

    await selectExecutionTab(page, "detail");
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

    await page.keyboard.press("Escape");
    await page.waitForSelector("#execution-drawer", { state: "hidden" });
    await page.setViewportSize({ width: 760, height: 1000 });
    await page.waitForFunction(() => document.getElementById("submit-order")?.disabled === true);
    await openExecutionDrawer(page, "ticket");
    if ((await page.locator("#execution-drawer").getAttribute("data-mobile-readonly")) !== "true") {
      throw new Error("760px execution drawer must expose its read-only posture.");
    }
    for (const formId of ["order-ticket-form", "replace-order-form", "journal-entry-form"]) {
      const form = page.locator(`#${formId}`);
      const posture = await form.evaluate((node) => ({
        inert: node.inert === true && node.hasAttribute("inert"),
        ariaDisabled: node.getAttribute("aria-disabled"),
        focusBlocked: (() => {
          const control = node.querySelector("input, select, textarea, button");
          control?.focus();
          return !node.contains(document.activeElement);
        })(),
      }));
      if (!posture.inert || posture.ariaDisabled !== "true" || !posture.focusBlocked) {
        throw new Error(`Mobile execution form #${formId} must be inert, aria-disabled, and unfocusable.`);
      }
    }
    const enabledMobileMutations = await page.locator("[data-broker-mutation='true']:not(:disabled)").count();
    if (enabledMobileMutations !== 0) {
      throw new Error(`Mobile viewport left ${enabledMobileMutations} broker mutation control(s) enabled.`);
    }
    if (!(await page.locator("#desktop-trading-notice").isVisible())) {
      throw new Error("Mobile viewport must show the desktop-required trading notice.");
    }
    await selectExecutionTab(page, "detail");
    await expectText(page.locator("#selected-order-card"), "MOCK.US");
    if (!(await page.locator("#replace-order-form").evaluate((node) => node.inert === true))) {
      throw new Error("Mobile Order Detail must keep the replacement form inert.");
    }
    await selectExecutionTab(page, "journal");
    if (!(await page.locator("#journal-entry-form").evaluate((node) => node.inert === true))) {
      throw new Error("Mobile Journal view must keep the journal form inert.");
    }
    await page.keyboard.press("Escape");
    await page.waitForSelector("#execution-drawer", { state: "hidden" });
    await page.setViewportSize({ width: 1440, height: 1200 });
    await page.waitForFunction(() => document.getElementById("submit-order")?.disabled === false);
    await selectWorkspace(page, "research");
    await page.locator("[data-research-view='table']").click();
    await page.waitForFunction(
      () => !document.getElementById("research-table-view")?.hidden && document.getElementById("research-chart-view")?.hidden,
    );
    if (!(await page.locator("#research-chart-view").isHidden())) {
      throw new Error("Screener view must hide the research chart view.");
    }

    const screenshots = await captureResponsiveScreenshots(page, screenshotPath);

    const summary = await page.evaluate(() => {
      const spreadRow = document.querySelector("#spreads-body tr");
      return {
        selectedOrderText: document.getElementById("selected-order-card")?.textContent ?? "",
        statusBanner: document.getElementById("status-banner")?.textContent ?? "",
        spreadTable: spreadRow?.textContent ?? "",
        journalText: document.getElementById("selected-order-journal")?.textContent ?? "",
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
            drawerReadonly: true,
            executionFormsInert: true,
          },
          research: {
            filteredSelectionSynchronized: true,
            resetRestoredRows: true,
          },
          responsive: {
            sidebar1024Width: 64,
            bottomNavigation760SpansViewport: true,
          },
          journal: {
            rendered: journalPanelText.includes("Browser regression review"),
            latestPanel: journalPanelText,
          },
          screenshot: screenshots["1440"],
          screenshots,
        },
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}

async function selectWorkspace(page, workspace) {
  await page.locator(`[data-workspace-option='${workspace}']`).click();
  await page.waitForFunction(
    (value) => document.body.dataset.workspace === value,
    workspace,
  );
  const panel = page.locator(`[data-workspace-panel='${workspace}']`);
  if (!(await panel.isVisible())) {
    throw new Error(`Workspace '${workspace}' did not reveal its panel.`);
  }
  if ((await page.locator("[data-workspace-panel]:visible").count()) !== 1) {
    throw new Error(`Workspace '${workspace}' did not keep the workspace panels mutually exclusive.`);
  }
}

async function selectStrategyTab(page, tab) {
  await page.locator(`button[data-strategy-tab='${tab}']`).click();
  if ((await page.locator(`button[data-strategy-tab='${tab}']`).getAttribute("aria-selected")) !== "true") {
    throw new Error(`Strategy tab '${tab}' did not become selected.`);
  }
}

async function openExecutionDrawer(page, tab = "ticket") {
  if (!(await page.locator("#execution-drawer").evaluate((node) => node.open))) {
    await page.click("#open-execution-drawer");
    await page.waitForSelector("#execution-drawer[open]");
  }
  await selectExecutionTab(page, tab);
  if ((await page.locator("#open-execution-drawer").getAttribute("aria-expanded")) !== "true") {
    throw new Error("Execution drawer trigger must expose aria-expanded=true while open.");
  }
}

async function selectExecutionTab(page, tab) {
  await page.locator(`button[data-execution-tab='${tab}']`).click();
  await page.waitForFunction(
    (value) => document.getElementById("execution-drawer")?.dataset.executionTab === value,
    tab,
  );
  if ((await page.locator(`button[data-execution-tab='${tab}']`).getAttribute("aria-selected")) !== "true") {
    throw new Error(`Execution tab '${tab}' did not become selected.`);
  }
}

async function readTicketDefaults(page) {
  return {
    side: await page.locator("#order-side").inputValue(),
    quantity: await page.locator("#order-quantity").inputValue(),
    type: await page.locator("#order-type").inputValue(),
    limitPrice: await page.locator("#order-limit-price").inputValue(),
    stopPrice: await page.locator("#order-stop-price").inputValue(),
  };
}

async function assertTicketDefaultsUnchanged(page, before) {
  const after = await readTicketDefaults(page);
  if (JSON.stringify(after) !== JSON.stringify(before)) {
    throw new Error(`Research order preparation changed fields beyond symbol: ${JSON.stringify({ before, after })}`);
  }
}

async function captureResponsiveScreenshots(page, screenshotPath) {
  fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
  const extension = path.extname(screenshotPath) || ".png";
  const base = screenshotPath.slice(0, screenshotPath.length - extension.length);
  const targets = [
    { label: "1440", width: 1440, height: 1200, output: screenshotPath },
    { label: "1024", width: 1024, height: 1000, output: `${base}-1024${extension}` },
    { label: "760", width: 760, height: 1000, output: `${base}-760${extension}` },
  ];
  const outputs = {};
  for (const target of targets) {
    await page.setViewportSize({ width: target.width, height: target.height });
    await assertResponsiveShell(page, target.label);
    await page.screenshot({ path: target.output, fullPage: true });
    outputs[target.label] = target.output;
  }
  return outputs;
}

async function assertResponsiveShell(page, label) {
  if (label === "1024") {
    await page.waitForFunction(
      () => Math.abs((document.getElementById("workspace-sidebar")?.getBoundingClientRect().width || 0) - 64) <= 1,
    );
    await page.waitForFunction(
      () => Math.abs(parseFloat(getComputedStyle(document.getElementById("workspace-sidebar")).width) - 64) < 0.01,
    );
    const sidebar = await page.locator("#workspace-sidebar").evaluate((node) => ({
      computedWidth: getComputedStyle(node).width,
      renderedWidth: node.getBoundingClientRect().width,
    }));
    if (sidebar.computedWidth !== "64px" || Math.abs(sidebar.renderedWidth - 64) > 1) {
      throw new Error(`1024px layout must render a 64px sidebar: ${JSON.stringify(sidebar)}`);
    }
  }
  if (label === "760") {
    await page.waitForFunction(() => {
      const sidebar = document.getElementById("workspace-sidebar")?.getBoundingClientRect();
      const nav = document.getElementById("workspace-nav")?.getBoundingClientRect();
      return sidebar && nav &&
        Math.abs(sidebar.left) <= 1 && Math.abs(sidebar.right - window.innerWidth) <= 1 &&
        Math.abs(nav.left) <= 1 && Math.abs(nav.right - window.innerWidth) <= 1;
    });
    const geometry = await page.evaluate(() => {
      const viewportWidth = window.innerWidth;
      const rectFor = (selector) => {
        const rect = document.querySelector(selector)?.getBoundingClientRect();
        return rect ? { left: rect.left, right: rect.right, width: rect.width } : null;
      };
      return {
        viewportWidth,
        sidebar: rectFor("#workspace-sidebar"),
        nav: rectFor("#workspace-nav"),
      };
    });
    for (const [name, rect] of [["sidebar", geometry.sidebar], ["navigation", geometry.nav]]) {
      if (
        !rect ||
        Math.abs(rect.left) > 1 ||
        Math.abs(rect.right - geometry.viewportWidth) > 1 ||
        Math.abs(rect.width - geometry.viewportWidth) > 1
      ) {
        throw new Error(`760px bottom ${name} must span the viewport: ${JSON.stringify(geometry)}`);
      }
    }
  }
}

async function runPostureScenarioAssertions(page, scenario) {
  if (scenario === "unknown-intent") {
    await openExecutionDrawer(page, "ticket");
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
    await page.keyboard.press("Escape");
    await page.waitForSelector("#execution-drawer", { state: "hidden" });
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#status-banner"), "unresolved trading intent");
    if ((await page.locator("[data-broker-mutation='true']:not(:disabled)").count()) !== 0) {
      throw new Error("Reloaded unknown intent must keep broker-writing actions locked.");
    }
    return { brokerActionsDisabled: true, idempotencyKeyRetained: true, reloadStillBlocked: true };
  }

  if (scenario === "auxiliary-data-failure") {
    await selectWorkspace(page, "macro");
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
    await openExecutionDrawer(page, "orders");
    const before = await page.locator("#orders-body").innerText();
    await page.keyboard.press("Escape");
    await page.waitForSelector("#execution-drawer", { state: "hidden" });
    await page.click("#refresh-dashboard");
    await expectText(page.locator("#status-banner"), "Core account data is stale: Orders");
    await openExecutionDrawer(page, "orders");
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
    await selectWorkspace(page, "strategy");
    await selectStrategyTab(page, "covered-call");
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
    await selectWorkspace(page, "operations");
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
  const location = {
    "degraded-broker": ["operations"],
    "paused-mandate": ["operations"],
    "advisor-pending-record": ["strategy", "experiments"],
    "manual-action-required": ["strategy", "bull-put"],
    "scheduler-backoff": ["operations"],
    "recover-eligible": ["strategy", "bull-put"],
    "recover-rejected": ["strategy", "bull-put"],
    "recover-already-working": ["strategy", "bull-put"],
    "ledger-mismatch": ["operations"],
    "repair-available": ["operations"],
    "quote-cache-fallback": ["operations"],
    "scheduler-lease-active": ["operations"],
  }[scenario];
  await selectWorkspace(page, location[0]);
  if (location[1]) {
    await selectStrategyTab(page, location[1]);
  }
  if (scenario.startsWith("recover-")) {
    const eligibility = page.waitForResponse((response) =>
      response.request().method() === "GET" && response.url().includes("/recover-close/eligibility"),
    );
    await page.locator("#spreads-body details[data-recovery-details] > summary").first().click();
    await eligibility;
  }
  const postureLocator = location[0] === "operations"
    ? page.locator("#account-section")
    : page.locator("#strategy-section");
  await expectTextInsensitive(postureLocator, expectedText);
  return { expectedText, matched: true };
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

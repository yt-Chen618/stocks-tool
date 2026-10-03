const path = require("node:path");

const {
  createRequestObserver,
  expectText,
  isBrokerMutationPath,
  launchBrowserPage,
  resolveBrowserExecutable,
  sleep,
  waitFor,
} = require("./browser_test_helpers");

const PRIMARY_ACCOUNT = "LBPT10087357";
const ALT_ACCOUNT = "LBPT10087357-ALT";
const SCREEN_NAME = "QQQ 中文趋势屏幕";
const CASE_TITLE = "MOCK 1Y 研究档案";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function cloneFixtureAccountFields(value, fromAccount, toAccount) {
  if (Array.isArray(value)) {
    return value.map((item) => cloneFixtureAccountFields(item, fromAccount, toAccount));
  }
  if (!value || typeof value !== "object") return value;
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

function replaceAccountInUrl(rawUrl, accountId) {
  const url = new URL(rawUrl);
  if (url.searchParams.has("external_account_id")) {
    url.searchParams.set("external_account_id", accountId);
  }
  return url.toString();
}

function addLeveragedPortfolioFixture(pathname, payload) {
  const clone = payload && typeof payload === "object" ? payload : payload;
  if (pathname === "/portfolio/analytics" && Array.isArray(clone?.allocation) && !clone.allocation.some((item) => item?.symbol === "LEVERAGED2X.US")) {
    const nav = Number(clone.latest?.net_liquidation || 0);
    clone.allocation.push({
      symbol: "LEVERAGED2X.US",
      asset_type: "etf",
      market_value: String(nav * 2),
      unrealized_pnl: "0",
      quantity: "200",
      absolute_market_value: String(nav * 2),
      weight_of_net_liquidation: "2.0",
      position_ids: ["mock-leveraged-position-200pct"],
    });
    clone.allocation.push({
      symbol: "UNKNOWN_HOLDING.US",
      asset_type: null,
      market_value: null,
      unrealized_pnl: null,
      quantity: null,
      absolute_market_value: null,
      weight_of_net_liquidation: null,
      position_ids: ["mock-unknown-holding"],
    });
  }
  if (pathname === "/portfolio/risk" && Array.isArray(clone?.concentrations) && !clone.concentrations.some((item) => item?.symbol === "LEVERAGED2X.US")) {
    clone.concentrations.push({
      symbol: "LEVERAGED2X.US",
      market_value: clone.balance?.net_liquidation ? String(Number(clone.balance.net_liquidation) * 2) : "0",
      absolute_market_value: clone.balance?.net_liquidation ? String(Number(clone.balance.net_liquidation) * 2) : "0",
      weight_of_net_liquidation: "2.0",
      risk_level: "unknown",
      source_position_ids: ["mock-leveraged-position-200pct"],
    });
    clone.concentrations.push({
      symbol: "UNKNOWN_HOLDING.US",
      market_value: null,
      absolute_market_value: null,
      weight_of_net_liquidation: null,
      risk_level: "unknown",
      source_position_ids: ["mock-unknown-holding"],
    });
  }
  return clone;
}

function annotateAlternateFixture(pathname, payload) {
  const clone = addLeveragedPortfolioFixture(pathname, cloneFixtureAccountFields(payload, PRIMARY_ACCOUNT, ALT_ACCOUNT));
  if (pathname === "/portfolio/analytics" && clone?.latest) {
    clone.latest.provenance = "mock_demo_alt";
    clone.data_quality ||= {};
    clone.data_quality.warnings = [...(clone.data_quality.warnings || []), "account_race_alt_fixture"];
  }
  if (pathname === "/portfolio/risk" && clone?.balance) {
    clone.balance.provenance = "mock_demo_alt";
  }
  if (pathname === "/research/timeline") {
    for (const item of [...(clone?.events || []), ...(clone?.items || [])]) {
      if (item && typeof item.title === "string") item.title = `[ALT] ${item.title}`;
      if (item?.payload && typeof item.payload.title === "string") item.payload.title = `[ALT] ${item.payload.title}`;
    }
  }
  if (pathname === "/strategies/advisor/audit") {
    for (const item of clone?.runs || []) {
      if (item?.advisor_run) item.advisor_run.model = "MockAltAdvisor";
    }
  }
  if (pathname === "/research/screens") {
    for (const item of clone?.items || []) {
      if (typeof item.name === "string") item.name = `ALT · ${item.name}`;
    }
  }
  if (pathname === "/research/cases") {
    for (const item of clone?.items || []) {
      if (typeof item.title === "string") item.title = `ALT · ${item.title}`;
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

async function pageJson(page, url, options = {}) {
  return page.evaluate(async ({ requestUrl, requestOptions }) => {
    const response = await fetch(requestUrl, requestOptions);
    let body = null;
    try {
      body = await response.json();
    } catch (_error) {
      body = null;
    }
    return { status: response.status, ok: response.ok, body };
  }, { requestUrl: url, requestOptions: options });
}

async function textOf(page, selector) {
  return page.locator(selector).innerText();
}

async function waitForAccount(page, accountId, timeoutMs) {
  await waitFor(
    async () => (await page.locator("#topbar-account-select").inputValue()) === accountId,
    timeoutMs,
    `topbar account ${accountId}`,
  );
  await waitFor(
    async () => (await page.locator("#account-select").inputValue()) === accountId,
    timeoutMs,
    `source account ${accountId}`,
  );
}

async function selectAccount(page, accountId, timeoutMs) {
  await page.selectOption("#topbar-account-select", accountId);
  await waitForAccount(page, accountId, timeoutMs);
  await sleep(250);
}

async function waitWorkspace(page, workspace, timeoutMs) {
  await waitFor(
    async () => (await page.locator("body").getAttribute("data-workspace")) === workspace,
    timeoutMs,
    `workspace ${workspace}`,
  );
}

async function openDetails(page, selector, timeoutMs) {
  const details = page.locator(selector);
  await waitFor(() => details.count().then((count) => count === 1), timeoutMs, `details ${selector}`);
  if (!(await details.evaluate((element) => Boolean(element.open)))) {
    await details.locator("summary").click();
  }
  await waitFor(() => details.evaluate((element) => Boolean(element.open)), timeoutMs, `open details ${selector}`);
}

async function assertDesktopChartExplanationLayout(page, timeoutMs) {
  await page.setViewportSize({ width: 1440, height: 1200 });
  await waitFor(async () => {
    const visible = await page.evaluate(() => ({
      chart: document.getElementById("research-chart-container")?.getBoundingClientRect(),
      explanation: document.getElementById("research-explanation-panel")?.getBoundingClientRect(),
      chartVisible: Boolean(document.getElementById("research-chart-container") && !document.getElementById("research-chart-container").closest("[hidden]")),
      explanationVisible: Boolean(document.getElementById("research-explanation-panel") && !document.getElementById("research-explanation-panel").hidden),
    }));
    if (!visible.chart || !visible.explanation || !visible.chartVisible || !visible.explanationVisible) return false;
    const verticalOverlap = visible.chart.bottom > visible.explanation.top && visible.explanation.bottom > visible.chart.top;
    return visible.chart.left < visible.explanation.left && visible.chart.right <= visible.explanation.left + 1 && verticalOverlap;
  }, timeoutMs, "desktop chart and explanation side-by-side");
  return page.evaluate(() => {
    const chart = document.getElementById("research-chart-container").getBoundingClientRect();
    const explanation = document.getElementById("research-explanation-panel").getBoundingClientRect();
    return {
      chart: { left: chart.left, right: chart.right, top: chart.top, bottom: chart.bottom },
      explanation: { left: explanation.left, right: explanation.right, top: explanation.top, bottom: explanation.bottom },
      viewport_width: window.innerWidth,
    };
  });
}

async function assertResponsive(page, width, timeoutMs) {
  await page.setViewportSize({ width, height: width <= 780 ? 1000 : 1200 });
  await page.waitForFunction((expectedWidth) => window.innerWidth === expectedWidth, width, { timeout: timeoutMs });
  await waitFor(
    async () => page.evaluate(() => {
      const documentWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0);
      return documentWidth <= window.innerWidth + 1;
    }),
    timeoutMs,
    `no horizontal overflow at ${width}px`,
  );
  const geometry = await page.evaluate(() => {
    const topbar = document.querySelector(".workspace-topbar")?.getBoundingClientRect();
    const labels = Array.from(document.querySelectorAll("#workspace-sidebar [data-workspace-option]"));
    const mobileMutationState = Array.from(document.querySelectorAll("[data-broker-mutation='true']"))
      .map((node) => ({ disabled: node.disabled, ariaDisabled: node.getAttribute("aria-disabled") }));
    const chineseLabels = labels.map((node) => ({
      aria: node.getAttribute("aria-label"),
      after: getComputedStyle(node.querySelector(".sidebar-label"), "::after").content,
    }));
    return {
      documentWidth: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
      viewportWidth: window.innerWidth,
      topbarHeight: topbar?.height || 0,
      chineseLabels,
      mobileMutationState,
    };
  });
  assert(geometry.topbarHeight > 0 && geometry.topbarHeight <= (width <= 780 ? 240 : 170), `Topbar height is unreasonable at ${width}px: ${geometry.topbarHeight}`);
  if (width <= 780) {
    await waitFor(
      async () => page.evaluate(() => {
        const controls = Array.from(document.querySelectorAll("[data-broker-mutation='true']"));
        const mobile = window.matchMedia?.("(max-width: 780px)")?.matches ?? window.innerWidth <= 780;
        return mobile && controls.length > 0 && controls.every((node) => node.disabled || node.getAttribute("aria-disabled") === "true");
      }),
      timeoutMs,
      `mobile broker-write safety state at ${width}px`,
    );
    assert(geometry.mobileMutationState.length > 0, "No broker-write controls were rendered for the mobile safety check.");
    assert(geometry.mobileMutationState.every((item) => item.disabled || item.ariaDisabled === "true"), `Broker-write control was enabled at ${width}px: ${JSON.stringify(geometry.mobileMutationState)}`);
    const expectedLabels = ["研究", "策略", "市场", "持仓", "运行与安全"];
    assert(expectedLabels.every((label) => geometry.chineseLabels.some((item) => String(item.after).includes(label) || item.aria === label)), `Chinese mobile labels are not readable: ${JSON.stringify(geometry.chineseLabels)}`);
  }
  return geometry;
}

async function captureWorkspace(page, workspace, width, outputDirectory, timeoutMs) {
  const tab = page.locator(`[data-workspace-option="${workspace}"]`);
  await tab.click();
  await waitWorkspace(page, workspace, timeoutMs);
  await assertResponsive(page, width, timeoutMs);
  const file = path.join(outputDirectory, `${workspace}-${width}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

async function main() {
  const [, , baseUrl, outputDirectory, playwrightCorePath, timeoutArg = "30000"] = process.argv;
  if (!baseUrl || !outputDirectory || !playwrightCorePath) {
    throw new Error("Usage: node workbench_feature_browser_flow.js <baseUrl> <outputDirectory> <playwrightCorePath> [timeoutMs]");
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
  const observer = createRequestObserver(page);
  const routeAudit = [];
  let activeAccount = PRIMARY_ACCOUNT;
  let delayedRead = null;
  let marketSessionPagingEnabled = false;
  let phase = "browser-flow";
  let backtestFixtureEnabled = false;
  let backtestRequests = [];
  let syntheticBacktestCounter = 0;
  const syntheticBacktestRuns = [
    {
      id: "mock-validation-freeze-0001",
      status: "succeeded",
      strategy_id: "bull_put",
      dataset_id: "mock-options-history",
      start_date: "2024-01-01",
      end_date: "2024-12-31",
      period_segment: "validation",
      run_manifest: { period_segment: "validation", data_hash: "mock-validation-hash" },
      coverage: { start: "2024-01-01", end: "2024-12-31", bars: 252 },
      metrics: { total_return_pct: 4.2, max_drawdown_pct: -2.1, net_pnl: 4200, fees: 100, trade_count: 4 },
      result: { equity_curve: [] },
    },
  ];

  function armDelayedRead(pathname, symbol = null) {
    let resolve;
    const promise = new Promise((resolver) => { resolve = resolver; });
    delayedRead = { pathname, symbol, promise, resolve, hitCount: 0, released: false, outcome: null };
  }

  function releaseDelayedRead(outcome = "error") {
    if (!delayedRead || delayedRead.released) return;
    delayedRead.released = true;
    delayedRead.outcome = outcome;
    delayedRead.resolve(outcome);
  }

  function requestAuditSnapshot() {
    const allNonGet = observer.requests.filter((item) => item.method !== "GET" && item.method !== "HEAD");
    const localWrites = allNonGet.filter((item) => !isBrokerMutationPath(item.pathname, item.search)).map((item) => ({ method: item.method, path: item.path }));
    const paperModeQueryViolations = observer.requests
      .filter((item) => item.method === "GET" && ["/executions/paged", "/journals/paged"].includes(item.pathname))
      .filter((item) => new URLSearchParams(item.search || "").get("mode") !== "paper")
      .map((item) => item.path);
    return {
      total_requests: observer.requests.length,
      unique_read_paths: Array.from(new Set(observer.requests.filter((item) => item.method === "GET").map((item) => item.path))).sort(),
      non_get_requests: allNonGet,
      local_research_or_blocked_writes: localWrites,
      broker_mutations: observer.mutationRequests,
      paper_mode_query_violations: paperModeQueryViolations,
      delayed_reads: routeAudit.filter((item) => item.pathname === "/portfolio/analytics" || item.pathname === "/strategies/advisor/audit" || item.pathname === "/research/timeline" || item.pathname === "/research/screens" || item.pathname === "/backtests" || item.pathname === "/market-session-comparisons" || item.pathname === "/market-session-comparisons/latest"),
    };
  }

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const requestAccount = url.searchParams.get("external_account_id");
    if (requestAccount) activeAccount = requestAccount;
    routeAudit.push({ method, pathname: url.pathname, search: url.search, account: requestAccount || activeAccount, at: Date.now() });

    const isGet = method === "GET" || method === "HEAD";
    const effectiveAccount = requestAccount || activeAccount;
    if (isGet && delayedRead && !delayedRead.released && delayedRead.pathname === url.pathname && effectiveAccount === PRIMARY_ACCOUNT && (!delayedRead.symbol || url.searchParams.get("symbol") === delayedRead.symbol)) {
      delayedRead.hitCount += 1;
      const outcome = await delayedRead.promise;
      if (outcome === "error") {
        await fulfillJson(route, { detail: "Late primary account fixture failure." }, 503);
        return;
      }
    }

    if (url.pathname === "/broker-accounts" && method === "GET") {
      const response = await route.fetch();
      const accounts = await response.json();
      if (accounts[0]) {
        accounts.push({
          ...accounts[0],
          id: "mock-account-alt",
          external_account_id: ALT_ACCOUNT,
          display_name: "Longbridge Paper Alt",
        });
      }
      await fulfillJson(route, accounts, response.status());
      return;
    }

    if (backtestFixtureEnabled && url.pathname === "/backtests/datasets" && method === "GET") {
      await fulfillJson(route, [{
        id: "mock-options-history",
        name: "Mock options history",
        status: "validated",
        license: "local-fixture",
        coverage: { start: "2020-01-01", end: "2026-09-30" },
        data_hash: "mock-options-history-hash",
      }]);
      return;
    }

    if (backtestFixtureEnabled && url.pathname === "/backtests" && method === "GET") {
      await fulfillJson(route, syntheticBacktestRuns.map((run) => JSON.parse(JSON.stringify(run))));
      return;
    }

    if (backtestFixtureEnabled && url.pathname === "/backtests" && method === "POST") {
      const requestPayload = request.postDataJSON() || {};
      backtestRequests.push(JSON.parse(JSON.stringify(requestPayload)));
      const run = {
        id: `mock-backtest-queued-${++syntheticBacktestCounter}`,
        status: "queued",
        strategy_id: requestPayload.strategy,
        dataset_id: requestPayload.dataset_id,
        start_date: requestPayload.start_date,
        end_date: requestPayload.end_date,
        period_segment: requestPayload.period_segment,
        freeze_source_run_id: requestPayload.freeze_source_run_id,
        fee_model: requestPayload.fee_model,
        slippage_model: requestPayload.slippage_model,
        initial_stock_lots: requestPayload.initial_stock_lots,
        run_manifest: {
          period_segment: requestPayload.period_segment,
          freeze_source_run_id: requestPayload.freeze_source_run_id,
          fee_model: requestPayload.fee_model,
          slippage_model: requestPayload.slippage_model,
          initial_stock_lots: requestPayload.initial_stock_lots,
        },
        coverage: { start: requestPayload.start_date, end: requestPayload.end_date, bars: 0 },
        metrics: {},
        result: { equity_curve: [] },
      };
      syntheticBacktestRuns.unshift(run);
      await fulfillJson(route, { run }, 201);
      return;
    }

    if (backtestFixtureEnabled && /^\/backtests\/[^/]+\/(start|cancel)$/.test(url.pathname) && method === "POST") {
      const [, runId, action] = url.pathname.match(/^\/backtests\/([^/]+)\/(start|cancel)$/) || [];
      const run = syntheticBacktestRuns.find((candidate) => candidate.id === runId);
      if (!run) {
        await fulfillJson(route, { detail: "Mock backtest run not found." }, 404);
        return;
      }
      if (action === "start") run.status = "running";
      if (action === "cancel") run.status = "cancelled";
      await fulfillJson(route, JSON.parse(JSON.stringify(run)));
      return;
    }

    if (backtestFixtureEnabled && /^\/backtests\/[^/]+$/.test(url.pathname) && method === "GET") {
      const runId = decodeURIComponent(url.pathname.split("/").pop());
      const run = syntheticBacktestRuns.find((candidate) => candidate.id === runId);
      if (!run) {
        await fulfillJson(route, { detail: "Mock backtest run not found." }, 404);
        return;
      }
      await fulfillJson(route, JSON.parse(JSON.stringify(run)));
      return;
    }

    if (isGet && requestAccount === ALT_ACCOUNT) {
      const forwardedUrl = new URL(replaceAccountInUrl(request.url(), PRIMARY_ACCOUNT));
      if (marketSessionPagingEnabled && forwardedUrl.pathname === "/market-session-comparisons") {
        forwardedUrl.searchParams.set("limit", "1");
      }
      const response = await route.fetch({ url: forwardedUrl.toString() });
      const contentType = response.headers()["content-type"] || "";
      if (contentType.includes("application/json")) {
        const payload = await response.json();
        await fulfillJson(route, annotateAlternateFixture(url.pathname, payload), response.status());
      } else {
        await route.fulfill({ response });
      }
      return;
    }

    // The UI intentionally asks for a generous page size. Cap the fixture
    // response to one row only during this gate so the real saved-select and
    // load-more DOM paths exercise the server cursor contract with two actual
    // immutable records.
    if (marketSessionPagingEnabled && isGet && url.pathname === "/market-session-comparisons" && effectiveAccount === PRIMARY_ACCOUNT) {
      const pagedUrl = new URL(request.url());
      pagedUrl.searchParams.set("limit", "1");
      const response = await route.fetch({ url: pagedUrl.toString() });
      await route.fulfill({ response });
      return;
    }

    if (isGet && (url.pathname === "/portfolio/analytics" || url.pathname === "/portfolio/risk")) {
      const response = await route.fetch();
      const contentType = response.headers()["content-type"] || "";
      if (contentType.includes("application/json")) {
        const payload = await response.json();
        await fulfillJson(route, addLeveragedPortfolioFixture(url.pathname, payload), response.status());
      } else {
        await route.fulfill({ response });
      }
      return;
    }

    await route.fallback();
  });

  const screenshots = {};
  const accountRace = [];
  let screenId = null;
  let caseId = null;
  let portfolioPayload = null;
  let riskPayload = null;
  let desktopResearchLayout = null;
  let marketSessionEvidence = null;

  try {
    await page.goto(`${baseUrl}/`, { waitUntil: "domcontentloaded" });
    await expectText(page.locator("#research-table-body"), "QQQ.US", timeoutMs);
    await waitForAccount(page, PRIMARY_ACCOUNT, timeoutMs);
    assert(await page.locator("#topbar-mode-context").innerText() === "模拟交易 / Paper", "Topbar did not show the paper/simulated mode.");
    assert(await page.locator("#topbar-data-time").innerText() !== "Waiting", "Topbar data time never became readable.");

    // P1.2: QQQ -> chart/explanation -> durable screen -> reload -> changed symbol/range -> immutable case.
    await page.locator("#research-table-body [data-research-select='QQQ.US']").click();
    await page.locator("#research-chart-tab").click();
    await expectText(page.locator("#research-chart-summary"), "QQQ.US", timeoutMs);
    await expectText(page.locator("#research-explanation-title"), "QQQ.US", timeoutMs);
    await waitFor(async () => (await page.locator("#research-chart-container svg, #research-chart-container canvas").count()) > 0, timeoutMs, "QQQ chart rendering");
    const qqqExplanation = await textOf(page, "#research-explanation-summary");
    assert(/证据|报价|以下是演示|均价|走势/.test(qqqExplanation), `QQQ explanation was not plain-language: ${qqqExplanation}`);
    desktopResearchLayout = await assertDesktopChartExplanationLayout(page, timeoutMs);
    await openDetails(page, "details.research-case-controls", timeoutMs);

    await page.locator("#research-screen-name").fill(SCREEN_NAME);
    await page.locator("#research-save-screen").click();
    await expectText(page.locator("#research-case-status"), "筛选配置已保存", timeoutMs);
    await waitFor(async () => await page.locator("#research-screen-select option").count() > 1, timeoutMs, "saved screen option");
    screenId = await page.locator("#research-screen-select option").nth(1).getAttribute("value");
    assert(screenId, "Saved screen did not expose a durable id.");

    await page.reload({ waitUntil: "domcontentloaded" });
    await expectText(page.locator("#research-table-body"), "QQQ.US", timeoutMs);
    await waitForAccount(page, PRIMARY_ACCOUNT, timeoutMs);
    await openDetails(page, "details.research-case-controls", timeoutMs);
    await waitFor(async () => await page.locator("#research-screen-select option").count() > 1, timeoutMs, "saved screen after reload");
    await page.locator("#research-screen-select").selectOption(screenId);
    await page.locator("#research-load-screen").click();
    await expectText(page.locator("#research-case-status"), "已加载筛选", timeoutMs);
    assert(await page.locator("#research-table-body [data-research-select='QQQ.US']").getAttribute("aria-selected") === "true", "Reloaded screen did not restore QQQ selection.");

    await page.locator("#research-table-tab").click();
    await page.locator("#research-table-body [data-research-select='MOCK.US']").click();
    await page.locator("#research-chart-tab").click();
    await page.locator("[data-chart-range='1y']").click();
    await expectText(page.locator("#research-chart-summary"), "MOCK.US", timeoutMs);
    await expectText(page.locator("#research-chart-summary"), "252", timeoutMs);
    await page.locator("#research-case-title-input").fill(CASE_TITLE);
    await page.locator("#research-case-thesis-input").fill("验证换标的和一年窗口后的证据是否仍能追溯。");
    await page.locator("#research-save-case").click();
    await expectText(page.locator("#research-case-status"), "研究档案已保存", timeoutMs);
    await waitFor(async () => await page.locator("#research-case-select option").count() > 1, timeoutMs, "saved immutable case option");
    caseId = await page.locator("#research-case-select option").nth(1).getAttribute("value");
    assert(caseId, "Saved case did not expose a durable id.");
    await page.locator("#research-case-select").selectOption(caseId);
    await page.locator("#research-load-case").click();
    await expectText(page.locator("#research-case-status"), "不可变研究档案", timeoutMs);
    await expectText(page.locator("#research-explanation-title"), "MOCK.US", timeoutMs);
    const caseResponse = await pageJson(page, `/research/cases/${encodeURIComponent(caseId)}?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper`);
    assert(caseResponse.ok && caseResponse.body.primary_symbol === "MOCK.US", `Immutable case detail had the wrong symbol: ${JSON.stringify(caseResponse.body)}`);
    assert(caseResponse.body.configuration?.history_range === "1y", `Immutable case detail did not retain the selected 1Y range: ${JSON.stringify(caseResponse.body.configuration)}`);
    assert(caseResponse.body.data_quality === "mock" && caseResponse.body.source === "mock_demo", "Case detail lost source/data-quality evidence.");
    await page.locator("#research-close-case").click();
    await waitFor(async () => await page.locator("#research-explanation-panel").isVisible(), timeoutMs, "return to live research after immutable case");
    await openDetails(page, "details.research-case-controls", timeoutMs);
    await page.locator("#research-table-tab").click();
    await page.locator("#research-table-body [data-research-select='QQQ.US']").click();
    await page.locator("#research-chart-tab").click();
    await page.locator("[data-chart-range='3m']").click();
    const immutableAfterChange = await pageJson(page, `/research/cases/${encodeURIComponent(caseId)}?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper`);
    assert(immutableAfterChange.body.primary_symbol === "MOCK.US" && immutableAfterChange.body.configuration?.history_range === "1y", "Changing the live research context mutated the immutable case.");

    const compareInput = page.locator("#research-compare-symbols");
    assert(await compareInput.isVisible(), `Candidate comparison input was hidden after the research case flow: ${JSON.stringify(await page.evaluate(() => ({ workspace: document.body.dataset.workspace, researchHidden: document.getElementById("research-section")?.hidden, panelHidden: document.getElementById("research-explanation-panel")?.hidden })))} `);
    await compareInput.fill("QQQ.US, MOCK.US");
    const compareButton = page.locator("#research-compare-button");
    assert(await compareButton.isVisible(), `Candidate comparison button was hidden after the research case flow: ${JSON.stringify(await page.evaluate(() => ({ workspace: document.body.dataset.workspace, researchHidden: document.getElementById("research-section")?.hidden, panelHidden: document.getElementById("research-explanation-panel")?.hidden })))} `);
    await compareButton.click();
    await waitFor(async () => {
      const result = String(await page.locator("#research-compare-result").textContent() || "");
      return (result.includes("QQQ.US") && result.includes("MOCK.US")) || result.includes("不可用") || result.includes("unavailable");
    }, timeoutMs, "candidate comparison result");
    const compareResultText = await textOf(page, "#research-compare-result");
    assert(compareResultText.includes("QQQ.US") && compareResultText.includes("MOCK.US"), `Candidate comparison did not return both current symbols: ${compareResultText}`);
    const evaluateButton = page.locator("#research-evaluate-strategy");
    assert(await evaluateButton.isVisible(), `Strategy evaluation button was hidden after the research case flow: ${JSON.stringify(await page.evaluate(() => ({ workspace: document.body.dataset.workspace, researchHidden: document.getElementById("research-section")?.hidden, panelHidden: document.getElementById("research-explanation-panel")?.hidden })))} `);
    await evaluateButton.click();
    await waitWorkspace(page, "strategy", timeoutMs);
    await expectText(page.locator("#strategy-evaluation-status"), "已从研究带入", timeoutMs);
    assert(await page.locator("#strategy-evaluation-symbol").inputValue() === "QQQ.US", "Strategy handoff did not use the current selected symbol.");
    await page.locator("#strategy-readiness-button").click();
    await expectText(page.locator("#strategy-evaluation-status"), "满足只读评估条件", timeoutMs);

    // P3: correct NAV, explicit unavailable investment return, and backend-provided weights.
    await page.locator("#portfolio-workspace-tab").click();
    await waitWorkspace(page, "portfolio", timeoutMs);
    await waitFor(async () => (await page.locator("#portfolio-equity-chart svg").count()) > 0, timeoutMs, "portfolio NAV curve");
    portfolioPayload = (await pageJson(page, `/portfolio/analytics?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper`)).body;
    riskPayload = (await pageJson(page, `/portfolio/risk?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper`)).body;
    const portfolioFacts = await page.evaluate(() => Object.fromEntries(Array.from(document.querySelectorAll("#portfolio-explanation-facts > div")).map((node) => [node.querySelector("dt")?.textContent, node.querySelector("dd")?.textContent])));
    assert(String(portfolioFacts["最新净清算值"] || "").includes("1,916,739") || String(portfolioFacts["最新净清算值"] || "").includes("1916739"), `Portfolio DOM did not show backend NAV: ${JSON.stringify(portfolioFacts)}`);
    assert(portfolioPayload.change?.investment_return == null && portfolioPayload.change?.investment_return_unavailable?.code === "cash_flow_history_unavailable", "Portfolio backend did not preserve the missing investment-return distinction.");
    const investmentReturnExplanation = String(portfolioFacts["投资收益率"] || "");
    assert(/暂时无法计算投资收益率|投资收益率.*不可用/.test(investmentReturnExplanation), `Portfolio DOM did not provide the Chinese missing-investment-return explanation: ${investmentReturnExplanation}`);
    const portfolioText = await textOf(page, "#portfolio-section");
    assert(/投资收益|investment return/i.test(portfolioText) && /不可用|缺口|unavailable|cash.?flow/i.test(portfolioText), "Portfolio DOM did not explain that investment return is unavailable because cash-flow evidence is missing.");
    for (const allocation of portfolioPayload.allocation || []) {
      const rowText = await page.locator(`#portfolio-analytics-body tr:has-text('${allocation.symbol}')`).innerText();
      if (allocation.weight_of_net_liquidation === null || allocation.weight_of_net_liquidation === undefined) {
        assert(rowText.includes("不可用") || rowText.includes("Unavailable"), `Portfolio unknown holding was treated as a numeric weight: ${rowText}`);
      } else {
        const weight = Number(allocation.weight_of_net_liquidation) * 100;
        assert(rowText.includes(`${weight.toFixed(1)}%`), `Portfolio row ${allocation.symbol} did not use backend weight ${weight.toFixed(1)}%: ${rowText}`);
      }
    }
    const leveragedAllocation = (portfolioPayload.allocation || []).find((item) => item.symbol === "LEVERAGED2X.US");
    assert(leveragedAllocation?.weight_of_net_liquidation === "2.0", `Leveraged 200% fixture was not present in the portfolio allocation: ${JSON.stringify(leveragedAllocation)}`);
    const leveragedRisk = (riskPayload.concentrations || []).find((item) => item.symbol === "LEVERAGED2X.US");
    assert(leveragedRisk?.weight_of_net_liquidation === "2.0", `Leveraged 200% fixture was not present in portfolio risk concentrations: ${JSON.stringify(leveragedRisk)}`);
    const riskText = await textOf(page, "#portfolio-risk-bars");
    assert(riskText.includes("LEVERAGED2X.US") && riskText.includes("200.0%"), `Portfolio risk UI did not preserve the leveraged 200% weight: ${riskText}`);
    await openDetails(page, "#portfolio-raw-snapshot", timeoutMs);
    await expectText(page.locator("#positions-body"), "MOCK.US", timeoutMs);

    // P2.3: market close / after-hours comparison stays separate from the
    // opening-follow-through review.  Exercise the real mock service through
    // the DOM, including saved-record pagination and immutable detail loads.
    marketSessionPagingEnabled = true;
    await page.locator("#macro-workspace-tab").click();
    await waitWorkspace(page, "macro", timeoutMs);
    const marketSessionInput = page.locator("#market-session-comparison-symbol");
    const marketSessionRefresh = page.locator("#market-session-comparison-refresh");
    const marketSessionCapture = page.locator("#market-session-comparison-capture");
    const marketSessionSaved = page.locator("#market-session-comparison-saved-select");
    const marketSessionLoadMore = page.locator("#market-session-comparison-load-more");
    await waitFor(() => marketSessionInput.isVisible(), timeoutMs, "market-session comparison panel");
    await marketSessionInput.fill("QQQ.US");
    await marketSessionRefresh.click();
    await expectText(page.locator("#market-session-comparison-summary"), "500.00 USD", timeoutMs);
    await expectText(page.locator("#market-session-comparison-summary"), "510.00 USD", timeoutMs);
    await expectText(page.locator("#market-session-comparison-summary"), "512.00 USD", timeoutMs);
    const marketQqqExplanation = await textOf(page, "#market-session-comparison-explanation");
    assert(marketQqqExplanation.includes("+2.00%") && marketQqqExplanation.includes("+0.39%"), `Market-session percentages were not rendered: ${marketQqqExplanation}`);
    assert(/中国/.test(marketQqqExplanation) && /美东/.test(marketQqqExplanation) && /16:00/.test(marketQqqExplanation), `Market-session explanation omitted China/ET evidence time: ${marketQqqExplanation}`);
    const qqqBeforeCapture = (await pageJson(page, `/market-session-comparisons/latest?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper&symbol=QQQ.US`)).body;
    assert(qqqBeforeCapture.status === "valid" && qqqBeforeCapture.data_quality === "verified", `QQQ market-session latest was not verified: ${JSON.stringify(qqqBeforeCapture)}`);
    assert(qqqBeforeCapture.baseline_price === "500" && qqqBeforeCapture.regular_close_price === "510" && qqqBeforeCapture.after_hours_price === "512", `QQQ market-session prices did not match the fixture: ${JSON.stringify(qqqBeforeCapture)}`);
    assert(qqqBeforeCapture.pre_to_regular_close_pct === "2.00" && qqqBeforeCapture.regular_close_to_after_hours_pct === "0.39", `QQQ market-session percentages did not match the backend: ${JSON.stringify(qqqBeforeCapture)}`);
    assert(qqqBeforeCapture.target_trading_day === "2026-10-02" && qqqBeforeCapture.baseline_evidence?.trading_date === "2026-10-02" && qqqBeforeCapture.regular_close_evidence?.trading_date === "2026-10-02" && qqqBeforeCapture.post_market_evidence?.trading_date === "2026-10-02", `QQQ market-session evidence did not share the 2026-10-02 ET trading date: ${JSON.stringify(qqqBeforeCapture)}`);
    const sessionCloseAt = new Date(qqqBeforeCapture.regular_close_evidence?.session_close_at || "");
    assert(sessionCloseAt.toISOString() === "2026-10-02T20:00:00.000Z", `Backend session_close_at was not 16:00 ET / 04:00 China: ${qqqBeforeCapture.regular_close_evidence?.session_close_at}`);
    const qqqCapturePostsBefore = routeAudit.filter((item) => item.method === "POST" && item.pathname === "/market-session-comparisons").length;
    await marketSessionCapture.click();
    await waitFor(() => routeAudit.filter((item) => item.method === "POST" && item.pathname === "/market-session-comparisons").length > qqqCapturePostsBefore, timeoutMs, "QQQ market-session capture request");
    await expectText(page.locator("#market-session-comparison-status"), "三段证据", timeoutMs);
    const qqqCaptured = (await pageJson(page, `/market-session-comparisons/latest?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper&symbol=QQQ.US`)).body;
    assert(qqqCaptured.id && qqqCaptured.id !== qqqBeforeCapture.id, `QQQ capture did not create a new immutable record: before=${qqqBeforeCapture.id} after=${qqqCaptured.id}`);
    assert(qqqCaptured.baseline_price === "500" && qqqCaptured.regular_close_price === "510" && qqqCaptured.after_hours_price === "512", `Captured QQQ record changed the three prices: ${JSON.stringify(qqqCaptured)}`);
    const savedPage1 = (await pageJson(page, `/market-session-comparisons?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper&symbol=QQQ.US&limit=1`)).body;
    assert(savedPage1.has_more === true && savedPage1.next_cursor, `Market-session saved history did not expose a next cursor: ${JSON.stringify(savedPage1)}`);
    const savedPage2 = (await pageJson(page, `/market-session-comparisons?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper&symbol=QQQ.US&limit=1&cursor=${encodeURIComponent(savedPage1.next_cursor)}`)).body;
    assert(savedPage2.items?.length === 1 && savedPage2.items[0].id !== savedPage1.items[0].id, `Market-session saved history cursor repeated its first record: ${JSON.stringify({ savedPage1, savedPage2 })}`);
    await waitFor(async () => (await marketSessionSaved.locator("option").count()) >= 2, timeoutMs, "first saved market-session page");
    await waitFor(async () => !(await marketSessionLoadMore.isDisabled()), timeoutMs, "market-session load-more enabled");
    await marketSessionLoadMore.click();
    await waitFor(async () => (await marketSessionSaved.locator("option").count()) >= 3, timeoutMs, "second saved market-session page");
    await waitFor(async () => await marketSessionLoadMore.isDisabled(), timeoutMs, "market-session load-more settled");
    const savedIds = await marketSessionSaved.locator("option").evaluateAll((options) => options.map((option) => option.value).filter(Boolean));
    const oldQqqId = savedIds.find((id) => id !== qqqCaptured.id);
    assert(oldQqqId, `Market-session history did not retain the older QQQ record: ${JSON.stringify(savedIds)}`);
    await marketSessionSaved.selectOption(oldQqqId);
    await waitFor(async () => (await page.locator("#market-session-comparison-raw").textContent() || "").includes(`\"id\": \"${oldQqqId}\"`), timeoutMs, "saved market-session detail selection");
    assert((await marketSessionSaved.inputValue()) === oldQqqId, "Saved market-session select did not retain the older record.");

    // A symbol with no pre-open baseline remains unavailable.  The panel must
    // preserve null evidence instead of turning the missing values into zero.
    await marketSessionInput.fill("AAPL.US");
    await marketSessionRefresh.click();
    await expectText(page.locator("#market-session-comparison-explanation"), "BLOCKED_DATA", timeoutMs);
    const aaplCapturePostsBefore = routeAudit.filter((item) => item.method === "POST" && item.pathname === "/market-session-comparisons").length;
    await marketSessionCapture.click();
    await waitFor(() => routeAudit.filter((item) => item.method === "POST" && item.pathname === "/market-session-comparisons").length > aaplCapturePostsBefore, timeoutMs, "AAPL market-session capture request");
    const aaplComparison = (await pageJson(page, `/market-session-comparisons/latest?external_account_id=${encodeURIComponent(PRIMARY_ACCOUNT)}&mode=paper&symbol=AAPL.US`)).body;
    assert(aaplComparison.status === "not_available" && aaplComparison.data_quality === "unavailable", `AAPL missing-baseline comparison was not unavailable: ${JSON.stringify(aaplComparison)}`);
    assert(aaplComparison.baseline_price == null && aaplComparison.regular_close_price == null && aaplComparison.after_hours_price == null && aaplComparison.pre_to_regular_close_pct == null && aaplComparison.regular_close_to_after_hours_pct == null, `AAPL missing-baseline evidence was filled with values: ${JSON.stringify(aaplComparison)}`);
    const aaplSummary = await textOf(page, "#market-session-comparison-summary");
    const aaplExplanation = await textOf(page, "#market-session-comparison-explanation");
    assert((aaplSummary.match(/缺少证据/g) || []).length >= 3 && !aaplSummary.includes("0.00"), `AAPL summary did not preserve missing prices: ${aaplSummary}`);
    assert(aaplExplanation.includes("未计算（证据不足）") && !aaplExplanation.includes("0.00%"), `AAPL explanation did not preserve missing percentage evidence: ${aaplExplanation}`);

    // Late latest response after an in-flight symbol change must be discarded,
    // and the new symbol must release all controls immediately.
    await marketSessionInput.fill("QQQ.US");
    armDelayedRead("/market-session-comparisons/latest", "QQQ.US");
    await marketSessionRefresh.click();
    await waitFor(() => delayedRead?.hitCount > 0, timeoutMs, "delayed QQQ market-session latest read");
    const busyMarketSession = await page.evaluate(() => ({
      refresh: document.getElementById("market-session-comparison-refresh")?.disabled,
      capture: document.getElementById("market-session-comparison-capture")?.disabled,
    }));
    assert(busyMarketSession.refresh && busyMarketSession.capture, `Market-session controls were not busy during the delayed read: ${JSON.stringify(busyMarketSession)}`);
    await marketSessionInput.fill("AAPL.US");
    await waitFor(async () => !(await marketSessionRefresh.isDisabled()) && !(await marketSessionCapture.isDisabled()), timeoutMs, "market-session controls after symbol change");
    releaseDelayedRead("error");
    await sleep(350);
    assert((await marketSessionInput.inputValue()) === "AAPL.US", "Late QQQ market-session response changed the current symbol.");
    assert((await textOf(page, "#market-session-comparison-explanation")).includes("标的已改变"), "Late QQQ market-session response polluted the AAPL empty state.");
    assert(!(await marketSessionRefresh.isDisabled()) && !(await marketSessionCapture.isDisabled()), "Market-session controls remained disabled after the late symbol response.");
    delayedRead = null;

    // The saved-list request gets a finite delay while the account generation
    // changes.  The late primary response must not overwrite the alternate
    // account, and its pagination control must settle for the new generation.
    await marketSessionInput.fill("QQQ.US");
    await marketSessionRefresh.click();
    await expectText(page.locator("#market-session-comparison-summary"), "500.00 USD", timeoutMs);
    await waitFor(async () => !(await marketSessionLoadMore.isDisabled()), timeoutMs, "QQQ market-session page before account race");
    armDelayedRead("/market-session-comparisons", "QQQ.US");
    await marketSessionRefresh.click();
    await waitFor(() => delayedRead?.hitCount > 0, timeoutMs, "delayed primary market-session saved page");
    await selectAccount(page, ALT_ACCOUNT, timeoutMs);
    await waitFor(async () => !(await marketSessionRefresh.isDisabled()) && !(await marketSessionCapture.isDisabled()) && !(await marketSessionSaved.locator("option").first().isDisabled()), timeoutMs, "alternate market-session controls after account generation");
    releaseDelayedRead("error");
    await sleep(350);
    assert((await page.locator("#topbar-account-select").inputValue()) === ALT_ACCOUNT, "Market-session account race did not settle on the alternate account.");
    const alternateMarketSessionRaw = String(await page.locator("#market-session-comparison-raw").textContent() || "");
    assert(alternateMarketSessionRaw.includes(ALT_ACCOUNT) && !alternateMarketSessionRaw.includes(`\"external_account_id\": \"${PRIMARY_ACCOUNT}\"`), `Late primary market-session response polluted the alternate account: ${alternateMarketSessionRaw}`);
    await waitFor(async () => !(await marketSessionLoadMore.isDisabled()), timeoutMs, "alternate market-session load-more enabled");
    await marketSessionLoadMore.click();
    await waitFor(async () => await marketSessionLoadMore.isDisabled(), timeoutMs, "alternate market-session pagination settled");
    const marketSessionAccountRace = { alternate_account: ALT_ACCOUNT, stale_primary_response_discarded: true, load_more_settled: true };
    releaseDelayedRead("error");
    delayedRead = null;
    await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);
    await waitFor(async () => !(await marketSessionRefresh.isDisabled()) && !(await marketSessionCapture.isDisabled()), timeoutMs, "primary market-session controls restored");
    marketSessionEvidence = {
      symbol: "QQQ.US",
      prices: { baseline: qqqBeforeCapture.baseline_price, regular_close: qqqBeforeCapture.regular_close_price, after_hours: qqqBeforeCapture.after_hours_price },
      percentages: { pre_to_regular_close: qqqBeforeCapture.pre_to_regular_close_pct, regular_close_to_after_hours: qqqBeforeCapture.regular_close_to_after_hours_pct },
      target_trading_day: qqqBeforeCapture.target_trading_day,
      session_close_at: qqqBeforeCapture.regular_close_evidence?.session_close_at,
      captured_record_id: qqqCaptured.id,
      older_record_id: oldQqqId,
      aapl_missing_baseline: true,
      symbol_change_race: { stale_response_discarded: true, controls_restored: true },
      account_generation_race: marketSessionAccountRace,
    };

    // P2.2: visible timeline plus explicit date/symbol filter and keyset page.
    await waitFor(async () => await page.locator("#market-event-timeline .workbench-timeline-item").count() >= 2, timeoutMs, "market timeline rows");
    await expectText(page.locator("#market-explanation-summary"), "事件", timeoutMs);
    const timelinePage1 = await pageJson(page, "/research/timeline?external_account_id=LBPT10087357&mode=paper&symbols=UNH.US&symbols=QQQ.US&start=2026-05-01T00:00:00Z&end=2026-06-30T23:59:59Z&limit=1");
    assert(timelinePage1.ok && timelinePage1.body.has_more && timelinePage1.body.next_cursor, `Timeline filter did not return a bounded first page: ${JSON.stringify(timelinePage1.body)}`);
    assert((timelinePage1.body.events || []).every((item) => !item.symbol || ["UNH.US", "QQQ.US"].includes(item.symbol)), "Timeline filter returned an unrelated symbol.");
    const timelinePage2 = await pageJson(page, `/research/timeline?external_account_id=LBPT10087357&mode=paper&symbols=UNH.US&symbols=QQQ.US&start=2026-05-01T00:00:00Z&end=2026-06-30T23:59:59Z&limit=1&cursor=${encodeURIComponent(timelinePage1.body.next_cursor)}`);
    const firstTimelineEventId = timelinePage1.body.events?.[0]?.id || timelinePage1.body.events?.[0]?.event_id;
    const secondTimelineEventId = timelinePage2.body.events?.[0]?.id || timelinePage2.body.events?.[0]?.event_id;
    assert(timelinePage2.ok && (timelinePage2.body.events || []).length === 1 && secondTimelineEventId !== firstTimelineEventId, "Timeline cursor page repeated or omitted its second event.");

    // P4/P5: no registered dataset means honest BLOCKED_DATA, no invented curve.
    await page.locator("#strategy-workspace-tab").click();
    await waitWorkspace(page, "strategy", timeoutMs);
    await waitFor(async () => (await page.locator("#backtest-dataset").isDisabled()) === true, timeoutMs, "empty backtest dataset registry");
    await expectText(page.locator("#backtest-dataset"), "没有已注册数据集", timeoutMs);
    await page.locator("#backtest-run-button").click();
    await expectText(page.locator("#backtest-status"), "先选择有效数据集", timeoutMs);
    assert(await page.locator("#backtest-result-chart svg").count() === 0, "Backtest rendered an invented equity curve without a dataset.");
    const blockedBacktest = await pageJson(page, "/backtests", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ dataset_id: "missing-fixture", strategy: "bull_put", symbols: ["QQQ"], start_date: "2020-01-01", end_date: "2026-09-30" }),
    });
    assert(blockedBacktest.status === 422 && blockedBacktest.body?.detail?.code === "blocked_data", `Backtest API did not remain honestly blocked: ${JSON.stringify(blockedBacktest)}`);

    // Isolated mock lifecycle: validate period/freeze, Covered Call lots/fees, and cancel.
    backtestFixtureEnabled = true;
    await page.locator("#portfolio-workspace-tab").click();
    await waitWorkspace(page, "portfolio", timeoutMs);
    await page.locator("#strategy-workspace-tab").click();
    await waitWorkspace(page, "strategy", timeoutMs);
    await waitFor(async () => !(await page.locator("#backtest-dataset").isDisabled()), timeoutMs, "mock backtest dataset registry");
    await expectText(page.locator("#backtest-dataset"), "Mock options history", timeoutMs);
    await page.locator("#backtest-strategy").selectOption("covered_call");
    await waitFor(async () => await page.locator("#backtest-initial-stock-symbol").isVisible(), timeoutMs, "Covered Call initial lot inputs");
    await page.locator("#backtest-period-segment").selectOption("holdout");
    await waitFor(async () => await page.locator("#backtest-freeze-source-run-id option").count() > 1, timeoutMs, "validation freeze source option");
    await page.locator("#backtest-freeze-source-run-id").selectOption("mock-validation-freeze-0001");
    await page.locator("#backtest-symbols").fill("QQQ");
    await page.locator("#backtest-start-date").fill("2025-01-01");
    await page.locator("#backtest-end-date").fill("2026-09-30");
    await page.locator("#backtest-fee-per-contract").fill("1.25");
    await page.locator("#backtest-slippage-bps").fill("7.5");
    await page.locator("#backtest-initial-stock-symbol").fill("QQQ.US");
    await page.locator("#backtest-initial-stock-quantity").fill("100");
    await page.locator("#backtest-initial-stock-price").fill("500");
    await page.locator("#backtest-initial-stock-fee").fill("12.50");
    await page.locator("#backtest-run-button").click();
    await waitFor(() => backtestRequests.length === 1, timeoutMs, "captured Covered Call backtest request");
    const syntheticSubmissionStatus = await textOf(page, "#backtest-status");
    assert(!syntheticSubmissionStatus.includes("回测服务暂时不可用"), `Synthetic backtest submission failed: ${syntheticSubmissionStatus}`);
    const capturedBacktest = backtestRequests[0];
    assert(capturedBacktest.strategy === "covered_call", `Covered Call request used the wrong strategy: ${JSON.stringify(capturedBacktest)}`);
    assert(capturedBacktest.period_segment === "holdout" && capturedBacktest.freeze_source_run_id === "mock-validation-freeze-0001", `Backtest request did not preserve period/freeze: ${JSON.stringify(capturedBacktest)}`);
    assert(capturedBacktest.fee_model?.commission_per_contract === "1.25" && capturedBacktest.slippage_model?.basis_points === "7.5", `Backtest request did not preserve fee/slippage assumptions: ${JSON.stringify(capturedBacktest)}`);
    assert(capturedBacktest.initial_stock_lots?.[0]?.symbol === "QQQ" && capturedBacktest.initial_stock_lots?.[0]?.quantity === "100" && capturedBacktest.initial_stock_lots?.[0]?.acquisition_price === "500" && capturedBacktest.initial_stock_lots?.[0]?.acquisition_fee === "12.50", `Covered Call initial lot was not captured exactly: ${JSON.stringify(capturedBacktest.initial_stock_lots)}`);
    await expectText(page.locator("#backtest-runs-body"), "mock-backtest-queued-1", timeoutMs);
    await waitFor(async () => !(await page.locator("#backtest-cancel-button").isDisabled()), timeoutMs, "queued backtest cancel control");
    await page.locator("#backtest-cancel-button").click();
    assert(routeAudit.some((item) => item.method === "POST" && /\/backtests\/[^/]+\/cancel$/.test(item.pathname)), "Mock backtest cancel request was not observed.");
    await waitFor(async () => {
      const statusText = await textOf(page, "#backtest-status");
      const rowsText = await textOf(page, "#backtest-runs-body");
      return statusText.includes("取消") || rowsText.includes("已取消") || rowsText.includes("Cancelled");
    }, timeoutMs, "cancelled backtest UI state");
    const cancelledStatusText = await textOf(page, "#backtest-status");
    const cancelledRowsText = await textOf(page, "#backtest-runs-body");
    assert(cancelledStatusText.includes("取消") || cancelledRowsText.includes("已取消") || cancelledRowsText.includes("Cancelled"), `Mock backtest cancel did not render a cancelled state: status=${cancelledStatusText}; rows=${cancelledRowsText}`);
    backtestFixtureEnabled = false;

    // Advisor audit is a local read and must never call the model or broker.
    await page.locator("button[data-strategy-tab='experiments']").click();
    await page.locator("#advisor-audit-load").click();
    await waitFor(async () => (await page.locator("#advisor-audit-list [data-advisor-audit-run]").count()) > 0, timeoutMs, "Advisor audit row");
    await expectText(page.locator("#advisor-audit-status"), "本地审计记录", timeoutMs);
    const advisorDetailVisible = await page.locator("#advisor-audit-detail").isVisible();
    assert(advisorDetailVisible, `Advisor audit detail was hidden after loading a run: ${await page.evaluate(() => ({ workspace: document.body.dataset.workspace, strategyTab: document.getElementById("strategy-section")?.dataset.strategyTab }))}`);
    await waitFor(async () => String(await page.locator("#advisor-audit-detail").textContent() || "").includes("Advisor"), timeoutMs, "Advisor audit detail");
    assert(!observer.requests.some((item) => item.method !== "GET" && item.pathname.includes("/strategies/advisor")), "Advisor audit triggered a model/advisor write.");

    // Account A/B/A stale-read probes for each new workspace module.
    async function runAccountRace({ name, pathname, workspace, trigger, assertAlternate, assertPrimary }) {
      await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);
      await sleep(200);
      armDelayedRead(pathname);
      await trigger();
      await waitFor(() => delayedRead?.hitCount > 0, timeoutMs, `${name} delayed primary read`);
      await selectAccount(page, ALT_ACCOUNT, timeoutMs);
      await assertAlternate();
      releaseDelayedRead("error");
      await sleep(350);
      await assertAlternate();
      await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);
      await assertPrimary();
      accountRace.push({ name, pathname, stale_primary_error_discarded: true, alternate_rendered_before_release: true });
      delayedRead = null;
    }

    await runAccountRace({
      name: "portfolio", pathname: "/portfolio/analytics", workspace: "portfolio",
      trigger: async () => { await page.locator("#portfolio-workspace-tab").click(); },
      assertAlternate: async () => await expectText(page.locator("#portfolio-explanation-summary"), "mock_demo_alt", timeoutMs),
      assertPrimary: async () => assert(!(await textOf(page, "#portfolio-explanation-summary")).includes("mock_demo_alt")),
    });
    await runAccountRace({
      name: "advisor", pathname: "/strategies/advisor/audit", workspace: "strategy",
      trigger: async () => { await page.locator("#strategy-workspace-tab").click(); await page.locator("button[data-strategy-tab='experiments']").click(); await page.locator("#advisor-audit-load").click(); },
      assertAlternate: async () => { await expectText(page.locator("#advisor-audit-list"), "MockAltAdvisor", timeoutMs); },
      assertPrimary: async () => assert(!(await textOf(page, "#advisor-audit-list")).includes("MockAltAdvisor")),
    });
    await runAccountRace({
      name: "market", pathname: "/research/timeline", workspace: "macro",
      trigger: async () => { await page.locator("#macro-workspace-tab").click(); await page.locator("#market-timeline-refresh").click(); },
      assertAlternate: async () => await expectText(page.locator("#market-event-timeline"), "[ALT]", timeoutMs),
      assertPrimary: async () => assert(!(await textOf(page, "#market-event-timeline")).includes("[ALT]")),
    });
    await runAccountRace({
      name: "research-saved-lists", pathname: "/research/screens", workspace: "research",
      trigger: async () => { await page.reload({ waitUntil: "domcontentloaded" }); await expectText(page.locator("#research-table-body"), "QQQ.US", timeoutMs); },
      assertAlternate: async () => await expectText(page.locator("#research-screen-select"), "ALT ·", timeoutMs),
      assertPrimary: async () => assert(!(await textOf(page, "#research-screen-select")).includes("ALT ·")),
    });
    await runAccountRace({
      name: "backtest", pathname: "/backtests", workspace: "strategy",
      trigger: async () => { await page.locator("#strategy-workspace-tab").click(); },
      assertAlternate: async () => { await waitFor(() => page.locator("#backtest-dataset").isDisabled(), timeoutMs, "alternate empty backtest registry"); assert(await page.locator("#backtest-result-chart svg").count() === 0, "Alternate account received an invented backtest curve."); },
      assertPrimary: async () => assert(await page.locator("#backtest-result-chart svg").count() === 0, "Primary account retained an invented backtest curve."),
    });

    // Responsive evidence for every workspace at each requested width.
    await selectAccount(page, PRIMARY_ACCOUNT, timeoutMs);
    for (const width of [1440, 1024, 760]) {
      for (const workspace of ["research", "strategy", "macro", "portfolio", "operations"]) {
        screenshots[`${workspace}_${width}`] = await captureWorkspace(page, workspace, width, outputDirectory, timeoutMs);
      }
    }
    await page.setViewportSize({ width: 1440, height: 1200 });

    const requestAudit = requestAuditSnapshot();
    assert(observer.mutationRequests.length === 0, `Broker mutation requests were observed: ${JSON.stringify(observer.mutationRequests)}`);
    assert(requestAudit.paper_mode_query_violations.length === 0, `Executions/journals reads omitted mode=paper: ${JSON.stringify(requestAudit.paper_mode_query_violations)}`);
    return {
      rendered: true,
      workflow: { screen_id: screenId, case_id: caseId, selected_symbol_after_case: "MOCK.US", selected_range_after_case: "1y", candidate_compare: true, strategy_evaluation: true },
      research_layout: desktopResearchLayout,
      portfolio: { nav: portfolioPayload.latest?.net_liquidation, investment_return: portfolioPayload.change?.investment_return, investment_return_unavailable: portfolioPayload.change?.investment_return_unavailable, weights: (portfolioPayload.allocation || []).map((item) => ({ symbol: item.symbol, weight_of_net_liquidation: item.weight_of_net_liquidation })), risk_known_max_loss: riskPayload.known_max_loss },
      market_session: marketSessionEvidence,
      timeline: { rendered_events: await page.locator("#market-event-timeline .workbench-timeline-item").count(), filtered_pages: 2 },
      backtest: {
        datasets_empty: true,
        status: "BLOCKED_DATA",
        invented_curve: false,
        synthetic_request: capturedBacktest,
        cancel_observed: routeAudit.some((item) => item.method === "POST" && /\/backtests\/[^/]+\/cancel$/.test(item.pathname)),
      },
      account_race: accountRace,
      screenshots,
      request_audit: requestAudit,
    };
  } catch (error) {
    for (const width of [1440, 1024, 760]) {
      try {
        await page.setViewportSize({ width, height: width <= 780 ? 1000 : 1200 });
        const failurePath = path.join(outputDirectory, `failure-portfolio-${width}.png`);
        await page.screenshot({ path: failurePath, fullPage: true });
        screenshots[`failure_portfolio_${width}`] = failurePath;
      } catch (_screenshotError) {
        // Preserve the original assertion failure; screenshot capture is evidence only.
      }
    }
    error.browserPayload = {
      rendered: false,
      phase,
      error: error?.stack || error?.message || String(error),
      research_layout: desktopResearchLayout,
      screenshots,
      request_audit: requestAuditSnapshot(),
    };
    throw error;
  } finally {
    observer.dispose();
    await browser.close();
  }
}

main().then((result) => {
  process.stdout.write(`${JSON.stringify(result)}\n`);
}).catch((error) => {
  process.stdout.write(`${JSON.stringify(error.browserPayload || { rendered: false, error: error?.stack || error?.message || String(error) })}\n`);
  process.exitCode = 1;
});

const fs = require("node:fs");
const path = require("node:path");
const { resolveBrowserExecutable } = require("./browser_test_helpers");

async function main() {
  const [, , baseUrl, screenshotPath, playwrightCorePath, iterationsArg, settleTimeoutArg, pauseMsArg] = process.argv;
  if (!baseUrl || !screenshotPath || !playwrightCorePath || !iterationsArg || !settleTimeoutArg || !pauseMsArg) {
    throw new Error(
      "Usage: node real_local_dashboard_refresh_flow.js <baseUrl> <screenshotPath> <playwrightCorePath> <iterations> <settleTimeoutMs> <pauseMs>",
    );
  }

  const iterations = Number(iterationsArg);
  const settleTimeoutMs = Number(settleTimeoutArg);
  const pauseMs = Number(pauseMsArg);
  if (!Number.isFinite(iterations) || iterations < 1) {
    throw new Error("Iterations must be a positive number.");
  }

  const { chromium } = require(playwrightCorePath);
  const executablePath = resolveBrowserExecutable();
  const browser = await chromium.launch({
    headless: true,
    ...(executablePath ? { executablePath } : {}),
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 2200 } });
  const runs = [];

  try {
    for (let index = 0; index < iterations; index += 1) {
      const label = index === 0 ? "initial-load" : `reload-${index}`;
      const startedAt = Date.now();
      if (index === 0) {
        await page.goto(baseUrl, { waitUntil: "load" });
      } else {
        await page.reload({ waitUntil: "load" });
      }

      await page.waitForSelector("#account-select", { state: "attached", timeout: settleTimeoutMs });
      await page.waitForSelector("#positions-body", { state: "attached", timeout: settleTimeoutMs });

      const dashboardReadyMs = await waitForDashboardReady(page, startedAt, settleTimeoutMs);
      const researchTableReadyMs = await waitForResearchTableReady(page, startedAt, settleTimeoutMs);
      const chartReadyMs = await measureSelectedChartReady(page, settleTimeoutMs);
      const overlaysSettledMs = await waitForOverlaysSettled(page, startedAt, settleTimeoutMs);
      const snapshot = await captureSnapshot(page);
      const resources = await captureResourceTimings(page);

      runs.push({
        label,
        dashboard_ready_ms: dashboardReadyMs,
        research_table_ready_ms: researchTableReadyMs,
        selected_chart_ready_ms: chartReadyMs,
        overlays_settled_ms: overlaysSettledMs,
        account_id: snapshot.accountId,
        status_banner: snapshot.statusBanner,
        research_status: snapshot.researchStatus,
        research_progress: snapshot.researchProgress,
        research_rows: snapshot.researchRows,
        pre_open_status: snapshot.preOpenStatus,
        pre_open_detail: snapshot.preOpenDetail,
        positions_rows: snapshot.positionsRows,
        orders_rows: snapshot.ordersRows,
        spreads_rows: snapshot.spreadsRows,
        resource_timings_ms: resources,
      });

      if (pauseMs > 0 && index < iterations - 1) {
        await page.waitForTimeout(pauseMs);
      }
    }

    fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: true });
    process.stdout.write(
      JSON.stringify(
        {
          runs,
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

async function measureSelectedChartReady(page, timeoutMs) {
  const startedAt = Date.now();
  const preferredRow = page.locator("#research-table-body tr[data-research-select='QQQ.US']").first();
  if ((await preferredRow.count()) > 0 && (await preferredRow.getAttribute("aria-selected")) !== "true") {
    await preferredRow.click();
  }
  const chartTab = page.locator("[data-research-view='chart']");
  if ((await chartTab.getAttribute("aria-selected")) !== "true") {
    await chartTab.click();
  }
  await page.waitForFunction(
    () => {
      const container = document.getElementById("research-chart-container");
      const summary = document.getElementById("research-chart-summary")?.textContent?.trim().toLowerCase() ?? "";
      const unavailable = container?.querySelector("[data-chart-unavailable]:not([hidden])");
      return (
        container?.getAttribute("aria-busy") !== "true" &&
        Boolean(container?.querySelector("canvas")) &&
        Boolean(summary) &&
        !summary.includes("loading") &&
        !summary.includes("正在加载") &&
        !unavailable
      );
    },
    null,
    { timeout: timeoutMs },
  );
  return Date.now() - startedAt;
}

async function waitForResearchTableReady(page, startedAt, timeoutMs) {
  await page.waitForFunction(
    () => {
      const body = document.getElementById("research-table-body");
      const progress = document.getElementById("research-progress")?.textContent?.trim().toLowerCase() ?? "";
      const hasDataRow = Boolean(body?.querySelector("tr[data-research-select]"));
      const hasTerminalEmpty = Boolean(body?.querySelector("td.research-empty-cell"));
      const universePending = progress.includes("waiting") || progress.includes("universe") || progress.includes("等待");
      return (hasDataRow || hasTerminalEmpty) && !universePending;
    },
    null,
    { timeout: timeoutMs },
  );
  return Date.now() - startedAt;
}

async function waitForDashboardReady(page, startedAt, timeoutMs) {
  await page.waitForFunction(
    () => {
      const banner = document.getElementById("status-banner")?.textContent ?? "";
      const dashboardUpdated =
        banner.includes("Dashboard updated") || banner.includes("工作台已更新");
      const positionsRows = document.querySelectorAll("#positions-body tr").length;
      const ordersRows = document.querySelectorAll("#orders-body tr").length;
      const spreadsRows = document.querySelectorAll("#spreads-body tr").length;
      return (
        dashboardUpdated &&
        positionsRows > 0 &&
        ordersRows > 0 &&
        spreadsRows > 0
      );
    },
    null,
    { timeout: timeoutMs },
  );
  return Date.now() - startedAt;
}

async function waitForOverlaysSettled(page, startedAt, timeoutMs) {
  await page.waitForFunction(
    () => {
      const researchProgress = document.getElementById("research-progress")?.textContent?.trim().toLowerCase() ?? "";
      const boardStatusTile = Array.from(document.querySelectorAll("#preopen-summary-strip .mini-metric-tile")).find(
        (tile) => {
          const text = tile.textContent ?? "";
          return text.includes("Board Status") || text.includes("看板状态");
        },
      );
      const preOpenStatus =
        boardStatusTile?.querySelector("strong")?.textContent?.trim().toUpperCase() ?? "";
      const preOpenText = document.getElementById("preopen-assessment-card")?.innerText ?? "";
      const researchSettled =
        researchProgress.includes("complete") ||
        researchProgress.includes("stale") ||
        researchProgress.includes("error") ||
        researchProgress.includes("no research") ||
        researchProgress.includes("完成") ||
        researchProgress.includes("陈旧") ||
        researchProgress.includes("失败") ||
        researchProgress.includes("没有可用");
      const preOpenSettled =
        (!!preOpenStatus && preOpenStatus !== "REFRESHING") ||
        (!!preOpenText && !preOpenText.toUpperCase().includes("REFRESHING"));
      return researchSettled && preOpenSettled;
    },
    null,
    { timeout: timeoutMs },
  );
  return Date.now() - startedAt;
}

async function captureSnapshot(page) {
  return page.evaluate(() => {
    const boardStatusTile = Array.from(document.querySelectorAll("#preopen-summary-strip .mini-metric-tile")).find(
      (tile) => (tile.textContent ?? "").includes("Board Status"),
    );
    return {
      accountId: document.getElementById("account-select")?.value ?? "",
      statusBanner: document.getElementById("status-banner")?.textContent?.trim() ?? "",
      researchStatus: document.getElementById("research-status")?.textContent?.trim() ?? "",
      researchProgress: document.getElementById("research-progress")?.textContent?.trim() ?? "",
      researchRows: document.querySelectorAll("#research-table-body tr[data-research-select]").length,
      preOpenStatus: boardStatusTile?.querySelector("strong")?.textContent?.trim() ?? "",
      preOpenDetail: boardStatusTile?.querySelector(".mini-metric-detail")?.textContent?.trim() ?? "",
      positionsRows: document.querySelectorAll("#positions-body tr").length,
      ordersRows: document.querySelectorAll("#orders-body tr").length,
      spreadsRows: document.querySelectorAll("#spreads-body tr").length,
    };
  });
}

async function captureResourceTimings(page) {
  return page.evaluate(() => {
    const interestingPaths = [
      "/broker-accounts",
      "/account-snapshots/latest",
      "/orders",
      "/strategies/bull-put/working-spreads",
      "/strategies/bull-put/runtime",
      "/strategies/experiment",
      "/executions",
      "/journals",
      "/strategies/pre-open-runs",
      "/research/universe",
      "/research/technicals",
      "/research/symbols/",
      "/strategies/pre-open-risk",
    ];
    return performance
      .getEntriesByType("resource")
      .filter((entry) => entry.initiatorType === "fetch" || entry.initiatorType === "xmlhttprequest")
      .map((entry) => {
        const url = new URL(entry.name);
        return {
          path: `${url.pathname}${url.search}`,
          duration_ms: Number(entry.duration.toFixed(1)),
        };
      })
      .filter((entry) => interestingPaths.some((prefix) => entry.path.startsWith(prefix)));
  });
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

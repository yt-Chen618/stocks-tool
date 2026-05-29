const fs = require("node:fs");
const path = require("node:path");

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
  const browser = await chromium.launch({ headless: true });
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

      await page.waitForSelector("#account-select", { timeout: settleTimeoutMs });
      await page.waitForSelector("#positions-body", { timeout: settleTimeoutMs });

      const dashboardReadyMs = await waitForDashboardReady(page, startedAt, settleTimeoutMs);
      const overlaysSettledMs = await waitForOverlaysSettled(page, startedAt, settleTimeoutMs);
      const snapshot = await captureSnapshot(page);
      const resources = await captureResourceTimings(page);

      runs.push({
        label,
        dashboard_ready_ms: dashboardReadyMs,
        overlays_settled_ms: overlaysSettledMs,
        account_id: snapshot.accountId,
        status_banner: snapshot.statusBanner,
        quote_status: snapshot.quoteStatus,
        quote_detail: snapshot.quoteDetail,
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

async function waitForDashboardReady(page, startedAt, timeoutMs) {
  await page.waitForFunction(
    () => {
      const banner = document.getElementById("status-banner")?.textContent ?? "";
      const positionsRows = document.querySelectorAll("#positions-body tr").length;
      const ordersRows = document.querySelectorAll("#orders-body tr").length;
      const spreadsRows = document.querySelectorAll("#spreads-body tr").length;
      return (
        banner.includes("Dashboard updated") &&
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
      const quoteStatus =
        document.querySelector("#quote-card .pill")?.textContent?.trim().toUpperCase() ?? "";
      const quoteText = document.getElementById("quote-card")?.innerText ?? "";
      const boardStatusTile = Array.from(document.querySelectorAll("#preopen-summary-strip .mini-metric-tile")).find(
        (tile) => (tile.textContent ?? "").includes("Board Status"),
      );
      const preOpenStatus =
        boardStatusTile?.querySelector("strong")?.textContent?.trim().toUpperCase() ?? "";
      const preOpenText = document.getElementById("preopen-assessment-card")?.innerText ?? "";
      const quoteSettled =
        (!!quoteStatus && quoteStatus !== "REFRESHING") ||
        (!!quoteText && !quoteText.toUpperCase().includes("REFRESHING"));
      const preOpenSettled =
        (!!preOpenStatus && preOpenStatus !== "REFRESHING") ||
        (!!preOpenText && !preOpenText.toUpperCase().includes("REFRESHING"));
      return quoteSettled && preOpenSettled;
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
      quoteStatus: document.querySelector("#quote-card .pill")?.textContent?.trim() ?? "",
      quoteDetail: document.querySelector("#quote-card .overlay-detail")?.textContent?.trim() ?? "",
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
      "/strategies/bull-put/spreads",
      "/strategies/bull-put/runtime",
      "/executions",
      "/journals",
      "/strategies/pre-open-runs",
      "/brokers/longbridge/quote",
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

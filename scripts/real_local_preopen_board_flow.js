const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const [, , baseUrl, screenshotPath, playwrightCorePath, expectedSessionDate] = process.argv;
  if (!baseUrl || !screenshotPath || !playwrightCorePath || !expectedSessionDate) {
    throw new Error(
      "Usage: node real_local_preopen_board_flow.js <baseUrl> <screenshotPath> <playwrightCorePath> <expectedSessionDate>",
    );
  }

  const { chromium } = require(playwrightCorePath);
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1200, height: 1600 } });

  try {
    await page.goto(baseUrl, { waitUntil: "load", timeout: 20000 });
    await page.waitForSelector("#account-select", { timeout: 20000 });
    await page.waitForSelector("#load-preopen-board", { timeout: 20000 });
    await page.waitForFunction(
      () => {
        const button = document.getElementById("load-preopen-board");
        return button && !button.disabled;
      },
      null,
      { timeout: 20000 },
    );

    const responsePromise = page.waitForResponse(
      (response) =>
        response.url().includes("/strategies/pre-open-risk") && response.request().method() === "GET",
      { timeout: 60000 },
    );
    await page.click("#load-preopen-board");
    const response = await responsePromise;
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }

    const latest = {
      status: response.status(),
      url: response.url(),
      body,
    };
    const expectedMonthDay = expectedSessionDate.slice(5).replace("-", "/");
    await page.waitForFunction(
      (monthDay) => {
        const text = document.getElementById("preopen-assessment-card")?.innerText ?? "";
        return text.includes(monthDay) || text.includes("Live board") || text.includes("\u5b9e\u65f6\u5b8f\u89c2");
      },
      expectedMonthDay,
      { timeout: 45000 },
    );

    if (latest.status !== 200) {
      throw new Error(`Pre-open risk request returned HTTP ${latest.status}.`);
    }
    if (!latest.url.includes("include_option_overlays=false")) {
      throw new Error(`Pre-open risk request did not use the fast path: ${latest.url}`);
    }
    if (!latest.body) {
      throw new Error("Pre-open risk response body was empty.");
    }
    if (latest.body.target_session_date !== expectedSessionDate) {
      throw new Error(
        `Expected target_session_date ${expectedSessionDate}, got ${latest.body.target_session_date}.`,
      );
    }
    if (latest.body.source_run_id) {
      throw new Error(`Expected a live board response, got stale source_run_id ${latest.body.source_run_id}.`);
    }

    const snapshot = await page.evaluate(() => {
      const boardStatusTile = Array.from(document.querySelectorAll("#preopen-summary-strip .mini-metric-tile")).find(
        (tile) => (tile.textContent ?? "").includes("Board Status") || (tile.textContent ?? "").includes("\u770b\u677f\u72b6\u6001"),
      );
      return {
        preOpenStatus: boardStatusTile?.querySelector("strong")?.textContent?.trim() ?? "",
        preOpenDetail: boardStatusTile?.querySelector(".mini-metric-detail")?.textContent?.trim() ?? "",
        preOpenCard: document.getElementById("preopen-assessment-card")?.innerText ?? "",
        storedRunCard: document.getElementById("preopen-run-review")?.innerText ?? "",
      };
    });

    fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: false });
    process.stdout.write(
      JSON.stringify(
        {
          response: latest,
          snapshot,
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

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

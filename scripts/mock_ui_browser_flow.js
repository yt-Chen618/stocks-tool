const fs = require("node:fs");
const path = require("node:path");

async function main() {
  const [, , baseUrl, screenshotPath, playwrightCorePath] = process.argv;
  if (!baseUrl || !screenshotPath || !playwrightCorePath) {
    throw new Error("Usage: node mock_ui_browser_flow.js <baseUrl> <screenshotPath> <playwrightCorePath>");
  }

  const { chromium } = require(playwrightCorePath);
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1600, height: 2200 } });
  page.on("dialog", (dialog) => dialog.accept());
  let journalPanelText = "";
  let strategySkipText = "";
  let strategyReviewText = "";
  let preOpenAssessmentText = "";
  let preOpenRunText = "";

  try {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.waitForSelector("#account-select");
    await page.waitForSelector("#spreads-body tr");
    await expectText(page.locator("body"), "Pre-open Risk Board");
    await expectText(page.locator("body"), "Risk Proxies");
    await expectText(page.locator("body"), "QQQ / SPY Put Check");
    await expectText(page.locator("body"), "Opening Follow-through");
    await expectText(page.locator("body"), "Bull Put Strategy");
    await expectText(page.locator("body"), "Bull Put Monitor");
    await expectText(page.locator("body"), "Bull Put Spreads");
    await expectText(page.locator("#strategy-runtime-strip"), "Entry Status");
    await expectText(page.locator("#spread-summary-strip"), "Active Spreads");
    await expectText(page.locator("#preopen-assessment-card"), "QQQ cleaner than SPY");
    await expectText(page.locator("#preopen-signals"), "Nasdaq 100 ETF");
    await expectText(page.locator("#preopen-puts"), "QQQ260530P498000.US");
    await expectText(page.locator("#preopen-run-review"), "Opening follow-through confirmed");
    preOpenAssessmentText = await page.locator("#preopen-assessment-card").innerText();
    preOpenRunText = await page.locator("#preopen-run-review").innerText();

    await clickRowButton(page, "#spreads-body tr", "QQQ.US", "Monitor");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Take Profit"),
    );
    await page.waitForFunction(
      () => document.getElementById("spreads-body")?.innerText?.toLowerCase().includes("closed"),
    );

    await page.selectOption("#strategy-manual-pause", "true");
    await page.fill("#strategy-paused-symbols", "SMH.US");
    await page.click("#save-strategy-controls");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("controls updated"),
    );
    await page.click("#run-strategy-scan");
    await page.waitForFunction(
      () => document.getElementById("strategy-skip-card")?.innerText?.toLowerCase().includes("manually paused"),
    );
    strategySkipText = await page.locator("#strategy-skip-card").innerText();
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
    await page.click("#submit-order");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Order submitted"),
    );

    await page.waitForSelector("#replace-order-form:not(.hidden)");
    await page.fill("#replace-quantity", "2");
    await page.fill("#replace-limit-price", "321");
    await page.click("#replace-order-form button[type='submit']");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("updated"),
    );
    await expectText(page.locator("#selected-order-card"), "x 2");

    await page.click("#selected-order-card button[data-selected-action='cancel']");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("canceled"),
    );
    await page.waitForFunction(
      () => document.getElementById("selected-order-card")?.innerText?.toLowerCase().includes("canceled"),
    );

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
          },
          strategy: {
            manualPauseRendered: strategySkipText.toLowerCase().includes("manually paused"),
            skipReason: strategySkipText,
            reviewRendered: strategyReviewText.toLowerCase().includes("short delta target"),
            reviewSummary: strategyReviewText,
          },
          order: {
            selectedOrder: summary.selectedOrderText,
            finalStatusBanner: summary.statusBanner,
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

async function expectText(locator, text) {
  const content = await locator.innerText();
  if (!content.includes(text)) {
    throw new Error(`Expected text '${text}' to appear in locator content.`);
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

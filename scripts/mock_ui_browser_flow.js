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

  try {
    await page.goto(baseUrl, { waitUntil: "networkidle" });
    await page.waitForSelector("#account-select");
    await page.waitForSelector("#spreads-body tr");
    await expectText(page.locator("body"), "Bull Put Monitor");
    await expectText(page.locator("body"), "Bull Put Spreads");
    await expectText(page.locator("#spread-summary-strip"), "Active Spreads");

    await clickRowButton(page, "#spreads-body tr", "QQQ.US", "Monitor");
    await page.waitForFunction(
      () => document.getElementById("status-banner")?.textContent?.includes("Take Profit"),
    );
    await page.waitForFunction(
      () => document.getElementById("spreads-body")?.innerText?.includes("Closed"),
    );

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
          spread: {
            monitorTriggered: summary.statusBanner.includes("canceled") || summary.spreadTable.includes("Closed"),
            tableRow: summary.spreadTable,
          },
          order: {
            selectedOrder: summary.selectedOrderText,
            finalStatusBanner: summary.statusBanner,
          },
          journal: {
            rendered: summary.journalText.includes("Browser regression review"),
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

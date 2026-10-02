const fs = require("node:fs");

function resolveBrowserExecutable() {
  const configured = process.env.PLAYWRIGHT_CHROME_PATH;
  return configured && fs.existsSync(configured) ? configured : null;
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function waitFor(predicate, timeoutMs = 15000, label = "condition") {
  const deadline = Date.now() + timeoutMs;
  let lastError = null;
  while (Date.now() < deadline) {
    try {
      if (await predicate()) {
        return;
      }
    } catch (error) {
      lastError = error;
    }
    await sleep(100);
  }
  throw new Error(`Timed out waiting for ${label}${lastError ? `: ${lastError.message}` : ""}.`);
}

async function expectText(locator, text, timeoutMs = 15000) {
  await waitFor(
    async () => (await locator.innerText()).includes(text),
    timeoutMs,
    `text '${text}'`,
  );
}

async function expectTextInsensitive(locator, text, timeoutMs = 10000) {
  const expected = text.toLowerCase();
  await waitFor(
    async () => (await locator.innerText()).toLowerCase().includes(expected),
    timeoutMs,
    `text '${text}'`,
  );
}

async function waitResponsiveSettled(page, width, timeoutMs = 15000) {
  await page.waitForFunction(
    (expectedWidth) => {
      const viewportWidth = window.innerWidth;
      const sidebar = document.getElementById("workspace-sidebar")?.getBoundingClientRect();
      const nav = document.getElementById("workspace-nav")?.getBoundingClientRect();
      const main = document.querySelector(".workbench-main")?.getBoundingClientRect();
      const documentWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0);
      if (!sidebar || !nav || !main || Math.abs(viewportWidth - expectedWidth) > 1) {
        return false;
      }
      const fullWidth = (rect) => Math.abs(rect.left) <= 1 && Math.abs(rect.right - viewportWidth) <= 1;
      if (expectedWidth <= 780) {
        return fullWidth(sidebar) && fullWidth(nav) && main.left <= 1 && main.right <= viewportWidth + 1 && documentWidth <= viewportWidth + 1;
      }
      return main.left >= 0 && main.right <= viewportWidth + 1 && documentWidth <= viewportWidth + 1;
    },
    width,
    { timeout: timeoutMs },
  );
}

function isBrokerMutationPath(pathname, search = "") {
  if (pathname === "/orders/submit") return true;
  if (pathname === "/strategies/bull-put/execute") return true;
  if (/^\/orders\/[^/]+\/(replace|cancel)$/.test(pathname)) return true;
  if (/^\/strategies\/bull-put\/spreads\/[^/]+\/(monitor|recover-close)$/.test(pathname)) return true;
  if (pathname.includes("/strategies/bull-put/runtime/") && pathname.endsWith("/scan") && search.includes("force=true")) return true;
  return /^\/strategies\/covered-call\/proposals\/[^/]+\/(execute|monitor|close|roll-execute|roll-continue)$/.test(pathname);
}

function createRequestObserver(page, { readPredicate = null, mutationPredicate = isBrokerMutationPath } = {}) {
  const requests = [];
  const readRequests = [];
  const mutationRequests = [];
  const listener = (request) => {
    const url = new URL(request.url());
    const evidence = {
      method: request.method(),
      path: `${url.pathname}${url.search}`,
      headers: request.headers(),
      postData: request.postData(),
      at: Date.now(),
    };
    requests.push(evidence);
    if (readPredicate?.(request, url)) {
      readRequests.push(evidence);
    }
    if (mutationPredicate?.(url.pathname, url.search, request)) {
      mutationRequests.push(evidence);
    }
  };
  page.on("request", listener);
  return {
    requests,
    readRequests,
    mutationRequests,
    dispose() {
      page.off("request", listener);
    },
  };
}

module.exports = {
  createRequestObserver,
  expectText,
  expectTextInsensitive,
  isBrokerMutationPath,
  resolveBrowserExecutable,
  sleep,
  waitFor,
  waitResponsiveSettled,
};

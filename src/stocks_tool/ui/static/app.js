const state = {
  accounts: [],
  selectedAccountId: "",
  watchlists: [],
  orders: [],
  snapshots: [],
  brokerStatus: null,
  latestSnapshot: null,
};

const els = {};

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  wireEvents();
  await loadDashboard();
});

function bindElements() {
  els.accountSelect = document.getElementById("account-select");
  els.statusBanner = document.getElementById("status-banner");
  els.metricsStrip = document.getElementById("metrics-strip");
  els.watchlistsBody = document.getElementById("watchlists-body");
  els.ordersBody = document.getElementById("orders-body");
  els.positionsBody = document.getElementById("positions-body");
  els.brokerStatus = document.getElementById("broker-status");
  els.quoteForm = document.getElementById("quote-form");
  els.quoteSymbol = document.getElementById("quote-symbol");
  els.quoteCard = document.getElementById("quote-card");
  els.refreshDashboard = document.getElementById("refresh-dashboard");
  els.syncAccount = document.getElementById("sync-account");
  els.syncOrders = document.getElementById("sync-orders");
}

function wireEvents() {
  els.accountSelect.addEventListener("change", async (event) => {
    state.selectedAccountId = event.target.value;
    await loadAccountData();
  });

  els.refreshDashboard.addEventListener("click", async () => {
    await loadDashboard();
  });

  els.syncAccount.addEventListener("click", async () => {
    if (!state.selectedAccountId) {
      setStatus("No broker account selected.", "warning");
      return;
    }
    await syncAccount();
  });

  els.syncOrders.addEventListener("click", async () => {
    if (!state.selectedAccountId) {
      setStatus("No broker account selected.", "warning");
      return;
    }
    await syncOrders();
  });

  els.quoteForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await loadQuote();
  });
}

async function loadDashboard() {
  setStatus("Loading dashboard...", "warning");
  try {
    const [accounts, watchlists, brokerStatus] = await Promise.all([
      fetchJson("/broker-accounts"),
      fetchJson("/watchlists"),
      fetchJson("/brokers/longbridge/configuration"),
    ]);

    state.accounts = accounts;
    state.watchlists = watchlists;
    state.brokerStatus = brokerStatus;

    if (!state.selectedAccountId && accounts.length > 0) {
      state.selectedAccountId = accounts[0].external_account_id;
    } else if (accounts.every((account) => account.external_account_id !== state.selectedAccountId)) {
      state.selectedAccountId = accounts[0]?.external_account_id || "";
    }

    renderAccountOptions();
    renderWatchlists();
    renderBrokerStatus();
    await loadAccountData();
    await loadQuote();
    setStatus("Dashboard updated.", "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Failed to load dashboard.", "error");
  }
}

async function loadAccountData() {
  if (!state.selectedAccountId) {
    state.snapshots = [];
    state.orders = [];
    state.latestSnapshot = null;
    renderMetrics();
    renderOrders();
    renderPositions();
    return;
  }

  try {
    const [snapshots, orders] = await Promise.all([
      fetchJson(`/account-snapshots?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/orders?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
    ]);
    state.snapshots = snapshots;
    state.orders = orders;
    state.latestSnapshot = snapshots[0] || null;
    renderMetrics();
    renderOrders();
    renderPositions();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Failed to load account data.", "error");
  }
}

async function loadQuote() {
  const symbol = els.quoteSymbol.value.trim().toUpperCase();
  if (!symbol) {
    els.quoteCard.className = "quote-card empty";
    els.quoteCard.textContent = "Enter a symbol.";
    return;
  }

  try {
    const quote = await fetchJson(`/brokers/longbridge/quote?symbol=${encodeURIComponent(symbol)}&mode=paper`);
    renderQuote(quote);
  } catch (error) {
    console.error(error);
    els.quoteCard.className = "quote-card";
    els.quoteCard.innerHTML = `<div class="pill error">Quote Error</div><div>${escapeHtml(error.message || "Unable to load quote.")}</div>`;
  }
}

async function syncAccount() {
  setStatus(`Syncing account ${state.selectedAccountId}...`, "warning");
  try {
    await fetchJson(`/brokers/longbridge/account-sync/${encodeURIComponent(state.selectedAccountId)}?mode=paper`, {
      method: "POST",
    });
    await loadAccountData();
    setStatus(`Account ${state.selectedAccountId} synced.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Account sync failed.", "error");
  }
}

async function syncOrders() {
  setStatus(`Syncing orders for ${state.selectedAccountId}...`, "warning");
  try {
    await fetchJson(`/orders/sync/longbridge/${encodeURIComponent(state.selectedAccountId)}?mode=paper`, {
      method: "POST",
    });
    await loadAccountData();
    setStatus(`Orders for ${state.selectedAccountId} synced.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order sync failed.", "error");
  }
}

function renderAccountOptions() {
  els.accountSelect.innerHTML = "";
  if (state.accounts.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No broker accounts";
    els.accountSelect.append(option);
    return;
  }

  for (const account of state.accounts) {
    const option = document.createElement("option");
    option.value = account.external_account_id;
    option.selected = account.external_account_id === state.selectedAccountId;
    option.textContent = `${account.display_name || account.external_account_id} · ${account.base_currency}`;
    els.accountSelect.append(option);
  }
}

function renderMetrics() {
  const snapshot = state.latestSnapshot;
  const values = [
    snapshot ? formatCurrency(snapshot.cash_balance, snapshot.currency) : "--",
    snapshot ? formatCurrency(snapshot.net_liquidation, snapshot.currency) : "--",
    snapshot ? formatCurrency(snapshot.buying_power, snapshot.currency) : "--",
    snapshot ? formatDateTime(snapshot.captured_at) : "--",
  ];

  const tiles = els.metricsStrip.querySelectorAll(".metric-value");
  tiles.forEach((tile, index) => {
    tile.textContent = values[index] || "--";
  });
}

function renderBrokerStatus() {
  const config = state.brokerStatus;
  if (!config) {
    els.brokerStatus.innerHTML = "";
    return;
  }

  const items = [
    ["App Key", config.app_key_configured ? "Configured" : "Missing"],
    ["App Secret", config.app_secret_configured ? "Configured" : "Missing"],
    ["Paper Token", config.paper_token_configured ? "Configured" : "Missing"],
    ["Live Token", config.live_token_configured ? "Configured" : "Missing"],
  ];

  els.brokerStatus.innerHTML = items
    .map(
      ([label, value]) => `
        <div>
          <dt>${escapeHtml(label)}</dt>
          <dd>${escapeHtml(value)}</dd>
        </div>
      `
    )
    .join("");
}

function renderWatchlists() {
  if (state.watchlists.length === 0) {
    els.watchlistsBody.innerHTML = '<div class="watchlist-block"><div class="watchlist-item">No watchlists found.</div></div>';
    return;
  }

  els.watchlistsBody.innerHTML = state.watchlists
    .map((watchlist) => {
      const items = watchlist.items.length
        ? watchlist.items
            .slice(0, 8)
            .map(
              (item) => `
                <div class="watchlist-item">
                  <div class="symbol-block">
                    <strong>${escapeHtml(item.symbol)}</strong>
                    <span>${escapeHtml(item.notes || item.asset_type)}</span>
                  </div>
                  <span class="pill neutral">${escapeHtml(item.asset_type)}</span>
                </div>
              `
            )
            .join("")
        : '<div class="watchlist-item">No symbols yet.</div>';

      return `
        <section class="watchlist-block">
          <div class="watchlist-head">
            <span class="watchlist-name">${escapeHtml(watchlist.name)}</span>
            <span class="watchlist-count">${watchlist.items.length} items</span>
          </div>
          <div class="watchlist-items">${items}</div>
        </section>
      `;
    })
    .join("");
}

function renderOrders() {
  if (state.orders.length === 0) {
    els.ordersBody.innerHTML = '<tr><td colspan="6" class="empty-row">No orders for this account.</td></tr>';
    return;
  }

  els.ordersBody.innerHTML = state.orders
    .slice(0, 10)
    .map((order) => {
      const pillClass = statusClass(order.status);
      return `
        <tr>
          <td>${escapeHtml(order.symbol)}</td>
          <td>${escapeHtml(order.side.toUpperCase())}</td>
          <td>${escapeHtml(String(order.quantity))}</td>
          <td><span class="pill ${pillClass}">${escapeHtml(order.status)}</span></td>
          <td>${order.limit_price ? escapeHtml(order.limit_price) : "--"}</td>
          <td>${escapeHtml(formatDateTime(order.updated_at))}</td>
        </tr>
      `;
    })
    .join("");
}

function renderPositions() {
  const positions = state.latestSnapshot?.positions || [];
  if (positions.length === 0) {
    els.positionsBody.innerHTML = '<tr><td colspan="5" class="empty-row">No positions in latest snapshot.</td></tr>';
    return;
  }

  els.positionsBody.innerHTML = positions
    .map(
      (position) => `
        <tr>
          <td>${escapeHtml(position.symbol)}</td>
          <td>${escapeHtml(String(position.quantity))}</td>
          <td>${escapeHtml(position.average_cost)}</td>
          <td>${escapeHtml(position.market_value)}</td>
          <td>${escapeHtml(position.unrealized_pnl)}</td>
        </tr>
      `
    )
    .join("");
}

function renderQuote(quote) {
  const lastDone = Number(quote.last_done);
  const prevClose = Number(quote.prev_close);
  const diff = lastDone - prevClose;
  const pct = prevClose === 0 ? 0 : (diff / prevClose) * 100;
  const changeClass = diff >= 0 ? "positive" : "negative";
  const changePrefix = diff >= 0 ? "+" : "";

  els.quoteCard.className = "quote-card";
  els.quoteCard.innerHTML = `
    <div>
      <span class="section-kicker">${escapeHtml(quote.symbol)}</span>
      <div class="quote-price">
        <strong>${formatNumber(quote.last_done)}</strong>
        <span class="quote-change ${changeClass}">${changePrefix}${formatNumber(diff.toFixed(2))} · ${changePrefix}${pct.toFixed(2)}%</span>
      </div>
    </div>
    <div class="quote-meta">
      <div><span>Open</span><strong>${formatNumber(quote.open)}</strong></div>
      <div><span>Prev Close</span><strong>${formatNumber(quote.prev_close)}</strong></div>
      <div><span>High</span><strong>${formatNumber(quote.high)}</strong></div>
      <div><span>Low</span><strong>${formatNumber(quote.low)}</strong></div>
      <div><span>Volume</span><strong>${Number(quote.volume).toLocaleString()}</strong></div>
      <div><span>Timestamp</span><strong>${escapeHtml(formatDateTime(quote.timestamp))}</strong></div>
    </div>
  `;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });

  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (payload?.detail) {
        detail = payload.detail;
      }
    } catch {
      // ignore
    }
    throw new Error(detail);
  }

  return response.json();
}

function setStatus(message, tone = "") {
  els.statusBanner.textContent = message;
  els.statusBanner.className = "status-banner";
  if (tone) {
    els.statusBanner.classList.add(tone);
  }
}

function formatCurrency(value, currency = "USD") {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(number);
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return number.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatDateTime(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    hour12: false,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusClass(status) {
  if (status === "filled") {
    return "success";
  }
  if (status === "canceled" || status === "rejected") {
    return "error";
  }
  if (status === "submitted" || status === "partially_filled") {
    return "warning";
  }
  return "neutral";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

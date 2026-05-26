const state = {
  accounts: [],
  selectedAccountId: "",
  watchlists: [],
  orders: [],
  spreads: [],
  runtime: null,
  executions: [],
  journals: [],
  brokerStatus: null,
  latestSnapshot: null,
  selectedOrderId: "",
  quote: null,
  quoteStatus: { kind: "idle", detail: "No quote loaded.", reason: "" },
  preOpenAssessment: null,
  preOpenStatus: { kind: "loading", detail: "Loading pre-open assessment...", reason: "" },
  preOpenRuns: [],
};

const els = {};

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  wireEvents();
  syncTicketOrderFields();
  renderSelectedOrder();
  await loadDashboard();
});

function bindElements() {
  els.accountSelect = document.getElementById("account-select");
  els.statusBanner = document.getElementById("status-banner");
  els.reconciliationStrip = document.getElementById("reconciliation-strip");
  els.metricsStrip = document.getElementById("metrics-strip");
  els.positionsSummaryStrip = document.getElementById("positions-summary-strip");
  els.holdingsFocus = document.getElementById("holdings-focus");
  els.watchlistsBody = document.getElementById("watchlists-body");
  els.strategyRuntimeStrip = document.getElementById("strategy-runtime-strip");
  els.strategyControlsForm = document.getElementById("strategy-controls-form");
  els.strategyAutoEntry = document.getElementById("strategy-auto-entry");
  els.strategyManualPause = document.getElementById("strategy-manual-pause");
  els.strategyKillSwitch = document.getElementById("strategy-kill-switch");
  els.strategyPausedSymbols = document.getElementById("strategy-paused-symbols");
  els.strategyControlsHint = document.getElementById("strategy-controls-hint");
  els.saveStrategyControls = document.getElementById("save-strategy-controls");
  els.runStrategyScan = document.getElementById("run-strategy-scan");
  els.runStrategyReview = document.getElementById("run-strategy-review");
  els.strategySkipCard = document.getElementById("strategy-skip-card");
  els.strategyJournalFeed = document.getElementById("strategy-journal-feed");
  els.strategyReviewCard = document.getElementById("strategy-review-card");
  els.spreadSummaryStrip = document.getElementById("spread-summary-strip");
  els.spreadsBody = document.getElementById("spreads-body");
  els.ordersBody = document.getElementById("orders-body");
  els.positionsBody = document.getElementById("positions-body");
  els.brokerStatus = document.getElementById("broker-status");
  els.quoteForm = document.getElementById("quote-form");
  els.quoteSymbol = document.getElementById("quote-symbol");
  els.quoteCard = document.getElementById("quote-card");
  els.preOpenSummaryStrip = document.getElementById("preopen-summary-strip");
  els.preOpenAssessmentCard = document.getElementById("preopen-assessment-card");
  els.preOpenSignals = document.getElementById("preopen-signals");
  els.preOpenPuts = document.getElementById("preopen-puts");
  els.preOpenChainAnalysis = document.getElementById("preopen-chain-analysis");
  els.preOpenRunReview = document.getElementById("preopen-run-review");
  els.refreshDashboard = document.getElementById("refresh-dashboard");
  els.syncAccount = document.getElementById("sync-account");
  els.syncOrders = document.getElementById("sync-orders");
  els.orderTicketForm = document.getElementById("order-ticket-form");
  els.orderSymbol = document.getElementById("order-symbol");
  els.orderSide = document.getElementById("order-side");
  els.orderQuantity = document.getElementById("order-quantity");
  els.orderType = document.getElementById("order-type");
  els.orderTimeInForce = document.getElementById("order-time-in-force");
  els.orderLimitField = document.getElementById("order-limit-field");
  els.orderLimitPrice = document.getElementById("order-limit-price");
  els.orderStopField = document.getElementById("order-stop-field");
  els.orderStopPrice = document.getElementById("order-stop-price");
  els.orderRemark = document.getElementById("order-remark");
  els.orderFormHint = document.getElementById("order-form-hint");
  els.submitOrder = document.getElementById("submit-order");
  els.selectedOrderCard = document.getElementById("selected-order-card");
  els.selectedOrderExecution = document.getElementById("selected-order-execution");
  els.journalEntryForm = document.getElementById("journal-entry-form");
  els.journalEntryType = document.getElementById("journal-entry-type");
  els.journalTitle = document.getElementById("journal-title");
  els.journalTags = document.getElementById("journal-tags");
  els.journalNotes = document.getElementById("journal-notes");
  els.journalFormHint = document.getElementById("journal-form-hint");
  els.submitJournal = document.getElementById("submit-journal");
  els.selectedOrderJournal = document.getElementById("selected-order-journal");
  els.replaceOrderForm = document.getElementById("replace-order-form");
  els.replaceQuantity = document.getElementById("replace-quantity");
  els.replaceLimitField = document.getElementById("replace-limit-field");
  els.replaceLimitPrice = document.getElementById("replace-limit-price");
  els.replaceStopField = document.getElementById("replace-stop-field");
  els.replaceStopPrice = document.getElementById("replace-stop-price");
  els.replaceRemark = document.getElementById("replace-remark");
  els.replaceFormHint = document.getElementById("replace-form-hint");
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

  els.strategyControlsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveStrategyControls();
  });

  els.runStrategyScan.addEventListener("click", async () => {
    await runStrategyScan();
  });

  els.runStrategyReview.addEventListener("click", async () => {
    await runStrategyReview();
  });

  els.orderType.addEventListener("change", () => {
    syncTicketOrderFields();
  });

  els.orderTicketForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitOrder();
  });

  els.ordersBody.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-order-action]");
    if (!button) {
      return;
    }

    const { orderAction, orderId } = button.dataset;
    if (!orderAction || !orderId) {
      return;
    }

    if (orderAction === "manage") {
      setSelectedOrder(orderId, true);
      return;
    }

    if (orderAction === "refresh") {
      await refreshOrder(orderId);
      return;
    }

    if (orderAction === "cancel") {
      await cancelOrder(orderId);
    }
  });

  els.spreadsBody.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-spread-action]");
    if (!button) {
      return;
    }

    const { spreadAction, spreadId } = button.dataset;
    if (!spreadAction || !spreadId) {
      return;
    }

    if (spreadAction === "refresh") {
      await refreshSpread(spreadId);
      return;
    }

    if (spreadAction === "monitor") {
      await monitorSpread(spreadId);
    }
  });

  els.selectedOrderCard.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-selected-action]");
    if (!button) {
      return;
    }

    const action = button.dataset.selectedAction;
    const order = getSelectedOrder();
    if (!action || !order) {
      return;
    }

    if (action === "refresh") {
      await refreshOrder(order.id);
      return;
    }

    if (action === "cancel") {
      await cancelOrder(order.id);
    }
  });

  els.replaceOrderForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await replaceSelectedOrder();
  });

  els.journalEntryForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await submitJournalEntry();
  });
}

async function loadDashboard() {
  setStatus("Loading dashboard...", "warning");
  try {
    const [watchlists, brokerStatus] = await Promise.all([
      fetchJson("/watchlists"),
      fetchJson("/brokers/longbridge/configuration"),
    ]);

    state.watchlists = watchlists;
    state.brokerStatus = brokerStatus;
    await refreshAccounts();
    renderWatchlists();
    renderBrokerStatus();
    await loadAccountData();
    loadMarketOverlayPanels();
    setStatus("Dashboard updated. Market overlays are refreshing in the background.", "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Failed to load dashboard.", "error");
  }
}

async function loadAccountData() {
  if (!state.selectedAccountId) {
    state.orders = [];
    state.spreads = [];
    state.runtime = null;
    state.executions = [];
    state.journals = [];
    state.preOpenRuns = [];
    state.latestSnapshot = null;
    state.selectedOrderId = "";
    renderReconciliationStatus();
    renderMetrics();
    renderHoldings();
    renderLatestPreOpenRun();
    renderStrategyRuntime();
    renderSpreads();
    renderOrders();
    renderPositions();
    renderSelectedOrder();
    updateSyncButtons();
    updateOrderTicketAvailability();
    return;
  }

  try {
    const [latestSnapshot, orders, spreads, runtime, executions, journals, preOpenRuns] = await Promise.all([
      fetchJson(`/account-snapshots/latest?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/orders?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/strategies/bull-put/spreads?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/strategies/bull-put/runtime?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/executions?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/journals?external_account_id=${encodeURIComponent(state.selectedAccountId)}`),
      fetchJson(`/strategies/pre-open-runs?external_account_id=${encodeURIComponent(state.selectedAccountId)}&limit=1`),
    ]);
    state.orders = orders;
    state.spreads = spreads;
    state.runtime = runtime;
    state.executions = executions;
    state.journals = journals;
    state.preOpenRuns = preOpenRuns;
    state.latestSnapshot = latestSnapshot;

    if (!orders.some((order) => order.id === state.selectedOrderId)) {
      state.selectedOrderId = orders[0]?.id || "";
    }

    renderReconciliationStatus();
    renderMetrics();
    renderHoldings();
    renderLatestPreOpenRun();
    renderStrategyRuntime();
    renderSpreads();
    renderOrders();
    renderPositions();
    renderSelectedOrder();
    updateSyncButtons();
    updateOrderTicketAvailability();
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Failed to load account data.", "error");
  }
}

function loadMarketOverlayPanels() {
  void loadQuote({ timeoutMs: 5000 });
  void loadPreOpenAssessment({ timeoutMs: 6000 });
}

async function loadQuote(options = {}) {
  const { timeoutMs = 8000 } = options;
  const symbol = els.quoteSymbol.value.trim().toUpperCase();
  if (!symbol) {
    state.quote = null;
    state.quoteStatus = buildOverlayStatus("idle", "Enter a symbol.");
    renderQuote();
    return;
  }

  const hasMatchingQuote = state.quote && state.quote.symbol === symbol;
  if (!hasMatchingQuote) {
    state.quote = null;
  }
  state.quoteStatus = buildOverlayStatus("loading", `Refreshing ${symbol} quote...`);
  renderQuote();

  try {
    state.quote = await fetchJson(
      `/brokers/longbridge/quote?symbol=${encodeURIComponent(symbol)}&mode=paper`,
      { timeoutMs }
    );
    state.quoteStatus = buildOverlayStatus("live", overlayLiveDetail("Quote", state.quote.timestamp));
    renderQuote();
  } catch (error) {
    console.error(error);
    const hasStaleQuote = state.quote && state.quote.symbol === symbol;
    if (!hasStaleQuote) {
      state.quote = null;
    }
    state.quoteStatus = classifyOverlayFailure(error, {
      label: "quote",
      stale: hasStaleQuote,
      staleAt: state.quote?.timestamp,
    });
    renderQuote();
  }
}

async function loadPreOpenAssessment(options = {}) {
  const { timeoutMs = 10000 } = options;
  state.preOpenStatus = buildOverlayStatus("loading", "Refreshing pre-open board...");
  renderPreOpenAssessment();

  try {
    state.preOpenAssessment = await fetchJson("/strategies/pre-open-risk", { timeoutMs });
    state.preOpenStatus = buildOverlayStatus(
      "live",
      overlayLiveDetail("Pre-open board", state.preOpenAssessment.analyzed_at)
    );
    renderPreOpenAssessment();
  } catch (error) {
    console.error(error);
    state.preOpenStatus = classifyOverlayFailure(error, {
      label: "pre-open board",
      stale: Boolean(state.preOpenAssessment),
      staleAt: state.preOpenAssessment?.analyzed_at,
    });
    renderPreOpenAssessment();
  }
}

async function syncAccount() {
  setStatus(`Syncing account ${state.selectedAccountId}...`, "warning");
  try {
    await fetchJson(`/brokers/longbridge/account-sync/${encodeURIComponent(state.selectedAccountId)}?mode=paper`, {
      method: "POST",
    });
    await refreshAccounts();
    await loadAccountData();
    setStatus(`Account ${state.selectedAccountId} synced.`, "success");
  } catch (error) {
    console.error(error);
    await refreshAccountsSilently();
    setStatus(error.message || "Account sync failed.", "error");
  }
}

async function syncOrders() {
  setStatus(`Syncing orders for ${state.selectedAccountId}...`, "warning");
  try {
    await fetchJson(`/orders/sync/longbridge/${encodeURIComponent(state.selectedAccountId)}?mode=paper`, {
      method: "POST",
    });
    await refreshAccounts();
    await loadAccountData();
    setStatus(`Orders for ${state.selectedAccountId} synced.`, "success");
  } catch (error) {
    console.error(error);
    await refreshAccountsSilently();
    setStatus(error.message || "Order sync failed.", "error");
  }
}

async function saveStrategyControls() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before updating strategy controls.", "warning");
    return;
  }

  const payload = {
    auto_entry_enabled: els.strategyAutoEntry.value === "true",
    manual_pause: els.strategyManualPause.value === "true",
    kill_switch_active: els.strategyKillSwitch.value === "true",
    paused_symbols: parseSymbolList(els.strategyPausedSymbols.value),
  };

  setStatus(`Saving bull put controls for ${state.selectedAccountId}...`, "warning");
  try {
    await fetchJson(`/strategies/bull-put/runtime/${encodeURIComponent(state.selectedAccountId)}?mode=paper`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await loadAccountData();
    setStatus(`Bull put controls updated for ${state.selectedAccountId}.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Bull put controls update failed.", "error");
  }
}

async function runStrategyScan() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before running a bull put scan.", "warning");
    return;
  }

  setStatus(`Running bull put scan for ${state.selectedAccountId}...`, "warning");
  try {
    const result = await fetchJson(
      `/strategies/bull-put/runtime/${encodeURIComponent(state.selectedAccountId)}/scan?mode=paper&force=true`,
      {
        method: "POST",
      }
    );
    await loadAccountData();
    const message = result.executed
      ? `Bull put scan opened ${result.executed_spread?.underlying_symbol || "a spread"}.`
      : result.reason || "Bull put scan completed without a new spread.";
    setStatus(message, result.executed ? "success" : "warning");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Bull put scan failed.", "error");
  }
}

async function runStrategyReview() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before running a bull put review.", "warning");
    return;
  }

  setStatus(`Running bull put review for ${state.selectedAccountId}...`, "warning");
  try {
    const result = await fetchJson(
      `/strategies/bull-put/runtime/${encodeURIComponent(state.selectedAccountId)}/review?mode=paper&force=true`,
      {
        method: "POST",
      }
    );
    await loadAccountData();
    const message = result.recommendation || result.reason || result.strategy_state?.last_review_summary || "Bull put review completed.";
    setStatus(message, result.review_status === "suggested" ? "success" : "warning");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Bull put review failed.", "error");
  }
}

async function refreshAccounts() {
  const accounts = await fetchJson("/broker-accounts");
  applyAccounts(accounts);
}

async function refreshAccountsSilently() {
  try {
    await refreshAccounts();
  } catch (error) {
    console.error(error);
  }
}

function applyAccounts(accounts) {
  state.accounts = accounts;

  if (!state.selectedAccountId && accounts.length > 0) {
    state.selectedAccountId = accounts[0].external_account_id;
  } else if (accounts.every((account) => account.external_account_id !== state.selectedAccountId)) {
    state.selectedAccountId = accounts[0]?.external_account_id || "";
  }

  renderAccountOptions();
  renderReconciliationStatus();
  updateSyncButtons();
  updateOrderTicketAvailability();
}

async function submitOrder() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before submitting an order.", "warning");
    return;
  }

  try {
    const payload = buildCreateOrderPayload();
    setStatus(`Submitting ${payload.side.toUpperCase()} ${payload.symbol}...`, "warning");
    const created = await fetchJson("/orders/submit", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.selectedOrderId = created.id;
    els.orderRemark.value = "";
    await loadAccountData();
    setSelectedOrder(created.id);
    setStatus(`Order submitted for ${created.symbol}.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order submission failed.", "error");
  }
}

async function refreshOrder(orderId) {
  const order = state.orders.find((item) => item.id === orderId);
  setStatus(`Refreshing order ${order?.symbol || orderId}...`, "warning");
  try {
    const refreshed = await fetchJson(`/orders/${encodeURIComponent(orderId)}/refresh`, {
      method: "POST",
    });
    state.selectedOrderId = refreshed.id;
    await loadAccountData();
    setSelectedOrder(refreshed.id);
    setStatus(`Order ${refreshed.symbol} refreshed.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order refresh failed.", "error");
  }
}

async function refreshSpread(spreadId) {
  const spread = state.spreads.find((item) => item.id === spreadId);
  setStatus(`Refreshing spread ${spread?.underlying_symbol || spreadId}...`, "warning");
  try {
    const refreshed = await fetchJson(`/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}/refresh`, {
      method: "POST",
    });
    await loadAccountData();
    setStatus(`Spread ${refreshed.underlying_symbol} refreshed.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Spread refresh failed.", "error");
  }
}

async function monitorSpread(spreadId) {
  const spread = state.spreads.find((item) => item.id === spreadId);
  setStatus(`Monitoring spread ${spread?.underlying_symbol || spreadId}...`, "warning");
  try {
    const result = await fetchJson(`/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}/monitor`, {
      method: "POST",
    });
    await loadAccountData();
    const action = result.should_close
      ? `Exit action ${formatSpreadExitReason(result.exit_reason)} evaluated for ${result.spread.underlying_symbol}.`
      : `Spread ${result.spread.underlying_symbol} remains within thresholds.`;
    setStatus(action, result.should_close ? "success" : "warning");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Spread monitor failed.", "error");
  }
}

async function cancelOrder(orderId) {
  const order = state.orders.find((item) => item.id === orderId);
  if (!order) {
    setStatus("Order not found in the current table.", "error");
    return;
  }
  if (!isCancelableOrder(order)) {
    setStatus("This order can no longer be canceled.", "warning");
    return;
  }
  if (!window.confirm(`Cancel order ${order.symbol} ${order.side.toUpperCase()} ${order.quantity}?`)) {
    return;
  }

  setStatus(`Canceling order ${order.symbol}...`, "warning");
  try {
    const canceled = await fetchJson(`/orders/${encodeURIComponent(orderId)}/cancel`, {
      method: "POST",
    });
    state.selectedOrderId = canceled.id;
    await loadAccountData();
    setSelectedOrder(canceled.id);
    setStatus(`Order ${canceled.symbol} canceled.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order cancel failed.", "error");
  }
}

async function replaceSelectedOrder() {
  const order = getSelectedOrder();
  if (!order) {
    setStatus("Select an order before replacing it.", "warning");
    return;
  }
  if (!isReplaceableOrder(order)) {
    setStatus("Only working orders can be replaced.", "warning");
    return;
  }

  try {
    const payload = buildReplaceOrderPayload(order);
    setStatus(`Replacing order ${order.symbol}...`, "warning");
    const updated = await fetchJson(`/orders/${encodeURIComponent(order.id)}/replace`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.selectedOrderId = updated.id;
    els.replaceRemark.value = "";
    await loadAccountData();
    setSelectedOrder(updated.id);
    setStatus(`Order ${updated.symbol} updated.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Order replace failed.", "error");
  }
}

async function submitJournalEntry() {
  const order = getSelectedOrder();
  if (!order) {
    setStatus("Select an order before saving a journal entry.", "warning");
    return;
  }

  try {
    const title = els.journalTitle.value.trim();
    const notes = els.journalNotes.value.trim();
    if (!title) {
      throw new Error("Journal title is required.");
    }
    if (!notes) {
      throw new Error("Journal notes are required.");
    }

    const execution = getSelectedExecution();
    const payload = {
      external_account_id: order.external_account_id,
      symbol: order.symbol,
      entry_type: els.journalEntryType.value,
      title,
      notes,
      order_id: order.id,
      trade_plan_id: order.trade_plan_id,
      execution_id: execution?.id || null,
      tags: parseTags(els.journalTags.value),
    };
    setStatus(`Saving ${payload.entry_type} entry for ${order.symbol}...`, "warning");
    const created = await fetchJson("/journals", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.journals = [created, ...state.journals.filter((entry) => entry.id !== created.id)];
    els.journalTitle.value = "";
    els.journalTags.value = "";
    els.journalNotes.value = "";
    renderSelectedJournal();
    setStatus(`Journal entry saved for ${created.symbol}.`, "success");
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Journal entry save failed.", "error");
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
    option.textContent = `${account.display_name || account.external_account_id} / ${account.base_currency}`;
    els.accountSelect.append(option);
  }
}

function renderReconciliationStatus() {
  const account = getSelectedAccount();
  if (!account) {
    els.reconciliationStrip.innerHTML = `
      <article class="reconciliation-card">
        <div class="reconciliation-head">
          <span class="metric-label">Auto Reconciliation</span>
          <span class="pill neutral">--</span>
        </div>
        <strong class="reconciliation-value">--</strong>
        <span class="reconciliation-detail">Select a broker account to view scheduler state.</span>
      </article>
      <article class="reconciliation-card">
        <div class="reconciliation-head">
          <span class="metric-label">Account Sync</span>
          <span class="pill neutral">--</span>
        </div>
        <strong class="reconciliation-value">--</strong>
        <span class="reconciliation-detail">No account selected.</span>
      </article>
      <article class="reconciliation-card">
        <div class="reconciliation-head">
          <span class="metric-label">Orders Sync</span>
          <span class="pill neutral">--</span>
        </div>
        <strong class="reconciliation-value">--</strong>
        <span class="reconciliation-detail">No account selected.</span>
      </article>
    `;
    return;
  }

  const cards = [
    {
      label: "Auto Reconciliation",
      tone: account.auto_reconcile_enabled ? "success" : "neutral",
      badge: account.auto_reconcile_enabled ? "Enabled" : "Disabled",
      value: account.auto_reconcile_enabled ? "Enabled" : "Disabled",
      detail: account.auto_reconcile_enabled
        ? "Background polling is active for this paper account."
        : "Automatic polling is disabled for this account.",
    },
    {
      label: "Account Sync",
      tone: reconciliationTone(account.account_sync_status),
      badge: reconciliationLabel(account.account_sync_status),
      value: formatSyncHeadline(account.account_last_synced_at, account.account_last_sync_attempt_at),
      detail: formatSyncDetail(
        account.account_sync_status,
        account.account_last_synced_at,
        account.account_last_sync_attempt_at,
        account.account_last_sync_error
      ),
    },
    {
      label: "Orders Sync",
      tone: reconciliationTone(account.orders_sync_status),
      badge: reconciliationLabel(account.orders_sync_status),
      value: formatSyncHeadline(account.orders_last_synced_at, account.orders_last_sync_attempt_at),
      detail: formatSyncDetail(
        account.orders_sync_status,
        account.orders_last_synced_at,
        account.orders_last_sync_attempt_at,
        account.orders_last_sync_error
      ),
    },
  ];

  els.reconciliationStrip.innerHTML = cards
    .map(
      (card) => `
        <article class="reconciliation-card">
          <div class="reconciliation-head">
            <span class="metric-label">${escapeHtml(card.label)}</span>
            <span class="pill ${escapeHtml(card.tone)}">${escapeHtml(card.badge)}</span>
          </div>
          <strong class="reconciliation-value">${escapeHtml(card.value)}</strong>
          <span class="reconciliation-detail">${escapeHtml(card.detail)}</span>
        </article>
      `
    )
    .join("");
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

function renderHoldings() {
  const snapshot = state.latestSnapshot;
  const positions = buildSortedPositions(snapshot?.positions || []);
  const currency = snapshot?.currency || "USD";
  const grossMarketValue = positions.reduce((sum, position) => sum + toFiniteNumber(position.market_value), 0);
  const totalUnrealizedPnl = positions.reduce((sum, position) => sum + toFiniteNumber(position.unrealized_pnl), 0);
  const largestHolding = positions[0] || null;
  const profitableCount = positions.filter((position) => toNumber(position.unrealized_pnl) > 0).length;
  const losingCount = positions.filter((position) => toNumber(position.unrealized_pnl) < 0).length;
  const summaryValues = [
    {
      label: "Open Positions",
      value: String(positions.length),
      tone: "",
      detail: positions.length ? `${profitableCount} profitable / ${losingCount} losing` : "No active holdings",
    },
    {
      label: "Gross Market Value",
      value: positions.length ? formatCurrency(grossMarketValue, currency) : "--",
      tone: "",
      detail: positions.length ? `Latest snapshot ${formatDateTime(snapshot?.captured_at)}` : "Sync account to load holdings",
    },
    {
      label: "Unrealized PnL",
      value: positions.length ? formatSignedCurrency(totalUnrealizedPnl, currency) : "--",
      tone: pnlTone(totalUnrealizedPnl),
      detail: positions.length ? `${formatPercent(totalUnrealizedPnl, grossMarketValue)}` : "No open positions",
    },
    {
      label: "Largest Holding",
      value: largestHolding ? largestHolding.symbol : "--",
      tone: "",
      detail: largestHolding ? `${formatCurrency(largestHolding.market_value, currency)} / ${formatWeight(largestHolding.market_value, grossMarketValue)}` : "No ranked holdings",
    },
  ];

  els.positionsSummaryStrip.innerHTML = summaryValues
    .map(
      (item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  if (positions.length === 0) {
    els.holdingsFocus.innerHTML = '<div class="holding-empty">No positions in latest snapshot.</div>';
    return;
  }

  els.holdingsFocus.innerHTML = positions
    .slice(0, 5)
    .map((position) => {
      const pnl = toNumber(position.unrealized_pnl);
      const tone = pnlTone(pnl);
      return `
        <article class="holding-card">
          <div class="holding-head">
            <div class="symbol-block">
              <strong>${escapeHtml(position.symbol)}</strong>
              <span>${escapeHtml(position.asset_type.toUpperCase())} / ${escapeHtml(formatWeight(position.market_value, grossMarketValue))}</span>
            </div>
            <span class="pill ${tone}">${escapeHtml(formatSignedCurrency(position.unrealized_pnl, currency))}</span>
          </div>
          <div class="holding-stats">
            <div>
              <span>Quantity</span>
              <strong>${escapeHtml(formatPositionQuantity(position.quantity))}</strong>
            </div>
            <div>
              <span>Avg Cost</span>
              <strong>${escapeHtml(formatCurrency(position.average_cost, currency))}</strong>
            </div>
            <div>
              <span>Market Value</span>
              <strong>${escapeHtml(formatCurrency(position.market_value, currency))}</strong>
            </div>
          </div>
        </article>
      `;
    })
    .join("");
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

function renderStrategyRuntime() {
  const runtime = state.runtime;
  if (!runtime) {
    els.strategyRuntimeStrip.innerHTML = `
      <article class="mini-metric-tile">
        <span class="metric-label">Entry Status</span>
        <strong class="mini-metric-value">--</strong>
        <span class="mini-metric-detail">Select a broker account to load bull put controls.</span>
      </article>
    `;
    els.strategySkipCard.className = "strategy-note-body empty";
    els.strategySkipCard.textContent = "No bull put scan has been skipped yet.";
    els.strategyJournalFeed.className = "strategy-note-body empty";
    els.strategyJournalFeed.textContent = "No bull put strategy notes for this account yet.";
    els.strategyReviewCard.className = "strategy-note-body empty";
    els.strategyReviewCard.textContent = "No bull put strategy review has been generated yet.";
    els.strategyControlsHint.textContent = "Strategy controls apply to new bull put entries only. Existing spreads remain monitored.";
    els.strategyAutoEntry.value = "true";
    els.strategyManualPause.value = "false";
    els.strategyKillSwitch.value = "false";
    els.strategyPausedSymbols.value = "";
    updateStrategyButtons();
    return;
  }

  const statusSummary = describeStrategyStatus(runtime);
  const summaryValues = [
    {
      label: "Entry Status",
      value: statusSummary.value,
      tone: statusSummary.tone,
      detail: statusSummary.detail,
    },
    {
      label: "Daily Entries",
      value: `${runtime.daily_entry_count}`,
      tone: runtime.daily_entry_count > 0 ? "success" : "",
      detail: `Cap ${state.spreads.length ? "tracked with active spreads" : "ready for first spread"}`,
    },
    {
      label: "Daily Realized PnL",
      value: formatSignedCurrency(runtime.daily_realized_pnl, "USD"),
      tone: pnlTone(runtime.daily_realized_pnl),
      detail: runtime.current_session_date ? `Session ${runtime.current_session_date}` : "No tracked session date",
    },
    {
      label: "Last Scan",
      value: runtime.last_scan_result ? formatRuntimeScanResult(runtime.last_scan_result) : "--",
      tone: runtime.last_scan_result === "executed" ? "success" : runtime.last_scan_result === "skipped" ? "warning" : "",
      detail: runtime.last_scan_at
        ? `${runtime.last_scan_symbol || "Account"} / ${formatDateTime(runtime.last_scan_at)}`
        : "Waiting for first bull put scan",
    },
  ];

  els.strategyRuntimeStrip.innerHTML = summaryValues
    .map(
      (item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  els.strategyAutoEntry.value = runtime.auto_entry_enabled ? "true" : "false";
  els.strategyManualPause.value = runtime.manual_pause ? "true" : "false";
  els.strategyKillSwitch.value = runtime.kill_switch_active ? "true" : "false";
  els.strategyPausedSymbols.value = (runtime.paused_symbols || []).join(", ");
  els.strategyControlsHint.textContent = runtime.last_action
    ? `${runtime.last_action}${runtime.last_action_at ? ` (${formatDateTime(runtime.last_action_at)})` : ""}`
    : "Strategy controls apply to new bull put entries only. Existing spreads remain monitored.";

  const skipReason = runtime.last_skip_reason || "No bull put skip reason recorded.";
  els.strategySkipCard.className = `strategy-note-body ${runtime.last_skip_reason ? "" : "empty"}`;
  els.strategySkipCard.textContent = skipReason;

  const strategyNotes = state.journals.filter((entry) =>
    Array.isArray(entry.tags) && entry.tags.some((tag) => String(tag).toLowerCase() === "bull-put")
  );
  const reviewSummary = runtime.last_review_summary || "No bull put strategy review has been generated yet.";
  els.strategyReviewCard.className = `strategy-note-body ${runtime.last_review_summary ? "" : "empty"}`;
  els.strategyReviewCard.textContent = runtime.last_review_at
    ? `${reviewSummary} (${formatDateTime(runtime.last_review_at)})`
    : reviewSummary;
  if (strategyNotes.length === 0) {
    els.strategyJournalFeed.className = "strategy-note-body empty";
    els.strategyJournalFeed.textContent = "No bull put strategy notes for this account yet.";
  } else {
    els.strategyJournalFeed.className = "strategy-note-body";
    els.strategyJournalFeed.innerHTML = strategyNotes
      .slice(0, 4)
      .map(
        (entry) => `
          <article class="strategy-journal-entry">
            <div class="strategy-journal-head">
              <strong>${escapeHtml(entry.title)}</strong>
              <span>${escapeHtml(formatDateTime(entry.updated_at))}</span>
            </div>
            <p>${escapeHtml(entry.notes)}</p>
          </article>
        `
      )
      .join("");
  }

  updateStrategyButtons();
}

function renderSpreads() {
  const spreads = [...state.spreads].sort(
    (left, right) => new Date(right.updated_at || 0).getTime() - new Date(left.updated_at || 0).getTime()
  );
  const activeSpreads = spreads.filter(isActiveSpread);
  const exitPendingSpreads = spreads.filter(isExitPendingSpread);
  const latestActionSpread = spreads.find((spread) => spread.exit_reason) || null;
  const lastMonitoredSpread = spreads.find((spread) => spread.last_synced_at) || null;

  const summaryValues = [
    {
      label: "Active Spreads",
      value: String(activeSpreads.length),
      tone: "",
      detail: activeSpreads.length
        ? `${activeSpreads.filter((spread) => spread.status === "open").length} open / ${exitPendingSpreads.length} exit pending`
        : "No active spreads",
    },
    {
      label: "Exit Pending",
      value: String(exitPendingSpreads.length),
      tone: exitPendingSpreads.length ? "warning" : "",
      detail: exitPendingSpreads.length
        ? `${exitPendingSpreads.map((spread) => spread.underlying_symbol).slice(0, 3).join(", ")}`
        : "No pending spread exits",
    },
    {
      label: "Latest Exit Action",
      value: latestActionSpread ? formatSpreadExitReason(latestActionSpread.exit_reason) : "--",
      tone: latestActionSpread ? spreadStatusClass(latestActionSpread.status) : "",
      detail: latestActionSpread
        ? `${latestActionSpread.underlying_symbol} / ${formatDateTime(latestActionSpread.updated_at)}`
        : "No exit actions recorded yet",
    },
    {
      label: "Last Monitor",
      value: lastMonitoredSpread ? formatDateTime(lastMonitoredSpread.last_synced_at) : "--",
      tone: "",
      detail: lastMonitoredSpread
        ? `${lastMonitoredSpread.underlying_symbol} / ${formatSpreadStatusLabel(lastMonitoredSpread.status)}`
        : "Waiting for first monitor run",
    },
  ];

  els.spreadSummaryStrip.innerHTML = summaryValues
    .map(
      (item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  if (spreads.length === 0) {
    els.spreadsBody.innerHTML = '<tr><td colspan="8" class="empty-row">No bull put spreads for this account.</td></tr>';
    return;
  }

  els.spreadsBody.innerHTML = spreads
    .map((spread) => {
      const monitorable = isMonitorableSpread(spread);
      const statusTone = spreadStatusClass(spread.status);
      const actionText = spread.exit_reason ? formatSpreadExitReason(spread.exit_reason) : "--";
      const legSummary = `${formatSpreadStrike(spread.long_strike)} / ${formatSpreadStrike(spread.short_strike)} puts`;
      return `
        <tr>
          <td>
            <div class="symbol-cell">
              <strong>${escapeHtml(spread.underlying_symbol)}</strong>
              <span>${escapeHtml(legSummary)}</span>
            </div>
          </td>
          <td>${escapeHtml(formatSpreadDate(spread.expiration_date))}</td>
          <td>${escapeHtml(formatSpreadStrike(spread.width))}</td>
          <td><span class="pill ${statusTone}">${escapeHtml(formatSpreadStatusLabel(spread.status))}</span></td>
          <td>${escapeHtml(formatSpreadCredit(spread.entry_net_credit))}</td>
          <td>${escapeHtml(formatDateTime(spread.last_synced_at))}</td>
          <td>
            <div class="strategy-action-cell">
              <strong>${escapeHtml(actionText)}</strong>
              <span>${escapeHtml(formatDateTime(spread.updated_at))}</span>
            </div>
          </td>
          <td>
            <div class="table-actions">
              <button class="table-action" type="button" data-spread-action="refresh" data-spread-id="${escapeHtml(spread.id)}">
                Refresh
              </button>
              ${
                monitorable
                  ? `<button class="table-action primary" type="button" data-spread-action="monitor" data-spread-id="${escapeHtml(spread.id)}">Monitor</button>`
                  : ""
              }
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderOrders() {
  if (state.orders.length === 0) {
    els.ordersBody.innerHTML = '<tr><td colspan="7" class="empty-row">No orders for this account.</td></tr>';
    return;
  }

  els.ordersBody.innerHTML = state.orders
    .slice(0, 10)
    .map((order) => {
      const pillClass = statusClass(order.status);
      const canCancel = isCancelableOrder(order);
      const selectedClass = order.id === state.selectedOrderId ? "is-selected" : "";
      return `
        <tr class="${selectedClass}">
          <td>
            <div class="symbol-cell">
              <strong>${escapeHtml(order.symbol)}</strong>
              <span>${escapeHtml(order.order_type.toUpperCase())} / ${escapeHtml(order.time_in_force.toUpperCase())}</span>
            </div>
          </td>
          <td>${escapeHtml(order.side.toUpperCase())}</td>
          <td>${escapeHtml(String(order.quantity))}</td>
          <td><span class="pill ${pillClass}">${escapeHtml(order.status)}</span></td>
          <td>${escapeHtml(formatOrderPrice(order))}</td>
          <td>${escapeHtml(formatDateTime(order.updated_at))}</td>
          <td>
            <div class="table-actions">
              <button class="table-action primary" type="button" data-order-action="manage" data-order-id="${escapeHtml(order.id)}">
                Manage
              </button>
              <button class="table-action" type="button" data-order-action="refresh" data-order-id="${escapeHtml(order.id)}">
                Refresh
              </button>
              ${
                canCancel
                  ? `<button class="table-action danger" type="button" data-order-action="cancel" data-order-id="${escapeHtml(order.id)}">Cancel</button>`
                  : ""
              }
            </div>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderPositions() {
  const snapshot = state.latestSnapshot;
  const positions = buildSortedPositions(snapshot?.positions || []);
  const currency = snapshot?.currency || "USD";
  const grossMarketValue = positions.reduce((sum, position) => sum + toFiniteNumber(position.market_value), 0);
  if (positions.length === 0) {
    els.positionsBody.innerHTML = '<tr><td colspan="7" class="empty-row">No positions in latest snapshot.</td></tr>';
    return;
  }

  els.positionsBody.innerHTML = positions
    .map(
      (position) => `
        <tr>
          <td>${escapeHtml(position.symbol)}</td>
          <td><span class="pill neutral">${escapeHtml(position.asset_type)}</span></td>
          <td>${escapeHtml(formatPositionQuantity(position.quantity))}</td>
          <td>${escapeHtml(formatCurrency(position.average_cost, currency))}</td>
          <td>${escapeHtml(formatCurrency(position.market_value, currency))}</td>
          <td><span class="pnl-chip ${pnlTone(toNumber(position.unrealized_pnl))}">${escapeHtml(formatSignedCurrency(position.unrealized_pnl, currency))}</span></td>
          <td>${escapeHtml(formatWeight(position.market_value, grossMarketValue))}</td>
        </tr>
      `
    )
    .join("");
}

function renderQuote() {
  const quote = state.quote;
  const overlay = state.quoteStatus;
  const symbol = quote?.symbol || els.quoteSymbol.value.trim().toUpperCase();
  if (!quote) {
    if (overlay.kind === "idle") {
      els.quoteCard.className = "quote-card empty";
      els.quoteCard.textContent = overlay.detail || "No quote loaded.";
      return;
    }

    els.quoteCard.className = "quote-card";
    els.quoteCard.innerHTML = `
      <div class="overlay-status-row">
        <div class="overlay-status-copy">
          <span class="section-kicker">${escapeHtml(symbol || "Quick Quote")}</span>
          <strong>${escapeHtml(overlayStatusLabel(overlay.kind))}</strong>
        </div>
        <span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span>
      </div>
      <p class="overlay-detail">${escapeHtml(overlay.detail || "Quote refresh is waiting for the next response.")}</p>
      ${renderOverlayReason(overlay)}
    `;
    return;
  }

  const lastDone = Number(quote.last_done);
  const prevClose = Number(quote.prev_close);
  const diff = lastDone - prevClose;
  const pct = prevClose === 0 ? 0 : (diff / prevClose) * 100;
  const changeClass = diff >= 0 ? "positive" : "negative";
  const changePrefix = diff >= 0 ? "+" : "";

  els.quoteCard.className = "quote-card";
  els.quoteCard.innerHTML = `
    <div class="overlay-status-row">
      <div class="overlay-status-copy">
        <span class="section-kicker">${escapeHtml(quote.symbol)}</span>
        <div class="quote-price">
          <strong>${formatNumber(quote.last_done)}</strong>
          <span class="quote-change ${changeClass}">${changePrefix}${formatNumber(diff.toFixed(2))} / ${changePrefix}${pct.toFixed(2)}%</span>
        </div>
      </div>
      <span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span>
    </div>
    <p class="overlay-detail">${escapeHtml(overlay.detail || overlayLiveDetail("Quote", quote.timestamp))}</p>
    ${renderOverlayReason(overlay)}
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

function renderPreOpenAssessment() {
  const assessment = state.preOpenAssessment;
  const overlay = state.preOpenStatus;
  if (!assessment) {
    const detail = overlay.detail || "Waiting for the latest macro proxy snapshot.";
    const summaryValues = [
      {
        label: "Board Status",
        value: overlayStatusLabel(overlay.kind),
        tone: overlayStatusTone(overlay.kind),
        detail,
      },
      {
        label: "Downside Score",
        value: "--",
        tone: "",
        detail,
      },
      {
        label: "Regime",
        value: "--",
        tone: "",
        detail: "Load the pre-open board to classify market tone.",
      },
      {
        label: "Plain Put View",
        value: "--",
        tone: "",
        detail: "QQQ / SPY directional put bias will render here.",
      },
      {
        label: "Preferred Vehicle",
        value: "--",
        tone: "",
        detail: "Waiting for proxy dispersion.",
      },
    ];

    els.preOpenSummaryStrip.innerHTML = summaryValues
      .map(
        (item) => `
          <article class="mini-metric-tile">
            <span class="metric-label">${escapeHtml(item.label)}</span>
            <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
            <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
          </article>
        `
      )
      .join("");

    els.preOpenAssessmentCard.className = `strategy-note-body ${overlay.kind === "idle" || overlay.kind === "loading" ? "empty" : ""}`;
    els.preOpenAssessmentCard.innerHTML = `
      <div class="overlay-status-row">
        <div class="overlay-status-copy">
          <strong>Pre-open Risk Board</strong>
          <span>${escapeHtml(detail)}</span>
        </div>
        <span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span>
      </div>
      ${renderOverlayReason(overlay)}
    `;
    els.preOpenSignals.innerHTML = '<div class="holding-empty">Waiting for market proxy signals.</div>';
    els.preOpenPuts.innerHTML = '<div class="holding-empty">Waiting for directional put snapshots.</div>';
    els.preOpenChainAnalysis.innerHTML = '<div class="holding-empty">Waiting for option chain analysis.</div>';
    return;
  }

  const summaryValues = [
    {
      label: "Board Status",
      value: overlayStatusLabel(overlay.kind),
      tone: overlayStatusTone(overlay.kind),
      detail: overlay.detail || overlayLiveDetail("Pre-open board", assessment.analyzed_at),
    },
    {
      label: "Downside Score",
      value: String(assessment.downside_score),
      tone: preOpenScoreTone(assessment.downside_score),
      detail: assessment.reasons.length
        ? `${assessment.reasons.length} bearish trigger${assessment.reasons.length === 1 ? "" : "s"} in play`
        : "No major bearish trigger is active",
    },
    {
      label: "Regime",
      value: formatPreOpenLabel(assessment.regime),
      tone: preOpenRegimeTone(assessment.regime),
      detail: `Session: ${formatPreOpenLabel(assessment.session)}`,
    },
    {
      label: "Plain Put View",
      value: formatPreOpenLabel(assessment.plain_put_view),
      tone: preOpenViewTone(assessment.plain_put_view),
      detail: assessment.market_open ? "Regular U.S. session is live." : formatPreOpenTimingDetail(assessment),
    },
    {
      label: "Action",
      value: formatPreOpenLabel(assessment.trade_action),
      tone: preOpenActionTone(assessment.trade_action),
      detail: assessment.preferred_vehicle
        ? `${assessment.preferred_vehicle} is the cleaner vehicle if the tape confirms.`
        : "No clean SPY / QQQ vehicle is standing out.",
    },
    {
      label: "Gap Chase Risk",
      value: formatPreOpenLabel(assessment.gap_chase_risk),
      tone: preOpenGapTone(assessment.gap_chase_risk),
      detail: "Measures the risk of overpaying for plain puts into the open.",
    },
  ];

  els.preOpenSummaryStrip.innerHTML = summaryValues
    .map(
      (item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `
    )
    .join("");

  const reasonsMarkup = assessment.reasons.length
    ? assessment.reasons
        .map(
          (reason) => `
            <article class="strategy-journal-entry">
              <p>${escapeHtml(reason)}</p>
            </article>
          `
        )
        .join("")
    : '<div class="strategy-note-body empty">No bearish trigger is strong enough to favor plain index puts right now.</div>';
  const checkpointsMarkup = assessment.checkpoints.length
    ? assessment.checkpoints
        .map(
          (checkpoint) => `
            <article class="strategy-journal-entry">
              <div class="strategy-journal-head">
                <strong>${escapeHtml(checkpoint.label)}</strong>
                <span>${escapeHtml(checkpoint.timing_label)}</span>
              </div>
              <div class="strategy-action-cell">
                <strong>${escapeHtml(formatPreOpenLabel(checkpoint.status))}</strong>
                <span>${escapeHtml(checkpoint.detail)}</span>
              </div>
            </article>
          `
        )
        .join("")
    : "";

  els.preOpenAssessmentCard.className = "strategy-note-body";
  els.preOpenAssessmentCard.innerHTML = `
    <div class="overlay-status-row">
      <div class="overlay-status-copy">
        <strong>${escapeHtml(assessment.summary)}</strong>
        <span>${escapeHtml(formatDateTime(assessment.analyzed_at))}</span>
      </div>
      <span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span>
    </div>
    <p class="overlay-detail">${escapeHtml(overlay.detail || overlayLiveDetail("Pre-open board", assessment.analyzed_at))}</p>
    ${renderOverlayReason(overlay)}
    <div class="status-list">
      <div>
        <dt>Preferred Vehicle</dt>
        <dd>${escapeHtml(assessment.preferred_vehicle || "--")}</dd>
      </div>
      <div>
        <dt>Action</dt>
        <dd>${escapeHtml(formatPreOpenLabel(assessment.trade_action))}</dd>
      </div>
      <div>
        <dt>Gap Chase Risk</dt>
        <dd>${escapeHtml(formatPreOpenLabel(assessment.gap_chase_risk))}</dd>
      </div>
      <div>
        <dt>Session</dt>
        <dd>${escapeHtml(formatPreOpenTimingDetail(assessment))}</dd>
      </div>
    </div>
    <article class="strategy-journal-entry">
      <p>${escapeHtml(formatPreOpenNarrative(assessment))}</p>
    </article>
    <article class="strategy-journal-entry">
      <p>${escapeHtml(assessment.trade_action_detail)}</p>
    </article>
    <article class="strategy-journal-entry">
      <p>${escapeHtml(assessment.gap_chase_detail)}</p>
    </article>
    ${reasonsMarkup}
    ${checkpointsMarkup}
  `;

  if (!assessment.signals.length) {
    els.preOpenSignals.innerHTML = '<div class="holding-empty">No market proxy signals are available.</div>';
  } else {
    els.preOpenSignals.innerHTML = assessment.signals
      .map(
        (signal) => `
          <article class="holding-card">
            <div class="holding-head">
              <div class="symbol-block">
                <strong>${escapeHtml(signal.label)}</strong>
                <span>${escapeHtml(signal.symbol)}</span>
              </div>
              <span class="pill ${preOpenSignalTone(signal.signal)}">${escapeHtml(formatPreOpenLabel(signal.signal))}</span>
            </div>
            <div class="holding-stats">
              <div>
                <span>Session Px</span>
                <strong>${escapeHtml(formatNumber(signal.session_price))}</strong>
              </div>
              <div>
                <span>Prev Close</span>
                <strong>${escapeHtml(formatNumber(signal.reference_price))}</strong>
              </div>
              <div>
                <span>Change</span>
                <strong>${escapeHtml(formatSignedPercentValue(signal.change_pct))}</strong>
              </div>
            </div>
            <span class="mini-metric-detail">${escapeHtml(signal.note || "No extra context for this proxy move.")}</span>
          </article>
        `
      )
      .join("");
  }

  if (!assessment.put_snapshots.length) {
    els.preOpenPuts.innerHTML = '<div class="holding-empty">No short-dated reference puts were found.</div>';
  } else {
    els.preOpenPuts.innerHTML = assessment.put_snapshots
      .map((snapshot) => {
        const preferred =
          assessment.preferred_vehicle && snapshot.underlying_symbol.startsWith(assessment.preferred_vehicle);
        return `
          <article class="holding-card">
            <div class="holding-head">
              <div class="symbol-block">
                <strong>${escapeHtml(snapshot.underlying_symbol)}</strong>
                <span>${escapeHtml(snapshot.put_symbol)}</span>
              </div>
              <span class="pill ${preferred ? "warning" : preOpenLiquidityTone(snapshot.liquidity_label)}">${escapeHtml(preferred ? "Preferred" : snapshot.liquidity_label || "Reference")}</span>
            </div>
            <div class="holding-stats">
              <div>
                <span>Expiry</span>
                <strong>${escapeHtml(formatSpreadDate(snapshot.expiration_date))}</strong>
              </div>
              <div>
                <span>Strike</span>
                <strong>${escapeHtml(formatSpreadStrike(snapshot.strike))}</strong>
              </div>
              <div>
                <span>DTE</span>
                <strong>${escapeHtml(String(snapshot.days_to_expiration))}</strong>
              </div>
                <div>
                  <span>Bid / Ask</span>
                  <strong>${escapeHtml(`${formatNumber(snapshot.bid)} / ${formatNumber(snapshot.ask)}`)}</strong>
                </div>
                <div>
                  <span>Mid / Spread</span>
                  <strong>${escapeHtml(`${formatNumber(snapshot.mid_price)} / ${formatPercentValue(snapshot.spread_pct)}`)}</strong>
                </div>
                <div>
                  <span>Delta / IV</span>
                  <strong>${escapeHtml(`${formatSignedDecimal(snapshot.delta, 2)} / ${formatImpliedVolatility(snapshot.implied_volatility)}`)}</strong>
                </div>
                <div>
                  <span>Spot Distance</span>
                  <strong>${escapeHtml(formatSpotDistance(snapshot.distance_from_spot_pct))}</strong>
                </div>
              </div>
            </article>
        `;
      })
      .join("");
  }

  renderPreOpenChainAnalysis(assessment.chain_analyses || []);
}

function renderPreOpenChainAnalysis(analyses) {
  if (!Array.isArray(analyses) || !analyses.length) {
    els.preOpenChainAnalysis.innerHTML = '<div class="holding-empty">No option chain analysis is available.</div>';
    return;
  }

  els.preOpenChainAnalysis.innerHTML = analyses
    .map((analysis) => {
      const front = analysis.front_expiration;
      const next = analysis.next_expiration;
      const termLabel = formatOptionTermStructure(analysis.term_structure_label);
      return `
        <article class="holding-card">
          <div class="holding-head">
            <div class="symbol-block">
              <strong>${escapeHtml(analysis.underlying_symbol)}</strong>
              <span>${escapeHtml(analysis.sample_note || "Front/next expiry summary with liquidity sampling.")}</span>
            </div>
            <span class="pill ${preOpenTermTone(analysis.term_structure_label)}">${escapeHtml(termLabel)}</span>
          </div>
          <div class="holding-stats">
            <div>
              <span>Spot</span>
              <strong>${escapeHtml(formatNumber(analysis.underlying_price))}</strong>
            </div>
            <div>
              <span>Front ATM IV</span>
              <strong>${escapeHtml(front ? formatImpliedVolatility(front.atm_implied_volatility) : "--")}</strong>
            </div>
            <div>
              <span>Next ATM IV</span>
              <strong>${escapeHtml(next ? formatImpliedVolatility(next.atm_implied_volatility) : "--")}</strong>
            </div>
            <div>
              <span>Term Slope</span>
              <strong>${escapeHtml(formatSignedIvDifference(analysis.atm_iv_term_diff))}</strong>
            </div>
            <div>
              <span>Front Put Skew</span>
              <strong>${escapeHtml(front ? formatSignedIvDifference(front.put_skew_diff) : "--")}</strong>
            </div>
            <div>
              <span>Front Median Spread</span>
              <strong>${escapeHtml(front ? formatPercentValue(front.median_spread_pct) : "--")}</strong>
            </div>
          </div>
          ${front ? renderOptionExpiryAnalysis(front, "Front Expiry") : ""}
          ${next ? renderOptionExpiryAnalysis(next, "Next Expiry") : ""}
        </article>
      `;
    })
    .join("");
}

function renderLatestPreOpenRun() {
  const run = Array.isArray(state.preOpenRuns) && state.preOpenRuns.length ? state.preOpenRuns[0] : null;
  if (!state.selectedAccountId) {
    els.preOpenRunReview.className = "strategy-note-body empty";
    els.preOpenRunReview.textContent = "Select a broker account to load the latest pre-open capture and opening review.";
    return;
  }

  if (!run) {
    els.preOpenRunReview.className = "strategy-note-body empty";
    els.preOpenRunReview.textContent = "No pre-open capture has been stored for this broker account yet.";
    return;
  }

  const checkpoints = Array.isArray(run.checkpoints) ? run.checkpoints : [];
  const capturedCount = checkpoints.filter((checkpoint) => checkpoint.captured_at).length;
  const checkpointMarkup = checkpoints.length
    ? checkpoints
        .map(
          (checkpoint) => `
            <article class="strategy-journal-entry">
              <div class="strategy-journal-head">
                <strong>${escapeHtml(checkpoint.label)}</strong>
                <span>${escapeHtml(checkpoint.timing_label)}</span>
              </div>
              <div class="status-list">
                <div>
                  <dt>Status</dt>
                  <dd><span class="pill ${preOpenReviewTone(checkpoint.status)}">${escapeHtml(formatPreOpenLabel(checkpoint.status))}</span></dd>
                </div>
                <div>
                  <dt>Review</dt>
                  <dd><span class="pill ${preOpenReviewTone(checkpoint.confirmation)}">${escapeHtml(formatPreOpenLabel(checkpoint.confirmation || "pending"))}</span></dd>
                </div>
                <div>
                  <dt>QQQ / SPY</dt>
                  <dd>${escapeHtml(`${formatSignedPercentValue(checkpoint.qqq_change_pct)} / ${formatSignedPercentValue(checkpoint.spy_change_pct)}`)}</dd>
                </div>
                <div>
                  <dt>Semis</dt>
                  <dd>${escapeHtml(formatSignedPercentValue(checkpoint.semis_change_pct))}</dd>
                </div>
                <div>
                  <dt>QQQ vs SPY</dt>
                  <dd>${escapeHtml(formatSignedPercentValue(checkpoint.qqq_vs_spy_diff))}</dd>
                </div>
                <div>
                  <dt>Semis vs QQQ</dt>
                  <dd>${escapeHtml(formatSignedPercentValue(checkpoint.semis_vs_qqq_diff))}</dd>
                </div>
              </div>
              <p>${escapeHtml(checkpoint.detail || "Opening review is still waiting for this checkpoint.")}</p>
            </article>
          `
        )
        .join("")
    : '<div class="holding-empty">No opening checkpoints were stored for this run.</div>';

  const assessmentSummary = run.assessment?.summary || "Stored pre-open assessment.";
  const reviewSummary = run.review_summary || "Opening follow-through review is still waiting for the first checkpoint.";
  const targetSession = formatSessionDate(run.target_session_date);
  const nextOpen = run.assessment?.next_regular_open_at ? formatDateTime(run.assessment.next_regular_open_at) : "--";

  els.preOpenRunReview.className = "strategy-note-body";
  els.preOpenRunReview.innerHTML = `
    <div class="strategy-journal-head">
      <strong>${escapeHtml(assessmentSummary)}</strong>
      <span>${escapeHtml(formatDateTime(run.created_at))}</span>
    </div>
    <div class="status-list">
      <div>
        <dt>Target Session</dt>
        <dd>${escapeHtml(targetSession)}</dd>
      </div>
      <div>
        <dt>Review Status</dt>
        <dd><span class="pill ${preOpenReviewTone(run.review_status)}">${escapeHtml(formatPreOpenLabel(run.review_status))}</span></dd>
      </div>
      <div>
        <dt>Checkpoints</dt>
        <dd>${escapeHtml(`${capturedCount} / ${checkpoints.length}`)}</dd>
      </div>
      <div>
        <dt>Next Open</dt>
        <dd>${escapeHtml(nextOpen)}</dd>
      </div>
      <div>
        <dt>Preferred Vehicle</dt>
        <dd>${escapeHtml(run.assessment?.preferred_vehicle || "--")}</dd>
      </div>
      <div>
        <dt>Action Bias</dt>
        <dd>${escapeHtml(formatPreOpenLabel(run.assessment?.trade_action || "--"))}</dd>
      </div>
    </div>
    <article class="strategy-journal-entry">
      <p>${escapeHtml(reviewSummary)}</p>
    </article>
    ${checkpointMarkup}
  `;
}

function renderOptionExpiryAnalysis(expiry, label) {
  const liquidMarkup = Array.isArray(expiry.liquid_strikes) && expiry.liquid_strikes.length
    ? expiry.liquid_strikes
        .map(
          (strike) => `
            <article class="strategy-journal-entry">
              <div class="strategy-journal-head">
                <strong>${escapeHtml(formatSpreadStrike(strike.strike))}</strong>
                <span>${escapeHtml(strike.put_symbol)}</span>
              </div>
              <div class="holding-stats compact">
                <div>
                  <span>OI / Vol</span>
                  <strong>${escapeHtml(`${formatPositionQuantity(strike.open_interest)} / ${formatPositionQuantity(strike.volume)}`)}</strong>
                </div>
                <div>
                  <span>Bid / Ask</span>
                  <strong>${escapeHtml(`${formatNumber(strike.bid)} / ${formatNumber(strike.ask)}`)}</strong>
                </div>
                <div>
                  <span>Spread / Delta</span>
                  <strong>${escapeHtml(`${formatPercentValue(strike.spread_pct)} / ${formatSignedDecimal(strike.delta, 2)}`)}</strong>
                </div>
              </div>
            </article>
          `
        )
        .join("")
    : '<div class="strategy-note-body empty">No liquid strikes were sampled for this expiry.</div>';

  return `
    <article class="strategy-journal-entry">
      <div class="strategy-journal-head">
        <strong>${escapeHtml(label)}</strong>
        <span>${escapeHtml(`${formatSpreadDate(expiry.expiration_date)} (${expiry.days_to_expiration} DTE)`)}</span>
      </div>
      <div class="status-list">
        <div>
          <dt>ATM Put</dt>
          <dd>${escapeHtml(`${formatSpreadStrike(expiry.atm_strike)} / ${formatNumber(expiry.atm_mid_price)}`)}</dd>
        </div>
        <div>
          <dt>ATM Delta / IV</dt>
          <dd>${escapeHtml(`${formatSignedDecimal(expiry.atm_delta, 2)} / ${formatImpliedVolatility(expiry.atm_implied_volatility)}`)}</dd>
        </div>
        <div>
          <dt>Put Skew Leg</dt>
          <dd>${escapeHtml(expiry.put_skew_strike ? `${formatSpreadStrike(expiry.put_skew_strike)} / ${formatSignedDecimal(expiry.put_skew_delta, 2)}` : "--")}</dd>
        </div>
        <div>
          <dt>Skew IV Lift</dt>
          <dd>${escapeHtml(formatSignedIvDifference(expiry.put_skew_diff))}</dd>
        </div>
        <div>
          <dt>Spread Buckets</dt>
          <dd>${escapeHtml(`${expiry.tight_count} tight / ${expiry.workable_count} workable / ${expiry.wide_count} wide`)}</dd>
        </div>
        <div>
          <dt>Median Spread</dt>
          <dd>${escapeHtml(formatPercentValue(expiry.median_spread_pct))}</dd>
        </div>
      </div>
      ${liquidMarkup}
    </article>
  `;
}

function renderSelectedOrder() {
  const order = getSelectedOrder();
  if (!order) {
    els.selectedOrderCard.className = "selected-order empty";
    els.selectedOrderCard.textContent = "Select an order from the table to manage it.";
    renderSelectedExecution();
    renderSelectedJournal();
    hideReplaceForm();
    return;
  }

  const canReplace = isReplaceableOrder(order);
  const canCancel = isCancelableOrder(order);
  const statusTone = statusClass(order.status);

  els.selectedOrderCard.className = "selected-order";
  els.selectedOrderCard.innerHTML = `
    <div class="selected-order-head">
      <div>
        <span class="section-kicker">Selected Order</span>
        <h3 class="selected-order-title">${escapeHtml(order.symbol)} ${escapeHtml(order.side.toUpperCase())} x ${escapeHtml(String(order.quantity))}</h3>
      </div>
      <span class="pill ${statusTone}">${escapeHtml(order.status)}</span>
    </div>
    <div class="selected-order-meta">
      <div>
        <span>External ID</span>
        <strong>${escapeHtml(order.external_order_id || "--")}</strong>
      </div>
      <div>
        <span>Account</span>
        <strong>${escapeHtml(order.external_account_id)}</strong>
      </div>
      <div>
        <span>Order Type</span>
        <strong>${escapeHtml(order.order_type.toUpperCase())}</strong>
      </div>
      <div>
        <span>Time In Force</span>
        <strong>${escapeHtml(order.time_in_force.toUpperCase())}</strong>
      </div>
      <div>
        <span>Price Logic</span>
        <strong>${escapeHtml(formatOrderPrice(order))}</strong>
      </div>
      <div>
        <span>Updated</span>
        <strong>${escapeHtml(formatDateTime(order.updated_at))}</strong>
      </div>
    </div>
    <div class="selected-order-actions">
      <button class="icon-button" type="button" data-selected-action="refresh">
        <span class="icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" focusable="false">
            <path d="M21 12a9 9 0 1 1-2.64-6.36"/>
            <path d="M21 3v6h-6"/>
          </svg>
        </span>
        <span>Refresh</span>
      </button>
      ${
        canCancel
          ? `
            <button class="icon-button" type="button" data-selected-action="cancel">
              <span class="icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" focusable="false">
                  <path d="M18 6 6 18"/>
                  <path d="m6 6 12 12"/>
                </svg>
              </span>
              <span>Cancel</span>
            </button>
          `
          : ""
      }
    </div>
    ${
      canReplace
        ? ""
        : '<p class="form-hint">Filled, canceled, and rejected orders can be refreshed but not replaced.</p>'
    }
  `;

  if (canReplace) {
    populateReplaceForm(order);
  } else {
    hideReplaceForm();
  }

  renderSelectedExecution();
  renderSelectedJournal();
}

function setSelectedOrder(orderId, shouldScroll = false) {
  state.selectedOrderId = orderId;
  renderOrders();
  renderSelectedOrder();

  if (shouldScroll) {
    els.selectedOrderCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

function getSelectedOrder() {
  return state.orders.find((order) => order.id === state.selectedOrderId) || null;
}

function getSelectedAccount() {
  return state.accounts.find((account) => account.external_account_id === state.selectedAccountId) || null;
}

function getSelectedExecution() {
  return state.executions.find((execution) => execution.order_id === state.selectedOrderId) || null;
}

function getSelectedJournalEntries() {
  const order = getSelectedOrder();
  if (!order) {
    return [];
  }

  return state.journals.filter(
    (entry) =>
      entry.order_id === order.id ||
      (order.trade_plan_id && entry.trade_plan_id === order.trade_plan_id)
  );
}

function renderSelectedExecution() {
  const execution = getSelectedExecution();
  if (!execution) {
    els.selectedOrderExecution.className = "selected-order-execution empty";
    els.selectedOrderExecution.textContent = "No fills recorded for this order yet.";
    return;
  }

  els.selectedOrderExecution.className = "selected-order-execution";
  els.selectedOrderExecution.innerHTML = `
    <div class="execution-grid">
      <div>
        <span>Filled Qty</span>
        <strong>${escapeHtml(formatPositionQuantity(execution.quantity))}</strong>
      </div>
      <div>
        <span>Avg Fill</span>
        <strong>${escapeHtml(formatCurrency(execution.price))}</strong>
      </div>
      <div>
        <span>Last Fill</span>
        <strong>${escapeHtml(formatDateTime(execution.executed_at))}</strong>
      </div>
    </div>
    <p class="form-hint">Derived from the latest broker order detail snapshot for this order.</p>
  `;
}

function renderSelectedJournal() {
  const order = getSelectedOrder();
  if (!order) {
    updateJournalFormAvailability(false);
    els.journalFormHint.textContent = "Select an order to save a plan note or post-trade review.";
    els.selectedOrderJournal.className = "selected-order-journal empty";
    els.selectedOrderJournal.textContent = "Select an order to load journal entries.";
    return;
  }

  updateJournalFormAvailability(true);
  const execution = getSelectedExecution();
  const entries = getSelectedJournalEntries();
  const context = [];
  if (order.trade_plan_id) {
    context.push("trade plan context");
  }
  if (execution) {
    context.push("latest fill context");
  }
  els.journalFormHint.textContent = context.length
    ? `New entries will attach ${context.join(" and ")} for ${order.symbol}.`
    : `New entries will attach to ${order.symbol} on ${order.external_account_id}.`;

  if (!entries.length) {
    els.selectedOrderJournal.className = "selected-order-journal empty";
    els.selectedOrderJournal.textContent = "No journal entries linked to this order yet.";
    return;
  }

  els.selectedOrderJournal.className = "selected-order-journal";
  els.selectedOrderJournal.innerHTML = entries
    .map((entry) => {
      const linkMeta = [];
      if (entry.trade_plan_id) {
        linkMeta.push("Plan linked");
      }
      if (entry.execution_id) {
        linkMeta.push("Execution linked");
      }
      const tags = entry.tags.length
        ? `<div class="journal-entry-tags">${entry.tags
            .map((tag) => `<span class="journal-tag">${escapeHtml(tag)}</span>`)
            .join("")}</div>`
        : "";

      return `
        <article class="journal-entry-card">
          <div class="journal-entry-head">
            <div class="journal-entry-title-block">
              <span class="pill ${journalEntryTone(entry.entry_type)}">${escapeHtml(entry.entry_type)}</span>
              <strong>${escapeHtml(entry.title)}</strong>
            </div>
            <span class="journal-entry-time">${escapeHtml(formatDateTime(entry.updated_at))}</span>
          </div>
          <div class="journal-entry-meta">
            <span>${escapeHtml(linkMeta.join(" / ") || "Order linked")}</span>
            <span>${escapeHtml(entry.symbol)}</span>
          </div>
          <p class="journal-entry-notes">${formatMultilineText(entry.notes)}</p>
          ${tags}
        </article>
      `;
    })
    .join("");
}

function updateJournalFormAvailability(enabled) {
  els.journalEntryType.disabled = !enabled;
  els.journalTitle.disabled = !enabled;
  els.journalTags.disabled = !enabled;
  els.journalNotes.disabled = !enabled;
  els.submitJournal.disabled = !enabled;
  els.submitJournal.title = enabled ? "" : "Select an order first.";
}

function populateReplaceForm(order) {
  els.replaceOrderForm.dataset.orderId = order.id;
  els.replaceQuantity.value = String(order.quantity);
  els.replaceLimitPrice.value = order.limit_price ?? "";
  els.replaceStopPrice.value = order.stop_price ?? "";
  els.replaceRemark.value = "";
  syncReplaceOrderFields(order.order_type);
  els.replaceOrderForm.classList.remove("hidden");
}

function hideReplaceForm() {
  els.replaceOrderForm.dataset.orderId = "";
  els.replaceOrderForm.classList.add("hidden");
}

function updateOrderTicketAvailability() {
  const hasAccount = Boolean(state.selectedAccountId);
  els.submitOrder.disabled = !hasAccount;
  els.submitOrder.title = hasAccount ? "" : "Select a broker account first.";
}

function updateSyncButtons() {
  const account = getSelectedAccount();
  const hasAccount = Boolean(account);
  const accountSyncing = account?.account_sync_status === "syncing";
  const ordersSyncing = account?.orders_sync_status === "syncing";

  els.syncAccount.disabled = !hasAccount || accountSyncing;
  els.syncOrders.disabled = !hasAccount || ordersSyncing;
  els.syncAccount.title = !hasAccount ? "Select a broker account first." : accountSyncing ? "Account sync already in progress." : "";
  els.syncOrders.title = !hasAccount ? "Select a broker account first." : ordersSyncing ? "Order sync already in progress." : "";
}

function updateStrategyButtons() {
  const hasAccount = Boolean(state.selectedAccountId);
  els.saveStrategyControls.disabled = !hasAccount;
  els.runStrategyScan.disabled = !hasAccount;
  els.runStrategyReview.disabled = !hasAccount;
  els.saveStrategyControls.title = hasAccount ? "" : "Select a broker account first.";
  els.runStrategyScan.title = hasAccount ? "" : "Select a broker account first.";
  els.runStrategyReview.title = hasAccount ? "" : "Select a broker account first.";
}

function syncTicketOrderFields() {
  syncOrderTypeFields({
    orderType: els.orderType.value,
    limitField: els.orderLimitField,
    stopField: els.orderStopField,
    limitInput: els.orderLimitPrice,
    stopInput: els.orderStopPrice,
    hintEl: els.orderFormHint,
    marketHint: "Market orders use the selected paper account and do not require a price.",
    limitHint: "Limit orders require a limit price.",
    stopHint: "Stop orders require a stop price. Add an optional limit price to send a stop-limit style order.",
  });
}

function syncReplaceOrderFields(orderType) {
  syncOrderTypeFields({
    orderType,
    limitField: els.replaceLimitField,
    stopField: els.replaceStopField,
    limitInput: els.replaceLimitPrice,
    stopInput: els.replaceStopPrice,
    hintEl: els.replaceFormHint,
    marketHint: "Market order replacements update quantity only.",
    limitHint: "Limit order replacements require a limit price.",
    stopHint: "Stop order replacements require a stop price. Limit price remains optional.",
  });
}

function syncOrderTypeFields({
  orderType,
  limitField,
  stopField,
  limitInput,
  stopInput,
  hintEl,
  marketHint,
  limitHint,
  stopHint,
}) {
  const showLimit = orderType === "limit" || orderType === "stop";
  const showStop = orderType === "stop";

  setFieldVisibility(limitField, limitInput, showLimit);
  setFieldVisibility(stopField, stopInput, showStop);

  if (orderType === "market") {
    limitInput.value = "";
    stopInput.value = "";
    hintEl.textContent = marketHint;
    return;
  }

  if (orderType === "limit") {
    stopInput.value = "";
    hintEl.textContent = limitHint;
    return;
  }

  hintEl.textContent = stopHint;
}

function setFieldVisibility(field, input, visible) {
  field.classList.toggle("hidden", !visible);
  input.disabled = !visible;
}

function buildCreateOrderPayload() {
  const symbol = els.orderSymbol.value.trim().toUpperCase();
  if (!symbol) {
    throw new Error("Order symbol is required.");
  }

  const payload = {
    external_account_id: state.selectedAccountId,
    symbol,
    side: els.orderSide.value,
    quantity: parsePositiveInteger(els.orderQuantity.value, "Order quantity"),
    order_type: els.orderType.value,
    time_in_force: els.orderTimeInForce.value,
    mode: "paper",
    remark: normalizeOptionalText(els.orderRemark.value),
  };
  applyOrderTypePrices({
    orderType: payload.order_type,
    limitValue: els.orderLimitPrice.value,
    stopValue: els.orderStopPrice.value,
    payload,
    contextLabel: "Order",
  });
  return payload;
}

function buildReplaceOrderPayload(order) {
  const payload = {
    quantity: parsePositiveInteger(els.replaceQuantity.value, "Replace quantity"),
    remark: normalizeOptionalText(els.replaceRemark.value),
  };
  applyOrderTypePrices({
    orderType: order.order_type,
    limitValue: els.replaceLimitPrice.value,
    stopValue: els.replaceStopPrice.value,
    payload,
    contextLabel: "Replace",
  });
  return payload;
}

function applyOrderTypePrices({ orderType, limitValue, stopValue, payload, contextLabel }) {
  if (orderType === "market") {
    payload.limit_price = null;
    payload.stop_price = null;
    return;
  }

  if (orderType === "limit") {
    payload.limit_price = parsePositiveNumber(limitValue, `${contextLabel} limit price`, true);
    payload.stop_price = null;
    return;
  }

  if (orderType === "stop") {
    payload.limit_price = parsePositiveNumber(limitValue, `${contextLabel} limit price`, false);
    payload.stop_price = parsePositiveNumber(stopValue, `${contextLabel} stop price`, true);
    return;
  }

  throw new Error(`Unsupported order type: ${orderType}`);
}

function parsePositiveInteger(value, label) {
  const number = Number.parseInt(String(value).trim(), 10);
  if (!Number.isInteger(number) || number <= 0) {
    throw new Error(`${label} must be a positive whole number.`);
  }
  return number;
}

function parsePositiveNumber(value, label, required) {
  const trimmed = String(value ?? "").trim();
  if (!trimmed) {
    if (required) {
      throw new Error(`${label} is required.`);
    }
    return null;
  }

  const number = Number(trimmed);
  if (!Number.isFinite(number) || number <= 0) {
    throw new Error(`${label} must be greater than 0.`);
  }
  return number;
}

function normalizeOptionalText(value) {
  const trimmed = String(value ?? "").trim();
  return trimmed ? trimmed : null;
}

function parseTags(value) {
  const seen = new Set();
  return String(value ?? "")
    .split(",")
    .map((tag) => tag.trim())
    .filter((tag) => {
      if (!tag || seen.has(tag)) {
        return false;
      }
      seen.add(tag);
        return true;
      });
}

function parseSymbolList(value) {
  return String(value ?? "")
    .split(",")
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean);
}

function isCancelableOrder(order) {
  return order.status === "created" || order.status === "submitted" || order.status === "partially_filled";
}

function isActiveSpread(spread) {
  return (
    spread.status === "entry_pending_long" ||
    spread.status === "entry_pending_short" ||
    spread.status === "open" ||
    spread.status === "exit_pending_short" ||
    spread.status === "exit_pending_long"
  );
}

function isExitPendingSpread(spread) {
  return spread.status === "exit_pending_short" || spread.status === "exit_pending_long";
}

function isMonitorableSpread(spread) {
  return spread.status === "open" || isExitPendingSpread(spread);
}

function isReplaceableOrder(order) {
  return order.status === "created" || order.status === "submitted" || order.status === "partially_filled";
}

function formatOrderPrice(order) {
  const parts = [];
  if (order.limit_price !== null && order.limit_price !== undefined) {
    parts.push(`L ${formatNumber(order.limit_price)}`);
  }
  if (order.stop_price !== null && order.stop_price !== undefined) {
    parts.push(`S ${formatNumber(order.stop_price)}`);
  }
  return parts.length > 0 ? parts.join(" / ") : "--";
}

function buildSortedPositions(positions) {
  return [...positions].sort((left, right) => toFiniteNumber(right.market_value) - toFiniteNumber(left.market_value));
}

function pnlTone(value) {
  if (value > 0) {
    return "success";
  }
  if (value < 0) {
    return "error";
  }
  return "neutral";
}

function describeStrategyStatus(runtime) {
  if (runtime.kill_switch_active) {
    return {
      value: "Kill Switch",
      tone: "error",
      detail: "New bull put entries are blocked until the kill switch is cleared.",
    };
  }
  if (runtime.manual_pause) {
    return {
      value: "Paused",
      tone: "warning",
      detail: "Manual pause blocks new bull put entries while monitoring stays active.",
    };
  }
  if (!runtime.auto_entry_enabled) {
    return {
      value: "Disabled",
      tone: "neutral",
      detail: "Automatic entry is disabled for this account.",
    };
  }
  if ((runtime.paused_symbols || []).length) {
    return {
      value: "Selective Pause",
      tone: "warning",
      detail: `Paused symbols: ${(runtime.paused_symbols || []).join(", ")}`,
    };
  }
  return {
    value: "Running",
    tone: "success",
    detail: "Automatic bull put entry is enabled for this account.",
  };
}

function preOpenScoreTone(score) {
  const number = toFiniteNumber(score);
  if (number >= 5) {
    return "error";
  }
  if (number >= 3) {
    return "warning";
  }
  return "success";
}

function preOpenRegimeTone(regime) {
  if (regime === "broad_downside_risk") {
    return "error";
  }
  if (regime === "selective_downside_risk") {
    return "warning";
  }
  return "success";
}

function preOpenViewTone(view) {
  if (view === "reasonable") {
    return "warning";
  }
  if (view === "selective") {
    return "neutral";
  }
  return "success";
}

function preOpenActionTone(action) {
  if (action === "wait_for_failed_bounce" || action === "wait_for_open_confirmation") {
    return "warning";
  }
  if (action === "use_intraday_confirmation" || action === "selective_probe_only") {
    return "neutral";
  }
  return "success";
}

function preOpenGapTone(risk) {
  if (risk === "high") {
    return "error";
  }
  if (risk === "medium") {
    return "warning";
  }
  return "success";
}

function preOpenSignalTone(signal) {
  if (signal === "bearish") {
    return "error";
  }
  if (signal === "supportive") {
    return "success";
  }
  return "neutral";
}

function preOpenLiquidityTone(label) {
  if (label === "wide") {
    return "error";
  }
  if (label === "workable") {
    return "warning";
  }
  if (label === "tight") {
    return "success";
  }
  return "neutral";
}

function preOpenTermTone(label) {
  if (label === "front_loaded") {
    return "error";
  }
  if (label === "next_richer") {
    return "warning";
  }
  return "neutral";
}

function preOpenReviewTone(value) {
  if (value === "confirmed") {
    return "success";
  }
  if (value === "failed") {
    return "error";
  }
  if (value === "mixed" || value === "in_progress" || value === "awaiting_open") {
    return "warning";
  }
  return "neutral";
}

function formatPreOpenLabel(value) {
  return String(value || "--")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatOptionTermStructure(label) {
  if (label === "front_loaded") {
    return "Front Loaded";
  }
  if (label === "next_richer") {
    return "Next Richer";
  }
  if (label === "flat") {
    return "Flat";
  }
  return "Unclear";
}

function formatSignedIvDifference(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const points = Math.abs(number) <= 1 ? number * 100 : number;
  const prefix = points > 0 ? "+" : "";
  return `${prefix}${points.toFixed(1)} pts`;
}

function formatPreOpenTimingDetail(assessment) {
  if (assessment.market_open) {
    return "Regular U.S. session is live.";
  }
  if (assessment.minutes_to_regular_open !== null && assessment.minutes_to_regular_open !== undefined) {
    return `${assessment.minutes_to_regular_open} min to 09:30 ET regular open.`;
  }
  if (assessment.next_regular_open_at) {
    const nextOpen = new Date(assessment.next_regular_open_at);
    if (!Number.isNaN(nextOpen.getTime())) {
      const month = String(nextOpen.getMonth() + 1).padStart(2, "0");
      const day = String(nextOpen.getDate()).padStart(2, "0");
      return `Next regular open: ${nextOpen.getFullYear()}-${month}-${day} 09:30 ET.`;
    }
  }
  if (assessment.session === "holiday") {
    return "U.S. equity options are closed for a market holiday.";
  }
  if (assessment.session === "weekend") {
    return "U.S. equity options are closed for the weekend.";
  }
  return `${formatPreOpenLabel(assessment.session)} session snapshot.`;
}

function formatPreOpenNarrative(assessment) {
  const timing = formatPreOpenTimingDetail(assessment);
  if (!assessment.preferred_vehicle) {
    return `${assessment.summary} ${timing} ${assessment.trade_action_detail}`;
  }
  return `${assessment.summary} ${assessment.preferred_vehicle} is the cleaner plain-put expression for now. ${timing}`;
}

function formatSpotDistance(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const prefix = number > 0 ? "+" : "";
  const suffix = number >= 0 ? " OTM" : " ITM";
  return `${prefix}${number.toFixed(2)}%${suffix}`;
}

function formatRuntimeScanResult(value) {
  return String(value || "--")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSignedCurrency(value, currency = "USD") {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${formatCurrency(number, currency)}`;
}

function formatWeight(value, total) {
  const amount = toNumber(value);
  const denominator = toNumber(total);
  if (!Number.isFinite(amount) || !Number.isFinite(denominator) || denominator <= 0) {
    return "--";
  }
  return `${((amount / denominator) * 100).toFixed(1)}%`;
}

function formatPercent(value, base) {
  const numerator = toNumber(value);
  const denominator = toNumber(base);
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) {
    return "--";
  }
  const percent = (numerator / denominator) * 100;
  const prefix = percent > 0 ? "+" : "";
  return `${prefix}${percent.toFixed(2)}% of book`;
}

function formatSignedPercentValue(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(2)}%`;
}

function formatPercentValue(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return `${number.toFixed(2)}%`;
}

function formatSignedDecimal(value, decimals = 2) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(decimals)}`;
}

function formatImpliedVolatility(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  const percent = Math.abs(number) <= 1 ? number * 100 : number;
  return `${percent.toFixed(1)}%`;
}

function formatPositionQuantity(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return number.toLocaleString("en-US", {
    minimumFractionDigits: Number.isInteger(number) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function toNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : Number.NaN;
}

function toFiniteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

async function fetchJson(url, options = {}) {
  const { timeoutMs = null, signal: providedSignal, ...requestOptions } = options;
  const controller = new AbortController();
  const signal = mergeAbortSignals(controller.signal, providedSignal);
  let timeoutId = null;
  if (timeoutMs !== null && timeoutMs !== undefined) {
    timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  }

  try {
    const response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...(requestOptions.headers || {}),
      },
      ...requestOptions,
      signal,
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
  } catch (error) {
    if (error?.name === "AbortError" && timeoutMs !== null && timeoutMs !== undefined) {
      throw new Error(`Request timed out after ${Math.ceil(timeoutMs / 1000)}s.`);
    }
    throw error;
  } finally {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
    }
  }
}

function mergeAbortSignals(...signals) {
  const activeSignals = signals.filter(Boolean);
  if (activeSignals.length === 0) {
    return undefined;
  }
  if (activeSignals.length === 1) {
    return activeSignals[0];
  }
  const controller = new AbortController();
  const abort = () => controller.abort();
  for (const signal of activeSignals) {
    if (signal.aborted) {
      controller.abort();
      return controller.signal;
    }
    signal.addEventListener("abort", abort, { once: true });
  }
  return controller.signal;
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

function buildOverlayStatus(kind, detail = "", reason = "") {
  return { kind, detail, reason };
}

function overlayStatusTone(kind) {
  if (kind === "live") {
    return "success";
  }
  if (kind === "loading" || kind === "timed_out" || kind === "stale") {
    return "warning";
  }
  if (kind === "circuit_open" || kind === "error") {
    return "error";
  }
  return "neutral";
}

function overlayStatusLabel(kind) {
  if (kind === "live") {
    return "Live";
  }
  if (kind === "loading") {
    return "Refreshing";
  }
  if (kind === "timed_out") {
    return "Timed Out";
  }
  if (kind === "circuit_open") {
    return "Circuit Open";
  }
  if (kind === "stale") {
    return "Stale";
  }
  if (kind === "error") {
    return "Unavailable";
  }
  return "Idle";
}

function overlayLiveDetail(label, refreshedAt) {
  const formatted = formatDateTime(refreshedAt);
  if (formatted === "--") {
    return `${label} refreshed successfully.`;
  }
  return `${label} refreshed ${formatted}.`;
}

function classifyOverlayFailure(error, { label, stale = false, staleAt = null } = {}) {
  const reason = error?.message || `Unable to load ${label}.`;
  const normalized = reason.toLowerCase();
  let failureKind = "error";
  if (normalized.includes("timed out")) {
    failureKind = "timed_out";
  } else if (normalized.includes("skipping attempt")) {
    failureKind = "circuit_open";
  }

  if (stale) {
    return buildOverlayStatus(
      "stale",
      buildStaleOverlayDetail(label, failureKind, staleAt),
      reason
    );
  }

  return buildOverlayStatus(
    failureKind,
    buildOverlayFailureDetail(label, failureKind),
    reason
  );
}

function buildOverlayFailureDetail(label, kind) {
  const namedLabel = capitalizeLabel(label);
  if (kind === "timed_out") {
    return `${namedLabel} refresh timed out before fresh broker data loaded.`;
  }
  if (kind === "circuit_open") {
    return `${namedLabel} refresh is paused while the Longbridge circuit breaker cools down.`;
  }
  return `${namedLabel} refresh failed before fresh broker data loaded.`;
}

function buildStaleOverlayDetail(label, failureKind, staleAt) {
  let failureText = "failed";
  if (failureKind === "timed_out") {
    failureText = "timed out";
  } else if (failureKind === "circuit_open") {
    failureText = "hit the Longbridge circuit breaker";
  }
  const lastSuccess = staleAt ? ` Last success ${formatDateTime(staleAt)}.` : "";
  return `Showing the last successful ${label} while the latest refresh ${failureText}.${lastSuccess}`;
}

function renderOverlayReason(status) {
  if (!status?.reason || status.kind === "idle" || status.kind === "loading" || status.kind === "live") {
    return "";
  }
  return `<p class="overlay-reason">Latest refresh: ${escapeHtml(status.reason)}</p>`;
}

function capitalizeLabel(value) {
  const text = String(value || "");
  if (!text) {
    return "";
  }
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatSyncHeadline(lastSyncedAt, lastAttemptAt) {
  if (lastSyncedAt) {
    return `Last success ${formatDateTime(lastSyncedAt)}`;
  }
  if (lastAttemptAt) {
    return `Last attempt ${formatDateTime(lastAttemptAt)}`;
  }
  return "Waiting for first run";
}

function formatSyncDetail(status, lastSyncedAt, lastAttemptAt, error) {
  if (status === "syncing") {
    return lastAttemptAt ? `Started ${formatDateTime(lastAttemptAt)}` : "Sync request is in progress.";
  }
  if (status === "error") {
    return error || "The latest sync failed.";
  }
  if (lastSyncedAt) {
    return `Updated ${formatDateTime(lastSyncedAt)}`;
  }
  if (lastAttemptAt) {
    return `Attempted ${formatDateTime(lastAttemptAt)}`;
  }
  return "No reconciliation run has completed yet.";
}

function reconciliationTone(status) {
  if (status === "success") {
    return "success";
  }
  if (status === "syncing") {
    return "warning";
  }
  if (status === "error") {
    return "error";
  }
  return "neutral";
}

function reconciliationLabel(status) {
  if (status === "success") {
    return "Success";
  }
  if (status === "syncing") {
    return "Syncing";
  }
  if (status === "error") {
    return "Error";
  }
  return "Idle";
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

function journalEntryTone(entryType) {
  if (entryType === "review") {
    return "warning";
  }
  if (entryType === "plan") {
    return "success";
  }
  return "neutral";
}

function spreadStatusClass(status) {
  if (status === "open" || status === "closed") {
    return "success";
  }
  if (
    status === "entry_pending_long" ||
    status === "entry_pending_short" ||
    status === "exit_pending_short" ||
    status === "exit_pending_long"
  ) {
    return "warning";
  }
  if (status === "entry_failed" || status === "rollback_failed") {
    return "error";
  }
  return "neutral";
}

function formatSpreadStatusLabel(status) {
  return String(status || "--")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSpreadExitReason(reason) {
  if (!reason) {
    return "--";
  }
  return String(reason)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatSpreadStrike(value) {
  const number = toNumber(value);
  if (!Number.isFinite(number)) {
    return "--";
  }
  return number.toLocaleString("en-US", {
    minimumFractionDigits: Number.isInteger(number) ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

function formatSpreadDate(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
}

function formatSessionDate(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function formatSpreadCredit(value) {
  if (value === null || value === undefined) {
    return "--";
  }
  return `$${formatSpreadStrike(value)}`;
}

function formatMultilineText(value) {
  return escapeHtml(value).replaceAll("\n", "<br />");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

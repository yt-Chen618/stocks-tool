const LANGUAGE_STORAGE_KEY = "stocks-tool-language";
const DEFAULT_LANGUAGE = "zh";
const BROKER_REQUEST_TIMEOUT_MS = 25000;
const PRE_OPEN_BOARD_TIMEOUT_MS = 35000;
const PRE_OPEN_OVERLAY_TIMEOUT_MS = 70000;
const COVERED_CALL_LIFECYCLE_TIMEOUT_MS = 60000;
const ADVISOR_REQUEST_TIMEOUT_MS = 180000;
const COLLAPSED_MODULES_STORAGE_KEY = "stocks-tool-collapsed-modules";
const IDEMPOTENCY_STORAGE_PREFIX = "stocks-tool-idempotency:";
const MOBILE_TRADING_QUERY = "(max-width: 780px)";
const {
  toNumber,
  toFiniteNumber,
  formatCurrency,
  formatNumber,
  formatDateTime,
  formatSignedCurrency,
  formatWeight,
  formatPercent,
  formatSignedPercentValue,
  formatPercentValue,
  formatSignedDecimal,
  formatImpliedVolatility,
  formatPositionQuantity,
  formatOrderAge,
  formatSyncHeadline,
  formatSyncDetail,
  reconciliationTone,
  reconciliationLabel,
  statusClass,
  strategyStatusClass,
  journalEntryTone,
  spreadStatusClass,
  formatSpreadStatusLabel,
  formatStrategyStatusLabel,
  formatSpreadExitReason,
  formatSpreadStrike,
  formatSpreadDate,
  formatSessionDate,
  formatSpreadCredit,
} = window.StocksToolFormatters;
const TEXT_NODE_ORIGINALS = new WeakMap();
const ATTRIBUTE_ORIGINALS = new WeakMap();
const TRANSLATIONS = window.StocksToolI18n.TRANSLATIONS;

const state = window.StocksToolState.createInitialState();

const els = {};
let accountLoader = null;
let bullPutView = null;
let strategyView = null;
let advisorView = null;
let ordersView = null;
let operationsRecoveryView = null;
let isApplyingLanguage = false;
let languageObserver = null;
let languageFrame = null;

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  initializeViewModules();
  window.StocksToolExecution?.init();
  window.StocksToolWorkspace?.init();
  enhanceCollapsibleModules();
  wireEvents();
  bindTradingViewportGuard();
  startLanguageObserver();
  if (document.body.dataset.demo === "true") {
    state.language = DEFAULT_LANGUAGE;
  }
  updateLanguageControls();
  applyLanguage();
  ordersView?.syncTicketOrderFields();
  ordersView?.renderSelectedOrder();
  window.StocksToolResearch?.init();
  await window.StocksToolWatchlists?.init();
  await loadDashboard();
  if (document.body.dataset.demo === "true" && state.language !== DEFAULT_LANGUAGE) {
    state.language = DEFAULT_LANGUAGE;
    applyLanguage();
  }
});

function initializeViewModules() {
  const fetchJson = window.StocksToolApiClient.fetchJson;
  const decodeCursorPage = window.StocksToolApiClient.decodeCursorPage;
  const createOverlayStatus = window.StocksToolState.createOverlayStatus;
  operationsRecoveryView = window.StocksToolOperationsRecovery;
  operationsRecoveryView?.init({
    root: "#operations-recovery-panel",
  });
  accountLoader = window.StocksToolAccountLoader?.createAccountLoader({
    state,
    fetchJson,
    decodeCursorPage,
    createOverlayStatus,
    formatPanelLoadLabel,
    renderAccountOptions: () => renderAccountOptions(),
    renderEmptyState: () => renderEmptyAccountState(),
    renderAccountState: (payload) => renderAccountDataState(payload),
    renderRecoveryLoading: () => operationsRecoveryView?.renderLoading(),
    renderRecoveryStatus: (snapshot) => operationsRecoveryView?.render(snapshot),
    renderRecoveryError: (error) => operationsRecoveryView?.renderError(error),
    applyTradingSafetyState,
    updateSyncButtons,
    updateOrderTicketAvailability: () => ordersView?.updateOrderTicketAvailability(),
    updatePreOpenButtons,
  });
  window.StocksToolAccountLoaderRuntime = accountLoader;
  bullPutView = window.StocksToolBullPutView?.createBullPutView({
    state,
    els,
    accountLoader,
    runConfirmedBrokerMutation,
    setStatus,
    setActionStatus,
    loadAccountData: () => accountLoader?.loadAccountData(),
    applyTradingSafetyState,
    escapeHtml,
    formatters: window.StocksToolFormatters,
  });
  strategyView = window.StocksToolStrategyView?.createStrategyView({
    state,
    els,
    escapeHtml,
    formatters: window.StocksToolFormatters,
    helpers: {
      describeStrategyStatus,
      formatRuntimeNextAction,
      pnlTone,
      updateStrategyButtons,
      updateZeroDteLotteryButtons,
      renderStrategyProposalDetails,
      renderStrategyProposalActions,
      renderStrategyProposalDetail,
      displayValue,
    },
  });
  advisorView = window.StocksToolAdvisorView?.createAdvisorView({
    state,
    els,
    fetchJson,
    decodeCursorPage,
    createOverlayStatus,
    setStatus,
    reloadAccountData: () => accountLoader?.loadAccountData(),
    escapeHtml,
    formatters: window.StocksToolFormatters,
  });
  ordersView = window.StocksToolOrdersView?.createOrdersView({
    state,
    els,
    fetchJson,
    decodeCursorPage,
    reloadAccountData: () => accountLoader?.loadAccountData(),
    loadActivityPage: (...args) => accountLoader?.loadActivityPage(...args),
    loadSelectedOrderDetails: (...args) => accountLoader?.loadSelectedOrderDetails(...args),
    ensureSelectedOrderDetail: (...args) => accountLoader?.ensureSelectedOrderDetail(...args),
    runConfirmedBrokerMutation,
    setStatus,
    setActionStatus,
    applyTradingSafetyState,
    setBusinessDisabled,
    matchingQuoteTime,
    escapeHtml,
    formatMultilineText,
    formatters: window.StocksToolFormatters,
    parsePositiveInteger,
    parsePositiveNumber,
    normalizeOptionalText,
    parseTags,
    workspace: window.StocksToolWorkspace,
  });
  advisorView?.wireEvents();
  ordersView?.wireEvents();
}

function bindElements() {
  els.languageOptions = Array.from(document.querySelectorAll("[data-lang-option]"));
  els.accountSelect = document.getElementById("account-select");
  els.statusBanner = document.getElementById("status-banner");
  els.desktopTradingNotice = document.getElementById("desktop-trading-notice");
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
  els.zeroDteLotteryStrip = document.getElementById("zero-dte-lottery-strip");
  els.zeroDteLotteryControlsForm = document.getElementById("zero-dte-lottery-controls-form");
  els.zeroDteLotteryAutoOrder = document.getElementById("zero-dte-lottery-auto-order");
  els.zeroDteLotterySymbol = document.getElementById("zero-dte-lottery-symbol");
  els.zeroDteLotteryDirection = document.getElementById("zero-dte-lottery-direction");
  els.zeroDteLotteryHint = document.getElementById("zero-dte-lottery-hint");
  els.previewZeroDteLottery = document.getElementById("preview-zero-dte-lottery");
  els.zeroDteLotteryResultCard = document.getElementById("zero-dte-lottery-result-card");
  els.strategyExperimentStrip = document.getElementById("strategy-experiment-strip");
  els.coveredCallActivityCard = document.getElementById("covered-call-activity-card");
  els.coveredCallActionStatus = document.getElementById("covered-call-action-status");
  els.strategyProposalsCard = document.getElementById("strategy-proposals-card");
  els.strategyRunsCard = document.getElementById("strategy-runs-card");
  els.strategySignalsCard = document.getElementById("strategy-signals-card");
  els.strategyReviewsCard = document.getElementById("strategy-reviews-card");
  els.loadAdvisorContext = document.getElementById("load-advisor-context");
  els.runDeepSeekAdvisor = document.getElementById("run-deepseek-advisor");
  els.recordAdvisorResponse = document.getElementById("record-advisor-response");
  els.advisorOutputCard = document.getElementById("advisor-output-card");
  els.marketEventsCard = document.getElementById("market-events-card");
  els.spreadSummaryStrip = document.getElementById("spread-summary-strip");
  els.spreadsBody = document.getElementById("spreads-body");
  els.bullPutHistoryPanel = document.getElementById("bull-put-history-panel");
  els.bullPutHistoryStatus = document.getElementById("bull-put-history-status");
  els.bullPutHistoryBody = document.getElementById("bull-put-history-body");
  els.bullPutHistoryLoadMore = document.getElementById("bull-put-history-load-more");
  els.ordersBody = document.getElementById("orders-body");
  els.ordersLoadMore = document.getElementById("orders-load-more");
  els.executionsLoadMore = document.getElementById("executions-load-more");
  els.journalsLoadMore = document.getElementById("journals-load-more");
  els.positionsBody = document.getElementById("positions-body");
  els.brokerStatus = document.getElementById("broker-status");
  els.loadPreOpenBoard = document.getElementById("load-preopen-board");
  els.loadPreOpenOverlays = document.getElementById("load-preopen-overlays");
  els.savePreOpenBoard = document.getElementById("save-preopen-board");
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
  els.orderActionStatus = document.getElementById("order-action-status");
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
  els.replaceSubmit = els.replaceOrderForm?.querySelector("button[type='submit']") || null;
  els.tradeConfirmDialog = document.getElementById("trade-confirm-dialog");
  els.tradeConfirmTitle = document.getElementById("trade-confirm-title");
  els.tradeConfirmSummary = document.getElementById("trade-confirm-summary");
  els.tradeConfirmDetails = document.getElementById("trade-confirm-details");
}

function renderEmptyAccountState() {
  renderReconciliationStatus();
  renderMetrics();
  renderHoldings();
  renderPreOpenAssessment();
  renderLatestPreOpenRun();
  strategyView?.renderStrategyRuntime();
  strategyView?.renderZeroDteLottery();
  strategyView?.renderCoveredCallActivity();
  strategyView?.renderStrategyExperiment();
  advisorView?.renderAdvisorPanel();
  strategyView?.renderMarketEvents();
  bullPutView?.render();
  ordersView?.render();
  renderPositions();
  updateSyncButtons();
  ordersView?.updateOrderTicketAvailability();
  updatePreOpenButtons();
  applyTradingSafetyState();
  notifyWorkbenchAccountState("empty");
}

function renderAccountDataState({ errors, requiredFailures, optionalFailures }) {
  if (state.preOpenRuns) {
    seedPreOpenAssessmentFromLatestRun({ clearWhenMissing: true });
  }
  renderReconciliationStatus();
  renderMetrics();
  renderHoldings();
  renderPreOpenAssessment();
  renderLatestPreOpenRun();
  strategyView?.renderStrategyRuntime();
  strategyView?.renderZeroDteLottery();
  strategyView?.renderCoveredCallActivity();
  strategyView?.renderStrategyExperiment();
  advisorView?.renderAdvisorPanel();
  strategyView?.renderMarketEvents();
  bullPutView?.render();
  ordersView?.render();
  renderPositions();
  renderPanelLoadStates(errors || {});
  updateSyncButtons();
  ordersView?.updateOrderTicketAvailability();
  updatePreOpenButtons();
  applyTradingSafetyState();
  if (state.selectedOrderId && state.selectedOrderDetailOrderId !== state.selectedOrderId) {
    void ordersView?.loadSelectedDetails(state.selectedOrderId);
  }
  void requiredFailures;
  void optionalFailures;
  notifyWorkbenchAccountState("loaded");
}

function notifyWorkbenchAccountState(reason) {
  try {
    window.dispatchEvent(new CustomEvent("stocks-tool:account-state", {
      detail: { state, reason },
    }));
  } catch (_error) {
    // The legacy dashboard remains usable when the enhanced surface is absent.
  }
}

function wireEvents() {
  for (const button of els.languageOptions) {
    button.addEventListener("click", () => {
      setLanguage(button.dataset.langOption || DEFAULT_LANGUAGE);
    });
  }

  els.accountSelect.addEventListener("change", async (event) => {
    state.selectedAccountId = event.target.value;
    window.StocksToolWorkspace?.updateAccountContext(state.selectedAccountId || "--");
    void refreshResearchContext();
    advisorView?.resetAdvisorState();
    setStatus(`Loading account ${state.selectedAccountId}...`, "warning");
    const loadResult = await loadAccountData();
    if (loadResult.discarded) {
      return;
    }
    if (!loadResult.coreHealthy) {
      setStatus(`Core account data is stale: ${loadResult.requiredFailures.join(", ")}.`, "error");
    } else if ((state.unresolvedTradingIntents || []).length > 0) {
      setStatus(
        `Trading blocked: ${state.unresolvedTradingIntents.length} unresolved trading intent(s) require reconciliation.`,
        "error"
      );
    } else if (loadResult.optionalFailures.length) {
      setStatus(`Account loaded with auxiliary failures: ${loadResult.optionalFailures.join(", ")}.`, "warning");
    } else {
      setStatus(`Account ${state.selectedAccountId} loaded.`, "success");
    }
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

  els.loadPreOpenBoard.addEventListener("click", async () => {
    await loadPreOpenAssessment({
      includeOptionOverlays: false,
      timeoutMs: PRE_OPEN_BOARD_TIMEOUT_MS,
    });
  });

  els.loadPreOpenOverlays.addEventListener("click", async () => {
    await loadPreOpenAssessment({
      includeOptionOverlays: true,
      timeoutMs: PRE_OPEN_OVERLAY_TIMEOUT_MS,
    });
  });

  els.savePreOpenBoard.addEventListener("click", async () => {
    await saveCurrentPreOpenBoard();
  });

  els.strategyControlsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveStrategyControls(els.saveStrategyControls);
  });

  els.runStrategyScan.addEventListener("click", async () => {
    await runStrategyScan(els.runStrategyScan);
  });

  els.runStrategyReview.addEventListener("click", async () => {
    await runStrategyReview();
  });

  if (els.zeroDteLotteryControlsForm) {
    els.zeroDteLotteryControlsForm.addEventListener("submit", (event) => {
      event.preventDefault();
    });
  }

  if (els.previewZeroDteLottery) {
    els.previewZeroDteLottery.addEventListener("click", async () => {
      await previewZeroDteLottery();
    });
  }

  bullPutView?.wireEvents();

  if (els.strategyProposalsCard) {
    els.strategyProposalsCard.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-proposal-action]");
      if (!button) {
        return;
      }

      const { proposalAction, proposalId } = button.dataset;
      if (!proposalAction || !proposalId) {
        return;
      }
      await handleStrategyProposalAction(proposalAction, proposalId, button);
    });
  }

  if (els.coveredCallActivityCard) {
    els.coveredCallActivityCard.addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-covered-call-action]");
      if (!button) {
        return;
      }

      const action = button.dataset.coveredCallAction;
      if (action !== "reconcile-lifecycle") {
        return;
      }

      await reconcileCoveredCallLifecycle(button);
    });
  }

}

function enhanceCollapsibleModules() {
  const modules = Array.from(document.querySelectorAll(".band, .panel")).filter(
    (module) => !module.closest("#execution-drawer") && !module.matches("[data-workspace-panel]")
  );
  const collapsedModules = readCollapsedModules();

  modules.forEach((module, index) => {
    const header = module.querySelector(":scope > .band-header, :scope > .panel-header");
    if (!header || header.querySelector("[data-module-collapse-toggle]")) {
      return;
    }

    const key = module.id || buildCollapsibleModuleKey(module, header, index);
    module.dataset.collapseKey = key;
    header.classList.add("collapsible-header");

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "module-collapse-toggle";
    toggle.dataset.moduleCollapseToggle = "true";
    toggle.innerHTML = `
      <span class="collapse-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" focusable="false">
          <path d="m6 9 6 6 6-6"></path>
        </svg>
      </span>
    `;
    header.appendChild(toggle);

    setModuleCollapsed(module, toggle, Boolean(collapsedModules[key]));

    toggle.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleModuleCollapsed(module, toggle, collapsedModules);
    });

    header.addEventListener("click", (event) => {
      if (event.defaultPrevented || isModuleCollapseInteractiveTarget(event.target)) {
        return;
      }
      toggleModuleCollapsed(module, toggle, collapsedModules);
    });
  });
}

function buildCollapsibleModuleKey(module, header, index) {
  const title = header.querySelector("h2")?.textContent?.trim() || "module";
  const kind = module.classList.contains("band") ? "band" : "panel";
  return `${kind}:${index}:${title}`;
}

function readCollapsedModules() {
  try {
    const stored = window.localStorage.getItem(COLLAPSED_MODULES_STORAGE_KEY);
    const parsed = stored ? JSON.parse(stored) : {};
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function writeCollapsedModules(collapsedModules) {
  try {
    window.localStorage.setItem(COLLAPSED_MODULES_STORAGE_KEY, JSON.stringify(collapsedModules));
  } catch {
    // Ignore storage failures; collapse state still works for this page load.
  }
}

function toggleModuleCollapsed(module, toggle, collapsedModules) {
  const nextCollapsed = !module.classList.contains("is-collapsed");
  setModuleCollapsed(module, toggle, nextCollapsed);

  const key = module.dataset.collapseKey;
  if (key) {
    if (nextCollapsed) {
      collapsedModules[key] = true;
    } else {
      delete collapsedModules[key];
    }
    writeCollapsedModules(collapsedModules);
  }
}

function setModuleCollapsed(module, toggle, collapsed) {
  module.classList.toggle("is-collapsed", collapsed);
  toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
  toggle.setAttribute("aria-label", collapsed ? "Expand module" : "Collapse module");
  toggle.title = collapsed ? "Expand module" : "Collapse module";
}

function isModuleCollapseInteractiveTarget(target) {
  if (!(target instanceof Element)) {
    return false;
  }
  return Boolean(
    target.closest(
      "a, button, input, select, textarea, label, summary, [role='button'], [data-module-collapse-toggle], .panel-actions"
    )
  );
}

function setLanguage(language) {
  if (language !== "en" && language !== "zh") {
    return;
  }
  if (state.language === language) {
    return;
  }
  state.language = language;
  try {
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // Ignore storage failures; the active page can still switch language.
  }
  renderAllForLanguage();
  applyLanguage();
}

function renderAllForLanguage() {
  renderAccountOptions();
  renderReconciliationStatus();
  renderMetrics();
  renderHoldings();
  renderPreOpenAssessment();
  renderLatestPreOpenRun();
  strategyView?.renderStrategyRuntime();
  bullPutView?.render();
  ordersView?.renderOrders();
  renderPositions();
  ordersView?.renderSelectedOrder();
  ordersView?.syncTicketOrderFields();
  const selectedOrder = ordersView?.getSelectedOrder();
  if (selectedOrder && !els.replaceOrderForm.classList.contains("hidden")) {
    ordersView?.syncReplaceOrderFields(selectedOrder.order_type);
  }
}

function startLanguageObserver() {
  if (languageObserver || !document.body) {
    return;
  }
  languageObserver = new MutationObserver(() => {
    scheduleLanguageRefresh();
  });
  languageObserver.observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ["placeholder", "title"],
  });
}

function scheduleLanguageRefresh() {
  if (isApplyingLanguage || languageFrame !== null) {
    return;
  }
  languageFrame = window.requestAnimationFrame(() => {
    languageFrame = null;
    applyLanguage();
  });
}

function applyLanguage() {
  if (!document.body || isApplyingLanguage) {
    return;
  }
  isApplyingLanguage = true;
  try {
    document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
    updateLanguageControls();
    translateTextNodes(document.body);
    translateElementAttributes(document.body);
  } finally {
    isApplyingLanguage = false;
  }
}

function updateLanguageControls() {
  if (!els.languageOptions) {
    return;
  }
  for (const button of els.languageOptions) {
    const active = button.dataset.langOption === state.language;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
}

function translateTextNodes(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const dictionary = TRANSLATIONS[state.language] || {};
  let node = walker.nextNode();
  while (node) {
    let original = TEXT_NODE_ORIGINALS.get(node);
    const current = node.nodeValue || "";
    if (original === undefined) {
      original = current;
      TEXT_NODE_ORIGINALS.set(node, original);
    } else if (state.language !== "en" && current !== original && current !== translatedTextForOriginal(original, dictionary)) {
      original = current;
      TEXT_NODE_ORIGINALS.set(node, original);
    }

    const trimmed = original.trim();
    if (trimmed) {
      if (state.language === "en") {
        node.nodeValue = original;
      } else {
        const translated = translatedTextForOriginal(original, dictionary);
        if (translated !== original) {
          node.nodeValue = translated;
        }
      }
    }
    node = walker.nextNode();
  }
}

function translatedTextForOriginal(original, dictionary) {
  const trimmed = String(original || "").trim();
  const translated = translateText(trimmed, dictionary);
  if (!trimmed || !translated) {
    return original;
  }
  return original.replace(trimmed, translated);
}

function translateText(text, dictionary) {
  if (!text) {
    return "";
  }
  if (dictionary[text]) {
    return dictionary[text];
  }
  if (state.language !== "zh") {
    return "";
  }

  const dynamicRules = [
    [/^Loading account (.+)\.\.\.$/, "正在读取账户 $1..."],
    [/^Account (.+) loaded\.$/, "账户 $1 已读取。"],
    [/^Account loaded with auxiliary failures: (.+)\.$/, "账户已读取；以下辅助信息暂不可用：$1。"],
    [/^Core account data is stale: (.+)\.$/, "核心账户数据已陈旧：$1。"],
    [/^Refreshing covered-call lifecycle for (.+)\.\.\.$/, "正在刷新 $1 的备兑看涨生命周期..."],
    [/^Covered-call lifecycle refreshed: (.+)\.$/, "备兑看涨生命周期已刷新：$1。"],
    [/^Live macro board refreshed (.+)\.$/, "实时宏观板已于 $1 刷新。"],
    [/^Showing the latest stored macro board captured (.+)\.$/, "正在显示 $1 捕获的最新存档宏观板。"],
    [/^Latest stored run for (.+)\.$/, "最新存储运行对应 $1。"],
    [/^Select a broker account before loading the macro board\.$/, "加载宏观板前请先选择券商账户。"],
    [/^No stored macro board is available yet\. Load it on demand when strategy work is done\.$/, "暂无存储的宏观板。策略工作完成后可按需加载。"],
    [/^(.+) proxies \/ option overlays skipped$/, "$1 个代理 / 已跳过期权叠加层"],
    [/^(.+) proxies \/ (.+) puts \/ (.+) chain layers$/, "$1 个代理 / $2 个看跌快照 / $3 个期权链层"],
    [/^Syncing account (.+)\.\.\.$/, "正在同步账户 $1..."],
    [/^Core account data is stale: (.+)\. Broker-writing actions are disabled\.$/, "核心账户数据已陈旧：$1。券商写操作已锁定。"],
    [/^Core account data updated\. Auxiliary panels unavailable: (.+)\.$/, "核心账户数据已更新；辅助面板暂不可用：$1。"],
    [/^Trading blocked: (.+) unresolved trading intent\(s\) require reconciliation\.$/, "交易已阻塞：$1 个订单意图需要核对。"],
    [/^Account (.+) synced\.$/, "账户 $1 已同步。"],
    [/^Syncing orders for (.+)\.\.\.$/, "正在同步 $1 的订单..."],
    [/^Orders for (.+) synced\.$/, "$1 的订单已同步。"],
    [/^Saving bull put controls for (.+)\.\.\.$/, "正在保存 $1 的牛市看跌控制项..."],
    [/^Bull put controls updated for (.+)\.$/, "$1 的牛市看跌控制项已更新。"],
    [/^Saving live macro board for (.+)\.\.\.$/, "正在保存 $1 的实时宏观板..."],
    [/^Stored macro board for (.+)\.$/, "已保存 $1 的宏观板。"],
    [/^Running bull put scan for (.+)\.\.\.$/, "正在为 $1 运行牛市看跌扫描..."],
    [/^Bull put scan opened (.+)\.$/, "牛市看跌扫描已开仓 $1。"],
    [/^Running bull put review for (.+)\.\.\.$/, "正在为 $1 运行牛市看跌复盘..."],
    [/^Submitting (.+) order for (.+)\.\.\.$/, "正在提交 $2 的 $1 订单..."],
    [/^Order submitted for (.+)\.$/, "$1 订单已提交。"],
    [/^Refreshing order (.+)\.\.\.$/, "正在刷新 $1 订单..."],
    [/^Order (.+) refreshed\.$/, "$1 订单已刷新。"],
    [/^Refreshing spread (.+)\.\.\.$/, "正在刷新 $1 价差..."],
    [/^Spread (.+) refreshed\.$/, "$1 价差已刷新。"],
    [/^Monitoring spread (.+)\.\.\.$/, "正在监控 $1 价差..."],
    [/^Canceling order (.+)\.\.\.$/, "正在取消 $1 订单..."],
    [/^Order (.+) canceled\.$/, "$1 订单已取消。"],
    [/^Replacing order (.+)\.\.\.$/, "正在修改 $1 订单..."],
    [/^Order (.+) updated\.$/, "$1 订单已更新。"],
    [/^Saving (.+) entry for (.+)\.\.\.$/, "正在保存 $2 的 $1 记录..."],
    [/^Journal entry saved for (.+)\.$/, "$1 的日志记录已保存。"],
    [/^New entries will attach to (.+) on (.+)\.$/, "新记录将关联到 $2 上的 $1。"],
    [/^New entries will attach (.+) for (.+)\.$/, "新记录将为 $2 关联 $1。"],
    [/^Last success (.+)$/, "最近成功 $1"],
    [/^Last attempt (.+)$/, "最近尝试 $1"],
    [/^Updated (.+)$/, "更新于 $1"],
    [/^Attempted (.+)$/, "尝试于 $1"],
    [/^Started (.+)$/, "开始于 $1"],
    [/^Session (.+)$/, "交易日 $1"],
    [/^Latest snapshot (.+)$/, "最新快照 $1"],
    [/^(.+) profitable \/ (.+) losing$/, "$1 个盈利 / $2 个亏损"],
    [/^(.+) open \/ (.+) exit pending$/, "$1 个打开 / $2 个平仓待处理"],
    [/^(.+) min to 09:30 ET regular open\.$/, "距离美东 09:30 正常开盘 $1 分钟。"],
  ];

  for (const [pattern, replacement] of dynamicRules) {
    if (pattern.test(text)) {
      return text.replace(pattern, replacement);
    }
  }

  return "";
}

function translateElementAttributes(root) {
  const dictionary = TRANSLATIONS[state.language] || {};
  const elements = root.querySelectorAll("[placeholder], [title]");
  for (const element of elements) {
    let originals = ATTRIBUTE_ORIGINALS.get(element);
    if (!originals) {
      originals = {};
      ATTRIBUTE_ORIGINALS.set(element, originals);
    }

    for (const attribute of ["placeholder", "title"]) {
      if (!element.hasAttribute(attribute)) {
        continue;
      }
      if (!Object.prototype.hasOwnProperty.call(originals, attribute)) {
        originals[attribute] = element.getAttribute(attribute) || "";
      }
      let original = originals[attribute];
      const current = element.getAttribute(attribute) || "";
      const translated = dictionary[original] || original;
      if (state.language !== "en" && current !== original && current !== translated) {
        original = current;
        originals[attribute] = original;
      }
      if (state.language === "en") {
        element.setAttribute(attribute, original);
      } else {
        element.setAttribute(attribute, dictionary[original] || original);
      }
    }
  }
}

function bindTradingViewportGuard() {
  const mediaQuery = window.matchMedia?.(MOBILE_TRADING_QUERY);
  if (mediaQuery?.addEventListener) {
    mediaQuery.addEventListener("change", applyTradingSafetyState);
  }
  applyTradingSafetyState();
}

function isMobileTradingViewport() {
  return window.matchMedia?.(MOBILE_TRADING_QUERY).matches ?? window.innerWidth <= 780;
}

function mutationScopeKey(accountId, actionKey) {
  return `${String(accountId || "")}::${String(actionKey || "")}`;
}

function pendingActionKeysForAccount(accountId = state.selectedAccountId) {
  const prefix = `${String(accountId || "")}::`;
  return new Set(
    Array.from(state.pendingActionKeys || [])
      .filter((key) => String(key).startsWith(prefix))
      .map((key) => String(key).slice(prefix.length)),
  );
}

function mutationContextIsCurrent(accountId, accountLoadGeneration) {
  return accountId === state.selectedAccountId && accountLoadGeneration === state.accountLoadGeneration;
}

function recordUnknownMutationLock(accountId, intent) {
  state.unknownMutationLocks ||= {};
  state.terminalUnknownMutationIds ||= {};
  state.terminalUnknownMutationIds[accountId] = (state.terminalUnknownMutationIds[accountId] || []).filter((id) => id !== intent.id);
  const current = Array.isArray(state.unknownMutationLocks[accountId])
    ? state.unknownMutationLocks[accountId]
    : [];
  state.unknownMutationLocks[accountId] = [
    intent,
    ...current.filter((candidate) => candidate.id !== intent.id),
  ];
  if (state.selectedAccountId === accountId) {
    state.unresolvedTradingIntents = [
      ...state.unknownMutationLocks[accountId],
      ...(state.unresolvedTradingIntents || []).filter((candidate) => candidate.id !== intent.id),
    ];
  }
}

function clearOwnedUnknownMutationLock(accountId, actionKey, idempotencyKey) {
  if (!idempotencyKey) return;
  const locks = state.unknownMutationLocks?.[accountId];
  if (!Array.isArray(locks)) return;
  state.unknownMutationLocks[accountId] = locks.filter(
    (lock) => !(lock.idempotency_key === idempotencyKey && (!lock.action_key || lock.action_key === actionKey)),
  );
}

function evaluateCurrentTradingSafety(options = {}) {
  const evaluator = window.StocksToolTradingSafety?.evaluateTradingSafety;
  if (typeof evaluator !== "function") {
    return { blocked: true, reasons: ["safety_module_unavailable"] };
  }
  return evaluator({
    accountId: options.accountId ?? state.selectedAccountId,
    selectedAccountId: state.selectedAccountId,
    mode: options.mode ?? "paper",
    expectedContext: options.expectedContext ?? null,
    requestSignature: options.requestSignature,
    accountLoadGeneration: state.accountLoadGeneration,
    coreDataHealthy: state.coreDataHealthy,
    recoveryStatusState: state.recoveryStatusState,
    recoveryStatus: state.recoveryStatus,
    unresolvedTradingIntents: state.unresolvedTradingIntents,
    mobileBlocked: options.mobileBlocked ?? isMobileTradingViewport(),
    pendingActionKeys: pendingActionKeysForAccount(state.selectedAccountId),
    actionKey: options.actionKey,
    ignorePendingAction: options.ignorePendingAction === true,
    businessDisabled: options.businessDisabled === true,
  });
}

function applyTradingSafetyState() {
  const mobileBlocked = isMobileTradingViewport();
  window.StocksToolExecution?.setMobileReadonly(mobileBlocked);
  document.querySelectorAll("button[data-broker-mutation='true']").forEach((button) => {
    const pending = state.pendingActionKeys.has(mutationScopeKey(state.selectedAccountId, button.dataset.actionKey || ""));
    const businessDisabled = button.dataset.businessDisabled === "true";
    const safety = evaluateCurrentTradingSafety({
      actionKey: button.dataset.actionKey || "",
      mobileBlocked,
      businessDisabled,
    });
    const blocked = safety.blocked;
    button.disabled = blocked;
    button.setAttribute("aria-disabled", String(blocked));
    button.setAttribute("aria-busy", String(pending));
    if (safety.blocked && !button.dataset.safetyOriginalTitle) {
      button.dataset.safetyOriginalTitle = button.title || "";
    }
    if (mobileBlocked) {
      button.title = "Use the desktop workbench for broker-writing actions.";
    } else if (safety.reasons.includes("core_data_unhealthy")) {
      button.title = "Required account data is stale. Refresh the dashboard before trading.";
    } else if (safety.reasons.includes("recovery_status_unavailable")) {
      button.title = "Recovery status is loading or unavailable. Broker-writing actions remain locked.";
    } else if (safety.reasons.includes("recovery_blocked")) {
      button.title = "Recovery evidence blocks broker-writing actions until reconciliation is complete.";
    } else if (safety.reasons.includes("unresolved_trading_intent")) {
      button.title = "An unresolved trading intent blocks all broker-writing actions.";
    } else if (button.dataset.safetyOriginalTitle !== undefined) {
      button.title = button.dataset.safetyOriginalTitle;
      delete button.dataset.safetyOriginalTitle;
    }
  });
}

function setBusinessDisabled(button, disabled, title = "") {
  if (!button) {
    return;
  }
  button.dataset.businessDisabled = String(Boolean(disabled));
  button.title = title;
}

function setActionStatus(element, message, tone = "") {
  if (!element) {
    return;
  }
  element.textContent = message;
  element.classList.remove("success", "warning", "error");
  if (tone) {
    element.classList.add(tone);
  }
}

function tradingBlockedMessage(options = {}) {
  const safety = evaluateCurrentTradingSafety(options);
  if (!safety.blocked) return "";
  if (safety.reasons.includes("mobile_viewport")) return "Broker-writing actions are desktop-only. No request was sent.";
  if (safety.reasons.includes("core_data_unhealthy")) return "Required account data is stale. Refresh the dashboard before trading.";
  if (safety.reasons.includes("recovery_status_unavailable")) return "Recovery status is loading or unavailable. No request was sent.";
  if (safety.reasons.includes("recovery_blocked")) return "Recovery evidence blocks broker-writing actions until reconciliation completes.";
  if (safety.reasons.includes("unresolved_trading_intent")) return "An unresolved trading intent blocks all broker-writing actions until reconciliation completes.";
  if (safety.reasons.includes("account_context_changed") || safety.reasons.includes("mode_context_changed")) return "The selected account or execution mode changed. Review the action again before sending.";
  if (safety.reasons.includes("request_signature_changed")) return "The action details changed while confirmation was open. Review the action again before sending.";
  if (safety.reasons.includes("business_disabled")) return "This action is no longer eligible. No request was sent.";
  if (safety.reasons.includes("safety_module_unavailable")) return "Trading safety checks are unavailable. No request was sent.";
  return "Trading safety checks blocked this action. No request was sent.";
}
async function runConfirmedBrokerMutation(
  { actionKey, button, confirmation, requestSignature, getRequestSignature, statusElement, accountId = state.selectedAccountId, mode = "paper", businessPredicate, businessBlockedMessage },
  operation
) {
  const accountLoadGeneration = state.accountLoadGeneration;
  const expectedContext = { accountId, mode, requestSignature, accountLoadGeneration };
  const scopedActionKey = mutationScopeKey(accountId, actionKey);
  const businessDisabled = button?.dataset.businessDisabled === "true" || (typeof businessPredicate === "function" && !businessPredicate());
  const blockedMessage = businessDisabled && businessBlockedMessage
    ? businessBlockedMessage
    : tradingBlockedMessage({ actionKey, accountId, mode, expectedContext, requestSignature, businessDisabled });
  if (blockedMessage) {
    setActionStatus(statusElement, blockedMessage, "error");
    setStatus(blockedMessage, "error");
    return { executed: false, blocked: true };
  }
  if (state.pendingActionKeys.has(scopedActionKey)) {
    return { executed: false, duplicate: true };
  }

  state.pendingActionKeys.add(scopedActionKey);
  applyTradingSafetyState();
  let idempotencyKey = null;
  try {
    setActionStatus(statusElement, "Review the paper action confirmation.", "warning");
    const confirmed = await showTradeConfirmation(confirmation);
    if (!confirmed) {
      const message = "Paper action canceled. No request was sent.";
      setActionStatus(statusElement, message, "warning");
      setStatus(message, "warning");
      return { executed: false, canceled: true };
    }

    const currentRequestSignature = typeof getRequestSignature === "function"
      ? getRequestSignature()
      : requestSignature;
    const postConfirmationBlocked = tradingBlockedMessage({
      actionKey,
      accountId,
      mode,
      expectedContext,
      requestSignature: currentRequestSignature,
      ignorePendingAction: true,
      businessDisabled: button?.dataset.businessDisabled === "true" || (typeof businessPredicate === "function" && !businessPredicate()),
    });
    if (postConfirmationBlocked) {
      const message = (typeof businessPredicate === "function" && !businessPredicate() && businessBlockedMessage)
        ? businessBlockedMessage
        : postConfirmationBlocked;
      setActionStatus(statusElement, message, "error");
      setStatus(message, "error");
      return { executed: false, blocked: true, contextChanged: true };
    }

    idempotencyKey = getOrCreateIdempotencyKey(actionKey, requestSignature, accountId, mode);
    const result = await operation(idempotencyKey);
    clearOwnedUnknownMutationLock(accountId, actionKey, idempotencyKey);
    clearIdempotencyKey(actionKey, accountId);
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) {
      return { executed: false, discarded: true, result };
    }
    return { executed: true, result };
  } catch (error) {
    if (error?.code === "order_outcome_unknown") {
      const intentId = error.intentId || `${actionKey}:${idempotencyKey || "unknown"}`;
      recordUnknownMutationLock(accountId, {
        id: intentId,
        state: "unknown",
        source: "broker-mutation-response",
        external_account_id: accountId,
        mode,
        action_key: actionKey,
        idempotency_key: idempotencyKey,
      });
      persistUnknownMutationIntent({ accountId, mode, actionKey, requestSignature, idempotencyKey, intentId });
    }
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) {
      if (isTerminalMutationError(error)) {
        clearOwnedUnknownMutationLock(accountId, actionKey, idempotencyKey);
        clearIdempotencyKey(actionKey, accountId);
      }
      return { executed: false, discarded: true, error };
    }
    if (error?.code === "order_outcome_unknown") {
      const intentId = error.intentId || "unknown";
      setActionStatus(
        statusElement,
        "Order outcome is unknown. Trading is locked pending reconciliation.",
        "error"
      );
    }
    if (isTerminalMutationError(error)) {
      clearOwnedUnknownMutationLock(accountId, actionKey, idempotencyKey);
      clearIdempotencyKey(actionKey, accountId);
    }
    throw error;
  } finally {
    state.pendingActionKeys.delete(scopedActionKey);
    if (button) {
      button.setAttribute("aria-busy", "false");
    }
    if (mutationContextIsCurrent(accountId, accountLoadGeneration)) {
      applyTradingSafetyState();
    }
  }
}

function showTradeConfirmation({ title, summary, details }) {
  const dialog = els.tradeConfirmDialog;
  if (!dialog || typeof dialog.showModal !== "function") {
    return Promise.resolve(false);
  }
  els.tradeConfirmTitle.textContent = title || "Confirm broker action";
  els.tradeConfirmSummary.textContent = summary || "Confirm this paper-account broker action.";
  els.tradeConfirmDetails.innerHTML = Object.entries(details || {})
    .map(
      ([label, value]) => `
        <div>
          <dt>${escapeHtml(label)}</dt>
          <dd>${escapeHtml(value ?? "--")}</dd>
        </div>
      `
    )
    .join("");
  dialog.returnValue = "cancel";
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true });
    dialog.showModal();
  });
}

function idempotencySignatureAccount(requestSignature) {
  if (typeof requestSignature !== "string") return null;
  try {
    const payload = JSON.parse(requestSignature);
    return payload?.external_account_id || payload?.account || payload?.accountId || null;
  } catch (_error) {
    return null;
  }
}

function readIdempotencyRecord(storageKey) {
  const raw = window.sessionStorage.getItem(storageKey);
  if (!raw) return null;
  let record;
  try {
    record = JSON.parse(raw);
  } catch (error) {
    throw new Error(`Stored idempotency record is invalid; reconcile before retrying: ${error.message}`);
  }
  if (!record || typeof record !== "object" || typeof record.key !== "string" || typeof record.requestSignature !== "string") {
    throw new Error("Stored idempotency record is incomplete; reconcile before retrying.");
  }
  return record;
}

function persistUnknownMutationIntent({ accountId, mode, actionKey, requestSignature, idempotencyKey, intentId }) {
  if (!intentId || !idempotencyKey) return;
  const storageKey = `${IDEMPOTENCY_STORAGE_PREFIX}${accountId}:${actionKey}`;
  try {
    const existing = readIdempotencyRecord(storageKey) || {};
    window.sessionStorage.setItem(storageKey, JSON.stringify({
      ...existing,
      key: idempotencyKey,
      requestSignature,
      accountId,
      mode,
      actionKey,
      intentId,
    }));
  } catch (error) {
    console.error(error);
  }
}

function getOrCreateIdempotencyKey(actionKey, requestSignature, accountId = state.selectedAccountId, mode = "paper") {
  const storageKey = `${IDEMPOTENCY_STORAGE_PREFIX}${accountId}:${actionKey}`;
  let existing = null;
  try {
    existing = readIdempotencyRecord(storageKey);
    if (!existing) {
      const legacyKey = `${IDEMPOTENCY_STORAGE_PREFIX}${actionKey}`;
      const legacy = window.sessionStorage.getItem(legacyKey) ? readIdempotencyRecord(legacyKey) : null;
      if (legacy) {
        const legacyAccount = legacy.accountId || idempotencySignatureAccount(legacy.requestSignature);
        if (legacyAccount !== accountId || (legacy.mode && legacy.mode !== mode)) {
          throw new Error("An unscoped idempotency record belongs to an unknown account. Reconcile it before retrying.");
        }
        if (legacy.requestSignature !== requestSignature) {
          throw new Error("A previous request for this action is unresolved. Retry with the same inputs after reconciliation.");
        }
        existing = { ...legacy, accountId, mode, actionKey };
        window.sessionStorage.setItem(storageKey, JSON.stringify(existing));
        window.sessionStorage.removeItem(legacyKey);
      }
    }
  } catch (error) {
    throw new Error(`Session storage is unavailable; broker action blocked: ${error.message}`);
  }
  if (existing?.key) {
    const signatureAccount = idempotencySignatureAccount(existing.requestSignature);
    if ((existing.accountId && existing.accountId !== accountId) || (signatureAccount && signatureAccount !== accountId) || (existing.mode && existing.mode !== mode)) {
      throw new Error("A stored idempotency record belongs to a different account or mode. Reconcile it before retrying.");
    }
    if (existing.requestSignature !== requestSignature) {
      throw new Error("A previous request for this action is unresolved. Retry with the same inputs after reconciliation.");
    }
    if (existing.accountId !== accountId || existing.mode !== mode || existing.actionKey !== actionKey) {
      try {
        window.sessionStorage.setItem(storageKey, JSON.stringify({ ...existing, accountId, mode, actionKey }));
      } catch (error) {
        throw new Error(`Could not update the idempotency record; broker action blocked: ${error.message}`);
      }
    }
    return existing.key;
  }
  const randomId = window.crypto?.randomUUID?.();
  if (!randomId) {
    throw new Error("Secure idempotency key generation is unavailable; broker action blocked.");
  }
  const safeAction = String(actionKey).toLowerCase().replace(/[^a-z0-9._:-]/g, "-").slice(0, 32);
  const key = `ui:${safeAction}:${randomId}`;
  try {
    window.sessionStorage.setItem(storageKey, JSON.stringify({ key, requestSignature, accountId, mode, actionKey }));
  } catch (error) {
    throw new Error(`Could not persist the idempotency key; broker action blocked: ${error.message}`);
  }
  return key;
}

function clearIdempotencyKey(actionKey, accountId = state.selectedAccountId) {
  try {
    window.sessionStorage.removeItem(`${IDEMPOTENCY_STORAGE_PREFIX}${accountId}:${actionKey}`);
  } catch (error) {
    console.error(error);
  }
}

function isTerminalMutationError(error) {
  return Number.isFinite(error?.status) && error.status >= 400 && error.status < 500 && error.code !== "order_outcome_unknown";
}

function renderPanelLoadStates(errors) {
  const targets = {
    latestSnapshot: els.metricsStrip,
    orders: els.ordersBody,
    workingSpreads: els.spreadsBody,
    spreadHistory: els.bullPutHistoryStatus,
    runtime: els.strategyRuntimeStrip,
    operatorStatus: els.reconciliationStrip,
    zeroDteLotteryRuntime: els.zeroDteLotteryStrip,
    strategyExperiment: els.strategyExperimentStrip,
    coveredCallActivity: els.coveredCallActivityCard,
    advisorRuns: els.advisorOutputCard,
    marketEvents: els.marketEventsCard,
    executions: els.selectedOrderExecution,
    journals: els.selectedOrderJournal,
    preOpenRuns: els.preOpenRunReview,
  };
  Object.entries(targets).forEach(([key, target]) => markPanelLoadState(key, target, errors[key] || ""));
}

function markPanelLoadState(key, target, errorMessage) {
  if (!target) {
    return;
  }
  target.dataset.loadState = errorMessage ? "stale" : "fresh";
  const panel = target.closest(".strategy-note-card, .panel, .band");
  if (!panel) {
    return;
  }
  let marker = panel.querySelector(`[data-panel-load-key="${key}"]`);
  if (!errorMessage) {
    marker?.remove();
    return;
  }
  if (!marker) {
    marker = document.createElement("p");
    marker.className = "panel-load-status";
    marker.dataset.panelLoadKey = key;
    const header = panel.querySelector(":scope > .form-header, :scope > .panel-header, :scope > .band-header");
    if (header) {
      header.insertAdjacentElement("afterend", marker);
    } else {
      target.insertAdjacentElement("beforebegin", marker);
    }
  }
  marker.textContent = `${formatPanelLoadLabel(key)} is stale; prior data is preserved. ${errorMessage}`;
}

function formatPanelLoadLabel(key) {
  const labels = {
    latestSnapshot: "Account snapshot",
    orders: "Orders",
    workingSpreads: "Bull Put working spreads",
    spreadHistory: "Bull Put history",
    runtime: "Bull Put runtime",
    operatorStatus: "Operator status",
    recoveryStatus: "Recovery status",
    tradingIntents: "Trading intents",
    tradeActions: "Trade actions",
    zeroDteLotteryRuntime: "Zero-DTE runtime",
    strategyExperiment: "Strategy experiment",
    coveredCallActivity: "Covered Call activity",
    advisorRuns: "Advisor runs",
    marketEvents: "Market events",
    executions: "Executions",
    journals: "Journals",
    preOpenRuns: "Stored macro review",
  };
  return labels[key] || key;
}

async function loadDashboard() {
  setStatus("Loading dashboard...", "warning");
  try {
    await refreshAccounts();
    window.StocksToolWorkspace?.updateAccountContext(state.selectedAccountId || "--");
    void refreshResearchContext();
    const loadResult = await loadAccountData();
    if (loadResult.discarded) {
      return;
    }
    prepareMarketOverlayPanels();
    if (!loadResult.coreHealthy) {
      setStatus(
        `Core account data is stale: ${loadResult.requiredFailures.join(", ")}. Broker-writing actions are disabled.`,
        "error"
      );
    } else if ((state.unresolvedTradingIntents || []).length > 0) {
      setStatus(
        `Trading blocked: ${state.unresolvedTradingIntents.length} unresolved trading intent(s) require reconciliation.`,
        "error"
      );
    } else if (loadResult.optionalFailures.length) {
      setStatus(
        `Core account data updated. Auxiliary panels unavailable: ${loadResult.optionalFailures.join(", ")}.`,
        "warning"
      );
    } else {
      setStatus("Dashboard updated. Option strategy panels loaded first. Macro overlays are available on demand.", "success");
    }
    window.StocksToolWorkspace?.updateDataTime(state.latestSnapshot?.captured_at || new Date());
  } catch (error) {
    console.error(error);
    setStatus(error.message || "Failed to load dashboard.", "error");
  }
}

async function refreshResearchContext() {
  if (typeof window.StocksToolResearch?.refresh !== "function") {
    return false;
  }
  try {
    const refreshed = await window.StocksToolResearch.refresh({
      externalAccountId: state.selectedAccountId || "",
      watchlistId: window.StocksToolWatchlists?.getSelectedId?.() || "",
    });
    const generatedAt = window.StocksToolResearch.getState?.().generatedAt;
    if (refreshed && generatedAt) {
      window.StocksToolWorkspace?.updateDataTime(generatedAt);
    }
    return refreshed;
  } catch (error) {
    console.error(error);
    return false;
  }
}

function prepareMarketOverlayPanels() {
  if (!state.preOpenAssessment) {
    state.preOpenStatus = buildOverlayStatus(
      "idle",
      "Macro board is available on demand so option strategy requests stay first."
    );
    renderPreOpenAssessment();
  }
}

async function loadPreOpenAssessment(options = {}) {
  const { includeOptionOverlays = false, timeoutMs = PRE_OPEN_BOARD_TIMEOUT_MS } = options;
  if (!state.selectedAccountId) {
    state.preOpenStatus = buildOverlayStatus("idle", "Select a broker account before loading the macro board.");
    renderPreOpenAssessment();
    return;
  }
  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;
  state.preOpenStatus = buildOverlayStatus(
    "loading",
    includeOptionOverlays
      ? "Refreshing live macro board with option overlays..."
      : "Refreshing live macro board..."
  );
  renderPreOpenAssessment();

  try {
    const params = new URLSearchParams();
    params.set("external_account_id", accountId);
    params.set("include_option_overlays", includeOptionOverlays ? "true" : "false");
    const assessment = await fetchJson(
      `/strategies/pre-open-risk?${params.toString()}`,
      { timeoutMs }
    );
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true };
    applyPreOpenAssessmentResponse(assessment);
    return { discarded: false };
  } catch (error) {
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true, error };
    console.error(error);
    state.preOpenStatus = classifyOverlayFailure(error, {
      label: "live macro board",
      stale: Boolean(state.preOpenAssessment),
      staleAt: state.preOpenAssessment?.analyzed_at,
    });
    renderPreOpenAssessment();
    return { discarded: false, error };
  }
}

async function saveCurrentPreOpenBoard() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before saving the macro board.", "warning");
    return;
  }
  if (!state.preOpenAssessment || state.preOpenStatus.kind === "idle" || state.preOpenStatus.kind === "loading") {
    setStatus("Load the live macro board before saving it.", "warning");
    return;
  }
  if (state.preOpenStatus.kind !== "live" && state.preOpenStatus.kind !== "partial") {
    setStatus("Only a live or partial live macro board can be saved.", "warning");
    return;
  }

  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;

  setStatus(`Saving live macro board for ${accountId}...`, "warning");
  updatePreOpenButtons(true);
  try {
    const result = await fetchJson(
      `/strategies/pre-open-runs/${encodeURIComponent(accountId)}/capture?force=true&include_option_overlays=false`,
      {
        method: "POST",
        timeoutMs: PRE_OPEN_BOARD_TIMEOUT_MS,
      }
    );
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true };
    if (result.run) {
      state.preOpenRuns = [
        result.run,
        ...state.preOpenRuns.filter((run) => run.id !== result.run.id),
      ];
      state.preOpenAssessment = result.run.assessment || state.preOpenAssessment;
      applyPreOpenAssessmentResponse(state.preOpenAssessment);
      renderLatestPreOpenRun();
    }
    setStatus(`Stored macro board for ${formatSessionDate(result.run?.target_session_date)}.`, "success");
    return { discarded: false };
  } catch (error) {
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true, error };
    console.error(error);
    setStatus(error.message || "Saving macro board failed.", "error");
    return { discarded: false, error };
  } finally {
    if (mutationContextIsCurrent(accountId, accountLoadGeneration)) updatePreOpenButtons(false);
  }
}

function seedPreOpenAssessmentFromLatestRun({ clearWhenMissing = false } = {}) {
  const run = Array.isArray(state.preOpenRuns) && state.preOpenRuns.length ? state.preOpenRuns[0] : null;
  if (!run?.assessment) {
    if (clearWhenMissing) {
      state.preOpenAssessment = null;
      if (state.preOpenStatus.kind !== "loading") {
        state.preOpenStatus = buildOverlayStatus(
          "idle",
          "No stored macro board is available yet. Load it on demand when strategy work is done."
        );
      }
    }
    return false;
  }

  state.preOpenAssessment = run.assessment;
  if (state.preOpenStatus.kind !== "loading") {
    state.preOpenStatus = buildOverlayStatus(
      "stale",
      run.assessment.freshness_detail || `Showing the latest stored macro board captured ${formatDateTime(run.assessment.analyzed_at)}.`,
      run.assessment.stale_reason || `Latest stored run for ${formatSessionDate(run.target_session_date)}.`
    );
  }
  return true;
}

function applyPreOpenAssessmentResponse(assessment) {
  state.preOpenAssessment = assessment;
  if (assessment?.freshness_status === "stale") {
    state.preOpenStatus = buildOverlayStatus(
      "stale",
      assessment.freshness_detail || buildStaleOverlayDetail("live macro board", "circuit_open", assessment.analyzed_at),
      assessment.stale_reason || ""
    );
  } else if (assessment?.freshness_status === "partial") {
    state.preOpenStatus = buildOverlayStatus(
      "partial",
      assessment.freshness_detail || "Live board loaded with partial proxy coverage.",
      assessment.stale_reason || ""
    );
  } else if (assessment?.freshness_status === "error") {
    state.preOpenStatus = buildOverlayStatus(
      "error",
      assessment.freshness_detail || "Live broker data is unavailable for the live macro board.",
      assessment.stale_reason || ""
    );
  } else {
    state.preOpenStatus = buildOverlayStatus(
      "live",
      assessment?.freshness_detail || overlayLiveDetail("Live macro board", assessment.analyzed_at)
    );
  }
  renderPreOpenAssessment();
  updatePreOpenButtons();
}

async function syncAccount() {
  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;
  setStatus(`Syncing account ${accountId}...`, "warning");
  try {
    await fetchJson(`/brokers/longbridge/account-sync/${encodeURIComponent(accountId)}?mode=paper`, {
      method: "POST",
    });
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true };
    await refreshAccounts();
    await loadAccountData();
    if (state.selectedAccountId !== accountId) return { discarded: true };
    setStatus(`Account ${accountId} synced.`, "success");
    return { discarded: false };
  } catch (error) {
    if (state.selectedAccountId !== accountId) return { discarded: true, error };
    console.error(error);
    await refreshAccountsSilently();
    setStatus(error.message || "Account sync failed.", "error");
    return { discarded: false, error };
  }
}

async function syncOrders() {
  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;
  setStatus(`Syncing orders for ${accountId}...`, "warning");
  try {
    await fetchJson(`/orders/sync/longbridge/${encodeURIComponent(accountId)}?mode=paper`, {
      method: "POST",
    });
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true };
    await refreshAccounts();
    await loadAccountData();
    if (state.selectedAccountId !== accountId) return { discarded: true };
    setStatus(`Orders for ${accountId} synced.`, "success");
    return { discarded: false };
  } catch (error) {
    if (state.selectedAccountId !== accountId) return { discarded: true, error };
    console.error(error);
    await refreshAccountsSilently();
    setStatus(error.message || "Order sync failed.", "error");
    return { discarded: false, error };
  }
}

async function saveStrategyControls(button = els.saveStrategyControls) {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before updating strategy controls.", "warning");
    return;
  }
  const accountId = state.selectedAccountId;

  const payload = {
    auto_entry_enabled: els.strategyAutoEntry.value === "true",
    manual_pause: els.strategyManualPause.value === "true",
    kill_switch_active: els.strategyKillSwitch.value === "true",
    paused_symbols: parseSymbolList(els.strategyPausedSymbols.value),
  };

  try {
    const mutation = await runConfirmedBrokerMutation(
      {
        actionKey: "bull-put-controls",
        button,
        requestSignature: JSON.stringify(payload),
        getRequestSignature: () => JSON.stringify(payload),
        statusElement: els.strategyControlsHint,
        confirmation: {
          title: "Confirm Bull Put controls",
          summary: payload.auto_entry_enabled ? "Enable paper Bull Put entry automation" : "Update Bull Put entry controls",
          details: {
            Account: accountId,
            Mode: "Paper",
            Symbol: payload.paused_symbols.length ? payload.paused_symbols.join(", ") : "Configured universe",
            "Side / Legs": "Protective put first / short put second",
            Quantity: "1 spread maximum per entry",
            Price: "Server-validated candidate limits",
            "Max Risk": "Server risk cap",
            "Quote Time": "Fresh quote required at execution",
          },
        },
      },
      async (idempotencyKey) => {
        setStatus(`Saving bull put controls for ${accountId}...`, "warning");
        return fetchJson(`/strategies/bull-put/runtime/${encodeURIComponent(accountId)}?mode=paper`, {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey },
          body: JSON.stringify(payload),
        });
      }
    );
    if (!mutation.executed) {
      return;
    }
    await loadAccountData();
    if (state.selectedAccountId !== accountId) return { discarded: true };
    setActionStatus(els.strategyControlsHint, `Bull put controls updated for ${accountId}.`, "success");
    setStatus(`Bull put controls updated for ${accountId}.`, "success");
  } catch (error) {
    if (state.selectedAccountId !== accountId) return { discarded: true, error };
    console.error(error);
    setActionStatus(els.strategyControlsHint, error.message || "Bull put controls update failed.", "error");
    setStatus(error.message || "Bull put controls update failed.", "error");
  }
}

async function runStrategyScan(button = els.runStrategyScan) {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before running a bull put scan.", "warning");
    return;
  }

  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;
  try {
    setActionStatus(els.strategyControlsHint, "Loading a fresh Bull Put candidate for confirmation...", "warning");
    const readiness = await fetchJson(
      `/strategies/bull-put/readiness?external_account_id=${encodeURIComponent(accountId)}&mode=paper`,
      { timeoutMs: BROKER_REQUEST_TIMEOUT_MS }
    );
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) {
      setActionStatus(els.strategyControlsHint, "Account changed while loading the Bull Put candidate; reload before trading.", "warning");
      return;
    }
    const previews = Array.isArray(readiness?.previews) ? readiness.previews : [];
    const preview = previews.find(
      (candidatePreview) =>
        candidatePreview?.eligible &&
        candidatePreview?.candidate &&
        (!readiness.preferred_symbol || candidatePreview.symbol === readiness.preferred_symbol)
    );
    if (!readiness?.ready || !preview?.candidate || !preview?.risk) {
      const message = readiness?.next_action || "No eligible Bull Put candidate is available for confirmation.";
      setActionStatus(els.strategyControlsHint, message, "warning");
      setStatus(message, "warning");
      return;
    }
    const candidate = preview.candidate;
    const risk = preview.risk;
    const quoteTime =
      candidate.short_put?.quote_timestamp ||
      candidate.long_put?.quote_timestamp ||
      preview.scanned_at;
    const actionKey = `bull-put-execute:${accountId}`;
    if (button) {
      button.dataset.actionKey = actionKey;
    }
    const mutation = await runConfirmedBrokerMutation(
      {
        actionKey,
        button,
        requestSignature: JSON.stringify({
          account: accountId,
          mode: "paper",
          force: true,
          symbol: preview.symbol,
          candidateToken: preview.candidate_token,
          minimumNetCredit: candidate.conservative_credit,
        }),
        getRequestSignature: () => JSON.stringify({
          account: state.selectedAccountId,
          mode: "paper",
          force: true,
          symbol: preview.symbol,
          candidateToken: preview.candidate_token,
          minimumNetCredit: candidate.conservative_credit,
        }),
        statusElement: els.strategyControlsHint,
        confirmation: {
          title: "Confirm Bull Put paper order",
          summary: "Open the exact previewed two-leg Bull Put spread in the paper account",
          details: {
            Account: accountId,
            Mode: "Paper",
            Symbol: preview.symbol,
            "Side / Legs": `Buy ${candidate.long_put?.symbol || "protective put"}, then sell ${candidate.short_put?.symbol || "short put"}`,
            Quantity: "1 spread",
            Price: `Minimum net credit ${formatCurrency(candidate.conservative_credit, "USD")}`,
            "Max Risk": formatCurrency(risk.max_loss, "USD"),
            "Quote Time": formatDateTime(quoteTime),
          },
        },
      },
      async (idempotencyKey) => {
        if (state.selectedAccountId !== accountId) {
          throw new Error("Account changed after confirmation; the Bull Put order was not sent.");
        }
        setStatus(`Opening the previewed bull put spread for ${accountId}...`, "warning");
        return fetchJson(`/strategies/bull-put/execute`, {
          method: "POST",
          headers: {
            "Idempotency-Key": idempotencyKey,
            "X-Confirm-Paper-Order": "true",
          },
          body: JSON.stringify({
            external_account_id: accountId,
            symbol: preview.symbol,
            mode: "paper",
            candidate_token: preview.candidate_token,
            minimum_net_credit: candidate.conservative_credit,
            confirm_paper_order: true,
            remark: "dashboard-bull-put",
          }),
          timeoutMs: BROKER_REQUEST_TIMEOUT_MS,
        });
      }
    );
    if (!mutation.executed) {
      return;
    }
    const result = mutation.result;
    await loadAccountData();
    if (state.selectedAccountId !== accountId) return { discarded: true };
    const message = `Bull put paper order opened ${result?.underlying_symbol || preview.symbol}.`;
    const tone = "success";
    setActionStatus(els.strategyControlsHint, message, tone);
    setStatus(message, tone);
  } catch (error) {
    if (state.selectedAccountId !== accountId) return { discarded: true, error };
    console.error(error);
    setActionStatus(els.strategyControlsHint, error.message || "Bull put scan failed.", "error");
    setStatus(error.message || "Bull put scan failed.", "error");
  }
}

async function runStrategyReview() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before running a bull put review.", "warning");
    return;
  }

  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;
  setStatus(`Running bull put review for ${accountId}...`, "warning");
  try {
    const result = await fetchJson(
      `/strategies/bull-put/runtime/${encodeURIComponent(accountId)}/review?mode=paper&force=true`,
      {
        method: "POST",
      }
    );
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true };
    await loadAccountData();
    if (state.selectedAccountId !== accountId) return { discarded: true };
    const message = result.recommendation || result.reason || result.strategy_state?.last_review_summary || "Bull put review completed.";
    setStatus(message, result.review_status === "suggested" ? "success" : "warning");
  } catch (error) {
    if (state.selectedAccountId !== accountId) return { discarded: true, error };
    console.error(error);
    setStatus(error.message || "Bull put review failed.", "error");
  }
}

async function previewZeroDteLottery() {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account before previewing zero-DTE lottery.", "warning");
    return;
  }

  let symbol = "";
  try {
    symbol = normalizeLotterySymbol();
  } catch (error) {
    setStatus(error.message || "Zero-DTE lottery symbol is required.", "error");
    return;
  }
  const direction = els.zeroDteLotteryDirection.value || "auto";
  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;
  setStatus(`Previewing zero-DTE lottery for ${symbol}...`, "warning");
  try {
    const params = new URLSearchParams();
    params.set("external_account_id", accountId);
    params.set("symbol", symbol);
    params.set("direction", direction);
    params.set("mode", "paper");
    const preview = await fetchJson(`/strategies/zero-dte-lottery/preview?${params.toString()}`);
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true };
    state.zeroDteLotteryPreview = preview;
    state.zeroDteLotteryScanResult = null;
    strategyView?.renderZeroDteLottery();
    const message = state.zeroDteLotteryPreview.eligible
      ? `Zero-DTE lottery candidate ready: ${state.zeroDteLotteryPreview.candidate?.option_symbol || symbol}.`
      : state.zeroDteLotteryPreview.reasons?.[0] || "Zero-DTE lottery preview completed without a candidate.";
    setStatus(message, state.zeroDteLotteryPreview.eligible ? "success" : "warning");
  } catch (error) {
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true, error };
    console.error(error);
    setStatus(error.message || "Zero-DTE lottery preview failed.", "error");
  }
}
async function reconcileCoveredCallLifecycle(button = null) {
  if (!state.selectedAccountId) {
    setStatus("Select a broker account first.", "warning");
    return;
  }

  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;
  try {
    if (button) {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
    }
    setStatus(`Refreshing covered-call lifecycle for ${accountId} (read-only)...`, "warning");
    const result = await fetchJson(
      `/strategies/covered-call/lifecycle/${encodeURIComponent(accountId)}/reconcile?limit=20`,
      {
        method: "POST",
        timeoutMs: COVERED_CALL_LIFECYCLE_TIMEOUT_MS,
      }
    );
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true };
    await loadAccountData();
    if (state.selectedAccountId !== accountId) return { discarded: true };
    setStatus(`Covered-call lifecycle refreshed read-only: ${formatCoveredCallLifecycleResult(result)}.`, "success");
    return { discarded: false };
  } catch (error) {
    if (state.selectedAccountId !== accountId) return { discarded: true, error };
    console.error(error);
    setStatus(error.message || "Covered-call lifecycle refresh failed.", "error");
  } finally {
    if (button && state.selectedAccountId === accountId) {
      button.removeAttribute("aria-busy");
      button.disabled = false;
    }
    if (state.selectedAccountId === accountId) applyTradingSafetyState();
  }
}

async function handleStrategyProposalAction(action, proposalId, button = null) {
  const actionLabels = {
    approve: "Approving strategy proposal",
    reject: "Rejecting strategy proposal",
    execute_covered_call: "Executing covered call proposal",
    monitor_covered_call: "Monitoring covered call proposal",
    close_covered_call: "Closing covered call proposal",
    roll_propose: "Creating covered call roll proposal",
    roll_execute: "Executing covered call roll proposal",
    roll_continue: "Continuing covered call roll proposal",
  };
  const accountId = state.selectedAccountId;
  const accountLoadGeneration = state.accountLoadGeneration;
  try {
    const requestPayload = buildStrategyProposalActionPayload(action);
    if (requestPayload.canceled) {
      setStatus("Strategy proposal action canceled.", "warning");
      return;
    }
    let result = null;
    if (isCoveredCallBrokerMutation(action)) {
      const actionKey = `covered-call:${proposalId}:${action}`;
      const proposal = findStrategyProposal(proposalId);
      const mutation = await runConfirmedBrokerMutation(
        {
          actionKey,
          button,
          requestSignature: JSON.stringify({ proposal_id: proposalId, action, ...requestPayload.body }),
          getRequestSignature: () => JSON.stringify({ proposal_id: proposalId, action, ...requestPayload.body }),
          statusElement: els.coveredCallActionStatus,
          confirmation: buildCoveredCallConfirmation(action, proposal, requestPayload.body),
        },
        async (idempotencyKey) => {
          setStatus(`${actionLabels[action] || "Updating strategy proposal"} ${proposalId}...`, "warning");
          return sendStrategyProposalActionRequest(action, proposalId, requestPayload.body, idempotencyKey);
        }
      );
      if (!mutation.executed) {
        return;
      }
      result = mutation.result;
    } else {
      setStatus(`${actionLabels[action] || "Updating strategy proposal"} ${proposalId}...`, "warning");
      result = await sendStrategyProposalActionRequest(action, proposalId, requestPayload.body, null);
    }
    if (!mutationContextIsCurrent(accountId, accountLoadGeneration)) return { discarded: true };
    await loadAccountData();
    if (state.selectedAccountId !== accountId) return { discarded: true };
    const message = formatStrategyProposalActionResult(action, result);
    if (isCoveredCallBrokerMutation(action)) {
      setActionStatus(els.coveredCallActionStatus, message, "success");
    }
    setStatus(message, "success");
  } catch (error) {
    if (state.selectedAccountId !== accountId) return { discarded: true, error };
    console.error(error);
    if (isCoveredCallBrokerMutation(action)) {
      setActionStatus(els.coveredCallActionStatus, error.message || "Covered Call action failed.", "error");
    }
    setStatus(error.message || "Strategy proposal action failed.", "error");
  }
}

function sendStrategyProposalActionRequest(action, proposalId, body, idempotencyKey) {
  const headers = idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {};
  const options = { method: "POST", headers };
  if (action === "approve" || action === "reject") {
    return fetchJson(`/strategies/proposals/${encodeURIComponent(proposalId)}/${action}`, options);
  }
  const suffixes = {
    execute_covered_call: "execute",
    monitor_covered_call: "monitor",
    close_covered_call: "close",
    roll_propose: "roll-propose",
    roll_execute: "roll-execute",
    roll_continue: "roll-continue",
  };
  const suffix = suffixes[action];
  if (!suffix) {
    throw new Error(`Unsupported proposal action: ${action}`);
  }
  if (action !== "monitor_covered_call") {
    options.body = JSON.stringify(body || {});
  }
  if (idempotencyKey) {
    options.timeoutMs = BROKER_REQUEST_TIMEOUT_MS;
  }
  return fetchJson(`/strategies/covered-call/proposals/${encodeURIComponent(proposalId)}/${suffix}`, options);
}

function findStrategyProposal(proposalId) {
  const proposals = [
    ...(state.strategyExperiment?.proposals || []),
    ...(state.coveredCallActivity?.proposals || []),
  ];
  return proposals.find((proposal) => proposal.id === proposalId) || { id: proposalId };
}

function buildCoveredCallConfirmation(action, proposal, body) {
  const candidate = objectPayload(proposal?.candidate_payload);
  const risk = objectPayload(proposal?.risk_payload);
  const rollFrom = objectPayload(candidate.roll_from);
  const rollTo = objectPayload(candidate.roll_to);
  const activeCandidate = rollTo.call_symbol ? rollTo : candidate;
  const contracts = candidate.contracts || rollTo.contracts || 1;
  const actionLabels = {
    execute_covered_call: "Sell covered call",
    monitor_covered_call: "Monitor covered call; exit rules may submit an order",
    close_covered_call: "Buy covered call to close",
    roll_execute: "Buy old call and sell rolled call",
    roll_continue: "Continue rolled-call execution",
  };
  const price = body.limit_price || body.buyback_limit_price || body.sell_limit_price || activeCandidate.call_bid;
  const legDescriptions = {
    execute_covered_call: `SELL ${candidate.call_symbol || "approved call"}`,
    monitor_covered_call: `Monitor ${candidate.call_symbol || "approved short call"}`,
    close_covered_call: `BUY ${candidate.call_symbol || "short call"} TO CLOSE`,
    roll_execute: `BUY ${rollFrom.call_symbol || "old short call"}, then SELL ${rollTo.call_symbol || "new call"}`,
    roll_continue: body.sell_order_id
      ? `Refresh sell order ${body.sell_order_id} for ${rollTo.call_symbol || "new call"}`
      : `After buyback ${body.buyback_order_id || "confirmation"}, SELL ${rollTo.call_symbol || "new call"}`,
  };
  return {
    title: "Confirm Covered Call broker action",
    summary: actionLabels[action] || "Covered Call action",
    details: {
      Account: proposal?.external_account_id || state.selectedAccountId,
      Mode: "Paper",
      Symbol: proposal?.symbol || candidate.underlying_symbol || "--",
      "Side / Legs": legDescriptions[action] || actionLabels[action] || action,
      Quantity: `${contracts} contract`,
      Price: price ? formatCurrency(price, "USD") : "Fresh broker/strategy price",
      "Max Risk": formatCurrency(risk.max_loss_if_zero || proposal?.expected_max_loss, "USD"),
      "Quote Time": formatDateTime(activeCandidate.quote_timestamp || activeCandidate.evaluated_at || proposal?.updated_at),
    },
  };
}

function buildStrategyProposalActionPayload(action) {
  if (action === "execute_covered_call") {
    return buildOptionalLimitPayload({
      field: "limit_price",
      promptText: "Optional sell-call limit price. Leave blank to use the current bid:",
      label: "Covered call sell limit price",
    });
  }
  if (action === "close_covered_call") {
    return buildRequiredLimitPayload({
      field: "limit_price",
      promptText: "Required buy-to-close limit price shown in the confirmation:",
      label: "Covered call close limit price",
    });
  }
  if (action === "roll_execute") {
    const buyback = promptRequiredPositiveNumber(
      "Required buyback limit price for the old short call:",
      "Covered call roll buyback limit price"
    );
    if (buyback.canceled) {
      return { canceled: true, body: {} };
    }
    const sell = promptRequiredPositiveNumber(
      "Required sell limit price for the new short call:",
      "Covered call roll sell limit price"
    );
    if (sell.canceled) {
      return { canceled: true, body: {} };
    }
    const body = {};
    addOptionalNumberField(body, "buyback_limit_price", buyback.value);
    addOptionalNumberField(body, "sell_limit_price", sell.value);
    return { canceled: false, body };
  }
  if (action === "roll_continue") {
    const buybackOrderId = window.prompt("Buyback order id to refresh before opening the rolled call:");
    if (buybackOrderId === null || !buybackOrderId.trim()) {
      return { canceled: true, body: {} };
    }
    const sellOrderId = window.prompt("Optional existing roll sell order id to refresh. Leave blank to submit a new sell order if buyback is filled:");
    if (sellOrderId === null) {
      return { canceled: true, body: {} };
    }
    const sell = promptRequiredPositiveNumber(
      "Required sell limit price for the new short call if continuation submits it:",
      "Covered call roll continuation sell limit price"
    );
    if (sell.canceled) {
      return { canceled: true, body: {} };
    }
    const body = { buyback_order_id: buybackOrderId.trim() };
    if (sellOrderId.trim()) {
      body.sell_order_id = sellOrderId.trim();
    }
    addOptionalNumberField(body, "sell_limit_price", sell.value);
    return { canceled: false, body };
  }
  return { canceled: false, body: {} };
}

function buildOptionalLimitPayload({ field, promptText, label }) {
  const limit = promptOptionalPositiveNumber(promptText, label);
  if (limit.canceled) {
    return { canceled: true, body: {} };
  }
  const body = {};
  addOptionalNumberField(body, field, limit.value);
  return { canceled: false, body };
}

function buildRequiredLimitPayload({ field, promptText, label }) {
  const limit = promptRequiredPositiveNumber(promptText, label);
  if (limit.canceled) {
    return { canceled: true, body: {} };
  }
  return { canceled: false, body: { [field]: limit.value } };
}

function promptOptionalPositiveNumber(promptText, label) {
  const value = window.prompt(promptText);
  if (value === null) {
    return { canceled: true, value: null };
  }
  return {
    canceled: false,
    value: parsePositiveNumber(value, label, false),
  };
}

function promptRequiredPositiveNumber(promptText, label) {
  const value = window.prompt(promptText);
  if (value === null) {
    return { canceled: true, value: null };
  }
  return {
    canceled: false,
    value: parsePositiveNumber(value, label, true),
  };
}

function addOptionalNumberField(payload, field, value) {
  if (value !== null && value !== undefined) {
    payload[field] = value;
  }
  return payload;
}

async function loadAccountData(...args) {
  return accountLoader.loadAccountData(...args);
}

async function refreshAccounts(...args) {
  return accountLoader.refreshAccounts(...args);
}

async function refreshAccountsSilently(...args) {
  return accountLoader.refreshAccountsSilently(...args);
}

function applyAccounts(...args) {
  return accountLoader.applyAccounts(...args);
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

  const operatorStatus = objectPayload(state.operatorStatus);
  const brokerProfiles = Array.isArray(operatorStatus.broker_profiles) ? operatorStatus.broker_profiles : [];
  const brokerProfile = brokerProfiles[0] || null;
  const mandate = objectPayload(operatorStatus.paper_mandate);
  const consistencySummary = objectPayload(operatorStatus.consistency_summary);
  const schedulerCheck = getOperatorCheck(operatorStatus, "scheduler_recent_runs");
  const consistencyCheck = getOperatorCheck(operatorStatus, "ledger_consistency");
  const manualActionCount = Array.isArray(operatorStatus.lifecycle_warnings)
    ? operatorStatus.lifecycle_warnings.length
    : 0;
  const mandateStrategyCount = Array.isArray(mandate.enabled_strategies)
    ? mandate.enabled_strategies.length
    : null;
  const latestAdvisorRun = Array.isArray(state.advisorRuns) ? state.advisorRuns[0] : null;
  const cards = [
    {
      label: "Broker Profile",
      priority: "secondary",
      tone: brokerProfile?.configured === false ? "warning" : "success",
      badge: brokerProfile?.paper_guard || "Profile",
      value: brokerProfile
        ? `${formatBrokerName(brokerProfile.broker || brokerProfile.name)} / ${formatStrategyStatusLabel(brokerProfile.mode || "paper")}`
        : "Longbridge / Paper",
      detail: brokerProfile
        ? `${brokerProfile.external_account_id || account.external_account_id} / ${formatStrategyStatusLabel(brokerProfile.credential_status || "unknown")}`
        : "Using the local Longbridge paper account profile.",
    },
    {
      label: "Scheduler Posture",
      priority: "secondary",
      tone: postureTone(schedulerCheck?.status || operatorStatus.status || "neutral"),
      badge: postureLabel(schedulerCheck?.status || operatorStatus.status || "observed"),
      value: operatorStatus.ready_for_unattended === false ? "Review" : "Ready",
      detail: formatOperatorCheckDetail(
        schedulerCheck,
        account.auto_reconcile_enabled
          ? "Background polling is active for this paper account."
          : "Automatic polling is disabled for this account."
      ),
    },
    {
      label: "Account Sync",
      priority: "primary",
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
      priority: "secondary",
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
    {
      label: "Paper Mandate",
      priority: "primary",
      tone: mandate.kill_switch ? "error" : mandate.manual_pause ? "warning" : "success",
      badge: mandate.kill_switch ? "Kill Switch" : mandate.manual_pause ? "Paused" : "Paper",
      value: mandateStrategyCount !== null
        ? `${mandateStrategyCount} ${mandateStrategyCount === 1 ? "Strategy" : "Strategies"}`
        : "--",
      detail: formatMandateDetail(mandate, operatorStatus.operator_posture_reason),
    },
    {
      label: "Ledger Consistency",
      priority: "primary",
      tone: postureTone(consistencySummary.status || consistencyCheck?.status || "neutral"),
      badge: postureLabel(consistencySummary.status || consistencyCheck?.status || "observed"),
      value: consistencySummary.repair_available_count
        ? `${consistencySummary.repair_available_count} Repair${consistencySummary.repair_available_count === 1 ? "" : "s"}`
        : `${displayValue(consistencySummary.check_count)} Check${Number(consistencySummary.check_count) === 1 ? "" : "s"}`,
      detail: formatConsistencyDetail(consistencySummary, consistencyCheck),
    },
    {
      label: "Manual Actions",
      priority: "primary",
      tone: manualActionCount ? "error" : "success",
      badge: manualActionCount ? "Required" : "Clear",
      value: `${manualActionCount} Warning${manualActionCount === 1 ? "" : "s"}`,
      detail: formatOperatorCheckDetail(
        getOperatorCheck(operatorStatus, "lifecycle_warnings"),
        operatorStatus.operator_posture_reason || "No strategy lifecycle manual action is currently blocking automation."
      ),
    },
    {
      label: "Advisor Last Run",
      priority: "secondary",
      tone: latestAdvisorRun ? advisorRunStatusClass(latestAdvisorRun.status) : "neutral",
      badge: latestAdvisorRun?.recorded ? "Recorded" : latestAdvisorRun ? "Observed" : "--",
      value: latestAdvisorRun ? (latestAdvisorRun.model || latestAdvisorRun.provider || "DeepSeek") : "--",
      detail: formatAdvisorRunCardDetail(latestAdvisorRun),
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

function getOperatorCheck(operatorStatus, name) {
  const checks = Array.isArray(operatorStatus?.checks) ? operatorStatus.checks : [];
  return checks.find((check) => check.name === name) || null;
}

function formatOperatorCheckDetail(check, fallback) {
  const detail = check?.detail || fallback || "";
  const reason = check?.reason_code
    ? `reason ${check.reason_code}${check.reason_detail ? `: ${check.reason_detail}` : ""}`
    : "";
  return [detail, reason].filter(Boolean).join(" / ");
}

function postureTone(status) {
  if (status === "pass" || status === "success") {
    return "success";
  }
  if (status === "fail" || status === "error") {
    return "error";
  }
  if (status === "warn" || status === "warning") {
    return "warning";
  }
  return "neutral";
}

function postureLabel(status) {
  if (status === "pass") {
    return "Pass";
  }
  if (status === "warn") {
    return "Warn";
  }
  if (status === "fail") {
    return "Fail";
  }
  return formatStrategyStatusLabel(status || "--");
}

function formatBrokerName(value) {
  return String(value || "--")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatMandateDetail(mandate, fallback) {
  const reasons = Array.isArray(mandate.reason_codes) ? mandate.reason_codes.filter(Boolean) : [];
  const symbols = Array.isArray(mandate.symbol_universe) ? mandate.symbol_universe.slice(0, 3).join(", ") : "";
  const caps = objectPayload(mandate.daily_caps);
  const bullPutCap = caps.bull_put_new_spreads;
  if (reasons.length) {
    return `${reasons.join(", ")} / ${fallback || "Paper mandate is paused or constrained."}`;
  }
  if (symbols && bullPutCap !== undefined) {
    return `${symbols} / bull put daily cap ${bullPutCap}`;
  }
  return fallback || "Paper mandate is derived from local strategy controls.";
}

function formatConsistencyDetail(summary, check) {
  const detail = formatOperatorCheckDetail(check, "");
  const status = summary?.status ? `status ${summary.status}` : "";
  const counts = [
    summary?.fail_count ? `${summary.fail_count} fail` : "",
    summary?.warn_count ? `${summary.warn_count} warn` : "",
    summary?.repair_available_count ? `${summary.repair_available_count} repair available` : "",
  ].filter(Boolean).join(", ");
  const latest = summary?.generated_at ? `evidence ${formatDateTime(summary.generated_at)}` : "";
  return [detail, counts, status, latest].filter(Boolean).join(" / ") || "Consistency report is not loaded yet.";
}

function formatAdvisorRunCardDetail(run) {
  if (!run) {
    return "No DeepSeek advisor run-card is available yet.";
  }
  const usage = objectPayload(run.token_usage);
  const totalTokens = usage.total_tokens ?? run.total_tokens;
  const hash = run.context_hash ? `hash ${String(run.context_hash).slice(0, 12)}` : "";
  const status = run.recordable_status ? `record ${formatStrategyStatusLabel(run.recordable_status)}` : "";
  const playbook = run.playbook_id ? `playbook ${run.playbook_id}` : "";
  const output = `${displayValue(run.proposal_count)} proposal(s), ${displayValue(run.review_count)} review(s)`;
  return [hash, totalTokens !== undefined ? `${displayValue(totalTokens)} tokens` : "", status, playbook, output]
    .filter(Boolean)
    .join(" / ");
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

  if (!els.holdingsFocus) {
    return;
  }

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
  if (!els.brokerStatus) {
    return;
  }
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
  if (!els.watchlistsBody) {
    return;
  }
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

function advisorRunStatusClass(status) {
  if (status === "recorded" || status === "succeeded") return "success";
  if (status === "failed") return "error";
  return "neutral";
}

function renderStrategyProposalDetails(proposal, proposals = []) {
  if (proposal.strategy_id !== "covered_call_v1") {
    return "";
  }
  const candidate = objectPayload(proposal.candidate_payload);
  const risk = objectPayload(proposal.risk_payload);
  let items = [];
  if (proposal.proposed_action === "sell_covered_call") {
    items = [
      [
        "Call",
        displayValue(candidate.call_symbol),
        `${formatProposalDate(candidate.expiration_date)} / K ${formatProposalNumber(candidate.call_strike)}`,
      ],
      [
        "Premium",
        formatProposalCurrency(candidate.premium_income),
        `${formatProposalCount(candidate.contracts)} contract(s) / bid ${formatProposalCurrency(candidate.call_bid)}`,
      ],
      [
        "Risk",
        `Max ${formatProposalCurrency(risk.max_income)}`,
        `B/E ${formatProposalCurrency(risk.break_even)} / zero ${formatProposalCurrency(risk.max_loss_if_zero)}`,
      ],
      [
        "Liquidity",
        `${formatProposalNumber(candidate.delta)} delta`,
        `OI ${formatProposalCount(candidate.open_interest)} / Vol ${formatProposalCount(candidate.volume)}`,
      ],
    ];
  } else if (proposal.proposed_action === "roll_covered_call") {
    const rollFrom = objectPayload(candidate.roll_from);
    const rollTo = objectPayload(candidate.roll_to);
    const currentMonitor = objectPayload(risk.current_monitor);
    const nextRisk = objectPayload(risk.next_risk);
    items = [
      [
        "Roll From",
        displayValue(rollFrom.call_symbol),
        `${formatProposalDate(rollFrom.expiration_date)} / K ${formatProposalNumber(rollFrom.call_strike)}`,
      ],
      [
        "Roll To",
        displayValue(rollTo.call_symbol),
        `${formatProposalDate(rollTo.expiration_date)} / K ${formatProposalNumber(rollTo.call_strike)}`,
      ],
      [
        "Buyback",
        formatProposalCurrency(pickProposalValue(risk.estimated_buyback_debit, currentMonitor.estimated_buyback_debit)),
        `Open PnL ${formatProposalSignedCurrency(pickProposalValue(risk.estimated_open_pnl, currentMonitor.estimated_open_pnl))}`,
      ],
      [
        "Next Income",
        formatProposalCurrency(rollTo.premium_income),
        `Bid ${formatProposalCurrency(rollTo.call_bid)} / B/E ${formatProposalCurrency(nextRisk.break_even)}`,
      ],
    ];
  }
  const detailsMarkup = items.length
    ? `
      <div class="proposal-detail-grid">
        ${items.map(renderStrategyProposalDetail).join("")}
      </div>
    `
    : "";
  const chainMarkup = renderStrategyProposalChainLine(proposal, proposals);
  if (!detailsMarkup && !chainMarkup) {
    return "";
  }
  return `${detailsMarkup}${chainMarkup}`;
}

function renderStrategyProposalDetail([label, value, detail]) {
  return `
    <div class="proposal-detail">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(detail)}</small>
    </div>
  `;
}

function renderStrategyProposalChainLine(proposal, proposals) {
  const candidate = objectPayload(proposal.candidate_payload);
  if (proposal.proposed_action === "roll_covered_call") {
    const sourceProposalId = pickProposalValue(candidate.source_proposal_id, objectPayload(proposal.risk_payload).source_proposal_id);
    if (sourceProposalId) {
      return `<p class="proposal-chain-line">Roll chain: ${escapeHtml(formatShortIdentifier(sourceProposalId))} -> ${escapeHtml(formatShortIdentifier(proposal.id))}</p>`;
    }
    return "";
  }
  const childRolls = proposals
    .filter((child) => objectPayload(child.candidate_payload).source_proposal_id === proposal.id)
    .map((child) => formatShortIdentifier(child.id));
  if (!childRolls.length) {
    return "";
  }
  return `<p class="proposal-chain-line">Roll proposals: ${escapeHtml(childRolls.join(", "))}</p>`;
}

function renderStrategyProposalActions(proposal) {
  const actions = [];
  if (proposal.status === "pending") {
    actions.push(["approve", "Approve", "primary"]);
    actions.push(["reject", "Reject", "danger"]);
  }
  const isCoveredCall = proposal.strategy_id === "covered_call_v1";
  const isOpenCoveredCallAction =
    proposal.proposed_action === "sell_covered_call" || proposal.proposed_action === "roll_covered_call";
  if (isCoveredCall && proposal.proposed_action === "sell_covered_call") {
    if (proposal.status === "approved") {
      actions.push(["execute_covered_call", "Execute", "primary"]);
    }
  }
  if (isCoveredCall && isOpenCoveredCallAction) {
    if (proposal.status === "executed") {
      actions.push(["monitor_covered_call", "Monitor", ""]);
      actions.push(["roll_propose", "Roll", "primary"]);
      actions.push(["close_covered_call", "Close", "danger"]);
    }
  }
  if (isCoveredCall && proposal.proposed_action === "roll_covered_call" && proposal.status === "approved") {
    actions.push(["roll_execute", "Execute Roll", "primary"]);
    actions.push(["roll_continue", "Continue Roll", ""]);
  }
  if (!actions.length) {
    return "";
  }
  return `
    <div class="table-actions">
      ${actions
        .map(
          ([action, label, tone]) => {
            const brokerMutation = isCoveredCallBrokerMutation(action);
            const actionKey = brokerMutation ? `covered-call:${proposal.id}:${action}` : "";
            return `
            <button class="table-action ${tone}" type="button" data-proposal-action="${escapeHtml(action)}" data-proposal-id="${escapeHtml(proposal.id)}" ${brokerMutation ? `data-broker-mutation="true" data-action-key="${escapeHtml(actionKey)}"` : ""}>
              ${escapeHtml(label)}
            </button>
          `;
          }
        )
        .join("")}
    </div>
  `;
}

function isCoveredCallBrokerMutation(action) {
  return [
    "execute_covered_call",
    "monitor_covered_call",
    "close_covered_call",
    "roll_execute",
    "roll_continue",
  ].includes(action);
}

function formatActivityCount(value) {
  const number = Number(value);
  return Number.isFinite(number) ? String(number) : "0";
}

function objectPayload(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function pickProposalValue(...values) {
  return values.find((value) => value !== null && value !== undefined && value !== "");
}

function displayValue(value) {
  const selected = pickProposalValue(value);
  return selected === undefined ? "--" : String(selected);
}

function formatProposalCurrency(value) {
  const selected = pickProposalValue(value);
  return selected === undefined ? "--" : formatCurrency(selected);
}

function formatProposalSignedCurrency(value) {
  const selected = pickProposalValue(value);
  return selected === undefined ? "--" : formatSignedCurrency(selected);
}

function formatProposalNumber(value) {
  const selected = pickProposalValue(value);
  return selected === undefined ? "--" : formatNumber(selected);
}

function formatProposalCount(value) {
  const selected = pickProposalValue(value);
  const number = Number(selected);
  return Number.isFinite(number) ? number.toLocaleString("en-US", { maximumFractionDigits: 0 }) : "--";
}

function formatProposalDate(value) {
  const selected = pickProposalValue(value);
  return selected === undefined ? "--" : formatSpreadDate(selected);
}

function formatShortIdentifier(value) {
  const text = String(value || "");
  return text.length > 12 ? text.slice(0, 8) : text || "--";
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

function renderPreOpenAssessment() {
  const assessment = state.preOpenAssessment;
  const overlay = state.preOpenStatus;
  updatePreOpenButtons();
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
        detail: "Load the live macro board to classify market tone.",
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
          <strong>Real-time Macro Board</strong>
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
      detail: overlay.detail || overlayLiveDetail("Live macro board", assessment.analyzed_at),
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
    <p class="overlay-detail">${escapeHtml(overlay.detail || overlayLiveDetail("Live macro board", assessment.analyzed_at))}</p>
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
      <div>
        <dt>Coverage</dt>
        <dd>${escapeHtml(formatPreOpenCoverage(assessment))}</dd>
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
    els.preOpenPuts.innerHTML = preOpenOptionOverlaysSkipped(assessment)
      ? '<div class="holding-empty">Option overlays were skipped for fast macro refresh. Use Load Option Overlays to inspect QQQ / SPY puts.</div>'
      : '<div class="holding-empty">No short-dated reference puts were found.</div>';
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

  renderPreOpenChainAnalysis(assessment);
}

function renderPreOpenChainAnalysis(assessment) {
  const analyses = assessment?.chain_analyses || [];
  if (!Array.isArray(analyses) || !analyses.length) {
    els.preOpenChainAnalysis.innerHTML = preOpenOptionOverlaysSkipped(assessment)
      ? '<div class="holding-empty">Option-chain overlays were skipped for fast macro refresh. Load option overlays when you need volatility and liquidity detail.</div>'
      : '<div class="holding-empty">No option chain analysis is available.</div>';
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

function preOpenOptionOverlaysSkipped(assessment) {
  const detail = `${assessment?.freshness_detail || ""} ${(assessment?.reasons || []).join(" ")}`.toLowerCase();
  return detail.includes("option overlays skipped");
}

function formatPreOpenCoverage(assessment) {
  const signalCount = Array.isArray(assessment?.signals) ? assessment.signals.length : 0;
  const putCount = Array.isArray(assessment?.put_snapshots) ? assessment.put_snapshots.length : 0;
  const chainCount = Array.isArray(assessment?.chain_analyses) ? assessment.chain_analyses.length : 0;
  if (preOpenOptionOverlaysSkipped(assessment)) {
    return `${signalCount} proxies / option overlays skipped`;
  }
  return `${signalCount} proxies / ${putCount} puts / ${chainCount} chain layers`;
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
                <div><span>OI / Vol</span><strong>${escapeHtml(`${formatPositionQuantity(strike.open_interest)} / ${formatPositionQuantity(strike.volume)}`)}</strong></div>
                <div><span>Bid / Ask</span><strong>${escapeHtml(`${formatNumber(strike.bid)} / ${formatNumber(strike.ask)}`)}</strong></div>
                <div><span>Spread / Delta</span><strong>${escapeHtml(`${formatPercentValue(strike.spread_pct)} / ${formatSignedDecimal(strike.delta, 2)}`)}</strong></div>
              </div>
            </article>
          `
        )
        .join("")
    : '<div class="strategy-note-body empty">No liquid strikes were sampled for this expiry.</div>';
  return `
    <article class="strategy-journal-entry">
      <div class="strategy-journal-head"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(`${formatSpreadDate(expiry.expiration_date)} (${expiry.days_to_expiration} DTE)`)}</span></div>
      <div class="status-list">
        <div><dt>ATM Put</dt><dd>${escapeHtml(`${formatSpreadStrike(expiry.atm_strike)} / ${formatNumber(expiry.atm_mid_price)}`)}</dd></div>
        <div><dt>ATM Delta / IV</dt><dd>${escapeHtml(`${formatSignedDecimal(expiry.atm_delta, 2)} / ${formatImpliedVolatility(expiry.atm_implied_volatility)}`)}</dd></div>
        <div><dt>Put Skew Leg</dt><dd>${escapeHtml(expiry.put_skew_strike ? `${formatSpreadStrike(expiry.put_skew_strike)} / ${formatSignedDecimal(expiry.put_skew_delta, 2)}` : "--")}</dd></div>
        <div><dt>Skew IV Lift</dt><dd>${escapeHtml(formatSignedIvDifference(expiry.put_skew_diff))}</dd></div>
        <div><dt>Spread Buckets</dt><dd>${escapeHtml(`${expiry.tight_count} tight / ${expiry.workable_count} workable / ${expiry.wide_count} wide`)}</dd></div>
        <div><dt>Median Spread</dt><dd>${escapeHtml(formatPercentValue(expiry.median_spread_pct))}</dd></div>
      </div>
      ${liquidMarkup}
    </article>
  `;
}

function getSelectedAccount() {
  return state.accounts.find((account) => account.external_account_id === state.selectedAccountId) || null;
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
  setBusinessDisabled(els.saveStrategyControls, !hasAccount, hasAccount ? "" : "Select a broker account first.");
  setBusinessDisabled(els.runStrategyScan, !hasAccount, hasAccount ? "" : "Select a broker account first.");
  els.runStrategyReview.disabled = !hasAccount;
  els.runStrategyReview.title = hasAccount ? "" : "Select a broker account first.";
  applyTradingSafetyState();
}

function updateZeroDteLotteryButtons(forceBusy = false) {
  if (!els.previewZeroDteLottery) {
    return;
  }
  const hasAccount = Boolean(state.selectedAccountId);
  const disabled = !hasAccount || forceBusy;
  els.previewZeroDteLottery.disabled = disabled;
  els.previewZeroDteLottery.title = hasAccount ? "Preview without submitting an order." : "Select a broker account first.";
}

function updatePreOpenButtons(forceSaving = false) {
  if (!els.loadPreOpenBoard || !els.loadPreOpenOverlays || !els.savePreOpenBoard) {
    return;
  }
  const hasAccount = Boolean(state.selectedAccountId);
  const loading = state.preOpenStatus?.kind === "loading";
  const hasLoadedAssessment = Boolean(state.preOpenAssessment) && !loading;
  const canSaveAssessment = hasLoadedAssessment && (state.preOpenStatus.kind === "live" || state.preOpenStatus.kind === "partial");

  els.loadPreOpenBoard.disabled = !hasAccount || loading;
  els.loadPreOpenOverlays.disabled = !hasAccount || loading;
  els.savePreOpenBoard.disabled = !hasAccount || !canSaveAssessment || forceSaving;

  els.loadPreOpenBoard.title = hasAccount ? "Refresh the fast live macro board." : "Select a broker account first.";
  els.loadPreOpenOverlays.title = hasAccount ? "Load slower QQQ / SPY option overlays on demand." : "Select a broker account first.";
  els.savePreOpenBoard.title = canSaveAssessment ? "Store the current live macro board as the latest run." : "Load the live macro board first.";
}

    hintEl: els.replaceFormHint,
async function submitOrder(...args) {
  return ordersView.submitOrder(...args);
}

async function refreshOrder(...args) {
  return ordersView.refreshOrder(...args);
}

async function cancelOrder(...args) {
  return ordersView.cancelOrder(...args);
}

async function replaceSelectedOrder(...args) {
  return ordersView.replaceSelectedOrder(...args);
}

async function submitJournalEntry() {
  return ordersView.submitJournalEntry();
}

function renderOrders(...args) {
  return ordersView.renderOrders(...args);
}

function renderSelectedOrder(...args) {
  return ordersView.renderSelectedOrder(...args);
}

function setSelectedOrder(...args) {
  return ordersView.setSelectedOrder(...args);
}

function getSelectedOrder(...args) {
  return ordersView.getSelectedOrder(...args);
}

function getSelectedExecution(...args) {
  return ordersView.getSelectedExecution(...args);
}

function getSelectedJournalEntries(...args) {
  return ordersView.getSelectedJournalEntries(...args);
}

function renderSelectedExecution() {
  return ordersView.renderSelectedExecution();
}

function renderSelectedJournal() {
  return ordersView.renderSelectedJournal();
}

function updateOrderTicketAvailability(...args) {
  return ordersView.updateOrderTicketAvailability(...args);
}

function syncTicketOrderFields(...args) {
  return ordersView.syncTicketOrderFields(...args);
}

function syncReplaceOrderFields(...args) {
  return ordersView.syncReplaceOrderFields(...args);
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

function normalizeLotterySymbol() {
  const symbol = String(els.zeroDteLotterySymbol?.value || "QQQ.US").trim().toUpperCase();
  if (!symbol) {
    throw new Error("Zero-DTE lottery symbol is required.");
  }
  if (els.zeroDteLotterySymbol) {
    els.zeroDteLotterySymbol.value = symbol;
  }
  return symbol;
}

function matchingQuoteTime(symbol) {
  const researchState = window.StocksToolResearch?.getState?.();
  const researchRow = researchState?.rows?.find(
    (row) => String(row?.symbol || "").toUpperCase() === String(symbol || "").toUpperCase()
  );
  const timestamp = researchRow?.quote?.timestamp || researchRow?.quote?.updated_at;
  if (!timestamp) {
    return "Not loaded";
  }
  return `${formatDateTime(timestamp)} (research context only)`;
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
  if (runtime.holding_open_position) {
    return {
      value: "Monitoring",
      tone: "warning",
      detail: `${runtime.open_spread_count || 1} open / next ${formatDateTime(runtime.next_monitor_after)}`,
    };
  }
  if (runtime.daily_entry_cap_reached) {
    return {
      value: "Daily Cap",
      tone: "warning",
      detail: runtime.next_action ? formatRuntimeNextAction(runtime.next_action) : "Wait next session",
    };
  }
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
    value: runtime.next_action ? formatRuntimeNextAction(runtime.next_action) : "Running",
    tone: "success",
    detail: runtime.entry_block_reason || "Automatic bull put entry is enabled for this account.",
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

function formatRuntimeNextAction(value) {
  if (value === "monitor_open_spread") {
    return "Monitor open spread";
  }
  if (value === "wait_next_session") {
    return "Wait next session";
  }
  if (value === "scan_for_entry") {
    return "Scan for entry";
  }
  if (value === "resolve_runtime_controls") {
    return "Resolve runtime controls";
  }
  if (value === "entry_blocked") {
    return "Entry blocked";
  }
  return formatRuntimeScanResult(value);
}

function setStatus(message, tone = "") {
  if (tone === "success" && !state.coreDataHealthy) {
    message = `Required account data is stale. Broker-writing actions are disabled. ${message}`;
    tone = "error";
  }
  if (document.body?.dataset.demo === "true") {
    const translated = translateText(String(message || ""), TRANSLATIONS.zh || {});
    if (translated) message = translated;
    if (String(message).startsWith("Dashboard updated.")) message = "页面已更新。策略面板优先加载，宏观数据按需读取。";
    if (String(message).includes("strategy lifecycle warning")) message = "有策略生命周期警告需要人工复核。";
  }
  els.statusBanner.textContent = message;
  els.statusBanner.className = "status-banner topbar-status";
  if (tone) {
    els.statusBanner.classList.add(tone);
  }
}

function buildOverlayStatus(kind, detail = "", reason = "") {
  return { kind, detail, reason };
}

function overlayStatusTone(kind) {
  if (kind === "live") {
    return "success";
  }
  if (kind === "loading" || kind === "timed_out" || kind === "stale" || kind === "partial") {
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
  if (kind === "partial") {
    return "Partial";
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

function formatStrategyProposalActionResult(action, result) {
  if (action === "approve" || action === "reject") {
    return `Strategy proposal ${result?.status || "updated"}.`;
  }
  if (action === "monitor_covered_call") {
    return `Covered call monitor action: ${formatStrategyStatusLabel(result?.action)}.`;
  }
  if (action === "roll_propose") {
    return result?.proposal?.id
      ? `Covered call roll proposal created: ${result.proposal.id}.`
      : "Covered call roll proposal scan completed without an eligible next call.";
  }
  if (action === "roll_execute" || action === "roll_continue") {
    const status = result?.sequence_status ? formatStrategyStatusLabel(result.sequence_status) : "submitted";
    const buyback = result?.buyback_order?.id ? ` Buyback order: ${result.buyback_order.id}.` : "";
    const sell = result?.sell_order?.id ? ` Sell order: ${result.sell_order.id}.` : "";
    return `Covered call roll ${status}.${buyback}${sell}`;
  }
  if (action === "execute_covered_call") {
    return `Covered call order submitted: ${result?.order?.id || "created"}.`;
  }
  if (action === "close_covered_call") {
    return `Covered call close order submitted: ${result?.order?.id || "created"}.`;
  }
  return "Strategy proposal action completed.";
}

function formatCoveredCallLifecycleResult(result) {
  const payload = objectPayload(result);
  const openRefreshed = Number(payload.sell_orders_refreshed || 0);
  const closeRefreshed = Number(payload.close_orders_refreshed || 0);
  const rollRefreshed = Number(payload.roll_buyback_orders_refreshed || 0) + Number(payload.roll_sell_orders_refreshed || 0);
  const advanced =
    Number(payload.sell_orders_executed || 0) +
    Number(payload.closed_proposals || 0) +
    Number(payload.roll_sell_orders_submitted || 0) +
    Number(payload.rolls_executed || 0);
  if (state.language === "zh") {
    return `${openRefreshed} 个开仓刷新，${closeRefreshed} 个平仓刷新，${rollRefreshed} 个移仓刷新；${advanced} 个推进`;
  }
  return `${openRefreshed} open, ${closeRefreshed} close, ${rollRefreshed} roll refreshed; ${advanced} advanced`;
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

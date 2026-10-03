(function () {
  "use strict";

  const listeners = new Set();
  let latestState = null;
  let latestResearchState = null;
  let currentWorkspace = "research";
  let demoLanguageRequested = false;

  function fetchJson(url, options) {
    if (typeof window.StocksToolApiClient?.fetchJson === "function") {
      return window.StocksToolApiClient.fetchJson(url, options);
    }
    return Promise.reject(new Error("The workbench API client is not ready."));
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function objectPayload(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function arrayPayload(value, keys = []) {
    if (Array.isArray(value)) return value;
    const payload = objectPayload(value);
    for (const key of keys) {
      if (Array.isArray(payload[key])) return payload[key];
    }
    return [];
  }

  function numberValue(value, fallback = null) {
    if (value === null || value === undefined || value === "") return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function money(value, currency = "USD") {
    const parsed = numberValue(value);
    if (parsed === null) return "--";
    try {
      return new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: currency || "USD",
        maximumFractionDigits: 2,
      }).format(parsed);
    } catch (_error) {
      return `${currency || "USD"} ${parsed.toFixed(2)}`;
    }
  }

  function percent(value, digits = 2) {
    const parsed = numberValue(value);
    return parsed === null ? "--" : `${parsed.toFixed(digits)}%`;
  }

  function dateTime(value, timeZone = "Asia/Shanghai") {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone,
    }).format(date);
  }

  function text(chinese, english) {
    return String(document.documentElement?.lang || "zh-CN").toLowerCase().startsWith("zh") ? chinese : english;
  }

  function statusLabel(value) {
    const raw = String(value ?? "");
    const labels = {
      live: text("实时", "Live"),
      ok: text("完整", "Complete"),
      partial: text("部分可用", "Partial"),
      degraded: text("质量下降", "Degraded"),
      unavailable: text("不可用", "Unavailable"),
      stale: text("陈旧", "Stale"),
      mock_demo: text("演示数据", "Demo data"),
      bull_put_ready: text("牛市看跌可评估", "Bull Put ready"),
      zero_dte_preview_only: text("零日期权仅预览", "Zero-DTE preview only"),
    };
    return labels[raw] || raw;
  }

  function accountIdFromState(state = latestState) {
    return state?.selectedAccountId || document.getElementById("account-select")?.value || "";
  }

  function selectedSymbol() {
    return latestResearchState?.selectedSymbol || window.StocksToolResearch?.getState?.().selectedSymbol || "";
  }

  function loadScopedReads(requestSpecs, state = latestState) {
    const loader = window.StocksToolAccountLoaderRuntime;
    if (!loader || typeof loader.loadWorkspaceReads !== "function") {
      return Promise.reject(new Error("Account read context is not ready."));
    }
    return loader.loadWorkspaceReads(requestSpecs, {
      accountId: state?.selectedAccountId || accountIdFromState(state),
      loadGeneration: Number(state?.accountLoadGeneration || 0),
    });
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  function notify(event) {
    for (const listener of listeners) {
      try {
        listener(event);
      } catch (error) {
        console.error(error);
      }
    }
  }

  function syncAccountOptions(state) {
    const topbarSelect = document.getElementById("topbar-account-select");
    const sourceSelect = document.getElementById("account-select");
    if (!topbarSelect) return;
    const accounts = Array.isArray(state?.accounts) ? state.accounts : [];
    topbarSelect.replaceChildren();
    if (!accounts.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = text("暂无账户", "No accounts");
      topbarSelect.appendChild(option);
      topbarSelect.disabled = true;
      return;
    }
    topbarSelect.disabled = false;
    for (const account of accounts) {
      const option = document.createElement("option");
      option.value = account.external_account_id || "";
      option.textContent = `${account.display_name || account.external_account_id} / ${account.base_currency || "USD"}`;
      option.selected = option.value === state.selectedAccountId;
      topbarSelect.appendChild(option);
    }
    if (sourceSelect && sourceSelect.value !== topbarSelect.value) {
      topbarSelect.value = sourceSelect.value || state.selectedAccountId || topbarSelect.value;
    }
  }

  function updateTopbar(state) {
    const account = accountIdFromState(state);
    const accountContext = document.getElementById("topbar-account-context");
    const modeContext = document.getElementById("topbar-mode-context");
    const reasonContext = document.getElementById("topbar-reason-context");
    if (accountContext) accountContext.textContent = account || "--";
    if (modeContext) modeContext.textContent = text("模拟交易 / Paper", "Paper / Simulated");
    if (!reasonContext) return;

    const unresolved = Array.isArray(state?.unresolvedTradingIntents) ? state.unresolvedTradingIntents.length : 0;
    const requiredFailures = Array.isArray(state?.coreLoadFailures) ? state.coreLoadFailures.filter(Boolean) : [];
    const operator = objectPayload(state?.operatorStatus);
    const postureReason = String(operator.operator_posture_reason || "");
    const lifecycleWarning = postureReason.match(/^(\d+) strategy lifecycle warning/);
    const postureLabel = lifecycleWarning
      ? text(`有 ${lifecycleWarning[1]} 项策略状态需要检查`, postureReason)
      : text("运行前需要人工检查；详情见“运行与安全”", postureReason || "Review required before unattended work");
    const reason = unresolved
      ? text(`有 ${unresolved} 个订单意图待核对`, `${unresolved} trading intent(s) need review`)
      : requiredFailures.length
        ? text(`核心数据待确认：${requiredFailures.join("、")}`, `Core data needs review: ${requiredFailures.join(", ")}`)
        : operator.ready_for_unattended === false
          ? postureLabel
          : text("可以继续研究；写操作仍需单独确认", "Research is ready; writes still need explicit confirmation");
    reasonContext.textContent = reason;
    reasonContext.dataset.tone = unresolved || requiredFailures.length || operator.ready_for_unattended === false ? "warning" : "success";
  }

  function updateAccountState(event) {
    if (document.body?.dataset.demo === "true" && !demoLanguageRequested && !String(document.documentElement.lang || "").toLowerCase().startsWith("zh")) {
      demoLanguageRequested = true;
      document.querySelector('[data-lang-option="zh"]')?.click();
    }
    latestState = event?.detail?.state || latestState;
    syncAccountOptions(latestState);
    updateTopbar(latestState);
    notify({ type: "account-state", state: latestState, payload: event?.detail || {} });
  }

  function updateResearchState(event) {
    latestResearchState = event?.detail?.state || latestResearchState;
    notify({ type: "research-state", state: latestResearchState });
  }

  function updateWorkspace(event) {
    currentWorkspace = event?.detail?.workspace || currentWorkspace;
    notify({ type: "workspace", workspace: currentWorkspace, state: latestState });
  }

  function wireAccountSelector() {
    const topbarSelect = document.getElementById("topbar-account-select");
    const sourceSelect = document.getElementById("account-select");
    topbarSelect?.addEventListener("change", () => {
      if (!sourceSelect || topbarSelect.value === sourceSelect.value) return;
      sourceSelect.value = topbarSelect.value;
      sourceSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  function init() {
    wireAccountSelector();
    window.addEventListener("stocks-tool:account-state", updateAccountState);
    window.addEventListener("stocks-tool:research-state", updateResearchState);
    window.addEventListener("stocks-tool:workspace-change", updateWorkspace);
    updateTopbar(latestState);
    return api;
  }

  const api = {
    init,
    fetchJson,
    loadScopedReads,
    escapeHtml,
    objectPayload,
    arrayPayload,
    numberValue,
    money,
    percent,
    dateTime,
    text,
    statusLabel,
    accountId: accountIdFromState,
    selectedSymbol,
    subscribe,
    getState: () => latestState,
    getResearchState: () => latestResearchState,
    getWorkspace: () => currentWorkspace,
  };

  window.StocksToolWorkbenchUI = api;
  document.addEventListener("DOMContentLoaded", init, { once: true });
})();

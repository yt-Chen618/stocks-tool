(function () {
  const ACTIVITY_PAGE_SIZE = 25;
  const EMPTY_EXPERIMENT = { proposals: [], runs: [], signals: [], reviews: [] };
  const EMPTY_COVERED_CALL = { summary: {}, proposals: [], runs: [], signals: [], reviews: [] };

  function createAccountLoader({
    state,
    fetchJson,
    decodeCursorPage,
    createOverlayStatus,
    formatPanelLoadLabel,
    renderAccountOptions,
    renderAccountState,
    renderEmptyState,
    renderRecoveryLoading,
    renderRecoveryStatus,
    renderRecoveryError,
    applyTradingSafetyState,
    updateSyncButtons,
    updateOrderTicketAvailability,
    updatePreOpenButtons,
  }) {
    if (!state || typeof fetchJson !== "function") {
      throw new Error("StocksToolAccountLoader requires state and fetchJson dependencies.");
    }

    function emptyActivityPage() {
      return { cursor: null, hasMore: false, loading: false, error: null };
    }

    function ensureActivityPages() {
      state.activityPages ||= {};
      for (const key of ["orders", "executions", "journals"]) {
        state.activityPages[key] ||= emptyActivityPage();
      }
    }

    function objectPayload(value) {
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }

    function normalizePagePayload(payload) {
      if (typeof decodeCursorPage !== "function") {
        throw new Error("CursorPage decoder is unavailable.");
      }
      const page = decodeCursorPage(payload);
      return { items: page.items, cursor: page.cursor, hasMore: page.hasMore, total: null };
    }

    function activityUrl(kind, accountId, { cursor = null, orderId = null } = {}) {
      const endpoint = kind === "orders" ? "/orders/paged" : kind === "executions" ? "/executions/paged" : "/journals/paged";
      const params = new URLSearchParams({
        external_account_id: accountId,
        limit: String(ACTIVITY_PAGE_SIZE),
      });
      if (kind === "orders") {
        params.set("mode", "paper");
      }
      if (cursor) {
        params.set("cursor", cursor);
      }
      if (orderId && kind !== "orders") {
        params.set("order_id", orderId);
      }
      return `${endpoint}?${params.toString()}`;
    }

    function setActivityPage(kind, payload, { append = false } = {}) {
      ensureActivityPages();
      const page = normalizePagePayload(payload);
      const current = Array.isArray(state[kind]) ? state[kind] : [];
      const values = append ? [...current, ...page.items] : page.items;
      const seen = new Set();
      state[kind] = values.filter((item) => {
        const id = item?.id || `${item?.order_id || ""}:${item?.executed_at || item?.updated_at || ""}`;
        if (seen.has(id)) {
          return false;
        }
        seen.add(id);
        return true;
      });
      state.activityPages[kind] = {
        cursor: page.cursor,
        hasMore: page.hasMore,
        loading: false,
        error: null,
        total: page.total,
      };
      return page;
    }

    async function loadActivityPage(kind, { append = false, orderId = null, accountId = state.selectedAccountId } = {}) {
      if (!accountId || !["orders", "executions", "journals"].includes(kind)) {
        return { discarded: false, page: { items: [], cursor: null, hasMore: false, total: null } };
      }
      ensureActivityPages();
      const pageState = state.activityPages[kind];
      if (pageState.loading) {
        return { discarded: false, skipped: true, page: pageState };
      }
      if (append && !pageState.hasMore) {
        return { discarded: false, skipped: true, page: pageState };
      }
      const loadGeneration = state.accountLoadGeneration;
      pageState.loading = true;
      pageState.error = null;
      const cursor = append ? pageState.cursor : null;
      try {
        const response = await fetchJson(activityUrl(kind, accountId, { cursor, orderId }));
        if (loadGeneration !== state.accountLoadGeneration || accountId !== state.selectedAccountId) {
          return { discarded: true, page: normalizePagePayload(response) };
        }
        const page = setActivityPage(kind, response, { append });
        return { discarded: false, page };
      } catch (error) {
        if (loadGeneration !== state.accountLoadGeneration || accountId !== state.selectedAccountId) {
          return { discarded: true, error };
        }
        pageState.loading = false;
        pageState.error = error?.message || "Request failed.";
        throw error;
      }
    }

    async function ensureSelectedOrderDetail(previousOrder = null) {
      const selectedId = state.selectedOrderId;
      const accountId = state.selectedAccountId;
      const loadGeneration = state.accountLoadGeneration;
      if (!selectedId) {
        return null;
      }
      const existing = state.orders.find((order) => order.id === selectedId);
      if (existing) {
        return existing;
      }
      try {
        const detail = await fetchJson(`/orders/${encodeURIComponent(selectedId)}`);
        if (loadGeneration !== state.accountLoadGeneration || accountId !== state.selectedAccountId || selectedId !== state.selectedOrderId) {
          return null;
        }
        if (accountId && detail?.external_account_id !== accountId) {
          throw new Error("Selected order belongs to a different broker account.");
        }
        state.selectedOrderDetail = detail;
        state.selectedOrderDetailOrderId = selectedId;
        const rowIndex = state.orders.findIndex((order) => order.id === selectedId);
        if (rowIndex >= 0) {
          state.orders[rowIndex] = detail;
        }
        return detail;
      } catch (error) {
        if (loadGeneration !== state.accountLoadGeneration || accountId !== state.selectedAccountId || selectedId !== state.selectedOrderId) {
          return null;
        }
        if (previousOrder?.id === selectedId && previousOrder.external_account_id === accountId) {
          state.selectedOrderDetail = previousOrder;
          state.selectedOrderDetailOrderId = selectedId;
          state.selectedOrderDetailError = error?.message || "Selected order detail unavailable.";
          return previousOrder;
        }
        state.selectedOrderId = "";
        state.selectedOrderDetail = null;
        state.selectedOrderDetailError = error?.message || "Selected order detail unavailable.";
        return null;
      }
    }

    function resetSelectedAccountState() {
      state.orders = [];
      state.spreads = [];
      state.runtime = null;
      state.zeroDteLotteryRuntime = null;
      state.zeroDteLotteryPreview = null;
      state.zeroDteLotteryScanResult = null;
      state.strategyExperiment = { ...EMPTY_EXPERIMENT };
      state.coveredCallActivity = { ...EMPTY_COVERED_CALL };
      state.advisorContext = null;
      state.advisorDraft = null;
      state.advisorRuns = [];
      state.operatorStatus = null;
      state.recoveryStatus = null;
      state.recoveryStatusState = "idle";
      state.unresolvedTradingIntents = [];
      state.coreDataHealthy = false;
      state.coreLoadFailures = ["account selection"];
      state.panelLoadErrors = {};
      state.marketEvents = [];
      state.executions = [];
      state.journals = [];
      state.preOpenRuns = [];
      state.recoverCloseEligibility = {};
      state.latestSnapshot = null;
      state.selectedOrderId = "";
      state.selectedOrderDetail = null;
      state.selectedOrderDetailError = null;
      state.preOpenAssessment = null;
      state.preOpenStatus = createOverlayStatus("idle", "Select a broker account to load the macro board on demand.");
      state.activityPages = {
        orders: emptyActivityPage(),
        executions: emptyActivityPage(),
        journals: emptyActivityPage(),
      };
      state.advisorStatus = createOverlayStatus(
        "idle",
        "Select a broker account before loading advisor context.",
      );
      renderEmptyState?.();
      renderRecoveryStatus?.(null);
    }

    async function loadRecoverCloseEligibility(spreads) {
      const entries = await Promise.all(
        (Array.isArray(spreads) ? spreads : []).map(async (spread) => {
          try {
            const eligibility = await fetchJson(
              `/strategies/bull-put/spreads/${encodeURIComponent(spread.id)}/recover-close/eligibility?external_account_id=${encodeURIComponent(state.selectedAccountId)}&mode=paper`,
            );
            return [spread.id, eligibility];
          } catch (error) {
            console.error(error);
            return [spread.id, {
              spread_id: spread.id,
              eligible: false,
              reasons: ["eligibility_unavailable"],
              external_account_id: spread.external_account_id,
              mode: spread.mode || "paper",
              latest_should_close: Boolean(spread.latest_monitor_should_close),
              old_short_close_order_id: spread.short_exit_order_id,
              old_short_close_order_status: spread.latest_close_order_status,
              working_replacement_order_id: null,
              max_debit_required_hint: null,
            }];
          }
        }),
      );
      return Object.fromEntries(entries);
    }

    async function loadAccountData() {
      const loadGeneration = ++state.accountLoadGeneration;
      const selectedAccountId = state.selectedAccountId;
      const previousOrder = state.orders.find((order) => order.id === state.selectedOrderId) || null;
      state.activityPages = {
        orders: emptyActivityPage(),
        executions: emptyActivityPage(),
        journals: emptyActivityPage(),
      };
      if (!selectedAccountId) {
        resetSelectedAccountState();
        applyTradingSafetyState?.();
        return { coreHealthy: false, requiredFailures: ["account selection"], optionalFailures: [], discarded: false };
      }

      state.coreDataHealthy = false;
      state.coreLoadFailures = ["Account data loading"];
      state.recoveryStatus = null;
      state.recoveryStatusState = "loading";
      renderRecoveryLoading?.();
      applyTradingSafetyState?.();

      const accountId = encodeURIComponent(selectedAccountId);
      const requestSpecs = [
        ["latestSnapshot", true, `/account-snapshots/latest?external_account_id=${accountId}`],
        ["orders", true, activityUrl("orders", selectedAccountId)],
        ["spreads", true, `/strategies/bull-put/spreads?external_account_id=${accountId}&mode=paper`],
        ["runtime", true, `/strategies/bull-put/runtime?external_account_id=${accountId}`],
        ["operatorStatus", true, `/ops/unattended-status?external_account_id=${accountId}&mode=paper`],
        ["recoveryStatus", true, `/ops/recovery-status?external_account_id=${accountId}&mode=paper&limit=100`],
        ["tradingIntents", true, `/ops/trading-intents?external_account_id=${accountId}&mode=paper&limit=100`],
        ["tradeActions", true, `/ops/trade-actions?external_account_id=${accountId}&mode=paper&limit=100`],
        ["zeroDteLotteryRuntime", false, `/strategies/zero-dte-lottery/runtime?external_account_id=${accountId}&mode=paper`],
        ["strategyExperiment", true, `/strategies/experiment?external_account_id=${accountId}&limit=6`],
        ["coveredCallActivity", true, `/strategies/covered-call/activity?external_account_id=${accountId}&limit=8`],
        ["advisorRuns", false, `/strategies/advisor/run-cards?external_account_id=${accountId}&source=deepseek&limit=5`],
        ["marketEvents", false, "/market-events?limit=8"],
        ["executions", false, activityUrl("executions", selectedAccountId)],
        ["journals", false, activityUrl("journals", selectedAccountId)],
        ["preOpenRuns", false, `/strategies/pre-open-runs?external_account_id=${accountId}&limit=1`],
      ];
      const settled = await Promise.allSettled(requestSpecs.map(([, , url]) => fetchJson(url)));
      const values = {};
      const errors = {};
      settled.forEach((result, index) => {
        const [key] = requestSpecs[index];
        if (result.status === "fulfilled") {
          values[key] = result.value;
        } else {
          console.error(result.reason);
          errors[key] = result.reason?.message || "Request failed.";
        }
      });
      if (loadGeneration !== state.accountLoadGeneration || selectedAccountId !== state.selectedAccountId) {
        return { coreHealthy: state.coreDataHealthy, requiredFailures: [], optionalFailures: [], discarded: true };
      }
      if (values.latestSnapshot === null || values.operatorStatus === null) {
        for (const key of ["latestSnapshot", "operatorStatus"]) {
          if (values[key] === null) {
            delete values[key];
            errors[key] = "Required account data was empty.";
          }
        }
      }

      if ("recoveryStatus" in values) {
        const recovery = objectPayload(values.recoveryStatus);
        if (
          recovery.external_account_id !== selectedAccountId ||
          recovery.mode !== "paper" ||
          typeof recovery.recovery_blocked !== "boolean" ||
          !recovery.status
        ) {
          delete values.recoveryStatus;
          errors.recoveryStatus = "Recovery status did not match the selected paper account.";
        } else {
          state.recoveryStatus = recovery;
          state.recoveryStatusState = "ready";
        }
      }

      const nextSpreads = "spreads" in values ? (Array.isArray(values.spreads) ? values.spreads : []) : null;
      const nextRecoverCloseEligibility = nextSpreads ? await loadRecoverCloseEligibility(nextSpreads) : null;
      if (loadGeneration !== state.accountLoadGeneration || selectedAccountId !== state.selectedAccountId) {
        return { coreHealthy: state.coreDataHealthy, requiredFailures: [], optionalFailures: [], discarded: true };
      }

      for (const kind of ["orders", "executions", "journals"]) {
        if (!(kind in values)) continue;
        try {
          setActivityPage(kind, values[kind]);
        } catch (error) {
          errors[kind] = error?.message || "Paged activity response was invalid.";
          state.activityPages[kind] = { ...emptyActivityPage(), error: errors[kind] };
          if (kind === "orders") state.orders = [];
          if (kind === "executions") state.executions = [];
          if (kind === "journals") state.journals = [];
        }
      }
      if (nextSpreads !== null) {
        state.spreads = nextSpreads;
        state.recoverCloseEligibility = nextRecoverCloseEligibility || {};
      }
      if ("runtime" in values) state.runtime = values.runtime;
      if ("operatorStatus" in values) state.operatorStatus = values.operatorStatus;
      if ("tradingIntents" in values && "tradeActions" in values) {
        const unresolvedStates = new Set(["prepared", "submitting", "broker_acknowledged", "unknown"]);
        state.unresolvedTradingIntents = [
          ...(Array.isArray(values.tradingIntents) ? values.tradingIntents : []),
          ...(Array.isArray(values.tradeActions) ? values.tradeActions : []),
        ].filter((intent) => unresolvedStates.has(intent?.state));
      }
      if ("latestSnapshot" in values) state.latestSnapshot = values.latestSnapshot;
      if ("zeroDteLotteryRuntime" in values) state.zeroDteLotteryRuntime = values.zeroDteLotteryRuntime;
      if ("strategyExperiment" in values) state.strategyExperiment = values.strategyExperiment || { ...EMPTY_EXPERIMENT };
      if ("coveredCallActivity" in values) state.coveredCallActivity = values.coveredCallActivity || { ...EMPTY_COVERED_CALL };
      if ("advisorRuns" in values) state.advisorRuns = Array.isArray(values.advisorRuns) ? values.advisorRuns : [];
      if ("marketEvents" in values) state.marketEvents = Array.isArray(values.marketEvents) ? values.marketEvents : [];
      if ("preOpenRuns" in values) state.preOpenRuns = Array.isArray(values.preOpenRuns) ? values.preOpenRuns : [];

      const requiredFailures = requestSpecs
        .filter(([key, required]) => required && errors[key])
        .map(([key]) => formatPanelLoadLabel?.(key) || key);
      const optionalFailures = requestSpecs
        .filter(([key, required]) => !required && errors[key])
        .map(([key]) => formatPanelLoadLabel?.(key) || key);
      state.coreDataHealthy = state.accountListHealthy && requiredFailures.length === 0;
      state.coreLoadFailures = requiredFailures;
      state.panelLoadErrors = errors;
      state.selectedOrderDetailError = null;

      if ("preOpenRuns" in values) {
        // The page owns the presentation of the latest stored run.
        state.preOpenRuns = Array.isArray(values.preOpenRuns) ? values.preOpenRuns : [];
      }
      if (state.orders.some((order) => order.id === state.selectedOrderId)) {
        state.selectedOrderDetail = state.orders.find((order) => order.id === state.selectedOrderId) || null;
        state.selectedOrderDetailOrderId = state.selectedOrderId;
      } else if (state.selectedOrderId) {
        await ensureSelectedOrderDetail(previousOrder);
      }
      if (!state.selectedOrderId) {
        state.selectedOrderId = state.orders[0]?.id || "";
        state.selectedOrderDetail = state.orders[0] || null;
        state.selectedOrderDetailOrderId = state.selectedOrderId;
      }

      renderAccountState?.({ errors, values, requiredFailures, optionalFailures });
      if ("recoveryStatus" in values && !errors.recoveryStatus) {
        renderRecoveryStatus?.(state.recoveryStatus);
      } else if (errors.recoveryStatus) {
        state.recoveryStatus = null;
        state.recoveryStatusState = "error";
        renderRecoveryError?.(new Error(errors.recoveryStatus));
      }
      updateSyncButtons?.();
      updateOrderTicketAvailability?.();
      updatePreOpenButtons?.();
      applyTradingSafetyState?.();
      return { coreHealthy: state.coreDataHealthy, requiredFailures, optionalFailures, discarded: false };
    }

    async function refreshAccounts() {
      try {
        const accounts = await fetchJson("/broker-accounts");
        state.accountListHealthy = true;
        applyAccounts(accounts);
      } catch (error) {
        state.accountListHealthy = false;
        state.coreDataHealthy = false;
        state.coreLoadFailures = ["Broker accounts"];
        state.recoveryStatus = null;
        state.recoveryStatusState = "error";
        renderRecoveryError?.(error);
        applyTradingSafetyState?.();
        throw error;
      }
    }

    async function refreshAccountsSilently() {
      try {
        await refreshAccounts();
      } catch (error) {
        console.error(error);
      }
    }

    function applyAccounts(accounts) {
      state.accounts = Array.isArray(accounts) ? accounts : [];
      if (!state.selectedAccountId && state.accounts.length > 0) {
        state.selectedAccountId = state.accounts[0].external_account_id;
      } else if (state.accounts.every((account) => account.external_account_id !== state.selectedAccountId)) {
        state.selectedAccountId = state.accounts[0]?.external_account_id || "";
      }
      renderAccountOptions?.();
      updateSyncButtons?.();
      updateOrderTicketAvailability?.();
    }

    return {
      loadAccountData,
      loadActivityPage,
      loadRecoverCloseEligibility,
      ensureSelectedOrderDetail,
      refreshAccounts,
      refreshAccountsSilently,
      applyAccounts,
      normalizePagePayload,
      activityUrl,
      pageSize: ACTIVITY_PAGE_SIZE,
    };
  }

  window.StocksToolAccountLoader = { createAccountLoader };
})();

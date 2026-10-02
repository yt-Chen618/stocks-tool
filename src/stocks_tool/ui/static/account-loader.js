(function () {
  const ACTIVITY_PAGE_SIZE = 25;
  const BULL_PUT_HISTORY_PAGE_SIZE = 25;
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

    function emptyBullPutHistoryPage() {
      return { cursor: null, hasMore: false, loading: false, error: null };
    }

    function currentAccountUnknownLocks(accountId) {
      const locks = state.unknownMutationLocks?.[accountId];
      return Array.isArray(locks) ? locks : [];
    }

    function signatureAccount(value) {
      if (typeof value !== "string") return null;
      try {
        const payload = JSON.parse(value);
        return payload?.external_account_id || payload?.account || payload?.accountId || null;
      } catch (_error) {
        return null;
      }
    }

    function rehydrateUnknownMutationLocks(accountId) {
      state.unknownMutationLocks ||= {};
      const existing = currentAccountUnknownLocks(accountId);
      const byId = new Map(existing.map((lock) => [lock.id, lock]));
      try {
        const prefix = "stocks-tool-idempotency:";
        for (let index = 0; index < Number(window.sessionStorage.length || 0); index += 1) {
          const storageKey = window.sessionStorage.key(index);
          if (!storageKey || !storageKey.startsWith(prefix)) continue;
          const remainder = storageKey.slice(prefix.length);
          const scoped = remainder.startsWith(`${accountId}:`);
          const actionKey = scoped ? remainder.slice(String(accountId).length + 1) : remainder;
          const possibleAccount = remainder.split(":", 1)[0];
          if (!scoped && state.accounts?.some((account) => account.external_account_id === possibleAccount)) continue;
          let record = null;
          try {
            record = JSON.parse(window.sessionStorage.getItem(storageKey) || "null");
          } catch (_error) {
            record = null;
          }
          const recordAccount = record?.accountId || signatureAccount(record?.requestSignature);
          if (scoped && recordAccount && recordAccount !== accountId) continue;
          if (!scoped && recordAccount && recordAccount !== accountId) continue;
          if (!scoped && recordAccount === accountId && record?.key && record?.requestSignature) {
            const migratedKey = `${prefix}${accountId}:${actionKey}`;
            record = { ...record, accountId, mode: record.mode || "paper", actionKey };
            try {
              window.sessionStorage.setItem(migratedKey, JSON.stringify(record));
              window.sessionStorage.removeItem(storageKey);
            } catch (_error) {
              // Keep the legacy record; the in-memory lock below remains fail closed.
            }
          }
          const lockId = typeof record?.intentId === "string" && record.intentId
            ? record.intentId
            : `legacy-idempotency:${storageKey}`;
          byId.set(lockId, {
            id: lockId,
            state: "unknown",
            source: record?.intentId ? "session-rehydrated" : "legacy-idempotency-record",
            external_account_id: accountId,
            mode: record?.mode || "paper",
            action_key: record?.actionKey || actionKey,
            idempotency_key: record?.key || null,
            request_signature: record?.requestSignature || null,
          });
        }
      } catch (_error) {
        // A storage failure cannot authorize a retry; the existing in-memory lock remains.
      }
      state.unknownMutationLocks[accountId] = Array.from(byId.values());
      return currentAccountUnknownLocks(accountId);
    }

    const TERMINAL_UNKNOWN_STATES = new Set(["persisted", "rejected", "resolved_no_order"]);

    async function reconcileUnknownMutationLocks(accountId, loadGeneration) {
      const locks = currentAccountUnknownLocks(accountId);
      if (!locks.length) return { discarded: false, cleared: [] };
      const cleared = [];
      for (const lock of locks) {
        if (!isCurrentScope(accountId, loadGeneration)) return { discarded: true, cleared: [] };
        let terminal = false;
        for (const path of ["/ops/trading-intents", "/ops/trade-actions"]) {
          try {
            const detail = await fetchJson(`${path}/${encodeURIComponent(lock.id)}`);
            if (
              detail?.id === lock.id &&
              detail.external_account_id === accountId &&
              detail.mode === lock.mode &&
              TERMINAL_UNKNOWN_STATES.has(detail.state)
            ) {
              terminal = true;
              break;
            }
            if (detail?.id === lock.id) break;
          } catch (error) {
            if (error?.status !== 404) break;
          }
        }
        if (terminal) cleared.push(lock.id);
        if (terminal && lock.action_key) {
          try {
            window.sessionStorage.removeItem(`stocks-tool-idempotency:${accountId}:${lock.action_key}`);
          } catch (_error) {
            // Preserve the terminal evidence even when browser storage is unavailable.
          }
        }
      }
      if (!isCurrentScope(accountId, loadGeneration)) return { discarded: true, cleared: [] };
      if (cleared.length) {
        state.unknownMutationLocks ||= {};
        state.terminalUnknownMutationIds ||= {};
        const clearedIds = new Set(cleared);
        state.unknownMutationLocks[accountId] = currentAccountUnknownLocks(accountId).filter((lock) => !clearedIds.has(lock.id));
        state.terminalUnknownMutationIds[accountId] = [
          ...(state.terminalUnknownMutationIds[accountId] || []),
          ...cleared,
        ].filter((id, index, ids) => ids.indexOf(id) === index);
      }
      return { discarded: false, cleared };
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

    function isCurrentScope(accountId, loadGeneration) {
      return loadGeneration === state.accountLoadGeneration && accountId === state.selectedAccountId;
    }

    function assertScopedSpread(spread, spreadId, accountId, mode = "paper") {
      if (!spread || typeof spread !== "object" || spread.id !== spreadId) {
        throw new Error("Bull Put spread detail did not match the requested id.");
      }
      if (spread.external_account_id !== accountId || spread.mode !== mode) {
        throw new Error("Bull Put spread did not match the selected paper account.");
      }
      return spread;
    }

    function assertScopedSpreadList(spreads, accountId, mode = "paper") {
      if (!Array.isArray(spreads)) {
        throw new Error("Bull Put working-spreads response did not match the list contract.");
      }
      return spreads.map((spread) => {
        if (!spread || typeof spread !== "object" || spread.external_account_id !== accountId || spread.mode !== mode) {
          throw new Error("Bull Put working-spreads response did not match the selected paper account.");
        }
        return spread;
      });
    }

    function setBullPutHistoryPage(payload, { append = false, accountId = state.selectedAccountId } = {}) {
      const page = normalizePagePayload(payload);
      const scopedItems = page.items.map((spread) => {
        if (!spread || typeof spread !== "object" || !spread.id || spread.external_account_id !== accountId || spread.mode !== "paper") {
          throw new Error("Bull Put history response did not match the selected paper account.");
        }
        return spread;
      });
      const current = Array.isArray(state.bullPutHistory) ? state.bullPutHistory : [];
      const values = append ? [...current, ...scopedItems] : scopedItems;
      const seen = new Set();
      state.bullPutHistory = values.filter((item) => {
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      });
      state.bullPutHistoryPage = {
        cursor: page.cursor,
        hasMore: page.hasMore,
        loading: false,
        error: null,
      };
      return { ...page, items: scopedItems };
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

    function bullPutWorkingUrl(accountId) {
      return `/strategies/bull-put/working-spreads?external_account_id=${encodeURIComponent(accountId)}&mode=paper`;
    }

    function bullPutHistoryUrl(accountId, { cursor = null } = {}) {
      const params = new URLSearchParams({
        external_account_id: accountId,
        mode: "paper",
        limit: String(BULL_PUT_HISTORY_PAGE_SIZE),
      });
      if (cursor) params.set("cursor", cursor);
      return `/strategies/bull-put/spreads/paged?${params.toString()}`;
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
          return { discarded: true };
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

    async function loadWorkingSpreads({ accountId = state.selectedAccountId } = {}) {
      if (!accountId) return { discarded: false, spreads: [] };
      const loadGeneration = state.accountLoadGeneration;
      try {
        const response = await fetchJson(bullPutWorkingUrl(accountId));
        if (!isCurrentScope(accountId, loadGeneration)) {
          return { discarded: true, spreads: [] };
        }
        const spreads = assertScopedSpreadList(response, accountId);
        state.spreads = spreads;
        return { discarded: false, spreads };
      } catch (error) {
        if (!isCurrentScope(accountId, loadGeneration)) {
          return { discarded: true, error };
        }
        throw error;
      }
    }

    async function loadBullPutHistoryPage({ append = false, accountId = state.selectedAccountId } = {}) {
      if (!accountId) {
        return { discarded: false, page: { items: [], cursor: null, hasMore: false, limit: BULL_PUT_HISTORY_PAGE_SIZE } };
      }
      state.bullPutHistoryPage ||= emptyBullPutHistoryPage();
      const pageState = state.bullPutHistoryPage;
      if (pageState.loading) return { discarded: false, skipped: true, page: pageState };
      if (append && !pageState.hasMore) return { discarded: false, skipped: true, page: pageState };
      const loadGeneration = state.accountLoadGeneration;
      const cursor = append ? pageState.cursor : null;
      pageState.loading = true;
      pageState.error = null;
      try {
        const response = await fetchJson(bullPutHistoryUrl(accountId, { cursor }));
        if (!isCurrentScope(accountId, loadGeneration)) {
          return { discarded: true };
        }
        const page = setBullPutHistoryPage(response, { append, accountId });
        return { discarded: false, page };
      } catch (error) {
        if (!isCurrentScope(accountId, loadGeneration)) {
          return { discarded: true, error };
        }
        pageState.loading = false;
        pageState.error = error?.message || "Bull Put history request failed.";
        throw error;
      }
    }

    async function loadSpreadDetail(spreadId, { accountId = state.selectedAccountId } = {}) {
      if (!spreadId || !accountId) return { discarded: false, detail: null };
      state.bullPutHistoryDetails ||= {};
      state.bullPutHistoryDetailLoading ||= {};
      state.bullPutHistoryDetailErrors ||= {};
      state.bullPutHistoryDetailLoading[spreadId] = true;
      delete state.bullPutHistoryDetailErrors[spreadId];
      const loadGeneration = state.accountLoadGeneration;
      try {
        const detail = await fetchJson(
          `/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}?external_account_id=${encodeURIComponent(accountId)}&mode=paper`,
        );
        if (!isCurrentScope(accountId, loadGeneration)) {
          return { discarded: true };
        }
        const scopedDetail = assertScopedSpread(detail, spreadId, accountId);
        state.bullPutHistoryDetails[spreadId] = scopedDetail;
        state.bullPutHistoryDetailLoading[spreadId] = false;
        const currentIndex = state.spreads.findIndex((spread) => spread.id === spreadId);
        if (currentIndex >= 0) state.spreads[currentIndex] = scopedDetail;
        const historyIndex = state.bullPutHistory.findIndex((spread) => spread.id === spreadId);
        if (historyIndex >= 0) state.bullPutHistory[historyIndex] = scopedDetail;
        return { discarded: false, detail: scopedDetail };
      } catch (error) {
        if (!isCurrentScope(accountId, loadGeneration)) {
          return { discarded: true, error };
        }
        state.bullPutHistoryDetailLoading[spreadId] = false;
        state.bullPutHistoryDetailErrors[spreadId] = error?.message || "Bull Put spread detail unavailable.";
        throw error;
      }
    }

    async function loadSpreadEligibility(spreadId, { accountId = state.selectedAccountId } = {}) {
      if (!spreadId || !accountId) return { discarded: false, eligibility: null };
      const loadGeneration = state.accountLoadGeneration;
      try {
        const eligibility = await fetchJson(
          `/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}/recover-close/eligibility?external_account_id=${encodeURIComponent(accountId)}&mode=paper`,
        );
        if (!isCurrentScope(accountId, loadGeneration)) {
          return { discarded: true };
        }
        if (
          !eligibility ||
          eligibility.spread_id !== spreadId ||
          eligibility.external_account_id !== accountId ||
          eligibility.mode !== "paper"
        ) {
          throw new Error("Recovery eligibility did not match the selected paper account.");
        }
        state.recoverCloseEligibility[spreadId] = eligibility;
        return { discarded: false, eligibility };
      } catch (error) {
        if (!isCurrentScope(accountId, loadGeneration)) {
          return { discarded: true, error };
        }
        state.recoverCloseEligibility[spreadId] = {
          spread_id: spreadId,
          eligible: false,
          reasons: ["eligibility_unavailable"],
          external_account_id: accountId,
          mode: "paper",
          error: error?.message || "Recovery eligibility unavailable.",
        };
        throw error;
      }
    }

    async function refreshSpread(spreadId, { accountId = state.selectedAccountId } = {}) {
      const loadGeneration = state.accountLoadGeneration;
      const response = await fetchJson(`/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}/refresh`, { method: "POST" });
      if (!isCurrentScope(accountId, loadGeneration)) return { discarded: true, detail: response };
      const detail = assertScopedSpread(response, spreadId, accountId);
      state.bullPutHistoryDetails ||= {};
      state.bullPutHistoryDetails[spreadId] = detail;
      return { discarded: false, detail };
    }

    async function monitorSpread(spreadId, idempotencyKey, { accountId = state.selectedAccountId } = {}) {
      const loadGeneration = state.accountLoadGeneration;
      const result = await fetchJson(`/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}/monitor`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        timeoutMs: 25000,
      });
      if (!isCurrentScope(accountId, loadGeneration)) return { discarded: true, result };
      if (result?.spread) assertScopedSpread(result.spread, spreadId, accountId);
      return { discarded: false, result };
    }

    async function recoverCloseSpread(spreadId, payload, idempotencyKey, { accountId = state.selectedAccountId } = {}) {
      const loadGeneration = state.accountLoadGeneration;
      const result = await fetchJson(`/strategies/bull-put/spreads/${encodeURIComponent(spreadId)}/recover-close`, {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload),
        timeoutMs: 25000,
      });
      if (!isCurrentScope(accountId, loadGeneration)) return { discarded: true, result };
      const detail = assertScopedSpread(result, spreadId, accountId);
      state.bullPutHistoryDetails ||= {};
      state.bullPutHistoryDetails[spreadId] = detail;
      return { discarded: false, detail };
    }

    const selectedOrderDetailRequestCache = new Map();

    function selectedOrderDetailCacheKey(accountId, loadGeneration, orderId) {
      return `${accountId}::${loadGeneration}::${orderId}`;
    }

    async function loadSelectedOrderDetails(orderId, { accountId = state.selectedAccountId, previousOrder = null } = {}) {
      if (!orderId || !accountId) return { discarded: false, order: null, failures: [] };
      const loadGeneration = state.accountLoadGeneration;
      const cacheKey = selectedOrderDetailCacheKey(accountId, loadGeneration, orderId);
      let request = selectedOrderDetailRequestCache.get(cacheKey);
      if (!request) {
        request = (async () => {
          const results = await Promise.allSettled([
            fetchJson(`/orders/${encodeURIComponent(orderId)}`),
            fetchJson(`/executions/paged?external_account_id=${encodeURIComponent(accountId)}&order_id=${encodeURIComponent(orderId)}&limit=${ACTIVITY_PAGE_SIZE}`),
            fetchJson(`/journals/paged?external_account_id=${encodeURIComponent(accountId)}&order_id=${encodeURIComponent(orderId)}&limit=${ACTIVITY_PAGE_SIZE}`),
          ]);
          const failures = [];
          let order = null;
          let executionsPage = null;
          let journalsPage = null;
          const [orderResult, executionsResult, journalsResult] = results;
          if (orderResult.status === "fulfilled") {
            const detail = orderResult.value;
            if (detail?.id === orderId && detail.external_account_id === accountId) {
              order = detail;
            } else {
              failures.push("order");
            }
          } else {
            failures.push("order");
          }
          if (executionsResult.status === "fulfilled") {
            try {
              executionsPage = normalizePagePayload(executionsResult.value);
            } catch (_error) {
              failures.push("executions");
            }
          } else {
            failures.push("executions");
          }
          if (journalsResult.status === "fulfilled") {
            try {
              journalsPage = normalizePagePayload(journalsResult.value);
            } catch (_error) {
              failures.push("journals");
            }
          } else {
            failures.push("journals");
          }
          return { order, executionsPage, journalsPage, failures };
        })();
        selectedOrderDetailRequestCache.set(cacheKey, request);
      }
      state.selectedOrderDetailLoading = true;
      state.selectedOrderDetailError = null;
      const result = await request;
      if (!isCurrentScope(accountId, loadGeneration) || orderId !== state.selectedOrderId) {
        return { ...result, discarded: true };
      }
      let order = result.order;
      if (!order && previousOrder?.id === orderId && previousOrder.external_account_id === accountId) {
        order = previousOrder;
      }
      if (order) {
        state.selectedOrderDetail = order;
        const rowIndex = state.orders.findIndex((candidate) => candidate.id === orderId);
        if (rowIndex >= 0) state.orders[rowIndex] = order;
      }
      if (result.executionsPage) {
        state.selectedOrderExecutions = result.executionsPage.items;
        state.selectedOrderExecutionPage = { cursor: result.executionsPage.cursor, hasMore: result.executionsPage.hasMore, loading: false };
      }
      if (result.journalsPage) {
        state.selectedOrderJournals = result.journalsPage.items;
        state.selectedOrderJournalPage = { cursor: result.journalsPage.cursor, hasMore: result.journalsPage.hasMore, loading: false };
      }
      state.selectedOrderDetailOrderId = orderId;
      state.selectedOrderDetailLoading = false;
      state.selectedOrderDetailError = result.failures.length ? `Detail unavailable: ${result.failures.join(", ")}.` : null;
      return { ...result, discarded: false, order };
    }

    async function ensureSelectedOrderDetail(previousOrder = null) {
      const selectedId = state.selectedOrderId;
      const accountId = state.selectedAccountId;
      if (!selectedId) {
        return null;
      }
      const existing = state.orders.find((order) => order.id === selectedId);
      if (existing) {
        return existing;
      }
      const result = await loadSelectedOrderDetails(selectedId, { accountId, previousOrder });
      return result?.order || null;
    }

    function resetSelectedAccountState() {
      state.accountContextId = "";
      state.orders = [];
      state.spreads = [];
      state.bullPutHistory = [];
      state.bullPutHistoryPage = emptyBullPutHistoryPage();
      state.bullPutHistoryDetails = {};
      state.bullPutHistoryDetailLoading = {};
      state.bullPutHistoryDetailErrors = {};
      state.recoverCloseEligibility = {};
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
      state.selectedOrderExecutions = [];
      state.selectedOrderJournals = [];
      state.selectedOrderExecutionPage = { cursor: null, hasMore: false, loading: false };
      state.selectedOrderJournalPage = { cursor: null, hasMore: false, loading: false };
      state.preOpenAssessment = null;
      state.preOpenStatus = createOverlayStatus("idle", "Select a broker account to load the macro board on demand.");
      state.activityPages = {
        orders: emptyActivityPage(),
        executions: emptyActivityPage(),
        journals: emptyActivityPage(),
      };
      state.selectedOrderDetailLoading = false;
      state.bullPutHistoryPage = emptyBullPutHistoryPage();
      state.bullPutHistory = [];
      state.bullPutHistoryDetails = {};
      state.bullPutHistoryDetailLoading = {};
      state.bullPutHistoryDetailErrors = {};
      state.bullPutLastActionDetail = null;
      state.advisorStatus = createOverlayStatus(
        "idle",
        "Select a broker account before loading advisor context.",
      );
      renderEmptyState?.();
      renderRecoveryStatus?.(null);
    }

    function mergeSettledResults(requestSpecs, settled, values, errors) {
      settled.forEach((result, index) => {
        const [key] = requestSpecs[index];
        if (result.status === "fulfilled") {
          values[key] = result.value;
        } else {
          console.error(result.reason);
          errors[key] = result.reason?.message || "Request failed.";
        }
      });
    }

    function applyLoadedValues(values, errors, selectedAccountId) {
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
      if ("workingSpreads" in values) {
        try {
          state.spreads = assertScopedSpreadList(values.workingSpreads, selectedAccountId);
        } catch (error) {
          errors.workingSpreads = error?.message || "Working Bull Put response was invalid.";
          state.spreads = [];
        }
      }
      if ("spreadHistory" in values) {
        try {
          setBullPutHistoryPage(values.spreadHistory, { accountId: selectedAccountId });
        } catch (error) {
          errors.spreadHistory = error?.message || "Bull Put history response was invalid.";
          state.bullPutHistory = [];
          state.bullPutHistoryPage = { ...emptyBullPutHistoryPage(), error: errors.spreadHistory };
        }
      }
      if ("runtime" in values) state.runtime = values.runtime;
      if ("operatorStatus" in values) state.operatorStatus = values.operatorStatus;
      if ("tradingIntents" in values && "tradeActions" in values) {
        const unresolvedStates = new Set(["prepared", "submitting", "broker_acknowledged", "unknown"]);
        const backendUnresolved = [
          ...(Array.isArray(values.tradingIntents) ? values.tradingIntents : []),
          ...(Array.isArray(values.tradeActions) ? values.tradeActions : []),
        ].filter((intent) => unresolvedStates.has(intent?.state));
        const terminalIds = new Set(state.terminalUnknownMutationIds?.[selectedAccountId] || []);
        const localUnknown = currentAccountUnknownLocks(selectedAccountId);
        state.unresolvedTradingIntents = [
          ...localUnknown,
          ...backendUnresolved.filter((intent) => !terminalIds.has(intent.id) && !localUnknown.some((candidate) => candidate.id === intent.id)),
        ];
      }
      if ("latestSnapshot" in values) state.latestSnapshot = values.latestSnapshot;
      if ("zeroDteLotteryRuntime" in values) state.zeroDteLotteryRuntime = values.zeroDteLotteryRuntime;
      if ("strategyExperiment" in values) state.strategyExperiment = values.strategyExperiment || { ...EMPTY_EXPERIMENT };
      if ("coveredCallActivity" in values) state.coveredCallActivity = values.coveredCallActivity || { ...EMPTY_COVERED_CALL };
      if ("advisorRuns" in values) state.advisorRuns = Array.isArray(values.advisorRuns) ? values.advisorRuns : [];
      if ("marketEvents" in values) state.marketEvents = Array.isArray(values.marketEvents) ? values.marketEvents : [];
      if ("preOpenRuns" in values) state.preOpenRuns = Array.isArray(values.preOpenRuns) ? values.preOpenRuns : [];
    }

    function loadFailures(requestSpecs, errors, required) {
      return requestSpecs
        .filter(([, isRequired]) => isRequired === required)
        .map(([key]) => errors[key] ? formatPanelLoadLabel?.(key) || key : null)
        .filter(Boolean);
    }

    async function loadAccountData() {
      const loadGeneration = ++state.accountLoadGeneration;
      const selectedAccountId = state.selectedAccountId;
      selectedOrderDetailRequestCache.clear();
      const accountChanged = Boolean(state.accountContextId && state.accountContextId !== selectedAccountId);
      if (accountChanged) {
        state.selectedOrderId = "";
        state.selectedOrderDetailOrderId = "";
        state.selectedOrderDetail = null;
        state.selectedOrderDetailError = null;
        state.orders = [];
        state.runtime = null;
        state.latestSnapshot = null;
        state.operatorStatus = null;
        state.strategyExperiment = { ...EMPTY_EXPERIMENT };
        state.coveredCallActivity = { ...EMPTY_COVERED_CALL };
        state.advisorRuns = [];
        state.marketEvents = [];
        state.executions = [];
        state.journals = [];
        state.preOpenRuns = [];
        state.zeroDteLotteryRuntime = null;
      }
      state.accountContextId = selectedAccountId;
      rehydrateUnknownMutationLocks(selectedAccountId);
      const previousOrder = state.orders.find((order) => order.id === state.selectedOrderId) || null;
      state.activityPages = {
        orders: emptyActivityPage(),
        executions: emptyActivityPage(),
        journals: emptyActivityPage(),
      };
      if (accountChanged) state.spreads = [];
      state.recoverCloseEligibility = {};
      state.unresolvedTradingIntents = [];
      if (state.bullPutLastActionDetail?.accountId !== selectedAccountId) {
        state.bullPutLastActionDetail = null;
      }
      state.bullPutHistory = [];
      state.bullPutHistoryPage = emptyBullPutHistoryPage();
      state.bullPutHistoryDetails = {};
      state.bullPutHistoryDetailLoading = {};
      state.bullPutHistoryDetailErrors = {};
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
        ["workingSpreads", true, bullPutWorkingUrl(selectedAccountId)],
        ["runtime", true, `/strategies/bull-put/runtime?external_account_id=${accountId}`],
        ["operatorStatus", true, `/ops/unattended-status?external_account_id=${accountId}&mode=paper`],
        ["recoveryStatus", true, `/ops/recovery-status?external_account_id=${accountId}&mode=paper&limit=100`],
        ["tradingIntents", true, `/ops/trading-intents?external_account_id=${accountId}&mode=paper&limit=100`],
        ["tradeActions", true, `/ops/trade-actions?external_account_id=${accountId}&mode=paper&limit=100`],
        ["zeroDteLotteryRuntime", false, `/strategies/zero-dte-lottery/runtime?external_account_id=${accountId}&mode=paper`],
        ["strategyExperiment", true, `/strategies/experiment?external_account_id=${accountId}&limit=6`],
        ["coveredCallActivity", true, `/strategies/covered-call/activity?external_account_id=${accountId}&mode=paper&limit=8`],
        ["advisorRuns", false, `/strategies/advisor/run-cards?external_account_id=${accountId}&source=deepseek&limit=5`],
        ["marketEvents", false, "/market-events?limit=8"],
        ["executions", false, activityUrl("executions", selectedAccountId)],
        ["journals", false, activityUrl("journals", selectedAccountId)],
        ["preOpenRuns", false, `/strategies/pre-open-runs?external_account_id=${accountId}&limit=1`],
      ];
      const requiredSpecs = requestSpecs.filter(([, required]) => required);
      const optionalSpecs = requestSpecs.filter(([, required]) => !required);
      const requiredPromise = Promise.allSettled(requiredSpecs.map(([, , url]) => fetchJson(url)));
      const optionalPromise = Promise.allSettled(optionalSpecs.map(([, , url]) => fetchJson(url)));
      const unknownCleanupPromise = reconcileUnknownMutationLocks(selectedAccountId, loadGeneration);
      const values = {};
      const errors = {};

      const applyStage = async (specs, settled) => {
        if (loadGeneration !== state.accountLoadGeneration || selectedAccountId !== state.selectedAccountId) {
          return { discarded: true };
        }
        mergeSettledResults(specs, settled, values, errors);
        applyLoadedValues(values, errors, selectedAccountId);
        const requiredFailures = loadFailures(requestSpecs, errors, true);
        const optionalFailures = loadFailures(requestSpecs, errors, false);
        state.coreDataHealthy = state.accountListHealthy && requiredFailures.length === 0;
        state.coreLoadFailures = requiredFailures;
        state.panelLoadErrors = { ...errors };
        state.selectedOrderDetailError = null;
        if (state.orders.some((order) => order.id === state.selectedOrderId)) {
          state.selectedOrderDetail = state.orders.find((order) => order.id === state.selectedOrderId) || null;
          state.selectedOrderDetailOrderId = state.selectedOrderId;
          state.selectedOrderDetailLoading = false;
        } else if (state.selectedOrderId) {
          await ensureSelectedOrderDetail(previousOrder);
        }
        if (!state.selectedOrderId) {
          state.selectedOrderId = state.orders[0]?.id || "";
          state.selectedOrderDetail = state.orders[0] || null;
          state.selectedOrderDetailOrderId = state.selectedOrderId;
          state.selectedOrderDetailLoading = false;
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
        return { discarded: false, coreHealthy: state.coreDataHealthy, requiredFailures, optionalFailures };
      };

      const requiredSettled = await requiredPromise;
      const requiredResult = await applyStage(requiredSpecs, requiredSettled);
      if (requiredResult.discarded) {
        return { coreHealthy: state.coreDataHealthy, requiredFailures: [], optionalFailures: [], discarded: true };
      }
      const unknownCleanup = await unknownCleanupPromise;
      if (unknownCleanup.discarded) {
        return { coreHealthy: state.coreDataHealthy, requiredFailures: [], optionalFailures: [], discarded: true };
      }
      if (unknownCleanup.cleared.length) {
        const cleanupRender = await applyStage([], []);
        if (cleanupRender.discarded) {
          return { coreHealthy: state.coreDataHealthy, requiredFailures: [], optionalFailures: [], discarded: true };
        }
      }
      const optionalSettled = await optionalPromise;
      const finalResult = await applyStage(optionalSpecs, optionalSettled);
      if (finalResult.discarded) {
        return { coreHealthy: state.coreDataHealthy, requiredFailures: [], optionalFailures: [], discarded: true };
      }
      return finalResult;
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
      loadWorkingSpreads,
      loadBullPutHistoryPage,
      loadSpreadDetail,
      loadSpreadEligibility,
      loadSelectedOrderDetails,
      reconcileUnknownMutationLocks,
      rehydrateUnknownMutationLocks,
      refreshSpread,
      monitorSpread,
      recoverCloseSpread,
      ensureSelectedOrderDetail,
      refreshAccounts,
      refreshAccountsSilently,
      applyAccounts,
      normalizePagePayload,
      activityUrl,
      bullPutWorkingUrl,
      bullPutHistoryUrl,
      pageSize: ACTIVITY_PAGE_SIZE,
    };
  }

  window.StocksToolAccountLoader = { createAccountLoader };
})();

(function () {
  const PAGE_SIZE = 25;

  function createOrdersView({
    state,
    els,
    fetchJson,
    decodeCursorPage,
    reloadAccountData,
    loadActivityPage,
    loadSelectedOrderDetails,
    ensureSelectedOrderDetail,
    runConfirmedBrokerMutation,
    setStatus,
    setActionStatus,
    applyTradingSafetyState,
    setBusinessDisabled,
    matchingQuoteTime,
    escapeHtml,
    formatMultilineText,
    formatters,
    parsePositiveInteger,
    parsePositiveNumber,
    normalizeOptionalText,
    parseTags,
    workspace,
  }) {
    const formatter = formatters || window.StocksToolFormatters || {};
    const formatCurrency = formatter.formatCurrency || ((value) => String(value ?? "--"));
    const formatNumber = formatter.formatNumber || ((value) => String(value ?? "--"));
    const formatDateTime = formatter.formatDateTime || ((value) => String(value ?? "--"));
    const formatPositionQuantity = formatter.formatPositionQuantity || ((value) => String(value ?? "--"));
    const journalEntryTone = formatter.journalEntryTone || (() => "neutral");
    const statusClass = formatter.statusClass || (() => "neutral");
    let detailGeneration = 0;

    function objectPayload(value) {
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }

    function normalizePagePayload(payload) {
      if (typeof decodeCursorPage !== "function") {
        throw new Error("CursorPage decoder is unavailable.");
      }
      const page = decodeCursorPage(payload);
      return { items: page.items, cursor: page.cursor, hasMore: page.hasMore };
    }

    function selectedOrder() {
      return state.orders.find((order) => order.id === state.selectedOrderId)
        || (state.selectedOrderDetail?.id === state.selectedOrderId ? state.selectedOrderDetail : null);
    }

    function selectedExecution() {
      const selected = state.selectedOrderExecutions?.find((execution) => execution.order_id === state.selectedOrderId);
      return selected || state.executions.find((execution) => execution.order_id === state.selectedOrderId) || null;
    }

    function selectedJournalEntries() {
      const order = selectedOrder();
      if (!order) return [];
      const entries = state.selectedOrderDetailOrderId === order.id
        ? (state.selectedOrderJournals || [])
        : (state.journals || []);
      return entries.filter((entry) => entry.order_id === order.id || (order.trade_plan_id && entry.trade_plan_id === order.trade_plan_id));
    }

    async function loadSelectedDetails(orderId) {
      const accountId = state.selectedAccountId;
      if (!orderId || !accountId) return { discarded: false };
      const generation = ++detailGeneration;
      state.selectedOrderDetailLoading = true;
      state.selectedOrderDetailError = null;
      renderSelectedOrder();
      const result = await loadSelectedOrderDetails(orderId);
      if (generation !== detailGeneration || result?.discarded) return { discarded: true };
      renderOrders();
      renderSelectedOrder();
      return { discarded: false, failures: result?.failures || [] };
    }

    async function loadMoreOrders() {
      const page = state.activityPages?.orders;
      if (!page?.hasMore || page.loading) return;
      try {
        await loadActivityPage("orders", { append: true });
        renderOrders();
      } catch (error) {
        setStatus(error.message || "More orders could not be loaded.", "error");
        renderOrders();
      }
    }

    async function loadMoreSelectedActivity(kind) {
      const order = selectedOrder();
      if (!order) return;
      const accountId = order.external_account_id;
      const selectedId = order.id;
      const accountLoadGeneration = state.accountLoadGeneration;
      const pageKey = kind === "executions" ? "selectedOrderExecutionPage" : "selectedOrderJournalPage";
      const page = state[pageKey] || {};
      if (!page.hasMore || page.loading) return;
      page.loading = true;
      try {
        const endpoint = kind === "executions" ? "/executions/paged" : "/journals/paged";
        const params = new URLSearchParams({
          external_account_id: order.external_account_id,
          order_id: order.id,
          limit: String(PAGE_SIZE),
        });
        if (page.cursor) params.set("cursor", page.cursor);
        const response = await fetchJson(`${endpoint}?${params.toString()}`);
        const next = normalizePagePayload(response);
        if (state.selectedAccountId !== accountId || state.selectedOrderId !== selectedId || state.accountLoadGeneration !== accountLoadGeneration) {
          return;
        }
        const targetKey = kind === "executions" ? "selectedOrderExecutions" : "selectedOrderJournals";
        state[targetKey] = [...(state[targetKey] || []), ...next.items].filter((item, index, values) => values.findIndex((candidate) => candidate.id === item.id) === index);
        state[pageKey] = { cursor: next.cursor, hasMore: next.hasMore, loading: false };
        renderSelectedOrder();
      } catch (error) {
        if (state.selectedAccountId !== accountId || state.selectedOrderId !== selectedId || state.accountLoadGeneration !== accountLoadGeneration) return { discarded: true, error };
        page.loading = false;
        setStatus(error.message || `More ${kind} could not be loaded.`, "error");
        renderSelectedOrder();
      }
    }

    function renderOrders() {
      if (!els.ordersBody) return;
      const orders = Array.isArray(state.orders) ? state.orders : [];
      if (!orders.length) {
        els.ordersBody.innerHTML = '<tr><td colspan="7" class="empty-row">No orders for this account.</td></tr>';
      } else {
        els.ordersBody.innerHTML = orders.map((order) => {
          const selectedClass = order.id === state.selectedOrderId ? "is-selected" : "";
          const canCancel = isCancelableOrder(order);
          return `
            <tr class="${selectedClass}">
              <td><div class="symbol-cell"><strong>${escapeHtml(order.symbol)}</strong><span>${escapeHtml(String(order.order_type || "").toUpperCase())} / ${escapeHtml(String(order.time_in_force || "").toUpperCase())}</span></div></td>
              <td>${escapeHtml(String(order.side || "").toUpperCase())}</td>
              <td>${escapeHtml(String(order.quantity))}</td>
              <td><span class="pill ${statusClass(order.status)}">${escapeHtml(order.status)}</span></td>
              <td>${escapeHtml(formatOrderPrice(order))}</td>
              <td>${escapeHtml(formatDateTime(order.updated_at))}</td>
              <td><div class="table-actions"><button class="table-action" type="button" data-order-action="manage" data-order-id="${escapeHtml(order.id)}">Manage</button><button class="table-action" type="button" data-order-action="refresh" data-order-id="${escapeHtml(order.id)}">Refresh</button>${canCancel ? `<button class="table-action" type="button" data-order-action="cancel" data-order-id="${escapeHtml(order.id)}" data-broker-mutation="true" data-action-key="order-cancel:${escapeHtml(order.id)}">Cancel</button>` : ""}</div></td>
            </tr>
          `;
        }).join("");
      }
      const loadMore = els.ordersLoadMore;
      if (loadMore) {
        const page = state.activityPages?.orders || {};
        loadMore.hidden = !page.hasMore;
        loadMore.disabled = Boolean(page.loading);
        loadMore.textContent = page.loading ? "Loading…" : "Load more orders";
        loadMore.setAttribute("aria-busy", String(Boolean(page.loading)));
      }
      applyTradingSafetyState?.();
    }

    function renderSelectedOrder() {
      const order = selectedOrder();
      if (!order) {
        els.selectedOrderCard.className = "selected-order empty";
        els.selectedOrderCard.textContent = state.selectedOrderDetailLoading ? "Loading selected order…" : "Select an order from the table to manage it.";
        renderSelectedExecution();
        renderSelectedJournal();
        hideReplaceForm();
        applyTradingSafetyState?.();
        return;
      }
      const canReplace = isReplaceableOrder(order);
      const canCancel = isCancelableOrder(order);
      els.selectedOrderCard.className = "selected-order";
      els.selectedOrderCard.innerHTML = `
        <div class="selected-order-head"><div><span class="section-kicker">Selected Order</span><h3 class="selected-order-title">${escapeHtml(order.symbol)} ${escapeHtml(String(order.side || "").toUpperCase())} x ${escapeHtml(String(order.quantity))}</h3></div><span class="pill ${statusClass(order.status)}">${escapeHtml(order.status)}</span></div>
        <div class="selected-order-meta"><div><span>External ID</span><strong>${escapeHtml(order.external_order_id || "--")}</strong></div><div><span>Account</span><strong>${escapeHtml(order.external_account_id)}</strong></div><div><span>Order Type</span><strong>${escapeHtml(String(order.order_type || "").toUpperCase())}</strong></div><div><span>Time In Force</span><strong>${escapeHtml(String(order.time_in_force || "").toUpperCase())}</strong></div><div><span>Price Logic</span><strong>${escapeHtml(formatOrderPrice(order))}</strong></div><div><span>Updated</span><strong>${escapeHtml(formatDateTime(order.updated_at))}</strong></div></div>
        <div class="selected-order-actions"><button class="icon-button" type="button" data-selected-action="refresh">Refresh</button>${canCancel ? `<button class="icon-button" type="button" data-selected-action="cancel" data-broker-mutation="true" data-action-key="order-cancel:${escapeHtml(order.id)}">Cancel</button>` : ""}</div>
        ${canReplace ? "" : '<p class="form-hint">Filled, canceled, and rejected orders can be refreshed but not replaced.</p>'}
        ${state.selectedOrderDetailLoading ? '<p class="form-hint">Loading order detail, fills, and journal entries…</p>' : ""}
        ${state.selectedOrderDetailError ? `<p class="form-hint error">${escapeHtml(state.selectedOrderDetailError)}</p>` : ""}
      `;
      if (canReplace) populateReplaceForm(order); else hideReplaceForm();
      renderSelectedExecution();
      renderSelectedJournal();
      applyTradingSafetyState?.();
    }

    function setSelectedOrder(orderId, shouldScroll = false) {
      if (!orderId) return;
      state.selectedOrderId = orderId;
      state.selectedOrderDetailOrderId = "";
      state.selectedOrderExecutions = [];
      state.selectedOrderJournals = [];
      state.selectedOrderExecutionPage = { cursor: null, hasMore: false, loading: false };
      state.selectedOrderJournalPage = { cursor: null, hasMore: false, loading: false };
      renderOrders();
      renderSelectedOrder();
      void loadSelectedDetails(orderId);
      if (shouldScroll) {
        workspace?.openExecutionDrawer({ tab: "detail" });
        window.requestAnimationFrame(() => {
          els.selectedOrderCard.scrollIntoView({ behavior: "auto", block: "nearest" });
          els.selectedOrderCard.focus({ preventScroll: true });
        });
      }
    }

    function renderSelectedExecution() {
      const execution = selectedExecution();
      if (!execution) {
        els.selectedOrderExecution.className = "selected-order-execution empty";
        els.selectedOrderExecution.textContent = state.selectedOrderDetailLoading ? "Loading fills…" : "No fills recorded for this order yet.";
      } else {
        els.selectedOrderExecution.className = "selected-order-execution";
        els.selectedOrderExecution.innerHTML = `<div class="execution-grid"><div><span>Filled Qty</span><strong>${escapeHtml(formatPositionQuantity(execution.quantity))}</strong></div><div><span>Avg Fill</span><strong>${escapeHtml(formatCurrency(execution.price))}</strong></div><div><span>Last Fill</span><strong>${escapeHtml(formatDateTime(execution.executed_at))}</strong></div></div><p class="form-hint">Derived from the latest broker order detail snapshot for this order.</p>`;
      }
      if (els.executionsLoadMore) {
        const page = state.selectedOrderExecutionPage || {};
        els.executionsLoadMore.hidden = !page.hasMore;
        els.executionsLoadMore.disabled = Boolean(page.loading);
      }
    }

    function renderSelectedJournal() {
      const order = selectedOrder();
      if (!order) {
        updateJournalFormAvailability(false);
        els.journalFormHint.textContent = "Select an order to save a plan note or post-trade review.";
        els.selectedOrderJournal.className = "selected-order-journal empty";
        els.selectedOrderJournal.textContent = "Select an order to load journal entries.";
        return;
      }
      updateJournalFormAvailability(true);
      const execution = selectedExecution();
      const entries = selectedJournalEntries();
      const context = [];
      if (order.trade_plan_id) context.push("trade plan context");
      if (execution) context.push("latest fill context");
      els.journalFormHint.textContent = context.length ? `New entries will attach ${context.join(" and ")} for ${order.symbol}.` : `New entries will attach to ${order.symbol} on ${order.external_account_id}.`;
      if (!entries.length) {
        els.selectedOrderJournal.className = "selected-order-journal empty";
        els.selectedOrderJournal.textContent = state.selectedOrderDetailLoading ? "Loading journal entries…" : "No journal entries linked to this order yet.";
      } else {
        els.selectedOrderJournal.className = "selected-order-journal";
        els.selectedOrderJournal.innerHTML = entries.map((entry) => {
          const linkMeta = [];
          if (entry.trade_plan_id) linkMeta.push("Plan linked");
          if (entry.execution_id) linkMeta.push("Execution linked");
          const tags = entry.tags?.length ? `<div class="journal-entry-tags">${entry.tags.map((tag) => `<span class="journal-tag">${escapeHtml(tag)}</span>`).join("")}</div>` : "";
          return `<article class="journal-entry-card"><div class="journal-entry-head"><div class="journal-entry-title-block"><span class="pill ${journalEntryTone(entry.entry_type)}">${escapeHtml(entry.entry_type)}</span><strong>${escapeHtml(entry.title)}</strong></div><span class="journal-entry-time">${escapeHtml(formatDateTime(entry.updated_at))}</span></div><div class="journal-entry-meta"><span>${escapeHtml(linkMeta.join(" / ") || "Order linked")}</span><span>${escapeHtml(entry.symbol)}</span></div><p class="journal-entry-notes">${formatMultilineText(entry.notes)}</p>${tags}</article>`;
        }).join("");
      }
      if (els.journalsLoadMore) {
        const page = state.selectedOrderJournalPage || {};
        els.journalsLoadMore.hidden = !page.hasMore;
        els.journalsLoadMore.disabled = Boolean(page.loading);
      }
    }

    function updateJournalFormAvailability(enabled) {
      for (const element of [els.journalEntryType, els.journalTitle, els.journalTags, els.journalNotes, els.submitJournal]) {
        if (element) element.disabled = !enabled;
      }
      if (els.submitJournal) els.submitJournal.title = enabled ? "" : "Select an order first.";
    }

    function populateReplaceForm(order) {
      els.replaceOrderForm.dataset.orderId = order.id;
      els.replaceQuantity.value = String(order.quantity);
      els.replaceLimitPrice.value = order.limit_price ?? "";
      els.replaceStopPrice.value = order.stop_price ?? "";
      els.replaceRemark.value = "";
      syncReplaceOrderFields(order.order_type);
      if (els.replaceSubmit) {
        els.replaceSubmit.dataset.actionKey = `order-replace:${order.id}`;
        setBusinessDisabled?.(els.replaceSubmit, false, "");
      }
      els.replaceOrderForm.classList.remove("hidden");
      applyTradingSafetyState?.();
    }

    function hideReplaceForm() {
      els.replaceOrderForm.dataset.orderId = "";
      els.replaceOrderForm.classList.add("hidden");
    }

    function updateOrderTicketAvailability() {
      const hasAccount = Boolean(state.selectedAccountId);
      setBusinessDisabled?.(els.submitOrder, !hasAccount, hasAccount ? "" : "Select a broker account first.");
      applyTradingSafetyState?.();
    }

    async function reloadAccountForMutation(accountId) {
      const reloadPromise = reloadAccountData();
      const reloadGeneration = state.accountLoadGeneration;
      try {
        const result = await reloadPromise;
        return {
          discarded: Boolean(result?.discarded) || state.selectedAccountId !== accountId || state.accountLoadGeneration !== reloadGeneration,
        };
      } catch (error) {
        if (state.selectedAccountId !== accountId || state.accountLoadGeneration !== reloadGeneration) {
          return { discarded: true, error };
        }
        throw error;
      }
    }

    async function submitOrder(button = els.submitOrder) {
      if (!state.selectedAccountId) {
        setStatus("Select a broker account before submitting an order.", "warning");
        return;
      }
      const accountId = state.selectedAccountId;
      const accountLoadGeneration = state.accountLoadGeneration;
      try {
        const payload = buildCreateOrderPayload();
        const price = payload.limit_price ? `Limit ${formatCurrency(payload.limit_price, "USD")}` : payload.stop_price ? `Stop ${formatCurrency(payload.stop_price, "USD")}` : "Market / unbounded";
        const boundedNotional = payload.side === "buy" && payload.limit_price ? formatCurrency(Number(payload.quantity) * Number(payload.limit_price), "USD") : "Not bounded in ticket";
        const mutation = await runConfirmedBrokerMutation({
          actionKey: "order-submit", button, requestSignature: JSON.stringify(payload), getRequestSignature: () => JSON.stringify(payload), statusElement: els.orderActionStatus,
          confirmation: { title: "Confirm paper order", summary: `${payload.side.toUpperCase()} ${payload.quantity} ${payload.symbol}`, details: { Account: accountId, Mode: "Paper", Symbol: payload.symbol, Side: payload.side.toUpperCase(), Quantity: String(payload.quantity), Price: price, "Max Risk": boundedNotional, "Quote Time": matchingQuoteTime(payload.symbol) } },
        }, async (idempotencyKey) => {
          setStatus(`Submitting ${payload.side.toUpperCase()} ${payload.symbol}...`, "warning");
          return fetchJson("/orders/submit", { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(payload), timeoutMs: 25000 });
        });
        if (!mutation.executed) return;
        const created = mutation.result;
        if (state.selectedAccountId !== accountId || state.accountLoadGeneration !== accountLoadGeneration) return { discarded: true };
        state.selectedOrderId = created.id;
        els.orderRemark.value = "";
        const reload = await reloadAccountForMutation(accountId);
        if (reload.discarded) return reload;
        setSelectedOrder(created.id);
        setActionStatus(els.orderActionStatus, `Order submitted for ${created.symbol}.`, "success");
        setStatus(`Order submitted for ${created.symbol}.`, "success");
      } catch (error) {
        if (state.selectedAccountId !== accountId) return { discarded: true, error };
        console.error(error);
        setActionStatus(els.orderActionStatus, error.message || "Order submission failed.", "error");
        setStatus(error.message || "Order submission failed.", "error");
      }
    }

    async function refreshOrder(orderId) {
      const order = selectedOrder() || state.orders.find((item) => item.id === orderId);
      const accountId = state.selectedAccountId;
      const accountLoadGeneration = state.accountLoadGeneration;
      setStatus(`Refreshing order ${order?.symbol || orderId}...`, "warning");
      try {
        const refreshed = await fetchJson(`/orders/${encodeURIComponent(orderId)}/refresh`, { method: "POST" });
        if (state.selectedAccountId !== accountId || state.accountLoadGeneration !== accountLoadGeneration) return { discarded: true };
        state.selectedOrderId = refreshed.id;
        const reload = await reloadAccountForMutation(accountId);
        if (reload.discarded) return reload;
        setSelectedOrder(refreshed.id);
        setStatus(`Order ${refreshed.symbol} refreshed.`, "success");
      } catch (error) {
        if (state.selectedAccountId !== accountId) return { discarded: true, error };
        console.error(error);
        setStatus(error.message || "Order refresh failed.", "error");
      }
    }

    async function cancelOrder(orderId, button = null) {
      const order = state.orders.find((item) => item.id === orderId);
      if (!order) { setStatus("Order not found in the current table.", "error"); return; }
      if (!isCancelableOrder(order)) { setStatus("This order can no longer be canceled.", "warning"); return; }
      const accountId = state.selectedAccountId;
      try {
        const mutation = await runConfirmedBrokerMutation({
          actionKey: `order-cancel:${orderId}`, button, requestSignature: JSON.stringify({ order_id: orderId, action: "cancel" }), getRequestSignature: () => JSON.stringify({ order_id: orderId, action: "cancel" }), statusElement: els.orderActionStatus,
          confirmation: { title: "Confirm paper order cancellation", summary: `Cancel ${String(order.side || "").toUpperCase()} ${order.quantity} ${order.symbol}`, details: { Account: order.external_account_id || state.selectedAccountId, Mode: "Paper", Symbol: order.symbol, Side: String(order.side || "").toUpperCase(), Quantity: String(order.quantity), Price: formatOrderPrice(order), "Max Risk": "Cancel only", "Quote Time": matchingQuoteTime(order.symbol) } },
        }, async (idempotencyKey) => fetchJson(`/orders/${encodeURIComponent(orderId)}/cancel`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, timeoutMs: 25000 }));
        if (!mutation.executed) return;
        const canceled = mutation.result;
        state.selectedOrderId = canceled.id;
        const reload = await reloadAccountForMutation(accountId);
        if (reload.discarded) return reload;
        setSelectedOrder(canceled.id);
        setActionStatus(els.orderActionStatus, `Order ${canceled.symbol} canceled.`, "success");
        setStatus(`Order ${canceled.symbol} canceled.`, "success");
      } catch (error) {
        if (state.selectedAccountId !== accountId) return { discarded: true, error };
        console.error(error);
        setActionStatus(els.orderActionStatus, error.message || "Order cancel failed.", "error");
        setStatus(error.message || "Order cancel failed.", "error");
      }
    }

    async function replaceSelectedOrder(button = null) {
      const order = selectedOrder();
      if (!order) { setStatus("Select an order before replacing it.", "warning"); return; }
      if (!isReplaceableOrder(order)) { setStatus("Only working orders can be replaced.", "warning"); return; }
      const accountId = state.selectedAccountId;
      try {
        const payload = buildReplaceOrderPayload(order);
        const actionKey = `order-replace:${order.id}`;
        if (button) button.dataset.actionKey = actionKey;
        const mutation = await runConfirmedBrokerMutation({
          actionKey, button, requestSignature: JSON.stringify({ order_id: order.id, ...payload }), getRequestSignature: () => JSON.stringify({ order_id: order.id, ...buildReplaceOrderPayload(order) }), statusElement: els.orderActionStatus,
          confirmation: { title: "Confirm paper order replacement", summary: `Replace ${String(order.side || "").toUpperCase()} ${payload.quantity} ${order.symbol}`, details: { Account: order.external_account_id || state.selectedAccountId, Mode: "Paper", Symbol: order.symbol, Side: String(order.side || "").toUpperCase(), Quantity: String(payload.quantity), Price: payload.limit_price ? `Limit ${formatCurrency(payload.limit_price, "USD")}` : formatOrderPrice(order), "Max Risk": payload.limit_price && order.side === "buy" ? formatCurrency(Number(payload.quantity) * Number(payload.limit_price), "USD") : "Not bounded in ticket", "Quote Time": matchingQuoteTime(order.symbol) } },
        }, async (idempotencyKey) => fetchJson(`/orders/${encodeURIComponent(order.id)}/replace`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey }, body: JSON.stringify(payload), timeoutMs: 25000 }));
        if (!mutation.executed) return;
        const updated = mutation.result;
        state.selectedOrderId = updated.id;
        els.replaceRemark.value = "";
        const reload = await reloadAccountForMutation(accountId);
        if (reload.discarded) return reload;
        setSelectedOrder(updated.id);
        setActionStatus(els.orderActionStatus, `Order ${updated.symbol} updated.`, "success");
        setStatus(`Order ${updated.symbol} updated.`, "success");
      } catch (error) {
        if (state.selectedAccountId !== accountId) return { discarded: true, error };
        console.error(error);
        setActionStatus(els.orderActionStatus, error.message || "Order replace failed.", "error");
        setStatus(error.message || "Order replace failed.", "error");
      }
    }

    async function submitJournalEntry() {
      const order = selectedOrder();
      if (!order) { setStatus("Select an order before saving a journal entry.", "warning"); return; }
      const accountId = state.selectedAccountId;
      const accountLoadGeneration = state.accountLoadGeneration;
      try {
        const title = els.journalTitle.value.trim();
        const notes = els.journalNotes.value.trim();
        if (!title) throw new Error("Journal title is required.");
        if (!notes) throw new Error("Journal notes are required.");
        const execution = selectedExecution();
        const payload = { external_account_id: order.external_account_id, symbol: order.symbol, entry_type: els.journalEntryType.value, title, notes, order_id: order.id, trade_plan_id: order.trade_plan_id, execution_id: execution?.id || null, tags: parseTags(els.journalTags.value) };
        setStatus(`Saving ${payload.entry_type} entry for ${order.symbol}...`, "warning");
        const created = await fetchJson("/journals", { method: "POST", body: JSON.stringify(payload) });
        if (state.selectedAccountId !== accountId || state.accountLoadGeneration !== accountLoadGeneration) return { discarded: true };
        state.journals = [created, ...(state.journals || []).filter((entry) => entry.id !== created.id)];
        state.selectedOrderJournals = [created, ...(state.selectedOrderJournals || []).filter((entry) => entry.id !== created.id)];
        els.journalTitle.value = "";
        els.journalTags.value = "";
        els.journalNotes.value = "";
        renderSelectedJournal();
        setStatus(`Journal entry saved for ${created.symbol}.`, "success");
      } catch (error) {
        if (state.selectedAccountId !== accountId) return { discarded: true, error };
        console.error(error);
        setStatus(error.message || "Journal entry save failed.", "error");
      }
    }

    function syncTicketOrderFields() {
      syncOrderTypeFields({ orderType: els.orderType.value, limitField: els.orderLimitField, limitInput: els.orderLimitPrice, stopField: els.orderStopField, stopInput: els.orderStopPrice, hintEl: els.orderFormHint, marketHint: "Market orders use the broker's current market price.", limitHint: "Limit orders require a positive limit price.", stopHint: "Stop orders require a positive stop price and may include a limit price." });
    }

    function syncReplaceOrderFields(orderType) {
      syncOrderTypeFields({ orderType, limitField: els.replaceLimitField, limitInput: els.replaceLimitPrice, stopField: els.replaceStopField, stopInput: els.replaceStopPrice, hintEl: els.replaceFormHint, marketHint: "Market replacement keeps the broker market-price behavior.", limitHint: "Limit replacement requires a positive limit price.", stopHint: "Stop replacement requires a positive stop price and may include a limit price." });
    }

    function syncOrderTypeFields({ orderType, limitField, limitInput, stopField, stopInput, hintEl, marketHint, limitHint, stopHint }) {
      const showLimit = orderType === "limit" || orderType === "stop";
      const showStop = orderType === "stop";
      setFieldVisibility(limitField, limitInput, showLimit);
      setFieldVisibility(stopField, stopInput, showStop);
      if (orderType === "market") { limitInput.value = ""; stopInput.value = ""; hintEl.textContent = marketHint; return; }
      if (orderType === "limit") { stopInput.value = ""; hintEl.textContent = limitHint; return; }
      hintEl.textContent = stopHint;
    }

    function setFieldVisibility(field, input, visible) {
      field.classList.toggle("hidden", !visible);
      input.disabled = !visible;
    }

    function buildCreateOrderPayload() {
      const symbol = els.orderSymbol.value.trim().toUpperCase();
      if (!symbol) throw new Error("Order symbol is required.");
      const payload = { external_account_id: state.selectedAccountId, symbol, side: els.orderSide.value, quantity: parsePositiveInteger(els.orderQuantity.value, "Order quantity"), order_type: els.orderType.value, time_in_force: els.orderTimeInForce.value, mode: "paper", remark: normalizeOptionalText(els.orderRemark.value) };
      applyOrderTypePrices({ orderType: payload.order_type, limitValue: els.orderLimitPrice.value, stopValue: els.orderStopPrice.value, payload, contextLabel: "Order" });
      return payload;
    }

    function buildReplaceOrderPayload(order) {
      const payload = { quantity: parsePositiveInteger(els.replaceQuantity.value, "Replace quantity"), remark: normalizeOptionalText(els.replaceRemark.value) };
      applyOrderTypePrices({ orderType: order.order_type, limitValue: els.replaceLimitPrice.value, stopValue: els.replaceStopPrice.value, payload, contextLabel: "Replace" });
      return payload;
    }

    function applyOrderTypePrices({ orderType, limitValue, stopValue, payload, contextLabel }) {
      if (orderType === "market") { payload.limit_price = null; payload.stop_price = null; return; }
      if (orderType === "limit") { payload.limit_price = parsePositiveNumber(limitValue, `${contextLabel} limit price`, true); payload.stop_price = null; return; }
      if (orderType === "stop") { payload.limit_price = parsePositiveNumber(limitValue, `${contextLabel} limit price`, false); payload.stop_price = parsePositiveNumber(stopValue, `${contextLabel} stop price`, true); return; }
      throw new Error(`Unsupported order type: ${orderType}`);
    }

    function isCancelableOrder(order) {
      return ["created", "submitted", "partially_filled"].includes(order.status);
    }

    function isReplaceableOrder(order) {
      return ["created", "submitted", "partially_filled"].includes(order.status);
    }

    function formatOrderPrice(order) {
      const parts = [];
      if (order.limit_price !== null && order.limit_price !== undefined) parts.push(`L ${formatNumber(order.limit_price)}`);
      if (order.stop_price !== null && order.stop_price !== undefined) parts.push(`S ${formatNumber(order.stop_price)}`);
      return parts.length ? parts.join(" / ") : "--";
    }

    function wireEvents() {
      els.orderType?.addEventListener("change", syncTicketOrderFields);
      els.orderTicketForm?.addEventListener("submit", (event) => { event.preventDefault(); void submitOrder(els.submitOrder); });
      els.ordersBody?.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-order-action]");
        if (!button) return;
        const { orderAction, orderId } = button.dataset;
        if (!orderAction || !orderId) return;
        if (orderAction === "manage") { setSelectedOrder(orderId, true); return; }
        if (orderAction === "refresh") { void refreshOrder(orderId); return; }
        if (orderAction === "cancel") { void cancelOrder(orderId, button); }
      });
      els.ordersLoadMore?.addEventListener("click", () => { void loadMoreOrders(); });
      els.selectedOrderCard?.addEventListener("click", (event) => {
        const button = event.target.closest("button[data-selected-action]");
        if (!button) return;
        const order = selectedOrder();
        if (!order) return;
        if (button.dataset.selectedAction === "refresh") void refreshOrder(order.id);
        if (button.dataset.selectedAction === "cancel") void cancelOrder(order.id, button);
      });
      els.replaceOrderForm?.addEventListener("submit", (event) => { event.preventDefault(); void replaceSelectedOrder(event.submitter); });
      els.journalEntryForm?.addEventListener("submit", (event) => { event.preventDefault(); void submitJournalEntry(); });
      els.executionsLoadMore?.addEventListener("click", () => { void loadMoreSelectedActivity("executions"); });
      els.journalsLoadMore?.addEventListener("click", () => { void loadMoreSelectedActivity("journals"); });
    }

    function render() {
      renderOrders();
      renderSelectedOrder();
    }

    return {
      wireEvents,
      render,
      renderOrders,
      renderSelectedOrder,
      renderSelectedExecution,
      renderSelectedJournal,
      setSelectedOrder,
      getSelectedOrder: selectedOrder,
      getSelectedExecution: selectedExecution,
      getSelectedJournalEntries: selectedJournalEntries,
      submitOrder,
      refreshOrder,
      cancelOrder,
      replaceSelectedOrder,
      submitJournalEntry,
      updateOrderTicketAvailability,
      syncTicketOrderFields,
      syncReplaceOrderFields,
      loadSelectedDetails,
      loadMoreOrders,
    };
  }

  window.StocksToolOrdersView = { createOrdersView };
})();

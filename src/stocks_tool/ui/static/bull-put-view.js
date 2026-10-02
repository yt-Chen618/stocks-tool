(function () {
  function createBullPutView({
    state,
    els,
    accountLoader,
    runConfirmedBrokerMutation,
    setStatus,
    setActionStatus,
    loadAccountData,
    applyTradingSafetyState,
    escapeHtml,
    formatters,
  }) {
    const formatter = formatters || window.StocksToolFormatters || {};
    const {
      toNumber,
      formatCurrency,
      formatDateTime,
      formatSignedCurrency,
      formatSpreadStatusLabel,
      formatSpreadExitReason,
      formatSpreadStrike,
      formatSpreadDate,
      formatSpreadCredit,
      spreadStatusClass,
      pnlTone,
    } = formatter;
    const openRecoveryIds = new Set();
    const openHistoryIds = new Set();
    const loadingEligibilityIds = new Set();
    let eventsWired = false;

    const resolvedPnlTone = pnlTone || ((value) => Number(value) > 0 ? "success" : Number(value) < 0 ? "error" : "neutral");

    function objectPayload(value) {
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }

    function isActiveSpread(spread) {
      return ["entry_pending_long", "entry_pending_short", "open", "exit_pending_short", "exit_pending_long"].includes(spread?.status);
    }

    function isExitPendingSpread(spread) {
      return spread?.status === "exit_pending_short" || spread?.status === "exit_pending_long";
    }

    function isMonitorableSpread(spread) {
      return spread?.status === "open" || isExitPendingSpread(spread);
    }

    function getSpreadLifecycleWarning(spread) {
      return window.StocksToolLifecycle?.bullPutSpreadLifecycleWarning(spread, state.orders) || null;
    }

    function spreadById(spreadId) {
      return state.spreads.find((spread) => spread.id === spreadId)
        || state.bullPutHistory.find((spread) => spread.id === spreadId)
        || state.bullPutHistoryDetails?.[spreadId]
        || null;
    }

    function renderSpreadDetailCell(lines, pnlValue = null, explicitTone = null) {
      const [primary = "--", ...secondary] = lines;
      const toneClass = explicitTone
        ? ` is-${explicitTone}`
          : pnlValue !== null && pnlValue !== undefined
          ? ` is-${resolvedPnlTone(toNumber(pnlValue))}`
          : "";
      return `
        <div class="spread-detail-cell">
          <strong class="${toneClass.trim()}">${escapeHtml(primary)}</strong>
          ${secondary.map((line) => `<span>${escapeHtml(line)}</span>`).join("")}
        </div>
      `;
    }

    function recoveryPanelMarkup(spread) {
      const eligibility = objectPayload(state.recoverCloseEligibility?.[spread.id]);
      const loading = loadingEligibilityIds.has(spread.id);
      let content = `<span data-recovery-placeholder>Expand to load recovery eligibility.</span>`;
      if (loading) {
        content = "Loading recovery eligibility...";
      } else if (eligibility.error || eligibility.spread_id) {
        content = renderRecoverClosePanel(spread, eligibility);
      }
      return `
        <details class="recover-close-disclosure" data-recovery-details data-spread-id="${escapeHtml(spread.id)}" ${openRecoveryIds.has(spread.id) ? "open" : ""}>
          <summary>Recovery check</summary>
          <div data-recovery-content>${content}</div>
        </details>
      `;
    }

    function renderRecoverClosePanel(spread, eligibility) {
      if (eligibility.error) {
        return `<div class="recover-close-panel"><strong class="is-warning">Recovery unavailable</strong><span>${escapeHtml(eligibility.error)}</span></div>`;
      }
      const reasons = Array.isArray(eligibility.reasons) ? eligibility.reasons.filter(Boolean) : [];
      const oldStatus = eligibility.old_short_close_order_status || "--";
      const workingReplacement = eligibility.working_replacement_order_id || "--";
      const hint = eligibility.max_debit_required_hint;
      const maxDebitValue = hint !== null && hint !== undefined ? String(hint) : "";
      const eligible = eligibility.eligible === true;
      const toneClass = eligible ? "is-success" : reasons.includes("close_not_required") ? "is-neutral" : "is-warning";
      const disabled = eligible ? "" : "disabled";
      return `
        <div class="recover-close-panel">
          <div class="recover-close-head">
            <strong class="${toneClass}">${eligible ? "Recovery Eligible" : "Recovery Blocked"}</strong>
            <span>${escapeHtml(reasons.length ? reasons.join(", ") : "Ready for manual paper recovery.")}</span>
          </div>
          <div class="recover-close-meta">
            <span>Old close ${escapeHtml(oldStatus)}</span>
            <span>Working ${escapeHtml(workingReplacement)}</span>
          </div>
          <form class="recover-close-form" data-recover-close-form="${escapeHtml(spread.id)}">
            <input name="actor" type="text" maxlength="80" value="local_operator" ${disabled} aria-label="Recovery actor" />
            <input name="max_debit" type="number" min="0" step="0.01" value="${escapeHtml(maxDebitValue)}" placeholder="Max debit" ${disabled} aria-label="Recovery max debit" />
            <input name="note" type="text" maxlength="500" value="manual recover close" ${disabled} aria-label="Recovery note" />
            <label class="recover-confirm">
              <input name="confirm_paper_order" type="checkbox" ${disabled} />
              <span>Paper</span>
            </label>
            <button class="table-action primary" type="submit" ${disabled} data-business-disabled="${eligible ? "false" : "true"}" data-broker-mutation="true" data-action-key="bull-put-recover:${escapeHtml(spread.id)}">Recover</button>
          </form>
        </div>
      `;
    }

    function renderCurrent() {
      if (!els.spreadSummaryStrip || !els.spreadsBody) return;
      const spreads = [...(state.spreads || [])].sort(
        (left, right) => new Date(right.updated_at || 0).getTime() - new Date(left.updated_at || 0).getTime(),
      );
      const activeSpreads = spreads.filter(isActiveSpread);
      const exitPendingSpreads = spreads.filter(isExitPendingSpread);
      const monitorableSpreads = spreads.filter(isMonitorableSpread);
      const monitoredOpenSpread = activeSpreads.find((spread) => spread.raw_payload?.monitor) || null;
      const monitoredSnapshot = monitoredOpenSpread ? monitoredOpenSpread.raw_payload.monitor : null;
      const lastMonitoredSpread = monitorableSpreads.find((spread) => spread.last_synced_at) || null;
      const lifecycleWarnings = monitorableSpreads.map(getSpreadLifecycleWarning).filter(Boolean);
      const primaryLifecycleWarning = lifecycleWarnings[0] || null;
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
          label: "Monitor Mark",
          value: monitoredSnapshot?.estimated_exit_debit ? formatSpreadCredit(monitoredSnapshot.estimated_exit_debit) : "--",
          tone: monitoredSnapshot?.exit_reason ? "warning" : "",
          detail: monitoredOpenSpread
            ? `${monitoredOpenSpread.underlying_symbol} / ${formatDateTime(monitoredSnapshot.evaluated_at)}`
            : "No monitor snapshot",
        },
        {
          label: "P/L",
          value: monitoredSnapshot?.estimated_pnl ? formatSignedCurrency(monitoredSnapshot.estimated_pnl, "USD") : "--",
          tone: monitoredSnapshot?.estimated_pnl ? resolvedPnlTone(monitoredSnapshot.estimated_pnl) : "",
          detail: monitoredSnapshot
            ? `TP Gap ${formatSpreadCredit(monitoredSnapshot.distance_to_take_profit_debit)} / SL Gap ${formatSpreadCredit(monitoredSnapshot.distance_to_stop_loss_debit)}`
            : "No monitor snapshot",
        },
        {
          label: "Last Monitor",
          value: lastMonitoredSpread ? formatDateTime(lastMonitoredSpread.last_synced_at) : "--",
          tone: primaryLifecycleWarning ? "error" : "",
          detail: primaryLifecycleWarning
            ? primaryLifecycleWarning.message
            : lastMonitoredSpread
              ? `${lastMonitoredSpread.underlying_symbol} / ${formatSpreadStatusLabel(lastMonitoredSpread.status)}`
              : monitorableSpreads.length
                ? "Waiting for first monitor run"
                : "No open or exit-pending spreads are being monitored.",
        },
      ];
      els.spreadSummaryStrip.innerHTML = summaryValues.map((item) => `
        <article class="mini-metric-tile">
          <span class="metric-label">${escapeHtml(item.label)}</span>
          <strong class="mini-metric-value ${item.tone ? `is-${item.tone}` : ""}">${escapeHtml(item.value)}</strong>
          <span class="mini-metric-detail">${escapeHtml(item.detail)}</span>
        </article>
      `).join("");
      const lastAction = state.bullPutLastActionDetail;
      const lastActionMarkup = lastAction && lastAction.accountId === state.selectedAccountId && lastAction.mode === "paper"
        ? `<tr class="bull-put-last-action" data-bull-put-last-action><td colspan="8"><div class="spread-history-detail"><strong>Last Bull Put action</strong><span>${escapeHtml(lastAction.message || "Action completed.")}</span><span>${escapeHtml(lastAction.detail?.underlying_symbol || lastAction.detail?.id || "--")} / ${escapeHtml(formatSpreadStatusLabel(lastAction.detail?.status))} / ${escapeHtml(formatDateTime(lastAction.detail?.closed_at || lastAction.detail?.updated_at))}</span></div></td></tr>`
        : "";
      if (!spreads.length) {
        els.spreadsBody.innerHTML = `${lastActionMarkup}<tr><td colspan="8" class="empty-row">No working bull put spreads for this account.</td></tr>`;
        return;
      }
      els.spreadsBody.innerHTML = lastActionMarkup + spreads.map((spread) => {
        const monitorable = isMonitorableSpread(spread);
        const lifecycleWarning = getSpreadLifecycleWarning(spread);
        const statusTone = lifecycleWarning ? "error" : spreadStatusClass(spread.status);
        const statusLabel = lifecycleWarning ? "Manual Action Needed" : formatSpreadStatusLabel(spread.status);
        const monitor = spread.raw_payload?.monitor || null;
        const legSummary = `${formatSpreadStrike(spread.long_strike)} / ${formatSpreadStrike(spread.short_strike)} puts`;
        const lastUpdatedAt = spread.last_synced_at || spread.updated_at || spread.created_at;
        const maxLoss = toNumber(spread.max_loss);
        const entryRiskLines = [
          `Credit ${formatSpreadCredit(spread.entry_net_credit)}`,
          `Max Loss ${Number.isFinite(maxLoss) ? formatSignedCurrency(-Math.abs(maxLoss), "USD") : "--"}`,
          `BE ${formatSpreadStrike(spread.break_even)}`,
        ];
        const monitorMark = monitor
          ? [`Mark ${formatSpreadCredit(monitor.estimated_exit_debit)}`, `Spot ${formatSpreadStrike(monitor.underlying_price)}`, `${monitor.days_to_expiration ?? "--"} DTE`]
          : ["No monitor snapshot"];
        const distanceLines = monitor
          ? [`P/L ${formatSignedCurrency(monitor.estimated_pnl, "USD")}`, `TP Gap ${formatSpreadCredit(monitor.distance_to_take_profit_debit)}`, `SL Gap ${formatSpreadCredit(monitor.distance_to_stop_loss_debit)}`]
          : [spread.exit_reason ? formatSpreadExitReason(spread.exit_reason) : "--"];
        const monitorLines = monitor
          ? [
              lifecycleWarning ? lifecycleWarning.message : monitor.exit_reason ? formatSpreadExitReason(monitor.exit_reason) : "Within thresholds",
              ...(lifecycleWarning ? [lifecycleWarning.detail, `Order ${lifecycleWarning.orderId} ${lifecycleWarning.orderStatus}`] : []),
              `Next Check ${formatDateTime(monitor.next_monitor_after)}`,
              `Updated ${formatDateTime(monitor.evaluated_at)}`,
            ]
          : [`Updated ${formatDateTime(lastUpdatedAt)}`];
        return `
          <tr data-spread-id="${escapeHtml(spread.id)}">
            <td><div class="symbol-cell"><strong>${escapeHtml(spread.underlying_symbol)}</strong><span>${escapeHtml(legSummary)}</span></div></td>
            <td>${escapeHtml(formatSpreadDate(spread.expiration_date))}</td>
            <td><span class="pill ${statusTone}">${escapeHtml(statusLabel)}</span></td>
            <td>${renderSpreadDetailCell(entryRiskLines)}</td>
            <td>${renderSpreadDetailCell(monitorMark)}</td>
            <td>${renderSpreadDetailCell(distanceLines, monitor?.estimated_pnl)}</td>
            <td>${renderSpreadDetailCell(monitorLines, null, lifecycleWarning ? "error" : null)}</td>
            <td>
              <div class="table-actions">
                <button class="table-action" type="button" data-spread-action="refresh" data-spread-id="${escapeHtml(spread.id)}">Refresh</button>
                ${monitorable ? `<button class="table-action primary" type="button" data-spread-action="monitor" data-spread-id="${escapeHtml(spread.id)}" data-broker-mutation="true" data-action-key="bull-put-monitor:${escapeHtml(spread.id)}">Monitor</button>` : ""}
              </div>
              ${monitorable ? recoveryPanelMarkup(spread) : ""}
            </td>
          </tr>
        `;
      }).join("");
    }

    function renderHistoryDetail(spreadId) {
      const detail = state.bullPutHistoryDetails?.[spreadId];
      const error = state.bullPutHistoryDetailErrors?.[spreadId];
      if (state.bullPutHistoryDetailLoading?.[spreadId]) return "Loading spread detail...";
      if (error) return `<span class="history-detail-error">${escapeHtml(error)}</span>`;
      if (!detail) return "Select Details to load this spread by id.";
      const legs = `${detail.long_symbol || "--"} / ${detail.short_symbol || "--"}`;
      return `<div class="spread-history-detail"><strong>${escapeHtml(detail.underlying_symbol || detail.id)}</strong><span>${escapeHtml(formatSpreadStatusLabel(detail.status))} / ${escapeHtml(legs)}</span><span>Entry ${escapeHtml(formatSpreadCredit(detail.entry_net_credit))} / Max loss ${escapeHtml(formatCurrency(detail.max_loss, "USD"))}</span><span>Opened ${escapeHtml(formatDateTime(detail.opened_at))} / Closed ${escapeHtml(formatDateTime(detail.closed_at))}</span></div>`;
    }

    function renderHistory() {
      if (!els.bullPutHistoryPanel || !els.bullPutHistoryBody || !els.bullPutHistoryLoadMore || !els.bullPutHistoryStatus) return;
      const page = state.bullPutHistoryPage || {};
      const history = Array.isArray(state.bullPutHistory) ? state.bullPutHistory : [];
      if (page.loading) {
        els.bullPutHistoryStatus.textContent = "Loading Bull Put history...";
      } else if (page.error) {
        els.bullPutHistoryStatus.textContent = `Bull Put history unavailable: ${page.error}`;
      } else if (!history.length) {
        els.bullPutHistoryStatus.textContent = "Expand to load completed Bull Put spreads.";
      } else {
        els.bullPutHistoryStatus.textContent = `${history.length} historical spread${history.length === 1 ? "" : "s"} loaded.`;
      }
      els.bullPutHistoryBody.innerHTML = history.length
        ? history.map((spread) => `
          <tr data-history-spread-id="${escapeHtml(spread.id)}">
            <td><strong>${escapeHtml(spread.underlying_symbol)}</strong><span>${escapeHtml(`${formatSpreadStrike(spread.long_strike)} / ${formatSpreadStrike(spread.short_strike)} puts`)}</span></td>
            <td>${escapeHtml(formatSpreadDate(spread.expiration_date))}</td>
            <td><span class="pill ${spreadStatusClass(spread.status)}">${escapeHtml(formatSpreadStatusLabel(spread.status))}</span></td>
            <td>${escapeHtml(formatDateTime(spread.updated_at || spread.closed_at || spread.created_at))}</td>
            <td><button class="table-action" type="button" data-history-action="detail" data-spread-id="${escapeHtml(spread.id)}">Details</button></td>
          </tr>
          <tr class="history-detail-row" data-history-detail-row="${escapeHtml(spread.id)}" ${openHistoryIds.has(spread.id) ? "" : "hidden"}><td colspan="5">${renderHistoryDetail(spread.id)}</td></tr>
        `).join("")
        : '<tr><td colspan="5" class="empty-row">No completed Bull Put spreads loaded.</td></tr>';
      els.bullPutHistoryLoadMore.hidden = !page.hasMore;
      els.bullPutHistoryLoadMore.disabled = Boolean(page.loading);
    }

    async function loadHistory({ append = false } = {}) {
      try {
        const result = await accountLoader.loadBullPutHistoryPage({ append });
        if (!result?.discarded) renderHistory();
      } catch (error) {
        renderHistory();
        setStatus(error.message || "Bull Put history load failed.", "error");
      }
    }

    async function loadHistoryDetail(spreadId) {
      try {
        const result = await accountLoader.loadSpreadDetail(spreadId);
        if (!result?.discarded) renderHistory();
      } catch (error) {
        renderHistory();
        setStatus(error.message || "Bull Put spread detail load failed.", "error");
      }
    }

    async function loadEligibility(spreadId) {
      if (loadingEligibilityIds.has(spreadId) || state.recoverCloseEligibility?.[spreadId]?.spread_id === spreadId) return;
      loadingEligibilityIds.add(spreadId);
      renderCurrent();
      try {
        await accountLoader.loadSpreadEligibility(spreadId);
      } catch (error) {
        setStatus(error.message || "Recovery eligibility unavailable.", "error");
      } finally {
        loadingEligibilityIds.delete(spreadId);
        renderCurrent();
        applyTradingSafetyState?.();
      }
    }

    async function refreshSpread(spreadId) {
      const spread = spreadById(spreadId);
      setStatus(`Refreshing spread ${spread?.underlying_symbol || spreadId}...`, "warning");
      try {
        const result = await accountLoader.refreshSpread(spreadId);
        if (result?.discarded) return;
        await loadAccountData();
        setStatus(`Spread ${result.detail.underlying_symbol} refreshed.`, "success");
      } catch (error) {
        console.error(error);
        setStatus(error.message || "Spread refresh failed.", "error");
      }
    }

    async function monitorSpread(spreadId, button = null) {
      const spread = spreadById(spreadId);
      try {
        const actionKey = `bull-put-monitor:${spreadId}`;
        const mutation = await runConfirmedBrokerMutation({
          actionKey,
          button,
          requestSignature: JSON.stringify({ spread_id: spreadId, action: "monitor" }),
          getRequestSignature: () => JSON.stringify({ spread_id: spreadId, action: "monitor" }),
          statusElement: els.strategyControlsHint,
          confirmation: {
            title: "Confirm Bull Put monitor",
            summary: `Monitor ${spread?.underlying_symbol || spreadId}; exit rules may submit closing orders`,
            details: {
              Account: spread?.external_account_id || state.selectedAccountId,
              Mode: "Paper",
              Symbol: spread?.underlying_symbol || spreadId,
              "Side / Legs": `${spread?.long_symbol || "Long put"} / ${spread?.short_symbol || "Short put"}`,
              Quantity: `${spread?.contracts || 1} spread`,
              Price: spread?.raw_payload?.monitor?.estimated_exit_debit ? `Estimated debit ${formatCurrency(spread.raw_payload.monitor.estimated_exit_debit, "USD")}` : "Fresh exit limits",
              "Max Risk": formatCurrency(spread?.max_loss, "USD"),
              "Quote Time": formatDateTime(spread?.raw_payload?.monitor?.evaluated_at || spread?.last_synced_at),
            },
          },
        }, async (idempotencyKey) => {
          setStatus(`Monitoring spread ${spread?.underlying_symbol || spreadId}...`, "warning");
          const response = await accountLoader.monitorSpread(spreadId, idempotencyKey);
          return response?.result;
        });
        if (!mutation.executed || mutation.result?.discarded) return;
        await loadAccountData();
        const result = mutation.result;
        const action = result.should_close
          ? `Exit action ${formatSpreadExitReason(result.exit_reason)} evaluated for ${result.spread.underlying_symbol}.`
          : `Spread ${result.spread.underlying_symbol} remains within thresholds.`;
        const tone = result.should_close ? "success" : "warning";
        state.bullPutLastActionDetail = { accountId: state.selectedAccountId, mode: "paper", detail: result.spread, message: action };
        renderCurrent();
        setActionStatus(els.strategyControlsHint, action, tone);
        setStatus(action, tone);
      } catch (error) {
        console.error(error);
        setActionStatus(els.strategyControlsHint, error.message || "Spread monitor failed.", "error");
        setStatus(error.message || "Spread monitor failed.", "error");
      }
    }

    async function recoverClose(spreadId, formData, button = null) {
      const spread = spreadById(spreadId);
      const eligibility = state.recoverCloseEligibility?.[spreadId];
      if (!eligibility?.eligible || eligibility.external_account_id !== state.selectedAccountId || eligibility.mode !== "paper") {
        setStatus("Recovery close is no longer eligible. No request was sent.", "error");
        return;
      }
      const actor = String(formData.get("actor") || "").trim();
      const note = String(formData.get("note") || "").trim();
      const maxDebit = String(formData.get("max_debit") || "").trim();
      if (!actor || !note || !maxDebit || formData.get("confirm_paper_order") !== "on") {
        setStatus("Recover close requires actor, note, max debit, and paper-order confirmation.", "error");
        return;
      }
      const payload = {
        external_account_id: state.selectedAccountId,
        mode: "paper",
        confirm_paper_order: true,
        max_debit: maxDebit,
        actor,
        note,
      };
      try {
        const mutation = await runConfirmedBrokerMutation({
          actionKey: `bull-put-recover:${spreadId}`,
          button,
          requestSignature: JSON.stringify({ spread_id: spreadId, ...payload }),
          getRequestSignature: () => JSON.stringify({ spread_id: spreadId, ...payload }),
          businessPredicate: () => {
            const current = state.recoverCloseEligibility?.[spreadId];
            return current?.eligible === true && current.external_account_id === state.selectedAccountId && current.mode === "paper";
          },
          businessBlockedMessage: "Recovery close is no longer eligible. No request was sent.",
          statusElement: els.strategyControlsHint,
          confirmation: {
            title: "Confirm Bull Put recovery close",
            summary: `Buy to close the short put for ${spread?.underlying_symbol || spreadId}`,
            details: {
              Account: state.selectedAccountId,
              Mode: "Paper",
              Symbol: spread?.short_symbol || spread?.underlying_symbol || spreadId,
              "Side / Legs": "Buy short put to close",
              Quantity: `${spread?.contracts || 1} contract`,
              Price: `Max debit ${formatCurrency(maxDebit, "USD")}`,
              "Max Risk": formatCurrency(Number(maxDebit) * Number(spread?.contracts || 1) * 100, "USD"),
              "Quote Time": formatDateTime(spread?.last_synced_at),
            },
          },
        }, async (idempotencyKey) => {
          setStatus(`Submitting recovery close for ${spread?.underlying_symbol || spreadId}...`, "warning");
          const response = await accountLoader.recoverCloseSpread(spreadId, payload, idempotencyKey);
          return response?.detail;
        });
        if (!mutation.executed || mutation.result?.discarded) return;
        await loadAccountData();
        state.bullPutLastActionDetail = { accountId: state.selectedAccountId, mode: "paper", detail: mutation.result, message: `Recovery close submitted for ${mutation.result.underlying_symbol}.` };
        renderCurrent();
        setActionStatus(els.strategyControlsHint, `Recovery close submitted for ${mutation.result.underlying_symbol}.`, "success");
        setStatus(`Recovery close submitted for ${mutation.result.underlying_symbol}.`, "success");
      } catch (error) {
        console.error(error);
        setActionStatus(els.strategyControlsHint, error.message || "Recover close failed.", "error");
        setStatus(error.message || "Recover close failed.", "error");
      }
    }

    function wireEvents() {
      if (eventsWired) return;
      eventsWired = true;
      els.spreadsBody?.addEventListener("click", async (event) => {
        const button = event.target.closest("button[data-spread-action]");
        if (!button) return;
        const spreadId = button.dataset.spreadId;
        if (button.dataset.spreadAction === "refresh") await refreshSpread(spreadId);
        if (button.dataset.spreadAction === "monitor") await monitorSpread(spreadId, button);
      });
      els.spreadsBody?.addEventListener("toggle", (event) => {
        const details = event.target.closest("details[data-recovery-details]");
        if (!details) return;
        const spreadId = details.dataset.spreadId;
        if (details.open) {
          openRecoveryIds.add(spreadId);
          void loadEligibility(spreadId);
        } else {
          openRecoveryIds.delete(spreadId);
        }
      }, true);
      els.spreadsBody?.addEventListener("submit", async (event) => {
        const form = event.target.closest("form[data-recover-close-form]");
        if (!form) return;
        event.preventDefault();
        await recoverClose(form.dataset.recoverCloseForm, new FormData(form), event.submitter);
      });
      els.bullPutHistoryPanel?.addEventListener("toggle", () => {
        if (!els.bullPutHistoryPanel.open) return;
        if (!state.bullPutHistory.length && !state.bullPutHistoryPage?.loading) void loadHistory();
      });
      els.bullPutHistoryBody?.addEventListener("click", async (event) => {
        const button = event.target.closest("button[data-history-action='detail']");
        if (!button) return;
        const spreadId = button.dataset.spreadId;
        const detailRow = Array.from(els.bullPutHistoryBody.querySelectorAll("[data-history-detail-row]"))
          .find((row) => row.dataset.historyDetailRow === spreadId);
        if (!detailRow) return;
        if (openHistoryIds.has(spreadId)) {
          openHistoryIds.delete(spreadId);
          detailRow.hidden = true;
          return;
        }
        openHistoryIds.add(spreadId);
        detailRow.hidden = false;
        if (!state.bullPutHistoryDetails?.[spreadId]) await loadHistoryDetail(spreadId);
        renderHistory();
      });
      els.bullPutHistoryLoadMore?.addEventListener("click", () => { void loadHistory({ append: true }); });
    }

    function render() {
      renderCurrent();
      renderHistory();
    }

    return { wireEvents, render, renderCurrent, renderHistory, loadHistory, loadHistoryDetail, loadEligibility };
  }

  window.StocksToolBullPutView = { createBullPutView };
})();

(function () {
  function createStrategyView({ state, els, escapeHtml, formatters, helpers = {} }) {
    const formatter = formatters || window.StocksToolFormatters || {};
    const {
      toNumber,
      formatCurrency,
      formatNumber,
      formatDateTime,
      formatSignedCurrency,
      formatSignedPercentValue,
      formatSignedDecimal,
      formatOrderAge,
      strategyStatusClass,
      formatStrategyStatusLabel,
    } = formatter;
    const {
      describeStrategyStatus = () => ({ value: "--", tone: "", detail: "" }),
      formatRuntimeNextAction = (value) => String(value || "--"),
      pnlTone = (value) => Number(value) > 0 ? "success" : Number(value) < 0 ? "error" : "neutral",
      updateStrategyButtons = () => {},
      updateZeroDteLotteryButtons = () => {},
      renderStrategyProposalDetails = () => "",
      renderStrategyProposalActions = () => "",
      renderStrategyProposalDetail = ([label, value, detail]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></div>`,
      displayValue = (value) => value === undefined || value === null || value === "" ? "--" : String(value),
      formatCoveredCallTaskDiagnostic = (task) => task?.diagnostic || "",
      formatCoveredCallSuggestedAction = (task) => task?.suggested_action || "",
    } = helpers;
    function objectPayload(value) {
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }
    function formatActivityCount(value) {
      const number = Number(value);
      return Number.isFinite(number) ? String(number) : "0";
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
      detail: runtime.daily_entry_cap_reached
        ? "Daily cap reached"
        : runtime.active_spread_count
          ? `${runtime.active_spread_count} active spread${runtime.active_spread_count === 1 ? "" : "s"}`
          : "ready for first spread",
    },
    {
      label: "Daily Realized PnL",
      value: formatSignedCurrency(runtime.daily_realized_pnl, "USD"),
      tone: pnlTone(runtime.daily_realized_pnl),
      detail: runtime.current_session_date ? `Session ${runtime.current_session_date}` : "No tracked session date",
    },
    {
      label: "Next Action",
      value: runtime.next_action ? formatRuntimeNextAction(runtime.next_action) : "--",
      tone: runtime.last_scan_result === "executed" ? "success" : runtime.last_scan_result === "skipped" ? "warning" : "",
      detail: runtime.next_monitor_after
        ? `Next monitor ${formatDateTime(runtime.next_monitor_after)}`
        : runtime.last_scan_at
          ? `Last scan ${runtime.last_scan_symbol || "Account"} / ${formatDateTime(runtime.last_scan_at)}`
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

function renderZeroDteLottery() {
  if (!els.zeroDteLotteryStrip || !els.zeroDteLotteryResultCard) {
    return;
  }
  const runtime = state.zeroDteLotteryRuntime;
  if (!runtime) {
    els.zeroDteLotteryStrip.innerHTML = `
      <article class="mini-metric-tile">
        <span class="metric-label">Execution</span>
        <strong class="mini-metric-value">Preview Only</strong>
        <span class="mini-metric-detail">Zero-DTE orders are disabled pending expiry lifecycle support.</span>
      </article>
    `;
    els.zeroDteLotteryAutoOrder.value = "false";
    els.zeroDteLotteryHint.textContent = "Preview only. Zero-DTE execution and automatic ordering are disabled.";
    renderZeroDteLotteryResult();
    updateZeroDteLotteryButtons();
    return;
  }

  const summaryValues = [
    {
      label: "Execution",
      value: "Preview Only",
      tone: runtime.auto_execute_enabled ? "warning" : "neutral",
      detail: runtime.auto_execute_enabled
        ? "Legacy auto-order flag detected; execution remains blocked."
        : "No manual, forced, or automatic orders.",
    },
    {
      label: "Max Premium",
      value: formatCurrency(runtime.max_premium_per_trade, "USD"),
      tone: "success",
      detail: `${runtime.contracts_per_trade || 1} contract(s) per order`,
    },
    {
      label: "Scan Window",
      value: `${runtime.scan_window_start || "--"}-${runtime.scan_window_end || "--"}`,
      tone: runtime.enabled ? "success" : "neutral",
      detail: `${runtime.scan_interval_seconds || "--"} second interval`,
    },
    {
      label: "Daily Cap",
      value: `${runtime.max_trades_per_day || 1}`,
      tone: "warning",
      detail: `${(runtime.symbols || []).join(", ") || "No symbols configured"}`,
    },
  ];
  els.zeroDteLotteryStrip.innerHTML = summaryValues
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

  els.zeroDteLotteryAutoOrder.value = "false";
  if (!els.zeroDteLotterySymbol.value.trim()) {
    els.zeroDteLotterySymbol.value = (runtime.symbols || [])[0] || "QQQ.US";
  }
  els.zeroDteLotteryHint.textContent = "Preview only. Zero-DTE execution and automatic ordering stay disabled until the expiry lifecycle is implemented.";
  renderZeroDteLotteryResult();
  updateZeroDteLotteryButtons();
}

function renderZeroDteLotteryResult() {
  const scan = state.zeroDteLotteryScanResult;
  const preview = state.zeroDteLotteryPreview || scan?.preview;
  if (!els.zeroDteLotteryResultCard) {
    return;
  }
  if (scan) {
    els.zeroDteLotteryResultCard.className = "strategy-note-body";
    els.zeroDteLotteryResultCard.innerHTML = renderZeroDteLotteryScanResult(scan);
    return;
  }
  if (preview) {
    els.zeroDteLotteryResultCard.className = "strategy-note-body";
    els.zeroDteLotteryResultCard.innerHTML = renderZeroDteLotteryPreview(preview);
    return;
  }
  els.zeroDteLotteryResultCard.className = "strategy-note-body empty";
  els.zeroDteLotteryResultCard.textContent = "No zero-DTE lottery preview loaded yet.";
}

function renderZeroDteLotteryPreview(preview) {
  const candidate = objectPayload(preview.candidate);
  const details = [
    ["Symbol", preview.symbol || "--", preview.direction ? formatStrategyStatusLabel(preview.direction) : "Direction not selected"],
    ["Underlying", formatCurrency(preview.underlying_price, "USD"), `${formatSignedDecimal(preview.underlying_change_pct)}% vs prior close`],
    ["Expiry", preview.selected_expiration_date || "--", `DTE ${preview.days_to_expiration ?? "--"}`],
    ["Max Premium", formatCurrency(preview.max_premium_per_trade, "USD"), preview.eligible ? "Candidate is inside cap" : "No eligible candidate"],
  ];
  if (candidate.option_symbol) {
    details.push(
      ["Option", candidate.option_symbol, `${formatStrategyStatusLabel(candidate.direction)} ${formatNumber(candidate.strike)}`],
      ["Bid / Ask", `${formatCurrency(candidate.option_bid, "USD")} / ${formatCurrency(candidate.option_ask, "USD")}`, `Mid ${formatCurrency(candidate.option_mid, "USD")}`],
      ["Premium", formatCurrency(candidate.premium_at_ask, "USD"), `Max loss ${formatCurrency(candidate.max_loss, "USD")}`],
      ["Liquidity", `OI ${displayValue(candidate.open_interest)} / Vol ${displayValue(candidate.volume)}`, `Delta ${formatSignedDecimal(candidate.delta)}`]
    );
  }
  const reasons = Array.isArray(preview.reasons) && preview.reasons.length
    ? `<p>${escapeHtml(preview.reasons[0])}</p>`
    : "";
  return `
    <article class="strategy-journal-entry">
      <div class="strategy-journal-head">
        <strong>${escapeHtml(preview.eligible ? "Eligible Lottery Candidate" : "Preview Result")}</strong>
        <span class="pill ${preview.eligible ? "success" : "warning"}">${escapeHtml(preview.eligible ? "Eligible" : "Skipped")}</span>
      </div>
      <div class="proposal-detail-grid">
        ${details.map(renderStrategyProposalDetail).join("")}
      </div>
      ${reasons}
      <span>${escapeHtml(`Evaluated ${formatDateTime(preview.evaluated_at)}`)}</span>
    </article>
  `;
}

function renderZeroDteLotteryScanResult(scan) {
  const order = objectPayload(scan.execution?.order);
  const previewMarkup = scan.preview ? renderZeroDteLotteryPreview(scan.preview) : "";
  const orderMarkup = scan.executed
    ? `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>Paper Order Submitted</strong>
          <span class="pill success">${escapeHtml(formatStrategyStatusLabel(order.status || "submitted"))}</span>
        </div>
        <div class="proposal-detail-grid">
          ${[
            ["Order", order.id || "--", order.external_order_id || "Local paper order"],
            ["Symbol", order.symbol || "--", `${formatStrategyStatusLabel(order.side)} ${displayValue(order.quantity)}`],
            ["Limit", formatCurrency(order.limit_price, "USD"), formatDateTime(order.submitted_at)],
            ["Mode", formatStrategyStatusLabel(order.mode || "paper"), "Zero-DTE lottery"],
          ].map(renderStrategyProposalDetail).join("")}
        </div>
      </article>
    `
    : `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head"><strong>Scan Skipped</strong><span class="pill warning">No Order</span></div>
        <p>${escapeHtml(scan.reason || "Zero-DTE lottery scan completed without an eligible candidate.")}</p>
        <span>${escapeHtml(formatDateTime(scan.scanned_at))}</span>
      </article>
    `;
  return `${orderMarkup}${previewMarkup}`;
}

function renderCoveredCallActivity() {
  if (!els.coveredCallActivityCard) {
    return;
  }
  const activity = state.coveredCallActivity || { summary: {}, lifecycle_tasks: [], latest_monitor: null, proposals: [], runs: [], signals: [], reviews: [] };
  const summary = objectPayload(activity.summary);
  const lifecycleTasks = Array.isArray(activity.lifecycle_tasks) ? activity.lifecycle_tasks : [];
  const latestMonitor = activity.latest_monitor ? objectPayload(activity.latest_monitor) : null;
  const proposals = Array.isArray(activity.proposals) ? activity.proposals : [];
  const runs = Array.isArray(activity.runs) ? activity.runs : [];
  const signals = Array.isArray(activity.signals) ? activity.signals : [];
  const reviews = Array.isArray(activity.reviews) ? activity.reviews : [];
  if (!lifecycleTasks.length && !proposals.length && !runs.length && !signals.length && !reviews.length) {
    els.coveredCallActivityCard.className = "strategy-note-body empty";
    els.coveredCallActivityCard.textContent = "No covered-call activity yet.";
    return;
  }

  const latestRun = runs[0] || null;
  const latestSignal = signals[0] || null;
  const summaryItems = [
    ["Active", formatActivityCount(summary.active_proposals), `${formatActivityCount(summary.total_proposals)} proposal(s) tracked`],
    ["Open CC", formatActivityCount(summary.executed_positions), "Open covered-call proposals"],
    ["Rolls", formatActivityCount(summary.pending_rolls), "Pending or approved roll proposals"],
    ["Lifecycle", formatActivityCount(lifecycleTasks.length), "Pending close / roll order tasks"],
    ["Closes", formatActivityCount(summary.close_runs), `Latest ${formatDateTime(summary.latest_activity_at)}`],
  ];
  const lifecycleMarkup = `
    <article class="strategy-journal-entry lifecycle-task-shell">
      <div class="strategy-journal-head">
        <strong>Pending Lifecycle</strong>
        <span>${escapeHtml(`${lifecycleTasks.length} task${lifecycleTasks.length === 1 ? "" : "s"}`)}</span>
      </div>
      ${
        lifecycleTasks.length
          ? `<div class="lifecycle-task-list">
              ${lifecycleTasks.slice(0, 4).map(renderCoveredCallLifecycleTask).join("")}
            </div>`
          : "<p>No pending close or roll lifecycle tasks.</p>"
      }
    </article>
  `;
  const proposalMarkup = proposals.length
    ? proposals
        .slice(0, 3)
        .map(
          (proposal) => `
            <article class="strategy-journal-entry">
              <div class="strategy-journal-head">
                <strong>${escapeHtml(proposal.title)}</strong>
                <span class="pill ${strategyStatusClass(proposal.status)}">${escapeHtml(formatStrategyStatusLabel(proposal.status))}</span>
              </div>
              <p>${escapeHtml([proposal.symbol, proposal.proposed_action].filter(Boolean).join(" / "))}</p>
              ${renderStrategyProposalDetails(proposal, proposals)}
              ${renderStrategyProposalActions(proposal)}
            </article>
          `
        )
        .join("")
    : '<article class="strategy-journal-entry"><p>No covered-call proposals recorded.</p></article>';
  const latestActivityMarkup = `
    <article class="strategy-journal-entry">
      <div class="strategy-journal-head">
        <strong>${escapeHtml(latestRun ? `${latestRun.run_type} / ${formatStrategyStatusLabel(latestRun.status)}` : "Latest signal")}</strong>
        <span>${escapeHtml(formatDateTime(latestRun?.created_at || latestSignal?.emitted_at))}</span>
      </div>
      <p>${escapeHtml(latestRun?.summary || latestRun?.reason || latestSignal?.summary || "No run or signal detail recorded.")}</p>
    </article>
  `;

  els.coveredCallActivityCard.className = "strategy-note-body";
  els.coveredCallActivityCard.innerHTML = `
    <div class="covered-call-activity-toolbar">
      <span>${escapeHtml(summary.latest_activity_at ? `Latest ${formatDateTime(summary.latest_activity_at)}` : "Lifecycle ready")}</span>
      <button class="table-action primary" type="button" data-covered-call-action="reconcile-lifecycle">
        Refresh Lifecycle
      </button>
    </div>
    <div class="proposal-detail-grid">
      ${summaryItems.map(renderStrategyProposalDetail).join("")}
    </div>
    ${latestMonitor ? renderCoveredCallLatestMonitor(latestMonitor) : ""}
    ${lifecycleMarkup}
    ${proposalMarkup}
    ${latestActivityMarkup}
  `;
}

function renderCoveredCallLatestMonitor(monitor) {
  const detailItems = [
    ["Underlying", formatNumber(monitor.underlying_price), monitor.symbol || "--"],
    ["Call Mark", formatCurrency(monitor.call_mark, "USD"), `DTE ${monitor.days_to_expiration ?? "--"}`],
    ["Open P/L", formatSignedCurrency(monitor.estimated_open_pnl, "USD"), "Against original premium"],
    ["Premium Capture", formatSignedPercentValue(monitor.premium_capture_pct), `Updated ${formatDateTime(monitor.emitted_at)}`],
  ];
  return `
    <article class="strategy-journal-entry covered-call-monitor-shell">
      <div class="strategy-journal-head">
        <strong>Latest Monitor</strong>
        <span class="pill ${strategyStatusClass(monitor.action)}">${escapeHtml(formatStrategyStatusLabel(monitor.action || "--"))}</span>
      </div>
      <div class="proposal-detail-grid">
        ${detailItems.map(renderStrategyProposalDetail).join("")}
      </div>
      <p>${escapeHtml(monitor.detail || "No covered-call monitor snapshot yet.")}</p>
    </article>
  `;
}

function renderCoveredCallLifecycleTask(task) {
  const orderParts = [
    task.open_order_id ? `Open ${task.open_order_id}` : "",
    task.close_order_id ? `Close ${task.close_order_id}` : "",
    task.roll_buyback_order_id ? `Buyback ${task.roll_buyback_order_id}` : "",
    task.roll_sell_order_id ? `Sell ${task.roll_sell_order_id}` : "",
  ].filter(Boolean);
  const statusParts = [
    task.sequence_status ? `Sequence ${formatStrategyStatusLabel(task.sequence_status)}` : "",
    task.open_status ? `Open ${formatStrategyStatusLabel(task.open_status)}` : "",
    task.close_status ? `Close ${formatStrategyStatusLabel(task.close_status)}` : "",
    task.buyback_status ? `Buyback ${formatStrategyStatusLabel(task.buyback_status)}` : "",
    task.sell_status ? `Sell ${formatStrategyStatusLabel(task.sell_status)}` : "",
  ].filter(Boolean);
  const ageText = formatOrderAge(task.order_age_seconds);
  const diagnosticText = formatCoveredCallTaskDiagnostic(task);
  const suggestedAction = formatCoveredCallSuggestedAction(task);
  const pillClass = task.is_stale ? "warning" : strategyStatusClass(task.proposal_status);
  return `
    <div class="lifecycle-task-item ${task.is_stale ? "is-stale" : ""}">
      <div class="strategy-journal-head">
        <strong>${escapeHtml([formatStrategyStatusLabel(task.task_type), task.symbol].filter(Boolean).join(" / "))}</strong>
        <span class="pill ${pillClass}">${escapeHtml(formatStrategyStatusLabel(task.last_refresh_status || task.proposal_status))}</span>
      </div>
      <p>${escapeHtml(task.proposal_title || task.proposal_id)}</p>
      <div class="lifecycle-task-grid">
        ${renderStrategyProposalDetail(["Proposal", task.proposal_id || "--", formatStrategyStatusLabel(task.proposal_status)])}
        ${renderStrategyProposalDetail(["Orders", orderParts.join(" / ") || "--", task.last_run_type || "--"])}
        ${renderStrategyProposalDetail(["Status", statusParts.join(" / ") || formatStrategyStatusLabel(task.last_refresh_status || "--"), `Last ${formatDateTime(task.last_refresh_at)}`])}
        ${renderStrategyProposalDetail(["Age", ageText || "--", task.is_stale ? "Stale working order" : "Working order"])}
        ${suggestedAction ? renderStrategyProposalDetail(["Suggested", suggestedAction, ""]) : ""}
      </div>
      ${diagnosticText ? `<p class="lifecycle-task-diagnostic">${escapeHtml(diagnosticText)}</p>` : ""}
      ${task.reason ? `<p>${escapeHtml(task.reason)}</p>` : ""}
    </div>
  `;
}

function renderStrategyExperiment() {
  const experiment = state.strategyExperiment || { proposals: [], runs: [], signals: [], reviews: [] };
  const proposals = Array.isArray(experiment.proposals) ? experiment.proposals : [];
  const runs = Array.isArray(experiment.runs) ? experiment.runs : [];
  const signals = Array.isArray(experiment.signals) ? experiment.signals : [];
  const reviews = Array.isArray(experiment.reviews) ? experiment.reviews : [];
  const pendingProposals = proposals.filter((proposal) => proposal.status === "pending");
  const latestRun = runs[0] || null;
  const latestSignal = signals[0] || null;
  const latestReview = reviews[0] || null;

  if (els.strategyExperimentStrip) {
    const summaryValues = [
      {
        label: "Active Proposals",
        value: String(pendingProposals.length),
        tone: pendingProposals.length ? "warning" : "",
        detail: proposals.length ? `${proposals.length} tracked proposal${proposals.length === 1 ? "" : "s"}` : "No strategy proposals loaded.",
      },
      {
        label: "Latest Run",
        value: latestRun ? formatStrategyStatusLabel(latestRun.status) : "--",
        tone: latestRun ? strategyStatusClass(latestRun.status) : "",
        detail: latestRun ? `${latestRun.strategy_id} / ${formatDateTime(latestRun.created_at)}` : "No strategy runs recorded.",
      },
      {
        label: "Signals",
        value: String(signals.length),
        tone: latestSignal ? strategyStatusClass(latestSignal.signal_type) : "",
        detail: latestSignal ? `${latestSignal.signal_type} / ${formatDateTime(latestSignal.emitted_at)}` : "No strategy signals recorded.",
      },
      {
        label: "Reviews",
        value: String(reviews.length),
        tone: latestReview ? strategyStatusClass(latestReview.status) : "",
        detail: latestReview ? `${latestReview.review_type} / ${formatDateTime(latestReview.reviewed_at)}` : "No strategy reviews recorded.",
      },
    ];
    els.strategyExperimentStrip.innerHTML = summaryValues
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
  }

  renderStrategyExperimentList({
    element: els.strategyProposalsCard,
    items: proposals,
    emptyText: "No strategy experiment proposals yet.",
    renderItem: (proposal) => `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>${escapeHtml(proposal.title)}</strong>
          <span class="pill ${strategyStatusClass(proposal.status)}">${escapeHtml(formatStrategyStatusLabel(proposal.status))}</span>
        </div>
        <p>${escapeHtml(proposal.rationale)}</p>
        <span>${escapeHtml([proposal.strategy_id, proposal.symbol, proposal.proposed_action].filter(Boolean).join(" / "))}</span>
        ${renderStrategyProposalDetails(proposal, proposals)}
        ${renderStrategyProposalActions(proposal)}
      </article>
    `,
  });
  renderStrategyExperimentList({
    element: els.strategyRunsCard,
    items: runs,
    emptyText: "No strategy runs recorded yet.",
    renderItem: (run) => `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>${escapeHtml(`${run.strategy_id} / ${run.run_type}`)}</strong>
          <span class="pill ${strategyStatusClass(run.status)}">${escapeHtml(formatStrategyStatusLabel(run.status))}</span>
        </div>
        <p>${escapeHtml(run.summary || run.reason || "Run recorded without a summary.")}</p>
        <span>${escapeHtml(formatDateTime(run.completed_at || run.started_at || run.created_at))}</span>
      </article>
    `,
  });
  renderStrategyExperimentList({
    element: els.strategySignalsCard,
    items: signals,
    emptyText: "No strategy signals recorded yet.",
    renderItem: (signal) => `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>${escapeHtml(signal.summary)}</strong>
          <span class="pill neutral">${escapeHtml(formatStrategyStatusLabel(signal.signal_type))}</span>
        </div>
        <p>${escapeHtml(signal.detail || [signal.strategy_id, signal.symbol].filter(Boolean).join(" / ") || "Signal recorded.")}</p>
        <span>${escapeHtml(formatDateTime(signal.emitted_at))}</span>
      </article>
    `,
  });
  renderStrategyExperimentList({
    element: els.strategyReviewsCard,
    items: reviews,
    emptyText: "No strategy reviews recorded yet.",
    renderItem: (review) => `
      <article class="strategy-journal-entry">
        <div class="strategy-journal-head">
          <strong>${escapeHtml(review.review_type)}</strong>
          <span class="pill ${strategyStatusClass(review.status)}">${escapeHtml(formatStrategyStatusLabel(review.status))}</span>
        </div>
        <p>${escapeHtml(review.recommendation || review.summary)}</p>
        <span>${escapeHtml(formatDateTime(review.reviewed_at))}</span>
      </article>
    `,
  });
}

function renderStrategyExperimentList({ element, items, emptyText, renderItem }) {
  if (!element) {
    return;
  }
  if (!items.length) {
    element.className = "strategy-note-body empty";
    element.textContent = emptyText;
    return;
  }
  element.className = "strategy-note-body";
  element.innerHTML = items.slice(0, 4).map(renderItem).join("");
}

function renderMarketEvents() {
  if (!els.marketEventsCard) {
    return;
  }
  const events = Array.isArray(state.marketEvents) ? state.marketEvents : [];
  if (!events.length) {
    els.marketEventsCard.className = "strategy-note-body empty";
    els.marketEventsCard.textContent = "No upcoming market events recorded.";
    return;
  }
  els.marketEventsCard.className = "strategy-note-body";
  els.marketEventsCard.innerHTML = events
    .slice(0, 6)
    .map(
      (event) => `
        <article class="strategy-journal-entry">
          <div class="strategy-journal-head">
            <strong>${escapeHtml(event.title)}</strong>
            <span class="pill ${strategyStatusClass(event.severity)}">${escapeHtml(formatStrategyStatusLabel(event.severity))}</span>
          </div>
          <p>${escapeHtml([event.symbol || "Market", event.event_type, event.source].filter(Boolean).join(" / "))}</p>
          <span>${escapeHtml(formatDateTime(event.scheduled_at))}</span>
        </article>
      `
    )
    .join("");
}

    return {
      renderStrategyRuntime,
      renderZeroDteLottery,
      renderZeroDteLotteryResult,
      renderCoveredCallActivity,
      renderStrategyExperiment,
      renderMarketEvents,
    };
  }
  window.StocksToolStrategyView = { createStrategyView };
})();

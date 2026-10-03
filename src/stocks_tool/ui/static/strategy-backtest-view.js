(function () {
  "use strict";

  let initialized = false;
  let loadToken = 0;
  let runs = [];
  let datasets = [];
  let selectedRun = null;
  let detailToken = 0;

  function ui() { return window.StocksToolWorkbenchUI; }
  function node(id) { return document.getElementById(id); }

  function setStatus(message, tone = "neutral") {
    const status = node("backtest-status");
    if (!status) return;
    status.textContent = message || "";
    status.dataset.tone = tone;
  }

  function strategyLabel(value) {
    return ({ bull_put: ui().text("牛市看跌", "Bull Put"), covered_call: ui().text("备兑看涨", "Covered Call"), zero_dte: ui().text("零日期权（仅预览）", "Zero-DTE (preview only)") })[value] || value || "--";
  }

  function stateLabel(value) {
    return ({ queued: ui().text("排队中", "Queued"), running: ui().text("运行中", "Running"), succeeded: ui().text("已完成", "Succeeded"), failed: ui().text("失败", "Failed"), cancelled: ui().text("已取消", "Cancelled"), interrupted: ui().text("已中断", "Interrupted"), blocked_data: ui().text("缺少数据", "Blocked data") })[value] || value || "--";
  }

  function normaliseRuns(payload) {
    const items = ui().arrayPayload(payload, ["items", "runs", "results"]);
    return items.map((run) => ({
      id: run.id || run.run_id,
      status: run.status || run.state || "unknown",
      strategy: run.strategy_id || run.strategy || "--",
      dataset: run.dataset_id || run.dataset || "local history",
      created: run.created_at || run.started_at || run.generated_at,
      coverage: run.coverage || run.data_coverage || { start: run.start_date, end: run.end_date, bars: run.result?.equity_curve?.length },
      metrics: run.metrics || run.result?.metrics || run.summary || {},
      warnings: Array.isArray(run.warnings) ? run.warnings : Array.isArray(run.result?.warnings) ? run.result.warnings : [],
      raw: run,
    })).filter((run) => run.id);
  }

  function renderDatasets() {
    const select = node("backtest-dataset");
    if (!select) return;
    const valid = datasets.filter((dataset) => dataset?.id);
    select.replaceChildren();
    if (!valid.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = ui().text("没有已注册数据集", "No registered dataset");
      select.appendChild(option);
      select.disabled = true;
      return;
    }
    select.disabled = false;
    valid.forEach((dataset) => {
      const option = document.createElement("option");
      option.value = dataset.id;
      option.textContent = `${dataset.name || dataset.id} / ${dataset.status || "unknown"}`;
      select.appendChild(option);
    });
    renderFreezeSources();
  }

  function renderFreezeSources() {
    const select = node("backtest-freeze-source-run-id");
    if (!select) return;
    select.replaceChildren();
    const none = document.createElement("option");
    none.value = "";
    none.textContent = ui().text("无（组合/开发/验证）", "None (development/validation/composite)");
    select.appendChild(none);
    runs.filter((run) => String(run.status).toLowerCase() === "succeeded" && (run.raw?.run_manifest?.period_segment === "validation" || run.raw?.period_segment === "validation")).forEach((run) => {
      const option = document.createElement("option");
      option.value = run.id;
      option.textContent = `${run.strategy} · ${run.raw?.start_date || "--"} → ${run.raw?.end_date || "--"} · ${run.id.slice(0, 8)}`;
      select.appendChild(option);
    });
  }

  function syncStrategyInputs() {
    const strategy = node("backtest-strategy")?.value || "bull_put";
    document.querySelectorAll(".backtest-covered-call-field").forEach((field) => { field.hidden = strategy !== "covered_call"; });
  }

  function renderList() {
    const body = node("backtest-runs-body");
    if (!body) return;
    if (!runs.length) {
      body.innerHTML = `<tr><td colspan="6" class="empty-row">${ui().escapeHtml(ui().text("没有历史回测记录。先选择数据集并显式运行。", "No historical backtest runs. Choose a dataset and run explicitly."))}</td></tr>`;
      return;
    }
    body.innerHTML = runs.slice(0, 20).map((run) => `<tr class="${run.id === selectedRun?.id ? "is-selected" : ""}"><td><button class="workbench-list-link" type="button" data-backtest-run="${ui().escapeHtml(run.id)}">${ui().escapeHtml(run.id)}</button></td><td>${ui().escapeHtml(strategyLabel(run.strategy))}</td><td>${ui().escapeHtml(run.dataset)}</td><td>${ui().escapeHtml(stateLabel(String(run.status).toLowerCase()))}</td><td>${ui().escapeHtml(ui().dateTime(run.created))}</td><td>${ui().escapeHtml(formatMetric(run.metrics))}</td></tr>`).join("");
    updateActions();
  }

  function updateActions() {
    const start = node("backtest-start-button");
    const compare = node("backtest-compare-button");
    const cancel = node("backtest-cancel-button");
    if (start) start.disabled = !selectedRun || String(selectedRun.status).toLowerCase() !== "queued";
    if (compare) compare.disabled = runs.length < 2;
    if (cancel) cancel.disabled = !selectedRun || !["queued", "running"].includes(String(selectedRun.status).toLowerCase());
  }

  function formatMetric(metrics) {
    const payload = ui().objectPayload(metrics);
    const returnValue = payload.total_return_pct ?? payload.return_pct ?? payload.total_return;
    const drawdown = payload.max_drawdown_pct ?? payload.max_drawdown;
    return [returnValue == null ? "" : `${ui().percent(returnValue)} ${ui().text("收益", "return")}`, drawdown == null ? "" : `${ui().percent(drawdown)} ${ui().text("回撤", "drawdown")}`].filter(Boolean).join(" / ") || "--";
  }

  function renderDetail() {
    const detail = node("backtest-explanation-summary");
    const facts = node("backtest-explanation-facts");
    const status = node("backtest-explanation-status");
    if (!detail || !facts || !status) return;
    if (!selectedRun) {
      status.textContent = ui().text("等待选择", "Waiting");
      detail.textContent = ui().text("回测结果只使用明确选择的数据集和参数。没有完整覆盖范围时，会显示‘缺少数据（BLOCKED_DATA）’。", "Backtests use only an explicitly selected dataset and parameters. Incomplete coverage is shown as missing data (BLOCKED_DATA).");
      facts.innerHTML = "";
      renderResultChart(null);
      return;
    }
    const coverage = ui().objectPayload(selectedRun.coverage);
    const metrics = ui().objectPayload(selectedRun.metrics);
    const state = String(selectedRun.status || "unknown").toLowerCase();
    const blocked = state.includes("blocked") || state.includes("data");
    const failed = ["failed", "cancelled", "interrupted"].includes(state);
    const succeeded = state === "succeeded";
    status.textContent = blocked ? ui().text("缺少数据（BLOCKED_DATA）", "Missing data (BLOCKED_DATA)") : failed ? ui().text(`运行${state === "cancelled" ? "已取消" : "失败"}`, `Run ${state}`) : selectedRun.status;
    status.dataset.tone = blocked || failed ? "error" : succeeded ? "success" : "warning";
    const warningCodes = [...(Array.isArray(selectedRun.warnings) ? selectedRun.warnings : []), ...(Array.isArray(selectedRun.raw?.result?.warnings) ? selectedRun.raw.result.warnings : [])];
    const warningCopy = {
      initial_stock_provider_start_metrics_invalidated: ui().text("初始持仓导致引擎起点指标不可信，CAGR/Sharpe 不可用。", "Initial holdings invalidate engine-start metrics; CAGR/Sharpe are unavailable."),
      time_zero_marked_equity_drawdown_baseline: ui().text("最大回撤从扣除初始费用后的起点净值计算。", "Max drawdown starts from equity after initial fees are deducted."),
    };
    const warningHtml = warningCodes.length
      ? `<ul class="workbench-explanation-list">${warningCodes.map((warning) => `<li>${ui().escapeHtml(warningCopy[warning] || warning)}</li>`).join("")}</ul>`
      : "";
    const fee = ui().objectPayload(selectedRun.raw?.fee_model);
    const slippage = ui().objectPayload(selectedRun.raw?.slippage_model);
    const feeText = [fee.name, fee.commission_per_contract && `每合约 ${fee.commission_per_contract}`, fee.minimum_commission && `最低 ${fee.minimum_commission}`, fee.commission_rate && `费率 ${fee.commission_rate}`, fee.exchange_fee_per_contract && `交易所费 ${fee.exchange_fee_per_contract}`].filter(Boolean).join(" · ") || "--";
    const slippageText = [slippage.name, slippage.basis_points != null && `${slippage.basis_points} bps`, slippage.fixed_per_contract && `每合约固定 ${slippage.fixed_per_contract}`].filter(Boolean).join(" · ") || "--";
    const explanation = blocked
      ? ui().text("数据覆盖不足，不能把这次运行解释成策略结果。", "Data coverage is incomplete; this run cannot be treated as a strategy result.")
      : failed
        ? `${ui().text("这次回测没有产生可用绩效结果。原因", "This run did not produce usable performance results. Reason")}: ${selectedRun.raw?.error || warningCodes.join("；") || ui().text("未记录", "Not recorded")}`
        : succeeded
          ? `${ui().text("这是历史模拟结果，不会下单。结果来源", "This is a historical simulation; no orders are submitted. Evidence source")}: ${selectedRun.raw?.run_manifest?.data_hash || selectedRun.raw?.data_hash || selectedRun.dataset || "--"}。${ui().text("最大回撤定义：从历史峰值净值到之后最低净值的最大跌幅。", "Max drawdown means the largest decline from a historical equity peak to a later trough.")}`
          : ui().text("任务尚未完成，当前只显示运行状态。", "The job is not complete; only its run state is shown.");
    const rawEvidence = {
      run_manifest: selectedRun.raw?.run_manifest || null,
      result: selectedRun.raw?.result || null,
      trades: selectedRun.raw?.result?.trades || selectedRun.raw?.trades || [],
      events: selectedRun.raw?.events || selectedRun.raw?.result?.events || [],
    };
    detail.innerHTML = `${ui().escapeHtml(explanation)}${warningHtml}<span class="workbench-data-badge" data-quality="partial">${ui().escapeHtml(ui().text("费用假设", "Fee assumption"))}: ${ui().escapeHtml(feeText)} · ${ui().escapeHtml(ui().text("滑点假设", "Slippage assumption"))}: ${ui().escapeHtml(slippageText)}</span><details class="workbench-raw-details"><summary>${ui().escapeHtml(ui().text("查看可核对运行证据", "Inspect run evidence"))}</summary><dl class="workbench-facts"><div><dt>Code</dt><dd>${ui().escapeHtml(selectedRun.raw?.code_version || "--")}</dd></div><div><dt>Engine</dt><dd>${ui().escapeHtml(selectedRun.raw?.engine_version || "--")}</dd></div><div><dt>Image</dt><dd>${ui().escapeHtml(selectedRun.raw?.engine_image_digest || "--")}</dd></div><div><dt>Data hash</dt><dd>${ui().escapeHtml(selectedRun.raw?.data_hash || selectedRun.raw?.run_manifest?.data_hash || "--")}</dd></div></dl><pre>${ui().escapeHtml(JSON.stringify(rawEvidence, null, 2))}</pre></details>`;
    facts.innerHTML = [
      [ui().text("数据集", "Dataset"), selectedRun.dataset],
      [ui().text("覆盖起点", "Coverage start"), coverage.start || coverage.from || "--"],
      [ui().text("覆盖终点", "Coverage end"), coverage.end || coverage.to || "--"],
      [ui().text("样本数", "Bars"), coverage.bars ?? coverage.count ?? "--"],
      [ui().text("收益", "Return"), succeeded ? ui().percent(metrics.total_return_pct ?? metrics.return_pct ?? metrics.total_return) : "--"],
      [ui().text("最大回撤", "Max drawdown"), succeeded ? ui().percent(metrics.max_drawdown_pct ?? metrics.max_drawdown) : "--"],
      [ui().text("净盈亏", "Net PnL"), succeeded ? ui().money(metrics.net_pnl ?? metrics.pnl) : "--"],
      [ui().text("费用", "Fees"), succeeded ? ui().money(metrics.fees ?? metrics.total_fees) : "--"],
      [ui().text("交易次数", "Trades"), succeeded ? (metrics.trade_count ?? metrics.trades ?? "--") : "--"],
      [ui().text("费用假设", "Fee assumption"), feeText],
      [ui().text("滑点假设", "Slippage assumption"), slippageText],
    ].map(([label, value]) => `<div><dt>${ui().escapeHtml(label)}</dt><dd>${ui().escapeHtml(String(value))}</dd></div>`).join("");
    renderResultChart(succeeded ? (selectedRun.raw?.result?.equity_curve || selectedRun.raw?.equity_curve || []) : null);
  }

  function renderResultChart(rawCurve) {
    const chart = node("backtest-result-chart");
    if (!chart) return;
    const curve = Array.isArray(rawCurve) ? rawCurve.map((point) => ({
      time: point?.timestamp || point?.captured_at || point?.date || point?.time,
      value: ui().numberValue(point?.equity ?? point?.value ?? point?.net_liquidation, null),
    })).filter((point) => point.time && point.value !== null) : [];
    if (!curve.length) {
      chart.innerHTML = `<div class="workbench-chart-empty">${ui().escapeHtml(ui().text("没有可绘制的净值曲线；这不代表结果为零。", "No equity curve was returned; this does not mean the result is zero."))}</div>`;
      return;
    }
    const width = 680;
    const height = 220;
    const values = curve.map((point) => point.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const points = curve.map((point, index) => `${18 + index / Math.max(1, curve.length - 1) * (width - 36)},${14 + (1 - (point.value - min) / span) * (height - 42)}`).join(" ");
    chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${ui().escapeHtml(ui().text("回测净值曲线", "Backtest equity curve"))}"><line x1="18" y1="${height - 28}" x2="${width - 18}" y2="${height - 28}" stroke="#d8e2de"/><polyline points="${points}" fill="none" stroke="#0b6e69" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><text x="18" y="${height - 8}" fill="#61706d" font-size="11">${ui().escapeHtml(ui().dateTime(curve[0].time))}</text><text x="${width - 18}" y="${height - 8}" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(ui().dateTime(curve[curve.length - 1].time))}</text><text x="${width - 18}" y="18" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(ui().money(max))}</text><text x="${width - 18}" y="${height - 32}" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(ui().money(min))}</text></svg>`;
  }

  async function loadRuns() {
    const state = ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    if (!accountId) return;
    const token = ++loadToken;
    setStatus(ui().text("正在读取历史回测…", "Loading historical backtests…"));
    const result = await ui().loadScopedReads([
      { key: "runs", url: "/backtests?limit=100" },
      { key: "datasets", url: "/backtests/datasets" },
    ], state).catch((error) => ({ discarded: false, values: {}, errors: { runs: error?.message || "backtest data unavailable", datasets: error?.message || "dataset data unavailable" } }));
    if (result.discarded || token !== loadToken || accountId !== ui().accountId()) return;
    const response = result.values.runs;
    datasets = Array.isArray(result.values.datasets) ? result.values.datasets : [];
    renderDatasets();
    if (!response) {
      runs = [];
      selectedRun = null;
      setStatus(`${ui().text("回测数据暂时不可用", "Backtest data unavailable")}（BLOCKED_DATA）：${result.errors.runs || ""}`, "error");
      renderList();
      renderDetail();
      return;
    }
    runs = normaliseRuns(response);
    if (selectedRun) selectedRun = runs.find((run) => run.id === selectedRun.id) || selectedRun;
    setStatus(ui().text(`${runs.length} 条历史回测记录`, `${runs.length} historical backtest run(s)`), "success");
    renderList();
    renderFreezeSources();
    syncStrategyInputs();
    renderDetail();
  }

  async function runBacktest() {
    const state = ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    const dataset = node("backtest-dataset")?.value || "";
    const strategy = node("backtest-strategy")?.value || "bull_put";
    if (!dataset) {
      setStatus(ui().text("先选择有效数据集。", "Select a valid dataset first."), "warning");
      return;
    }
    const periodSegment = node("backtest-period-segment")?.value || "composite";
    const freezeSource = node("backtest-freeze-source-run-id")?.value || null;
    if (["holdout", "composite"].includes(periodSegment) && !freezeSource) {
      setStatus(ui().text("当前区间需要先选择已完成验证冻结来源。", "This date range requires a completed validation freeze source."), "warning");
      return;
    }
    const requestedSymbol = String(node("strategy-evaluation-symbol")?.value || ui().selectedSymbol() || "QQQ").trim().toUpperCase().replace(/\.US$/, "");
    const symbols = String(node("backtest-symbols")?.value || requestedSymbol || "QQQ").split(",").map((value) => value.trim().toUpperCase().replace(/\.US$/, "")).filter(Boolean);
    const initialLots = [];
    if (strategy === "covered_call") {
      const lotSymbol = String(node("backtest-initial-stock-symbol")?.value || "").trim().toUpperCase().replace(/\.US$/, "");
      const quantity = node("backtest-initial-stock-quantity")?.value || "";
      const acquisitionPrice = node("backtest-initial-stock-price")?.value || "";
      if (!lotSymbol || !quantity || !acquisitionPrice) {
        setStatus(ui().text("备兑看涨回测需要明确的初始股票批次、股数和取得价格。", "Covered Call backtests require explicit initial stock lots, quantity, and acquisition price."), "warning");
        return;
      }
      initialLots.push({ symbol: lotSymbol, quantity, acquisition_price: acquisitionPrice, acquisition_fee: "0" });
    }
    setStatus(ui().text("正在提交历史回测任务…", "Submitting historical backtest job…"));
    try {
      const response = await ui().fetchJson("/backtests", {
        method: "POST",
        body: JSON.stringify({
          dataset_id: dataset,
          strategy,
          symbols,
          start_date: node("backtest-start-date")?.value || "2020-01-01",
          end_date: node("backtest-end-date")?.value || "2026-09-30",
          initial_cash: node("backtest-initial-cash")?.value || "100000",
          parameters: { source: "local_history", no_paid_data: true },
          fee_model: { name: "explicit_fee", commission_per_contract: node("backtest-fee-per-contract")?.value || "0" },
          slippage_model: { name: "explicit_slippage", basis_points: node("backtest-slippage-bps")?.value || "0" },
          lifecycle_model: { name: "explicit_options_lifecycle" },
          period_segment: periodSegment,
          freeze_source_run_id: freezeSource,
          initial_stock_lots: strategy === "covered_call" ? initialLots.map((lot) => ({ ...lot, acquisition_fee: node("backtest-initial-stock-fee")?.value || "0" })) : initialLots,
          formal: true,
          research_only: strategy === "zero_dte",
        }),
      });
      if (state.selectedAccountId !== ui().accountId() || state.accountLoadGeneration !== ui().getState()?.accountLoadGeneration) return;
      const next = normaliseRuns([response?.run || response]);
      if (next[0]) selectedRun = next[0];
      setStatus(ui().text("回测任务已提交，等待结果。", "Backtest job submitted; waiting for results."), "success");
      await loadRuns();
    } catch (error) {
      setStatus(`${ui().text("回测服务暂时不可用", "Backtest service unavailable")}（BLOCKED_DATA）：${error?.message || ""}`, "error");
    }
  }

  async function selectRun(runId) {
    const found = runs.find((run) => run.id === runId);
    if (!found) return;
    const requestToken = ++detailToken;
    selectedRun = found;
    renderList();
    renderDetail();
    try {
      const state = ui().getState() || {};
      const result = await ui().loadScopedReads([
        { key: "detail", url: `/backtests/${encodeURIComponent(runId)}` },
      ], state);
      if (result.discarded || requestToken !== detailToken || selectedRun?.id !== runId) return;
      const detail = result.values.detail;
      if (!detail) throw new Error(result.errors.detail || "backtest detail unavailable");
      const updated = normaliseRuns([detail?.run || detail])[0];
      if (updated) selectedRun = updated;
      renderList();
      renderDetail();
      updateActions();
    } catch (error) {
      setStatus(`${ui().text("回测详情暂时不可用", "Backtest detail unavailable")}（BLOCKED_DATA）：${error?.message || ""}`, "error");
    }
  }

  async function startSelected() {
    if (!selectedRun) return;
    const state = ui().getState() || {};
    setStatus(ui().text("正在启动选中的回测任务…", "Starting the selected backtest job…"));
    try {
      const response = await ui().fetchJson(`/backtests/${encodeURIComponent(selectedRun.id)}/start`, { method: "POST" });
      if (state.accountLoadGeneration !== ui().getState()?.accountLoadGeneration || state.selectedAccountId !== ui().accountId()) return;
      const next = normaliseRuns([response])[0] || selectedRun;
      selectedRun = next;
      const nextState = String(next.status || "unknown").toLowerCase();
      if (nextState === "queued") {
        setStatus(ui().text("任务仍在排队，服务尚未确认已开始。", "The job is still queued; the service has not confirmed a start."), "warning");
      } else if (["running", "succeeded"].includes(nextState)) {
        setStatus(ui().text("回测任务已确认开始。", "Backtest job start confirmed."), "success");
      } else {
        setStatus(`${ui().text("回测任务状态", "Backtest job state")}: ${next.status}`, "warning");
      }
      await loadRuns();
    } catch (error) {
      setStatus(`${ui().text("回测任务无法启动", "Backtest job could not start")}（BLOCKED_DATA）：${error?.message || ""}`, "error");
    }
  }

  async function cancelSelected() {
    if (!selectedRun || !["queued", "running"].includes(String(selectedRun.status).toLowerCase())) return;
    const state = ui().getState() || {};
    const runId = selectedRun.id;
    try {
      const response = await ui().fetchJson(`/backtests/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
      if (state.accountLoadGeneration !== ui().getState()?.accountLoadGeneration || state.selectedAccountId !== ui().accountId() || selectedRun?.id !== runId) return;
      const next = normaliseRuns([response])[0];
      if (next) selectedRun = next;
      if (String(selectedRun.status).toLowerCase() === "cancelled") {
        setStatus(ui().text("回测任务已取消。", "Backtest job cancelled."), "success");
      } else {
        setStatus(`${ui().text("任务返回状态", "Job returned state")}: ${selectedRun.status}`, "warning");
      }
      renderList();
      renderDetail();
    } catch (error) {
      setStatus(`${ui().text("回测任务无法取消", "Backtest job could not be cancelled")}（BLOCKED_DATA）：${error?.message || ""}`, "error");
    }
  }

  async function compareSelected() {
    if (runs.length < 2) return;
    const primary = selectedRun || runs[0];
    const secondary = runs.find((run) => run.id !== primary.id) || runs[1];
    try {
      const comparison = await ui().fetchJson("/backtests/compare", {
        method: "POST",
        body: JSON.stringify({ run_ids: [primary.id, secondary.id] }),
      });
      const detail = node("backtest-explanation-summary");
      if (detail) detail.textContent = ui().text(`已比较 ${primary.id} 与 ${secondary.id}。${comparison?.warnings?.join("；") || ""}`, `Compared ${primary.id} and ${secondary.id}. ${comparison?.warnings?.join("; ") || ""}`);
      setStatus(ui().text("两次历史回测已比较。", "Two historical backtests compared."), "success");
    } catch (error) {
      setStatus(`${ui().text("回测比较暂时不可用", "Backtest comparison unavailable")}（BLOCKED_DATA）：${error?.message || ""}`, "error");
    }
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    node("backtest-run-button")?.addEventListener("click", () => { void runBacktest(); });
    node("backtest-start-button")?.addEventListener("click", () => { void startSelected(); });
    node("backtest-cancel-button")?.addEventListener("click", () => { void cancelSelected(); });
    node("backtest-compare-button")?.addEventListener("click", () => { void compareSelected(); });
    node("backtest-strategy")?.addEventListener("change", syncStrategyInputs);
    syncStrategyInputs();
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-backtest-run]");
      if (button) void selectRun(button.dataset.backtestRun);
    });
    ui().subscribe((event) => {
      if (event.type === "workspace" && event.workspace === "strategy") void loadRuns();
      if (event.type === "account-state" && ui().getWorkspace() === "strategy") void loadRuns();
    });
    renderDetail();
    updateActions();
  }

  window.StocksToolBacktests = { init: bind, load: loadRuns };
  document.addEventListener("DOMContentLoaded", bind, { once: true });
})();

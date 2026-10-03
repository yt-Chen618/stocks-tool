(function () {
  "use strict";

  let initialized = false;
  let loadToken = 0;
  let accountId = "";
  let analytics = null;
  let risk = null;

  function ui() { return window.StocksToolWorkbenchUI; }
  function node(id) { return document.getElementById(id); }

  function currencyFor(payload) {
    const currency = String(payload?.currency || "").trim().toUpperCase();
    return /^[A-Z]{3}$/.test(currency) ? currency : null;
  }

  function moneyValue(value, currency) {
    if (value === null || value === undefined || value === "") return "--";
    return currency ? ui().money(value, currency) : ui().text("货币未知", "Currency unknown");
  }

  function pick(payload, keys, fallback = null) {
    const source = ui().objectPayload(payload);
    for (const key of keys) {
      if (source[key] !== undefined && source[key] !== null) return source[key];
    }
    return fallback;
  }

  function seriesFrom(payload) {
    const raw = Array.isArray(payload) ? payload : pick(payload, ["series", "points", "nav_series", "equity_curve", "history"], []);
    return (Array.isArray(raw) ? raw : []).map((item) => ({
      time: item?.time || item?.timestamp || item?.date || item?.captured_at,
      value: ui().numberValue(item?.value ?? item?.nav ?? item?.net_liquidation ?? item?.equity ?? item?.close),
      label: item?.label || item?.date || item?.timestamp,
      timeValue: Date.parse(item?.time || item?.timestamp || item?.date || item?.captured_at || ""),
    })).filter((item) => item.time && item.value !== null && Number.isFinite(item.timeValue)).sort((left, right) => left.timeValue - right.timeValue);
  }

  function renderSvg(series, currency = null) {
    const chart = node("portfolio-equity-chart");
    if (!chart) return;
    if (!series.length) {
      chart.innerHTML = `<div class="workbench-chart-empty"><div><strong>${ui().escapeHtml(ui().text("缺少历史净值", "Historical NAV unavailable"))}</strong><br /><span class="workbench-code">BLOCKED_DATA</span> · ${ui().escapeHtml(ui().text("暂无可用的历史净值数据。", "No historical portfolio series is available."))}</div></div>`;
      return;
    }
    const width = 720;
    const height = 250;
    const pad = { left: 18, right: 16, top: 18, bottom: 24 };
    const values = series.map((item) => item.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const firstTime = series[0].timeValue;
    const lastTime = series[series.length - 1].timeValue;
    const timeSpan = lastTime - firstTime || 1;
    const points = series.map((item) => {
      const x = pad.left + ((item.timeValue - firstTime) / timeSpan) * (width - pad.left - pad.right);
      const y = pad.top + (1 - (item.value - min) / span) * (height - pad.top - pad.bottom);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    }).join(" ");
    const hasGap = series.some((item, index) => index > 0 && item.timeValue - series[index - 1].timeValue > 45 * 24 * 60 * 60 * 1000);
    chart.innerHTML = `
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${ui().escapeHtml(ui().text("组合净值曲线", "Portfolio equity curve"))}">
        <defs><linearGradient id="portfolio-equity-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#0b6e69" stop-opacity=".20"/><stop offset="1" stop-color="#0b6e69" stop-opacity="0"/></linearGradient></defs>
        <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#d8e2de" />
        <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" stroke="#d8e2de" />
        <polyline points="${points}" fill="none" stroke="#0b6e69" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />
        <text x="${pad.left}" y="${height - 5}" fill="#61706d" font-size="11">${ui().escapeHtml(ui().dateTime(series[0].time))}</text>
        <text x="${width - pad.right}" y="${height - 5}" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(ui().dateTime(series[series.length - 1].time))}</text>
        <text x="${width - pad.right}" y="${pad.top + 4}" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(moneyValue(max, currency))}</text>
        <text x="${width - pad.right}" y="${height - pad.bottom - 3}" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(moneyValue(min, currency))}</text>
        ${hasGap ? `<text x="${pad.left}" y="${pad.top + 15}" fill="#a46615" font-size="11">${ui().escapeHtml(ui().text("数据存在日期缺口", "Date gaps in source data"))}</text>` : ""}
      </svg>
    `;
  }

  function renderRisk() {
    const chart = node("portfolio-risk-bars");
    if (!chart) return;
    const riskObject = ui().objectPayload(risk);
    const currency = currencyFor(riskObject);
    const rawItems = Array.isArray(risk) ? risk : (Array.isArray(riskObject.concentrations) ? riskObject.concentrations : []);
    const items = rawItems.map((item) => ({
      label: item?.label || item?.name || item?.strategy || item?.symbol || "Risk",
      used: ui().numberValue(item?.used ?? item?.value ?? item?.exposure ?? item?.exposure_value ?? item?.known_max_loss ?? item?.market_value, null),
      limit: ui().numberValue(item?.limit ?? item?.cap ?? item?.budget, null),
      percent: ui().numberValue(item?.weight_of_net_liquidation, null),
      tone: item?.risk_level === "unknown" || item?.status === "blocked" || item?.status === "fail" ? "error" : item?.status === "warn" ? "warning" : "unknown",
    })).filter((item) => item.label);
    if (!items.length) {
      chart.innerHTML = `<div class="workbench-blocked"><div><strong>${ui().escapeHtml(ui().text("暂时无法计算风险", "Risk budget unavailable"))}</strong><br /><span class="workbench-code">BLOCKED_DATA</span> · ${ui().escapeHtml(ui().text("风险预算接口尚未提供数据。", "Risk budget data is not available."))}</div></div>`;
    } else {
      chart.innerHTML = items.slice(0, 8).map((item) => {
      const rawPercent = ui().numberValue(item.percent ?? item.utilization_pct ?? item.used_pct, null);
      const explicitPercent = rawPercent === null ? null : rawPercent * 100;
      const ratio = explicitPercent !== null ? explicitPercent : item.limit && item.limit > 0 && item.used !== null ? item.used / item.limit * 100 : null;
      const tone = item.tone === "unknown" || ratio === null ? "error" : item.tone;
      const width = ratio === null ? 0 : Math.min(100, Math.abs(ratio));
      return `<div class="workbench-bar-row"><div class="workbench-bar-label"><span>${ui().escapeHtml(item.label)}</span><strong>${ui().escapeHtml(ratio === null ? ui().text("无法计算", "Unavailable") : item.limit ? `${moneyValue(item.used, currency)} / ${moneyValue(item.limit, currency)}` : `${ratio.toFixed(1)}%`)}</strong></div><div class="workbench-bar-track"><div class="workbench-bar-fill" data-tone="${tone}" style="width:${width.toFixed(1)}%"></div></div></div>`;
      }).join("");
    }
    const strategyNode = node("portfolio-strategy-exposures");
    const strategyItems = Array.isArray(riskObject.strategy_exposures) ? riskObject.strategy_exposures : [];
    if (strategyNode) {
      strategyNode.innerHTML = strategyItems.length
        ? strategyItems.map((item) => `<div class="workbench-bar-row"><div class="workbench-bar-label"><span>${ui().escapeHtml(item.label || item.strategy_id || "Strategy")}</span><strong>${ui().escapeHtml(item.known_max_loss == null ? ui().text("最大损失未知", "Max loss unknown") : moneyValue(item.known_max_loss, currency))}</strong></div><div class="workbench-bar-label"><span>${ui().escapeHtml(item.symbol || "--")}</span><span>${ui().escapeHtml(item.status || "--")}</span></div></div>`).join("")
        : `<div class="workbench-blocked"><div>${ui().escapeHtml(ui().text("当前没有策略暴露记录。", "No strategy exposure records."))}</div></div>`;
    }
  }

  function renderExplanation() {
    const explanation = node("portfolio-explanation-summary");
    const facts = node("portfolio-explanation-facts");
    const status = node("portfolio-explanation-status");
    if (!explanation || !facts || !status) return;
    const payload = ui().objectPayload(analytics);
    const qualityPayload = ui().objectPayload(payload.data_quality);
    const currency = currencyFor(payload);
    const quality = pick(payload, ["quality", "status"], qualityPayload.unavailable?.length ? "partial" : qualityPayload.snapshot_stale ? "stale" : "available");
    const latestMeta = pick(payload, ["as_of", "generated_at", "captured_at", "latest_at"], null);
    const latest = ui().objectPayload(payload.latest);
    const change = ui().objectPayload(payload.change);
    const net = pick(payload, ["net_liquidation", "latest_net_liquidation", "nav"], latest.net_liquidation);
    const pnl = pick(payload, ["unrealized_pnl", "total_unrealized_pnl", "pnl"], change.investment_return);
    const drawdown = pick(payload, ["max_drawdown_pct", "drawdown_pct", "drawdown"], null);
    const provenance = latest.provenance || (qualityPayload.warnings || [])[0] || ui().text("本地快照", "Local snapshot");
    status.textContent = quality === "available" ? ui().text("组合证据可用", "Portfolio evidence ready") : `${ui().text("数据状态", "Data")}: ${ui().statusLabel(quality)}`;
    status.dataset.tone = quality === "available" ? "success" : quality === "unavailable" ? "error" : "warning";
    explanation.textContent = quality === "unavailable" || !analytics
      ? ui().text("当前没有足够的历史组合数据。这里不会用估算值填补缺口。", "Historical portfolio data is unavailable. The view will not fill the gap with estimates.")
      : `${ui().text("曲线展示已保存的账户快照变化；它说明组合发生了什么，不代表下一笔订单应该怎么做。", "The curve shows saved account snapshot changes. It explains what happened, not what the next order should be.")} ${ui().text("来源", "Source")}: ${provenance}`;
    facts.innerHTML = [
      [ui().text("最新净清算值", "Latest NAV"), moneyValue(net, currency)],
      [ui().text("投资收益率", "Investment return"), change.investment_return === null || change.investment_return === undefined ? ui().text(`暂时无法计算投资收益率：${change.investment_return_unavailable?.reason || "缺少完整出入金记录"}`, `Investment return unavailable: ${change.investment_return_unavailable?.reason || "complete cash-flow history is missing"}`) : ui().percent(change.investment_return)],
      [ui().text("净清算值变化", "NAV change"), moneyValue(change.net_liquidation_change, currency)],
      [ui().text("未实现盈亏", "Unrealized PnL"), moneyValue(pnl, currency)],
      [ui().text("最大回撤", "Max drawdown"), ui().percent(drawdown)],
      [ui().text("数据时间", "As of"), ui().dateTime(latestMeta || latest.captured_at)],
    ].map(([label, value]) => `<div><dt>${ui().escapeHtml(label)}</dt><dd>${ui().escapeHtml(value)}</dd></div>`).join("");
    const reviewList = node("portfolio-linked-review-list");
    if (reviewList) {
      const unavailable = Array.isArray(qualityPayload.unavailable) ? qualityPayload.unavailable : [];
      const links = ui().objectPayload(payload.links);
      const riskPayload = ui().objectPayload(risk);
      const knownLoss = ui().objectPayload(riskPayload.known_max_loss);
      const lines = [
        `${ui().text("关联订单", "Linked orders")}: ${links.orders?.length ?? 0}`,
        `${ui().text("关联成交", "Linked executions")}: ${links.executions?.length ?? 0}`,
        `${ui().text("关联日志", "Linked journals")}: ${links.journals?.length ?? 0}`,
        `${ui().text("已知最大损失范围", "Known max-loss scope")}: ${knownLoss.scope || "--"}`,
        `${ui().text("损失/净清算值比例", "Loss/NAV ratio")}: ${knownLoss.nav_ratio_pct == null ? (knownLoss.nav_ratio_unavailable?.reason || ui().text("未知", "Unknown")) : `${knownLoss.nav_ratio_pct}%`}`,
        `${ui().text("损失货币 / 净清算值货币", "Loss / NAV currency")}: ${knownLoss.loss_currency || "?"} / ${knownLoss.nav_currency || "?"}`,
        ...(Array.isArray(knownLoss.excluded_sources) && knownLoss.excluded_sources.length ? [`${ui().text("未纳入来源", "Excluded sources")}: ${knownLoss.excluded_sources.join("、")}`] : []),
        ...unavailable.slice(0, 3).map((item) => `${ui().text("假设/缺口", "Assumption/gap")}: ${item.reason || item.code || "--"}`),
      ];
      reviewList.innerHTML = lines.map((line) => `<li>${ui().escapeHtml(line)}</li>`).join("");
    }
  }

  function renderHoldingsTable(state) {
    const body = node("portfolio-analytics-body");
    if (!body) return;
    const allocation = Array.isArray(analytics?.allocation) ? analytics.allocation : [];
    const positions = allocation.length ? allocation : (Array.isArray(state?.latestSnapshot?.positions) ? state.latestSnapshot.positions : []);
    const currency = currencyFor(analytics);
    if (!positions.length) {
      body.innerHTML = `<tr><td colspan="5" class="empty-row">${ui().escapeHtml(ui().text("暂无持仓证据。", "No holding evidence."))}</td></tr>`;
      return;
    }
    body.innerHTML = positions.slice().sort((a, b) => (ui().numberValue(b.market_value, null) ?? Number.NEGATIVE_INFINITY) - (ui().numberValue(a.market_value, null) ?? Number.NEGATIVE_INFINITY)).map((item) => {
      const value = ui().numberValue(item.market_value, null);
      const rawWeight = ui().numberValue(item.weight_of_net_liquidation, null);
      const weight = rawWeight === null ? "--" : `${(rawWeight * 100).toFixed(1)}%`;
      return `<tr><td><button class="workbench-list-link" type="button" data-portfolio-symbol="${ui().escapeHtml(item.symbol)}">${ui().escapeHtml(item.symbol)}</button></td><td>${ui().escapeHtml(item.asset_type || "--")}</td><td>${ui().escapeHtml(item.quantity ?? "--")}</td><td>${ui().escapeHtml(moneyValue(value, currency))}</td><td>${ui().escapeHtml(value === null ? ui().text("不可用", "Unavailable") : weight)}</td></tr>`;
    }).join("");
  }

  async function load(accountOverride) {
    const snapshot = ui().getState() || {};
    accountId = accountOverride || snapshot.selectedAccountId || ui().accountId();
    if (!accountId) return;
    const token = ++loadToken;
    const end = new Date();
    const start = new Date(end.getTime() - 365 * 24 * 60 * 60 * 1000);
    const query = `external_account_id=${encodeURIComponent(accountId)}&mode=paper&start=${encodeURIComponent(start.toISOString())}&end=${encodeURIComponent(end.toISOString())}&max_points=500`;
    const result = await ui().loadScopedReads([
      { key: "analytics", url: `/portfolio/analytics?${query}` },
      { key: "risk", url: `/portfolio/risk?external_account_id=${encodeURIComponent(accountId)}&mode=paper` },
    ], snapshot).catch((error) => ({ discarded: false, values: {}, errors: { analytics: error?.message || "read failed", risk: error?.message || "read failed" } }));
    if (result.discarded || token !== loadToken || accountId !== ui().accountId()) {
      return;
    }
    analytics = result.values.analytics || { status: "unavailable", error: result.errors.analytics || "analytics unavailable" };
    risk = result.values.risk || { status: "unavailable", error: result.errors.risk || "risk unavailable" };
    renderSvg(seriesFrom(analytics), currencyFor(analytics));
    renderRisk();
    renderExplanation();
    renderHoldingsTable(ui().getState());
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-portfolio-symbol]");
      if (!button) return;
      const symbol = button.dataset.portfolioSymbol;
      window.StocksToolWorkspace?.selectWorkspace?.("research");
      window.StocksToolResearch?.selectSymbol?.(symbol);
    });
    node("portfolio-refresh-analytics")?.addEventListener("click", () => { void load(); });
    node("portfolio-open-research")?.addEventListener("click", () => {
      window.StocksToolWorkspace?.selectWorkspace?.("research");
      const first = ui().getState()?.latestSnapshot?.positions?.[0]?.symbol;
      if (first) window.StocksToolResearch?.selectSymbol?.(first);
    });
    ui().subscribe((event) => {
      if (event.type === "workspace" && event.workspace === "portfolio") void load();
      if (event.type === "account-state") {
        renderHoldingsTable(event.state);
        if (ui().getWorkspace() === "portfolio") void load(event.state?.selectedAccountId);
      }
    });
    renderExplanation();
  }

  window.StocksToolPortfolio = { init: bind, load };
  document.addEventListener("DOMContentLoaded", bind, { once: true });
})();

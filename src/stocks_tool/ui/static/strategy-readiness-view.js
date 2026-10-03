(function () {
  "use strict";

  let initialized = false;
  let loadToken = 0;
  let riskPayload = null;
  let readinessToken = 0;

  function ui() { return window.StocksToolWorkbenchUI; }
  function node(id) { return document.getElementById(id); }

  function pick(payload, keys, fallback = null) {
    const source = ui().objectPayload(payload);
    for (const key of keys) if (source[key] !== undefined && source[key] !== null) return source[key];
    return fallback;
  }

  function setStatus(id, message, tone = "neutral") {
    const status = node(id);
    if (!status) return;
    status.textContent = message || "";
    status.dataset.tone = tone;
  }

  function renderRisk() {
    const bars = node("strategy-risk-bars");
    const payload = ui().objectPayload(riskPayload);
    const qualityPayload = ui().objectPayload(payload.data_quality);
    const quality = pick(payload, ["quality", "status"], qualityPayload.unavailable?.length ? "partial" : qualityPayload.snapshot_stale ? "stale" : "available");
    const strategyExposures = Array.isArray(payload.strategy_exposures) ? payload.strategy_exposures : [];
    const coveredGroups = Array.isArray(payload.covered_share_groups) ? payload.covered_share_groups : [];
    const knownLoss = ui().objectPayload(payload.known_max_loss);
    const currency = /^[A-Z]{3}$/.test(String(payload.currency || "").trim().toUpperCase()) ? String(payload.currency).trim().toUpperCase() : null;
    const money = (value) => value === null || value === undefined ? ui().text("货币未知", "Currency unknown") : currency ? ui().money(value, currency) : ui().text("货币未知", "Currency unknown");
    const lossMoney = (value) => value === null || value === undefined ? ui().text("货币未知", "Currency unknown") : /^[A-Z]{3}$/.test(String(knownLoss.loss_currency || "").trim().toUpperCase()) ? ui().money(value, String(knownLoss.loss_currency).trim().toUpperCase()) : money(value);
    const knownLossTotal = ui().numberValue(knownLoss.total, null);
    const knownLossPct = ui().numberValue(knownLoss.nav_ratio_pct, null);
    const ratioUnavailable = ui().objectPayload(knownLoss.nav_ratio_unavailable);
    setStatus("strategy-risk-status", quality === "available" ? ui().text("风险证据可用", "Risk evidence ready") : `${ui().text("数据状态", "Data")}: ${ui().statusLabel(quality)}`, quality === "available" ? "success" : quality === "unavailable" ? "error" : "warning");
    if (!bars) return;
    const lines = [];
    if (knownLossTotal !== null) {
      lines.push(`<div class="workbench-bar-row"><div class="workbench-bar-label"><span>${ui().escapeHtml(ui().text("已知牛市看跌最大损失", "Known Bull Put max loss"))}</span><strong>${ui().escapeHtml(lossMoney(knownLossTotal))}</strong></div><div class="workbench-bar-track"><div class="workbench-bar-fill" data-tone="warning" style="width:${knownLossPct === null ? 0 : Math.min(100, Math.max(0, knownLossPct)).toFixed(1)}%"></div></div><small>${ui().escapeHtml(knownLoss.scope || "bull_put")} · ${ui().escapeHtml(knownLossPct === null ? (ratioUnavailable.reason || ui().text("占净清算值比例未知", "NAV proportion unavailable")) : `${knownLossPct.toFixed(2)}% of NAV`)} · ${ui().escapeHtml(`${knownLoss.loss_currency || "?"} / ${knownLoss.nav_currency || "?"}`)}</small></div>`);
    } else {
      lines.push(`<div class="workbench-blocked"><div><strong>${ui().escapeHtml(ui().text("已知最大损失不可用", "Known max loss unavailable"))}</strong><br /><span class="workbench-code">${ui().escapeHtml(knownLoss.unavailable?.code || "UNKNOWN_RISK")}</span> · ${ui().escapeHtml(knownLoss.unavailable?.reason || ui().text("当前证据不足，不能把未知当作零。", "Evidence is incomplete; unknown is not treated as zero."))}</div></div>`);
    }
    strategyExposures.slice(0, 8).forEach((item) => {
      const loss = ui().numberValue(item.known_max_loss, null);
      lines.push(`<div class="workbench-bar-row"><div class="workbench-bar-label"><span>${ui().escapeHtml(item.label || item.strategy_id || "Strategy")}</span><strong>${ui().escapeHtml(loss === null ? ui().text("最大损失未知", "Max loss unknown") : ui().money(loss))}</strong></div><small>${ui().escapeHtml([item.symbol, item.status].filter(Boolean).join(" · ") || ui().text("无额外说明", "No additional detail"))}</small></div>`);
    });
    coveredGroups.slice(0, 8).forEach((group) => {
      lines.push(`<div class="workbench-bar-row"><div class="workbench-bar-label"><span>${ui().escapeHtml(ui().text("备兑股份预留", "Covered shares reserved"))} · ${ui().escapeHtml(group.underlying_symbol || "--")}</span><strong>${ui().escapeHtml(group.reserved_shares ?? ui().text("未知", "Unknown"))}</strong></div><small>${ui().escapeHtml(group.expiration_date || "--")}</small></div>`);
    });
    if (!lines.length) {
      bars.innerHTML = `<div class="workbench-blocked"><div><strong>${ui().escapeHtml(ui().text("暂无策略风险证据", "No strategy risk evidence"))}</strong><br /><span class="workbench-code">BLOCKED_DATA</span></div></div>`;
      return;
    }
    bars.innerHTML = lines.join("");
  }

  function renderExplanation() {
    const payload = ui().objectPayload(riskPayload);
    const qualityPayload = ui().objectPayload(payload.data_quality);
    const quality = pick(payload, ["quality", "status"], qualityPayload.unavailable?.length ? "partial" : qualityPayload.snapshot_stale ? "stale" : "available");
    const blockers = [
      ...ui().arrayPayload(payload, ["blockers", "reasons", "warnings"]),
      ...(Array.isArray(qualityPayload.unavailable) ? qualityPayload.unavailable : []),
    ];
    const summary = node("strategy-explanation-summary");
    const facts = node("strategy-explanation-facts");
    const reasons = node("strategy-explanation-reasons");
    const status = node("strategy-explanation-status");
    if (!summary || !facts || !reasons || !status) return;
    const ready = quality === "available";
    status.textContent = ready ? ui().text("风险证据可用", "Risk evidence ready") : quality === "unavailable" ? ui().text("数据不可用", "Data unavailable") : ui().text("需要检查", "Review needed");
    status.dataset.tone = ready ? "success" : quality === "unavailable" ? "error" : "warning";
    summary.textContent = ready
      ? ui().text("当前风险数据允许继续做只读策略评估；这不等于获得纸账户 Canary。", "Current risk data supports a read-only strategy evaluation; it does not authorize a paper canary.")
      : ui().text("策略状态不能只看一个分数。请先看下方数据缺口和阻塞原因。", "Strategy readiness is not one score. Review the data gaps and blockers below.");
    facts.innerHTML = [
      [ui().text("策略数量", "Strategies"), payload.strategy_exposures?.length ?? "--"],
      [ui().text("已知最大损失", "Known max loss"), money(payload.known_max_loss?.total)],
      [ui().text("风险范围", "Risk scope"), payload.known_max_loss?.scope === "bull_put" ? ui().text("牛市看跌", "Bull Put") : (payload.known_max_loss?.scope || "--")],
      [ui().text("风险证据", "Risk evidence"), payload.known_max_loss?.unavailable || payload.known_max_loss?.nav_ratio_unavailable ? ui().text("不完整", "Incomplete") : ui().text("可读", "Readable")],
      [ui().text("数据时间", "As of"), ui().dateTime(payload.as_of || payload.generated_at)],
    ].map(([label, value]) => `<div><dt>${ui().escapeHtml(label)}</dt><dd>${ui().escapeHtml(String(value))}</dd></div>`).join("");
    reasons.innerHTML = (blockers.length ? blockers : [ui().text("没有返回具体阻塞原因。", "No specific blocker was returned.")]).slice(0, 6).map((reason) => `<li>${ui().escapeHtml(typeof reason === "string" ? reason : reason.detail || reason.message || JSON.stringify(reason))}</li>`).join("");
  }

  async function load() {
    const state = ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    if (!accountId) return;
    const token = ++loadToken;
    const result = await ui().loadScopedReads([
      { key: "risk", url: `/portfolio/risk?external_account_id=${encodeURIComponent(accountId)}&mode=paper` },
    ], state).catch((error) => ({ discarded: false, values: {}, errors: { risk: error?.message || "risk budget unavailable" } }));
    if (result.discarded || token !== loadToken || accountId !== ui().accountId()) {
      return;
    }
    riskPayload = result.values.risk || { status: "unavailable", data_quality: "unavailable", blockers: [result.errors.risk || "risk budget unavailable"] };
    renderRisk();
    renderExplanation();
  }

  async function readiness() {
    const accountId = ui().accountId();
    const symbol = String(node("strategy-evaluation-symbol")?.value || "").trim().toUpperCase();
    const status = node("strategy-evaluation-status");
    if (!accountId || !symbol) {
      if (status) status.textContent = ui().text("先填写评估标的。", "Enter a symbol to evaluate.");
      return;
    }
    if (status) status.textContent = ui().text("正在读取只读准备度…", "Loading read-only readiness…");
    const state = ui().getState() || {};
    const token = ++readinessToken;
    try {
      const result = await ui().loadScopedReads([
        { key: "readiness", url: `/strategies/bull-put/readiness?external_account_id=${encodeURIComponent(accountId)}&mode=paper&symbol=${encodeURIComponent(symbol)}` },
      ], state);
      if (result.discarded || token !== readinessToken || accountId !== ui().accountId() || state.accountLoadGeneration !== ui().getState()?.accountLoadGeneration) return;
      const payload = result.values.readiness || { ready: false, reason: result.errors.readiness || "readiness unavailable" };
      const returnedAccount = payload.external_account_id;
      const returnedMode = payload.mode;
      const preferred = String(payload.preferred_symbol || "").trim().toUpperCase();
      const previews = Array.isArray(payload.previews) ? payload.previews : [];
      const previewMatches = previews.some((preview) => String(preview?.symbol || "").trim().toUpperCase() === symbol);
      const scopeValid = returnedAccount === accountId && returnedMode === "paper";
      const symbolValid = !preferred || preferred === symbol || previewMatches;
      if (!scopeValid || !symbolValid) {
        if (status) status.textContent = `${ui().text("返回的准备度结果与当前请求不一致", "Readiness response did not match the request")}（BLOCKED_DATA）：${preferred || returnedAccount || returnedMode || "unknown"}`;
        if (status) status.dataset.tone = "error";
        return;
      }
      if (status) status.textContent = payload.ready === true ? `${symbol}：${ui().text("满足只读评估条件。Canary 仍需单独批准。", "read-only evaluation ready. Canary still requires separate approval.")}` : `${symbol}：${payload.next_action || payload.reason || ui().text("暂时不能评估。", "Evaluation is not ready.")}`;
      if (status) status.dataset.tone = payload.ready === true ? "success" : "warning";
    } catch (error) {
      if (status) status.textContent = `${ui().text("准备度暂时不可用", "Readiness unavailable")}（BLOCKED_DATA）：${error?.message || ""}`;
    }
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    node("strategy-readiness-button")?.addEventListener("click", () => { void readiness(); });
    node("strategy-canary-button")?.setAttribute("title", ui().text("Canary 需要单独批准。", "Canary requires separate approval."));
    ui().subscribe((event) => {
      if (event.type === "workspace" && event.workspace === "strategy") void load();
      if (event.type === "account-state" && ui().getWorkspace() === "strategy") void load();
    });
    renderRisk();
    renderExplanation();
  }

  window.StocksToolStrategyReadiness = { init: bind, load, readiness };
  document.addEventListener("DOMContentLoaded", bind, { once: true });
})();

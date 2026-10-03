(function () {
  "use strict";

  let initialized = false;
  let runs = [];
  let selected = null;
  let loadToken = 0;
  let activeAccountId = "";

  function ui() { return window.StocksToolWorkbenchUI; }
  function node(id) { return document.getElementById(id); }

  function setStatus(message, tone = "neutral") {
    const status = node("advisor-audit-status");
    if (!status) return;
    status.textContent = message || "";
    status.dataset.tone = tone;
  }

  function normalise(payload) {
    const items = ui().arrayPayload(payload, ["runs", "items", "audit"]);
    return items.map((item) => {
      const run = ui().objectPayload(item.advisor_run || item);
      return {
      id: run.run_id || run.id,
      status: item.record_state || run.status || run.recordable_status || "unknown",
      model: run.model || run.provider || "DeepSeek",
      summary: item.impact_summary || run.summary || "",
      warnings: Array.isArray(run.warnings) ? run.warnings : [],
      usage: ui().objectPayload(item.token_usage || run.token_usage || run.usage),
       impact: ui().objectPayload(item.downstream_impact || run.downstream_impact || item.impact),
       checks: Array.isArray(item.checks) ? item.checks : [],
       comparison: ui().objectPayload(item.comparison),
       responsePayload: item.response_payload || null,
       rawResponse: item.raw_response || null,
       contextHash: run.context_hash || "--",
      raw: item,
      };
    }).filter((run) => run.id);
  }

  function render() {
    const list = node("advisor-audit-list");
    const detail = node("advisor-audit-detail");
    if (!list || !detail) return;
    if (!runs.length) {
      list.innerHTML = `<div class="workbench-blocked"><div><strong>${ui().escapeHtml(ui().text("暂无 Advisor 审计记录", "Advisor audit unavailable"))}</strong><br /><span class="workbench-code">BLOCKED_DATA</span> · ${ui().escapeHtml(ui().text("本地审计接口没有返回记录。", "The local audit endpoint returned no records."))}</div></div>`;
      detail.innerHTML = "";
      return;
    }
    list.innerHTML = runs.slice(0, 10).map((run) => `<button type="button" class="advisor-audit-row ${run.id === selected?.id ? "is-selected" : ""}" data-advisor-audit-run="${ui().escapeHtml(run.id)}"><strong>${ui().escapeHtml(run.model)}</strong><span>${ui().escapeHtml(run.status)}</span><small>${ui().escapeHtml(run.summary || run.id)}</small></button>`).join("");
    if (!selected) selected = runs[0];
    const usage = selected.usage;
    const impact = selected.impact;
    const checks = selected.checks.length ? selected.checks : [{ detail: ui().text("没有额外检查。", "No additional checks.") }];
    detail.innerHTML = `
      <div class="workbench-explanation-header"><div><span class="section-kicker">Advisor 证据</span><h3>${ui().escapeHtml(selected.model)} · ${ui().escapeHtml(selected.status)}</h3></div><span class="workbench-status-chip" data-tone="${selected.status === "recorded" ? "success" : selected.status === "failed" ? "error" : "warning"}">${ui().escapeHtml(selected.status)}</span></div>
      <div class="workbench-explanation-body">
        <p class="workbench-explanation-summary">${ui().escapeHtml(selected.summary || ui().text("该运行没有摘要。", "This run has no summary."))}</p>
        <dl class="workbench-facts">
          <div><dt>输入摘要</dt><dd>${ui().escapeHtml(selected.contextHash === "--" ? ui().text("未记录", "Not recorded") : String(selected.contextHash).slice(0, 16))}</dd></div>
          <div><dt>输入字数（token）</dt><dd>${ui().escapeHtml(usage.prompt_tokens ?? "--")}</dd></div>
          <div><dt>输出字数（token）</dt><dd>${ui().escapeHtml(usage.completion_tokens ?? "--")}</dd></div>
          <div><dt>总字数（token）</dt><dd>${ui().escapeHtml(usage.total_tokens ?? "--")}</dd></div>
          <div><dt>推理字数（token）</dt><dd>${ui().escapeHtml(usage.reasoning_tokens ?? "--")}</dd></div>
          <div><dt>缓存命中/未命中</dt><dd>${ui().escapeHtml(`${usage.cache_hit_tokens ?? "--"} / ${usage.cache_miss_tokens ?? "--"}`)}</dd></div>
          <div><dt>下游提案</dt><dd>${ui().escapeHtml(impact.proposal_ids?.length ?? impact.proposals ?? "--")}</dd></div>
          <div><dt>下游复盘</dt><dd>${ui().escapeHtml(impact.review_ids?.length ?? impact.reviews ?? "--")}</dd></div>
          <div><dt>响应记录</dt><dd>${ui().escapeHtml(selected.responsePayload ? ui().text("已记录", "Recorded") : ui().text("仅试运行", "Dry run only"))}</dd></div>
          <div><dt>响应标识</dt><dd>${ui().escapeHtml(selected.rawResponse?.response_id || selected.rawResponse?.finish_reason || "--")}</dd></div>
        </dl>
        <ul class="workbench-explanation-list">${checks.slice(0, 6).map((check) => `<li>${ui().escapeHtml(check.detail || check.message || check.name || "--")}</li>`).join("")}</ul>
        ${selected.warnings.length ? `<p class="workbench-data-badge" data-quality="partial">${ui().escapeHtml(selected.warnings[0])}</p>` : ""}
        ${Object.keys(selected.comparison).length ? `<p class="workbench-data-badge" data-quality="partial">${ui().escapeHtml(ui().text("与上次运行", "Compared with previous run"))}: ${ui().escapeHtml(JSON.stringify(selected.comparison))}</p>` : ""}
      </div>
    `;
  }

  async function load() {
    const state = ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    if (!accountId) return;
    const token = ++loadToken;
    activeAccountId = accountId;
    runs = [];
    selected = null;
    render();
    setStatus(ui().text("正在读取 Advisor 审计…", "Loading advisor audit…"));
    try {
      const result = await ui().loadScopedReads([
        { key: "audit", url: `/strategies/advisor/audit?external_account_id=${encodeURIComponent(accountId)}&source=deepseek&limit=10` },
      ], state);
      if (result.discarded || token !== loadToken || accountId !== ui().accountId() || activeAccountId !== accountId) return;
      const payload = result.values.audit;
      if (!payload) throw new Error(result.errors.audit || "advisor audit unavailable");
      runs = normalise(payload);
      selected = runs[0] || null;
      setStatus(ui().text(`${runs.length} 条本地审计记录`, `${runs.length} local audit record(s)`), "success");
      render();
    } catch (error) {
      if (token !== loadToken || accountId !== ui().accountId() || activeAccountId !== accountId) return;
      runs = [];
      selected = null;
      setStatus(`${ui().text("Advisor 审计暂时不可用", "Advisor audit unavailable")}（BLOCKED_DATA）：${error?.message || ""}`, "error");
      render();
    }
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    node("advisor-audit-load")?.addEventListener("click", () => { void load(); });
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-advisor-audit-run]");
      if (!button) return;
      selected = runs.find((run) => run.id === button.dataset.advisorAuditRun) || selected;
      render();
    });
    ui().subscribe((event) => {
      if (event.type === "account-state" && ui().getWorkspace() === "strategy") void load();
    });
    render();
  }

  window.StocksToolAdvisorAudit = { init: bind, load };
  document.addEventListener("DOMContentLoaded", bind, { once: true });
})();

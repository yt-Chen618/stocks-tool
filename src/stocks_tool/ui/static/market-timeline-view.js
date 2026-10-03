(function () {
  "use strict";

  let initialized = false;
  let loadToken = 0;
  let events = [];
  let preOpen = null;

  function ui() { return window.StocksToolWorkbenchUI; }
  function node(id) { return document.getElementById(id); }

  function render() {
    const list = node("market-event-timeline");
    const summary = node("market-explanation-summary");
    const facts = node("market-explanation-facts");
    const status = node("market-explanation-status");
    if (!list || !summary || !facts || !status) return;
    const assessment = ui().objectPayload(preOpen);
    const quality = assessment.freshness_status || (events.length ? "local" : "unavailable");
    status.textContent = quality === "live" ? ui().text("实时市场证据", "Live market evidence") : `${ui().text("状态", "Status")}: ${quality}`;
    status.dataset.tone = quality === "live" ? "success" : quality === "unavailable" ? "error" : "warning";
    summary.textContent = ui().text(
      "时间线把事件和盘前代理放在同一个可读顺序里。事件本身不构成交易建议，存档数据会明确标注。",
      "The timeline puts events and pre-open proxies in one readable order. Events are not trade instructions, and stored data is labelled.",
    );
    facts.innerHTML = [
      [ui().text("事件数量", "Events"), String(events.length)],
      [ui().text("盘前状态", "Pre-open"), assessment.regime || ui().text("未加载", "Not loaded")],
      [ui().text("下行分数", "Downside score"), assessment.downside_score ?? "--"],
      [ui().text("数据时间", "As of"), ui().dateTime(assessment.analyzed_at || assessment.generated_at)],
    ].map(([label, value]) => `<div><dt>${ui().escapeHtml(label)}</dt><dd>${ui().escapeHtml(value)}</dd></div>`).join("");
    if (!events.length) {
      list.innerHTML = `<div class="workbench-blocked"><div><strong>${ui().escapeHtml(ui().text("暂无市场事件证据", "Market event evidence unavailable"))}</strong><br /><span class="workbench-code">BLOCKED_DATA</span> · ${ui().escapeHtml(ui().text("时间线服务没有返回完整事件。", "The timeline service returned no complete event set."))}</div></div>`;
      return;
    }
    list.innerHTML = events.map((event) => {
      const label = event.symbol || ui().text("全市场", "Market");
      const detail = [event.event_type, event.source, event.severity].filter(Boolean).join(" · ");
      return `<article class="workbench-timeline-item"><time class="workbench-timeline-time">${ui().escapeHtml(ui().dateTime(event.scheduled_at || event.event_date, "America/New_York"))}</time><div><div class="workbench-timeline-title">${ui().escapeHtml(event.title || event.name || "Market event")}</div><div class="workbench-timeline-detail">${ui().escapeHtml([label, detail].filter(Boolean).join(" / "))}</div></div></article>`;
    }).join("");
  }

  async function loadAllTimelinePages(initialPayload, baseUrl, accountId) {
    if (Array.isArray(initialPayload)) return initialPayload;
    let payload = initialPayload && typeof initialPayload === "object" ? initialPayload : {};
    const rows = Array.isArray(payload.items)
      ? [...payload.items]
      : Array.isArray(payload.events) ? [...payload.events] : [];
    const seenCursors = new Set();
    while (payload.has_more && payload.next_cursor && !seenCursors.has(payload.next_cursor)) {
      seenCursors.add(payload.next_cursor);
      payload = await ui().fetchJson(`${baseUrl}&cursor=${encodeURIComponent(payload.next_cursor)}`);
      if (accountId !== ui().accountId()) return [];
      if (Array.isArray(payload?.items)) rows.push(...payload.items);
      else if (Array.isArray(payload?.events)) rows.push(...payload.events);
    }
    return rows;
  }

  async function load() {
    const state = ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    if (!accountId) return;
    const token = ++loadToken;
    const timelineUrl = `/research/timeline?external_account_id=${encodeURIComponent(accountId)}&mode=paper&limit=100`;
    const result = await ui().loadScopedReads([
      { key: "timeline", url: timelineUrl },
    ], state).catch((error) => ({ discarded: false, values: {}, errors: { timeline: error?.message || "timeline unavailable" } }));
    if (result.discarded || token !== loadToken || accountId !== ui().accountId()) return;
    try {
      events = await loadAllTimelinePages(result.values.timeline, timelineUrl, accountId);
    } catch (_error) {
      events = result.values.timeline ? ui().arrayPayload(result.values.timeline, ["items", "events", "timeline"]) : [];
    }
    preOpen = state.preOpenRuns?.[0]?.assessment || state.preOpenAssessment || null;
    if (result.errors.timeline) {
      events = [];
    }
    render();
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    ui().subscribe((event) => {
      if (event.type === "workspace" && event.workspace === "macro") void load();
      if (event.type === "account-state") {
        preOpen = event.state?.preOpenAssessment || preOpen;
        if (ui().getWorkspace() === "macro") void load();
      }
    });
    node("market-timeline-refresh")?.addEventListener("click", () => { void load(); });
    node("market-load-preopen-board")?.addEventListener("click", () => node("load-preopen-board")?.click());
    node("market-load-preopen-overlays")?.addEventListener("click", () => node("load-preopen-overlays")?.click());
    node("market-save-preopen-board")?.addEventListener("click", () => node("save-preopen-board")?.click());
    render();
  }

  window.StocksToolMarketTimeline = { init: bind, load };
  document.addEventListener("DOMContentLoaded", bind, { once: true });
})();

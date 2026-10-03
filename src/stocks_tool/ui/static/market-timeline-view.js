(function () {
  "use strict";

  let initialized = false;
  let loadToken = 0;
  let events = [];
  let preOpen = null;

  function ui() { return window.StocksToolWorkbenchUI; }
  function node(id) { return document.getElementById(id); }

  function isChinese() {
    return String(document.documentElement?.lang || "zh-CN").toLowerCase().startsWith("zh");
  }

  function demoMode() {
    return document.body?.dataset?.demo === "true";
  }

  function explicitDateTime(value, timeZone) {
    if (!value) return "--";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(isChinese() ? "zh-CN" : "en-US", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone,
    }).format(date);
  }

  function observationTime(value) {
    if (!value) return ui().text("时间未知", "Time unknown");
    return `${ui().text("中国时间", "China")} ${explicitDateTime(value, "Asia/Shanghai")} · ${ui().text("美东时间", "ET")} ${explicitDateTime(value, "America/New_York")}`;
  }

  function qualityLabel(value) {
    const raw = String(value || "unknown");
    const labels = {
      live: ["实时读取", "Live read"],
      partial: ["部分可用", "Partially available"],
      stale: ["已保存旧数据", "Stored / stale"],
      error: ["读取失败", "Read failed"],
      unavailable: ["不可用", "Unavailable"],
      local: ["本地已保存事件", "Local stored events"],
      degraded: ["数据质量下降", "Degraded data"],
    };
    const label = labels[raw];
    if (demoMode() && raw === "live") return ui().text("演示数据（不代表实时行情）", "Demo data (not live market evidence)");
    if (demoMode() && raw === "local") return ui().text("演示数据（本地事件存档）", "Demo data (local event archive)");
    return label ? ui().text(label[0], label[1]) : ui().text(`未知数据状态（${raw}）`, `Unknown data status (${raw})`);
  }

  function regimeLabel(value) {
    const raw = String(value || "unknown");
    const labels = {
      broad_downside_risk: ["广泛下行风险", "Broad downside risk"],
      selective_downside_risk: ["选择性下行风险", "Selective downside risk"],
      mixed_to_firm: ["市场混合至偏强", "Mixed to firm"],
      neutral: ["中性", "Neutral"],
      unavailable: ["盘前状态不可用", "Pre-open status unavailable"],
    };
    const label = labels[raw];
    return label ? ui().text(label[0], label[1]) : ui().text(`未知盘前状态（${raw}）`, `Unknown pre-open status (${raw})`);
  }

  function sourceLabel(value) {
    const raw = String(value || "");
    const labels = {
      "mock-ui": ["本地演示存档", "Local demo archive"],
      local: ["本地事件存档", "Local event archive"],
      fmp: ["FMP 外部来源", "FMP external source"],
      longbridge: ["Longbridge 行情来源", "Longbridge market source"],
    };
    const label = labels[raw];
    return label ? ui().text(label[0], label[1]) : raw ? ui().text(`未知来源（${raw}）`, `Unknown source (${raw})`) : ui().text("来源未知", "Source unknown");
  }

  function eventTypeLabel(value) {
    const raw = String(value || "");
    const labels = {
      macro: ["宏观事件", "Macro event"],
      economic: ["经济数据", "Economic data"],
      earnings: ["财报事件", "Earnings"],
      fomc: ["FOMC 会议", "FOMC meeting"],
      dividend: ["分红事件", "Dividend"],
    };
    const label = labels[raw];
    return label ? ui().text(label[0], label[1]) : raw ? ui().text(`事件类型：${raw}`, `Event type: ${raw}`) : "";
  }

  function severityLabel(value) {
    const raw = String(value || "");
    const labels = {
      high: ["高影响", "High impact"],
      medium: ["中影响", "Medium impact"],
      low: ["低影响", "Low impact"],
      critical: ["关键影响", "Critical impact"],
    };
    const label = labels[raw];
    return label ? ui().text(label[0], label[1]) : raw ? ui().text(`影响等级：${raw}`, `Impact: ${raw}`) : "";
  }

  function eventTimeLabel(event) {
    if (event?.scheduled_at) return observationTime(event.scheduled_at);
    if (event?.event_date) return ui().text(`交易日 ${event.event_date}（没有具体时刻）`, `Trading date ${event.event_date} (no exact time)`);
    return ui().text("时间未知", "Time unknown");
  }

  function render() {
    const list = node("market-event-timeline");
    const summary = node("market-explanation-summary");
    const facts = node("market-explanation-facts");
    const status = node("market-explanation-status");
    if (!list || !summary || !facts || !status) return;
    const assessment = ui().objectPayload(preOpen);
    const quality = assessment.freshness_status || (events.length ? "local" : "unavailable");
    status.textContent = qualityLabel(quality);
    status.dataset.tone = quality === "live" && !demoMode() ? "success" : ["unavailable", "error"].includes(quality) ? "error" : "warning";
    summary.textContent = ui().text(
      "时间线把事件和盘前代理放在同一个可读顺序里。事件本身不构成交易建议，存档数据会明确标注。",
      "The timeline puts events and pre-open proxies in one readable order. Events are not trade instructions, and stored data is labelled.",
    );
    facts.innerHTML = [
      [ui().text("事件数量", "Events"), String(events.length)],
      [ui().text("盘前状态", "Pre-open"), assessment.regime ? regimeLabel(assessment.regime) : ui().text("未加载", "Not loaded")],
      [ui().text("下行分数", "Downside score"), assessment.downside_score ?? "--"],
      [ui().text("数据时间", "As of"), observationTime(assessment.analyzed_at || assessment.generated_at)],
    ].map(([label, value]) => `<div><dt>${ui().escapeHtml(label)}</dt><dd>${ui().escapeHtml(value)}</dd></div>`).join("");
    if (!events.length) {
      list.innerHTML = `<div class="workbench-blocked"><div><strong>${ui().escapeHtml(ui().text("暂无市场事件证据", "Market event evidence unavailable"))}</strong><br /><span class="workbench-code">BLOCKED_DATA</span> · ${ui().escapeHtml(ui().text("时间线服务没有返回完整事件。", "The timeline service returned no complete event set."))}</div></div>`;
      return;
    }
    list.innerHTML = events.map((event) => {
      const label = event.symbol || ui().text("全市场", "Market");
      const detail = [eventTypeLabel(event.event_type), sourceLabel(event.source), severityLabel(event.severity)].filter(Boolean).join(" · ");
      const rawTime = event.scheduled_at || event.event_date || "";
      return `<article class="workbench-timeline-item"><time class="workbench-timeline-time" datetime="${ui().escapeHtml(rawTime)}">${ui().escapeHtml(eventTimeLabel(event))}</time><div><div class="workbench-timeline-title">${ui().escapeHtml(event.title || event.name || ui().text("未命名事件", "Unnamed event"))}</div><div class="workbench-timeline-detail">${ui().escapeHtml([label, detail].filter(Boolean).join(" / "))}</div></div></article>`;
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

(function () {
  "use strict";

  let initialized = false;
  let researchState = null;
  let saveGeneration = 0;
  let currentScreenId = null;
  let currentAccountId = "";
  let screens = [];
  let cases = [];
  let caseLoadToken = 0;
  let pageLoadToken = 0;
  let screenPage = { cursor: null, hasMore: false, loading: false };
  let casePage = { cursor: null, hasMore: false, loading: false };

  function ui() {
    return window.StocksToolWorkbenchUI;
  }

  function element(id) {
    return document.getElementById(id);
  }

  function selectedRow() {
    const symbol = String(researchState?.selectedSymbol || "").toUpperCase();
    return (researchState?.rows || []).find((row) => String(row?.symbol || "").toUpperCase() === symbol) || null;
  }

  function strategyLabel(value) {
    const raw = String(value || "");
    const labels = {
      bull_put_pool: ui().text("牛市看跌标的池", "Bull Put pool"),
      zero_dte_pool: ui().text("零日期权标的池", "Zero-DTE pool"),
      covered_call_active: ui().text("备兑看涨持仓", "Covered Call active"),
      bull_put_spread: ui().text("牛市看跌价差", "Bull Put spread"),
      strategy_proposal: ui().text("策略提案", "Strategy proposal"),
      bull_put_ready: ui().text("牛市看跌价差：可继续评估", "Bull Put: ready for evaluation"),
      zero_dte_preview_only: ui().text("零日期权：仅供研究", "Zero-DTE: research only"),
    };
    const prefix = raw.split(":", 1)[0];
    return labels[raw] || (labels[prefix] ? `${labels[prefix]}${raw.slice(prefix.length)}` : raw);
  }

  function setStatus(message, tone = "neutral") {
    const node = element("research-case-status");
    if (!node) return;
    node.textContent = message || "";
    node.dataset.tone = tone;
  }

  function contextIsCurrent(accountId, generation) {
    return accountId === ui().accountId() && generation === ui().getState()?.accountLoadGeneration;
  }

  function renderSavedSelectors() {
    const screenSelect = element("research-screen-select");
    const caseSelect = element("research-case-select");
    if (screenSelect) {
      screenSelect.replaceChildren();
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = ui().text("暂无已保存筛选", "No saved screens");
      screenSelect.appendChild(empty);
      screens.forEach((screen) => {
        const option = document.createElement("option");
        option.value = screen.id;
        option.textContent = screen.name;
        option.selected = screen.id === currentScreenId;
        screenSelect.appendChild(option);
      });
    }
    if (caseSelect) {
      caseSelect.replaceChildren();
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = ui().text("暂无已保存档案", "No saved cases");
      caseSelect.appendChild(empty);
      cases.forEach((researchCase) => {
        const option = document.createElement("option");
        option.value = researchCase.id;
        option.textContent = researchCase.title || researchCase.id;
        caseSelect.appendChild(option);
      });
    }
    const moreScreens = element("research-load-more-screens");
    const moreCases = element("research-load-more-cases");
    if (moreScreens) moreScreens.hidden = !screenPage.hasMore || screenPage.loading;
    if (moreCases) moreCases.hidden = !casePage.hasMore || casePage.loading;
  }

  async function loadSavedRecords(stateOverride = null) {
    const state = stateOverride || ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    if (!accountId) return;
    const result = await ui().loadScopedReads([
      { key: "screens", url: `/research/screens?external_account_id=${encodeURIComponent(accountId)}&mode=paper&limit=100` },
      { key: "cases", url: `/research/cases?external_account_id=${encodeURIComponent(accountId)}&mode=paper&limit=100` },
    ], state).catch(() => ({ discarded: false, values: {} }));
    if (result.discarded || accountId !== ui().accountId()) return;
    const screenPayload = result.values.screens;
    const casePayload = result.values.cases;
    screens = Array.isArray(screenPayload) ? screenPayload : ui().arrayPayload(screenPayload, ["items"]);
    cases = Array.isArray(casePayload) ? casePayload : ui().arrayPayload(casePayload, ["items"]);
    screenPage = { cursor: screenPayload?.next_cursor || null, hasMore: screenPayload?.has_more === true, loading: false };
    casePage = { cursor: casePayload?.next_cursor || null, hasMore: casePayload?.has_more === true, loading: false };
    renderSavedSelectors();
  }

  async function loadMoreRecords(kind) {
    const state = ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    const page = kind === "screens" ? screenPage : casePage;
    if (!accountId || !page.hasMore || !page.cursor || page.loading) return;
    const token = ++pageLoadToken;
    page.loading = true;
    renderSavedSelectors();
    const result = await ui().loadScopedReads([
      { key: kind, url: `/research/${kind}?external_account_id=${encodeURIComponent(accountId)}&mode=paper&limit=100&cursor=${encodeURIComponent(page.cursor)}` },
    ], state).catch((error) => ({ discarded: false, values: {}, errors: { [kind]: error?.message || "page failed" } }));
    if (result.discarded || token !== pageLoadToken || accountId !== ui().accountId() || state.accountLoadGeneration !== ui().getState()?.accountLoadGeneration) {
      page.loading = false;
      renderSavedSelectors();
      return;
    }
    const payload = result.values[kind];
    if (!payload) {
      page.loading = false;
      setStatus(`${ui().text("加载下一页失败", "Next page failed")}（BLOCKED_DATA）：${result.errors[kind] || ""}`, "error");
      renderSavedSelectors();
      return;
    }
    const items = Array.isArray(payload) ? payload : ui().arrayPayload(payload, ["items"]);
    const target = kind === "screens" ? screens : cases;
    items.forEach((item) => { if (!target.some((existing) => existing.id === item.id)) target.push(item); });
    page.cursor = payload.next_cursor || null;
    page.hasMore = payload.has_more === true;
    page.loading = false;
    renderSavedSelectors();
  }

  function loadSelectedScreen() {
    const id = element("research-screen-select")?.value;
    const screen = screens.find((candidate) => candidate.id === id);
    if (!screen) return;
    currentScreenId = screen.id;
    window.StocksToolResearch?.applySavedScreen?.(screen);
    setStatus(`${ui().text("已加载筛选", "Loaded screen")}: ${screen.name}`, "success");
    renderSavedSelectors();
  }

  async function loadSelectedCase() {
    const id = element("research-case-select")?.value;
    let researchCase = cases.find((candidate) => candidate.id === id);
    if (!researchCase) return;
    const state = ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    const token = ++caseLoadToken;
    const result = await ui().loadScopedReads([
      { key: "case", url: `/research/cases/${encodeURIComponent(id)}?external_account_id=${encodeURIComponent(accountId)}&mode=paper` },
    ], state).catch(() => ({ discarded: false, values: {} }));
    if (result.discarded || token !== caseLoadToken || accountId !== ui().accountId() || state.accountLoadGeneration !== ui().getState()?.accountLoadGeneration) return;
    researchCase = result.values.case || researchCase;
    renderImmutableCase(researchCase);
    setStatus(`${ui().text("已加载不可变研究档案", "Loaded immutable research case")}: ${researchCase.title || researchCase.id}`, "success");
  }

  function renderImmutableCase(researchCase) {
    const panel = element("research-immutable-case-panel");
    const livePanel = element("research-explanation-panel");
    const summary = element("research-immutable-case-summary");
    const facts = element("research-immutable-case-facts");
    const warnings = element("research-immutable-case-warnings");
    if (!panel || !summary || !facts || !warnings) return;
    panel.hidden = false;
    if (livePanel) livePanel.hidden = true;
    const snapshot = ui().objectPayload(researchCase.universe);
    const researchUniverse = ui().objectPayload(snapshot.research_universe);
    const rows = Array.isArray(researchUniverse.rows) ? researchUniverse.rows : Array.isArray(snapshot.rows) ? snapshot.rows : [];
    const technicalResults = ui().arrayPayload(snapshot.technicals, ["results"]);
    const history = ui().objectPayload(snapshot.history);
    const primary = researchCase.primary_symbol || researchCase.symbols?.[0] || rows[0]?.symbol || "--";
    const primaryRow = rows.find((row) => row?.symbol === primary) || rows[0] || {};
    const technicals = technicalResults.find((item) => item?.symbol === primary) || ui().objectPayload(primaryRow.technicals);
    const quality = researchCase.data_quality || "unknown";
    summary.textContent = `${ui().text("历史档案", "Historical case")}: ${researchCase.title || researchCase.id}。${ui().text("这是保存时的证据，不代表当前市场。", "This is captured evidence, not current market state.")}`;
    facts.innerHTML = [
      [ui().text("主标的", "Primary symbol"), primary],
      [ui().text("保存时间", "Captured at"), ui().dateTime(researchCase.as_of)],
      [ui().text("数据质量", "Data quality"), ui().statusLabel(quality)],
      [ui().text("标的数量", "Symbols"), researchCase.symbols?.length ?? rows.length ?? 0],
      [ui().text("下一步", "Next action"), researchCase.next_action || ui().text("未记录", "Not recorded")],
      [ui().text("来源", "Source"), ui().statusLabel(researchCase.source || ui().text("未记录", "Not recorded"))],
      [ui().text("历史范围", "History range"), history.range || researchCase.configuration?.history_range || "--"],
      [ui().text("历史数据时间", "History as of"), ui().dateTime(history.generated_at || history.as_of)],
      [ui().text("20 日价格涨跌", "20D price change"), ui().percent(technicals.return_20d_pct)],
      [ui().text("60 日价格涨跌", "60D price change"), ui().percent(technicals.return_60d_pct)],
      [ui().text("保存时事件", "Event at capture"), primaryRow.next_event?.title || ui().text("无", "None")],
    ].map(([label, value]) => `<div><dt>${ui().escapeHtml(label)}</dt><dd>${ui().escapeHtml(String(value))}</dd></div>`).join("");
    const caseWarnings = Array.isArray(researchCase.warnings) ? researchCase.warnings : [];
    warnings.innerHTML = (caseWarnings.length ? caseWarnings : [ui().text("没有保存时警告。", "No capture warnings.")]).map((warning) => `<li>${ui().escapeHtml(warning)}</li>`).join("");
    renderImmutableChart(history.bars || []);
  }

  function renderImmutableChart(rawBars) {
    const chart = element("research-immutable-case-chart");
    if (!chart) return;
    const bars = (Array.isArray(rawBars) ? rawBars : []).map((bar) => ({
      time: bar?.timestamp || bar?.date || bar?.time,
      value: ui().numberValue(bar?.close, null),
    })).filter((bar) => bar.time && bar.value !== null);
    if (!bars.length) {
      chart.innerHTML = `<div class="workbench-chart-empty">${ui().escapeHtml(ui().text("档案中没有保存的历史图表。", "No saved chart history exists in this case."))}</div>`;
      return;
    }
    const width = 680;
    const height = 220;
    const values = bars.map((bar) => bar.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const points = bars.map((bar, index) => `${18 + index / Math.max(1, bars.length - 1) * (width - 36)},${14 + (1 - (bar.value - min) / span) * (height - 42)}`).join(" ");
    chart.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${ui().escapeHtml(ui().text("保存时历史收盘价", "Captured historical close"))}"><line x1="18" y1="${height - 28}" x2="${width - 18}" y2="${height - 28}" stroke="#d8e2de"/><polyline points="${points}" fill="none" stroke="#6d4fd2" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/><text x="18" y="${height - 8}" fill="#61706d" font-size="11">${ui().escapeHtml(ui().dateTime(bars[0].time))}</text><text x="${width - 18}" y="${height - 8}" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(ui().dateTime(bars[bars.length - 1].time))}</text><text x="${width - 18}" y="18" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(ui().money(max))}</text><text x="${width - 18}" y="${height - 32}" fill="#61706d" font-size="11" text-anchor="end">${ui().escapeHtml(ui().money(min))}</text></svg>`;
  }

  function closeImmutableCase() {
    const panel = element("research-immutable-case-panel");
    const livePanel = element("research-explanation-panel");
    if (panel) panel.hidden = true;
    if (livePanel) livePanel.hidden = false;
  }

  async function compareCandidates() {
    const resultNode = element("research-compare-result");
    const rawSymbols = String(element("research-compare-symbols")?.value || "").split(",").map((value) => value.trim().toUpperCase()).filter(Boolean);
    const symbols = Array.from(new Set(rawSymbols));
    const rows = symbols.map((symbol) => (researchState?.rows || []).find((row) => row.symbol === symbol)).filter(Boolean);
    if (rows.length < 2) {
      if (resultNode) resultNode.textContent = ui().text("至少输入两个当前研究标的。", "Enter at least two symbols from the current research universe.");
      return;
    }
    const incomplete = rows.filter((row) => {
      const technicals = ui().objectPayload(row.technicals);
      return ["return_20d_pct", "return_60d_pct", "realized_volatility_20d_pct", "average_turnover_20d"].some((key) => technicals[key] === null || technicals[key] === undefined);
    });
    if (incomplete.length) {
      if (resultNode) resultNode.textContent = `${ui().text("无法比较：技术数据不完整", "Comparison blocked: incomplete technical data")}（BLOCKED_DATA）：${incomplete.map((row) => row.symbol).join(", ")}`;
      return;
    }
    const candidates = rows.map((row) => {
      const technicals = ui().objectPayload(row.technicals);
      const eventType = row.next_event?.event_type || "technical";
      const clamp = (value) => Math.min(1, Math.max(0, Number(value)));
      const momentum = clamp((Number(technicals.return_20d_pct) + 20) / 40);
      const volatility = clamp(1 - Number(technicals.realized_volatility_20d_pct) / 100);
      const liquidity = clamp(Number(technicals.average_turnover_20d) / 10_000_000);
      const catalyst = row.next_event ? 0.7 : 0.3;
      return {
        symbol: row.symbol,
        asset_type: row.asset_type || "stock",
        catalyst_type: ["earnings", "filing", "rating", "macro", "news", "technical"].includes(eventType) ? eventType : "technical",
        thesis: `${row.symbol} research comparison`,
        news_summary: row.next_event?.title || null,
        momentum_score: momentum,
        volatility_score: volatility,
        liquidity_score: liquidity,
        catalyst_score: catalyst,
      };
    });
    if (resultNode) resultNode.textContent = ui().text("正在比较候选…", "Comparing candidates…");
    const state = ui().getState() || {};
    const accountId = state.selectedAccountId || ui().accountId();
    const requestToken = ++caseLoadToken;
    try {
      const result = await ui().loadScopedReads([
        { key: "rank", url: "/research/rank", options: { method: "POST", body: JSON.stringify({ candidates }) } },
      ], state);
      if (result.discarded || requestToken !== caseLoadToken || accountId !== ui().accountId() || state.accountLoadGeneration !== ui().getState()?.accountLoadGeneration) return;
      const ranked = result.values.rank;
      const values = Array.isArray(ranked) ? ranked : [];
      if (resultNode) {
        resultNode.innerHTML = `${ui().escapeHtml(ui().text("权重：动量35% · 波动25% · 流动性25% · 催化剂15%。分数是归一化研究输入的排序，不是概率或收益预测。", "Weights: momentum 35%, volatility 25%, liquidity 25%, catalyst 15%. Scores rank normalized research inputs; they are not probabilities or return forecasts."))}<br />${values.map((item, index) => `<strong>${index + 1}. ${ui().escapeHtml(item.candidate?.symbol || "--")}</strong> <span>${ui().escapeHtml(String(item.composite_score ?? "--"))}</span>`).join(" · ") || ui().text("没有返回比较结果。", "No comparison result returned.")}`;
      }
    } catch (error) {
      if (resultNode) resultNode.textContent = `${ui().text("候选比较暂时不可用", "Candidate comparison unavailable")}（BLOCKED_DATA）：${error?.message || ""}`;
    }
  }

  function renderExplanation() {
    const row = selectedRow();
    const title = element("research-explanation-title");
    const summary = element("research-explanation-summary");
    const status = element("research-explanation-status");
    const facts = element("research-explanation-facts");
    const reasons = element("research-explanation-reasons");
    const buttons = document.querySelectorAll("[data-research-case-action]");
    buttons.forEach((button) => { button.disabled = !row; });

    if (!row) {
      if (title) title.textContent = ui().text("请选择一个标的", "Select a symbol");
      if (summary) summary.textContent = ui().text(
        "研究表和图表共享同一标的。选择一行后，这里会解释数据、证据缺口和下一步。",
        "The table and chart share one symbol. Select a row to see the evidence, gaps, and next step.",
      );
      if (status) status.textContent = ui().text("等待选择", "Waiting");
      if (facts) facts.replaceChildren();
      if (reasons) reasons.innerHTML = `<li>${ui().escapeHtml(ui().text("没有标的就没有策略判断。", "No strategy judgement is made without a selected symbol."))}</li>`;
      return;
    }

    const technicals = ui().objectPayload(row.technicals);
    const quote = ui().objectPayload(row.quote);
    const last = quote.last_done ?? quote.last_price ?? quote.price ?? quote.close;
    const warningList = [
      ...(Array.isArray(row.warnings) ? row.warnings : []),
      technicals.warning,
      ...(researchState?.warnings || []),
    ].filter(Boolean);
    const quoteQuality = researchState?.dataQuality || "unknown";
    const technicalQuality = technicals.status || "unavailable";
    const isDemo = document.body?.dataset.demo === "true";
    if (title) title.textContent = `${row.symbol} · ${ui().text("当前研究解读", "Current research")}`;
    if (status) {
      status.textContent = isDemo
        ? ui().text("演示数据", "Demo data")
        : `${ui().text("报价", "Quotes")}: ${ui().statusLabel(quoteQuality)} · ${ui().text("日线", "Daily bars")}: ${ui().statusLabel(technicalQuality)}`;
      status.dataset.tone = isDemo ? "warning" : quoteQuality === "live" && technicalQuality === "ok" ? "success" : technicalQuality === "unavailable" ? "error" : "warning";
    }
    if (summary) {
      const trend = technicalQuality !== "ok"
        ? ui().text("日线数据不完整，暂时不能判断趋势。", "Daily evidence is incomplete; the trend cannot be assessed yet.")
        : technicals.close_above_sma20 === true && technicals.sma20_above_sma50 === true
          ? ui().text("价格高于20日均价，20日均价也高于50日均价，近期走势偏强。", "Price is above its 20-day average, which is above its 50-day average; the recent trend is stronger.")
          : ui().text("价格和两条均线还没有同时满足趋势转强的条件。", "Price and the two averages do not jointly meet the stronger-trend condition.");
      summary.textContent = `${isDemo ? ui().text("以下是演示：", "Demonstration: ") : ""}${trend} ${ui().text("用于研究比较，下单仍需单独评估风险。", "Use this for research; an order requires a separate risk assessment.")}`;
    }
    if (facts) {
      facts.innerHTML = [
        [ui().text("最新价", "Last"), last == null ? "--" : ui().money(last)],
        [ui().text("20 日价格涨跌", "20D price change"), ui().percent(technicals.return_20d_pct)],
        [ui().text("60 日价格涨跌", "60D price change"), ui().percent(technicals.return_60d_pct)],
        [ui().text("事件", "Next event"), row.next_event?.title || ui().text("暂无", "None")],
        [ui().text("策略状态", "Strategy"), (row.strategy_states || []).map(strategyLabel).join(" · ") || ui().text("暂无", "None")],
        [ui().text("报价时间", "Quote time"), ui().dateTime(quote.timestamp)],
        [ui().text("日线截至", "Daily data through"), ui().dateTime(technicals.latest_bar_at)],
      ].map(([label, value]) => `<div><dt>${ui().escapeHtml(label)}</dt><dd>${ui().escapeHtml(value)}</dd></div>`).join("");
    }
    if (reasons) {
      const notes = warningList.length
        ? warningList.slice(0, 5)
        : [ui().text("当前没有已知数据警告。", "No known data warnings.")];
      reasons.innerHTML = notes.map((warning) => `<li>${ui().escapeHtml(warning)}</li>`).join("");
    }
  }

  function screenConfig() {
    const state = researchState || window.StocksToolResearch?.getState?.() || {};
    return {
      filters: state.filters || {},
      sort: state.sort || {},
      view: state.view || "table",
      history_range: state.range || "6m",
      column_set: state.columnSet || "overview",
      watchlist_id: state.watchlistId || "",
      selected_symbol: state.selectedSymbol || "",
    };
  }

  async function saveScreen() {
    const accountId = ui().accountId();
    const nameInput = element("research-screen-name");
    const name = String(nameInput?.value || "").trim();
    if (!accountId || !name) {
      setStatus(ui().text("先选择账户并填写筛选名称。", "Select an account and enter a screen name."), "warning");
      return;
    }
    const generation = ++saveGeneration;
    const requestGeneration = ui().getState()?.accountLoadGeneration || 0;
    setStatus(ui().text("正在保存筛选配置…", "Saving screen configuration…"), "neutral");
    try {
      const config = screenConfig();
      const response = await ui().fetchJson("/research/screens", {
        method: "POST",
        body: JSON.stringify({
          external_account_id: accountId,
          mode: "paper",
          name,
          configuration: config,
          symbols: (researchState?.rows || []).map((row) => row.symbol).filter(Boolean),
        }),
      });
      if (generation !== saveGeneration || !contextIsCurrent(accountId, requestGeneration)) return;
      currentScreenId = response?.id || currentScreenId;
      setStatus(ui().text("筛选配置已保存。", "Screen configuration saved."), "success");
      await loadSavedRecords({ selectedAccountId: accountId, accountLoadGeneration: ui().getState()?.accountLoadGeneration || 0 });
    } catch (error) {
      if (generation !== saveGeneration) return;
      setStatus(`${ui().text("筛选服务暂时不可用", "Screen service unavailable")}（BLOCKED_DATA）：${error?.message || ""}`, "error");
    }
  }

  async function saveCase() {
    const row = selectedRow();
    const accountId = ui().accountId();
    const titleInput = element("research-case-title-input");
    const thesisInput = element("research-case-thesis-input");
    const title = String(titleInput?.value || "").trim() || `${row?.symbol || "Symbol"} research case`;
    if (!row || !accountId) {
      setStatus(ui().text("选择标的和账户后才能保存研究档案。", "Select a symbol and account before saving a research case."), "warning");
      return;
    }
    if (!currentScreenId) {
      setStatus(ui().text("请先保存一个筛选配置，再保存当前研究档案。", "Save a screen configuration before saving the current research case."), "warning");
      return;
    }
    const generation = ++saveGeneration;
    const requestGeneration = ui().getState()?.accountLoadGeneration || 0;
    setStatus(ui().text("正在保存不可变研究档案…", "Saving immutable research case…"), "neutral");
    try {
      const config = { ...screenConfig(), selected_symbol: row.symbol };
      await ui().fetchJson("/research/cases", {
        method: "POST",
        body: JSON.stringify({
          screen_id: currentScreenId,
          external_account_id: accountId,
          mode: "paper",
          configuration: config,
          symbols: [row.symbol],
          title,
          notes: String(thesisInput?.value || "").trim() || null,
          next_action: `strategy_evaluate:${row.symbol}`,
        }),
      });
      if (generation !== saveGeneration || !contextIsCurrent(accountId, requestGeneration)) return;
      setStatus(ui().text("研究档案已保存，证据快照不可变。", "Research case saved with immutable evidence."), "success");
      await loadSavedRecords({ selectedAccountId: accountId, accountLoadGeneration: ui().getState()?.accountLoadGeneration || 0 });
    } catch (error) {
      if (generation !== saveGeneration) return;
      setStatus(`${ui().text("研究档案服务暂时不可用", "Research case service unavailable")}（BLOCKED_DATA）：${error?.message || ""}`, "error");
    }
  }

  function evaluateStrategy() {
    const row = selectedRow();
    if (!row) return;
    const workspace = window.StocksToolWorkspace;
    workspace?.selectWorkspace?.("strategy");
    const tab = document.querySelector('[data-strategy-tab="bull-put"]');
    tab?.click();
    const symbolInput = element("strategy-evaluation-symbol");
    if (symbolInput) symbolInput.value = row.symbol;
    const target = element("strategy-evaluation-status");
    if (target) target.textContent = `${ui().text("已从研究带入", "Research handoff")}: ${row.symbol}。${ui().text("请运行只读策略评估。", "Run the read-only strategy evaluation.")}`;
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    document.getElementById("research-save-screen")?.addEventListener("click", () => { void saveScreen(); });
    document.getElementById("research-save-case")?.addEventListener("click", () => { void saveCase(); });
    document.getElementById("research-evaluate-strategy")?.addEventListener("click", evaluateStrategy);
    window.StocksToolWorkbenchUI?.subscribe((event) => {
      if (event.type === "research-state") {
        researchState = event.state || researchState;
        renderExplanation();
      }
      if (event.type === "account-state") {
        const nextAccountId = event.state?.selectedAccountId || "";
        if (currentAccountId && nextAccountId !== currentAccountId) currentScreenId = null;
        currentAccountId = nextAccountId;
        void loadSavedRecords(event.state);
      }
    });
    researchState = window.StocksToolResearch?.getState?.() || researchState;
    element("research-load-screen")?.addEventListener("click", loadSelectedScreen);
    element("research-load-case")?.addEventListener("click", () => { void loadSelectedCase(); });
    element("research-close-case")?.addEventListener("click", closeImmutableCase);
    element("research-load-more-screens")?.addEventListener("click", () => { void loadMoreRecords("screens"); });
    element("research-load-more-cases")?.addEventListener("click", () => { void loadMoreRecords("cases"); });
    element("research-compare-button")?.addEventListener("click", () => { void compareCandidates(); });
    renderExplanation();
  }

  window.StocksToolResearchCase = { init: bind, render: renderExplanation };
  document.addEventListener("DOMContentLoaded", bind, { once: true });
})();

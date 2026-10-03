(function () {
  "use strict";

  const STORAGE_KEY = "stocks-tool-research-state";
  const TECHNICAL_BATCH_SIZE = 10;
  const VALID_VIEWS = new Set(["table", "chart"]);
  const VALID_COLUMN_SETS = new Set(["overview", "momentum", "strategy"]);
  const VALID_RANGES = new Set(["3m", "6m", "1y"]);
  const TECHNICAL_FILTER_IDS = [
    "research-trend-close-sma20",
    "research-trend-sma20-sma50",
    "research-min-return20",
    "research-min-return60",
    "research-max-volatility",
    "research-min-turnover",
  ];
  const TECHNICAL_SORT_KEYS = new Set([
    "return_20d",
    "return_20d_pct",
    "return_60d",
    "return_60d_pct",
    "volatility",
    "realized_volatility_20d_pct",
    "turnover",
    "average_turnover_20d",
  ]);
  const DEFAULT_PERSISTED_STATE = {
    filters: {
      search: "",
      source: "",
      event: "",
      held: "",
      strategy: "",
      closeAboveSma20: false,
      sma20AboveSma50: false,
      minDayChange: "",
      minReturn20: "",
      minReturn60: "",
      maxVolatility: "",
      minTurnover: "",
    },
    sort: { key: "symbol", direction: "asc" },
    selectedSymbol: "",
    view: "table",
    range: "6m",
    columnSet: "overview",
  };

  const runtime = {
    initialized: false,
    elements: {},
    rows: [],
    generatedAt: null,
    dataQuality: null,
    warnings: [],
    technicalsComplete: false,
    refreshGeneration: 0,
    chartGeneration: 0,
    externalAccountId: "",
    watchlistId: "",
    chart: null,
    languageObserver: null,
    lastLanguage: "",
    status: { key: "idle", values: {} },
  };
  let persisted = readPersistedState();

  function cloneDefaultState() {
    return JSON.parse(JSON.stringify(DEFAULT_PERSISTED_STATE));
  }

  function readPersistedState() {
    const fallback = cloneDefaultState();
    try {
      const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "null");
      if (!parsed || typeof parsed !== "object") {
        return fallback;
      }
      const filters = parsed.filters && typeof parsed.filters === "object" ? parsed.filters : {};
      fallback.filters = { ...fallback.filters, ...filters };
      fallback.sort = {
        key: typeof parsed.sort?.key === "string" ? parsed.sort.key : fallback.sort.key,
        direction: parsed.sort?.direction === "desc" ? "desc" : "asc",
      };
      fallback.selectedSymbol = normalizeSymbol(parsed.selectedSymbol);
      fallback.view = VALID_VIEWS.has(parsed.view) ? parsed.view : fallback.view;
      fallback.range = VALID_RANGES.has(parsed.range) ? parsed.range : fallback.range;
      fallback.columnSet = VALID_COLUMN_SETS.has(parsed.columnSet)
        ? parsed.columnSet
        : fallback.columnSet;
      return fallback;
    } catch (_error) {
      return fallback;
    }
  }

  function persistState() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(persisted));
    } catch (_error) {
      // The workspace stays usable when storage is unavailable.
    }
  }

  function bindElements() {
    const byId = (id) => document.getElementById(id);
    runtime.elements = {
      status: byId("research-status"),
      progress: byId("research-progress"),
      tableView: byId("research-table-view"),
      chartView: byId("research-chart-view"),
      tableBody: byId("research-table-body"),
      search: byId("research-search"),
      watchlist: byId("research-watchlist-select"),
      source: byId("research-source-filter"),
      event: byId("research-event-filter"),
      held: byId("research-held-filter"),
      heldFilterStatus: byId("research-held-filter-status"),
      strategy: byId("research-strategy-filter"),
      closeAboveSma20: byId("research-trend-close-sma20"),
      sma20AboveSma50: byId("research-trend-sma20-sma50"),
      minDayChange: byId("research-min-day-change"),
      minReturn20: byId("research-min-return20"),
      minReturn60: byId("research-min-return60"),
      maxVolatility: byId("research-max-volatility"),
      minTurnover: byId("research-min-turnover"),
      resetFilters: byId("research-reset-filters"),
      viewButtons: Array.from(document.querySelectorAll("[data-research-view]")),
      columnButtons: Array.from(document.querySelectorAll("[data-research-columns]")),
      sortButtons: Array.from(document.querySelectorAll("[data-research-sort]")),
      symbolList: byId("research-symbol-list"),
      rangeButtons: Array.from(document.querySelectorAll("[data-chart-range]")),
      chartContainer: byId("research-chart-container"),
      chartSummary: byId("research-chart-summary"),
      selectedEvents: byId("research-selected-events"),
      selectedStrategies: byId("research-selected-strategies"),
      selectedNotes: byId("research-selected-notes"),
      prepareOrder: byId("research-prepare-order"),
    };
  }

  function init(options = {}) {
    if (runtime.initialized) {
      return true;
    }
    bindElements();
    if (!runtime.elements.tableBody || !runtime.elements.tableView || !runtime.elements.chartView) {
      return false;
    }
    runtime.initialized = true;
    restoreControls();
    bindEvents();
    runtime.chart = window.StocksToolChart?.create(runtime.elements.chartContainer) || null;
    observeLanguage();
    renderAll();
    setTechnicalFiltersDisabled(true);
    if (options.autoRefresh) {
      void refresh(options);
    }
    return true;
  }

  function bindEvents() {
    const inputs = [
      [runtime.elements.search, "search"],
      [runtime.elements.source, "source"],
      [runtime.elements.event, "event"],
      [runtime.elements.held, "held"],
      [runtime.elements.strategy, "strategy"],
      [runtime.elements.minDayChange, "minDayChange"],
      [runtime.elements.minReturn20, "minReturn20"],
      [runtime.elements.minReturn60, "minReturn60"],
      [runtime.elements.maxVolatility, "maxVolatility"],
      [runtime.elements.minTurnover, "minTurnover"],
    ];
    for (const [element, key] of inputs) {
      if (!element) {
        continue;
      }
      const eventName = element.tagName === "INPUT" && element.type !== "checkbox" ? "input" : "change";
      element.addEventListener(eventName, () => {
        persisted.filters[key] = readControlValue(element);
        persistState();
        applyFilterChange();
      });
    }
    const checks = [
      [runtime.elements.closeAboveSma20, "closeAboveSma20"],
      [runtime.elements.sma20AboveSma50, "sma20AboveSma50"],
    ];
    for (const [element, key] of checks) {
      element?.addEventListener("change", () => {
        persisted.filters[key] = element.checked;
        persistState();
        applyFilterChange();
      });
    }
    runtime.elements.resetFilters?.addEventListener("click", resetFilters);

    for (const button of runtime.elements.viewButtons) {
      button.addEventListener("click", () => setView(button.dataset.researchView));
    }
    for (const button of runtime.elements.columnButtons) {
      button.addEventListener("click", () => setColumnSet(button.dataset.researchColumns));
    }
    for (const button of runtime.elements.sortButtons) {
      button.addEventListener("click", () => setSort(button.dataset.researchSort));
    }
    for (const button of runtime.elements.rangeButtons) {
      button.addEventListener("click", () => setRange(button.dataset.chartRange));
    }
    bindArrowNavigation(runtime.elements.viewButtons, (button) => setView(button.dataset.researchView));
    bindArrowNavigation(runtime.elements.columnButtons, (button) => setColumnSet(button.dataset.researchColumns));
    bindArrowNavigation(runtime.elements.rangeButtons, (button) => setRange(button.dataset.chartRange));

    runtime.elements.tableBody.addEventListener("click", handleResearchAction);
    runtime.elements.tableBody.addEventListener("keydown", handleResearchKeydown);
    runtime.elements.symbolList?.addEventListener("click", handleResearchAction);
    runtime.elements.prepareOrder?.addEventListener("click", prepareSelectedOrder);
  }

  function bindArrowNavigation(buttons, activate) {
    buttons.forEach((button, index) => {
      button.addEventListener("keydown", (event) => {
        let nextIndex = index;
        if (event.key === "ArrowRight" || event.key === "ArrowDown") {
          nextIndex = (index + 1) % buttons.length;
        } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
          nextIndex = (index - 1 + buttons.length) % buttons.length;
        } else if (event.key === "Home") {
          nextIndex = 0;
        } else if (event.key === "End") {
          nextIndex = buttons.length - 1;
        } else {
          return;
        }
        event.preventDefault();
        const target = buttons[nextIndex];
        activate(target);
        target.focus();
      });
    });
  }

  function restoreControls() {
    const pairs = [
      [runtime.elements.search, "search"],
      [runtime.elements.source, "source"],
      [runtime.elements.event, "event"],
      [runtime.elements.held, "held"],
      [runtime.elements.strategy, "strategy"],
      [runtime.elements.minDayChange, "minDayChange"],
      [runtime.elements.minReturn20, "minReturn20"],
      [runtime.elements.minReturn60, "minReturn60"],
      [runtime.elements.maxVolatility, "maxVolatility"],
      [runtime.elements.minTurnover, "minTurnover"],
    ];
    for (const [element, key] of pairs) {
      if (element) {
        if (element.type === "checkbox") {
          element.checked = Boolean(persisted.filters[key]);
        } else {
          element.value = persisted.filters[key] ?? "";
        }
      }
    }
    if (runtime.elements.closeAboveSma20) {
      runtime.elements.closeAboveSma20.checked = Boolean(persisted.filters.closeAboveSma20);
    }
    if (runtime.elements.sma20AboveSma50) {
      runtime.elements.sma20AboveSma50.checked = Boolean(persisted.filters.sma20AboveSma50);
    }
  }

  function applySavedScreen(screen) {
    const configuration = screen?.configuration && typeof screen.configuration === "object" ? screen.configuration : {};
    const defaults = cloneDefaultState();
    persisted.filters = { ...defaults.filters, ...(configuration.filters || {}) };
    persisted.sort = {
      ...defaults.sort,
      ...(configuration.sort || {}),
      direction: configuration.sort?.direction === "desc" ? "desc" : "asc",
    };
    persisted.view = VALID_VIEWS.has(configuration.view) ? configuration.view : defaults.view;
    const savedRange = configuration.history_range;
    persisted.range = VALID_RANGES.has(savedRange) ? savedRange : defaults.range;
    persisted.columnSet = VALID_COLUMN_SETS.has(configuration.column_set || configuration.columnSet)
      ? (configuration.column_set || configuration.columnSet)
      : defaults.columnSet;
    persisted.selectedSymbol = normalizeSymbol(configuration.selected_symbol);
    if (configuration.watchlist_id && runtime.elements.watchlist) {
      runtime.elements.watchlist.value = configuration.watchlist_id;
      runtime.watchlistId = configuration.watchlist_id;
    }
    persistState();
    restoreControls();
    updateSourceOptions();
    ensureSelection();
    renderAll();
    if (persisted.view === "chart") void loadSelectedChart();
    return true;
  }

  async function refresh(options = {}) {
    if (!runtime.initialized && !init()) {
      return false;
    }
    const normalizedOptions = typeof options === "string" ? { externalAccountId: options } : options;
    runtime.externalAccountId = String(
      normalizedOptions.externalAccountId ??
      normalizedOptions.external_account_id ??
      normalizedOptions.accountId ??
      document.getElementById("account-select")?.value ??
      runtime.externalAccountId ??
      "",
    );
    runtime.watchlistId = String(
      normalizedOptions.watchlistId ??
      normalizedOptions.watchlist_id ??
      document.getElementById("research-watchlist-select")?.value ??
      runtime.watchlistId ??
      "",
    );
    const generation = ++runtime.refreshGeneration;
    setTechnicalFiltersDisabled(true);
    setStatus("loading");
    setProgress("universe");

    const query = new URLSearchParams({ mode: "paper" });
    if (runtime.externalAccountId) {
      query.set("external_account_id", runtime.externalAccountId);
    }
    if (runtime.watchlistId) {
      query.set("watchlist_id", runtime.watchlistId);
    }

    let universe;
    try {
      universe = await fetchJson(`/research/universe?${query.toString()}`);
    } catch (error) {
      if (generation !== runtime.refreshGeneration) {
        return false;
      }
      setStatus(runtime.rows.length ? "stale" : "error", { message: error?.message || String(error) });
      setProgress(runtime.rows.length ? "stale" : "error");
      setTechnicalFiltersDisabled(!runtime.technicalsComplete);
      renderAll();
      return false;
    }
    if (generation !== runtime.refreshGeneration) {
      return false;
    }

    const previousTechnicals = new Map(runtime.rows.map((row) => [row.symbol, row.technicals]));
    runtime.rows = (Array.isArray(universe?.rows) ? universe.rows : [])
      .map((row) => normalizeUniverseRow(row, previousTechnicals.get(normalizeSymbol(row?.symbol))))
      .filter((row) => row.symbol);
    runtime.generatedAt = universe?.generated_at || null;
    runtime.dataQuality = universe?.data_quality || null;
    runtime.warnings = Array.isArray(universe?.warnings) ? universe.warnings : [];
    setHeldFilterAvailability();
    runtime.technicalsComplete = runtime.rows.length === 0;
    ensureSelection();
    updateSourceOptions();
    setTechnicalFiltersDisabled(!runtime.technicalsComplete);
    renderAll();

    const symbols = runtime.rows.map((row) => row.symbol);
    const batchCount = Math.ceil(symbols.length / TECHNICAL_BATCH_SIZE);
    for (let index = 0; index < symbols.length; index += TECHNICAL_BATCH_SIZE) {
      if (generation !== runtime.refreshGeneration) {
        return false;
      }
      const batch = symbols.slice(index, index + TECHNICAL_BATCH_SIZE);
      const batchNumber = Math.floor(index / TECHNICAL_BATCH_SIZE) + 1;
      setProgress("technicals", { completed: batchNumber - 1, total: batchCount });
      let payload;
      try {
        const batchQuery = new URLSearchParams();
        for (const symbol of batch) {
          batchQuery.append("symbols", symbol);
        }
        payload = await fetchJson(`/research/technicals?${batchQuery.toString()}`);
      } catch (error) {
        payload = {
          results: batch.map((symbol) => ({
            symbol,
            status: "unavailable",
            warning: error?.message || String(error),
          })),
        };
      }
      if (generation !== runtime.refreshGeneration) {
        return false;
      }
      mergeTechnicalResults(batch, payload?.results);
      setProgress("technicals", { completed: batchNumber, total: batchCount });
      renderRowsAndList();
    }

    if (generation !== runtime.refreshGeneration) {
      return false;
    }
    runtime.technicalsComplete = true;
    setTechnicalFiltersDisabled(false);
    ensureSelection(getVisibleRows());
    const unavailable = runtime.rows.filter((row) => row.technicals?.status !== "ok").length;
    const rowWarningCount = runtime.rows.reduce(
      (total, row) => total + (Array.isArray(row.warnings) ? row.warnings.length : 0),
      0,
    );
    const degraded = !["live", "empty"].includes(runtime.dataQuality);
    setStatus(
      unavailable || runtime.warnings.length || rowWarningCount || degraded ? "partial" : "ready",
      { unavailable, dataQuality: runtime.dataQuality },
    );
    setProgress("complete", { total: runtime.rows.length });
    renderAll();
    if (persisted.view === "chart") {
      await loadSelectedChart();
    }
    return true;
  }

  function fetchJson(url, options) {
    if (typeof window.fetchJson === "function") {
      return window.fetchJson(url, options);
    }
    return window.fetch(url, options).then(async (response) => {
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      return response.json();
    });
  }

  function normalizeUniverseRow(source, previousTechnicals) {
    const quote = source?.quote && typeof source.quote === "object" ? source.quote : null;
    return {
      ...source,
      symbol: normalizeSymbol(source?.symbol),
      sources: Array.from(new Set((Array.isArray(source?.sources) ? source.sources : [])
        .map((value) => String(value).trim())
        .filter(Boolean))),
      notes: source?.notes || "",
      quote,
      dayChangePct: deriveDayChangePct(quote),
      technicals: previousTechnicals || null,
    };
  }

  function mergeTechnicalResults(batch, results) {
    const resultMap = new Map((Array.isArray(results) ? results : []).map((result) => [
      normalizeSymbol(result?.symbol),
      normalizeTechnical(result),
    ]));
    for (const symbol of batch) {
      const row = runtime.rows.find((candidate) => candidate.symbol === symbol);
      if (row) {
        row.technicals = resultMap.get(symbol) || {
          symbol,
          status: "unavailable",
          warning: "No technical result returned.",
        };
      }
    }
  }

  function normalizeTechnical(source) {
    return {
      ...source,
      symbol: normalizeSymbol(source?.symbol),
      status: ["ok", "partial", "unavailable"].includes(source?.status)
        ? source.status
        : "unavailable",
      return_20d_pct: toNumber(source?.return_20d_pct),
      return_60d_pct: toNumber(source?.return_60d_pct),
      sma20: toNumber(source?.sma20),
      sma50: toNumber(source?.sma50),
      realized_volatility_20d_pct: toNumber(source?.realized_volatility_20d_pct),
      average_volume_20d: toNumber(source?.average_volume_20d),
      average_turnover_20d: toNumber(source?.average_turnover_20d),
      close_above_sma20: normalizeBoolean(source?.close_above_sma20),
      sma20_above_sma50: normalizeBoolean(source?.sma20_above_sma50),
    };
  }

  function renderAll() {
    renderViewState();
    renderColumnState();
    renderSortState();
    renderRangeState();
    renderStatus();
    renderProgress();
    renderRowsAndList();
    renderSelectedDetails();
    notifyResearchState();
  }

  function notifyResearchState() {
    try {
      window.dispatchEvent(new CustomEvent("stocks-tool:research-state", {
        detail: { state: getState() },
      }));
    } catch (_error) {
      // Research remains usable when a host does not provide CustomEvent.
    }
  }

  function renderRowsAndList() {
    const rows = getVisibleRows();
    renderTable(rows);
    renderSymbolList(rows);
  }

  function renderTable(rows) {
    const body = runtime.elements.tableBody;
    if (!body) {
      return;
    }
    body.replaceChildren();
    if (rows.length === 0) {
      const row = document.createElement("tr");
      const cell = document.createElement("td");
      cell.colSpan = 13;
      cell.className = "research-empty-cell";
      cell.textContent = text("没有符合当前条件的标的。", "No symbols match the current filters.");
      row.appendChild(cell);
      body.appendChild(row);
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const item of rows) {
      const row = document.createElement("tr");
      row.dataset.researchSelect = item.symbol;
      row.tabIndex = 0;
      row.setAttribute("aria-selected", item.symbol === persisted.selectedSymbol ? "true" : "false");
      if (item.symbol === persisted.selectedSymbol) {
        row.classList.add("is-selected");
      }
      const rowWarnings = [
        ...(Array.isArray(item.warnings) ? item.warnings : []),
        item.technicals?.warning,
      ].filter(Boolean);
      if (rowWarnings.length) {
        row.title = rowWarnings.join(" · ");
      }
      appendCell(row, item.symbol, "always", "research-symbol-cell");
      appendCell(row, formatMoney(quoteLast(item.quote)), "overview", "numeric");
      appendCell(row, formatSignedPercent(item.dayChangePct), "overview", toneClass(item.dayChangePct));
      appendCell(row, item.sources.map(formatSource).join(" · ") || "--", "overview");
      appendCell(row, formatMoney(item.position_market_value), "overview", "numeric");
      appendCell(row, formatSignedPercent(item.technicals?.return_20d_pct), "momentum", toneClass(item.technicals?.return_20d_pct));
      appendCell(row, formatSignedPercent(item.technicals?.return_60d_pct), "momentum", toneClass(item.technicals?.return_60d_pct));
      appendCell(row, formatPercent(item.technicals?.realized_volatility_20d_pct), "momentum", "numeric");
      appendCell(row, formatCompactMoney(item.technicals?.average_turnover_20d), "momentum", "numeric");
      appendCell(row, formatTrend(item.technicals), "momentum");
      appendCell(row, formatEvent(item.next_event), "strategy");
      appendCell(row, formatStrategies(item.strategy_states), "strategy");
      const actionCell = appendCell(row, "", "always", "research-row-action");
      const action = document.createElement("button");
      action.type = "button";
      action.className = "button compact ghost";
      action.dataset.researchOrder = item.symbol;
      action.textContent = text("准备订单", "Prepare order");
      action.setAttribute("aria-label", `${text("准备订单", "Prepare order")} ${item.symbol}`);
      actionCell.appendChild(action);
      fragment.appendChild(row);
    }
    body.appendChild(fragment);
  }

  function appendCell(row, value, group, className = "") {
    const cell = document.createElement("td");
    cell.dataset.columnGroup = group;
    if (className) {
      cell.className = className;
    }
    cell.textContent = value;
    row.appendChild(cell);
    return cell;
  }

  function renderSymbolList(rows) {
    const list = runtime.elements.symbolList;
    if (!list) {
      return;
    }
    list.replaceChildren();
    const fragment = document.createDocumentFragment();
    for (const row of rows) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "research-symbol-option";
      button.dataset.researchSelect = row.symbol;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", row.symbol === persisted.selectedSymbol ? "true" : "false");
      if (row.symbol === persisted.selectedSymbol) {
        button.classList.add("is-selected");
      }
      const symbol = document.createElement("strong");
      symbol.textContent = row.symbol;
      const change = document.createElement("span");
      change.textContent = formatSignedPercent(row.dayChangePct);
      change.className = toneClass(row.dayChangePct);
      button.append(symbol, change);
      fragment.appendChild(button);
    }
    list.appendChild(fragment);
  }

  function renderSelectedDetails() {
    const row = selectedRow();
    setDetail(runtime.elements.selectedEvents, row ? formatEvent(row.next_event) : "--");
    setDetail(runtime.elements.selectedStrategies, row ? formatStrategies(row.strategy_states) : "--");
    setDetail(runtime.elements.selectedNotes, row ? noteText(row.notes) : "--");
    if (runtime.elements.prepareOrder) {
      runtime.elements.prepareOrder.disabled = !row;
      runtime.elements.prepareOrder.dataset.symbol = row?.symbol || "";
    }
    renderChartSummary(row);
  }

  function setDetail(element, value) {
    if (element) {
      element.textContent = value;
    }
  }

  function renderChartSummary(row, history = null) {
    const summary = runtime.elements.chartSummary;
    if (!summary) {
      return;
    }
    if (!row) {
      summary.textContent = text("请选择标的。", "Select a symbol.");
      return;
    }
    const parts = [row.symbol, formatMoney(quoteLast(row.quote)), formatSignedPercent(row.dayChangePct)];
    if (history?.bars?.length) {
      parts.push(`${history.bars.length} ${text("根日线", "daily bars")}`);
    }
    summary.textContent = parts.join(" · ");
  }

  function renderViewState() {
    const chartActive = persisted.view === "chart";
    runtime.elements.tableView.hidden = chartActive;
    runtime.elements.chartView.hidden = !chartActive;
    for (const button of runtime.elements.viewButtons) {
      const active = button.dataset.researchView === persisted.view;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
      button.setAttribute("aria-selected", String(active));
      button.tabIndex = active ? 0 : -1;
    }
  }

  function renderColumnState() {
    runtime.elements.tableView.dataset.columnSet = persisted.columnSet;
    for (const button of runtime.elements.columnButtons) {
      const active = button.dataset.researchColumns === persisted.columnSet;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    }
  }

  function renderSortState() {
    for (const button of runtime.elements.sortButtons) {
      const active = button.dataset.researchSort === persisted.sort.key;
      button.setAttribute("aria-pressed", String(active));
      const header = button.closest("th");
      if (header) {
        header.setAttribute(
          "aria-sort",
          active ? (persisted.sort.direction === "asc" ? "ascending" : "descending") : "none",
        );
      }
    }
  }

  function setView(view) {
    if (!VALID_VIEWS.has(view) || persisted.view === view) {
      return;
    }
    persisted.view = view;
    persistState();
    renderViewState();
    if (view === "chart") {
      window.requestAnimationFrame(() => {
        runtime.chart?.resize();
        void loadSelectedChart();
      });
    }
  }

  function setColumnSet(columnSet) {
    if (!VALID_COLUMN_SETS.has(columnSet)) {
      return;
    }
    persisted.columnSet = columnSet;
    persistState();
    renderColumnState();
    notifyResearchState();
  }

  function setSort(key) {
    if (!key || (!runtime.technicalsComplete && TECHNICAL_SORT_KEYS.has(key))) {
      return;
    }
    if (persisted.sort.key === key) {
      persisted.sort.direction = persisted.sort.direction === "asc" ? "desc" : "asc";
    } else {
      persisted.sort = { key, direction: "asc" };
    }
    persistState();
    renderSortState();
    renderRowsAndList();
    notifyResearchState();
  }

  function setRange(range) {
    if (!VALID_RANGES.has(range)) {
      return;
    }
    persisted.range = range;
    persistState();
    renderRangeState();
    notifyResearchState();
    if (persisted.view === "chart") {
      void loadSelectedChart();
    }
  }

  function renderRangeState() {
    for (const button of runtime.elements.rangeButtons) {
      const active = button.dataset.chartRange === persisted.range;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    }
  }

  function selectSymbol(symbol, options = {}) {
    const normalized = normalizeSymbol(symbol);
    if (!normalized || !runtime.rows.some((row) => row.symbol === normalized)) {
      return false;
    }
    persisted.selectedSymbol = normalized;
    persistState();
    renderRowsAndList();
    renderSelectedDetails();
    notifyResearchState();
    if (persisted.view === "chart" && options.loadChart !== false) {
      void loadSelectedChart();
    }
    return true;
  }

  function handleResearchAction(event) {
    const orderButton = event.target.closest("[data-research-order]");
    if (orderButton) {
      event.stopPropagation();
      selectSymbol(orderButton.dataset.researchOrder, { loadChart: false });
      prepareSelectedOrder();
      return;
    }
    const selectable = event.target.closest("[data-research-select]");
    if (selectable) {
      selectSymbol(selectable.dataset.researchSelect);
    }
  }

  function handleResearchKeydown(event) {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    const selectable = event.target.closest("[data-research-select]");
    if (!selectable || event.target.closest("button, a, input, select, textarea")) {
      return;
    }
    event.preventDefault();
    selectSymbol(selectable.dataset.researchSelect);
  }

  function prepareSelectedOrder() {
    const row = selectedRow();
    const symbolInput = document.getElementById("order-symbol");
    if (!row || !symbolInput) {
      return false;
    }
    // Research context intentionally transfers only the symbol. Direction, size,
    // order type, and price remain explicit operator decisions in the ticket.
    symbolInput.value = row.symbol;
    window.StocksToolWorkspace?.openExecutionDrawer?.({ tab: "ticket" });
    return true;
  }

  async function loadSelectedChart() {
    const row = selectedRow();
    if (!row || !runtime.chart) {
      runtime.chart?.setUnavailable(text("请选择标的。", "Select a symbol."));
      return false;
    }
    const generation = ++runtime.chartGeneration;
    runtime.elements.chartContainer?.setAttribute("aria-busy", "true");
    if (runtime.elements.chartSummary) {
      runtime.elements.chartSummary.textContent = `${row.symbol} · ${text("正在加载图表…", "Loading chart…")}`;
    }
    try {
      const url = `/research/symbols/${encodeURIComponent(row.symbol)}/history?range=${encodeURIComponent(persisted.range)}`;
      const history = await fetchJson(url);
      if (generation !== runtime.chartGeneration || row.symbol !== persisted.selectedSymbol) {
        return false;
      }
      runtime.chart.render(history?.bars || [], {
        locale: document.documentElement.lang || "zh-CN",
        emptyMessage: text("暂无可用历史行情。", "No chart history available."),
      });
      renderChartSummary(row, history);
      return true;
    } catch (error) {
      if (generation !== runtime.chartGeneration) {
        return false;
      }
      runtime.chart.setUnavailable(
        `${text("图表加载失败", "Chart load failed")}: ${error?.message || String(error)}`,
      );
      renderChartSummary(row);
      return false;
    } finally {
      if (generation === runtime.chartGeneration) {
        runtime.elements.chartContainer?.removeAttribute("aria-busy");
      }
    }
  }

  function getVisibleRows() {
    const filtered = runtime.rows.filter(matchesFilters);
    const direction = persisted.sort.direction === "desc" ? -1 : 1;
    const sortKey = !runtime.technicalsComplete && TECHNICAL_SORT_KEYS.has(persisted.sort.key)
      ? "symbol"
      : persisted.sort.key;
    return filtered.sort((left, right) => {
      const leftValue = sortValue(left, sortKey);
      const rightValue = sortValue(right, sortKey);
      if (leftValue === null && rightValue !== null) {
        return 1;
      }
      if (rightValue === null && leftValue !== null) {
        return -1;
      }
      const comparison = typeof leftValue === "string"
        ? leftValue.localeCompare(String(rightValue || ""))
        : Number(leftValue || 0) - Number(rightValue || 0);
      return comparison === 0 ? left.symbol.localeCompare(right.symbol) : comparison * direction;
    });
  }

  function matchesFilters(row) {
    const filters = persisted.filters;
    const search = String(filters.search || "").trim().toUpperCase();
    if (search) {
      const haystack = [row.symbol, row.sources.join(" "), noteText(row.notes), formatStrategies(row.strategy_states)]
        .join(" ")
        .toUpperCase();
      if (!haystack.includes(search)) {
        return false;
      }
    }
    if (filters.source && !row.sources.includes(filters.source)) {
      return false;
    }
    if (!matchesHeldFilter(row, filters.held) || !matchesStrategyFilter(row, filters.strategy)) {
      return false;
    }
    if (!matchesEventFilter(row.next_event, filters.event)) {
      return false;
    }
    if (!meetsMinimum(row.dayChangePct, filters.minDayChange)) {
      return false;
    }
    if (!runtime.technicalsComplete) {
      return true;
    }
    const technicals = row.technicals;
    if (filters.closeAboveSma20 && technicals?.close_above_sma20 !== true) {
      return false;
    }
    if (filters.sma20AboveSma50 && technicals?.sma20_above_sma50 !== true) {
      return false;
    }
    if (!meetsMinimum(technicals?.return_20d_pct, filters.minReturn20)) {
      return false;
    }
    if (!meetsMinimum(technicals?.return_60d_pct, filters.minReturn60)) {
      return false;
    }
    if (!meetsMaximum(technicals?.realized_volatility_20d_pct, filters.maxVolatility)) {
      return false;
    }
    return meetsMinimum(technicals?.average_turnover_20d, filters.minTurnover);
  }

  function matchesHeldFilter(row, value) {
    const normalized = String(value || "").toLowerCase();
    if (!normalized || normalized === "all" || normalized === "any") {
      return true;
    }
    if (runtime.warnings.includes("account_snapshot_unavailable")) {
      return true;
    }
    const held = (toNumber(row.position_quantity) || 0) !== 0;
    return ["held", "yes", "true", "only"].includes(normalized) ? held : !held;
  }

  function matchesStrategyFilter(row, value) {
    const normalized = String(value || "").toLowerCase();
    if (!normalized || normalized === "all" || normalized === "any") {
      return true;
    }
    const active = hasStrategy(row.strategy_states);
    return ["active", "configured", "yes", "true", "only"].includes(normalized) ? active : !active;
  }

  function matchesEventFilter(event, value) {
    const normalized = String(value || "").toLowerCase();
    if (!normalized || normalized === "all" || normalized === "any") {
      return true;
    }
    const date = eventDate(event);
    if (["none", "no-event"].includes(normalized)) {
      return !date;
    }
    if (!date) {
      return false;
    }
    const days = Number.parseInt(normalized, 10);
    if (!Number.isFinite(days)) {
      return true;
    }
    const difference = (date.getTime() - Date.now()) / 86_400_000;
    return difference >= -1 && difference <= days;
  }

  function meetsMinimum(value, filter) {
    if (filter === "" || filter === null || filter === undefined) {
      return true;
    }
    const minimum = toNumber(filter);
    const actual = toNumber(value);
    return minimum === null || (actual !== null && actual >= minimum);
  }

  function meetsMaximum(value, filter) {
    if (filter === "" || filter === null || filter === undefined) {
      return true;
    }
    const maximum = toNumber(filter);
    const actual = toNumber(value);
    return maximum === null || (actual !== null && actual <= maximum);
  }

  function sortValue(row, key) {
    const technicals = row.technicals;
    const values = {
      symbol: row.symbol,
      source: row.sources.join(" "),
      last: quoteLast(row.quote),
      price: quoteLast(row.quote),
      "quote.last": quoteLast(row.quote),
      day_change: row.dayChangePct,
      change: row.dayChangePct,
      "quote.change_pct": row.dayChangePct,
      position: toNumber(row.position_quantity),
      position_market_value: toNumber(row.position_market_value),
      return_20d: technicals?.return_20d_pct,
      return_20d_pct: technicals?.return_20d_pct,
      return_60d: technicals?.return_60d_pct,
      return_60d_pct: technicals?.return_60d_pct,
      volatility: technicals?.realized_volatility_20d_pct,
      realized_volatility_20d_pct: technicals?.realized_volatility_20d_pct,
      turnover: technicals?.average_turnover_20d,
      average_turnover_20d: technicals?.average_turnover_20d,
      event: eventDate(row.next_event)?.getTime() ?? null,
      next_event: eventDate(row.next_event)?.getTime() ?? null,
      strategy: hasStrategy(row.strategy_states) ? 1 : 0,
    };
    const value = values[key];
    return value === undefined || value === null || Number.isNaN(value) ? null : value;
  }

  function ensureSelection(candidates = runtime.rows) {
    if (!candidates.some((row) => row.symbol === persisted.selectedSymbol)) {
      persisted.selectedSymbol = candidates[0]?.symbol || "";
      persistState();
      return true;
    }
    return false;
  }

  function applyFilterChange() {
    const selectionChanged = ensureSelection(getVisibleRows());
    renderRowsAndList();
    renderSelectedDetails();
    notifyResearchState();
    if (selectionChanged && persisted.view === "chart") {
      void loadSelectedChart();
    }
  }

  function selectedRow() {
    return runtime.rows.find((row) => row.symbol === persisted.selectedSymbol) || null;
  }

  function resetFilters() {
    persisted.filters = { ...cloneDefaultState().filters };
    restoreControls();
    persistState();
    applyFilterChange();
  }

  function updateSourceOptions() {
    const select = runtime.elements.source;
    if (!select || select.tagName !== "SELECT") {
      return;
    }
    const selected = persisted.filters.source;
    const sources = Array.from(new Set(runtime.rows.flatMap((row) => row.sources))).sort();
    select.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = text("全部来源", "All sources");
    select.appendChild(all);
    for (const source of sources) {
      const option = document.createElement("option");
      option.value = source;
      option.textContent = formatSource(source);
      select.appendChild(option);
    }
    select.value = sources.includes(selected) ? selected : "";
    if (select.value !== selected) {
      persisted.filters.source = select.value;
      persistState();
    }
  }

  function setTechnicalFiltersDisabled(disabled) {
    for (const id of TECHNICAL_FILTER_IDS) {
      const element = document.getElementById(id);
      if (element) {
        element.disabled = disabled;
        element.setAttribute("aria-disabled", String(disabled));
        element.title = disabled
          ? text("技术指标批次完成后可用", "Available after all technical batches complete")
          : "";
      }
    }
    for (const button of runtime.elements.sortButtons) {
      const technicalSort = TECHNICAL_SORT_KEYS.has(button.dataset.researchSort);
      if (!technicalSort) {
        continue;
      }
      button.disabled = disabled;
      button.setAttribute("aria-disabled", String(disabled));
      button.title = disabled
        ? text("技术指标批次完成后可排序", "Sorting is available after all technical batches complete")
        : "";
    }
  }

  function setHeldFilterAvailability() {
    const unavailable = runtime.warnings.includes("account_snapshot_unavailable");
    const select = runtime.elements.held;
    const hint = runtime.elements.heldFilterStatus;
    if (select) {
      select.disabled = unavailable;
      select.setAttribute("aria-disabled", String(unavailable));
      select.title = unavailable
        ? text("暂无可信账户快照，持仓情况未知；此筛选已停用。", "No trusted account snapshot; holding status is unknown and this filter is disabled.")
        : "";
    }
    if (unavailable && persisted.filters.held) {
      persisted.filters.held = "";
      persistState();
    }
    if (hint) {
      hint.hidden = !unavailable;
      hint.textContent = unavailable
        ? text("持仓情况未知，不能判断已持仓/未持仓。", "Holding status is unknown; held/not-held cannot be determined.")
        : "";
    }
  }

  function setStatus(key, values = {}) {
    runtime.status = { key, values };
    renderStatus();
  }

  function renderStatus() {
    const element = runtime.elements.status;
    if (!element) {
      return;
    }
    const { key, values } = runtime.status;
    const labels = {
      idle: text("等待加载研究标的。", "Research universe is ready to load."),
      loading: text("正在加载研究标的…", "Loading research universe…"),
      ready: text(`已加载 ${runtime.rows.length} 个标的。`, `${runtime.rows.length} symbols loaded.`),
      partial: text(
        `已加载 ${runtime.rows.length} 个标的，${values.unavailable || 0} 个技术指标不完整，数据质量 ${values.dataQuality || "partial"}。`,
        `${runtime.rows.length} symbols loaded; ${values.unavailable || 0} technical results incomplete; data quality ${values.dataQuality || "partial"}.`,
      ),
      stale: text(
        `刷新失败，保留上次数据：${values.message || "--"}`,
        `Refresh failed; showing stale data: ${values.message || "--"}`,
      ),
      error: text(`研究数据加载失败：${values.message || "--"}`, `Research load failed: ${values.message || "--"}`),
    };
    element.textContent = labels[key] || labels.idle;
    element.dataset.tone = ["error", "stale"].includes(key) ? "danger" : key === "partial" ? "warning" : "neutral";
  }

  function setProgress(key, values = {}) {
    runtime.progressState = { key, values };
    renderProgress();
  }

  function renderProgress() {
    const element = runtime.elements.progress;
    if (!element) {
      return;
    }
    const { key = "idle", values = {} } = runtime.progressState || {};
    const labels = {
      idle: "",
      universe: text("正在加载报价与持仓…", "Loading quotes and positions…"),
      technicals: text(
        `技术指标批次 ${values.completed || 0}/${values.total || 0}`,
        `Technical batches ${values.completed || 0}/${values.total || 0}`,
      ),
      complete: text(`技术指标完成 · ${values.total || 0} 个标的`, `Technicals complete · ${values.total || 0} symbols`),
      stale: text("刷新失败，当前为陈旧数据。", "Refresh failed; current data is stale."),
      error: text("没有可用研究数据。", "No research data available."),
    };
    element.textContent = labels[key] ?? "";
    element.setAttribute("aria-live", "polite");
  }

  function observeLanguage() {
    if (typeof MutationObserver !== "function") {
      return;
    }
    runtime.lastLanguage = document.documentElement.lang || "zh-CN";
    runtime.languageObserver = new MutationObserver(() => {
      const language = document.documentElement.lang || "zh-CN";
      if (language === runtime.lastLanguage) {
        return;
      }
      runtime.lastLanguage = language;
      updateSourceOptions();
      renderAll();
      if (persisted.view === "chart") {
        runtime.chart?.resize();
      }
    });
    runtime.languageObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
  }

  function getState() {
    return {
      ...JSON.parse(JSON.stringify(persisted)),
      rows: runtime.rows.slice(),
      generatedAt: runtime.generatedAt,
      dataQuality: runtime.dataQuality,
      warnings: runtime.warnings.slice(),
      technicalsComplete: runtime.technicalsComplete,
      externalAccountId: runtime.externalAccountId,
      watchlistId: runtime.watchlistId,
    };
  }

  function readControlValue(element) {
    if (element?.type === "checkbox") {
      return element.checked ? "only" : "";
    }
    return element?.value ?? "";
  }

  function normalizeSymbol(value) {
    return String(value || "").trim().toUpperCase();
  }

  function toNumber(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function normalizeBoolean(value) {
    return value === true ? true : value === false ? false : null;
  }

  function quoteLast(quote) {
    return toNumber(quote?.last_done ?? quote?.last_price ?? quote?.price ?? quote?.close);
  }

  function deriveDayChangePct(quote) {
    const last = quoteLast(quote);
    const previous = toNumber(quote?.prev_close ?? quote?.previous_close);
    if (last !== null && previous !== null && previous !== 0) {
      return ((last - previous) / previous) * 100;
    }
    return toNumber(quote?.change_percent ?? quote?.change_pct ?? quote?.change_rate);
  }

  function eventDate(event) {
    const raw = event?.event_at ?? event?.starts_at ?? event?.scheduled_at ?? event?.event_date ?? event?.date;
    if (!raw) {
      return null;
    }
    const date = new Date(raw);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function formatEvent(event) {
    if (!event) {
      return "--";
    }
    const kind = event.kind || event.event_type || event.type || event.title || text("事件", "Event");
    const date = eventDate(event);
    if (!date) {
      return String(kind);
    }
    return `${kind} · ${new Intl.DateTimeFormat(isChinese() ? "zh-CN" : "en-US", {
      month: "short",
      day: "numeric",
    }).format(date)}`;
  }

  function hasStrategy(states) {
    if (Array.isArray(states)) {
      return states.length > 0;
    }
    if (states && typeof states === "object") {
      return Object.values(states).some((value) => value !== null && value !== false && value !== "" && value !== "inactive");
    }
    return Boolean(states);
  }

  function formatStrategies(states) {
    const label = (value) => {
      const raw = String(value || "");
      const known = {
        bull_put_pool: text("牛市看跌标的池", "Bull Put pool"),
        zero_dte_pool: text("零日期权标的池", "Zero-DTE pool"),
        covered_call_active: text("备兑看涨持仓", "Covered Call active"),
        bull_put_spread: text("牛市看跌价差", "Bull Put spread"),
        strategy_proposal: text("策略提案", "Strategy proposal"),
        bull_put_ready: text("牛市看跌价差：可继续评估", "Bull Put: ready for evaluation"),
        zero_dte_preview_only: text("零日期权：仅供研究", "Zero-DTE: research only"),
      };
      if (known[raw]) return known[raw];
      const prefix = raw.split(":", 1)[0];
      const prefixLabel = known[prefix];
      return prefixLabel ? `${prefixLabel}${raw.slice(prefix.length)}` : raw;
    };
    if (Array.isArray(states)) {
      const labels = states.map((state) => typeof state === "string"
        ? state
        : state?.strategy || state?.name || state?.kind || state?.status).filter(Boolean);
      return labels.map(label).join(" · ") || "--";
    }
    if (states && typeof states === "object") {
      const labels = Object.entries(states).filter(([, value]) => value !== null && value !== false && value !== "")
        .map(([key, value]) => typeof value === "string" ? `${label(key)}: ${label(value)}` : label(key));
      return labels.join(" · ") || "--";
    }
    return states ? String(states) : "--";
  }

  function formatSource(source) {
    const labels = {
      watchlist: text("自选列表", "Watchlist"),
      position: text("已有持仓", "Position"),
      bull_put_pool: text("牛市看跌候选池", "Bull Put pool"),
      zero_dte_pool: text("零日期权研究池", "Zero-DTE research pool"),
      bull_put_spread: text("当前价差持仓", "Active spread"),
    };
    return labels[source] || source;
  }

  function noteText(notes) {
    if (Array.isArray(notes)) {
      return notes.map((note) => typeof note === "string" ? note : note?.note || note?.text).filter(Boolean).join(" · ") || "--";
    }
    if (notes && typeof notes === "object") {
      return notes.note || notes.text || JSON.stringify(notes);
    }
    return notes ? String(notes) : "--";
  }

  function formatTrend(technicals) {
    if (!technicals || technicals.status === "unavailable") {
      return "--";
    }
    const labels = [];
    if (technicals.close_above_sma20 !== null) {
      labels.push(technicals.close_above_sma20
        ? text("收盘高于20日均价", "Close>SMA20")
        : text("收盘不高于20日均价", "Close≤SMA20"));
    }
    if (technicals.sma20_above_sma50 !== null) {
      labels.push(technicals.sma20_above_sma50 ? text("20日均价高于50日均价", "SMA20>SMA50") : text("20日均价不高于50日均价", "SMA20≤SMA50"));
    }
    return labels.join(" · ") || "--";
  }

  function formatMoney(value) {
    const number = toNumber(value);
    return number === null ? "--" : new Intl.NumberFormat(isChinese() ? "zh-CN" : "en-US", {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    }).format(number);
  }

  function formatCompactMoney(value) {
    const number = toNumber(value);
    return number === null ? "--" : new Intl.NumberFormat(isChinese() ? "zh-CN" : "en-US", {
      style: "currency",
      currency: "USD",
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(number);
  }

  function formatQuantity(value) {
    const number = toNumber(value);
    return number === null ? "--" : new Intl.NumberFormat(isChinese() ? "zh-CN" : "en-US", {
      maximumFractionDigits: 4,
    }).format(number);
  }

  function formatSignedPercent(value) {
    const number = toNumber(value);
    if (number === null) {
      return "--";
    }
    return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
  }

  function formatPercent(value) {
    const number = toNumber(value);
    return number === null ? "--" : `${number.toFixed(2)}%`;
  }

  function toneClass(value) {
    const number = toNumber(value);
    return number === null || number === 0 ? "numeric" : number > 0 ? "positive" : "negative";
  }

  function isChinese() {
    return (document.documentElement.lang || "zh-CN").toLowerCase().startsWith("zh");
  }

  function text(chinese, english) {
    return isChinese() ? chinese : english;
  }

  window.StocksToolResearch = { init, refresh, selectSymbol, getState, applySavedScreen };
})();

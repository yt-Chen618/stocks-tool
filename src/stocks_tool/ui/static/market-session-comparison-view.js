(function () {
  "use strict";

  let initialized = false;
  let requestToken = 0;
  let currentSymbol = "";
  let comparison = null;
  let lastScope = null;
  let savedComparisons = [];
  let savedNextCursor = null;
  let savedHasMore = false;
  let savedLoading = false;
  let savedToken = 0;
  let captureKeyState = null;

  function ui() {
    return window.StocksToolWorkbenchUI;
  }

  function node(id) {
    return document.getElementById(id);
  }

  function escape(value) {
    return ui().escapeHtml(value ?? "");
  }

  function objectPayload(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function isDemo() {
    return document.body?.dataset?.demo === "true";
  }

  function selectedAccount() {
    const state = ui().getState?.() || {};
    return {
      accountId: state.selectedAccountId || ui().accountId?.() || "",
      generation: Number(state.accountLoadGeneration || 0),
    };
  }

  function readSymbol() {
    const input = node("market-session-comparison-symbol");
    return String(input?.value || "").trim().toUpperCase();
  }

  function scopeIsCurrent(scope, symbol, token) {
    const selected = selectedAccount();
    return Boolean(
      token === requestToken &&
        scope?.accountId &&
        scope.accountId === selected.accountId &&
        scope.generation === selected.generation &&
        symbol === readSymbol(),
    );
  }

  function savedScopeIsCurrent(scope, symbol, token) {
    const selected = selectedAccount();
    return Boolean(
      token === savedToken &&
        scope?.accountId &&
        scope.accountId === selected.accountId &&
        scope.generation === selected.generation &&
        symbol === readSymbol(),
    );
  }

  function savedStatusText(value) {
    const payload = objectPayload(value);
    if (payload.status === "valid" && payload.data_quality === "verified") return isDemo() ? "演示数据 · 完整" : "完整证据";
    if (payload.status === "partial" || payload.data_quality === "partial") return "部分证据";
    return "缺少完整证据";
  }

  function savedTradingDate(value) {
    const payload = objectPayload(value);
    return payload.target_trading_day || payload.baseline_session_date || payload.regular_close_evidence?.trading_date || payload.post_market_evidence?.trading_date || "交易日未知";
  }

  function resetSavedComparisons(message = "选择标的后读取历史记录") {
    savedToken += 1;
    savedComparisons = [];
    savedNextCursor = null;
    savedHasMore = false;
    savedLoading = false;
    renderSavedComparisons(message);
  }

  function setBusy(kind, busy) {
    const refresh = node("market-session-comparison-refresh");
    const capture = node("market-session-comparison-capture");
    if (refresh) refresh.disabled = busy;
    if (capture) capture.disabled = busy;
    if (busy) {
      const status = node("market-session-comparison-status");
      if (status) {
        status.textContent = kind === "capture" ? "正在采集时段证据…" : "正在读取已保存对照…";
        status.dataset.tone = "warning";
      }
    }
  }

  function setSavedBusy(busy) {
    const select = node("market-session-comparison-saved-select");
    const loadMore = node("market-session-comparison-load-more");
    savedLoading = busy;
    if (loadMore) {
      loadMore.disabled = busy || !savedHasMore;
      loadMore.textContent = busy ? "正在读取历史记录…" : "加载更多历史记录";
    }
    if (select && !savedComparisons.length) select.disabled = busy;
  }

  function renderSavedComparisons(emptyMessage = "暂无已保存的对照") {
    const select = node("market-session-comparison-saved-select");
    const loadMore = node("market-session-comparison-load-more");
    if (!select) return;
    const selectedId = comparison?.id || select.value;
    select.replaceChildren();
    if (!savedComparisons.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = emptyMessage;
      select.appendChild(option);
      select.disabled = savedLoading;
    } else {
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "选择已保存的对照以复盘";
      select.appendChild(placeholder);
      for (const item of savedComparisons) {
        const option = document.createElement("option");
        option.value = item.id;
        option.textContent = `${item.symbol} · 美东交易日 ${savedTradingDate(item)} · 中国采集时间 ${formatDate(item.created_at, "Asia/Shanghai")} · ${savedStatusText(item)}`;
        option.selected = item.id === selectedId;
        select.appendChild(option);
      }
      select.disabled = false;
    }
    if (loadMore) {
      loadMore.disabled = savedLoading || !savedHasMore;
      loadMore.textContent = savedLoading ? "正在读取历史记录…" : "加载更多历史记录";
    }
  }

  function formatPrice(value, currency) {
    if (value === null || value === undefined || value === "") return "缺少证据";
    const number = Number(value);
    if (!Number.isFinite(number)) return "缺少证据";
    let formatted = number.toLocaleString("zh-CN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    });
    return currency ? `${formatted} ${currency}` : `${formatted}（货币未知）`;
  }

  function formatDate(value, timeZone) {
    if (!value) return "时间未知";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "时间格式不可识别";
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone,
    }).format(date);
  }

  function formatTradingDate(value) {
    if (!value) return "交易日未知";
    return String(value).slice(0, 10);
  }

  function formatPercent(value) {
    if (value === null || value === undefined || value === "") return "未计算（证据不足）";
    const number = Number(value);
    if (!Number.isFinite(number)) return "未计算（证据不足）";
    const prefix = number > 0 ? "+" : "";
    return `${prefix}${number.toFixed(2)}%`;
  }

  function statusText(status, quality) {
    if (status === "valid" && quality === "verified") return isDemo() ? "演示数据 · 三段证据" : "三段证据已验证";
    if (status === "partial" || quality === "partial") return isDemo() ? "演示数据 · 部分证据" : "部分证据可用";
    return isDemo() ? "演示数据 · 缺少时段证据" : "缺少完整时段证据";
  }

  function statusTone(status, quality) {
    if (status === "valid" && quality === "verified" && !isDemo()) return "success";
    if (status === "not_available" || quality === "unavailable") return "error";
    return "warning";
  }

  function sourceText(source) {
    const raw = String(source || "");
    if (isDemo() || raw === "mock_demo" || raw.includes("fixture")) return "演示数据";
    const labels = {
      pre_open_assessment_run: "已保存盘前评估",
      longbridge_quote: "Longbridge 行情",
      longbridge_daily_bar: "Longbridge 日线",
      longbridge_market_session_capture: "Longbridge 时段采集",
    };
    return labels[raw] || raw || "来源未知";
  }

  function reasonText(code) {
    const labels = {
      provider_unavailable: "行情服务暂时不可用",
      post_market_quote_missing: "没有盘后报价",
      regular_close_missing: "没有常规收盘参考",
      different_trading_day: "证据不属于同一个美东交易日",
      timestamp_timezone_unknown: "某条证据没有可确认的时区",
      evidence_before_baseline: "证据时间早于盘前基准",
      baseline_missing: "没有盘前基准",
      currency_mismatch: "证据货币不一致",
    };
    return labels[code] || String(code || "未知原因");
  }

  function evidenceCurrency(evidence, item) {
    return evidence?.currency || item?.currency || comparison?.currency || comparison?.quote_currency || null;
  }

  function evidenceMeta(evidence, item) {
    if (!evidence) {
      return "尚未提供这段证据，不能把缺失当成 0。";
    }
    const timestamp = evidence.timestamp
      ? `证据时间：中国 ${formatDate(evidence.timestamp, "Asia/Shanghai")} · 美东 ${formatDate(evidence.timestamp, "America/New_York")}`
      : "证据时间：中国/美东未知";
    const closeAt = evidence.session_close_at
      ? `收盘时点（美东）${formatDate(evidence.session_close_at, "America/New_York")}`
      : evidence.session === "pre_open" ? null : "收盘时点未知";
    const tradingDate = evidence.trading_date || item?.target_trading_day || item?.baseline_session_date;
    const source = sourceText(evidence.source);
    return [source, timestamp, closeAt, `交易日（美东）${formatTradingDate(tradingDate)}`].filter(Boolean).join(" · ");
  }

  function cardData(item) {
    const evidence = item.evidence;
    return `<article class="market-session-evidence-card${evidence ? "" : " is-missing"}" data-session="${escape(item.key)}">
      <span class="market-session-evidence-label">${escape(item.label)}</span>
      <strong>${escape(formatPrice(item.price, evidenceCurrency(evidence, item)))}</strong>
      <small>${escape(evidenceMeta(evidence, item))}</small>
    </article>`;
  }

  function renderCards(value) {
    const summary = node("market-session-comparison-summary");
    if (!summary) return;
    const payload = objectPayload(value);
    comparison = value && typeof value === "object" ? value : null;
    const entries = [
      { key: "pre_open", label: "盘前基准", price: payload.baseline_price, evidence: payload.baseline_evidence, target_trading_day: payload.target_trading_day, baseline_session_date: payload.baseline_session_date },
      { key: "regular_close", label: "常规收盘", price: payload.regular_close_price, evidence: payload.regular_close_evidence, target_trading_day: payload.target_trading_day, baseline_session_date: payload.baseline_session_date },
      { key: "post_market", label: "盘后报价", price: payload.after_hours_price, evidence: payload.post_market_evidence, target_trading_day: payload.target_trading_day, baseline_session_date: payload.baseline_session_date },
    ];
    summary.innerHTML = entries.map(cardData).join("");
  }

  function renderExplanation(value, fallbackMessage = null) {
    const target = node("market-session-comparison-explanation");
    if (!target) return;
    if (!value) {
      target.innerHTML = `<p class="workbench-explanation-summary">${escape(fallbackMessage || "读取后会说明两段变化、来源、时区和证据缺口。")}</p>`;
      return;
    }
    const payload = objectPayload(value);
    const codes = Array.isArray(payload.reason_codes) ? payload.reason_codes.filter(Boolean) : [];
    const fieldExplanations = objectPayload(payload.field_explanations);
    const baseline = payload.baseline_evidence;
    const close = payload.regular_close_evidence;
    const post = payload.post_market_evidence;
    const source = sourceText(payload.source);
    const status = statusText(payload.status, payload.data_quality);
    const reasons = codes.length
      ? `<ul class="workbench-explanation-list"><li>缺口原因：${codes.map((code) => `${escape(reasonText(code))} <code>${escape(code)}</code>`).join("；")}</li></ul>`
      : "";
    const fieldLines = Object.entries(fieldExplanations)
      .filter(([, explanation]) => explanation)
      .map(([field, explanation]) => `<li><strong>${escape(field)}</strong>：${escape(explanation)}</li>`)
      .join("");
    const staleNote = payload.status === "valid" && payload.data_quality === "verified"
      ? "两段变化可直接阅读；仍请以证据时间判断是否已经过时。"
      : "当前只能作部分或不可用的历史对照，不能把缺失证据当成零，也不能据此证明实时行情。";
    target.innerHTML = `<p class="workbench-explanation-summary">${escape(status)} · ${escape(staleNote)}</p>
      <dl class="workbench-facts market-session-comparison-facts">
        <div><dt>盘前 → 收盘</dt><dd>${escape(formatPercent(payload.pre_to_regular_close_pct))}</dd></div>
        <div><dt>收盘 → 盘后</dt><dd>${escape(formatPercent(payload.regular_close_to_after_hours_pct))}</dd></div>
        <div><dt>证据来源</dt><dd>${escape(source)}</dd></div>
        <div><dt>目标交易日（美东）</dt><dd>${escape(formatTradingDate(payload.target_trading_day || payload.baseline_session_date))}</dd></div>
        <div><dt>盘前基准记录</dt><dd>${escape(payload.pre_open_run_id || "未关联")}</dd></div>
        <div><dt>证据截至</dt><dd>${escape(payload.evidence_as_of ? `中国 ${formatDate(payload.evidence_as_of, "Asia/Shanghai")} · 美东 ${formatDate(payload.evidence_as_of, "America/New_York")}` : "时间未知")}</dd></div>
      </dl>
      <p class="market-session-comparison-explanation-line">盘前基准：${escape(evidenceMeta(baseline, payload))}</p>
      <p class="market-session-comparison-explanation-line">常规收盘：${escape(evidenceMeta(close, payload))}</p>
      <p class="market-session-comparison-explanation-line">盘后报价：${escape(evidenceMeta(post, payload))}</p>
      ${payload.reason_detail ? `<p class="market-session-comparison-reason">${escape(payload.reason_detail)}</p>` : ""}
      ${reasons}
      ${fieldLines ? `<details class="market-session-field-explanations"><summary>查看字段含义</summary><ul class="workbench-explanation-list">${fieldLines}</ul></details>` : ""}`;
  }

  function renderStatus(value, message = null, tone = null) {
    const target = node("market-session-comparison-status");
    if (!target) return;
    if (message) {
      target.textContent = message;
      target.dataset.tone = tone || "warning";
      return;
    }
    const payload = objectPayload(value);
    target.textContent = statusText(payload.status, payload.data_quality);
    target.dataset.tone = statusTone(payload.status, payload.data_quality);
  }

  function renderRaw(value, errorText = null) {
    const target = node("market-session-comparison-raw");
    if (!target) return;
    if (errorText) {
      target.textContent = `技术详情：${errorText}`;
      return;
    }
    target.textContent = value ? JSON.stringify(value, null, 2) : "暂无原始证据。";
  }

  function renderEmpty(message) {
    renderCards(null);
    renderStatus(null, "缺少时段证据", "warning");
    renderExplanation(null, message);
    renderRaw(null);
  }

  function renderComparison(value) {
    renderCards(value);
    renderStatus(value);
    renderExplanation(value);
    renderRaw(value);
  }

  function renderError(message, { retain = true } = {}) {
    if (!retain) {
      comparison = null;
      renderCards(null);
      renderRaw(null, message || "Request failed.");
    }
    renderStatus(null, retain ? "读取失败，保留上次证据" : "暂时无法读取", "warning");
    const target = node("market-session-comparison-explanation");
    if (target) {
      if (retain && comparison) {
        renderExplanation(comparison);
        target.insertAdjacentHTML("afterbegin", `<p class="market-session-comparison-reason">本次读取失败，下面仍是同一账户、同一标的的上次证据：${escape(message || "时段对照读取失败。")}。</p>`);
      } else {
        target.innerHTML = `<p class="workbench-explanation-summary">暂时没有可用的时段对照。</p><p class="market-session-comparison-reason">${escape(message || "时段对照读取失败。")}</p>`;
      }
    }
    if (retain && comparison) renderRaw(comparison);
  }

  function validComparison(value, scope, symbol) {
    const payload = objectPayload(value);
    if (!payload.id || payload.external_account_id !== scope.accountId || payload.mode !== "paper" || payload.symbol !== symbol) {
      throw new Error("时段对照响应没有匹配当前模拟账户和标的。");
    }
    return payload;
  }

  function validSavedPage(value, scope, symbol) {
    const page = objectPayload(value);
    if (!Array.isArray(page.items) || typeof page.has_more !== "boolean" || !("next_cursor" in page)) {
      throw new Error("已保存时段对照响应没有匹配分页合同。");
    }
    if (page.next_cursor !== null && (typeof page.next_cursor !== "string" || !page.next_cursor.trim())) {
      throw new Error("已保存时段对照返回了无效的下一页游标。");
    }
    if (page.has_more && !page.next_cursor) {
      throw new Error("已保存时段对照标记有下一页但没有游标。");
    }
    const items = page.items.map((item) => {
      const payload = objectPayload(item);
      if (!payload.id || payload.external_account_id !== scope.accountId || payload.mode !== "paper" || payload.symbol !== symbol) {
        throw new Error("已保存时段对照包含不属于当前模拟账户或标的的记录。");
      }
      return payload;
    });
    return { items, nextCursor: page.next_cursor, hasMore: page.has_more };
  }

  async function loadSavedComparisons({ reset = false } = {}) {
    const symbol = readSymbol();
    const scope = selectedAccount();
    if (!scope.accountId || !symbol) {
      resetSavedComparisons(scope.accountId ? "请输入标的后读取历史记录" : "选择账户后读取历史记录");
      return;
    }
    const token = ++savedToken;
    const previousItems = savedComparisons;
    const previousCursor = savedNextCursor;
    const previousHasMore = savedHasMore;
    const cursor = reset ? null : savedNextCursor;
    if (reset) {
      savedNextCursor = null;
      savedHasMore = false;
    }
    setSavedBusy(true);
    try {
      const params = new URLSearchParams({
        external_account_id: scope.accountId,
        mode: "paper",
        symbol,
        limit: "25",
      });
      if (cursor) params.set("cursor", cursor);
      const result = await ui().loadScopedReads([{ key: "saved", url: `/market-session-comparisons?${params.toString()}` }], ui().getState?.() || {});
      if (!savedScopeIsCurrent(scope, symbol, token) || result.discarded) return;
      if (result.errors.saved) {
        throw new Error(result.errors.saved);
      }
      const page = validSavedPage(result.values.saved, scope, symbol);
      const values = reset ? page.items : [...savedComparisons, ...page.items];
      const seen = new Set();
      savedComparisons = values.filter((item) => {
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      });
      savedNextCursor = page.nextCursor;
      savedHasMore = page.hasMore;
      setSavedBusy(false);
      renderSavedComparisons();
    } catch (error) {
      if (!savedScopeIsCurrent(scope, symbol, token)) return;
      savedComparisons = previousItems;
      savedNextCursor = previousCursor;
      savedHasMore = previousHasMore;
      setSavedBusy(false);
      renderSavedComparisons(savedComparisons.length ? "历史读取失败，保留上次记录" : "历史记录暂时不可用");
      const loadMore = node("market-session-comparison-load-more");
      if (loadMore && !savedComparisons.length) loadMore.title = error?.message || "历史记录读取失败";
    } finally {
      // Only the request that owns the current token may release the loading
      // state; a late page must never re-enable a newer request's button.
      if (token === savedToken && savedLoading) setSavedBusy(false);
    }
  }

  async function loadSavedDetail(comparisonId) {
    const selectedId = String(comparisonId || "");
    if (!selectedId) return;
    const symbol = readSymbol();
    const scope = selectedAccount();
    const item = savedComparisons.find((candidate) => candidate.id === selectedId);
    if (!scope.accountId || !symbol || !item) return;
    const token = ++requestToken;
    currentSymbol = symbol;
    lastScope = scope;
    setBusy("read", true);
    try {
      const params = new URLSearchParams({ external_account_id: scope.accountId, mode: "paper" });
      const result = await ui().loadScopedReads([{
        key: "detail",
        url: `/market-session-comparisons/${encodeURIComponent(selectedId)}?${params.toString()}`,
      }], ui().getState?.() || {});
      if (!scopeIsCurrent(scope, symbol, token) || result.discarded) return;
      if (result.errors.detail) throw new Error(result.errors.detail);
      renderComparison(validComparison(result.values.detail, scope, symbol));
    } catch (error) {
      if (!scopeIsCurrent(scope, symbol, token)) return;
      renderError(`历史对照详情读取失败：${error?.message || "Request failed."}`, { retain: Boolean(comparison) });
    } finally {
      if (scopeIsCurrent(scope, symbol, token)) setBusy("read", false);
    }
  }

  async function readLatest() {
    const symbol = readSymbol();
    const scope = selectedAccount();
    if (!scope.accountId) {
      renderEmpty("选择模拟账户后，才能读取已保存的盘前、收盘和盘后对照。");
      return;
    }
    if (!symbol) {
      renderEmpty("请输入标的，例如 QQQ.US；没有标的就无法定位时段证据。");
      return;
    }
    const token = ++requestToken;
    currentSymbol = symbol;
    lastScope = scope;
    setBusy("read", true);
    try {
      const params = new URLSearchParams({
        symbol,
        external_account_id: scope.accountId,
        mode: "paper",
      });
      const result = await ui().loadScopedReads([{ key: "latest", url: `/market-session-comparisons/latest?${params.toString()}` }], ui().getState?.() || {});
      if (!scopeIsCurrent(scope, symbol, token) || result.discarded) return;
      if (result.errors.latest) {
        const retain = Boolean(comparison && currentSymbol === symbol && lastScope?.accountId === scope.accountId);
        if (retain) {
          renderError(result.errors.latest, { retain: true });
        } else {
          renderEmpty(result.errors.latest.includes("404") ? "暂无已保存的时段对照（BLOCKED_DATA）。点击“采集并记录时段报价”后，才会创建新的只读记录。" : "时段对照暂时无法读取；没有用 0 填补缺失证据。");
          renderRaw(null, result.errors.latest);
        }
        return;
      }
      renderComparison(validComparison(result.values.latest, scope, symbol));
    } catch (error) {
      if (!scopeIsCurrent(scope, symbol, token)) return;
      renderError(error?.message || "时段对照读取失败。", { retain: Boolean(comparison && currentSymbol === symbol && lastScope?.accountId === scope.accountId) });
    } finally {
      if (scopeIsCurrent(scope, symbol, token)) setBusy("read", false);
    }
  }

  function newCaptureKey() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return `market-session-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }

  function captureFingerprint(scope, symbol, preOpenRunId) {
    return [scope.accountId, "paper", symbol, preOpenRunId || ""].join("|");
  }

  function captureKeyFor(scope, symbol, preOpenRunId) {
    const fingerprint = captureFingerprint(scope, symbol, preOpenRunId);
    if (!captureKeyState || captureKeyState.fingerprint !== fingerprint) {
      captureKeyState = { fingerprint, key: newCaptureKey() };
    }
    return captureKeyState.key;
  }

  function clearCaptureKey() {
    captureKeyState = null;
  }

  function definitiveCaptureError(error, message) {
    const status = Number(error?.status);
    if (Number.isInteger(status) && status >= 400 && status < 500) return true;
    return /Request failed:\s*(400|401|403|404|409|422)\b/.test(String(message || ""));
  }

  async function capture() {
    const symbol = readSymbol();
    const scope = selectedAccount();
    if (!scope.accountId) {
      renderError("请先选择模拟账户。", { retain: false });
      return;
    }
    if (!symbol) {
      renderError("请输入标的，例如 QQQ.US。", { retain: false });
      return;
    }
    const token = ++requestToken;
    currentSymbol = symbol;
    lastScope = scope;
    const state = ui().getState?.() || {};
    const request = {
      external_account_id: scope.accountId,
      mode: "paper",
      symbol,
      capture_key: captureKeyFor(scope, symbol, null),
    };
    setBusy("capture", true);
    renderStatus(null, isDemo() ? "正在读取演示行情并记录…" : "正在读取行情并记录…", "warning");
    try {
      const result = await ui().loadScopedReads([{
        key: "capture",
        url: "/market-session-comparisons",
        options: { method: "POST", body: JSON.stringify(request), timeoutMs: 70000 },
      }], state);
      if (!scopeIsCurrent(scope, symbol, token) || result.discarded) return;
      if (result.errors.capture) {
        if (definitiveCaptureError(result.errorObjects?.capture, result.errors.capture)) clearCaptureKey();
        renderError(result.errors.capture, { retain: Boolean(comparison && currentSymbol === symbol && lastScope?.accountId === scope.accountId) });
        return;
      }
      const captureResult = objectPayload(result.values.capture);
      const capturedComparison = validComparison(captureResult.comparison, scope, symbol);
      clearCaptureKey();
      renderComparison(capturedComparison);
      void loadSavedComparisons({ reset: true });
    } catch (error) {
      if (!scopeIsCurrent(scope, symbol, token)) return;
      clearCaptureKey();
      renderError(error?.message || "时段报价采集失败。", { retain: Boolean(comparison && currentSymbol === symbol && lastScope?.accountId === scope.accountId) });
    } finally {
      if (scopeIsCurrent(scope, symbol, token)) setBusy("capture", false);
    }
  }

  function bind() {
    if (initialized) return;
    initialized = true;
    const input = node("market-session-comparison-symbol");
    const handleSymbolChange = () => {
      currentSymbol = readSymbol();
      requestToken += 1;
      setBusy("read", false);
      clearCaptureKey();
      comparison = null;
      lastScope = null;
      resetSavedComparisons("标的已改变，点击读取最新对照后加载历史记录");
      renderEmpty("标的已改变。点击“读取最新对照”查看该标的的已保存证据。");
    };
    input?.addEventListener("input", handleSymbolChange);
    input?.addEventListener("change", handleSymbolChange);
    node("market-session-comparison-refresh")?.addEventListener("click", () => {
      void readLatest();
      void loadSavedComparisons({ reset: true });
    });
    node("market-session-comparison-capture")?.addEventListener("click", () => { void capture(); });
    node("market-session-comparison-saved-select")?.addEventListener("change", (event) => {
      void loadSavedDetail(event.target?.value || "");
    });
    node("market-session-comparison-load-more")?.addEventListener("click", () => {
      void loadSavedComparisons({ reset: false });
    });
    ui().subscribe((event) => {
      if (event.type === "account-state") {
        const accountId = event.state?.selectedAccountId || "";
        if (lastScope?.accountId && lastScope.accountId !== accountId) {
          requestToken += 1;
          setBusy("read", false);
          clearCaptureKey();
          comparison = null;
          lastScope = null;
          resetSavedComparisons("账户已切换，请读取当前模拟账户的历史记录");
          renderEmpty("账户已切换。旧账户的时段证据已卸载，请重新读取当前模拟账户。");
        }
        if (ui().getWorkspace?.() === "macro") {
          void readLatest();
          void loadSavedComparisons({ reset: true });
        }
      }
      if (event.type === "workspace" && event.workspace === "macro") {
        void readLatest();
        void loadSavedComparisons({ reset: true });
      }
    });
    resetSavedComparisons("选择账户后读取已保存的历史记录");
    renderEmpty("选择账户后读取已保存的时段对照；采集按钮只记录行情证据，不会下单。");
  }

  window.StocksToolMarketSessionComparison = { init: bind, readLatest, capture };
  document.addEventListener("DOMContentLoaded", bind, { once: true });
})();

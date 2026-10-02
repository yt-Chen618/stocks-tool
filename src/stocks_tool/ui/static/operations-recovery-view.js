(function () {
  "use strict";

  let root = null;
  let displayState = { kind: "empty", error: null };
  let languageObserver = null;

  const REASON_COPY = Object.freeze({
    order_outcome_unknown: {
      en: "Order outcome is unknown",
      zh: "订单结果未知",
      nextEn: "Review the parent and child reconciliation evidence before any broker mutation.",
      nextZh: "请先复核父子意图的核对证据，再考虑任何券商写操作。",
    },
    order_reconciliation_pending: {
      en: "Order reconciliation is still pending",
      zh: "订单核对仍在等待",
      nextEn: "Let the existing reconciliation process continue; do not retry a broker mutation.",
      nextZh: "等待现有核对流程继续，不要重试券商写操作。",
    },
    reconciliation_checks_pending: {
      en: "Reconciliation checks are incomplete",
      zh: "核对次数还不够",
      nextEn: "Wait for the remaining complete zero-match checks; do not retry a broker mutation.",
      nextZh: "等待剩余的完整零匹配核对，不要重试券商写操作。",
    },
    reconciliation_coverage_incomplete: {
      en: "Broker history is incomplete",
      zh: "券商历史覆盖不完整",
      nextEn: "Wait for a history window that covers the intent creation time.",
      nextZh: "等待覆盖意图创建时间的历史窗口。",
    },
    reconciliation_timestamps_incomplete: {
      en: "Reconciliation timestamps are incomplete",
      zh: "核对时间戳不完整",
      nextEn: "Wait for complete reconciliation timestamps before reviewing the evidence.",
      nextZh: "等待完整核对时间戳后再复核证据。",
    },
    reconciliation_wait_window: {
      en: "The reconciliation window is still too short",
      zh: "核对时间窗口还不够",
      nextEn: "Wait until the complete evidence chain spans 60 seconds.",
      nextZh: "等待完整证据链覆盖 60 秒。",
    },
    external_order_id_present: {
      en: "A broker order is already recorded",
      zh: "已有券商订单记录",
      nextEn: "Inspect and reconcile the recorded broker order instead of treating it as no order.",
      nextZh: "请检查并核对已有券商订单，不要将其当作无订单。",
    },
    parent_action_persisted: {
      en: "The parent action needs review",
      zh: "父动作还需要复核",
      nextEn: "Review the persisted parent action and its child intents together.",
      nextZh: "请将已持久化的父动作与子意图一起复核。",
    },
    parent_intent_missing: {
      en: "The parent action cannot be read",
      zh: "父动作暂时不可读",
      nextEn: "Keep recovery blocked until the parent trade action is readable.",
      nextZh: "在父交易动作可读前保持恢复阻塞。",
    },
    intent_state_not_resolvable: {
      en: "The intent state needs review",
      zh: "意图状态需要复核",
      nextEn: "Review the existing intent lifecycle before taking any local action.",
      nextZh: "请先复核现有意图生命周期，再进行本地操作。",
    },
    paper_resolution_not_allowed: {
      en: "Paper no-order review is unavailable",
      zh: "该意图不能按纸账户无订单处理",
      nextEn: "Keep the intent blocked and review the broker outcome manually.",
      nextZh: "保持意图阻塞，并人工复核券商结果。",
    },
    reconciliation_evidence_ready: {
      en: "Evidence is complete for review",
      zh: "证据链已完整，可供复核",
      nextEn: "Review the evidence before any local paper resolution; this view never resolves it.",
      nextZh: "请先复核证据；此视图不会执行本地纸账户解锁。",
    },
    sdk_timeout_quarantine: {
      en: "SDK is still waiting after a timeout",
      zh: "SDK 超时调用仍在等待",
      nextEn: "Wait for the timed-out SDK call to finish and keep broker writes paused.",
      nextZh: "等待超时 SDK 调用结束，并保持券商写操作暂停。",
    },
    sdk_runtime_unavailable: {
      en: "SDK runtime status is unavailable",
      zh: "SDK 运行状态暂时不可读",
      nextEn: "Keep recovery blocked until local SDK runtime state can be read.",
      nextZh: "在本地 SDK 运行状态可读前保持恢复阻塞。",
    },
  });

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function formatDateTime(value) {
    if (!value) {
      return "--";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return escapeHtml(value);
    }
    return escapeHtml(
      new Intl.DateTimeFormat(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(date),
    );
  }

  function languageIsZh() {
    return String(document.documentElement?.lang || "").toLowerCase().startsWith("zh");
  }

  function label(en, zh) {
    if (!languageIsZh()) {
      return en;
    }
    const dictionary = window.StocksToolI18n?.TRANSLATIONS?.zh || {};
    return dictionary[en] || zh;
  }

  function reasonCopy(code) {
    const normalized = String(code || "").trim();
    const copy = REASON_COPY[normalized];
    if (copy) {
      return {
        title: label(copy.en, copy.zh),
        next: label(copy.nextEn, copy.nextZh),
      };
    }
    return {
      title: languageIsZh()
        ? "恢复状态需要复核"
        : "Recovery status needs review",
      next: languageIsZh()
        ? "请查看下方证据并等待现有恢复流程继续。"
        : "Review the evidence below and let the existing recovery process continue.",
    };
  }

  function reasonBadge(code) {
    const normalized = String(code || "").trim();
    if (!normalized) {
      return "";
    }
    const title = languageIsZh()
      ? `原因代码：${normalized}`
      : `Canonical reason code: ${normalized}`;
    return `<span class="operations-recovery-reason-code" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">ⓘ</span>`;
  }

  function reasonBlock(code, fallbackNext = "") {
    const copy = reasonCopy(code);
    const next = copy.next || fallbackNext;
    return `<strong>${escapeHtml(copy.title)}</strong>${reasonBadge(code)} <span class="operations-recovery-next-step">${escapeHtml(next)}</span>`;
  }

  function reasonTitleBlock(code) {
    const copy = reasonCopy(code);
    return `<strong>${escapeHtml(copy.title)}</strong>${reasonBadge(code)}`;
  }

  function overallGuidance(snapshot, sdk) {
    const parts = [];
    const primaryCode = String(snapshot.primary_blocker || "").trim();
    if (primaryCode) {
      parts.push(reasonCopy(primaryCode).next);
    }
    const sdkCode = sdk.available === false
      ? "sdk_runtime_unavailable"
      : Number(sdk.pending_count || 0) > 0
        ? "sdk_timeout_quarantine"
        : "";
    if (sdkCode && sdkCode !== primaryCode) {
      parts.push(reasonCopy(sdkCode).next);
    }
    if (!parts.length) {
      return label("No recovery action is required.", "当前无需恢复操作。");
    }
    return Array.from(new Set(parts)).join(" ");
  }

  function shortId(value) {
    const text = String(value || "");
    return text.length > 18 ? `${text.slice(0, 8)}…${text.slice(-6)}` : text || "--";
  }

  function statusClass(value) {
    if (value === "clear" || value === "ready" || value === "pass") {
      return "success";
    }
    if (value === "blocked" || value === "unknown" || value === "fail") {
      return "error";
    }
    return "warning";
  }

  function renderEmpty(message) {
    if (!root) {
      return;
    }
    displayState = { kind: "empty", error: null };
    root.innerHTML = `
      <div class="operations-recovery-header">
        <div><span class="section-kicker">${label("Operations", "运营")}</span><h2 id="operations-recovery-title">${label("Recovery status", "恢复状态")}</h2></div>
      </div>
      <p class="operations-recovery-empty">${escapeHtml(message || label("Select a broker account to inspect recovery evidence.", "选择券商账户后查看恢复证据。"))}</p>
    `;
  }

  function renderSnapshot(snapshot) {
    if (!root) {
      return snapshot;
    }
    if (!snapshot) {
      renderEmpty();
      return snapshot;
    }

    displayState = { kind: "snapshot", snapshot, error: null };

    const status = String(snapshot.status || "unknown");
    const sdk = snapshot.sdk_quarantine || {};
    const intents = Array.isArray(snapshot.intents) ? snapshot.intents : [];
    const parents = Array.isArray(snapshot.parents) ? snapshot.parents : [];
    const blocked = snapshot.recovery_blocked ?? status === "blocked";
    const sdkUnavailable = sdk.available === false;
    const sdkPending = Number(sdk.pending_count || 0) > 0;
    const sdkTone = sdkUnavailable || sdkPending ? "error" : "success";

    const parentRows = parents.length
      ? parents.map((parent) => `
          <li class="operations-recovery-parent">
            <div>
              <strong>${escapeHtml(parent.action || label("Parent trade action", "父交易动作"))}</strong>
              <span class="operations-recovery-id">${escapeHtml(shortId(parent.id))}</span>
            </div>
            <span class="pill ${statusClass(parent.reason_code === "reconciliation_evidence_ready" ? "pass" : "warn")}">${escapeHtml(parent.unresolved_child_count)} ${label("child shown", "个子意图已显示")}</span>
            <p class="operations-recovery-reason">${reasonBlock(parent.reason_code, parent.next_action)}${parent.children_truncated ? ` ${label("More children are outside this view.", "还有子意图未在当前视图显示。")}` : ""}</p>
          </li>
        `).join("")
      : `<li class="operations-recovery-muted">${label("No parent trade action is waiting for recovery.", "没有等待恢复的父交易动作。")}</li>`;

    const intentRows = intents.length
      ? intents.map((intent) => {
          const attempts = Number(intent.reconciliation_attempts || 0);
          const span = intent.check_span_seconds == null ? "--" : `${intent.check_span_seconds}s`;
          const coverage = intent.coverage_covers_intent
            ? label("Covers creation time", "覆盖创建时间")
            : label("Does not cover creation time", "未覆盖创建时间");
          const coverageClass = intent.coverage_covers_intent ? "success" : "error";
          const checks = intent.checks_satisfied
            ? label("Evidence checks ready", "证据检查已满足")
            : label(`${attempts}/3 checks; ${span} window`, `${attempts}/3 次检查；窗口 ${span}`);
          return `
            <article class="operations-recovery-intent">
              <div class="operations-recovery-intent-head">
                <div>
                  <strong>${escapeHtml(intent.action || label("Order intent", "订单意图"))}</strong>
                  <span class="operations-recovery-id">${escapeHtml(shortId(intent.id))}</span>
                </div>
                <span class="pill ${statusClass(intent.state)}">${escapeHtml(intent.state || "unknown")}</span>
              </div>
              <dl class="operations-recovery-facts">
                <div><dt>${label("Parent", "父意图")}</dt><dd>${escapeHtml(intent.parent_action || shortId(intent.trade_action_intent_id))}</dd></div>
                <div><dt>${label("Leg", "腿")}</dt><dd>${escapeHtml(intent.leg || intent.operation || "--")}</dd></div>
                <div><dt>${label("Checks", "检查")}</dt><dd>${escapeHtml(checks)}</dd></div>
                <div><dt>${label("Coverage", "覆盖")}</dt><dd class="${coverageClass}">${escapeHtml(coverage)}</dd></div>
                <div><dt>${label("History window", "历史窗口")}</dt><dd>${formatDateTime(intent.coverage_start_at)} → ${formatDateTime(intent.coverage_end_at)}</dd></div>
                <div><dt>${label("Created", "创建时间")}</dt><dd>${formatDateTime(intent.created_at)}</dd></div>
              </dl>
              <p class="operations-recovery-reason">${reasonBlock(intent.reason_code, intent.next_action)}</p>
            </article>
          `;
        }).join("")
      : `<p class="operations-recovery-muted">${label("No unresolved order intents.", "没有未解决的订单意图。")}</p>`;

    let sdkDetail = label("No timed-out SDK call is pending.", "没有等待中的 SDK 超时调用。");
    if (sdkUnavailable) {
      sdkDetail = label("Local SDK quarantine state is unavailable. Broker writes stay paused.", "本地 SDK 隔离状态不可读，券商写操作保持暂停。");
    } else if (sdkPending) {
      sdkDetail = label(
        `${sdk.pending_count} SDK call(s) still running after timeout. Oldest: ${sdk.oldest_duration_seconds ?? "--"}s.`,
        `${sdk.pending_count} 个 SDK 调用超时后仍在运行，最早已持续 ${sdk.oldest_duration_seconds ?? "--"} 秒。`,
      );
    }

    const sdkCode = sdkUnavailable ? "sdk_runtime_unavailable" : sdkPending ? "sdk_timeout_quarantine" : "";
    const sdkNext = sdkCode
      ? `${reasonBlock(sdkCode, sdk.next_action)}`
      : escapeHtml(label("No action is required.", "无需操作。"));

    root.innerHTML = `
      <div class="operations-recovery-header">
        <div><span class="section-kicker">${label("Operations", "运营")}</span><h2 id="operations-recovery-title">${label("Recovery status", "恢复状态")}</h2></div>
        <span class="pill ${statusClass(status)}">${blocked ? label("Blocked", "已阻塞") : label("Clear", "无阻塞")}</span>
      </div>
      <p class="operations-recovery-guidance">${snapshot.primary_blocker ? reasonTitleBlock(snapshot.primary_blocker) : `<strong>${escapeHtml(label("No blocker", "无阻塞原因"))}</strong>`} <span class="operations-recovery-next-step">${escapeHtml(overallGuidance(snapshot, sdk))}</span></p>
      <div class="operations-recovery-summary">
        <div><span>${label("Unresolved intents", "未解决意图")}</span><strong>${escapeHtml(snapshot.unresolved_count ?? 0)}</strong><small>${label("shown", "已显示")} ${escapeHtml(snapshot.displayed_unresolved_count ?? intents.length)}${snapshot.truncated ? " · …" : ""}</small></div>
        <div><span>${label("Unknown outcomes", "未知结果")}</span><strong>${escapeHtml(snapshot.unknown_count ?? 0)}</strong><small>${label("shown", "已显示")} ${escapeHtml(snapshot.displayed_unknown_count ?? 0)}</small></div>
        <div><span>${label("Parent actions", "父交易动作")}</span><strong>${escapeHtml(snapshot.unresolved_parent_count ?? parents.length)}</strong><small>${label("shown", "已显示")} ${escapeHtml(snapshot.displayed_parent_count ?? parents.length)}${snapshot.truncated ? " · …" : ""}</small></div>
      </div>
      <section class="operations-recovery-section">
        <div class="operations-recovery-section-head"><h3>${label("Parent actions", "父交易动作")}</h3><span>${label("Read only", "只读")}</span></div>
        <ul class="operations-recovery-parent-list">${parentRows}</ul>
      </section>
      <section class="operations-recovery-section">
        <div class="operations-recovery-section-head"><h3>${label("Child intent evidence", "子意图证据")}</h3><span>${label("Coverage and checks", "覆盖与检查")}</span></div>
        <div class="operations-recovery-intents">${intentRows}</div>
      </section>
      <section class="operations-recovery-section operations-recovery-sdk">
        <div class="operations-recovery-section-head"><h3>${label("SDK timeout quarantine", "SDK 超时隔离")}</h3><span class="pill ${sdkTone}">${sdkUnavailable ? label("Unavailable", "不可读") : sdkPending ? label("Pending", "等待中") : label("Clear", "无等待")}</span></div>
        <p>${escapeHtml(sdkDetail)}</p>
        <p class="operations-recovery-next">${sdkNext}</p>
      </section>
    `;
    return snapshot;
  }

  function render(snapshot) {
    return renderSnapshot(snapshot);
  }

  function renderError(error) {
    if (!root) {
      return;
    }
    displayState = { kind: "error", error };
    const detail = error?.message || label("Recovery status could not be loaded.", "恢复状态加载失败。");
    root.innerHTML = `
      <div class="operations-recovery-header">
        <div><span class="section-kicker">${label("Operations", "运营")}</span><h2>${label("Recovery status", "恢复状态")}</h2></div>
        <span class="pill error">${label("Unavailable", "不可用")}</span>
      </div>
      <p class="operations-recovery-empty">${escapeHtml(label("Recovery status could not be loaded. Check the account and refresh again.", "恢复状态暂时无法加载，请检查账户后刷新。"))}</p>
      <p class="operations-recovery-code-detail" title="${escapeHtml(detail)}">${escapeHtml(label("Details are available in the request log.", "详细原因已记录在请求日志中。"))}</p>
    `;
  }

  function renderLoading() {
    if (!root) {
      return;
    }
    displayState = { kind: "loading", error: null };
    root.innerHTML = `
      <div class="operations-recovery-header">
        <div><span class="section-kicker">${label("Operations", "运营")}</span><h2 id="operations-recovery-title">${label("Recovery status", "恢复状态")}</h2></div>
        <span class="pill warning">${label("Loading", "加载中")}</span>
      </div>
      <p class="operations-recovery-empty">${escapeHtml(label("Loading recovery evidence for the selected account.", "正在加载所选账户的恢复证据。"))}</p>
    `;
  }

  function watchLanguage() {
    if (languageObserver || !document.documentElement || typeof MutationObserver === "undefined") {
      return;
    }
    languageObserver = new MutationObserver(() => {
      if (displayState.kind === "snapshot" && displayState.snapshot) {
        renderSnapshot(displayState.snapshot);
      } else if (displayState.kind === "error") {
        renderError(displayState.error);
      } else if (displayState.kind === "loading") {
        renderLoading();
      } else if (root) {
        renderEmpty();
      }
    });
    languageObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["lang"],
    });
  }

  function init(options = {}) {
    if (typeof options.root === "string") {
      root = document.querySelector(options.root);
    } else if (typeof Element !== "undefined" && options.root instanceof Element) {
      root = options.root;
    } else {
      root = document.querySelector("[data-operations-recovery]");
    }
    if (root && !root.dataset.operationsRecoveryInitialized) {
      root.dataset.operationsRecoveryInitialized = "true";
      render(null);
    }
    watchLanguage();
    return window.StocksToolOperationsRecovery;
  }

  window.StocksToolOperationsRecovery = { init, render, renderError, renderLoading };
})();

(function () {
  function createAdvisorView({
    state,
    els,
    fetchJson,
    createOverlayStatus,
    setStatus,
    reloadAccountData,
    escapeHtml,
    formatters,
  }) {
    const formatter = formatters || window.StocksToolFormatters || {};
    const formatDateTime = formatter.formatDateTime || ((value) => String(value || "--"));
    const formatStrategyStatusLabel = formatter.formatStrategyStatusLabel || ((value) => String(value || "--"));
    const strategyStatusClass = formatter.strategyStatusClass || (() => "neutral");
    let requestGeneration = 0;

    function objectPayload(value) {
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    }

    function pickProposalValue(...values) {
      return values.find((value) => value !== null && value !== undefined && value !== "");
    }

    function displayValue(value) {
      const selected = pickProposalValue(value);
      return selected === undefined ? "--" : String(selected);
    }

    function formatActivityCount(value) {
      const number = Number(value);
      return Number.isFinite(number) ? String(number) : "0";
    }

    function overlayStatusTone(kind) {
      if (kind === "live") return "success";
      if (["loading", "timed_out", "stale", "partial"].includes(kind)) return "warning";
      if (["circuit_open", "error"].includes(kind)) return "error";
      return "neutral";
    }

    function overlayStatusLabel(kind) {
      if (kind === "live") return "Live";
      if (kind === "loading") return "Refreshing";
      if (kind === "timed_out") return "Timed Out";
      if (kind === "circuit_open") return "Circuit Open";
      if (kind === "stale") return "Stale";
      if (kind === "partial") return "Partial";
      if (kind === "error") return "Unavailable";
      return "Idle";
    }

    function renderOverlayReason(status) {
      if (!status?.reason || status.kind === "idle" || status.kind === "loading" || status.kind === "live") {
        return "";
      }
      return `<p class="overlay-reason">Latest refresh: ${escapeHtml(status.reason)}</p>`;
    }

    function renderStrategyProposalDetail([label, value, detail]) {
      return `
        <div>
          <dt>${escapeHtml(label)}</dt>
          <dd><strong>${escapeHtml(value)}</strong><span>${escapeHtml(detail || "")}</span></dd>
        </div>
      `;
    }

    function renderAdvisorContextSummary(context) {
      if (!context) return "";
      const activity = context.covered_call_activity || {};
      const summary = objectPayload(activity.summary);
      const hardRules = Array.isArray(context.hard_rules) ? context.hard_rules : [];
      const playbooks = Array.isArray(context.playbooks) ? context.playbooks : [];
      const playbookIds = playbooks.map((playbook) => playbook.id).filter(Boolean).slice(0, 3);
      const items = [
        ["Account", context.external_account_id || "--", context.controls?.execution_mode || "paper"],
        ["Active CC", formatActivityCount(summary.active_proposals), `${formatActivityCount(summary.total_proposals)} proposal(s)`],
        ["Open CC", formatActivityCount(summary.executed_positions), `${formatActivityCount(summary.pending_rolls)} pending roll(s)`],
        ["Rules", String(hardRules.length), hardRules[0]?.name || "advisor_context_is_read_only"],
        ["Playbooks", String(playbooks.length), playbookIds.join(", ") || "--"],
        ["Boundary", "Proposal / Review", "No broker orders"],
      ];
      return `<div class="proposal-detail-grid">${items.map(renderStrategyProposalDetail).join("")}</div>`;
    }

    function renderAdvisorUsage(rawResponse) {
      const raw = objectPayload(rawResponse);
      const usage = objectPayload(raw.usage);
      if (!Object.keys(usage).length) return "";
      const details = objectPayload(usage.prompt_tokens_details);
      const items = [
        ["Prompt", displayValue(usage.prompt_tokens), `Model ${raw.model || "--"}`],
        ["Completion", displayValue(usage.completion_tokens), `Reasoning ${displayValue(objectPayload(usage.completion_tokens_details).reasoning_tokens)}`],
        ["Cache Hit", displayValue(pickProposalValue(usage.prompt_cache_hit_tokens, details.cached_tokens)), "Reused prompt tokens"],
        ["Cache Miss", displayValue(usage.prompt_cache_miss_tokens), "New prompt tokens billed as input"],
      ];
      return `
        <article class="strategy-journal-entry advisor-usage">
          <div class="strategy-journal-head"><strong>Usage</strong><span>${escapeHtml(raw.response_id || raw.finish_reason || "--")}</span></div>
          <div class="proposal-detail-grid">${items.map(renderStrategyProposalDetail).join("")}</div>
        </article>
      `;
    }

    function renderAdvisorDraftList(title, items, renderItem) {
      if (!items.length) {
        return `<article class="strategy-journal-entry"><div class="strategy-journal-head"><strong>${escapeHtml(title)}</strong><span class="pill neutral">0</span></div><p>No ${title.toLowerCase()} generated.</p></article>`;
      }
      return `
        <article class="strategy-journal-entry">
          <div class="strategy-journal-head"><strong>${escapeHtml(title)}</strong><span class="pill neutral">${escapeHtml(String(items.length))}</span></div>
          <div class="advisor-draft-list">${items.slice(0, 4).map(renderItem).join("")}</div>
        </article>
      `;
    }

    function advisorRunStatusClass(status) {
      if (status === "recorded" || status === "succeeded") return "success";
      if (status === "failed") return "error";
      return "neutral";
    }

    function renderAdvisorRunItem(run) {
      const usage = objectPayload(run.token_usage);
      const tokenLine = [
        `${displayValue(usage.prompt_tokens ?? run.prompt_tokens)} prompt`,
        `${displayValue(usage.completion_tokens ?? run.completion_tokens)} completion`,
        `${displayValue(usage.cache_hit_tokens ?? run.cache_hit_tokens)} cache hit`,
        `${displayValue(usage.cache_miss_tokens ?? run.cache_miss_tokens)} cache miss`,
      ].join(" / ");
      const outputLine = `${displayValue(run.proposal_count)} proposal(s), ${displayValue(run.review_count)} review(s)`;
      const warnings = Array.isArray(run.warnings) ? run.warnings : [];
      const contextHash = run.context_hash ? `context ${String(run.context_hash).slice(0, 12)}` : "";
      const guardLine = [
        run.playbook_id ? `playbook ${run.playbook_id}` : "",
        run.recordable_status ? `record ${formatStrategyStatusLabel(run.recordable_status)}` : "",
        run.impact_summary || "",
      ].filter(Boolean).join(" / ");
      return `
        <div class="advisor-draft-item">
          <div class="strategy-journal-head"><strong>${escapeHtml(run.model || run.provider || "deepseek")}</strong><span class="pill ${advisorRunStatusClass(run.status)}">${escapeHtml(formatStrategyStatusLabel(run.status || "succeeded"))}</span></div>
          <p>${escapeHtml(run.summary || [tokenLine, outputLine].filter(Boolean).join(" | "))}</p>
          <span>${escapeHtml([run.context_format, contextHash, formatDateTime(run.completed_at || run.created_at), run.response_id].filter(Boolean).join(" / "))}</span>
          ${guardLine ? `<span>${escapeHtml(guardLine)}</span>` : ""}
          ${warnings.length ? `<span>${escapeHtml(warnings[0])}</span>` : ""}
          ${run.error_message ? `<span>${escapeHtml(run.error_message)}</span>` : ""}
        </div>
      `;
    }

    function renderAdvisorRunHistory(runs) {
      if (!runs.length) {
        return `<article class="strategy-journal-entry"><div class="strategy-journal-head"><strong>Advisor Run History</strong><span class="pill neutral">0</span></div><p>No DeepSeek advisor runs recorded yet.</p></article>`;
      }
      return `<article class="strategy-journal-entry"><div class="strategy-journal-head"><strong>Advisor Run History</strong><span class="pill neutral">${escapeHtml(String(runs.length))}</span></div><div class="advisor-draft-list">${runs.slice(0, 5).map(renderAdvisorRunItem).join("")}</div></article>`;
    }

    function renderAdvisorProposalDraft(proposal) {
      const checks = Array.isArray(proposal.checks) ? proposal.checks : [];
      return `
        <div class="advisor-draft-item">
          <div class="strategy-journal-head"><strong>${escapeHtml(proposal.title || "Advisor proposal")}</strong><span class="pill warning">${escapeHtml(formatStrategyStatusLabel(proposal.proposed_action || "proposal"))}</span></div>
          <p>${escapeHtml(proposal.rationale || proposal.thesis || "No rationale supplied.")}</p>
          <span>${escapeHtml([proposal.strategy_id, proposal.symbol, checks.slice(0, 2).join(", ")].filter(Boolean).join(" / "))}</span>
        </div>
      `;
    }

    function renderAdvisorReviewDraft(review) {
      return `
        <div class="advisor-draft-item">
          <div class="strategy-journal-head"><strong>${escapeHtml(review.review_type || "advisor")}</strong><span class="pill ${strategyStatusClass(review.status)}">${escapeHtml(formatStrategyStatusLabel(review.status || "observed"))}</span></div>
          <p>${escapeHtml(review.recommendation || review.summary || "No recommendation supplied.")}</p>
          <span>${escapeHtml([review.strategy_id, formatDateTime(review.reviewed_at)].filter(Boolean).join(" / "))}</span>
        </div>
      `;
    }

    function updateAdvisorButtons() {
      const busy = state.advisorStatus?.kind === "loading";
      const payload = objectPayload(state.advisorDraft?.response_payload);
      const proposalCount = Array.isArray(payload.proposals) ? payload.proposals.length : 0;
      const reviewCount = Array.isArray(payload.reviews) ? payload.reviews.length : 0;
      if (els.loadAdvisorContext) els.loadAdvisorContext.disabled = busy || !state.selectedAccountId;
      if (els.runDeepSeekAdvisor) els.runDeepSeekAdvisor.disabled = busy || !state.selectedAccountId;
      if (els.recordAdvisorResponse) els.recordAdvisorResponse.disabled = busy || proposalCount + reviewCount === 0;
    }

    function renderAdvisorPanel() {
      if (!els.advisorOutputCard) return;
      updateAdvisorButtons();
      const overlay = state.advisorStatus || createOverlayStatus("idle", "Advisor context is available on demand.");
      const context = state.advisorContext;
      const result = state.advisorDraft || null;
      const payload = objectPayload(result?.response_payload);
      const proposals = Array.isArray(payload.proposals) ? payload.proposals : [];
      const reviews = Array.isArray(payload.reviews) ? payload.reviews : [];
      const advisorRuns = Array.isArray(state.advisorRuns) ? state.advisorRuns : [];
      if (!context && !result && !advisorRuns.length) {
        els.advisorOutputCard.className = "strategy-note-body empty";
        els.advisorOutputCard.innerHTML = `<div class="overlay-status-row"><div class="overlay-status-copy"><strong>DeepSeek Advisor</strong><span>${escapeHtml(overlay.detail)}</span></div><span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span></div>${renderOverlayReason(overlay)}`;
        return;
      }
      els.advisorOutputCard.className = "strategy-note-body";
      els.advisorOutputCard.innerHTML = `
        <div class="overlay-status-row"><div class="overlay-status-copy"><strong>DeepSeek Advisor</strong><span>${escapeHtml(overlay.detail || "Advisor output ready.")}</span></div><span class="pill ${overlayStatusTone(overlay.kind)}">${escapeHtml(overlayStatusLabel(overlay.kind))}</span></div>
        ${renderOverlayReason(overlay)}
        ${renderAdvisorContextSummary(context)}
        ${renderAdvisorUsage(payload.raw_response)}
        ${renderAdvisorDraftList("Proposals", proposals, renderAdvisorProposalDraft)}
        ${renderAdvisorDraftList("Reviews", reviews, renderAdvisorReviewDraft)}
        ${renderAdvisorRunHistory(advisorRuns)}
      `;
    }

    function resetAdvisorState(detail = "Advisor context is available on demand. DeepSeek dry-run sends selected account context outside the local app.") {
      requestGeneration += 1;
      state.advisorContext = null;
      state.advisorDraft = null;
      state.advisorStatus = createOverlayStatus("idle", detail);
      renderAdvisorPanel();
    }

    async function loadAdvisorContext() {
      const accountId = state.selectedAccountId;
      if (!accountId) {
        setStatus("Select a broker account before loading advisor context.", "warning");
        resetAdvisorState("Select a broker account before loading advisor context.");
        return;
      }
      const generation = ++requestGeneration;
      state.advisorStatus = createOverlayStatus("loading", `Loading advisor context for ${accountId}...`);
      renderAdvisorPanel();
      try {
        const context = await fetchJson(`/strategies/advisor-context?external_account_id=${encodeURIComponent(accountId)}&limit=10`);
        if (generation !== requestGeneration || accountId !== state.selectedAccountId) return { discarded: true };
        state.advisorContext = context;
        state.advisorDraft = null;
        const summary = objectPayload(context.covered_call_activity?.summary);
        state.advisorStatus = createOverlayStatus("live", `Advisor context loaded for ${accountId}.`, `${formatActivityCount(summary.active_proposals)} active covered-call proposal(s), ${formatActivityCount(summary.executed_positions)} open covered-call position(s).`);
        renderAdvisorPanel();
        setStatus(`Advisor context loaded for ${accountId}.`, "success");
        return { discarded: false, context };
      } catch (error) {
        if (generation !== requestGeneration || accountId !== state.selectedAccountId) return { discarded: true };
        console.error(error);
        state.advisorStatus = createOverlayStatus("error", error.message || "Advisor context load failed.");
        renderAdvisorPanel();
        setStatus(error.message || "Advisor context load failed.", "error");
        return { discarded: false, error };
      }
    }

    async function runDeepSeekAdvisorDryRun() {
      const accountId = state.selectedAccountId;
      if (!accountId) {
        setStatus("Select a broker account before running DeepSeek advisor.", "warning");
        return;
      }
      const generation = ++requestGeneration;
      state.advisorStatus = createOverlayStatus("loading", `Running DeepSeek advisor dry-run for ${accountId}...`, "This sends the selected account advisor context to DeepSeek.");
      renderAdvisorPanel();
      try {
        const result = await fetchJson("/strategies/advisor/deepseek/dry-run", {
          method: "POST",
          body: JSON.stringify({ external_account_id: accountId, context_limit: 10 }),
          timeoutMs: 180000,
        });
        if (generation !== requestGeneration || accountId !== state.selectedAccountId) return { discarded: true };
        state.advisorContext = result.context || null;
        state.advisorDraft = result;
        if (result.advisor_run) upsertAdvisorRun(result.advisor_run);
        const payload = objectPayload(result.response_payload);
        const proposalCount = Array.isArray(payload.proposals) ? payload.proposals.length : 0;
        const reviewCount = Array.isArray(payload.reviews) ? payload.reviews.length : 0;
        state.advisorStatus = createOverlayStatus("live", `DeepSeek generated ${proposalCount} proposal(s) and ${reviewCount} review(s).`, "Dry-run only; use Record Output to write local ledger entries.");
        renderAdvisorPanel();
        setStatus(`DeepSeek dry-run generated ${proposalCount} proposal(s) and ${reviewCount} review(s).`, "success");
        return { discarded: false, result };
      } catch (error) {
        if (generation !== requestGeneration || accountId !== state.selectedAccountId) return { discarded: true };
        console.error(error);
        state.advisorStatus = createOverlayStatus("error", error.message || "DeepSeek advisor dry-run failed.");
        renderAdvisorPanel();
        setStatus(error.message || "DeepSeek advisor dry-run failed.", "error");
        return { discarded: false, error };
      }
    }

    async function recordAdvisorResponse() {
      const payload = objectPayload(state.advisorDraft?.response_payload);
      const proposalCount = Array.isArray(payload.proposals) ? payload.proposals.length : 0;
      const reviewCount = Array.isArray(payload.reviews) ? payload.reviews.length : 0;
      if (!proposalCount && !reviewCount) {
        setStatus("No DeepSeek advisor output is ready to record.", "warning");
        return;
      }
      const accountId = state.selectedAccountId;
      const generation = ++requestGeneration;
      state.advisorStatus = createOverlayStatus("loading", "Recording advisor output to the local strategy ledger...");
      renderAdvisorPanel();
      try {
        const result = await fetchJson("/strategies/advisor/responses", { method: "POST", body: JSON.stringify(payload) });
        if (generation !== requestGeneration || accountId !== state.selectedAccountId) return { discarded: true };
        if (result.advisor_run) upsertAdvisorRun(result.advisor_run);
        state.advisorDraft = null;
        state.advisorStatus = createOverlayStatus("live", `Recorded ${proposalCount} advisor proposal(s) and ${reviewCount} review(s).`, "Broker orders were not submitted.");
        if (typeof reloadAccountData === "function") await reloadAccountData();
        renderAdvisorPanel();
        setStatus(`Recorded advisor output: ${proposalCount} proposal(s), ${reviewCount} review(s).`, "success");
        return { discarded: false, result };
      } catch (error) {
        if (generation !== requestGeneration || accountId !== state.selectedAccountId) return { discarded: true };
        console.error(error);
        state.advisorStatus = createOverlayStatus("error", error.message || "Advisor output recording failed.");
        renderAdvisorPanel();
        setStatus(error.message || "Advisor output recording failed.", "error");
        return { discarded: false, error };
      }
    }

    function upsertAdvisorRun(run) {
      if (!run?.id) return;
      state.advisorRuns = [run, ...(state.advisorRuns || []).filter((candidate) => candidate.id !== run.id)].slice(0, 5);
    }

    function wireEvents() {
      els.loadAdvisorContext?.addEventListener("click", () => { void loadAdvisorContext(); });
      els.runDeepSeekAdvisor?.addEventListener("click", () => { void runDeepSeekAdvisorDryRun(); });
      els.recordAdvisorResponse?.addEventListener("click", () => { void recordAdvisorResponse(); });
    }

    return {
      wireEvents,
      renderAdvisorPanel,
      updateAdvisorButtons,
      resetAdvisorState,
      loadAdvisorContext,
      runDeepSeekAdvisorDryRun,
      recordAdvisorResponse,
      upsertAdvisorRun,
    };
  }

  window.StocksToolAdvisorView = { createAdvisorView };
})();

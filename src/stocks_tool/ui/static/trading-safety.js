(function () {
  "use strict";

  function hasPendingAction(pendingActionKeys, actionKey) {
    if (!actionKey || !pendingActionKeys) {
      return false;
    }
    if (typeof pendingActionKeys.has === "function") {
      return pendingActionKeys.has(actionKey);
    }
    return Array.isArray(pendingActionKeys) && pendingActionKeys.includes(actionKey);
  }

  function hasAnyPendingActionExcept(pendingActionKeys, actionKey) {
    if (!pendingActionKeys) return false;
    const values = typeof pendingActionKeys.values === "function"
      ? Array.from(pendingActionKeys.values())
      : Array.isArray(pendingActionKeys) ? pendingActionKeys : [];
    return values.some((value) => value !== actionKey);
  }

  function evaluateTradingSafety({
    accountId = "",
    selectedAccountId = "",
    mode = "paper",
    expectedContext = null,
    requestSignature,
    coreDataHealthy = false,
    recoveryStatusState = "idle",
    recoveryStatus = null,
    unresolvedTradingIntents = [],
    mobileBlocked = false,
    pendingActionKeys,
    actionKey = "",
    ignorePendingAction = false,
    businessDisabled = false,
  } = {}) {
    const normalizedAccountId = String(accountId || "").trim();
    const normalizedSelectedAccountId = String(selectedAccountId || "").trim();
    const normalizedMode = String(mode || "").trim().toLowerCase();
    const reasons = [];
    const recoveryReady = recoveryStatusState === "ready"
      && recoveryStatus?.external_account_id === normalizedSelectedAccountId
      && recoveryStatus?.mode === normalizedMode;
    const recoveryUnavailable = Boolean(normalizedSelectedAccountId) && !recoveryReady;

    if (!normalizedAccountId || normalizedAccountId !== normalizedSelectedAccountId) {
      reasons.push("account_context_changed");
    }
    if (normalizedMode !== "paper") {
      reasons.push("mode_not_paper");
    }
    if (expectedContext?.accountId && expectedContext.accountId !== normalizedSelectedAccountId) {
      reasons.push("account_context_changed");
    }
    if (expectedContext?.mode && expectedContext.mode !== normalizedMode) {
      reasons.push("mode_context_changed");
    }
    if (expectedContext && Object.prototype.hasOwnProperty.call(expectedContext, "requestSignature") && requestSignature !== expectedContext.requestSignature) {
      reasons.push("request_signature_changed");
    }
    if (!coreDataHealthy) {
      reasons.push("core_data_unhealthy");
    }
    if (recoveryUnavailable) {
      reasons.push("recovery_status_unavailable");
    } else if (recoveryStatus?.recovery_blocked === true) {
      reasons.push("recovery_blocked");
    }
    if (Array.isArray(unresolvedTradingIntents) && unresolvedTradingIntents.length > 0) {
      reasons.push("unresolved_trading_intent");
    }
    if (mobileBlocked) {
      reasons.push("mobile_viewport");
    }
    const pendingOtherAction = hasAnyPendingActionExcept(pendingActionKeys, actionKey);
    const pendingSelf = hasPendingAction(pendingActionKeys, actionKey);
    if ((ignorePendingAction && pendingOtherAction) || (!ignorePendingAction && (pendingSelf || pendingOtherAction))) {
      reasons.push("pending_action");
    }
    if (businessDisabled) {
      reasons.push("business_disabled");
    }

    return {
      blocked: reasons.length > 0,
      reasons: Array.from(new Set(reasons)),
      accountId: normalizedAccountId,
      selectedAccountId: normalizedSelectedAccountId,
      mode: normalizedMode,
      recoveryReady,
      recoveryUnavailable,
    };
  }

  window.StocksToolTradingSafety = { evaluateTradingSafety };
})();

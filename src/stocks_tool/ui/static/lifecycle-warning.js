(function attachLifecycleWarningHelpers(global) {
  const FAILED_CLOSE_ORDER_STATUSES = new Set(["canceled", "rejected"]);
  const WORKING_CLOSE_ORDER_STATUSES = new Set(["created", "submitted", "partially_filled"]);
  const BULL_PUT_CLOSE_ORDER_WARNING = "close_order_canceled_manual_action_needed";

  function normalizeStatus(value) {
    return String(value || "").trim().toLowerCase();
  }

  function isTruthLike(value) {
    return value === true || String(value || "").trim().toLowerCase() === "true";
  }

  function isMonitorableSpread(spread) {
    return ["open", "exit_pending_short", "exit_pending_long"].includes(spread?.status);
  }

  function hasWorkingReplacementCloseOrder(spread, orders) {
    return (Array.isArray(orders) ? orders : []).some((order) => {
      if (order.id === spread.short_exit_order_id) {
        return false;
      }
      if (order.symbol !== spread.short_symbol) {
        return false;
      }
      if (normalizeStatus(order.side) !== "buy") {
        return false;
      }
      return WORKING_CLOSE_ORDER_STATUSES.has(normalizeStatus(order.status));
    });
  }

  function bullPutSpreadLifecycleWarning(spread, orders) {
    if (!isMonitorableSpread(spread)) {
      return null;
    }
    const lifecycle = spread.raw_payload?.lifecycle || {};
    const shortExitOrder =
      (Array.isArray(orders) ? orders : []).find((order) => order.id === spread.short_exit_order_id) || null;
    const shortExitStatus = normalizeStatus(shortExitOrder?.status || lifecycle.close_order_state);
    const monitorRequiresClose = spread.status === "open" && isTruthLike(spread.raw_payload?.monitor?.should_close);
    const lifecycleRequiresAction =
      lifecycle.warning === BULL_PUT_CLOSE_ORDER_WARNING || lifecycle.manual_action_required === true;

    if (!spread.short_exit_order_id || !FAILED_CLOSE_ORDER_STATUSES.has(shortExitStatus)) {
      return null;
    }
    if (hasWorkingReplacementCloseOrder(spread, orders)) {
      return null;
    }
    if (!monitorRequiresClose && !lifecycleRequiresAction) {
      return null;
    }

    return {
      code: BULL_PUT_CLOSE_ORDER_WARNING,
      message: "Close order canceled / manual action needed",
      detail: "Review close workflow before leaving unattended.",
      orderId: spread.short_exit_order_id,
      orderStatus: shortExitStatus || "--",
    };
  }

  global.StocksToolLifecycle = {
    bullPutSpreadLifecycleWarning,
  };
})(window);

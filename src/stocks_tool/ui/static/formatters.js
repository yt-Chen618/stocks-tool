(function () {
  function toNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? number : Number.NaN;
  }

  function toFiniteNumber(value, fallback = 0) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function formatCurrency(value, currency = "USD") {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(number);
  }

  function formatNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    return number.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatDateTime(value) {
    if (!value) {
      return "--";
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleString("zh-CN", {
      hour12: false,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function formatSignedCurrency(value, currency = "USD") {
    const number = toNumber(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    const prefix = number > 0 ? "+" : "";
    return `${prefix}${formatCurrency(number, currency)}`;
  }

  function formatWeight(value, total) {
    const amount = toNumber(value);
    const denominator = toNumber(total);
    if (!Number.isFinite(amount) || !Number.isFinite(denominator) || denominator <= 0) {
      return "--";
    }
    return `${((amount / denominator) * 100).toFixed(1)}%`;
  }

  function formatPercent(value, base) {
    const numerator = toNumber(value);
    const denominator = toNumber(base);
    if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) {
      return "--";
    }
    const percent = (numerator / denominator) * 100;
    const prefix = percent > 0 ? "+" : "";
    return `${prefix}${percent.toFixed(2)}% of book`;
  }

  function formatSignedPercentValue(value) {
    const number = toNumber(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    const prefix = number > 0 ? "+" : "";
    return `${prefix}${number.toFixed(2)}%`;
  }

  function formatPercentValue(value) {
    const number = toNumber(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    return `${number.toFixed(2)}%`;
  }

  function formatSignedDecimal(value, decimals = 2) {
    const number = toNumber(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    const prefix = number > 0 ? "+" : "";
    return `${prefix}${number.toFixed(decimals)}`;
  }

  function formatImpliedVolatility(value) {
    const number = toNumber(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    const percent = Math.abs(number) <= 1 ? number * 100 : number;
    return `${percent.toFixed(1)}%`;
  }

  function formatPositionQuantity(value) {
    const number = toNumber(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    return number.toLocaleString("en-US", {
      minimumFractionDigits: Number.isInteger(number) ? 0 : 2,
      maximumFractionDigits: 2,
    });
  }

  function formatOrderAge(seconds) {
    if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) {
      return "";
    }
    const total = Math.max(0, Number(seconds));
    if (total < 60) {
      return `${Math.round(total)}s`;
    }
    const minutes = Math.floor(total / 60);
    const remainder = Math.round(total % 60);
    return remainder ? `${minutes}m ${remainder}s` : `${minutes}m`;
  }

  function formatSyncHeadline(lastSyncedAt, lastAttemptAt) {
    if (lastSyncedAt) {
      return `Last success ${formatDateTime(lastSyncedAt)}`;
    }
    if (lastAttemptAt) {
      return `Last attempt ${formatDateTime(lastAttemptAt)}`;
    }
    return "Waiting for first run";
  }

  function formatSyncDetail(status, lastSyncedAt, lastAttemptAt, error) {
    if (status === "syncing") {
      return lastAttemptAt ? `Started ${formatDateTime(lastAttemptAt)}` : "Sync request is in progress.";
    }
    if (status === "error") {
      return error || "The latest sync failed.";
    }
    if (lastSyncedAt) {
      return `Updated ${formatDateTime(lastSyncedAt)}`;
    }
    if (lastAttemptAt) {
      return `Attempted ${formatDateTime(lastAttemptAt)}`;
    }
    return "No reconciliation run has completed yet.";
  }

  function reconciliationTone(status) {
    if (status === "success") {
      return "success";
    }
    if (status === "syncing") {
      return "warning";
    }
    if (status === "error") {
      return "error";
    }
    return "neutral";
  }

  function reconciliationLabel(status) {
    if (status === "success") {
      return "Success";
    }
    if (status === "syncing") {
      return "Syncing";
    }
    if (status === "error") {
      return "Error";
    }
    return "Idle";
  }

  function statusClass(status) {
    if (status === "filled") {
      return "success";
    }
    if (status === "canceled" || status === "rejected") {
      return "error";
    }
    if (status === "submitted" || status === "partially_filled") {
      return "warning";
    }
    return "neutral";
  }

  function strategyStatusClass(status) {
    if (
      status === "approved" ||
      status === "executed" ||
      status === "closed" ||
      status === "rolled" ||
      status === "reviewed" ||
      status === "suggested" ||
      status === "low"
    ) {
      return "success";
    }
    if (
      status === "pending" ||
      status === "planned" ||
      status === "running" ||
      status === "candidate" ||
      status === "risk_check" ||
      status === "medium"
    ) {
      return "warning";
    }
    if (
      status === "rejected" ||
      status === "expired" ||
      status === "failed" ||
      status === "blocked" ||
      status === "high"
    ) {
      return "error";
    }
    return "neutral";
  }

  function journalEntryTone(entryType) {
    if (entryType === "review") {
      return "warning";
    }
    if (entryType === "plan") {
      return "success";
    }
    return "neutral";
  }

  function spreadStatusClass(status) {
    if (status === "open" || status === "closed") {
      return "success";
    }
    if (
      status === "entry_pending_long" ||
      status === "entry_pending_short" ||
      status === "exit_pending_short" ||
      status === "exit_pending_long"
    ) {
      return "warning";
    }
    if (status === "entry_failed" || status === "rollback_failed") {
      return "error";
    }
    return "neutral";
  }

  function titleizeStatus(value) {
    return String(value || "--")
      .replaceAll("_", " ")
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function formatSpreadStatusLabel(status) {
    return titleizeStatus(status);
  }

  function formatStrategyStatusLabel(status) {
    return titleizeStatus(status);
  }

  function formatSpreadExitReason(reason) {
    if (!reason) {
      return "--";
    }
    return titleizeStatus(reason);
  }

  function formatSpreadStrike(value) {
    const number = toNumber(value);
    if (!Number.isFinite(number)) {
      return "--";
    }
    return number.toLocaleString("en-US", {
      minimumFractionDigits: Number.isInteger(number) ? 0 : 2,
      maximumFractionDigits: 2,
    });
  }

  function formatSpreadDate(value) {
    if (!value) {
      return "--";
    }
    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleDateString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
    });
  }

  function formatSessionDate(value) {
    if (!value) {
      return "--";
    }
    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return date.toLocaleDateString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    });
  }

  function formatSpreadCredit(value) {
    if (value === null || value === undefined) {
      return "--";
    }
    return `$${formatSpreadStrike(value)}`;
  }

  window.StocksToolFormatters = {
    toNumber,
    toFiniteNumber,
    formatCurrency,
    formatNumber,
    formatDateTime,
    formatSignedCurrency,
    formatWeight,
    formatPercent,
    formatSignedPercentValue,
    formatPercentValue,
    formatSignedDecimal,
    formatImpliedVolatility,
    formatPositionQuantity,
    formatOrderAge,
    formatSyncHeadline,
    formatSyncDetail,
    reconciliationTone,
    reconciliationLabel,
    statusClass,
    strategyStatusClass,
    journalEntryTone,
    spreadStatusClass,
    formatSpreadStatusLabel,
    formatStrategyStatusLabel,
    formatSpreadExitReason,
    formatSpreadStrike,
    formatSpreadDate,
    formatSessionDate,
    formatSpreadCredit,
  };
})();

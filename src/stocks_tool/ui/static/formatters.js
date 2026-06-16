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
  };
})();

(function () {
  "use strict";

  const COLORS = {
    background: "#ffffff",
    text: "#43504e",
    grid: "#e8ecea",
    border: "#d7ddda",
    up: "#16866a",
    down: "#c44d56",
    sma20: "#2f6fed",
    sma50: "#b7791f",
  };

  function toNumber(value) {
    if (value === null || value === undefined || value === "") {
      return null;
    }
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function normalizeTime(bar) {
    const raw = bar?.date || bar?.time || bar?.timestamp || bar?.trade_date;
    if (raw === null || raw === undefined || raw === "") {
      return null;
    }
    if (typeof raw === "number") {
      return raw > 10_000_000_000 ? Math.floor(raw / 1000) : raw;
    }
    const value = String(raw);
    const dateMatch = value.match(/^(\d{4}-\d{2}-\d{2})/);
    if (dateMatch) {
      return dateMatch[1];
    }
    const milliseconds = Date.parse(value);
    return Number.isFinite(milliseconds) ? Math.floor(milliseconds / 1000) : null;
  }

  function normalizeBars(bars) {
    if (!Array.isArray(bars)) {
      return [];
    }
    const byTime = new Map();
    for (const source of bars) {
      const time = normalizeTime(source);
      const open = toNumber(source?.open);
      const high = toNumber(source?.high);
      const low = toNumber(source?.low);
      const close = toNumber(source?.close);
      if (time === null || [open, high, low, close].some((value) => value === null)) {
        continue;
      }
      byTime.set(String(time), {
        time,
        open,
        high,
        low,
        close,
        volume: toNumber(source?.volume),
        sma20: toNumber(source?.sma20),
        sma50: toNumber(source?.sma50),
      });
    }
    return Array.from(byTime.values()).sort((left, right) => {
      const leftValue = typeof left.time === "string" ? Date.parse(left.time) : left.time * 1000;
      const rightValue = typeof right.time === "string" ? Date.parse(right.time) : right.time * 1000;
      return leftValue - rightValue;
    });
  }

  function createUnavailableMessage(container, message) {
    let node = container.querySelector("[data-chart-unavailable]");
    if (!node) {
      node = document.createElement("div");
      node.dataset.chartUnavailable = "true";
      node.className = "research-chart-unavailable";
      node.setAttribute("role", "status");
      container.appendChild(node);
    }
    node.textContent = message;
    node.hidden = false;
    return node;
  }

  function create(container, options = {}) {
    if (!container) {
      return createNoopController();
    }

    const library = window.LightweightCharts;
    if (!library || typeof library.createChart !== "function") {
      createUnavailableMessage(
        container,
        options.unavailableMessage || "Chart library unavailable / 图表组件不可用",
      );
      return createNoopController(container);
    }

    const chart = library.createChart(container, {
      autoSize: false,
      width: Math.max(container.clientWidth, 320),
      height: Math.max(container.clientHeight, 420),
      layout: {
        attributionLogo: true,
        background: { type: library.ColorType?.Solid || "solid", color: COLORS.background },
        textColor: COLORS.text,
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: COLORS.grid },
        horzLines: { color: COLORS.grid },
      },
      rightPriceScale: { borderColor: COLORS.border },
      timeScale: {
        borderColor: COLORS.border,
        rightOffset: 4,
        barSpacing: 8,
        timeVisible: false,
      },
      crosshair: { mode: library.CrosshairMode?.Normal ?? 0 },
      localization: { locale: document.documentElement.lang || "zh-CN" },
    });

    const candleSeries = chart.addSeries(library.CandlestickSeries, {
      upColor: COLORS.up,
      downColor: COLORS.down,
      borderVisible: false,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
      priceScaleId: "right",
    });
    const volumeSeries = chart.addSeries(library.HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    const sma20Series = chart.addSeries(library.LineSeries, {
      color: COLORS.sma20,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: "SMA20",
    });
    const sma50Series = chart.addSeries(library.LineSeries, {
      color: COLORS.sma50,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: "SMA50",
    });

    chart.priceScale("right").applyOptions({ scaleMargins: { top: 0.08, bottom: 0.28 } });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
      borderVisible: false,
    });

    const unavailableNode = createUnavailableMessage(container, "");
    unavailableNode.hidden = true;
    let destroyed = false;
    let resizeObserver = null;

    const resize = () => {
      if (destroyed) {
        return;
      }
      const width = container.clientWidth;
      const height = container.clientHeight;
      if (width > 0 && height > 0) {
        chart.resize(width, Math.max(height, 420));
      }
    };
    if (typeof window.ResizeObserver === "function") {
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(container);
    } else {
      window.addEventListener("resize", resize);
    }

    function render(bars, renderOptions = {}) {
      if (destroyed) {
        return false;
      }
      const normalized = normalizeBars(bars);
      chart.applyOptions({
        localization: { locale: renderOptions.locale || document.documentElement.lang || "zh-CN" },
      });
      if (normalized.length === 0) {
        clear();
        unavailableNode.textContent =
          renderOptions.emptyMessage || "No chart history available / 暂无可用历史行情";
        unavailableNode.hidden = false;
        return false;
      }

      unavailableNode.hidden = true;
      candleSeries.setData(normalized.map(({ time, open, high, low, close }) => ({
        time,
        open,
        high,
        low,
        close,
      })));
      volumeSeries.setData(normalized
        .filter((bar) => bar.volume !== null)
        .map((bar) => ({
          time: bar.time,
          value: bar.volume,
          color: bar.close >= bar.open ? "rgba(22, 134, 106, 0.35)" : "rgba(196, 77, 86, 0.35)",
        })));
      sma20Series.setData(normalized
        .filter((bar) => bar.sma20 !== null)
        .map((bar) => ({ time: bar.time, value: bar.sma20 })));
      sma50Series.setData(normalized
        .filter((bar) => bar.sma50 !== null)
        .map((bar) => ({ time: bar.time, value: bar.sma50 })));
      chart.timeScale().fitContent();
      return true;
    }

    function clear() {
      if (destroyed) {
        return;
      }
      candleSeries.setData([]);
      volumeSeries.setData([]);
      sma20Series.setData([]);
      sma50Series.setData([]);
    }

    function setUnavailable(message) {
      clear();
      unavailableNode.textContent = message || "Chart unavailable / 图表不可用";
      unavailableNode.hidden = false;
    }

    function destroy() {
      if (destroyed) {
        return;
      }
      destroyed = true;
      if (resizeObserver) {
        resizeObserver.disconnect();
      } else {
        window.removeEventListener("resize", resize);
      }
      chart.remove();
    }

    return { render, clear, setUnavailable, resize, destroy, isAvailable: true };
  }

  function createNoopController(container = null) {
    return {
      render(_bars, options = {}) {
        if (container) {
          createUnavailableMessage(
            container,
            options.emptyMessage || "Chart library unavailable / 图表组件不可用",
          );
        }
        return false;
      },
      clear() {},
      setUnavailable(message) {
        if (container) {
          createUnavailableMessage(container, message || "Chart unavailable / 图表不可用");
        }
      },
      resize() {},
      destroy() {},
      isAvailable: false,
    };
  }

  window.StocksToolChart = { create, normalizeBars };
})();

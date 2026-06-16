(function () {
  const LANGUAGE_STORAGE_KEY = "stocks-tool-language";
  const DEFAULT_LANGUAGE = "zh";

  function readStoredLanguage() {
    try {
      return window.localStorage.getItem(LANGUAGE_STORAGE_KEY) || DEFAULT_LANGUAGE;
    } catch (_error) {
      return DEFAULT_LANGUAGE;
    }
  }

  function createOverlayStatus(kind, detail = "", reason = "") {
    return { kind, detail, reason };
  }

  function createInitialState() {
    return {
      accounts: [],
      selectedAccountId: "",
      watchlists: [],
      orders: [],
      spreads: [],
      recoverCloseEligibility: {},
      runtime: null,
      zeroDteLotteryRuntime: null,
      zeroDteLotteryPreview: null,
      zeroDteLotteryScanResult: null,
      strategyExperiment: { proposals: [], runs: [], signals: [], reviews: [] },
      coveredCallActivity: { summary: {}, proposals: [], runs: [], signals: [], reviews: [] },
      advisorContext: null,
      advisorDraft: null,
      advisorRuns: [],
      operatorStatus: null,
      advisorStatus: createOverlayStatus(
        "idle",
        "Advisor context is available on demand. DeepSeek dry-run sends selected account context outside the local app.",
      ),
      marketEvents: [],
      executions: [],
      journals: [],
      brokerStatus: null,
      latestSnapshot: null,
      selectedOrderId: "",
      quote: null,
      quoteStatus: createOverlayStatus("idle", "Load a quote manually to keep the dashboard fast."),
      preOpenAssessment: null,
      preOpenStatus: createOverlayStatus(
        "idle",
        "Macro board is available on demand so option strategy requests stay first.",
      ),
      preOpenRuns: [],
      preOpenSeedAttempts: {},
      language: readStoredLanguage(),
    };
  }

  window.StocksToolState = {
    createInitialState,
    readStoredLanguage,
    createOverlayStatus,
  };
})();

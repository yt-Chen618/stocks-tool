(function () {
  async function fetchJson(url, options = {}) {
    const {
      timeoutMs = null,
      signal: providedSignal,
      headers: providedHeaders = {},
      ...requestOptions
    } = options;
    const controller = new AbortController();
    const signal = mergeAbortSignals(controller.signal, providedSignal);
    let timeoutId = null;
    if (timeoutMs !== null && timeoutMs !== undefined) {
      timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    }

    try {
      const response = await fetch(url, {
        ...requestOptions,
        headers: {
          "Content-Type": "application/json",
          ...providedHeaders,
        },
        signal,
      });

      if (!response.ok) {
        let detail = `Request failed: ${response.status}`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = typeof payload.detail === "string" ? payload.detail : payload.detail.message || detail;
            const error = new Error(detail);
            error.status = response.status;
            error.code = payload.detail.code || payload.code || null;
            error.intentId = payload.detail.intent_id || payload.intent_id || null;
            error.retryable = payload.detail.retryable ?? payload.retryable;
            error.payload = payload;
            throw error;
          }
        } catch (error) {
          if (error instanceof Error && error.status) {
            throw error;
          }
          // Keep the status-based detail when the error payload is not JSON.
        }
        const error = new Error(detail);
        error.status = response.status;
        throw error;
      }

      return response.json();
    } catch (error) {
      if (error?.name === "AbortError" && timeoutMs !== null && timeoutMs !== undefined) {
        throw new Error(`Request timed out after ${Math.ceil(timeoutMs / 1000)}s.`);
      }
      throw error;
    } finally {
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
      }
    }
  }

  function mergeAbortSignals(...signals) {
    const activeSignals = signals.filter(Boolean);
    if (activeSignals.length === 0) {
      return undefined;
    }
    if (activeSignals.length === 1) {
      return activeSignals[0];
    }
    const controller = new AbortController();
    const abort = () => controller.abort();
    for (const signal of activeSignals) {
      if (signal.aborted) {
        controller.abort();
        return controller.signal;
      }
      signal.addEventListener("abort", abort, { once: true });
    }
    return controller.signal;
  }

  window.StocksToolApiClient = {
    fetchJson,
    mergeAbortSignals,
  };
  window.fetchJson = fetchJson;
})();

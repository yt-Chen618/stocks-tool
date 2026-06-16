(function () {
  async function fetchJson(url, options = {}) {
    const { timeoutMs = null, signal: providedSignal, ...requestOptions } = options;
    const controller = new AbortController();
    const signal = mergeAbortSignals(controller.signal, providedSignal);
    let timeoutId = null;
    if (timeoutMs !== null && timeoutMs !== undefined) {
      timeoutId = setTimeout(() => controller.abort(), timeoutMs);
    }

    try {
      const response = await fetch(url, {
        headers: {
          "Content-Type": "application/json",
          ...(requestOptions.headers || {}),
        },
        ...requestOptions,
        signal,
      });

      if (!response.ok) {
        let detail = `Request failed: ${response.status}`;
        try {
          const payload = await response.json();
          if (payload?.detail) {
            detail = payload.detail;
          }
        } catch {
          // Keep the status-based detail when the error payload is not JSON.
        }
        throw new Error(detail);
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

# API Route Inventory

Last updated: 2026-08-10

This inventory groups public routes by bounded context. Paths are part of the compatibility surface for the dashboard and regression scripts.

## UI and Health

- `GET /`
- `GET /app`
- `GET /health`
- `GET /docs`

## Research and Plans

- `POST /research/rank`
- `GET /research/universe`
- `GET /research/technicals`
- `GET /research/symbols/{symbol}/history`
- `POST /plans/draft`
- `POST /plans/validate`

## Accounts and Brokers

- `GET /broker-accounts`
- `POST /broker-accounts`
- `GET /account-snapshots`
- `GET /account-snapshots/latest`
- `GET /brokers/profiles`
- `POST /brokers/longbridge/account-sync/{external_account_id}`
- `GET /brokers/longbridge/profile`
- `GET /brokers/longbridge/quote`
- `GET /brokers/longbridge/option-chain`

## Orders, Executions, and Journals

Every broker-mutation route requires a 16-128 character ASCII `Idempotency-Key` matching `[A-Za-z0-9._:-]`. This includes direct order submit/replace/cancel and Bull Put/Covered Call lifecycle writes. Missing keys return `428`; conflicting or unresolved keys return a structured `409`; completed replays preserve the original result and add `Idempotent-Replayed: true`.

- `GET /orders`
- `POST /orders/submit`
- `POST /orders/{order_id}/refresh`
- `POST /orders/{order_id}/replace`
- `POST /orders/{order_id}/cancel`
- `POST /orders/sync/longbridge/{external_account_id}`
- `GET /executions`
- `GET /journals`
- `POST /journals`

## Market Events and Watchlists

- `GET /market-events`
- `POST /market-events`
- `POST /market-events/import`
- `POST /market-events/import/provider`
- `GET /watchlists`
- `POST /watchlists`
- `POST /watchlists/{watchlist_id}/items`
- `PATCH /watchlists/{watchlist_id}`
- `PATCH /watchlists/{watchlist_id}/items/{item_id}`
- `DELETE /watchlists/{watchlist_id}/items/{item_id}`

### Research Workstation Read Contracts

All three workspace reads require `mode=paper` (the default) and are strictly read-only. They do not provide quote authorization for a broker mutation.

- `GET /research/universe` accepts optional `external_account_id` and `watchlist_id`. It merges the requested/default watchlist, latest positions, configured Bull Put and Zero-DTE pools, and active Bull Put spread state by uppercase symbol, preserving all source labels. Rows carry a batch quote, position fields, next event within 30 days, strategy state, warnings, and aggregate `data_quality`. The maximum is 50 unique symbols; an overflow returns `422 research_universe_limit_exceeded` with `limit` and `count`, rather than truncating. A requested missing list returns `404 research_watchlist_not_found`.
- `GET /research/technicals` takes repeated and/or comma-separated `symbols` query parameters, with a hard maximum of 10 expanded nonblank symbol tokens per request. More than 10 returns `422 research_technicals_limit_exceeded`; blank input returns `422 research_symbols_required`. The service normalizes symbols before calculation. Every returned symbol is independent: `status` is `ok`, `partial`, or `unavailable` and includes a warning when appropriate. It reads 66 daily bars to calculate 20/60-day returns, SMA20/SMA50, two trend booleans, 20-day annualized realized volatility, and average volume/turnover over the preceding 20 complete sessions.
- `GET /research/symbols/{symbol}/history` accepts `range=3m|6m|1y` and reads 66/132/252 daily bars. Each point contains OHLCV, turnover, SMA20, and SMA50. It returns `short_history` or `daily_bars_unavailable` warning codes instead of authorizing any downstream trading action.

The watchlist update routes keep list deletion, drag ordering, and grouping out of scope. `PATCH /watchlists/{watchlist_id}` updates name, description, and/or default selection; `PATCH /watchlists/{watchlist_id}/items/{item_id}` updates item notes; deleting an item returns `204` after the client-side confirmation step.

Adding a watchlist item trims and uppercases its symbol, rejects blank/overlong input with `422`, and returns `409` for a duplicate (including a legacy whitespace/case variant). Historical rows are not rewritten. Research skips blank legacy symbols and reports normalization/duplicate warnings. Event lookup filters the universe symbols plus global events before reading the full 30-day window, so unrelated events cannot consume a global 500-row limit.

## Strategy Runtime

- `GET /strategies/controls`
- `GET /strategies/experiment`
- `GET /strategies/proposals`
- `POST /strategies/proposals`
- `POST /strategies/proposals/{proposal_id}/approve`
- `POST /strategies/proposals/{proposal_id}/reject`
- `GET /strategies/runs`
- `POST /strategies/runs`
- `GET /strategies/signals`
- `POST /strategies/signals`
- `GET /strategies/reviews`
- `POST /strategies/reviews`

## Advisor

- `GET /strategies/advisor-context`
- `POST /strategies/advisor/deepseek/dry-run`
- `GET /strategies/advisor/audit`
- `GET /strategies/advisor/runs`
- `GET /strategies/advisor/run-cards`
- `GET /strategies/advisor/playbooks`
- `POST /strategies/advisor/responses`

## Bull Put

- `GET /strategies/bull-put/preview`
- `GET /strategies/bull-put/readiness`
- `GET /strategies/bull-put/spreads`
- `GET /strategies/bull-put/spreads/{spread_id}`
- `GET /strategies/bull-put/dashboard`
- `GET /strategies/bull-put/runtime`
- `POST /strategies/bull-put/runtime/{external_account_id}`
- `POST /strategies/bull-put/runtime/{external_account_id}/scan`
- `POST /strategies/bull-put/runtime/{external_account_id}/review`
- `POST /strategies/bull-put/execute`
- `POST /strategies/bull-put/spreads/{spread_id}/refresh`
- `GET /strategies/bull-put/spreads/{spread_id}/recover-close/eligibility`
- `POST /strategies/bull-put/spreads/{spread_id}/recover-close`
- `POST /strategies/bull-put/spreads/{spread_id}/monitor`

## Covered Call

- `GET /strategies/covered-call/preview`
- `POST /strategies/covered-call/propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/monitor`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue`
- `POST /strategies/covered-call/proposals/{proposal_id}/close`
- `GET /strategies/covered-call/activity`
- `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile`

## Zero-DTE Lottery

Only Preview is executable in P0. The execute route, `force=true` scan, and attempts to enable auto-order return `409 zero_dte_execution_disabled_pending_lifecycle` before reaching the order service.

- `GET /strategies/zero-dte-lottery/preview`
- `POST /strategies/zero-dte-lottery/execute`
- `GET /strategies/zero-dte-lottery/runtime`
- `POST /strategies/zero-dte-lottery/runtime/{external_account_id}`
- `POST /strategies/zero-dte-lottery/runtime/{external_account_id}/scan`

## Pre-Open

- `GET /strategies/pre-open-risk`
- `GET /strategies/pre-open-runs`
- `POST /strategies/pre-open-runs/{external_account_id}/capture`
- `POST /strategies/pre-open-runs/{external_account_id}/review`

## Operator

- `GET /ops/unattended-status`
- `GET /ops/reason-codes`
- `GET /ops/market-data-runtime`
- `GET /ops/scheduler`
- `GET /ops/consistency`
- `POST /ops/consistency/repairs/{repair_id}`
- `GET /ops/audit`
- `GET /ops/audit/summary`
- `GET /ops/trading-intents`
- `GET /ops/trading-intents/{intent_id}`
- `POST /ops/trading-intents/{intent_id}/resolve-no-order`
- `GET /ops/trade-actions`
- `GET /ops/trade-actions/{action_intent_id}`

No-order resolution requires explicit paper confirmation and three complete zero-match reconciliations spanning at least 60 seconds. Migration `20261002_0017` adds the persisted coverage evidence required by this check; legacy counts alone do not qualify. Incomplete history reads or conflicting broker identity evidence keep the intent unresolved.

Advisor Record Output is atomic across its local ledger and audit writes. With `advisor_run_id`, matching retries return the linked proposal/review records; mismatched payloads or run ownership return `409`. Covered-call roll continuation validates that both order IDs belong to the current proposal's latest roll run and that quantities match the proposal; an existing linked sell ID cannot be omitted to request a new sell.

# API Route Inventory

Last updated: 2026-10-04

This inventory groups public routes by bounded context. Paths are part of the compatibility surface for the dashboard and regression scripts.

## UI and Health

- `GET /`
- `GET /app`
- `GET /health`
- `GET /health/live`
- `GET /health/ready`
- `GET /docs`

## Portfolio and Offline Backtests

- `GET /portfolio/analytics`
- `GET /portfolio/risk`
- `GET|POST /backtests/datasets`
- `GET /backtests/datasets/{dataset_id}`
- `POST /backtests/datasets/{dataset_id}/validate`
- `GET|POST /backtests`
- `GET /backtests/{run_id}`
- `POST /backtests/{run_id}/start`
- `POST /backtests/{run_id}/cancel`
- `POST /backtests/compare`

Portfolio reads default to paper mode. Analytics accept `start`, `end` and bounded
`max_points`; risk currently describes current persisted exposures, and rejects
historical `as_of` requests rather than combining historical balances with current
strategy state. Unknown currencies, cash flows, fees and Greeks are explicit gaps.

Backtests operate on registered local datasets and separate run/result tables.
They have no broker execution mode or implicit account holdings. Formal runs
covering the holdout period require a frozen validation reference. Dataset
registration and a queued job are not evidence of a successful simulation.

## Research and Plans

New screen/case/timeline reads return bounded cursor envelopes, with `limit`
at most 100. Timeline ranges are at most 366 days. Capturing a case is an
explicit server read of the selected symbol and configuration; subsequent GETs
read the immutable saved evidence and do not call a provider.

- `POST /research/rank`
- `GET /research/universe`
- `GET /research/technicals`
- `GET /research/symbols/{symbol}/history`
- `GET|POST /research/screens`
- `GET|PATCH /research/screens/{screen_id}`
- `POST /research/screens/{screen_id}/copy`
- `GET|POST /research/cases`
- `GET /research/cases/{case_id}`
- `GET /research/timeline`
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
- `GET /orders/paged`
- `POST /orders/submit`
- `POST /orders/{order_id}/refresh`
- `POST /orders/{order_id}/replace`
- `POST /orders/{order_id}/cancel`
- `POST /orders/sync/longbridge/{external_account_id}`
- `GET /executions`
- `GET /executions/paged`
- `GET /journals`
- `GET /journals/paged`
- `POST /journals`

The historical `GET /orders`, `GET /executions`, and `GET /journals` routes keep their complete-list contract for reconciliation and explicit history reads. The three `/paged` routes are bounded dashboard reads. They return a `CursorPage` with `items`, `next_cursor`, `has_more`, and `limit`; `limit` is 1–100 and defaults to 50. Cursors are opaque and bound to the account and other filters used to create them. Orders accept `status`, `mode`, and `symbol`; executions accept `order_id`; journals accept `order_id`, `trade_plan_id`, and `entry_type`. A cursor reused with different filters is rejected.

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
- `GET /strategies/bull-put/spreads/paged`
- `GET /strategies/bull-put/working-spreads`
- `GET /strategies/bull-put/active-spreads`
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

The Bull Put `/spreads/paged` read requires `external_account_id`, defaults to `mode=paper` and `limit=50` (maximum 100), and returns the existing `CursorPage`. Ordering is fixed at `(created_at DESC, id DESC)` and the opaque cursor is bound to account and mode. The dashboard requests 25 rows per page. `/working-spreads` requires the account and returns all active or `manual_action_required=true` records in that mode. Complete-list, active-list and ID-detail routes keep their existing contracts. Strategy decisions never consume UI pages.

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

## Market-Session Comparison

- `POST /market-session-comparisons`
- `GET /market-session-comparisons`
- `GET /market-session-comparisons/latest`
- `GET /market-session-comparisons/{comparison_id}`

The comparison capture is broker-read-only but persists an immutable local row. It
accepts an account, `mode`, `symbol`, and optional `pre_open_run_id` / `capture_key`.
The server resolves a true premarket assessment for the same target trading day;
client-supplied prices are never accepted as evidence. The regular-close reference
uses a Longbridge quote observed at or after the exchange close, or a validated
same-day daily-bar close when that is the available reference. The close boundary is
`16:00 ET`, or `13:00 ET` on a confirmed U.S. half day. A quote observed before that
boundary cannot be labelled regular close.

The post-market leg uses `post_market_quote.last_done`. Missing, stale, future,
cross-day, timezone-unknown, or currency-unknown evidence remains missing and the
corresponding percentage is not calculated; it is never replaced with zero. The
response carries `baseline_evidence`, `regular_close_evidence`,
`post_market_evidence`, reason codes, field explanations, and both
`pre_to_regular_close_pct` and `regular_close_to_after_hours_pct` when valid.

Comparison history is account/mode/symbol scoped and uses the opaque bounded cursor
contract with `limit=1..100`. Capture idempotency is scoped to account and mode. A
retry with the same `capture_key` and original request fingerprint replays the
immutable comparison; reusing that key with a different symbol, mode, or baseline
returns `409`. Omitting `capture_key` creates a new observation. Migration
`20261004_0025` is required for the persisted table; operator rollout must be
verified separately from this route contract.

## Operator

- `GET /ops/unattended-status`
- `GET /ops/reason-codes`
- `GET /ops/market-data-runtime`
- `GET /ops/recovery-status`
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

`/ops/consistency` preserves `check_count`, `pass_count`, `warn_count`, `fail_count`, and `repair_available_count` for the displayed checks. The additive `total_check_count`, `total_warn_count`, `total_fail_count`, `total_repair_available_count`, `truncated`, and `coverage_complete` fields describe the full scan. Overall status uses complete evidence; changing `limit` only changes detail display. Incomplete coverage cannot produce a healthy status. Covered Call activity and Advisor context use complete account/mode aggregates independently of their displayed history limit.

Advisor Record Output is atomic across its local ledger and audit writes. With `advisor_run_id`, matching retries return the linked proposal/review records; mismatched payloads or run ownership return `409`. Covered-call roll continuation validates that both order IDs belong to the current proposal's latest roll run and that quantities match the proposal; an existing linked sell ID cannot be omitted to request a new sell.

### Bounded strategy and recovery reads

`GET /strategies/bull-put/active-spreads` is the bounded strategy/dashboard read. It applies the active lifecycle-status predicate in the database and accepts `external_account_id`, `mode` (default `paper`), and an optional `symbol`. The historical `GET /strategies/bull-put/spreads` route remains the complete read. The active route is read-only and is not used for order-capacity or lifecycle decisions.

`GET /ops/recovery-status?external_account_id=LBPT10087357&mode=paper&limit=100` is a read-only operator explanation of unresolved parent trade actions and child order intents. It reports total and displayed counts, unknown states, coverage timestamps, no-order evidence status, per-parent and per-child reason codes, next actions, and local SDK timeout quarantine state. `limit` bounds the displayed unresolved records (1–500); the `truncated` flag must be checked before treating the displayed list as complete. The endpoint does not reconcile intents, resolve them, initialize a broker context, or submit an order.

Migration `20261002_0018` adds the account/time/id keyset indexes used by the paged history reads, the proposal/run decision-scope indexes used by Covered Call lifecycle and reservation queries, and the active-spread scope index used by the database-filtered route. It is additive and does not change the complete-list semantics of the legacy routes.

Covered Call lifecycle reconciliation accepts `mode` (default `paper`). Its former `limit` query parameter remains accepted but is marked deprecated: complete lifecycle evidence queries now ignore that old history cap. Paper scheduler work, spread capacity, and the paper dashboard apply explicit mode filters. The legacy Bull Put spread history route accepts an optional `mode`; omitting it preserves the prior complete-history contract.

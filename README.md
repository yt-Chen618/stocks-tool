# Stocks Tool

`stocks-tool` is the first-pass architecture skeleton for a US equities and options trading workbench.

The project is intentionally scoped around:

- research and event ingestion
- standardized trade-plan generation
- rule-based risk checks
- broker adapter boundaries
- paper-first execution workflows

It does not attempt live autonomous trading in the current phase.

The October 2026 correction pass requires `alembic upgrade head` to revision `20261002_0017`. It hardens unknown-order history evidence, covered-call order linkage, scheduler leases, and atomic Advisor recording; it also corrects imported option metadata, research event completeness, and watchlist input handling. See `docs/runtime-operations.md` for the migration and recovery rules. Paper entry kill switches and the Zero-DTE execution lock remain in force.

## Current status

This repository currently contains:

- a runnable FastAPI application skeleton
- domain models for plans, accounts, risk checks, and orders
- a Longbridge adapter boundary with quote and account-sync entry points
- a paper bull put spread workflow with preview, two-leg entry, exit monitoring, rollback, and spread persistence
- a bull put runtime-state layer with scheduled entry scans, review generation, kill-switch style controls, and strategy journaling
- a strategy experiment ledger for proposals, runs, signals, and reviews before new strategies are automated
- a persistent DeepSeek advisor run ledger for dry-run auditing, token/cache usage, response payloads, record status, downstream impact snapshots, and dashboard history
- a first-pass `covered_call_v1` proposal workflow that records covered-call candidates and roll candidates before order execution
- a preview-only `zero_dte_lottery_v1` research workflow; all execution and auto-order surfaces are P0-locked until expiration handling exists
- a local market-event calendar for earnings and macro risk windows, including CSV import and a first FMP provider adapter
- a pre-open downside board with SPY / QQQ option-chain analysis for directional long-put checks
- a background paper-account reconciliation loop for account snapshots, orders, and open bull put spreads
- a read-only operator status endpoint for unattended paper posture and lifecycle warnings
- an order-linked journal and review workflow for trade notes
- a PostgreSQL-ready database layer with SQLAlchemy and Alembic
- current architecture, route inventory, runtime operations, lifecycle, regression, operator runbook, release-slice, and optimization design docs under `docs/`

### 2026-08-10 research workstation change

`/` and `/app` now render the same fixed, paper-first research workstation. The old `Focus` / `All` dashboard toggle and the unused `Quick Quote` surface are removed; this is not a second frontend or a new build service.

- The five persistent workspaces are Research Desk (the default), Strategy Lab, Macro & Events, Portfolio, and Operations. A 224px dark sidebar can collapse to 64px; the fixed top bar keeps the selected account, Paper posture, data time, global status, language switch, refresh, and the explicit Execution entry point visible.
- Research Desk is a shared-symbol context: it combines the selected/default watchlist, latest positions for the selected account, configured Bull Put and Zero-DTE pools, active Bull Put spread state, local events, and batched quotes. The screener draws quotes/account context first, then loads technicals progressively; it does not wait for daily bars before showing the table.
- The screener supplies fixed Overview, Momentum, and Strategy column groups, sorting, sticky headers, source/event/position/strategy filters, and a synchronized chart selection. Table/chart choice, filters, sorting, selected symbol, chart range, column group, workspace, sidebar state, language, and collapsible-module state persist locally. Current keys are `stocks-tool-workspace`, `stocks-tool-sidebar-collapsed`, `stocks-tool-research-state`, `stocks-tool-language`, and `stocks-tool-collapsed-modules`; per-action idempotency keys remain session-scoped under `stocks-tool-idempotency:`.
- Chart view uses the bundled standalone TradingView Lightweight Charts `5.2.0` asset, including its attribution logo. It is served locally from `src/stocks_tool/ui/static/vendor/`, with the upstream license and NOTICE/attribution record beside it; no chart CDN is required at runtime.
- The native `dialog` execution drawer is 640px on desktop and contains Ticket, Orders, Order Detail, and Journal tabs. Research may prefill only a symbol; it must not infer side, quantity, order type, or price. The existing confirmation dialog, API idempotency/replay behavior, unknown-outcome locks, and strategy safety gates remain the authority for broker writes. At `<=780px`, the drawer stays available for read-only review while broker-writing controls remain disabled.
- Watchlist management retains create and add-item behavior and now supports renaming, description/default changes, editing item notes, and confirmed item removal. This release deliberately does not delete whole lists, reorder items, or introduce groups.

#### Research read APIs

The three Research Workstation read routes below are paper-mode only (`mode=paper`): they are read models and must not be used as broker-order authorization evidence. The pre-existing `/research/rank` route is a separate research contract.

- `GET /research/universe?external_account_id=...&watchlist_id=...&mode=paper` returns uppercase-deduplicated rows with every source label retained, batch quote, position summary, next event in the next 30 days, strategy states, per-row warnings, overall data quality, and response warnings. It uses the explicit watchlist when supplied or the default list otherwise, then merges positions and strategy pools. More than 50 unique symbols returns `422` with `research_universe_limit_exceeded`; it never silently truncates. Missing selected lists return `404 research_watchlist_not_found`.
- `GET /research/technicals?symbols=AAPL.US&symbols=MSFT.US&mode=paper` accepts repeated and comma-separated values, with at most 10 expanded nonblank symbol tokens per request. The UI sequences repeated-parameter batches and keeps technical-dependent filters disabled until all batches finish, so row ordering does not jump. Each item independently returns `ok`, `partial`, or `unavailable` plus a warning. Calculations read 66 daily bars: 20/60-day returns, SMA20/SMA50, close-vs-SMA20 and SMA20-vs-SMA50 flags, 20-day annualized realized volatility, and prior-20-complete-session average volume/turnover. A failed symbol does not fail its batch.
- `GET /research/symbols/{symbol}/history?range=3m|6m|1y&mode=paper` reads 66/132/252 daily bars, returns OHLCV, turnover, and point-in-time SMA20/SMA50, and reports `short_history` or `daily_bars_unavailable` warnings without treating degraded/cached data as trade permission.

## Repository layout

```text
alembic/
compose.yaml
docs/
  architecture.md
  database.md
src/stocks_tool/
  api/
  application/
  adapters/
  core/
  db/
  domain/
  ports/
  repositories/
tests/
```

## Quick start

1. Create a virtual environment.
2. Copy `.env.example` to `.env`.
3. Start PostgreSQL with Docker Compose.
4. Install the package in editable mode.
5. Apply database migrations.
6. Start the API server.

```bash
python -m venv .venv
.venv\Scripts\activate
copy .env.example .env
docker compose up -d db
pip install -e .[dev]
alembic upgrade head
uvicorn --app-dir src stocks_tool.main:app --reload
```

If you already installed the project before the Longbridge SDK dependency was added, rerun:

```bash
pip install -e .[dev]
```

For Longbridge integration, fill these values in `.env`:

```text
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_PAPER_ACCESS_TOKEN=...
LONGBRIDGE_ACCESS_TOKEN=...
```

Then open:

- `GET /`
- `GET /app`
- `GET /health`
- `POST /research/rank`
- `GET /research/universe?external_account_id=LBPT10087357&mode=paper`
- `GET /research/technicals?symbols=QQQ.US&mode=paper`
- `GET /research/symbols/QQQ.US/history?range=6m&mode=paper`
- `POST /plans/draft`
- `POST /plans/validate`
- `GET /brokers/profiles`
- `GET /brokers/longbridge/profile`
- `GET /brokers/longbridge/quote?symbol=AAPL.US&mode=paper`
- `POST /brokers/longbridge/account-sync/{external_account_id}?mode=paper`
- `GET /account-snapshots/latest?external_account_id=LBPT10087357`
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
- `GET /strategies/bull-put/preview?external_account_id=LBPT10087357&symbol=QQQ.US&mode=paper`
- `GET /strategies/bull-put/readiness?external_account_id=LBPT10087357&mode=paper`
- `GET /strategies/pre-open-risk`
- `GET /strategies/pre-open-runs`
- `POST /strategies/pre-open-runs/{external_account_id}/capture`
- `POST /strategies/pre-open-runs/{external_account_id}/review`
- `GET /strategies/bull-put/spreads`
- `GET /strategies/bull-put/spreads/{spread_id}`
- `GET /strategies/bull-put/runtime?external_account_id=LBPT10087357&mode=paper`
- `POST /strategies/bull-put/execute`
- `POST /strategies/bull-put/spreads/{spread_id}/refresh`
- `GET /strategies/bull-put/spreads/{spread_id}/recover-close/eligibility`
- `POST /strategies/bull-put/spreads/{spread_id}/recover-close`
- `POST /strategies/bull-put/spreads/{spread_id}/monitor`
- `POST /strategies/bull-put/runtime/{external_account_id}`
- `POST /strategies/bull-put/runtime/{external_account_id}/scan`
- `POST /strategies/bull-put/runtime/{external_account_id}/review`
- `GET /strategies/covered-call/preview`
- `GET /strategies/zero-dte-lottery/preview`
- `POST /strategies/zero-dte-lottery/execute`
- `GET /strategies/zero-dte-lottery/runtime`
- `POST /strategies/zero-dte-lottery/runtime/{external_account_id}`
- `POST /strategies/zero-dte-lottery/runtime/{external_account_id}/scan`
- `GET /strategies/covered-call/activity`
- `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile`
- `POST /strategies/covered-call/propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/monitor`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue`
- `POST /strategies/covered-call/proposals/{proposal_id}/close`
- `GET /strategies/experiment`
- `GET /strategies/controls`
- `GET /strategies/advisor-context`
- `POST /strategies/advisor/deepseek/dry-run`
- `POST /strategies/advisor/responses`
- `GET /strategies/advisor/runs`
- `GET /strategies/advisor/run-cards`
- `GET /strategies/advisor/playbooks`
- `GET /strategies/advisor/audit`
- `GET /ops/unattended-status?external_account_id=LBPT10087357&mode=paper`
- `GET /ops/scheduler?external_account_id=LBPT10087357`
- `GET /ops/consistency?external_account_id=LBPT10087357&mode=paper`
- `POST /ops/consistency/repairs/{repair_id}`
- `GET /ops/audit?external_account_id=LBPT10087357`
- `GET /ops/audit/summary?external_account_id=LBPT10087357&mode=paper`
- `GET /ops/market-data-runtime`
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
- `GET /journals`
- `GET /executions`
- `GET /orders`
- `POST /journals`
- `POST /orders/submit`
- `POST /orders/{order_id}/refresh`
- `POST /orders/{order_id}/replace`
- `POST /orders/{order_id}/cancel`
- `POST /orders/sync/longbridge/{external_account_id}`

Order submission is currently paper-first and broker-native:

- use Longbridge-formatted symbols such as `AAPL.US`
- `limit` and `market` orders map directly
- `stop` orders are translated to Longbridge `MIT` or `LIT` based on whether `limit_price` is provided
- live submission stays blocked unless `ALLOW_LIVE_TRADING=true`
- local order reconciliation can be pulled on demand through `/orders/sync/longbridge/{external_account_id}`
- automatic paper reconciliation also runs in the background for active Longbridge broker accounts
- automatic bull put monitoring also runs in the background for open or exit-pending paper spreads
- execution summaries are persisted from broker order-detail snapshots and can be read through `/executions`
- journal entries can be linked to an account, order, trade plan, and latest execution context through `/journals`

The bull put spread workflow is currently paper-only:

- configured universe: `QQQ.US`, `SMH.US`, `SOXL.US`, `EWY.US`
- entry caps: at most `2` active spreads per account, `1` active spread per symbol, and `1` active spread across the correlated `QQQ.US / SMH.US / SOXL.US` group
- daily caps and controls: at most `1` new spread per day, a runtime-tracked realized loss stop, per-account manual pause, kill switch, and paused-symbol list
- target expiration window: `28-35 DTE`
- short-leg filter: `abs(delta)` in `0.18-0.28`, `open_interest >= 200`
- liquidity filter: both legs must have a tight positive bid/ask, fresh option quote timestamps, and configured minimum same-day volume
- width rule: `<75 -> 1`, `75-249.99 -> 2`, `>=250 -> 3`
- trend filter: price above `20 DMA`, `20 DMA > 50 DMA`, not more than `0.5%` below prior close, and not more than `2%` below the open
- risk model: conservative credit and per-trade account risk cap are enforced before the spread is marked eligible
- entry session gate: new spread entries only execute during regular U.S. options hours (`09:30-16:00 ET`)
- entry timing guard: new spread entries wait for the configured post-open confirmation window and stop before the close buffer, so manual execution does not chase the opening print or start a two-leg entry too late in the day
- entry workflow: preview the candidate, buy the protective long put first, then sell the short put
- repricing ladder: long-leg entry now starts at the current ask and can step higher by the configured increment; short-leg entry starts at bid and can reprice lower before the spread is abandoned and the hedge is rolled back
- exit monitor: manual or scripted `monitor` calls evaluate `50%` take-profit, `200%` stop-loss, short-strike breach, and `<= 7 DTE`
- close workflow: buy back the short put first, then flatten the long put; if the long-leg close does not fill, the spread remains `exit_pending_long`
- scheduler: the existing background reconciliation loop now checks the bull put entry window once per loop and also monitors open or exit-pending bull put spreads on the configured monitor interval
- review workflow: the strategy now auto-generates account-level bull put reviews when the closed-spread count or review window is due, and it can also be forced manually
- rollback behavior: if the short leg fails to fill, the service attempts to flatten the long leg and marks the spread `rolled_back` or `rollback_failed`
- persistence: spread lifecycle, order ids, entry credit, and risk summary are stored in `bull_put_spreads`
- runtime state: daily entry count, daily realized PnL, last scan result, last skip reason, last review summary, last action, and paused symbols are stored in `bull_put_strategy_runtime`
- journaling: the strategy now writes entry, close, scan-skip, and parameter-review notes into the existing journal workflow
- pre-open run persistence: the strategy now stores one structured pre-open assessment per target U.S. session date, auto-journals the captured read, and records opening follow-through at `09:30 / 09:45 / 10:00 ET`
- holiday handling: the pre-open assessment now distinguishes normal Mondays from exchange holidays, so `2026-05-25` Memorial Day correctly rolls the next regular open to `2026-05-26 09:30 ET`
- dashboard: the `/` workbench now shows a real-time macro board for QQQ / SPY downside checks, including plain-put action guidance, gap-chase risk, opening checkpoints, optional reference-put liquidity summaries, optional deeper option-chain analysis with front / next expiry ATM IV, put-skew, term-slope, and liquid-strike summaries, plus a separate stored opening follow-through review for the selected broker account, alongside bull put strategy controls, last skip reason, latest review, recent strategy notes, bull put spread summary cards, and per-spread `refresh` / `monitor` controls
- historical dashboard load behavior: before the 2026-08-10 research workstation, account snapshots, orders, spreads, runtime state, executions, journals, and the latest stored pre-open run rendered first while `Quick Quote` and the real-time macro board were manual. `Quick Quote` is now removed; Research Desk renders its batch quote/account context first and fills daily-bar technicals progressively.
- dashboard strategy-first behavior: `/` now loads bull put runtime, spreads, orders, executions, journals, and stored pre-open runs first; `Load Live Macro` uses the fast macro path, `Load Option Overlays` fetches slower option-chain layers on demand, and `Save Current Board` persists the current live/partial macro read for follow-through review
- bull put readiness: `GET /strategies/bull-put/readiness` performs a read-only opening readiness check across account configuration, runtime controls, entry window, candidate preview, capacity, and next action before any paper order is submitted
- bull put execution lock: previews return a `candidate_token`; execute requests can include that token plus `minimum_net_credit` so a manual submit cannot silently switch to a different spread candidate
- bull put performance visibility: previews include `timing_ms`, and locked execute can reuse the cached candidate while refreshing only the two selected option legs before submission
- bull put runtime state: runtime responses include computed fields such as `holding_open_position`, `daily_entry_cap_reached`, `next_action`, active/open spread counts, and `next_monitor_after`
- strategy experiment ledger: `/strategies/experiment` aggregates strategy proposals, runs, signals, and reviews; `/strategies/controls` exposes paper/live locks, scheduler state, covered-call automation flags, and execution permission boundaries; `/strategies/advisor-context` packages the same local controls, ledger snapshot, covered-call activity, advisor sources, and hard rules for read-only LLM advisor input; `/strategies/advisor/runs` lists persistent advisor dry-run history with token/cache usage, response ids, status, and record timestamps; `/strategies/advisor/audit` returns a local audit snapshot with response payloads, token/cache deltas, downstream proposal/review impact, and paper-first/manual-approval checks; direct list/create routes are available so future strategies and LLM advisors can record plans before execution
- advisor response intake: `POST /strategies/advisor/responses` records external advisor output as paper-only proposals or reviews after loading the local advisor context; it normalizes recognized sources such as `deepseek`, forces proposal `approval_required=true`, adds read-only/manual-approval checks, and does not touch any broker order path
- DeepSeek advisor dry-run: `POST /strategies/advisor/deepseek/dry-run` loads local advisor context, sends it to DeepSeek through the configured client, records a `strategy_advisor_runs` audit row, persists the recordable response payload back onto the run with `advisor_run_id`, and returns `recorded=false`; Record Output writes only local proposals/reviews and marks the same run `recorded`
- DeepSeek advisor client: `scripts\run_regression.py advisor-intake --call-deepseek` uses the local API dry-run route, which reads `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` from `.env` to ask DeepSeek for a structured advisor response; it sends a compact `compact_v1` advisor context that preserves current lifecycle/status facts while omitting bulky candidate, risk, raw, and broker snapshot payloads; it includes `/strategies/advisor/audit` in the local report when available, stays read-only unless `--record` is also supplied, and sending context to DeepSeek should be treated as explicit external data sharing
- strategy audit and permission boundaries: proposal approval/rejection can include an audit actor and note, recorded as `strategy_policy` signals; LLM/advisor-sourced proposals are read-only advice until local deterministic checks and manual approval are present; advisor-sourced proposals must keep `approval_required=true`, cannot be created in live mode, and are audited when recorded; covered-call order entry enforces the policy before any broker call
- market events: `/market-events` stores local earnings, dividend, FOMC, CPI, jobs, and other risk events for strategy filters; `/market-events/import` ingests CSV-shaped batches with duplicate suppression; `/market-events/import/provider` can import normalized FMP earnings and U.S. macro events through the same dedupe path
- covered call proposals: `GET /strategies/covered-call/preview` scans the latest local stock/ETF position snapshot for a covered lot and a liquid OTM call, including upcoming event warnings from `/market-events`; `POST /strategies/covered-call/propose` persists the candidate into the strategy experiment ledger for manual approval and skips duplicate active proposals for the same symbol; `POST /strategies/covered-call/proposals/{proposal_id}/execute` submits a paper covered-call sell order only after that proposal is approved, leaving the proposal approved while the sell order works and marking it executed only after fill; `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile` is read-only with respect to broker mutations and only refreshes/advances already linked orders; a filled roll buyback with no successor sell remains waiting for explicit `roll-continue`; `POST /strategies/covered-call/proposals/{proposal_id}/monitor` gives read-only take-profit / assignment-pressure / expiration-week guidance for executed sell or roll proposals; `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose` records a manual-approval roll proposal with current buyback estimate and next OTM call candidate; `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute` executes an approved roll proposal by submitting buy-to-close first and only submitting sell-to-open when the buyback is already filled; `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue` owns the explicit successor sell action and refreshes any existing sell-to-open id to prevent duplicate roll-open orders; `POST /strategies/covered-call/proposals/{proposal_id}/close` submits a paper buy-to-close limit order for an executed sell or roll proposal; filled close orders mark proposals `closed`, and rolls mark the source proposal `rolled` only after the new short call fill is confirmed
- covered-call Longbridge load shaping: covered-call preview and roll-preview filter the option chain to standard calls inside the configured OTM strike window before requesting option market snapshots, capped to a focused subset, so liquid long chains such as QQQ do not request every call contract in one broker call
- zero-DTE lottery preview-only posture: `GET /strategies/zero-dte-lottery/preview` still evaluates a same-day long call/put candidate for research. Execution, force scan, and enabling auto-order return `409 zero_dte_execution_disabled_pending_lifecycle` and never call the order service. This P0 lock remains until close-before-cutoff, DNE, exercise/assignment, and post-expiry stock-position reconciliation are implemented.
- dashboard experiment bench: `/` now includes a strategy experiment panel that surfaces pending proposals, recent runs, signal feed, and review feed for the selected paper account
- dashboard covered-call activity: `/` now includes a dedicated covered-call activity card backed by `GET /strategies/covered-call/activity`, with proposal counts, open covered-call count, latest monitor action/P&L/premium-capture visibility, pending roll count, close-run count, pending close / roll lifecycle task visibility, a manual lifecycle refresh control, and recent proposal/run history
- dashboard proposal controls: the strategy experiment panel now exposes approve / reject, covered-call execute / monitor / close / roll-propose, and covered-call roll execute / continue actions, with compact proposal payload details, optional execution limit-price overrides, and roll-chain references
- dashboard event calendar: `/` now shows upcoming market events so strategy proposal risk warnings have a visible source
- dashboard snapshot load: `/` now reads a lightweight latest-snapshot summary from `/account-snapshots/latest` instead of pulling the full account snapshot history on each refresh
- Longbridge resilience: broker SDK calls now use a bounded `20s` request timeout plus a short circuit breaker, giving slow background loads room to complete while still failing fast when quote connectivity degrades
- Longbridge market-data session reuse: paper and live modes each own one lazy, single-threaded `QuoteContext`; calls are serialized on the context owner thread, the pending queue is bounded, and account/order SDK work uses a separate executor. This keeps the first connection cost out of subsequent quote/chain calls without sharing a WebSocket context across request threads.
- Longbridge reference-data cache: trading calendars, option expiry dates, option chains, and recent daily bars use a mode-scoped, bounded LRU/TTL cache on the market-data owner thread. Concurrent duplicate reads coalesce behind the first SDK call, and callers receive defensive copies. Ordinary quotes and option snapshots are intentionally uncached so trade-time authorization still reaches Longbridge.
- optional market-data prewarm: `LONGBRIDGE_MARKET_DATA_PREWARM_ENABLED=true` opens the configured paper/live quote session in the background after a short startup delay. `/health` becomes available first; prewarm failure is logged without failing application startup.
- market-data observability: `/ops/market-data-runtime` reports mode-scoped context/cache state and low-cardinality operation metrics for requests, SDK calls, cache hits/misses, successes, failures, timeouts, queue depth, and latency. Reading the endpoint never initializes a broker session. Use `python scripts/run_regression.py market-data-runtime` for a read-only JSON report.
- trade-time quote authorization: Bull Put locked execution refreshes the underlying plus both selected legs; Covered Call open and roll-open refresh the underlying plus the selected call. Cached, stale, mismatched, incomplete, or illiquid evidence fails closed. Preview freshness remains independently configurable for research views.
- scheduler resilience: automatic Longbridge tasks now project per-account/task backoff, next attempt, consecutive failures, and single-flight lease state into `scheduler_task_states`, while preserving append-only observations in `scheduler_job_runs`
- Longbridge circuit isolation: account/order failures and market-data failures now use separate circuit-breaker buckets, so a failed account sync does not automatically block quote-backed dashboard panels
- scheduler safety order: each account cycle reconciles unresolved intents, synchronizes orders, synchronizes account/positions, advances existing strategy lifecycles, and only then evaluates new entries; a failed prerequisite blocks downstream broker mutations
- pre-open board resilience: `/strategies/pre-open-risk` now falls back to the latest stored pre-open run when transient Longbridge failures hit, returns a partial board when only some proxies are unavailable, and degrades to a structured unavailable board when no live or stored pre-open snapshot exists yet
- historical homepage quote behavior: the retired `Quick Quote` panel stopped auto-loading `UNH.US` on first paint. The panel is removed in the research workstation; quote reads now come through the shared research-universe read model.
- pre-open proxy fetch path: the pre-open board now loads its proxy symbols through one batched Longbridge quote request instead of five sequential quote calls, and the dashboard skips slow option overlays by default so fresh macro proxy data can render first
- overlay timeout margin: the homepage now gives `pre-open-risk` slightly more time than the underlying Longbridge fail-fast window, so the first degraded render lands as structured `Unavailable` instead of a client-side `Timed Out`
- dashboard asset versioning: `/` now serves versioned `app.css` and `app.js` URLs so browser tabs pick up the latest frontend after a reload instead of sticking to stale cached static assets
- historical focused dashboard hierarchy: the prior persisted `Focus` / `All` switch is superseded by the five-workspace shell described above. Its old local-storage key is intentionally no longer read or written.

## Regression scripts

The repo includes regression workflows behind a single entrypoint:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
.venv\Scripts\python.exe scripts\run_regression.py bull-put-recovery-drill
.venv\Scripts\python.exe scripts\run_regression.py consistency-report
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit
.venv\Scripts\python.exe scripts\run_regression.py paper-session-gate --session full --strict
.venv\Scripts\python.exe scripts\run_regression.py zero-dte-lottery-drill
.venv\Scripts\python.exe scripts\run_regression.py 60h-completion-audit
.venv\Scripts\python.exe scripts\run_regression.py operator-platform-v8
.venv\Scripts\python.exe scripts\run_regression.py p0-safety
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
.venv\Scripts\python.exe scripts\run_regression.py real-paper
.venv\Scripts\python.exe scripts\run_regression.py real-preopen-board
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper arm
```

Available workflows:

- `bull-put-paper`: runs an in-memory bull put service regression through scheduled scan, spread open, spread close, parameter review, runtime PnL update, and strategy journal writes
- `bull-put-readiness`: runs the read-only bull put opening readiness check against an already running local API session; it defaults to `QQQ.US` so the check avoids scanning the full universe before the open
- `bull-put-real-paper`: hits the local API against the real Longbridge paper account and validates bull put runtime state plus live preview responses without placing option orders unless `--execute` is supplied
- `bull-put-recovery-drill`: reads bull put recover-close eligibility for all listed spreads or a selected `--spread-id`, classifies the operator action, and never submits a recovery order
- `consistency-report`: exports read-only `/ops/consistency` evidence over orders, strategy runs/signals/proposals, bull put spreads, and repair availability; it never applies a repair
- `worktree-release-inventory`: classifies the dirty worktree into reviewable release slices and flags unknown or generated-artifact candidates
- `data-hygiene-audit`: performs a read-only audit of watchlist residue and generated evidence artifacts by default; generated file archival or project-cache cleanup requires explicit `--confirm-generated-cleanup`
- `paper-session-gate`: runs the morning, midday, evening, or full paper operator evidence loop against an already running local API; the full loop includes consistency-report and a preview-only zero-DTE lottery drill by default, and `--strict` fails if consistency evidence is missing or any broker submit / local repair / destructive action is observed
- `zero-dte-lottery-drill`: reads Zero-DTE runtime plus preview evidence for `QQQ.US`; the optional legacy `--force-scan --confirm-paper-scan` pair now verifies the stable `409 zero_dte_execution_disabled_pending_lifecycle` lock and never authorizes or attempts broker submission
- `60h-completion-audit`: audits current JSON evidence against the 60h operator hardening plan and reports `incomplete` while any requirement is missing, weak, or not backed by confirmed/reconciled evidence plus required local recording
- `advisor-intake`: fetches `/strategies/advisor-context` from an already running local API session, can call DeepSeek with `--call-deepseek` through the same `/strategies/advisor/deepseek/dry-run` API path used by the dashboard, includes the local `/strategies/advisor/audit` snapshot when available, and can record a provided or generated advisor response into `/strategies/advisor/responses` only when `--record` is explicitly supplied
- `audit-export`: exports read-only `/ops/audit` and `/ops/audit/summary` evidence from an already running local API session
- `operator-platform-v8`: runs the aggregate local V8 gate and writes `artifacts\operator-platform-v8-manifest.json`; it excludes DeepSeek calls and confirmed zero-DTE force scans by default
- `p0-safety`: runs full pytest, script/JavaScript syntax, Alembic head/current, duplicate-order preflight, an isolated temporary-PostgreSQL concurrency proof, the 18-scenario dashboard safety matrix, consistency evidence, and `git diff --check`; it never enables broker submission, local repair, or destructive actions
- `mock-ui`: starts the in-memory mock dashboard backend and drives a headless browser through the real-time macro board, save-current-board action, stored opening follow-through review card, option-chain analysis, strategy controls, strategy review, spread monitor, filled-order execution summary, journal submit, and submit / replace / cancel without touching the real paper account
- `real-paper`: by default prints a dry-run plan based on the latest quote; add `--execute` to actually send the paper order through the local API
- `real-preopen-board`: drives a headless browser against an already running local dashboard on `127.0.0.1:8000`, clicks `Load Live Macro`, and verifies the response is live fast-path data for the expected U.S. session date instead of a stored fallback
- `real-ui-refresh`: drives a headless browser against an already running local dashboard on `127.0.0.1:8000`, reloads it repeatedly, and reports core dashboard, research-universe table, selected chart, and technical-settled timings. Warm core/table checks retain the 3-second target, warm overlays retain the 7-second target, and warm cached charts use a 2-second target; the first real Longbridge connection is reported as a cold measurement and does not alter any broker safety gate.
- `unattended-paper`: arms, inspects, or resumes the local paper unattended workflow. `arm` disables new Bull Put entries while keeping existing spread monitoring and lifecycle reconciliation under the running FastAPI scheduler; Zero-DTE auto-order cannot be enabled in P0; `status` prints a morning/evening summary covering paper-first controls, Covered Call posture, Bull Put runtime and linked lifecycle orders, executions, journals, and the Zero-DTE execution lock; `resume` re-enables the Bull Put runtime flag while the release kill switch remains authoritative. Optional `--notification-channel dry-run|console|file` emits a local notification payload; file notifications include `run_id` and size-based JSONL rotation; email/push/SMS are reserved but not active.
- `scheduler-on-long-gate`: starts a temporary scheduler-enabled API on an available local port, then runs `real-ui-refresh`, `unattended-paper status --notification-channel dry-run`, `bull-put-real-paper`, and `bull-put-recovery-drill` against the same process; the report includes scheduler lease/backoff evidence

All workflow scripts emit the same JSON envelope shape:

- `script`
- `workflow`
- `status`
- `mode`
- `target`
- `summary`
- `generated_at`
- `payload`

Useful examples:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper --json-output artifacts/bull-put-paper-regression.json
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness --symbol QQQ.US --json-output artifacts/bull-put-readiness.json
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper --json-output artifacts/bull-put-real-paper-dry-run.json
.venv\Scripts\python.exe scripts\run_regression.py bull-put-recovery-drill --json-output artifacts/bull-put-recovery-drill.json
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory --json-output artifacts/worktree-release-inventory.json
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit --json-output artifacts/data-hygiene-audit.json
.venv\Scripts\python.exe scripts\run_regression.py paper-session-gate --session full --json-output artifacts/paper-session-gate.json
.venv\Scripts\python.exe scripts\run_regression.py zero-dte-lottery-drill --json-output artifacts/zero-dte-lottery-drill.json
.venv\Scripts\python.exe scripts\run_regression.py 60h-completion-audit --json-output artifacts/60h-completion-audit.json
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --json-output artifacts/advisor-intake-context.json
.venv\Scripts\python.exe scripts\run_regression.py audit-export --json-output artifacts/audit-export.json
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --call-deepseek --json-output artifacts/deepseek-advisor-dry-run.json
.venv\Scripts\python.exe scripts\run_regression.py mock-ui --json-output artifacts/mock-ui-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-paper --json-output artifacts/real-paper-dry-run.json
.venv\Scripts\python.exe scripts\run_regression.py real-preopen-board --expected-session-date 2026-05-29 --json-output artifacts/real-preopen-board-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --json-output artifacts/real-ui-refresh-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-paper --execute --json-output artifacts/real-paper-executed.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper arm --json-output artifacts/unattended-paper-arm.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --json-output artifacts/unattended-paper-status.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run --json-output artifacts/unattended-paper-status-notify.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel file --notification-file artifacts/unattended-paper-notifications.jsonl --json-output artifacts/unattended-paper-status.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper resume --json-output artifacts/unattended-paper-resume.json
.venv\Scripts\python.exe scripts\run_regression.py scheduler-on-long-gate --iterations 2 --json-output artifacts/scheduler-on-long-gate.json
```

Market events can also be imported from a local CSV. The importer posts one batch to `/market-events/import`, so reruns skip events already present with the same symbol, type, title, and scheduled time.

```powershell
.venv\Scripts\python.exe scripts\import_market_events.py --csv artifacts/market-events.csv
```

To let the background scheduler import the same CSV periodically, set:

```text
MARKET_EVENT_AUTO_IMPORT_ENABLED=true
MARKET_EVENT_IMPORT_CSV_PATH=artifacts/market-events.csv
MARKET_EVENT_IMPORT_INTERVAL_SECONDS=3600
```

Provider-backed import is also available for FMP when `FMP_API_KEY` is configured:

```powershell
.venv\Scripts\python.exe scripts\import_market_events.py --provider fmp --start 2026-06-01 --end 2026-06-30 --symbols UNH.US,QQQ.US
```

To let the background scheduler import provider events periodically, set:

```text
MARKET_EVENT_PROVIDER_AUTO_IMPORT_ENABLED=true
MARKET_EVENT_PROVIDER=fmp
MARKET_EVENT_PROVIDER_SYMBOLS=UNH.US,QQQ.US
MARKET_EVENT_PROVIDER_LOOKAHEAD_DAYS=30
FMP_API_KEY=...
```

DeepSeek advisor calls are optional and disabled unless you run the advisor-intake script with `--call-deepseek` or click the dashboard DeepSeek dry-run control. Apply Alembic migrations before using the formalized advisor history and audit snapshot because run auditing is stored in `strategy_advisor_runs`.

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_TIMEOUT_SECONDS=120
DEEPSEEK_MAX_TOKENS=4096
DEEPSEEK_TEMPERATURE=0.2
```

## Next milestones

1. Stabilize the paper-account strategy loop for `LBPT10087357`: keep the product boundary paper-first, keep covered-call auto-propose disabled unless intentionally creating a new candidate, and use the dashboard plus runtime/activity endpoints to confirm bull put spreads, covered-call lifecycle tasks, zero-DTE runtime state, orders, executions, and journals agree before leaving the app unattended.
2. Exercise the unattended paper workflow end to end for a few real paper sessions: run `scripts\run_regression.py unattended-paper arm` before nights when the local API will remain running, keep the FastAPI scheduler process alive, inspect `unattended-paper status` the next morning for account/order sync, open spread monitoring, lifecycle reconciliation, and zero-DTE switch state, then use `resume` only after deciding bull put auto-entry should be re-enabled.
3. Design and implement the complete Zero-DTE expiration lifecycle (close-before-cutoff, DNE, exercise/assignment, and resulting stock-position reconciliation) before reopening any execution control; until then use Preview only and treat every execute, force-scan, or auto-enable `409` as the expected posture.
4. Confirm every environment has run `alembic upgrade head` so `/strategies/advisor/runs` and `/strategies/advisor/audit` can read the DeepSeek audit table.
5. Use `/strategies/advisor/audit` and the dashboard run history to compare compact-context token usage, cache hit/miss, response payloads, recorded status, and downstream proposal/review impact across approved DeepSeek dry runs before expanding advisor sources.
6. Exercise the local unattended notification adapter with `--notification-channel dry-run` first, then `console` or `file` once the JSONL payload shape is stable. External email/push/SMS delivery remains a future adapter on top of the same payload.

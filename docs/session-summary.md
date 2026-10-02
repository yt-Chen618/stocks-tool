# Session Summary

Last updated: 2026-10-02

## Project

- Name: `stocks-tool`
- Workspace: `C:\Users\dell\OneDrive - Duke University\桌面\stocks-tool`
- Product boundary: local FastAPI + SQLAlchemy paper-first trading workbench for U.S. equities and options.
- Canonical local Longbridge paper account: `LBPT10087357`

## Current Handoff

The durable architecture and runbook content now lives in the focused docs listed below. This file is intentionally a short handoff, not a full historical log.

- Architecture and safety boundary: `docs/architecture.md`
- Runtime startup and operator procedures: `docs/runtime-operations.md`
- Strategy lifecycle invariants: `docs/strategy-lifecycle.md`
- Public route inventory: `docs/api-route-inventory.md`
- Regression matrix: `docs/regression-matrix.md`
- V8 release checklist: `docs/operator-platform-v8-release-checklist.md`
- Release-slice map: `docs/worktree-release-slices.md`
- Optimization backlog: `docs/project-optimization-design.md`

The pre-shrink historical handoff was copied to a local archive outside the repo during the 2026-06-26 cleanup pass.

## Active Runtime Surfaces

- Dashboard: `GET /`
- Alternate dashboard path: `GET /app`
- Swagger: `GET /docs`
- Health: `GET /health`
- Broker/profile/account: `/brokers/*`, `/broker-accounts`, `/account-snapshots*`
- Orders/executions/journals: `/orders*`, `/executions`, `/journals`
- Market events: `/market-events*`
- Research workstation reads: `/research/universe`, `/research/technicals`, `/research/symbols/{symbol}/history`
- Watchlists: `/watchlists*`
- Bull put: `/strategies/bull-put/*`
- Covered call: `/strategies/covered-call/*`
- Zero-DTE lottery: `/strategies/zero-dte-lottery/*`
- Strategy ledger and advisor: `/strategies/experiment`, `/strategies/proposals*`, `/strategies/runs*`, `/strategies/signals*`, `/strategies/reviews*`, `/strategies/advisor*`
- Operator posture and audit: `/ops/unattended-status`, `/ops/scheduler`, `/ops/consistency`, `/ops/audit`, `/ops/audit/summary`, `/ops/trading-intents`, `/ops/trade-actions`, `/ops/reason-codes`

## Local Startup

```powershell
docker compose up -d db
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\alembic.exe upgrade head
$env:RECONCILIATION_SCHEDULER_ENABLED="true"
.venv\Scripts\python.exe -m uvicorn --app-dir src stocks_tool.main:app --reload
```

Open:

- Dashboard: `http://127.0.0.1:8000/`
- Swagger: `http://127.0.0.1:8000/docs`

## Current Implementation State

### 2026-10-02 Repository correctness pass

- Covered Call roll continuation now requires the orders linked to the proposal's latest persisted roll run, queried by proposal instead of a truncated account-wide history. Missing/foreign order IDs, omitted existing successor sell IDs, and wrong contract quantities fail before advancing the lifecycle or submitting another order.
- Unknown-order reconciliation covers the intent's lifetime and reads existing cancel/replace targets by broker order ID. SUBMIT identity checks include order type and time in force. Failed reads, saturated history responses, fingerprint conflicts, and unconfirmed existing mutation targets cannot become zero-match evidence. Later incomplete or contradictory checks invalidate the prior evidence chain.
- Additive migration `20261002_0017` persists history-coverage start/end timestamps. A no-order resolution requires three consecutive complete zero-match checks spanning at least 60 seconds; legacy counts without coverage do not qualify. The local database was backed up, upgraded, and checked: all 25 table row counts were preserved, with zero duplicate external order IDs.
- Imported and refreshed U.S. option orders recover asset type, underlying, expiry, strike, and right from the shared symbol parser.
- Scheduler lease acquisition failures skip work; concurrent first creation rolls back and rereads the committed owner. Working-order detection uses scoped `EXISTS`. Bull Put monitor read failures roll back in the repository, produce FAILED/BACKOFF evidence, release the lease, and prevent subsequent entry; a monitor lease owned by another worker also blocks this worker's entry scan.
- Advisor recording uses one atomic repository command for proposals, reviews, policy signals, audit events, and run state. Matching run retries reuse downstream rows, conflicts are rejected, and legacy review metadata links remain readable. External payloads cannot override local advisor provenance or execution-safety metadata. No non-atomic fallback path remains.
- Research event lookup filters selected symbols plus global events before reading its 30-day window. Watchlist inputs normalize whitespace/case and return 409 for duplicates, including legacy variants. Historical rows remain unchanged; research skips/warns about blank or duplicate legacy symbols.
- Longbridge market-data circuits are isolated by paper/live mode. Running SDK calls that outlive their deadline are quarantined until completion, and mutation timeouts stay unknown. A 1,000-row history response fails closed because the Python SDK does not expose the provider's `has_more` flag.
- Final source tests: `509 passed`. The aggregate P0 gate passed all 22 child checks, including all 18 mock browser scenarios; the final source tests and PostgreSQL proof were repeated after the last backend refinements. The PostgreSQL gate verified one simulated broker call for concurrent order submission, one lease owner in each of five races, one set of Advisor rows for concurrent recording, and complete rollback after an injected database error. Evidence is stored locally under `artifacts/repository-corrections-20261002/`; generated evidence is not source.
- Real read-only UI refresh reached the live-history dependency but failed because the `.com` socket-token endpoint connection was reset. The official `.cn` public endpoint was reachable, but launching the explicitly user-authorized `.cn` validation process was rejected by automatic approval review (`blocked by policy`). This remains a real-market validation gap, not a passing latency result. No `.env` values were changed, no real or paper broker order was submitted, and the entry kill switch remains active.

### 2026-08-10 Research Workstation (current change; validation complete)

- `/` and `/app` now use one fixed five-workspace shell: Research Desk (default), Strategy Lab, Macro & Events, Portfolio, and Operations. The persistent sidebar is 224px wide and collapses to 64px; the top bar keeps selected account, Paper label, data time, global status, language, refresh, and the explicit Execution control visible.
- The prior Focus/All dashboard toggle and `stocks-tool-view-mode` key are retired. Workspace state uses `stocks-tool-workspace`; sidebar state uses `stocks-tool-sidebar-collapsed`; research table/chart selection, filters, sorting, column group, selected symbol, and range use `stocks-tool-research-state`. The language, collapsed-module, and session idempotency storage contracts remain in place.
- Research Desk is a read-only shared symbol context. `GET /research/universe` merges the selected/default watchlist, latest selected-account positions, Bull Put and Zero-DTE configuration pools, and active Bull Put spread state by uppercase symbol, keeping source labels and attaching batch quotes, position values, 30-day events, strategy states, warnings, and `data_quality`. The endpoint refuses more than 50 unique symbols with `422 research_universe_limit_exceeded`; it never silently truncates.
- `GET /research/technicals` accepts repeated and/or comma-separated values, with at most 10 expanded nonblank symbol tokens per request, and returns per-symbol `ok`, `partial`, or `unavailable` outcomes after 66 daily bars. The browser sequences repeated-parameter batches, shows progress, and holds technical-dependent filters disabled until all batches complete. `GET /research/symbols/{symbol}/history?range=3m|6m|1y` returns 66/132/252 OHLCV/turnover bars with point-in-time SMA20/SMA50 and string warning codes.
- Chart view uses the locally committed TradingView Lightweight Charts `5.2.0` standalone bundle in `src/stocks_tool/ui/static/vendor/`, with its license and third-party notice. Runtime chart loading uses no CDN and leaves the library attribution logo enabled.
- Watchlists keep existing create/add APIs and now allow list rename, description/default selection, item-note editing, and confirmed item deletion through `PATCH /watchlists/{watchlist_id}`, `PATCH /watchlists/{watchlist_id}/items/{item_id}`, and `DELETE /watchlists/{watchlist_id}/items/{item_id}`. Whole-list deletion, drag order, and grouping remain out of scope.
- Execution is now an explicit native `dialog` drawer containing Ticket, Orders, Order Detail, and Journal. A research row may prefill the ticket symbol only; side, quantity, type, and price remain explicit. Existing confirmation, idempotency/replay, unknown-outcome locks, paper-first policy, and Zero-DTE Preview Only controls remain authoritative. At `<=780px`, broker-write controls stay disabled while the drawer remains readable.
- The retired Quick Quote surface is no longer rendered. Research universe batch quotes are display/read-model data and never authorize an order; cached or degraded daily-bar data is also not trade authorization evidence.
- Final validation on 2026-08-10 passed: full pytest reported `458 passed`; the normal browser flow and all 18 mock safety/posture scenarios passed with 1440px, 1024px, and 760px captures; `real-ui-refresh --iterations 2` passed against a scheduler-disabled Paper API; and the expanded `p0-safety` gate passed all 22 child checks, including syntax checks for every new browser module and the vendored chart bundle, with broker submission, local repair, and destructive actions disabled. The real refresh measured the cold/warm research table at `13,465ms / 1,351ms`, the selected QQQ chart at `673ms / 19ms`, core readiness at `13,458ms / 1,342ms`, and settled overlays at `14,157ms / 1,374ms`. The cold Longbridge connection is measurement evidence; warm targets and all trading safety gates remain unchanged.

- P0.1/P1 quote authorization and latency work is implemented: Bull Put locked candidates refresh the underlying and both legs before entry; Covered Call open and roll-open refresh the underlying and selected call under a 15-second authorization window. Cached/stale evidence fails closed before an opening order.
- Longbridge market data now uses persistent, mode-scoped, single-owner `QuoteContext` sessions with a bounded queue and a separate executor from account/order work. A 2026-07-11 real read-only check measured about `6.59s` for first connection and `0.52s` for subsequent live quotes in the same session.
- The P0.1/P1 full Python suite passes with 433 tests. After the safe paper-only server was restarted, the aggregate `p0-safety` gate passed all 16 children, including the 18-scenario DOM matrix, temporary-PostgreSQL exact-once proof, migration checks, and all 3 consistency checks with no repairs. No broker order was submitted.
- P2 read-only reference caching is implemented for trading calendars, option expiries, option chains, and daily bars with mode isolation, a 300-second TTL, a 256-entry LRU bound, concurrent request coalescing, and defensive copies. Quotes and option snapshots remain uncached for trade authorization. Optional delayed background prewarm is available and currently used by the safe local runtime.
- The 2026-07-11 P2 real read-only measurement observed expiry `549.72ms -> 0.14ms`, a 183-contract chain `554.79ms -> 1.31ms`, and 60 daily bars `560.63ms -> 0.69ms`. With delayed prewarm enabled, `/health` was available in about `2.45s` and the first user quote completed in about `0.66s` with `data_quality=live`.
- The post-P2 Python suite passes with 437 tests and `scripts\run_regression.py p0-safety` passes all 16 children. Broker submission, local repair, and destructive-action flags were all false during the gate; no order was submitted.
- P3 market-data observability adds `GET /ops/market-data-runtime` and `scripts\run_regression.py market-data-runtime`. It exposes mode/session state and stable per-operation request, SDK-call, cache, success/failure/timeout, queue, and latency metrics without opening a broker connection. The first real read-only report observed 3 successful requests, 3 SDK calls, no failures/timeouts, and no pending work.
- The post-P3 Python suite passes with 440 tests and the aggregate `p0-safety` gate passes all 16 children. The gate kept broker submission, local repair, and destructive actions disabled; no order was submitted.
- Historical (superseded by the 2026-08-10 workstation): the dashboard visual hierarchy defaulted to a persisted Focus view. It reduced the account posture grid from eight cards to four critical cards and hid nine secondary information regions while retaining one-click All view access. The corresponding prior validation evidence remains historical evidence for that UI, not proof of the new workstation.

- P0 trading-safety hardening adds parent trade-action intents with child order intents, API idempotency/replay, atomic order/execution/audit persistence, unknown-outcome reconciliation, Bull Put CAS/state-machine protection, Covered Call share reservation, preview-only Zero-DTE posture, and dashboard mutation guards behind migration `20260711_0016`.
- `scripts\run_regression.py p0-safety` is the aggregate release gate. It may create and drop an isolated temporary PostgreSQL database for concurrency proof, but broker submission, local repairs, and destructive account actions remain disabled.
- Local PostgreSQL was backed up and upgraded to `20260711_0016` on 2026-07-11. The post-migration duplicate-order preflight reported zero duplicates and `head=current` passed.
- The post-migration `p0-safety` release gate passed all 16 child checks: 429 pytest cases, script and dashboard syntax, migration/preflight checks, exact-once temporary-PostgreSQL concurrency, the 18-scenario DOM matrix, read-only consistency, and `git diff --check`.
- No real or paper canary order was authorized or submitted. Keep the entry kill switch active until separate approval is given for a one-contract Bull Put canary.

- V8 operator-platform reliability work is in progress on `main`.
- The worktree is intentionally organized into release slices by `scripts\run_regression.py worktree-release-inventory`.
- `scheduler_task_states` is the DB-backed latest-state projection for scheduler backoff, next attempt, consecutive failures, and single-flight lease evidence.
- `scheduler_job_runs` remains append-only scheduler observation history.
- `/ops/consistency` reports local ledger drift for zero-DTE manual-scan recording, covered-call order linkage, and bull put lifecycle-warning drift.
- `/ops/consistency/repairs/{repair_id}` remains local-only and currently supports guarded zero-DTE ledger repair only.
- Longbridge quote cache fallback is read-only visibility evidence only. Cached quote evidence must not justify paper order submission.
- DeepSeek/advisor output can write local proposals/reviews only after explicit record action and cannot submit broker orders.
- Zero-DTE lottery is Preview only. Execute, force scan, and auto-enable uniformly return `409 zero_dte_execution_disabled_pending_lifecycle` before the order service is called.
- Covered-call auto-propose remains disabled unless intentionally enabled.
- Bull put still coordinates two separate option orders rather than broker-native combo orders.

## Cleanup State

- `.env` secrets must not be printed, copied into chat, or committed.
- Generated evidence under `artifacts/`, browser screenshots under `output/playwright/`, `.playwright-cli/`, cache directories, and transient logs are local evidence, not source.
- The 2026-06-26 cleanup pass removed tracked generated/local files from the Git index and moved stale local evidence to a sibling `stocks-tool-local-archives` directory.
- `scripts\run_regression.py data-hygiene-audit` remains the read-only audit path by default. Generated cleanup requires explicit confirmation flags.

## Verification Gates

Run the smallest relevant gate first, then broaden:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory
.venv\Scripts\python.exe -m pytest -q
node --check src\stocks_tool\ui\static\lifecycle-warning.js
node --check src\stocks_tool\ui\static\api-client.js
node --check src\stocks_tool\ui\static\formatters.js
node --check src\stocks_tool\ui\static\i18n.js
node --check src\stocks_tool\ui\static\state.js
node --check src\stocks_tool\ui\static\app.js
node --check src\stocks_tool\ui\static\execution-drawer.js
node --check src\stocks_tool\ui\static\workspace-shell.js
node --check src\stocks_tool\ui\static\research-view.js
node --check src\stocks_tool\ui\static\chart-view.js
node --check src\stocks_tool\ui\static\watchlist-view.js
node --check src\stocks_tool\ui\static\vendor\lightweight-charts-5.2.0.standalone.production.js
.venv\Scripts\python.exe -m pytest tests\test_research_workspace.py tests\test_watchlist_repository.py tests\test_watchlists_api.py tests\test_ui_dashboard.py -q
.venv\Scripts\python.exe scripts\run_mock_ui_order_regression.py --scenario all --timeout-seconds 30
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --iterations 2
.venv\Scripts\python.exe scripts\run_regression.py consistency-report
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit
.venv\Scripts\python.exe scripts\run_regression.py operator-platform-v8
.venv\Scripts\python.exe scripts\run_regression.py p0-safety
git diff --check
```

Broker-facing gates that call the running local API may warn when `127.0.0.1:8000` is not running or Longbridge is degraded. Treat those as current operator posture, not a reason to weaken safety checks.

## Recommended Next Steps

1. Keep the P0 entry kill switch active until an explicitly approved one-contract paper canary completes entry, reconciliation, and exit with no unknown intent.
2. Keep stabilizing the paper-account strategy loop for `LBPT10087357` before adding new strategy families.
3. Implement the full Zero-DTE expiration lifecycle before reopening any execution surface.
4. Continue reducing oversized modules behind existing facades: dashboard view modules, Bull Put entry/pre-open/review helpers, Covered Call lifecycle helpers, and mock scenario builders.

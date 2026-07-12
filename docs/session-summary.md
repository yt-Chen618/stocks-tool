# Session Summary

Last updated: 2026-07-11

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
- Swagger: `GET /docs`
- Health: `GET /health`
- Broker/profile/account: `/brokers/*`, `/broker-accounts`, `/account-snapshots*`
- Orders/executions/journals: `/orders*`, `/executions`, `/journals`
- Market events: `/market-events*`
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

- P0.1/P1 quote authorization and latency work is implemented: Bull Put locked candidates refresh the underlying and both legs before entry; Covered Call open and roll-open refresh the underlying and selected call under a 15-second authorization window. Cached/stale evidence fails closed before an opening order.
- Longbridge market data now uses persistent, mode-scoped, single-owner `QuoteContext` sessions with a bounded queue and a separate executor from account/order work. A 2026-07-11 real read-only check measured about `6.59s` for first connection and `0.52s` for subsequent live quotes in the same session.
- The P0.1/P1 full Python suite passes with 433 tests. After the safe paper-only server was restarted, the aggregate `p0-safety` gate passed all 16 children, including the 18-scenario DOM matrix, temporary-PostgreSQL exact-once proof, migration checks, and all 3 consistency checks with no repairs. No broker order was submitted.
- P2 read-only reference caching is implemented for trading calendars, option expiries, option chains, and daily bars with mode isolation, a 300-second TTL, a 256-entry LRU bound, concurrent request coalescing, and defensive copies. Quotes and option snapshots remain uncached for trade authorization. Optional delayed background prewarm is available and currently used by the safe local runtime.
- The 2026-07-11 P2 real read-only measurement observed expiry `549.72ms -> 0.14ms`, a 183-contract chain `554.79ms -> 1.31ms`, and 60 daily bars `560.63ms -> 0.69ms`. With delayed prewarm enabled, `/health` was available in about `2.45s` and the first user quote completed in about `0.66s` with `data_quality=live`.
- The post-P2 Python suite passes with 437 tests and `scripts\run_regression.py p0-safety` passes all 16 children. Broker submission, local repair, and destructive-action flags were all false during the gate; no order was submitted.
- P3 market-data observability adds `GET /ops/market-data-runtime` and `scripts\run_regression.py market-data-runtime`. It exposes mode/session state and stable per-operation request, SDK-call, cache, success/failure/timeout, queue, and latency metrics without opening a broker connection. The first real read-only report observed 3 successful requests, 3 SDK calls, no failures/timeouts, and no pending work.
- The post-P3 Python suite passes with 440 tests and the aggregate `p0-safety` gate passes all 16 children. The gate kept broker submission, local repair, and destructive actions disabled; no order was submitted.
- The dashboard visual hierarchy now defaults to a persisted Focus view. It reduces the account posture grid from eight cards to four critical cards and hides nine secondary information regions while retaining one-click All view access. The shell uses a stronger dark trading-desk header, narrower reading width, denser cards/tables, and quieter surfaces; mobile broker-write protection and existing panel collapse state remain intact.
- The focused dashboard change passes the normal browser workflow, mobile read-only assertion, all 18 posture scenarios inside `p0-safety`, 440 Python tests, JavaScript syntax checks, and the complete 16-child safety gate. No broker order was authorized by the validation run.

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
.venv\Scripts\python.exe scripts\run_mock_ui_order_regression.py --scenario all --timeout-seconds 30
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

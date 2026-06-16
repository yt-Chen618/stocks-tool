# Full Project Optimization Design

Last updated: 2026-06-15

## Purpose

This document is the project-wide optimization design for `stocks-tool`. It is based on the current repository state, not only the original architecture notes. The application has moved beyond a skeleton: it now runs a FastAPI + SQLAlchemy trading workbench with Longbridge paper integration, strategy schedulers, a native dashboard, regression scripts, and DeepSeek advisor audit flows.

The goal is to keep the current modular monolith, make the safety-critical strategy loop easier to reason about, and reduce future feature work from large cross-file edits to smaller bounded changes.

## Current Inventory

The important current surfaces are:

- API: FastAPI routes under `src/stocks_tool/api/routes`, with `/` serving the dashboard and `/docs` serving Swagger.
- Data: PostgreSQL via SQLAlchemy and Alembic, with strategy, order, execution, journal, market-event, and advisor audit tables.
- Broker: Longbridge adapter with paper/live mode separation, request timeouts, circuit breakers, quote caching, account sync, order sync, option chain and option quote access.
- Strategies: bull put spread, covered call, zero-DTE lottery, pre-open downside board, strategy experiment ledger, DeepSeek advisor intake/audit.
- Scheduler: in-process reconciliation loop handling account/order sync, bull put monitor/scan/review, pre-open capture/review, covered-call lifecycle, zero-DTE scans, and market-event imports.
- UI: native JavaScript/CSS dashboard at `/`, with strategy, execution, advisor, event, and order workflows.
- Verification: unit/API tests, mock dashboard browser regression, real local dashboard smoke, unattended-paper workflow, real paper dry-run scripts.

Current concentration hotspots:

| Area | File | Lines | Main Risk |
| --- | --- | ---: | --- |
| Dashboard | `src/stocks_tool/ui/static/app.js` | ~5366 | UI state, rendering, actions, i18n, fetch logic all mixed |
| Bull put | `src/stocks_tool/application/services/bull_put_strategy.py` | ~4027 | market data, pre-open board, entry, close, runtime, journaling in one class |
| Covered call | `src/stocks_tool/application/services/covered_call_strategy.py` | ~2119 | proposal, execution, roll, close, lifecycle reconciliation in one class |
| Mock backend | `scripts/mock_dashboard_server.py` | ~1846 | mock behavior can drift from real API behavior |
| Domain schemas | `src/stocks_tool/domain/models.py` | ~1307 | all response/request models share one large namespace |
| Strategy routes | `src/stocks_tool/api/routes/strategies.py` | ~1071 | many strategy families in one router file |
| Strategy experiment service | `src/stocks_tool/application/services/strategy_experiments.py` | ~987 | advisor audit, policy, activity aggregation, generic ledger in one service |
| Unattended script | `scripts/run_unattended_paper.py` | ~906 | validation logic may diverge from API/runtime invariants |

## Design Principles

- Keep FastAPI + SQLAlchemy as the primary stack.
- Keep the dashboard at `/` and Swagger at `/docs`.
- Keep paper-first execution as the default product boundary.
- Treat Longbridge as an external unreliable system: rate limits, transient errors, stale data, and partial fills are normal.
- Model strategy lifecycle states explicitly; avoid hiding lifecycle facts only in `raw_payload`.
- Keep strategy automation deterministic. DeepSeek/advisor output remains read-only until local checks and explicit recording/approval.
- Prefer extracting bounded modules over broad rewrites.
- Every optimization phase must come with regression evidence.

## Target Architecture

The optimized shape is still a modular monolith:

```text
Dashboard (/)
  -> API routers
    -> application use cases
      -> domain engines / lifecycle services
        -> repositories
        -> broker and advisor adapters
        -> scheduler job runner
          -> Postgres
          -> Longbridge / DeepSeek / event providers
```

### Bounded Contexts

The codebase should converge toward these bounded contexts:

| Context | Responsibility | Primary Modules |
| --- | --- | --- |
| Accounts | broker accounts, snapshots, positions, sync state | account snapshots, broker accounts, Longbridge integration |
| Orders | local order intent, remote order sync, execution ledger | orders, executions, order lifecycle helpers |
| Journals | user/system trade notes linked to orders/executions/strategies | journal service and repository |
| Market Data | quotes, option chains, top-of-book, market events | Longbridge market gateway, event ingestion |
| Strategy Runtime | common controls, scheduler state, lifecycle checks, unattended validation | scheduler, controls, lifecycle event model |
| Bull Put | candidate selection, entry, monitor, close, review, pre-open board | bull put modules |
| Covered Call | preview, proposal, execute, monitor, roll, close, lifecycle | covered call modules |
| Zero-DTE Lottery | preview, controlled paper execution, scan runtime | zero-DTE modules |
| Advisor | DeepSeek context, runs, audit, record output | advisor adapter, advisor intake, experiment ledger |
| Dashboard | user-facing workbench and API view models | static modules and API summary endpoints |
| Regression/Ops | scripts, artifacts, smoke checks, unattended status | `scripts/`, `artifacts/`, ops docs |

## Optimization Workstreams

### 1. Canonical Documentation and Runtime Map

Problem: `docs/architecture.md` still describes an early skeleton, while the real app includes broker execution, scheduler, strategy ledger, DeepSeek audit, and the dashboard.

Design:

- Make `docs/session-summary.md` the short handoff only.
- Promote durable architecture into:
  - `docs/architecture.md`
  - `docs/runtime-operations.md`
  - `docs/strategy-lifecycle.md`
  - `docs/regression-matrix.md`
- Add a generated or manually maintained route inventory grouped by bounded context.
- Add a “current safety posture” section for paper/live locks, scheduler flags, DeepSeek sharing, and unattended checks.

Acceptance:

- README, architecture docs, and session summary agree on active routes and startup commands.
- New contributors can identify the canonical source for runtime state, strategy lifecycle, and regression gates.

### 2. API Router Decomposition

Problem: `strategies.py` mixes zero-DTE, covered call, advisor, experiment ledger, pre-open, and bull put routes.

Design:

- Split routes without changing paths:
  - `api/routes/strategy_zero_dte.py`
  - `api/routes/strategy_covered_call.py`
  - `api/routes/strategy_experiment.py`
  - `api/routes/strategy_advisor.py`
  - `api/routes/strategy_pre_open.py`
  - `api/routes/strategy_bull_put.py`
- Keep `main.py` as the only router inclusion point.
- Keep public route paths stable.
- Add route-level tests that assert legacy paths still exist.

Acceptance:

- `pytest` and OpenAPI load pass with unchanged endpoint paths.
- No dashboard URL changes.

### 3. Strategy Lifecycle and Invariants

Problem: lifecycle facts are split across spread/proposal status, linked order ids, broker status, `raw_payload`, unattended scripts, and dashboard inference. The P0 close-order drift was a symptom of this.

Design:

- Introduce a common lifecycle invariant layer:
  - `application/services/strategy_lifecycle.py`
  - pure functions that inspect strategy records + orders + executions and emit invariant results.
- Initial invariant set:
  - bull put open spread with `monitor.should_close=true` must have either a working close order or an explicit manual-action warning.
  - bull put `exit_pending_short` must have a short exit order id.
  - bull put `exit_pending_long` must have filled short exit and linked long exit intent or warning.
  - covered-call executed/roll/close proposals must have consistent linked order state.
  - zero-DTE auto-order must satisfy cap, paper mode, and one-trade-per-session guard.
- Use the same invariant layer from:
  - API summary endpoints
  - scheduler reconciliation
  - unattended-paper script
  - dashboard view models
  - regression tests
- Add a structured `manual_action_required` view model for lifecycle problems.

Acceptance:

- No duplicated string logic for major lifecycle drift checks.
- A new invariant test can fail both API and unattended behavior before implementation.

### 4. Bull Put Service Decomposition

Problem: `BullPutStrategyService` owns candidate scanning, execution, monitoring, pre-open board, journal writing, runtime controls, review generation, option-chain analysis, and lifecycle patching.

Design:

Extract by behavior, keeping the public service as a facade:

- `bull_put/candidate.py`: expiry/leg selection, liquidity filters, candidate token.
- `bull_put/execution.py`: entry order sequencing, repricing ladder, rollback.
- `bull_put/monitor.py`: exit reason, estimated exit debit/PnL, close sequencing.
- `bull_put/runtime.py`: runtime state, entry gating, daily caps, next action.
- `bull_put/pre_open.py`: pre-open proxy signals, option-chain analysis, stored run capture/review.
- `bull_put/review.py`: periodic performance review and journaling.
- `bull_put/lifecycle.py`: spread/order lifecycle diagnostics and manual-action payloads.

The existing `BullPutStrategyService` should remain the injected API dependency and delegate internally.

Acceptance:

- Public behavior unchanged.
- Tests stay green after each extraction slice.
- New files have narrow responsibilities and no direct FastAPI dependencies.

### 5. Covered Call Service Decomposition

Problem: covered-call flow has preview/proposal/open/monitor/roll/close/lifecycle logic in one service, which makes state transitions harder to audit.

Design:

- Split into:
  - candidate selection
  - proposal policy
  - open/close order orchestration
  - roll workflow
  - lifecycle reconciliation
  - activity aggregation
- Share common order-lifecycle helpers with bull put where possible.
- Keep proposal approval as a separate policy boundary.

Acceptance:

- Roll/close/open flows have focused tests with state transition tables.
- Covered-call lifecycle tasks and dashboard activity still match existing API payloads.

### 6. Scheduler Job Model

Problem: scheduler state is in memory. Backoff is useful, but there is no durable job-run history or operator view for why a job ran, skipped, failed, or is backing off.

Design:

- Add a scheduler job abstraction:
  - job key
  - account id
  - due policy
  - run function
  - success/failure classification
  - backoff policy
- Add a `scheduler_job_runs` table or strategy-run-backed equivalent for durable job observations.
- Add `/ops/scheduler` or `/strategies/scheduler-status` to show:
  - last run
  - next due
  - backoff reason
  - failure count
  - last lifecycle warnings
- Keep in-process scheduler for now; do not introduce Celery/Redis worker until there is a real deployment need.

Acceptance:

- Morning unattended status can explain which job changed strategy state and when.
- Backoff/failure state survives app restarts if persisted.

### 7. Broker Gateway Hardening

Problem: Longbridge access is central to account sync, quotes, option chains, order status, and dashboard smoke. The adapter already has timeout/circuit/cache logic, but strategy code still needs broker-aware load shaping.

Design:

- Separate logical gateways:
  - market data gateway
  - order/trade gateway
  - account gateway
- Formalize failure taxonomy:
  - configuration error
  - transient timeout
  - circuit open
  - rate limit
  - stale quote
  - broker rejection
- Add option snapshot batch planners shared by bull put, covered call, zero-DTE, and pre-open analysis.
- Add per-endpoint metrics in JSON regression artifacts: request count, max latency, fallback used, cached quote used.

Acceptance:

- Strategy services do not each reinvent option-chain candidate slicing.
- Dashboard degraded state explains market-data failures without blocking order/risk views.

### 8. Data Model and Query Hygiene

Problem: JSONB raw payloads preserve broker detail, but lifecycle-critical facts need normalized summaries for scanning, dashboard, and unattended checks.

Design:

- Keep raw broker payloads in JSONB.
- Normalize safety-critical derived fields:
  - lifecycle warning code
  - manual action required
  - latest monitor should close
  - latest close order status
  - next monitor after
- Add targeted indexes for high-use queries:
  - orders by account/status/updated_at
  - spreads by account/status/updated_at
  - strategy proposals by account/status/strategy_id
  - strategy runs/signals/reviews by account/created_at
  - market events by scheduled_at/symbol/severity
- Add migration review checklist before any schema change.

Acceptance:

- Dashboard and unattended checks avoid scanning large raw payloads for critical status.
- Raw payload remains available for audit.

### 9. Dashboard Modularization Without New Stack

Problem: `app.js` combines fetch client, state store, rendering, translations, event handlers, strategy workflows, order ticket, and formatting.

Design:

Keep the native dashboard, but split static JS into modules served under `/static`:

- `api-client.js`: fetch wrapper, timeout, error classification.
- `state.js`: selected account, loaded data, mutation helpers.
- `formatters.js`: currency/date/status formatting.
- `i18n.js`: translations and dynamic rules.
- `orders-view.js`
- `bull-put-view.js`
- `covered-call-view.js`
- `zero-dte-view.js`
- `advisor-view.js`
- `pre-open-view.js`
- `dashboard-app.js`: startup and event wiring.

Add small pure view-model helpers:

- lifecycle warning classifier
- order row classifier
- strategy proposal action builder
- pre-open overlay status builder

Acceptance:

- `node --check` still covers all JS modules.
- mock-ui browser flow still passes.
- No React/Vue/build step is introduced unless a later decision explicitly justifies it.

### 10. Dashboard View-Model Endpoints

Problem: the dashboard currently assembles many related API payloads client-side. That makes stale/mismatched state easier when several endpoints return at different moments.

Design:

- Add read-only summary endpoints that do not replace the detailed APIs:
  - `/dashboard/account-summary`
  - `/strategies/bull-put/dashboard`
  - `/strategies/covered-call/dashboard`
  - `/strategies/advisor/dashboard`
  - `/ops/unattended-status`
- These endpoints should use lifecycle invariant helpers and return explicit warnings.
- Keep detailed endpoints for drill-down and actions.

Acceptance:

- Dashboard first paint can render consistent strategy/runtime/order warning state from fewer calls.
- Existing detailed endpoints remain backward compatible.

### 11. Regression Harness Consolidation

Problem: mock server and regression scripts are valuable but contain duplicated data shapes and behavior.

Design:

- Create shared fixtures/builders for:
  - broker account
  - account snapshot
  - orders/executions
  - bull put spread lifecycle states
  - covered-call proposals
  - zero-DTE runtime
- Make mock dashboard states deliberately scenario-based:
  - healthy paper account
  - bull put close-order canceled drift
  - broker degraded market data
  - covered-call lifecycle pending
  - advisor dry-run with recordable response
- Convert critical script validators into importable pure functions with tests.
- Keep `scripts/run_regression.py` as the single user entrypoint.

Acceptance:

- A scenario can be added without editing a 1800-line mock server block.
- Regression artifacts include scenario name and invariant summary.

### 12. Observability and Operator Experience

Problem: current artifacts are useful, but day-to-day operation still relies on manual interpretation across dashboard, scripts, logs, and JSON files.

Design:

- Add an operator status model:
  - paper account posture
  - scheduler posture
  - active positions/spreads
  - lifecycle warnings
  - open orders
  - recent broker failures
  - DeepSeek/advisor last run
  - zero-DTE auto switch
- Surface the same model in:
  - dashboard status strip
  - unattended-paper status
  - JSON artifact
  - optional notification payload
- Add artifact retention guidance:
  - keep latest pass/fail per workflow
  - archive or ignore older generated screenshots/reports
  - avoid checking artifacts into git

Acceptance:

- “Can I leave this running unattended?” has one canonical answer.
- File, dashboard, and script status agree.

### 13. Security and Safety Boundary

Problem: paper-first is implemented, but the surface area is expanding.

Design:

- Keep live mode blocked by environment.
- Add idempotency keys for order-submitting endpoints.
- Add explicit duplicate-order prevention for strategy close/retry paths.
- Never let advisor proposals execute directly.
- Keep `.env` secret non-disclosure rule in docs and tests.
- Add a safety checklist for any new automation:
  - paper mode only by default
  - deterministic local checks
  - daily cap
  - max premium/loss cap
  - manual action path
  - regression scenario
  - unattended invariant

Acceptance:

- Every new strategy automation must include an explicit safety checklist in PR/review notes.

## Phase Plan

### Phase 0: Design Freeze and Documentation Convergence

Deliverables:

- Update `docs/architecture.md` to reflect current reality.
- Add route inventory and runtime topology docs.
- Add a lifecycle invariant catalog.
- Add current regression matrix doc with exact commands.

Gates:

- `pytest -q`
- `node --check` for dashboard JS
- docs mention the real account id `LBPT10087357` where examples need an account.

### Phase 1: No-Behavior-Change Modularization

Deliverables:

- Split `strategies.py` into route modules with unchanged URLs.
- Split dashboard JS into static modules without a build step.
- Extract bull put helper modules behind the existing service facade.
- Extract covered-call helper modules behind the existing service facade.

Gates:

- Full pytest.
- `mock-ui`.
- `real-ui-refresh`.
- OpenAPI loads at `/docs`.

### Phase 2: Lifecycle Invariant Layer

Deliverables:

- Shared invariant service for bull put, covered call, zero-DTE.
- Unattended-paper consumes invariant results instead of owning duplicate logic.
- Dashboard warning state consumes invariant view models.
- Add lifecycle drift scenario fixtures.

Gates:

- Unit tests for each invariant.
- mock-ui scenario for each dashboard warning.
- unattended-paper status validates current real paper posture.

### Phase 3: Scheduler and Operator Status

Deliverables:

- Durable scheduler job-run observations.
- Operator status endpoint.
- Backoff/failure reporting in unattended status and dashboard.
- Artifact retention and status report conventions.

Gates:

- Scheduler tests with success, skip, transient failure, and backoff.
- unattended-paper status artifact shows scheduler posture.

### Phase 4: Broker Gateway and Market-Data Load Shaping

Deliverables:

- Market/order/account gateway separation.
- Shared option snapshot batch planner.
- Broker failure taxonomy and response classification.
- Regression artifacts include broker call timing/fallback summaries.

Gates:

- Longbridge adapter tests.
- strategy preview tests for rate-limit-conscious candidate slicing.
- real-paper dry-run remains non-mutating by default.

### Phase 5: Data Hygiene and Normalized Lifecycle Summaries

Deliverables:

- Normalize lifecycle warning fields where queries need them.
- Add indexes for dashboard and unattended status paths.
- Add migration checklist and backfill scripts where needed.
- Clean local residue after artifact review.

Gates:

- Alembic upgrade succeeds.
- Existing raw payload audit data remains available.
- dashboard and unattended checks still agree.

## Cross-Cutting Acceptance Matrix

Every optimization slice should run the narrowest relevant subset first, then the project gates before being considered done:

```powershell
.venv\Scripts\python.exe -m pytest -q
node --check src\stocks_tool\ui\static\app.js
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --iterations 2
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
```

DeepSeek gates are opt-in because they share local advisor context with an external provider:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --call-deepseek
```

## Priority Backlog

P0:

- Align architecture docs with current runtime.
- Split `strategies.py` by strategy/advisor context without changing routes.
- Extract lifecycle invariant helpers and point unattended/dashboard at them.
- Add operator status model for paper-account readiness.

P1:

- Split bull put service behind existing facade.
- Split covered-call service behind existing facade.
- Modularize dashboard JavaScript.
- Consolidate mock scenario builders.
- Add scheduler job-run observations.

P2:

- Normalize lifecycle summary columns and add indexes.
- Refine broker gateway separation and option snapshot planners.
- Add artifact retention automation.
- Add external notification adapters after local file/console payloads are stable.

## Non-Goals

- Do not enable live autonomous trading as part of this optimization.
- Do not replace FastAPI + SQLAlchemy.
- Do not introduce a second frontend stack unless the native modular dashboard becomes the proven bottleneck.
- Do not route DeepSeek/advisor output into broker order paths.
- Do not remove raw broker payloads; keep them for audit even when adding normalized summaries.

## First Implementation Slice

The safest first coding slice is:

1. Split `api/routes/strategies.py` into subrouters with unchanged paths.
2. Add route inventory tests or OpenAPI path assertions.
3. Keep all service code untouched.
4. Run full pytest and mock-ui.

This reduces router blast radius before deeper lifecycle/service extraction work starts.

## Implementation Status

Implemented on 2026-06-15:

- Phase 0 documentation convergence:
  - refreshed `docs/architecture.md`
  - added `docs/runtime-operations.md`
  - added `docs/strategy-lifecycle.md`
  - added `docs/regression-matrix.md`
  - added `docs/api-route-inventory.md`
- Phase 1 router decomposition:
  - kept `src/stocks_tool/api/routes/strategies.py` as the `/strategies` aggregator
  - moved strategy route groups into `src/stocks_tool/api/routes/strategy_routes/`
  - added OpenAPI route inventory assertions in `tests/test_strategies_api.py`
- Phase 2 first invariant extraction:
  - added `src/stocks_tool/application/services/strategy_lifecycle.py`
  - pointed bull put refresh and unattended status at the shared close-order warning invariant
  - added `tests/test_strategy_lifecycle.py`
- Phase 3 / Phase 10 first operator view:
  - added `src/stocks_tool/application/services/operator_status.py`
  - added `GET /ops/unattended-status`
  - added durable `scheduler_job_runs` observations with migration `20260615_0012`
  - added `GET /ops/scheduler`
  - added `GET /strategies/bull-put/dashboard`
  - added `tests/test_operator_status_api.py`
- Phase 4 / Phase 5 / Phase 7 first shared helpers:
  - added `src/stocks_tool/application/services/option_snapshot_planner.py`
  - covered-call chain snapshot selection now delegates to the shared planner
- Phase 4 bull put first service extraction:
  - added `src/stocks_tool/application/services/bull_put/runtime.py`
  - `BullPutStrategyService` delegates runtime block/next-action/monitor timing helpers to that module
- Phase 5 covered-call first service extraction:
  - added `src/stocks_tool/application/services/covered_call/policy.py`
  - `CoveredCallStrategyService` delegates order-execution policy checks to that module
- Phase 9 first dashboard module:
  - added `src/stocks_tool/ui/static/lifecycle-warning.js`
  - changed `app.js` to consume the shared browser helper for bull put lifecycle warnings
  - added `src/stocks_tool/ui/static/api-client.js`
  - moved the dashboard fetch/timeout wrapper out of `app.js` while keeping the native no-build dashboard
- Phase 5 data hygiene:
  - added normalized bull put lifecycle summary fields to `bull_put_spreads`
  - added migration `20260615_0013` with JSONB backfill for existing monitor/lifecycle payloads
  - added targeted indexes for order, spread, strategy ledger, and market-event query paths
  - wired `BullPutStrategyService`, `SQLAlchemyBullPutSpreadRepository`, operator status, dashboard view models, and `scripts/run_unattended_paper.py` to prefer normalized lifecycle facts with raw-payload fallback
  - added repository, lifecycle, operator, unattended, and strategy tests for normalized lifecycle persistence and warning behavior
- Phase 4 bull put monitor extraction:
  - added `src/stocks_tool/application/services/bull_put/monitor.py`
  - `BullPutStrategyService` now delegates exit debit, PnL, DTE, and exit-reason calculations to that pure module
- Phase 3 scheduler/operator summary:
  - added scheduler job summaries to `/ops/scheduler`
  - added recent scheduler summaries to `/ops/unattended-status`
- Phase 7 broker gateway hardening:
  - added split broker gateway protocols in `src/stocks_tool/ports/broker_gateway.py`
  - added broker failure taxonomy/classification in `src/stocks_tool/application/services/broker_gateway.py`
- Phase 11 regression fixture consolidation:
  - added `scripts/mock_dashboard_fixtures.py`
  - moved common mock account/watchlist/configuration/quote fixtures and helpers out of `scripts/mock_dashboard_server.py`

Continued on 2026-06-16:

- Phase 3 scheduler/operator due-policy summaries:
  - extended `SchedulerJobSummary` with `posture`, `due_status`, `status_detail`, and `last_problem_at`
  - changed unattended scheduler checks to derive pass/warn/fail from grouped scheduler summary posture
  - added tests for backoff, failed, and recovered scheduler summary states
- Phase 4 bull put service extraction:
  - added `src/stocks_tool/application/services/bull_put/candidate.py`
  - `BullPutStrategyService` delegates expiry selection, short-put candidate checks, option-leg liquidity reasons, entry limit price selection, repricing ladders, and mid-price helpers to that module
  - added `src/stocks_tool/application/services/bull_put/calendar.py`
  - `BullPutStrategyService` delegates U.S. options holiday/session/target-open helpers to that module
- Phase 5 covered-call service extraction:
  - added `src/stocks_tool/application/services/covered_call/candidate.py`
  - `CoveredCallStrategyService` delegates candidate metric construction, risk summary, monitor action, proposal confidence, DTE, mid-price, safe percentage, and annualization helpers
  - added `src/stocks_tool/application/services/covered_call/order_lifecycle.py`
  - covered-call open/close/roll order request construction, order consistency validation, filled-state checks, run grouping, decimal parsing, symbol normalization, and reference-time handling now live outside the service facade
- Phase 7 broker gateway hardening:
  - added composite `BrokerIntegrationGateway` and `BrokerGateway` protocols
  - migrated service constructor and broker route type hints from concrete `LongbridgeBrokerAdapter` to market-data/order/account gateway protocols; the concrete adapter remains only in the factory and adapter tests
- Phase 9 dashboard modularization:
  - added `src/stocks_tool/ui/static/formatters.js`
  - moved dashboard currency/date/percentage/quantity formatting helpers out of `app.js`
  - added `src/stocks_tool/ui/static/state.js`
  - moved dashboard initial state and local-language bootstrap into the no-build static module chain

Verified on 2026-06-15:

```powershell
.venv\Scripts\python.exe -m pytest -q
node --check src\stocks_tool\ui\static\app.js
node --check src\stocks_tool\ui\static\api-client.js
node --check src\stocks_tool\ui\static\formatters.js
node --check src\stocks_tool\ui\static\lifecycle-warning.js
node --check src\stocks_tool\ui\static\state.js
.venv\Scripts\python.exe -m py_compile scripts\mock_dashboard_fixtures.py scripts\mock_dashboard_server.py scripts\run_unattended_paper.py
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe current
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --iterations 2
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
git diff --check
```

Latest verification results:

- `253 passed`
- `node --check` passed for `app.js`, `api-client.js`, `formatters.js`, `lifecycle-warning.js`, and `state.js`
- Alembic head: `20260615_0013`
- `mock-ui`, `real-ui-refresh` (dashboard ready `139-835 ms`, overlays settled `159-918 ms`), `unattended-paper status`, and `bull-put-real-paper` passed
- `git diff --check` reported no whitespace errors, only LF/CRLF working-copy warnings

Follow-up refinements:

- Continue optional fine-grained extraction of bull put entry execution, pre-open option-chain analysis, and review/journal orchestration if those areas change again.
- Continue optional fine-grained extraction of covered-call roll orchestration, lifecycle reconciliation, and dashboard activity aggregation if those flows need feature work.
- Add more dashboard view modules such as `orders-view.js`, `bull-put-view.js`, and `covered-call-view.js` only when changing those UI surfaces; the current no-build module chain now covers fetch, lifecycle warnings, formatters, and state.
- Add per-endpoint broker timing summaries to JSON regression artifacts when the regression scripts next need broker-call observability.

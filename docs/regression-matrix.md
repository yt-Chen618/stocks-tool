# Regression Matrix

Last updated: 2026-10-04

Run the smallest relevant test first, then the broader gates before treating an optimization slice as done.

## Resumable Evidence and Fault Limits

P0, V8 and the 18-scenario mock matrix write an atomic `state.json`, append-only `events.jsonl`, and separate stdout/stderr logs under their evidence directory. Reports retain their existing JSON fields and add run/source/environment identity and child-log references. Each scenario still starts its own mock server and fixture state. Long-running checks refresh liveness every 30 seconds; a quiet but live process is not a failed check.

Resume by rerunning the same command with the same evidence directory after inspecting its recorded owner and child PID/start token. An OS lock and process-identity checks reject duplicate owners. Only explicitly cacheable checks with matching source, environment, command and existing logs can reuse a pass. Volatile environment/database/API checks run again. Source changes invalidate old results; a missing final report or interrupted child is never a pass.

Fault timeouts apply per child, not to the campaign: static/environment checks default to 120 seconds, pytest/PostgreSQL/recovery checks to 600 seconds, and the complete mock matrix to 1,800 seconds. Browser wrappers have a separate 300-second default process deadline; real-refresh deadlines also allow the requested iteration count. Browser-step deadlines remain in effect. Owned process trees are checked by PID/start identity before cleanup, including Linux descendants in separate sessions. Mock-server output goes to diagnostic log files, avoiding unconsumed pipes. Cleanup or identity failures require inspection and cannot justify a successful validation claim.

CI runs on PR updates, `main` pushes and manual dispatch, and checks out the exact PR head. Its concurrency group cancels only an older run for the same PR/ref. Uploaded evidence includes P0, history-query, strategy-query, deterministic Bull Put flow and screenshots. A saved workflow, local pass, or previous-head green run does not prove final remote acceptance.

## Professional Workbench Gates

`scripts/run_regression.py workbench-features` drives the real mock DOM through
research selection, save/reload and immutable case capture, comparison, portfolio,
events, Advisor and backtest read surfaces. It checks new-panel account races,
explicit paper activity scope, missing-data explanations and three viewport sizes.
It records zero broker mutations and hashes all served UI assets before/after;
source drift invalidates the run. This gate is included in `p0-safety`.

`scripts/run_regression.py p6-query` uses isolated PostgreSQL for 100k-intent keyset
and fairness evidence, concurrent event deduplication, and legacy duplicate reuse
beyond the first batch. Old records remain untouched; no broker is called.

`scripts/lean_offline_smoke.py` is a separate actual-engine gate. It never pulls an
image, downloads market data or contacts a broker. Provision the pinned official
image first. `BLOCKED_ENV`, fixture simulation, and genuine historical validation
are distinct outcomes. Synthetic data cannot satisfy the multi-year data gate.

The engine matrix includes `--registered-fixture` for native equity and two
explicit option contracts, and `--registered-fixture --partial-fill-fixture` for
limited quote size, fill-forward rejection and incomplete-leg state. Lifecycle
fixtures exercise stock split/dividend accounting and standard option expiry
behavior. Record raw input rows separately from repeated/fill-forward observations;
those observation counts are not independent historical samples. Compare repeat
runs on normalized trades, equity and lifecycle events rather than elapsed time.

Use `--lifecycle-fixture --lifecycle-scenario` with `split_dividend`,
`covered_call_assignment`, or `long_call_exercise` for each actual-engine case.
Split warnings and applied splits are counted separately. Option event counts
also distinguish the contract exercise/assignment from underlying stock delivery.

CI additionally checks the Windows process paths from a Unicode checkout and
runs the actual offline LEAN fixture in an independent Linux job. All artifacts
must match the PR head; a skipped or blocked engine gate is not a passing result.

## Reproducible Environment Gates

Use the repository-owned setup entry point from a clean checkout. It reads `.python-version` and `.node-version`, installs the locked Python environment from `uv.lock`, installs the project-local browser dependency from `package-lock.json`, downloads Chromium into the repository browser cache, and can start the pinned PostgreSQL service:

```powershell
python scripts\setup_environment.py --start-postgres
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe scripts\check_environment.py --strict --json-output artifacts\environment-preflight.json
```

`check_environment.py --strict` is read-only: it does not install packages, start containers, read `.env`, or open a broker connection. It reports tool versions, lock synchronization, local Chromium, PostgreSQL reachability, and Alembic head/current state. A `PLAYWRIGHT_CHROME_PATH` override is diagnostic evidence rather than the reproducible browser runtime. Use `--skip-browser` on setup only when browser gates are intentionally out of scope.

## Local Code Gates

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests\test_research_workspace.py tests\test_watchlist_repository.py tests\test_watchlists_api.py tests\test_ui_dashboard.py -q
.venv\Scripts\python.exe -m pytest tests\test_strategy_audit_event_repository.py tests\test_operator_status_api.py tests\test_bull_put_strategy.py tests\test_strategies_api.py tests\test_strategy_experiments_api.py tests\test_reconciliation_services.py -q
node --check src\stocks_tool\ui\static\app.js
node --check src\stocks_tool\ui\static\api-client.js
node --check src\stocks_tool\ui\static\chart-view.js
node --check src\stocks_tool\ui\static\execution-drawer.js
node --check src\stocks_tool\ui\static\formatters.js
node --check src\stocks_tool\ui\static\i18n.js
node --check src\stocks_tool\ui\static\lifecycle-warning.js
node --check src\stocks_tool\ui\static\research-view.js
node --check src\stocks_tool\ui\static\state.js
node --check src\stocks_tool\ui\static\watchlist-view.js
node --check src\stocks_tool\ui\static\workspace-shell.js
node --check src\stocks_tool\ui\static\vendor\lightweight-charts-5.2.0.standalone.production.js
node --check src\stocks_tool\ui\static\account-loader.js
node --check src\stocks_tool\ui\static\advisor-view.js
node --check src\stocks_tool\ui\static\orders-view.js
node --check src\stocks_tool\ui\static\operations-recovery-view.js
.venv\Scripts\python.exe -m py_compile scripts\setup_environment.py scripts\check_environment.py scripts\browser_runtime.py scripts\run_history_query_regression.py
.venv\Scripts\python.exe -m py_compile scripts\mock_dashboard_fixtures.py scripts\mock_dashboard_server.py scripts\run_mock_ui_order_regression.py scripts\run_unattended_paper.py scripts\run_audit_export_regression.py scripts\run_consistency_report.py scripts\run_bull_put_recovery_drill.py scripts\run_data_hygiene_audit.py scripts\run_paper_session_gate.py scripts\run_worktree_release_inventory.py scripts\run_zero_dte_lottery_drill.py scripts\run_60h_completion_audit.py scripts\run_scheduler_on_long_gate.py scripts\run_operator_platform_v8_gate.py scripts\run_regression.py
.venv\Scripts\python.exe -m alembic heads
.venv\Scripts\python.exe -m alembic current
.venv\Scripts\python.exe scripts\run_regression.py p0-safety --skip-running-api-checks
```

These gates verify Python behavior, API imports, migration-sensitive models used by tests, and dashboard JavaScript syntax.

`p0-safety` starts with the strict environment preflight, then runs the duplicate-external-order preflight, an isolated temporary-PostgreSQL two-request concurrency proof, and the full mock browser safety matrix. Without `--skip-running-api-checks` it also reads `/ops/consistency` from the configured local API. Its manifest fixes `broker_order_submit_allowed=false`, `local_repair_allowed=false`, and `destructive_actions_allowed=false`; the temporary database is created, migrated, tested, and dropped without touching broker state.

Both aggregate gates discover every JavaScript file under `ui/static`, including vendor assets. The temporary PostgreSQL gate also verifies five independent first-lease races and Advisor Record Output from two separate sessions. A database trigger injects a review-insert failure to prove that proposals, reviews, signals, audit records, and advisor-run status roll back together. Unit regressions cover old unresolved intents, incomplete history evidence, option metadata import, proposal-linked roll orders, scheduler acquisition failures, watchlist conflicts, and research events beyond the former global cutoff.

## Bounded Reads and Recovery Gates

Run the focused tests after changing the paged reads, active-spread query, Covered Call decision filters, or recovery read model:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_history_pagination.py tests\test_recovery_status.py tests\test_strategy_query_filters.py tests\test_covered_call_query_boundaries.py tests\test_ui_pagination_contract.py -q
```

The isolated PostgreSQL history gate creates and removes its own temporary database:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py history-query --json-output artifacts\history-query-regression.json
.venv\Scripts\python.exe scripts\run_regression.py strategy-query --json-output artifacts\strategy-query-regression.json
```

The history gate applies current migrations, seeds 10,000 and then 100,000 rows per history table with another account interleaved, and checks 50-row order/execution/journal/Bull Put keyset pages. It verifies account/mode isolation, tied `(created_at, id)` boundaries, no duplicates/omissions, deep cursors after 80,001 account rows at the 100,000-row scale, bounded ORM materialization and actual-query `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` index plans. It also checks old spread details and active/manual-action working records.

The strategy gate uses separate 10,000/100,000 closed-history fixtures. SQL oracles verify global activity/Advisor totals at display limits 1 and 25, latest per-type runs for old active proposals, complete consistency warnings at limit 1, and legacy link repairs without duplicate signals. SQLAlchemy hooks capture the actual SQL and bound parameters for EXPLAIN. ORM-load counters verify active-only lifecycle materialization; weak finalizers measure retained domain objects during full consistency scanning against a fixed 1,200-object ceiling. Broker and mutation attempts are counted and must be zero. `--sizes 100,1000` is a diagnostic pilot, not full-scale acceptance.

Both gates create/drop their own temporary database and report cleanup failure as failure. They make no real broker calls. A failed or interrupted run is retained as evidence and never treated as a pass.

The active-spread route and recovery read model are local read contracts. Targeted tests must keep `GET /strategies/bull-put/spreads` as a complete historical read, verify that `GET /strategies/bull-put/active-spreads` pushes lifecycle status into SQL, and verify that `GET /ops/recovery-status` reports truncation and evidence guidance without reconciliation, local resolution, broker-session initialization, or order submission.

Run the actual recovery-panel interaction gate through the shared entry point:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py recovery-ui
```

It uses the local mock dashboard and real Playwright DOM interactions. Required cases include parent-only unknown actions, totals beyond the displayed page, coverage/check/time evidence, known broker orders, SDK quarantine, clear-to-blocked and error transitions, account and pagination response races, language switching, and desktop/mobile captures. The test requires zero broker mutations. This gate is also a required child of `p0-safety`.

## Operator Posture Gates

Targeted pytest coverage should include:

- `/ops/reason-codes` catalog exposure and `OperatorStatusCheck.reason_detail`
- broker profile resolution through `/brokers/profiles`, including `LBPT10087357` and `paper_guard=config_declared`
- advisor run-card projection through `/strategies/advisor/run-cards`
- paper mandate serialization through `/strategies/controls` and enrichment in `/ops/unattended-status`
- audit event serialization through `/ops/audit`
- durable strategy audit event append/filter behavior through `strategy_audit_events`
- `/ops/audit/summary` aggregation and durable/synthetic dedupe preference
- `/ops/consistency` read-only ledger checks and guarded `/ops/consistency/repairs/{repair_id}` local-only repair
- `/ops/recovery-status` parent/child intent grouping, coverage evidence, truncation, next-action guidance, and SDK quarantine read-only behavior
- scheduler nonblocking behavior while `run_once` blocks, plus DB-backed task-state lease/backoff projection
- bull put recover-close eligibility, accept/reject paths, and API route mapping
- advisor playbook registry through `/strategies/advisor/playbooks`
- operator posture consistency across profile, scheduler summary, manual action warning, advisor last run, and audit summary fields

## Dashboard Gates

```powershell
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
.venv\Scripts\python.exe scripts\run_mock_ui_order_regression.py --scenario all
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --iterations 2
.venv\Scripts\python.exe scripts\run_regression.py scheduler-on-long-gate --iterations 2
```

- `mock-ui` drives the dashboard against the in-memory mock backend and should cover strategy controls, macro board, spread monitor, execution summary, journals, and order actions.
- `mock-ui` now seeds `/brokers/profiles`, `/ops/unattended-status`, `/ops/audit`, `/ops/consistency`, and `/strategies/advisor/run-cards`, then asserts the dashboard operator strip renders Broker Profile, Scheduler Posture, Paper Mandate, Ledger Consistency, Manual Actions, and Advisor Last Run.
- `run_mock_ui_order_regression.py --scenario all` runs 18 independent DOM-assertion scenarios: `normal`, `degraded-broker`, `paused-mandate`, `advisor-pending-record`, `manual-action-required`, `scheduler-backoff`, `recover-eligible`, `recover-rejected`, `recover-already-working`, `ledger-mismatch`, `repair-available`, `quote-cache-fallback`, `scheduler-lease-active`, `auxiliary-data-failure`, `core-data-failure`, `covered-call-data-failure`, `accounts-data-failure`, and `unknown-intent`.
- `real-ui-refresh` reloads the real local dashboard on `127.0.0.1:8000` and measures core readiness separately from the research table and selected chart. It gates warm core/table readiness at 3 seconds, warm overlays at 7 seconds, and a warm cached chart at 2 seconds while reporting the first cold Longbridge connection as measurement evidence; sequential technical completion remains a separate settled metric and broker safety gates are unchanged.
- `scheduler-on-long-gate` starts a temporary scheduler-enabled API on an available local port, then runs `real-ui-refresh`, `unattended-paper status --notification-channel dry-run`, `bull-put-real-paper`, and `bull-put-recovery-drill` against the same process. Its manifest includes scheduler summary and lease/backoff evidence from `/ops/unattended-status`.

### Research workstation coverage

For the 2026-08-10 workstation change, cover the following before treating the UI slice as complete:

- API and service tests: universe source merge/deduplication, 50-symbol overflow, no account/default watchlist, technical formulas, short history, and one-symbol daily-bar failure without losing the rest of the batch; watchlist rename/default/description, note edit, and item removal.
- Browser behavior: screener filters/sort/column groups, table/chart selected-symbol synchronization, chart range persistence, watchlist edits and stale-data retention, native drawer focus/Escape behavior, and the symbol-only research-to-ticket prefill boundary.
- Safety behavior: confirmation cancellation, idempotency replay, double-click exact-once submit, unknown-outcome lock, Zero-DTE Preview Only, and broker-write disablement at `<=780px` while read-only drawer review remains available.
- Capture the current shell at 1440px, 1024px, and 760px in the mock browser workflow. The existing 18-scenario posture matrix remains required, along with `real-ui-refresh` and `p0-safety`; do not weaken either gate for degraded Longbridge conditions.

## Paper Strategy Gates

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
.venv\Scripts\python.exe scripts\run_regression.py bull-put-recovery-drill
.venv\Scripts\python.exe scripts\run_regression.py zero-dte-lottery-drill
.venv\Scripts\python.exe scripts\run_regression.py consistency-report
.venv\Scripts\python.exe scripts\run_regression.py paper-session-gate --session full --strict
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run
.venv\Scripts\python.exe scripts\run_regression.py audit-export
.venv\Scripts\python.exe scripts\run_regression.py 60h-completion-audit
.venv\Scripts\python.exe scripts\run_regression.py operator-platform-v8
```

- `bull-put-paper` is the in-memory service regression.
- `bull-put-readiness` checks opening posture without submitting orders.
- `bull-put-real-paper` talks to the local API and real Longbridge paper account without placing option orders unless explicitly requested.
- `bull-put-recovery-drill` reads recover-close eligibility for listed or selected spreads and emits operator action evidence without submitting recovery orders.
- `zero-dte-lottery-drill` reads runtime plus preview evidence. The legacy `--force-scan --confirm-paper-scan` pair verifies that the mutation-shaped endpoint returns the stable lifecycle-disabled `409`; it never authorizes, attempts, or reconciles a new broker order.
- `consistency-report` exports `/ops/consistency` evidence and never applies a local repair.
- `paper-session-gate` composes the morning, midday, evening, or full read-only operator evidence loop, including consistency evidence and the preview-only zero-DTE drill in the midday phase. `--strict` fails if consistency evidence is missing or if any child reports broker order submission, local repair execution, or destructive action. The session manifest lists child artifact paths, status counts, broker-submit flags, local-repair flags, and destructive-action flags.
- `unattended-paper status` verifies paper-first controls, linked order/lifecycle state, executions, journals, zero-DTE guard state, and notification payload shape. File notifications include `run_id` and rotate JSONL output by size.
- `audit-export` writes read-only `/ops/audit` plus `/ops/audit/summary` evidence.
- `operator-platform-v8` aggregates full pytest, script compile, dashboard syntax, Alembic head/current, release inventory, mock UI scenarios, strict paper-session gate, audit export, consistency report, and `git diff --check` into `artifacts/operator-platform-v8-manifest.json`. It does not call DeepSeek or authorize Zero-DTE execution.
- `60h-completion-audit` is a legacy pre-P0 evidence checklist and may remain `incomplete`; its historical force-scan item is intentionally superseded by the P0 Zero-DTE lifecycle lock.

## Worktree and Hygiene Gates

```powershell
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit
```

- `worktree-release-inventory` classifies dirty paths into release slices and flags unknown/generated candidates before staging.
- `data-hygiene-audit` reads watchlists and local evidence directories, identifies duplicates/test residue, reports stale artifacts, stale Playwright screenshots, and stale JSONL notifications, and emits cleanup notes without deleting anything by default. Generated file cleanup is available only with explicit confirmation flags such as `--archive-stale-generated --confirm-generated-cleanup` or `--cleanup-project-caches --confirm-generated-cleanup`.
- `market-data-runtime` exports `/health` plus `/ops/market-data-runtime`, summarizes requests, SDK calls, cache hits/misses, failures, timeouts, pending work, and maximum latency, and performs no broker mutation or local repair.

## Advisor Gate

```powershell
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --call-deepseek
```

The DeepSeek call sends compact local advisor context to an external provider. Use it only when that external data sharing is intended. Recording output still requires `--record`.

## Evidence

Add `--json-output artifacts\<name>.json` when a run should leave local evidence. Generated artifacts should stay local unless a fixture intentionally depends on them.

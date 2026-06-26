# Regression Matrix

Last updated: 2026-06-16

Run the smallest relevant test first, then the broader gates before treating an optimization slice as done.

## Local Code Gates

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests\test_strategy_audit_event_repository.py tests\test_operator_status_api.py tests\test_bull_put_strategy.py tests\test_strategies_api.py tests\test_strategy_experiments_api.py tests\test_reconciliation_services.py -q
node --check src\stocks_tool\ui\static\app.js
node --check src\stocks_tool\ui\static\api-client.js
node --check src\stocks_tool\ui\static\formatters.js
node --check src\stocks_tool\ui\static\i18n.js
node --check src\stocks_tool\ui\static\lifecycle-warning.js
node --check src\stocks_tool\ui\static\state.js
.venv\Scripts\python.exe -m py_compile scripts\mock_dashboard_fixtures.py scripts\mock_dashboard_server.py scripts\run_mock_ui_order_regression.py scripts\run_unattended_paper.py scripts\run_audit_export_regression.py scripts\run_consistency_report.py scripts\run_bull_put_recovery_drill.py scripts\run_data_hygiene_audit.py scripts\run_paper_session_gate.py scripts\run_worktree_release_inventory.py scripts\run_zero_dte_lottery_drill.py scripts\run_60h_completion_audit.py scripts\run_scheduler_on_long_gate.py scripts\run_operator_platform_v8_gate.py scripts\run_regression.py
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe current
```

These gates verify Python behavior, API imports, migration-sensitive models used by tests, and dashboard JavaScript syntax.

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
- `run_mock_ui_order_regression.py --scenario all` runs independent evidence for `normal`, `degraded-broker`, `paused-mandate`, `advisor-pending-record`, `manual-action-required`, `scheduler-backoff`, `recover-eligible`, `recover-rejected`, `recover-already-working`, `ledger-mismatch`, `repair-available`, `quote-cache-fallback`, and `scheduler-lease-active`.
- `real-ui-refresh` reloads the real local dashboard on `127.0.0.1:8000` and checks that first paint and overlay settling remain usable.
- `scheduler-on-long-gate` starts a temporary scheduler-enabled API on an available local port, then runs `real-ui-refresh`, `unattended-paper status --notification-channel dry-run`, `bull-put-real-paper`, and `bull-put-recovery-drill` against the same process. Its manifest includes scheduler summary and lease/backoff evidence from `/ops/unattended-status`.

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
- `zero-dte-lottery-drill` reads runtime plus preview evidence and is preview-only by default; force scan is allowed only with both `--force-scan` and `--confirm-paper-scan`. If a confirmed force scan already produced a same-session paper manual-scan order but the scan response failed, the drill may reconcile that existing local order only when the order remark, underlying, paper mode, buy-option side, and premium cap all match. Missing local strategy run/signal rows are repaired only when `--record-reconciled-ledger` is supplied; this repair writes local ledger rows and does not submit broker orders.
- `consistency-report` exports `/ops/consistency` evidence and never applies a local repair.
- `paper-session-gate` composes the morning, midday, evening, or full read-only operator evidence loop, including consistency evidence and the preview-only zero-DTE drill in the midday phase. `--strict` fails if consistency evidence is missing or if any child reports broker order submission, local repair execution, or destructive action. The session manifest lists child artifact paths, status counts, broker-submit flags, local-repair flags, and destructive-action flags.
- `unattended-paper status` verifies paper-first controls, linked order/lifecycle state, executions, journals, zero-DTE guard state, and notification payload shape. File notifications include `run_id` and rotate JSONL output by size.
- `audit-export` writes read-only `/ops/audit` plus `/ops/audit/summary` evidence.
- `operator-platform-v8` aggregates full pytest, script compile, dashboard syntax, Alembic head/current, release inventory, mock UI scenarios, strict paper-session gate, audit export, consistency report, and `git diff --check` into `artifacts/operator-platform-v8-manifest.json`. It does not call DeepSeek and does not run confirmed zero-DTE force scan by default.
- `60h-completion-audit` checks the current evidence against the long 60h plan and should remain `incomplete` until every requirement, including confirmed or reconciled manual-only force-scan evidence plus strategy run/signal recording, is truly proven.

## Worktree and Hygiene Gates

```powershell
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit
```

- `worktree-release-inventory` classifies dirty paths into release slices and flags unknown/generated candidates before staging.
- `data-hygiene-audit` reads watchlists and local evidence directories, identifies duplicates/test residue, reports stale artifacts, stale Playwright screenshots, and stale JSONL notifications, and emits cleanup notes without deleting anything by default. Generated file cleanup is available only with explicit confirmation flags such as `--archive-stale-generated --confirm-generated-cleanup` or `--cleanup-project-caches --confirm-generated-cleanup`.

## Advisor Gate

```powershell
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --call-deepseek
```

The DeepSeek call sends compact local advisor context to an external provider. Use it only when that external data sharing is intended. Recording output still requires `--record`.

## Evidence

Add `--json-output artifacts\<name>.json` when a run should leave local evidence. Generated artifacts should stay local unless a fixture intentionally depends on them.

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
node --check src\stocks_tool\ui\static\lifecycle-warning.js
node --check src\stocks_tool\ui\static\state.js
.venv\Scripts\python.exe -m py_compile scripts\mock_dashboard_fixtures.py scripts\mock_dashboard_server.py scripts\run_mock_ui_order_regression.py scripts\run_unattended_paper.py scripts\run_audit_export_regression.py scripts\run_scheduler_on_long_gate.py
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe current
```

These gates verify Python behavior, API imports, migration-sensitive models used by tests, and dashboard JavaScript syntax.

## Operator Posture Gates

Targeted pytest coverage should include:

- broker profile resolution through `/brokers/profiles`, including `LBPT10087357` and `paper_guard=config_declared`
- advisor run-card projection through `/strategies/advisor/run-cards`
- paper mandate serialization through `/strategies/controls` and enrichment in `/ops/unattended-status`
- audit event serialization through `/ops/audit`
- durable strategy audit event append/filter behavior through `strategy_audit_events`
- `/ops/audit/summary` aggregation and durable/synthetic dedupe preference
- scheduler nonblocking behavior while `run_once` blocks
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
- `mock-ui` now seeds `/brokers/profiles`, `/ops/unattended-status`, `/ops/audit`, and `/strategies/advisor/run-cards`, then asserts the dashboard operator strip renders Broker Profile, Scheduler Posture, Paper Mandate, Manual Actions, and Advisor Last Run.
- `run_mock_ui_order_regression.py --scenario all` runs independent evidence for `normal`, `degraded-broker`, `paused-mandate`, `advisor-pending-record`, `manual-action-required`, `scheduler-backoff`, `recover-eligible`, `recover-rejected`, and `recover-already-working`.
- `real-ui-refresh` reloads the real local dashboard on `127.0.0.1:8000` and checks that first paint and overlay settling remain usable.
- `scheduler-on-long-gate` starts a temporary scheduler-enabled API on an available local port, then runs `real-ui-refresh`, `unattended-paper status --notification-channel dry-run`, and `bull-put-real-paper` against the same process.

## Paper Strategy Gates

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run
.venv\Scripts\python.exe scripts\run_regression.py audit-export
```

- `bull-put-paper` is the in-memory service regression.
- `bull-put-readiness` checks opening posture without submitting orders.
- `bull-put-real-paper` talks to the local API and real Longbridge paper account without placing option orders unless explicitly requested.
- `unattended-paper status` verifies paper-first controls, linked order/lifecycle state, executions, journals, zero-DTE guard state, and notification payload shape.
- `audit-export` writes read-only `/ops/audit` plus `/ops/audit/summary` evidence.

## Advisor Gate

```powershell
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --call-deepseek
```

The DeepSeek call sends compact local advisor context to an external provider. Use it only when that external data sharing is intended. Recording output still requires `--record`.

## Evidence

Add `--json-output artifacts\<name>.json` when a run should leave local evidence. Generated artifacts should stay local unless a fixture intentionally depends on them.

# Worktree Release Slices

Last updated: 2026-06-16

This repository currently carries a large V2/V3 operator-platform worktree. Review it as coherent slices instead of as one undifferentiated diff.

## Slice 0: Generated Cleanup

- Tracked local/generated files such as `.playwright-cli/`, `debug.log`, `output/`, and local editor helper output should be removed from the Git index when they appear in the worktree.
- Generated evidence stays in `artifacts/` or `output/` and can be archived outside the repo with the confirmed `data-hygiene-audit` cleanup flags.

Review focus:

- generated files are deleted from the index rather than staged as source
- cleanup reports preserve current release evidence before archival
- no database rows or strategy ledgers are deleted as part of source cleanup

## Slice A: Database, Repositories, and Broker Boundary

- Alembic migrations through `20260616_0014` add scheduler job-run and strategy audit durability.
- SQLAlchemy models/repositories add scheduler and strategy audit persistence.
- Broker gateway protocols keep application services dependent on capability interfaces while the concrete Longbridge adapter stays at dependency construction.

Review focus:

- migrations are forward-only and idempotent against the current local DB
- repository serialization preserves enum/date/JSON fields
- Longbridge paper account id remains `LBPT10087357`

## Slice B: Operator Status, Audit, and Scheduler Posture

- `/ops/unattended-status`, `/ops/scheduler`, `/ops/consistency`, `/ops/audit`, and `/ops/audit/summary` provide the canonical operator explanation layer.
- Operator checks now use reason codes plus reason details from a backend catalog.
- Scheduler backoff is expected to degrade posture to `warn` without blocking FastAPI request handling.

Review focus:

- reason codes are stable across API, dashboard, and unattended CLI evidence
- audit events remain explanation records and do not replace orders, executions, journals, scheduler runs, or strategy records
- durable and synthetic audit events dedupe consistently
- consistency repair remains explicit, paper/local-only, and never submits broker orders

## Slice C: Strategy Workflow Hardening

- Bull put spread lifecycle includes normalized monitor/close fields and paper-only recover-close eligibility/action.
- Covered call lifecycle remains proposal-first with manual approval and optional reconcile/monitor paths.
- Zero-DTE lottery remains a controlled paper drill: preview, confirmed force scan, paper execution, and explicit auto-order switch.
- Advisor playbooks and run cards are static, read-only, and proposal/review-only.

Review focus:

- no live recovery or autonomous live trading path appears
- advisor output cannot submit, cancel, replace, or recover broker orders
- zero-DTE auto-execute remains disabled unless explicitly armed

## Slice D: Dashboard, Mock, and Regression Evidence

- Native dashboard remains the only frontend stack.
- Mock scenarios cover normal, degraded broker, paused mandate, advisor pending record, manual action required, scheduler backoff, and recover-close drill cases.
- Regression scripts share the JSON envelope and keep full generated evidence under `artifacts/`; V8 adds `consistency-report`, strict `paper-session-gate`, and `operator-platform-v8`.

Review focus:

- dashboard renders operator posture from API read models instead of duplicating business decisions
- recovery form stays disabled until eligibility is true
- generated screenshots/logs/JSON reports remain local evidence, not source files

## Slice E: Docs and Tests

- Runtime, architecture, regression matrix, route inventory, roadmap, and session summary describe the current operator platform.
- Unit/API tests cover profile, mandate, audit, scheduler, recovery, advisor, zero-DTE, and dashboard route inventory.

Review focus:

- docs match implemented routes and scripts
- full pytest, static JS checks, py_compile, Alembic head/current, mock UI, scheduler-on gate, audit export, and `git diff --check` remain green

## Release Checklist

Run before staging a review slice:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m py_compile scripts\mock_dashboard_fixtures.py scripts\mock_dashboard_server.py scripts\run_mock_ui_order_regression.py scripts\run_unattended_paper.py scripts\run_audit_export_regression.py scripts\run_bull_put_recovery_drill.py scripts\run_data_hygiene_audit.py scripts\run_paper_session_gate.py scripts\run_worktree_release_inventory.py scripts\run_zero_dte_lottery_drill.py scripts\run_60h_completion_audit.py scripts\run_scheduler_on_long_gate.py scripts\run_regression.py
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory --json-output artifacts\worktree-release-inventory.json
node --check src\stocks_tool\ui\static\app.js
node --check src\stocks_tool\ui\static\state.js
node --check src\stocks_tool\ui\static\api-client.js
node --check src\stocks_tool\ui\static\formatters.js
node --check src\stocks_tool\ui\static\i18n.js
node --check src\stocks_tool\ui\static\lifecycle-warning.js
node --check scripts\mock_ui_browser_flow.js
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe current
.venv\Scripts\python.exe scripts\run_mock_ui_order_regression.py --scenario all --timeout-seconds 30
.venv\Scripts\python.exe scripts\run_regression.py scheduler-on-long-gate --iterations 2 --json-output artifacts\scheduler-on-long-gate.json
.venv\Scripts\python.exe scripts\run_regression.py audit-export --json-output artifacts\audit-export.json
.venv\Scripts\python.exe scripts\run_regression.py zero-dte-lottery-drill --json-output artifacts\zero-dte-lottery-drill.json
.venv\Scripts\python.exe scripts\run_regression.py 60h-completion-audit --json-output artifacts\60h-completion-audit.json
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit --json-output artifacts\data-hygiene-audit.json
git diff --check
```

Do not stage `artifacts/`, `output/playwright/`, `.playwright-cli`, transient logs, or local screenshots unless a fixture intentionally depends on them.

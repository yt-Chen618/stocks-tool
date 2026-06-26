# Operator Platform V8 Release Checklist

Last updated: 2026-06-18

This checklist freezes the current paper-first operator-platform work into reviewable slices. Generated artifacts under `artifacts/`, `output/playwright/`, cache folders, and local notification logs are evidence only and should not be staged as source.

## Review Slices

1. `operator_status_audit_scheduler`
   - `/ops/unattended-status`, `/ops/scheduler`, `/ops/audit`, `/ops/audit/summary`, `/ops/consistency`
   - reason-code catalog, durable/synthetic audit behavior, consistency summary, local repair guards
   - DB-backed `scheduler_task_states` projection plus scheduler summary fields for lease/backoff evidence

2. `strategy_workflow_hardening`
   - zero-DTE manual-scan ledger consistency and local-only repair
   - covered-call order-linkage consistency warning
   - bull put close-order lifecycle warning drift report
   - existing paper-only recover-close and zero-DTE force-scan guards remain unchanged

3. `dashboard_mock_regression`
   - native dashboard Operator Console band with Ledger Consistency
   - mock scenarios: `ledger-mismatch`, `repair-available`, `quote-cache-fallback`, `scheduler-lease-active`
   - `consistency-report`, strict `paper-session-gate`, scheduler-on lease evidence, notification rotation, and `operator-platform-v8` aggregate gate

4. `docs_tests`
   - route inventory, runtime operations, regression matrix, V8 checklist, session summary
   - focused unit/API/script tests for consistency report, guarded repair, durable scheduler state, quote fallback metadata, strict session gate, retention report, and scenario matrix

## Acceptance Commands

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m py_compile scripts\run_consistency_report.py scripts\run_paper_session_gate.py scripts\run_operator_platform_v8_gate.py scripts\mock_dashboard_server.py scripts\run_mock_ui_order_regression.py src\stocks_tool\application\services\operator_consistency.py
.venv\Scripts\python.exe -m py_compile scripts\run_unattended_paper.py scripts\run_data_hygiene_audit.py scripts\run_scheduler_on_long_gate.py src\stocks_tool\application\services\reconciliation.py src\stocks_tool\repositories\sqlalchemy_scheduler_job_run_repository.py
node --check src\stocks_tool\ui\static\lifecycle-warning.js
node --check src\stocks_tool\ui\static\api-client.js
node --check src\stocks_tool\ui\static\formatters.js
node --check src\stocks_tool\ui\static\i18n.js
node --check src\stocks_tool\ui\static\state.js
node --check src\stocks_tool\ui\static\app.js
.venv\Scripts\alembic.exe heads
.venv\Scripts\alembic.exe current
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory
.venv\Scripts\python.exe scripts\run_regression.py mock-ui --scenario all
.venv\Scripts\python.exe scripts\run_regression.py paper-session-gate --session full --strict
.venv\Scripts\python.exe scripts\run_regression.py audit-export
.venv\Scripts\python.exe scripts\run_regression.py consistency-report
git diff --check
```

`operator-platform-v8` can run the same broad gate and write `artifacts\operator-platform-v8-manifest.json` when a local API is already running:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py operator-platform-v8
```

## Guardrails

- canonical paper account remains `LBPT10087357`
- no live autonomous trading
- no React/Vite or second service stack
- no MCP/Vibe runtime dependency
- no broker submission in default V8 gates
- no confirmed zero-DTE force scan in routine gates
- local repair requires explicit confirmation and never talks to Longbridge
- file notifications are local-only JSONL with run-id grouping and size-based rotation; external email/push/SMS remains out of scope
- orders, executions, journals, strategy audit events, advisor runs, scheduler runs, and scheduler task states are never cleaned by hygiene scripts

## Known Local DB Notes

- Existing V7 zero-DTE paper force-scan evidence was repaired through local strategy run/signal rows; V8 consistency should now report that as recorded when the same rows remain present.
- Longbridge transient timeout/backoff is acceptable only as `warn` posture when dashboard/API responsiveness remains healthy.
- Apply migration `20260618_0015` before relying on DB-backed scheduler task-state lease/backoff summaries.
- Covered-call and bull put consistency warnings are report-only in V8; no local repair is implemented for those checks in this slice.

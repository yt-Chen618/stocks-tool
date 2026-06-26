# Session Summary

Last updated: 2026-06-26

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
- Operator posture and audit: `/ops/unattended-status`, `/ops/scheduler`, `/ops/consistency`, `/ops/audit`, `/ops/audit/summary`, `/ops/reason-codes`

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

- V8 operator-platform reliability work is in progress on `main`.
- The worktree is intentionally organized into release slices by `scripts\run_regression.py worktree-release-inventory`.
- `scheduler_task_states` is the DB-backed latest-state projection for scheduler backoff, next attempt, consecutive failures, and single-flight lease evidence.
- `scheduler_job_runs` remains append-only scheduler observation history.
- `/ops/consistency` reports local ledger drift for zero-DTE manual-scan recording, covered-call order linkage, and bull put lifecycle-warning drift.
- `/ops/consistency/repairs/{repair_id}` remains local-only and currently supports guarded zero-DTE ledger repair only.
- Longbridge quote cache fallback is read-only visibility evidence only. Cached quote evidence must not justify paper order submission.
- DeepSeek/advisor output can write local proposals/reviews only after explicit record action and cannot submit broker orders.
- Zero-DTE lottery remains paper-only, one contract, one trade per account/session, `$150` premium cap, and disabled unless explicitly armed.
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
git diff --check
```

Broker-facing gates that call the running local API may warn when `127.0.0.1:8000` is not running or Longbridge is degraded. Treat those as current operator posture, not a reason to weaken safety checks.

## Recommended Next Steps

1. Finish V8 slice review in this order: `operator_status_audit_scheduler`, `strategy_workflow_hardening`, `dashboard_mock_regression`, `docs_tests`.
2. Keep stabilizing the paper-account strategy loop for `LBPT10087357` before adding new strategy families.
3. Continue reducing oversized modules behind existing facades: dashboard view modules, bull put entry/pre-open/review helpers, covered-call lifecycle helpers, and mock scenario builders.
4. Keep external email/push/SMS notification delivery out of scope until local dry-run/console/file notification payloads have stayed stable across multiple paper sessions.

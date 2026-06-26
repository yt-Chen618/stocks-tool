# Operator Platform V4 Runbook

Last updated: 2026-06-16

This runbook is for the local paper-first operator workflow around Longbridge paper account `LBPT10087357`. It does not enable live autonomous trading.

## Before Leaving the API Unattended

1. Start the API and keep the process alive.

```powershell
uvicorn --app-dir src stocks_tool.main:app --reload
```

2. Confirm DB migrations and source checks are healthy.

```powershell
.venv\Scripts\alembic.exe current
.venv\Scripts\python.exe -m pytest -q
```

3. Check operator posture with local notification dry-run.

```powershell
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run --json-output artifacts\unattended-paper-status.json
```

4. Run the scheduler-on long gate when validating a real unattended session.

```powershell
.venv\Scripts\python.exe scripts\run_regression.py scheduler-on-long-gate --iterations 2 --json-output artifacts\scheduler-on-long-gate.json
```

5. Classify the current dirty tree before staging or handing off a review.

```powershell
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory --json-output artifacts\worktree-release-inventory.json
```

Acceptance:

- dashboard refresh remains within target
- `event_loop_stall_detected=false`
- Longbridge transient failures appear as `warn` posture, not request timeouts
- zero-DTE auto-order remains off unless explicitly armed

## Morning / Midday / Evening Paper Session Loop

Morning:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run --json-output artifacts\morning-unattended-status.json
.venv\Scripts\python.exe scripts\run_regression.py consistency-report --json-output artifacts\morning-consistency-report.json
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper --json-output artifacts\morning-bull-put-real-paper.json
```

Midday:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness --symbol QQQ.US --json-output artifacts\midday-bull-put-readiness.json
.venv\Scripts\python.exe scripts\run_regression.py zero-dte-lottery-drill --json-output artifacts\midday-zero-dte-lottery-drill.json
.venv\Scripts\python.exe scripts\run_regression.py bull-put-recovery-drill --json-output artifacts\midday-bull-put-recovery-drill.json
```

Evening:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py audit-export --json-output artifacts\evening-audit-export.json
.venv\Scripts\python.exe scripts\run_regression.py consistency-report --json-output artifacts\evening-consistency-report.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run --json-output artifacts\evening-unattended-status.json
```

The same loop can be run as one read-only gate against an already running API:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py paper-session-gate --session full --strict --json-output artifacts\paper-session-gate.json
```

Use `unattended-paper arm` only when intentionally disabling new bull put entries while leaving existing spread monitoring and lifecycle reconciliation active. Use `resume` only after deciding auto-entry should be restored.

## When Longbridge Backoff Appears

Treat Longbridge connectivity backoff as acceptable only when:

- `/` remains responsive
- `/ops/unattended-status` returns `status=warn`, not `fail`
- reason code includes `scheduler_backoff` or another explicit degraded-broker code
- `scheduler-on-long-gate` reports `event_loop_stall_detected=false`

Do not manually retry broker-heavy workflows in a tight loop. Let the scheduler backoff window expire, then rerun `unattended-paper status` or `audit-export`.

## When Consistency Report Fails

Start read-only:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py consistency-report --json-output artifacts\consistency-report.json
```

If `/ops/consistency` returns `repair_available=true`, inspect the related order/proposal/spread ids first. The only guarded repair currently implemented is zero-DTE manual-scan ledger repair:

```powershell
POST /ops/consistency/repairs/zero-dte-ledger:{order_id}
```

The request must include `mode=paper`, `confirm_local_repair=true`, `actor`, and `note`. This repair creates missing local strategy run/signal rows only; it never submits broker orders and never deletes history.

## When Scheduler Lease Is Active

Treat `lease_status=active` in scheduler summaries as single-flight evidence. Wait until `lease_expires_at` before launching another broker-heavy manual gate for the same account/task. If `next_attempt_source=lease` persists across process restarts, inspect scheduler job-run evidence before retrying.

## When Quote Cache Fallback Is Used

`quote_cache_fallback` is acceptable only for read-only dashboard, readiness, or preview rendering. Do not submit paper orders from cached quote evidence. Order submission paths must refresh live broker data and pass their existing strategy-specific guards.

## When Bull Put Recover-Close Becomes Eligible

Always inspect eligibility first:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-recovery-drill --spread-id f9956612-218a-4b20-94f7-66ce556a202c --json-output artifacts\recover-drill.json
```

Manual recovery is allowed only when eligibility says:

- `eligible=true`
- latest monitor still requires close
- old short close order is canceled, rejected, or expired
- no working replacement order exists
- account is `LBPT10087357`
- mode is `paper`

The drill script never calls `POST /recover-close`. The dashboard form and API action still require `confirm_paper_order=true`, actor, note, and max debit. Do not recover a spread whose latest monitor says `should_close=false`.

## When Advisor Output Is Pending Record

Advisor dry-runs are read-only until explicitly recorded.

Use:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --json-output artifacts\advisor-context.json
```

Use `--call-deepseek` only when external data sharing is intentional. Record Output only writes local proposal/review rows and marks the matching advisor run recorded. Advisor proposals must keep `approval_required=true` and cannot submit, cancel, replace, or recover broker orders.

## When a Zero-DTE Paper Drill Is Requested

Keep zero-DTE as a controlled paper drill:

- preview first
- use `scripts\run_regression.py zero-dte-lottery-drill` for the default preview-only evidence path
- use force scan only for explicit manual validation with both `--force-scan` and `--confirm-paper-scan`
- keep `auto_execute_enabled=false` unless intentionally testing the switch
- require `confirm_paper_order=true` for execution
- preserve the `$150` premium cap and one-trade-per-session guard

Do not treat zero-DTE as stable unattended automation until repeated paper sessions prove the posture and evidence are reliable.

## Data Hygiene and Cleanup Policy

Do not delete rows or artifacts during operator checks.

Known local cleanup candidates:

- duplicate/test watchlists such as duplicate `core-us` rows or a `string` test watchlist
- old JSON reports under `artifacts/`
- old screenshots under `output/playwright/`
- transient `.playwright-cli` dumps and local debug logs

Generate a read-only cleanup report with:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit --json-output artifacts\data-hygiene-audit.json
```

Before cleanup, preserve the latest useful pass/fail evidence for scheduler-on gate, audit export, unattended status, mock UI, and any manual recovery drill. Never delete orders, executions, journals, strategy audit rows, advisor runs, or scheduler job runs as part of cosmetic cleanup.

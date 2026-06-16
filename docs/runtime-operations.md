# Runtime Operations

Last updated: 2026-06-16

## Local Startup

```powershell
docker compose up -d db
.venv\Scripts\python.exe -m pip install -e .[dev]
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\uvicorn.exe --app-dir src stocks_tool.main:app --reload
```

Open:

- Dashboard: `http://127.0.0.1:8000/`
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

The canonical local paper account id is `LBPT10087357`.

## Runtime Components

| Component | Runtime Role | Operator Notes |
| --- | --- | --- |
| FastAPI app | serves dashboard, API, Swagger | one process is enough for local paper workflows |
| PostgreSQL | stores accounts, orders, executions, journals, strategies, advisor audit | apply Alembic migrations before smoke testing |
| Longbridge adapter | paper/live account, order, quote, option-chain integration | treat timeouts and circuit-open responses as normal degraded states |
| In-process scheduler | reconciles broker/account/order/strategy state | keep the API process running for unattended paper monitoring |
| Scheduler job runs | durable observations for automatic task success, skip, failure, and backoff | query `/ops/scheduler` after migrations are applied |
| DeepSeek advisor client | optional dry-run advisor response generation | use only when external context sharing is intended |
| Broker profile | Longbridge capability, credential, and paper guard posture | query `/brokers/profiles`; paper guard is `config_declared` |
| Operator audit | durable plus synthetic explanation events over strategy, advisor, scheduler, order, and manual recovery observations | query `/ops/audit`; use as an explanation layer, not as the order ledger |
| Regression scripts | smoke and unattended workflows | write JSON reports to `artifacts/` when preserving evidence |

## Scheduler Posture

The scheduler is currently in-process. It handles:

- Longbridge paper account snapshots and order sync.
- Bull put spread monitoring and close lifecycle reconciliation.
- Bull put entry scans only when runtime controls allow them.
- Bull put periodic review generation.
- Covered-call pending lifecycle reconciliation.
- Zero-DTE lottery scans only when the paper auto-order switch is armed.
- Market-event provider imports where configured.

The scheduler runs Longbridge/DB reconciliation through the in-process scheduler without introducing Celery, Redis, or a second service. The scheduler loop dispatches blocking `run_once` work off the FastAPI event loop, so API/dashboard requests should not wait behind broker sync calls. If the API process stops, scheduler state that is only in memory stops with it. Durable strategy, order, execution, journal, scheduler job-run, audit, and advisor records remain in the database.

Recent scheduler job observations are stored in `scheduler_job_runs` after migration `20260615_0012` is applied. They record job key, account id, status, started/completed timestamps, backoff state, failure count, and error detail. Use `GET /ops/scheduler?external_account_id=LBPT10087357` or the `recent_scheduler_runs` field in `GET /ops/unattended-status` to explain what the scheduler most recently did. Both endpoints also expose scheduler summaries grouped by job/account so the latest status, recent problem count, consecutive failures, backoff window, and next attempt can be read without manually scanning every run row. The summary fields `posture`, `due_status`, `status_detail`, and `last_problem_at` are derived from the grouped run window and are the canonical operator-facing explanation for healthy, recovered, failed, and backoff scheduler states.

## Broker Profile and Paper Mandate

Use `GET /brokers/profiles` to inspect the current profile list. The Longbridge profile is intentionally narrow:

- `external_account_id`: `LBPT10087357`
- `mode`: `paper`
- `paper_guard`: `config_declared`
- `credential_status`: `ready`, `missing_paper_credentials`, or another non-secret local posture string

The paper guard is a local policy statement. It means the app selected paper mode and the configured paper token path; it does not mean the Longbridge API returned a structured proof of paper/live status.

Use `GET /strategies/controls?external_account_id=LBPT10087357` for the static paper mandate and `GET /ops/unattended-status?external_account_id=LBPT10087357&mode=paper` for the enriched operator mandate. The operator snapshot adds runtime `manual_pause`, `kill_switch`, active lifecycle warnings, recent scheduler summaries, audit summaries, and `operator_posture_reason`.

`PaperMandate` and `OperatorStatusCheck` also expose optional `reason_codes` / `reason_code` and `severity` fields. These are the canonical short explanations used by the dashboard and `scripts\run_unattended_paper.py` for states such as `manual_pause`, `kill_switch`, `scheduler_backoff`, `manual_action_required`, `advisor_pending_record`, and broker degradation.

## Lifecycle Data Hygiene

Bull put lifecycle summaries are normalized in `bull_put_spreads` after migration `20260615_0013` is applied:

- `lifecycle_warning_code`
- `manual_action_required`
- `latest_monitor_should_close`
- `latest_close_order_status`
- `next_monitor_after`

The raw JSONB payload remains available for audit. Operator status, bull put dashboard snapshots, and `scripts\run_unattended_paper.py` prefer these normalized fields and fall back to `raw_payload.monitor` / `raw_payload.lifecycle` for older records.

Manual close recovery is available only through `POST /strategies/bull-put/spreads/{spread_id}/recover-close`. It is paper-only and requires:

- `mode=paper`
- `confirm_paper_order=true`
- matching `external_account_id`
- latest monitor `should_close=true`
- an existing short close order that is canceled, rejected, or expired
- no working replacement close order

The endpoint submits a replacement buy-to-close for the short leg and then uses the existing long-leg close flow if the replacement fills. Success and rejection paths append durable audit events. It does not recover a spread when the current latest monitor says `should_close=false`.

Use `GET /strategies/bull-put/spreads/{spread_id}/recover-close/eligibility?external_account_id=LBPT10087357&mode=paper` before submitting a recovery order. It is a pure local read over spread/order state and returns whether recovery is eligible, rejection reason codes, the old short close order status, any working replacement order id, and the latest monitor debit hint. The dashboard consumes this endpoint and keeps the manual recovery form disabled until the read model says recovery is eligible.

## Operator Checks

Use these read-only checks before leaving the local process running:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --iterations 2
.venv\Scripts\python.exe scripts\run_regression.py scheduler-on-long-gate --iterations 2
```

Use `unattended-paper arm` to disable new bull put entries while leaving existing spread monitoring and lifecycle reconciliation active. Use `resume` only after intentionally restoring auto-entry posture.

## Advisor Run Cards and Audit

Use `GET /strategies/advisor/run-cards?external_account_id=LBPT10087357&source=deepseek` for the dashboard-friendly advisor trace. A run-card summarizes provider/model, context format/hash, token usage, output counts, recorded state, downstream proposal/review ids, and warnings. Advisor output still cannot submit broker orders and still requires an explicit record action plus deterministic checks and manual approval.

Use `GET /strategies/advisor/playbooks` to inspect static advisor playbooks. The current registry is `bull_put_v1`, `covered_call_v1`, and `zero_dte_lottery_v1`. These are static task boundaries, not a dynamic user-writeable skill system.

Use `GET /ops/audit?external_account_id=LBPT10087357` to inspect recent explanation events. The endpoint supports `mode`, `source`, `strategy`, `action`, `warning_only`, `since`, and `limit` filters. Events include `event_origin=durable|synthetic`; durable rows are stored in `strategy_audit_events`, while synthetic events preserve older projections from existing ledgers. The unattended paper script also includes `/ops/unattended-status`, `/ops/audit`, and `/brokers/profiles` in its local report so the CLI and dashboard explain the same operator posture. The audit endpoint composes:

- durable proposal approval/reject and advisor record/proposal record events
- durable paper order submit/refresh/cancel events
- durable scheduler lifecycle advance events
- durable bull put recover-close submit/reject/complete events
- synthetic strategy policy signals, advisor run observations, scheduler job runs, and local order observations for compatibility

Audit events explain what happened across modules. They do not replace the canonical orders, executions, journals, scheduler job runs, or strategy records.

Use `GET /ops/audit/summary?external_account_id=LBPT10087357&mode=paper` or `scripts\run_regression.py audit-export` for grouped evidence. The summary groups events by account, mode, source, action, strategy, warning code, and event origin, and reports the latest event timestamp for each group.

## External Data Boundary

Longbridge calls can submit paper orders through guarded routes and scripts. DeepSeek calls are optional and read-only; they receive compact local advisor context and return recordable local proposals/reviews. Do not include `.env` secrets in logs, chat, or artifacts.

Broker-facing code now has split gateway protocols for market data, orders, account/profile access, and composite integration use cases under `src\stocks_tool\ports\broker_gateway.py`. Application services depend on those protocols instead of the concrete Longbridge adapter; the concrete adapter is constructed at the FastAPI dependency boundary. Longbridge-specific exceptions can be mapped into a common failure taxonomy through `classify_broker_exception()` for configuration, dependency, timeout, circuit-open, rate-limit, stale-quote, broker-rejection, transient, and unknown failures.

## Artifact Guidance

Generated screenshots and JSON reports belong under `artifacts/` or `output/`. Keep the latest useful pass/fail evidence locally, but do not treat generated artifacts as source unless a test fixture explicitly needs them.

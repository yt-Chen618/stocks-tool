# Runtime Operations

Last updated: 2026-10-02

## Local Startup

```powershell
python scripts\setup_environment.py --start-postgres
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe scripts\check_environment.py --strict --json-output artifacts\environment-preflight.json
.venv\Scripts\uvicorn.exe --app-dir src stocks_tool.main:app --reload
```

`setup_environment.py` is the clean-checkout entry point. It enforces the versions in `.python-version` and `.node-version`, installs the locked Python dependencies from `uv.lock`, installs the project-local Playwright dependency from `package-lock.json`, downloads Chromium into `.playwright-browsers`, and starts the PostgreSQL image pinned in `compose.yaml`. `check_environment.py --strict` is read-only: it reports tool versions, lock synchronization, browser availability, PostgreSQL reachability, and Alembic head/current without installing packages, starting containers, reading `.env`, or opening a broker connection. For an existing environment, use `uv sync --locked --extra dev` rather than refreshing the lock implicitly.

Open:

- Dashboard: `http://127.0.0.1:8000/`
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

The canonical local paper account id is `LBPT10087357`.

Dashboard mutation keys remain in session storage and are scoped to account and action. Known unknown outcomes also retain their intent identity across reloads. The loader clears those locks only after an exact ID/account/mode detail read confirms `persisted`, `rejected`, or `resolved_no_order`; missing rows, truncated lists and failed reads do not authorize clearing. A legacy unscoped key is migrated only when its stored account/signature proves ownership. Ambiguous legacy keys remain preserved and block a new key for that action until reviewed. A normal pending key alone is not a synthetic unknown intent.

## P0 Migration and Release Procedure

Keep `ALLOW_LIVE_TRADING=false` throughout the release. Before migration, stop the API/scheduler, activate the Bull Put entry kill switch, back up PostgreSQL, and run the duplicate external-order preflight:

```powershell
$stamp = Get-Date -Format yyyyMMdd-HHmmss
New-Item -ItemType Directory -Force artifacts | Out-Null
docker exec stocks-tool-postgres pg_dump -U postgres -Fc -f /tmp/stocks_tool_pre_p0.dump stocks_tool
docker cp stocks-tool-postgres:/tmp/stocks_tool_pre_p0.dump "artifacts\stocks_tool_pre_p0_$stamp.dump"
$env:ALLOW_LIVE_TRADING = "false"
$env:BULL_PUT_STRATEGY__ENTRY_KILL_SWITCH_ACTIVE = "true"
$env:RECONCILIATION_SCHEDULER_ENABLED = "false"
.venv\Scripts\python.exe scripts\check_order_external_id_duplicates.py
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe scripts\check_alembic_head_current.py
```

Migration `20261002_0018` adds the bounded-history keyset indexes for orders, executions, and journals, Covered Call proposal/run decision-scope indexes, and the active Bull Put spread scope index. The next revision, `20261002_0019`, adds the Bull Put `(external_account_id, execution_mode, created_at, id)` history index. Both are additive and preserve all historical migrations and rows. Apply `alembic upgrade head` before using the query paths; head/current equality is schema evidence, not a substitute for regression gates.

Validate upgrades in an isolated database first. Back up the local database before applying them, then compare business-table row counts and sorted complete-row digests. The October 2 campaign verified unchanged contents of all 24 business tables around `0019`; its dump and comparison remain local under the campaign artifact directory. For recovery, retain that backup and investigate in a separate restored database. Do not restore over the operator database or remove historical migrations as an automatic rollback.

Then run mock/fault/concurrency verification and a read-only account consistency check. The aggregate command is:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py p0-safety
```

The gate never authorizes a broker submit. Do not send even a paper order without a separate user approval. If approval is later granted, limit the canary to one Bull Put contract and keep the kill switch active until the complete entry, intent reconciliation, and exit loop has no unknown state.

For rollback, stop the app and scheduler first. Preserve migration `20260711_0016` tables/columns and the intent history; do not downgrade or run an older build with broker writes enabled. An older application may be used only in read-only mode while the application rollback is investigated.

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
- Zero-DTE lottery remains preview-only; scheduler and manual execution paths cannot be armed in P0.
- Market-event provider imports where configured.

The scheduler runs Longbridge/DB reconciliation through the in-process scheduler without introducing Celery, Redis, or a second service. The scheduler loop dispatches blocking `run_once` work off the FastAPI event loop, so API/dashboard requests should not wait behind broker sync calls. Durable strategy, order, execution, journal, scheduler job-run, scheduler task-state, audit, and advisor records remain in the database.

Recent scheduler job observations are stored in `scheduler_job_runs` after migration `20260615_0012` is applied. They record job key, account id, status, started/completed timestamps, backoff state, failure count, and error detail. Migration `20260618_0015` adds `scheduler_task_states`, a latest-state projection for per-account/task backoff, next attempt, consecutive failures, and single-flight lease ownership. Use `GET /ops/scheduler?external_account_id=LBPT10087357` or the `recent_scheduler_runs` / `recent_scheduler_summaries` fields in `GET /ops/unattended-status` to explain what the scheduler most recently did. Both endpoints merge run history with task state so the latest status, recent problem count, consecutive failures, backoff window, next attempt, `lease_status`, `lease_expires_at`, and `next_attempt_source` can be read without manually scanning every run row. The summary fields `posture`, `due_status`, `status_detail`, and `last_problem_at` are the canonical operator-facing explanation for healthy, recovered, failed, backoff, and lease-active scheduler states.

## Broker Profile and Paper Mandate

Use `GET /brokers/profiles` to inspect the current profile list. The Longbridge profile is intentionally narrow:

- `external_account_id`: `LBPT10087357`
- `mode`: `paper`
- `paper_guard`: `config_declared`
- `credential_status`: `ready`, `missing_paper_credentials`, or another non-secret local posture string

The paper guard is a local policy statement. It means the app selected paper mode and the configured paper token path; it does not mean the Longbridge API returned a structured proof of paper/live status.

Use `GET /strategies/controls?external_account_id=LBPT10087357` for the static paper mandate and `GET /ops/unattended-status?external_account_id=LBPT10087357&mode=paper` for the enriched operator mandate. The operator snapshot adds runtime `manual_pause`, `kill_switch`, active lifecycle warnings, recent scheduler summaries, audit summaries, consistency summaries, `primary_blocker`, `local_repair_available`, `latest_evidence_at`, and `operator_posture_reason`.

`PaperMandate` and `OperatorStatusCheck` also expose optional `reason_codes` / `reason_code`, `reason_detail`, and `severity` fields. The backend reason-code catalog is the canonical short explanation source used by the dashboard and `scripts\run_unattended_paper.py` for states such as `manual_pause`, `kill_switch`, `scheduler_backoff`, `manual_action_required`, `advisor_pending_record`, and broker degradation. Use `GET /ops/reason-codes` to inspect that catalog directly.

## Lifecycle Data Hygiene

Apply migration `20261002_0017` before running the corrected order-reconciliation code. It adds nullable history-coverage timestamps to `order_intents`; it does not delete or rewrite order history. Back up the database before upgrading. A rollback to older application code must keep these additive columns, because removing them also removes the new reconciliation evidence.

Unknown-order reconciliation requests history from the earliest unresolved intent's creation time through the current check and reads known cancel/replace targets by their exact broker order ID. A manual `resolve-no-order` requires three consecutive complete zero-match checks over at least 60 seconds with persisted coverage of the intent. Historical counts without coverage evidence do not qualify: the first new complete check starts a fresh count. Failed/incomplete reads or contradictory broker identity evidence invalidate the previous zero-match chain.

The [Longbridge history-orders API](https://open.longbridge.com/docs/trade/order/history_orders) returns at most 1,000 orders per query. The current Python SDK returns only an order list, without `has_more`; a response at that cap is therefore rejected as incomplete, and the intent remains unresolved. Do not bypass this guard by resolving from a truncated list.

If an SDK operation times out after its worker has started, its outcome is not known. The adapter temporarily rejects further account/order SDK work until that worker finishes, while paper/live market-data circuits remain independent. Do not retry a timed-out mutation with a new idempotency key. Reconcile its original intent when the SDK becomes available again; an indefinitely blocked native call requires operator investigation and a controlled process restart, not automatic replacement threads or resubmission.

Covered-call roll continuation requires the order IDs linked to the latest roll run for that proposal. If a successor sell already exists, supply that ID; omitting it does not authorize a second sell. Wrong proposal linkage or contract quantity is rejected before advancing the lifecycle.

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

Use `scripts\run_regression.py bull-put-recovery-drill` for a read-only recovery drill report. The script inspects all listed spreads or a selected `--spread-id`, classifies the operator action, and never calls `POST /recover-close`.

## Bounded History and Recovery Reads

The dashboard uses the bounded history routes for account activity:

- `GET /orders/paged` accepts `external_account_id`, optional `status`, `mode`, and `symbol`, plus `limit=1..100` (default `50`) and an opaque `cursor`.
- `GET /executions/paged` accepts `external_account_id`, optional `order_id`, `limit`, and `cursor`.
- `GET /journals/paged` accepts `external_account_id`, optional `order_id`, `trade_plan_id`, `entry_type`, `limit`, and `cursor`.

Each returns `items`, `next_cursor`, `has_more`, and `limit`. The cursor is a keyset position over `(created_at, id)` and is bound to the complete filter scope. Reusing it with another account or filter is rejected. The legacy `/orders`, `/executions`, and `/journals` routes remain complete reads for explicit history and reconciliation; do not replace a complete-history decision with a page response.

`GET /strategies/bull-put/active-spreads?external_account_id=LBPT10087357&mode=paper` pushes the active lifecycle-status predicate into PostgreSQL and accepts an optional `symbol`. It is a read-only strategy/dashboard view. `GET /strategies/bull-put/spreads` remains the complete historical route, and the active view must not be used for order capacity or lifecycle decisions.

The Bull Put dashboard uses `/working-spreads` for current or manual-action records and loads `/spreads/paged` only when history is opened. History uses account/mode-bound cursors and 25-row UI pages. ID-detail reads retain old and just-completed results even when a record leaves the working set. Recovery eligibility is loaded only when that spread's recovery disclosure is opened; it is not preloaded for every historical row.

`GET /ops/recovery-status?external_account_id=LBPT10087357&mode=paper&limit=100` composes local unresolved parent/child intent evidence with the SDK timeout-quarantine read model. It reports total versus displayed counts, `truncated`, coverage start/end, count and time evidence, reason codes, next actions, and whether recovery is blocked. The endpoint does not reconcile, resolve, submit, or initialize a Longbridge context. Treat `truncated=true` or unavailable quarantine state as incomplete operator evidence.

Migration `20261002_0018` adds the query indexes supporting these paths: account/time/id keysets for orders, executions, and journals; decision-scope indexes for strategy proposals and runs; and the account/mode/status/symbol scope for active Bull Put spreads. The migration is additive and does not alter the legacy complete-read contract.

## Ledger Consistency and Local Repair

Use `GET /ops/consistency?external_account_id=LBPT10087357&mode=paper` or `scripts\run_regression.py consistency-report` to inspect read-only consistency evidence. The report currently checks:

- zero-DTE manual-scan paper orders that are missing local `strategy_runs` or `strategy_signals`
- covered-call executed/closed/rolled proposals without observable local order linkage
- bull put close-order lifecycle warning drift versus linked order state

The report's `total_*` fields and `coverage_complete` are the authority for overall posture. Legacy counts describe the displayed checks; `limit` never restricts the global judgement. A warning outside the visible window remains a warning. Metadata from old runs/signals is processed in bounded batches, including older valid links when a newer run has none.

Consistency repair is explicit and local-only. `POST /ops/consistency/repairs/{repair_id}` currently supports guarded zero-DTE manual-scan ledger repair only. It requires `mode=paper`, `confirm_local_repair=true`, `actor`, and `note`; it creates missing local strategy run/signal records and never submits broker orders or deletes history. A report may expose `repair_available=true`, but operators should still inspect the related order id before applying a repair.

## Operator Checks

Use these read-only checks before leaving the local process running:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
.venv\Scripts\python.exe scripts\run_regression.py bull-put-recovery-drill
.venv\Scripts\python.exe scripts\run_regression.py consistency-report
.venv\Scripts\python.exe scripts\run_regression.py zero-dte-lottery-drill
.venv\Scripts\python.exe scripts\run_regression.py paper-session-gate --session full --strict
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --iterations 2
.venv\Scripts\python.exe scripts\run_regression.py scheduler-on-long-gate --iterations 2
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit
.venv\Scripts\python.exe scripts\run_regression.py worktree-release-inventory
.venv\Scripts\python.exe scripts\run_regression.py 60h-completion-audit
.venv\Scripts\python.exe scripts\run_regression.py operator-platform-v8
```

For the bounded-read scale check, run the isolated gate directly:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py history-query --json-output artifacts\history-query-regression.json
```

The gate requires PostgreSQL, applies migrations to a temporary database, seeds 10,000 and 100,000 rows per history table, and validates 50-row keyset pages for account isolation, tied timestamps, duplicate/omission-free cursors, bounded ORM materialization, and indexed `EXPLAIN` plans. It performs no broker call and removes the temporary database. A failed or interrupted run is incomplete evidence and must not be described as a passing large-history gate.

Use `unattended-paper arm` to disable new bull put entries while leaving existing spread monitoring and lifecycle reconciliation active. Use `resume` only after intentionally restoring auto-entry posture.

`zero-dte-lottery-drill` reads runtime and preview evidence. With both legacy `--force-scan` and `--confirm-paper-scan` flags it only proves the stable `409 zero_dte_execution_disabled_pending_lifecycle` response; the script fixes broker submission permission and attempt flags to `false`.

`60h-completion-audit` predates P0. Its historical confirmed-force-scan requirement is superseded and should remain incomplete until a later release implements the full Zero-DTE expiration lifecycle and replaces that evidence contract.

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

Longbridge quote reads expose cache fallback metadata only for read-only degraded rendering. When fallback is used, `SecurityQuoteSnapshot.data_quality` is `cached` and `warning_code` is `quote_cache_fallback`. Treat this as dashboard/readiness evidence only. Do not use cached quote evidence to justify paper order submission.

The adapter keeps one lazy market-data `QuoteContext` per execution mode. Each context is created and used on its own single worker thread, with at most `LONGBRIDGE_MARKET_DATA_MAX_PENDING_REQUESTS` queued/in-flight calls (default `8`). Account and order work remains on the general SDK executor, so slow reconciliation cannot occupy the market-data owner thread. A timeout detaches the context and opens the market-data circuit; a later request reconnects after the circuit window instead of retrying the timed-out read automatically. Application shutdown closes and clears the cached adapter.

Reference-data reads use the same owner thread as the SDK context and therefore coalesce concurrent identical requests without a second coordination layer. The cache covers US trading-calendar results, option expiry lists, option chains, and recent daily bars. It defaults to a 300-second TTL and 256-entry LRU bound through `LONGBRIDGE_REFERENCE_DATA_CACHE_TTL_SECONDS` and `LONGBRIDGE_REFERENCE_DATA_CACHE_MAX_ENTRIES`. Values are copied on storage and cache hits so a caller cannot mutate later responses. Security quotes, option market snapshots, and best bid/ask are outside this cache.

Set `LONGBRIDGE_MARKET_DATA_PREWARM_ENABLED=true` to initialize the selected execution-mode context with the comma-separated `LONGBRIDGE_MARKET_DATA_PREWARM_SYMBOLS`. Prewarm starts after `LONGBRIDGE_MARKET_DATA_PREWARM_DELAY_SECONDS` (default `2`) so `/health` is available before the first Longbridge connection. It is read-only, optional, and fail-open for application availability; it does not bypass strategy quote authorization or permit order submission.

Use `GET /ops/market-data-runtime` to inspect the local session without triggering a Longbridge connection. Metrics are grouped by mode and stable operation name rather than symbol. Each operation exposes request and SDK-call counts, reference-cache hits/misses, success/failure/timeout counts, and last/max latency; the session also exposes current and peak pending requests, reference-cache size, and whether its context is initialized. Export the same evidence with:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py market-data-runtime
```

The report is read-only and always records `broker_order_submit_allowed=false`, `local_repair_executed=false`, and `destructive_actions_executed=false`.

Trade authorization uses stricter evidence than previews. Covered Call open and replacement roll-open require live underlying and selected-option snapshots no older than `COVERED_CALL_STRATEGY__TRADE_AUTHORIZATION_MAX_QUOTE_AGE_SECONDS` (default `15`), then recheck contract identity, liquidity, and covered shares. Bull Put locked execution likewise refreshes its underlying and both selected legs. Risk-reducing Covered Call buyback remains allowed before replacement-leg authorization; if refresh fails after the buyback fills, the roll stops at manual action instead of guessing a replacement order.

## Professional workbench operations

`/health/live` reports process liveness. `/health/ready` reports dependency and
read-only service readiness; it never grants permission to trade. Requests receive
an `X-Request-ID` for joining a displayed failure to server diagnostics. Error
responses do not expose connection URLs or provider credentials.

Before schema upgrades, make a new custom-format backup and manifest. The backup
and restore tools use an explicit `DATABASE_URL` environment value and never load
`.env`. With the existing local PostgreSQL container, the commands are:

```powershell
.venv\Scripts\python.exe scripts\backup_database.py --docker-container stocks-tool-postgres --output-dir artifacts\database-backups
.venv\Scripts\python.exe scripts\restore_database.py --docker-container stocks-tool-postgres --manifest <new-manifest-path> --target-database stocks_tool_restore_<unique-suffix>
```

The target must be a new isolated database. Restore verifies table content,
constraints, and column metadata; it cannot overwrite the operator database.
Apply migrations to the isolated copy and compare the original-column projection
before upgrading the operator database. Keep ambiguous historical snapshot modes
unknown. For application rollback, first use read-only service operation; do not
delete history or guess how mixed-mode records should be merged during downgrade.
For that read-only recovery session, override all Longbridge and advisor
credential environment variables with empty values, and disable reconciliation,
backtest dispatch and market-data prewarm in the process environment. Do not edit
the saved `.env`, or reconnect broker credentials to older code that cannot
enforce the new mode/provenance contract. Prefer inspecting the isolated restored
database with the current read models over downgrading mixed-mode business data.

Backtest data belongs under `BACKTEST_DATA_ROOT` (default `data/backtesting`).
`BACKTEST_RESULT_ROOT` defaults to `artifacts/backtests/results`. Both are separate
from broker records. Review local provider licensing and canonical file schemas
before registering a dataset; the application never purchases or downloads data.

```powershell
.venv\Scripts\python.exe scripts\backtest.py doctor --require-docker
.venv\Scripts\python.exe scripts\backtest.py register <dataset-registration.json>
.venv\Scripts\python.exe scripts\backtest.py validate <dataset-id> --strategy bull_put
.venv\Scripts\python.exe scripts\backtest.py run <backtest-request.json>
```

The default `run` waits for a terminal state; `--queue` explicitly requests a
durable queued task. The application dispatcher leases one job at a time. Set
`BACKTEST_DISPATCHER_ENABLED=false` for read-only verification processes. Cancelling
or shutting down affects only the exact container owned by that job. Interrupted
or ownership-unknown runs do not become successful results.

Provision the digest in `adapters/backtesting/engine_lock.py` from the official
QuantConnect image before running. The launcher uses `--pull never`, no network,
read-only input mounts and a separate output directory. The smoke command
`scripts/lean_offline_smoke.py` is a software fixture check, not historical strategy
validation. Missing licensed full-range data remains `BLOCKED_DATA`.

The canonical quote contract carries observation/availability times and explicit
bid/ask sizes. Trade volume is not quoted liquidity. Missing sizes, stale quotes
or fill-forward quotes cannot authorize a simulated fill. The LEAN fill model
uses ask for buys and bid for sells, limits each fill to observed size, and
records partial legs before a strategy becomes active. Supported corporate-action
imports include stock splits and cash dividends; unsupported actions fail closed
instead of disappearing from results. Standard option contracts use a 100-share
multiplier; unsupported adjusted-contract models require an explicit extension
and new validation before formal history can pass.

## Artifact Guidance

Generated screenshots and JSON reports belong under `artifacts/` or `output/`. Keep the latest useful pass/fail evidence locally, but do not treat generated artifacts as source unless a test fixture explicitly needs them.

`scripts\run_unattended_paper.py --notification-channel file` writes JSONL payloads with a `run_id`; use `--notification-run-id` to group a local session explicitly. The file adapter rotates the JSONL before appending when it reaches `--notification-max-bytes` so long-running local sessions do not create an unreadable notification file.

`scripts\run_regression.py data-hygiene-audit` now includes a read-only retention report for stale artifacts, Playwright screenshots, and JSONL notification files. It emits manual cleanup guidance only and never deletes database rows or files.

Generated evidence cleanup is opt-in and local-file-only. To archive stale generated evidence outside the repo, use:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit --archive-stale-generated --confirm-generated-cleanup
```

To remove project-local Python and pytest caches while leaving `.venv` untouched, use:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py data-hygiene-audit --cleanup-project-caches --confirm-generated-cleanup
```

These flags never delete orders, executions, journals, strategy audit rows, advisor runs, scheduler rows, or strategy ledger rows.

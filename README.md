# Stocks Tool

`stocks-tool` is the first-pass architecture skeleton for a US equities and options trading workbench.

The project is intentionally scoped around:

- research and event ingestion
- standardized trade-plan generation
- rule-based risk checks
- broker adapter boundaries
- paper-first execution workflows

It does not attempt live autonomous trading in the current phase.

## Current status

This repository currently contains:

- a runnable FastAPI application skeleton
- domain models for plans, accounts, risk checks, and orders
- a Longbridge adapter boundary with quote and account-sync entry points
- a paper bull put spread workflow with preview, two-leg entry, exit monitoring, rollback, and spread persistence
- a bull put runtime-state layer with scheduled entry scans, review generation, kill-switch style controls, and strategy journaling
- a strategy experiment ledger for proposals, runs, signals, and reviews before new strategies are automated
- a persistent DeepSeek advisor run ledger for dry-run auditing, token/cache usage, response payloads, record status, downstream impact snapshots, and dashboard history
- a first-pass `covered_call_v1` proposal workflow that records covered-call candidates and roll candidates before order execution
- a first-pass `zero_dte_lottery_v1` preview and paper execution workflow for same-day long-option lottery candidates with a `$150` max premium cap
- a local market-event calendar for earnings and macro risk windows, including CSV import and a first FMP provider adapter
- a pre-open downside board with SPY / QQQ option-chain analysis for directional long-put checks
- a background paper-account reconciliation loop for account snapshots, orders, and open bull put spreads
- an order-linked journal and review workflow for trade notes
- a PostgreSQL-ready database layer with SQLAlchemy and Alembic
- architecture documentation for the next build phases

## Repository layout

```text
alembic/
compose.yaml
docs/
  architecture.md
  database.md
src/stocks_tool/
  api/
  application/
  adapters/
  core/
  db/
  domain/
  ports/
  repositories/
tests/
```

## Quick start

1. Create a virtual environment.
2. Copy `.env.example` to `.env`.
3. Start PostgreSQL with Docker Compose.
4. Install the package in editable mode.
5. Apply database migrations.
6. Start the API server.

```bash
python -m venv .venv
.venv\Scripts\activate
copy .env.example .env
docker compose up -d db
pip install -e .[dev]
alembic upgrade head
uvicorn --app-dir src stocks_tool.main:app --reload
```

If you already installed the project before the Longbridge SDK dependency was added, rerun:

```bash
pip install -e .[dev]
```

For Longbridge integration, fill these values in `.env`:

```text
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_PAPER_ACCESS_TOKEN=...
LONGBRIDGE_ACCESS_TOKEN=...
```

Then open:

- `GET /`
- `GET /health`
- `POST /research/rank`
- `POST /plans/draft`
- `POST /plans/validate`
- `GET /brokers/longbridge/profile`
- `GET /brokers/longbridge/quote?symbol=AAPL.US&mode=paper`
- `POST /brokers/longbridge/account-sync/{external_account_id}?mode=paper`
- `GET /account-snapshots/latest?external_account_id=LBPT10087357`
- `GET /market-events`
- `POST /market-events`
- `POST /market-events/import`
- `POST /market-events/import/provider`
- `GET /strategies/bull-put/preview?external_account_id=LBPT10087357&symbol=QQQ.US&mode=paper`
- `GET /strategies/bull-put/readiness?external_account_id=LBPT10087357&mode=paper`
- `GET /strategies/pre-open-risk`
- `GET /strategies/pre-open-runs`
- `POST /strategies/pre-open-runs/{external_account_id}/capture`
- `POST /strategies/pre-open-runs/{external_account_id}/review`
- `GET /strategies/bull-put/spreads`
- `GET /strategies/bull-put/spreads/{spread_id}`
- `GET /strategies/bull-put/runtime?external_account_id=LBPT10087357&mode=paper`
- `POST /strategies/bull-put/execute`
- `POST /strategies/bull-put/spreads/{spread_id}/refresh`
- `POST /strategies/bull-put/spreads/{spread_id}/monitor`
- `POST /strategies/bull-put/runtime/{external_account_id}`
- `POST /strategies/bull-put/runtime/{external_account_id}/scan`
- `POST /strategies/bull-put/runtime/{external_account_id}/review`
- `GET /strategies/covered-call/preview`
- `GET /strategies/zero-dte-lottery/preview`
- `POST /strategies/zero-dte-lottery/execute`
- `GET /strategies/zero-dte-lottery/runtime`
- `POST /strategies/zero-dte-lottery/runtime/{external_account_id}`
- `POST /strategies/zero-dte-lottery/runtime/{external_account_id}/scan`
- `GET /strategies/covered-call/activity`
- `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile`
- `POST /strategies/covered-call/propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/monitor`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue`
- `POST /strategies/covered-call/proposals/{proposal_id}/close`
- `GET /strategies/experiment`
- `GET /strategies/controls`
- `GET /strategies/advisor-context`
- `POST /strategies/advisor/deepseek/dry-run`
- `POST /strategies/advisor/responses`
- `GET /strategies/advisor/runs`
- `GET /strategies/advisor/audit`
- `GET /strategies/proposals`
- `POST /strategies/proposals`
- `POST /strategies/proposals/{proposal_id}/approve`
- `POST /strategies/proposals/{proposal_id}/reject`
- `GET /strategies/runs`
- `POST /strategies/runs`
- `GET /strategies/signals`
- `POST /strategies/signals`
- `GET /strategies/reviews`
- `POST /strategies/reviews`
- `GET /journals`
- `GET /executions`
- `GET /orders`
- `POST /journals`
- `POST /orders/submit`
- `POST /orders/{order_id}/refresh`
- `POST /orders/{order_id}/replace`
- `POST /orders/{order_id}/cancel`
- `POST /orders/sync/longbridge/{external_account_id}`

Order submission is currently paper-first and broker-native:

- use Longbridge-formatted symbols such as `AAPL.US`
- `limit` and `market` orders map directly
- `stop` orders are translated to Longbridge `MIT` or `LIT` based on whether `limit_price` is provided
- live submission stays blocked unless `ALLOW_LIVE_TRADING=true`
- local order reconciliation can be pulled on demand through `/orders/sync/longbridge/{external_account_id}`
- automatic paper reconciliation also runs in the background for active Longbridge broker accounts
- automatic bull put monitoring also runs in the background for open or exit-pending paper spreads
- execution summaries are persisted from broker order-detail snapshots and can be read through `/executions`
- journal entries can be linked to an account, order, trade plan, and latest execution context through `/journals`

The bull put spread workflow is currently paper-only:

- configured universe: `QQQ.US`, `SMH.US`, `SOXL.US`, `EWY.US`
- entry caps: at most `2` active spreads per account, `1` active spread per symbol, and `1` active spread across the correlated `QQQ.US / SMH.US / SOXL.US` group
- daily caps and controls: at most `1` new spread per day, a runtime-tracked realized loss stop, per-account manual pause, kill switch, and paused-symbol list
- target expiration window: `28-35 DTE`
- short-leg filter: `abs(delta)` in `0.18-0.28`, `open_interest >= 200`
- liquidity filter: both legs must have a tight positive bid/ask, fresh option quote timestamps, and configured minimum same-day volume
- width rule: `<75 -> 1`, `75-249.99 -> 2`, `>=250 -> 3`
- trend filter: price above `20 DMA`, `20 DMA > 50 DMA`, not more than `0.5%` below prior close, and not more than `2%` below the open
- risk model: conservative credit and per-trade account risk cap are enforced before the spread is marked eligible
- entry session gate: new spread entries only execute during regular U.S. options hours (`09:30-16:00 ET`)
- entry timing guard: new spread entries wait for the configured post-open confirmation window and stop before the close buffer, so manual execution does not chase the opening print or start a two-leg entry too late in the day
- entry workflow: preview the candidate, buy the protective long put first, then sell the short put
- repricing ladder: long-leg entry now starts at the current ask and can step higher by the configured increment; short-leg entry starts at bid and can reprice lower before the spread is abandoned and the hedge is rolled back
- exit monitor: manual or scripted `monitor` calls evaluate `50%` take-profit, `200%` stop-loss, short-strike breach, and `<= 7 DTE`
- close workflow: buy back the short put first, then flatten the long put; if the long-leg close does not fill, the spread remains `exit_pending_long`
- scheduler: the existing background reconciliation loop now checks the bull put entry window once per loop and also monitors open or exit-pending bull put spreads on the configured monitor interval
- review workflow: the strategy now auto-generates account-level bull put reviews when the closed-spread count or review window is due, and it can also be forced manually
- rollback behavior: if the short leg fails to fill, the service attempts to flatten the long leg and marks the spread `rolled_back` or `rollback_failed`
- persistence: spread lifecycle, order ids, entry credit, and risk summary are stored in `bull_put_spreads`
- runtime state: daily entry count, daily realized PnL, last scan result, last skip reason, last review summary, last action, and paused symbols are stored in `bull_put_strategy_runtime`
- journaling: the strategy now writes entry, close, scan-skip, and parameter-review notes into the existing journal workflow
- pre-open run persistence: the strategy now stores one structured pre-open assessment per target U.S. session date, auto-journals the captured read, and records opening follow-through at `09:30 / 09:45 / 10:00 ET`
- holiday handling: the pre-open assessment now distinguishes normal Mondays from exchange holidays, so `2026-05-25` Memorial Day correctly rolls the next regular open to `2026-05-26 09:30 ET`
- dashboard: the `/` workbench now shows a real-time macro board for QQQ / SPY downside checks, including plain-put action guidance, gap-chase risk, opening checkpoints, optional reference-put liquidity summaries, optional deeper option-chain analysis with front / next expiry ATM IV, put-skew, term-slope, and liquid-strike summaries, plus a separate stored opening follow-through review for the selected broker account, alongside bull put strategy controls, last skip reason, latest review, recent strategy notes, bull put spread summary cards, and per-spread `refresh` / `monitor` controls
- dashboard load behavior: account snapshots, orders, spreads, runtime state, executions, journals, and the latest stored pre-open run render first; Longbridge-backed `Quick Quote` and the real-time macro board are manual so `/` stays usable even when broker quote calls are slow
- dashboard strategy-first behavior: `/` now loads bull put runtime, spreads, orders, executions, journals, and stored pre-open runs first; `Load Live Macro` uses the fast macro path, `Load Option Overlays` fetches slower option-chain layers on demand, and `Save Current Board` persists the current live/partial macro read for follow-through review
- bull put readiness: `GET /strategies/bull-put/readiness` performs a read-only opening readiness check across account configuration, runtime controls, entry window, candidate preview, capacity, and next action before any paper order is submitted
- bull put execution lock: previews return a `candidate_token`; execute requests can include that token plus `minimum_net_credit` so a manual submit cannot silently switch to a different spread candidate
- bull put performance visibility: previews include `timing_ms`, and locked execute can reuse the cached candidate while refreshing only the two selected option legs before submission
- bull put runtime state: runtime responses include computed fields such as `holding_open_position`, `daily_entry_cap_reached`, `next_action`, active/open spread counts, and `next_monitor_after`
- strategy experiment ledger: `/strategies/experiment` aggregates strategy proposals, runs, signals, and reviews; `/strategies/controls` exposes paper/live locks, scheduler state, covered-call automation flags, and execution permission boundaries; `/strategies/advisor-context` packages the same local controls, ledger snapshot, covered-call activity, advisor sources, and hard rules for read-only LLM advisor input; `/strategies/advisor/runs` lists persistent advisor dry-run history with token/cache usage, response ids, status, and record timestamps; `/strategies/advisor/audit` returns a local audit snapshot with response payloads, token/cache deltas, downstream proposal/review impact, and paper-first/manual-approval checks; direct list/create routes are available so future strategies and LLM advisors can record plans before execution
- advisor response intake: `POST /strategies/advisor/responses` records external advisor output as paper-only proposals or reviews after loading the local advisor context; it normalizes recognized sources such as `deepseek`, forces proposal `approval_required=true`, adds read-only/manual-approval checks, and does not touch any broker order path
- DeepSeek advisor dry-run: `POST /strategies/advisor/deepseek/dry-run` loads local advisor context, sends it to DeepSeek through the configured client, records a `strategy_advisor_runs` audit row, persists the recordable response payload back onto the run with `advisor_run_id`, and returns `recorded=false`; Record Output writes only local proposals/reviews and marks the same run `recorded`
- DeepSeek advisor client: `scripts\run_regression.py advisor-intake --call-deepseek` uses the local API dry-run route, which reads `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` from `.env` to ask DeepSeek for a structured advisor response; it sends a compact `compact_v1` advisor context that preserves current lifecycle/status facts while omitting bulky candidate, risk, raw, and broker snapshot payloads; it includes `/strategies/advisor/audit` in the local report when available, stays read-only unless `--record` is also supplied, and sending context to DeepSeek should be treated as explicit external data sharing
- strategy audit and permission boundaries: proposal approval/rejection can include an audit actor and note, recorded as `strategy_policy` signals; LLM/advisor-sourced proposals are read-only advice until local deterministic checks and manual approval are present; advisor-sourced proposals must keep `approval_required=true`, cannot be created in live mode, and are audited when recorded; covered-call order entry enforces the policy before any broker call
- market events: `/market-events` stores local earnings, dividend, FOMC, CPI, jobs, and other risk events for strategy filters; `/market-events/import` ingests CSV-shaped batches with duplicate suppression; `/market-events/import/provider` can import normalized FMP earnings and U.S. macro events through the same dedupe path
- covered call proposals: `GET /strategies/covered-call/preview` scans the latest local stock/ETF position snapshot for a covered lot and a liquid OTM call, including upcoming event warnings from `/market-events`; `POST /strategies/covered-call/propose` persists the candidate into the strategy experiment ledger for manual approval and skips duplicate active proposals for the same symbol; `POST /strategies/covered-call/proposals/{proposal_id}/execute` submits a paper covered-call sell order only after that proposal is approved, leaving the proposal approved while the sell order works and marking it executed only after fill; `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile` manually refreshes and advances existing pending covered-call open / close / roll orders; `POST /strategies/covered-call/proposals/{proposal_id}/monitor` gives read-only take-profit / assignment-pressure / expiration-week guidance for executed sell or roll proposals; `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose` records a manual-approval roll proposal with current buyback estimate and next OTM call candidate; `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute` executes an approved roll proposal by submitting buy-to-close first and only submitting sell-to-open when the buyback is already filled; `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue` refreshes a pending buyback order and can refresh an existing sell-to-open order id to avoid duplicate roll-open orders; `POST /strategies/covered-call/proposals/{proposal_id}/close` submits a paper buy-to-close limit order for an executed sell or roll proposal; filled close orders mark proposals `closed`, and rolls mark the source proposal `rolled` only after the new short call fill is confirmed; optional background flags can auto-scan proposals, monitor executed covered-call proposals, and reconcile pending covered-call open / close / roll orders without approving new proposals
- covered-call Longbridge load shaping: covered-call preview and roll-preview filter the option chain to standard calls inside the configured OTM strike window before requesting option market snapshots, capped to a focused subset, so liquid long chains such as QQQ do not request every call contract in one broker call
- zero-DTE lottery preview/execution/scan: `GET /strategies/zero-dte-lottery/preview` evaluates a same-day long call/put candidate for configured symbols such as `QQQ.US`; `POST /strategies/zero-dte-lottery/execute` re-runs the same preview checks and submits a paper buy-limit order only when the candidate is still eligible and the request includes `confirm_paper_order=true`; `GET/POST /strategies/zero-dte-lottery/runtime` exposes the in-process paper auto-order switch; `POST /strategies/zero-dte-lottery/runtime/{external_account_id}/scan` runs the controlled paper automation path and records a strategy run/signal when the experiment ledger is available. It is paper-only, limited to one contract, caps ask/limit premium at `$150`, enforces at most one lottery trade per account per U.S. session date, and filters for same-day expiry, delta, quote freshness, OI, volume, and bid/ask width. Scheduler execution is available only when the runtime or `.env` auto-execute flag is enabled; the default is disabled, the default scan interval is `900` seconds, and the default scan window is `10:00-14:30 ET`. The dashboard exposes the paper auto-order switch, read-only preview, and confirmed force-scan action; live execution is not supported yet.
- dashboard experiment bench: `/` now includes a strategy experiment panel that surfaces pending proposals, recent runs, signal feed, and review feed for the selected paper account
- dashboard covered-call activity: `/` now includes a dedicated covered-call activity card backed by `GET /strategies/covered-call/activity`, with proposal counts, open covered-call count, latest monitor action/P&L/premium-capture visibility, pending roll count, close-run count, pending close / roll lifecycle task visibility, a manual lifecycle refresh control, and recent proposal/run history
- dashboard proposal controls: the strategy experiment panel now exposes approve / reject, covered-call execute / monitor / close / roll-propose, and covered-call roll execute / continue actions, with compact proposal payload details, optional execution limit-price overrides, and roll-chain references
- dashboard event calendar: `/` now shows upcoming market events so strategy proposal risk warnings have a visible source
- dashboard snapshot load: `/` now reads a lightweight latest-snapshot summary from `/account-snapshots/latest` instead of pulling the full account snapshot history on each refresh
- Longbridge resilience: broker SDK calls now use a bounded `20s` request timeout plus a short circuit breaker, giving slow background loads room to complete while still failing fast when quote connectivity degrades
- scheduler resilience: automatic Longbridge tasks now add an in-memory `account + task` backoff after timeout / circuit-open / connectivity failures so the same account does not keep retrying every poll while the broker is unstable
- Longbridge circuit isolation: account/order failures and market-data failures now use separate circuit-breaker buckets, so a failed account sync does not automatically block quote-backed dashboard panels
- scheduler priority: the background loop now runs bull put monitor / scan / review and pre-open capture / review before account and order reconciliation so strategy and market-data tasks get first access to Longbridge when broker connectivity is unstable
- pre-open board resilience: `/strategies/pre-open-risk` now falls back to the latest stored pre-open run when transient Longbridge failures hit, returns a partial board when only some proxies are unavailable, and degrades to a structured unavailable board when no live or stored pre-open snapshot exists yet
- homepage quote behavior: the dashboard no longer auto-loads `Quick Quote` on first paint, so the default `UNH.US` lookup does not open the shared Longbridge circuit before the pre-open board has a chance to refresh
- pre-open proxy fetch path: the pre-open board now loads its proxy symbols through one batched Longbridge quote request instead of five sequential quote calls, and the dashboard skips slow option overlays by default so fresh macro proxy data can render first
- overlay timeout margin: the homepage now gives `pre-open-risk` slightly more time than the underlying Longbridge fail-fast window, so the first degraded render lands as structured `Unavailable` instead of a client-side `Timed Out`
- dashboard asset versioning: `/` now serves versioned `app.css` and `app.js` URLs so browser tabs pick up the latest frontend after a reload instead of sticking to stale cached static assets

## Regression scripts

The repo includes regression workflows behind a single entrypoint:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
.venv\Scripts\python.exe scripts\run_regression.py real-paper
.venv\Scripts\python.exe scripts\run_regression.py real-preopen-board
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper arm
```

Available workflows:

- `bull-put-paper`: runs an in-memory bull put service regression through scheduled scan, spread open, spread close, parameter review, runtime PnL update, and strategy journal writes
- `bull-put-readiness`: runs the read-only bull put opening readiness check against an already running local API session; it defaults to `QQQ.US` so the check avoids scanning the full universe before the open
- `bull-put-real-paper`: hits the local API against the real Longbridge paper account and validates bull put runtime state plus live preview responses without placing option orders unless `--execute` is supplied
- `advisor-intake`: fetches `/strategies/advisor-context` from an already running local API session, can call DeepSeek with `--call-deepseek` through the same `/strategies/advisor/deepseek/dry-run` API path used by the dashboard, includes the local `/strategies/advisor/audit` snapshot when available, and can record a provided or generated advisor response into `/strategies/advisor/responses` only when `--record` is explicitly supplied
- `mock-ui`: starts the in-memory mock dashboard backend and drives a headless browser through the real-time macro board, save-current-board action, stored opening follow-through review card, option-chain analysis, strategy controls, strategy review, spread monitor, filled-order execution summary, journal submit, and submit / replace / cancel without touching the real paper account
- `real-paper`: by default prints a dry-run plan based on the latest quote; add `--execute` to actually send the paper order through the local API
- `real-preopen-board`: drives a headless browser against an already running local dashboard on `127.0.0.1:8000`, clicks `Load Live Macro`, and verifies the response is live fast-path data for the expected U.S. session date instead of a stored fallback
- `real-ui-refresh`: drives a headless browser against an already running local dashboard on `127.0.0.1:8000`, reloads it repeatedly, and reports dashboard-ready plus overlay-settled timings for the warm real instance
- `unattended-paper`: arms, inspects, or resumes the local paper unattended workflow. `arm` disables new bull put entries while keeping existing spread monitoring and lifecycle reconciliation under the running FastAPI scheduler; add `--zero-dte-lottery-auto-order on` to explicitly arm paper zero-DTE lottery auto-ordering, or `off` to turn it back off; `status` prints a morning/evening summary with `strategy_loop_checks` covering paper-first controls, covered-call auto-propose, bull put runtime state, linked spread/lifecycle orders, executions, journals, and zero-DTE cap/one-trade guard; `resume` re-enables bull put auto-entry. Optional `--notification-channel dry-run|console|file` emits a local notification payload for arm/status/resume, failures, warning checks, zero-DTE auto-order state, and strategy-loop drift; email/push/SMS are reserved but not active.

All workflow scripts emit the same JSON envelope shape:

- `script`
- `workflow`
- `status`
- `mode`
- `target`
- `summary`
- `generated_at`
- `payload`

Useful examples:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper --json-output artifacts/bull-put-paper-regression.json
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness --symbol QQQ.US --json-output artifacts/bull-put-readiness.json
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper --json-output artifacts/bull-put-real-paper-dry-run.json
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --json-output artifacts/advisor-intake-context.json
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake --call-deepseek --json-output artifacts/deepseek-advisor-dry-run.json
.venv\Scripts\python.exe scripts\run_regression.py mock-ui --json-output artifacts/mock-ui-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-paper --json-output artifacts/real-paper-dry-run.json
.venv\Scripts\python.exe scripts\run_regression.py real-preopen-board --expected-session-date 2026-05-29 --json-output artifacts/real-preopen-board-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --json-output artifacts/real-ui-refresh-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-paper --execute --json-output artifacts/real-paper-executed.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper arm --json-output artifacts/unattended-paper-arm.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper arm --zero-dte-lottery-auto-order on --json-output artifacts/unattended-paper-lottery-on.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --json-output artifacts/unattended-paper-status.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel dry-run --json-output artifacts/unattended-paper-status-notify.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --notification-channel file --notification-file artifacts/unattended-paper-notifications.jsonl --json-output artifacts/unattended-paper-status.json
.venv\Scripts\python.exe scripts\run_regression.py unattended-paper resume --zero-dte-lottery-auto-order off --json-output artifacts/unattended-paper-resume.json
```

Market events can also be imported from a local CSV. The importer posts one batch to `/market-events/import`, so reruns skip events already present with the same symbol, type, title, and scheduled time.

```powershell
.venv\Scripts\python.exe scripts\import_market_events.py --csv artifacts/market-events.csv
```

To let the background scheduler import the same CSV periodically, set:

```text
MARKET_EVENT_AUTO_IMPORT_ENABLED=true
MARKET_EVENT_IMPORT_CSV_PATH=artifacts/market-events.csv
MARKET_EVENT_IMPORT_INTERVAL_SECONDS=3600
```

Provider-backed import is also available for FMP when `FMP_API_KEY` is configured:

```powershell
.venv\Scripts\python.exe scripts\import_market_events.py --provider fmp --start 2026-06-01 --end 2026-06-30 --symbols UNH.US,QQQ.US
```

To let the background scheduler import provider events periodically, set:

```text
MARKET_EVENT_PROVIDER_AUTO_IMPORT_ENABLED=true
MARKET_EVENT_PROVIDER=fmp
MARKET_EVENT_PROVIDER_SYMBOLS=UNH.US,QQQ.US
MARKET_EVENT_PROVIDER_LOOKAHEAD_DAYS=30
FMP_API_KEY=...
```

DeepSeek advisor calls are optional and disabled unless you run the advisor-intake script with `--call-deepseek` or click the dashboard DeepSeek dry-run control. Apply Alembic migrations before using the formalized advisor history and audit snapshot because run auditing is stored in `strategy_advisor_runs`.

```text
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_TIMEOUT_SECONDS=120
DEEPSEEK_MAX_TOKENS=4096
DEEPSEEK_TEMPERATURE=0.2
```

## Next milestones

1. Stabilize the paper-account strategy loop for `LBPT10087357`: keep the product boundary paper-first, keep covered-call auto-propose disabled unless intentionally creating a new candidate, and use the dashboard plus runtime/activity endpoints to confirm bull put spreads, covered-call lifecycle tasks, zero-DTE runtime state, orders, executions, and journals agree before leaving the app unattended.
2. Exercise the unattended paper workflow end to end for a few real paper sessions: run `scripts\run_regression.py unattended-paper arm` before nights when the local API will remain running, keep the FastAPI scheduler process alive, inspect `unattended-paper status` the next morning for account/order sync, open spread monitoring, lifecycle reconciliation, and zero-DTE switch state, then use `resume` only after deciding bull put auto-entry should be re-enabled.
3. Complete controlled zero-DTE lottery validation before treating it as an unattended feature: use the dashboard `Lottery Strategy` panel or the equivalent preview endpoint, test confirmed force scan through `POST /strategies/zero-dte-lottery/runtime/LBPT10087357/scan?symbol=QQQ.US&direction=auto&mode=paper&force=true`, execute a manual paper order only with `confirm_paper_order=true`, and verify the `$150` premium cap, one-trade-per-session guard, run/signal recording, and explicit auto-order switch behavior.
4. Confirm every environment has run `alembic upgrade head` so `/strategies/advisor/runs` and `/strategies/advisor/audit` can read the DeepSeek audit table.
5. Use `/strategies/advisor/audit` and the dashboard run history to compare compact-context token usage, cache hit/miss, response payloads, recorded status, and downstream proposal/review impact across approved DeepSeek dry runs before expanding advisor sources.
6. Exercise the local unattended notification adapter with `--notification-channel dry-run` first, then `console` or `file` once the JSONL payload shape is stable. External email/push/SMS delivery remains a future adapter on top of the same payload.

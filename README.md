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
- a first-pass `covered_call_v1` proposal workflow that records covered-call candidates and roll candidates before order execution
- a local market-event calendar for earnings and macro risk windows
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
- `POST /strategies/covered-call/propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/monitor`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue`
- `POST /strategies/covered-call/proposals/{proposal_id}/close`
- `GET /strategies/experiment`
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
- strategy experiment ledger: `/strategies/experiment` aggregates strategy proposals, runs, signals, and reviews; direct list/create routes are available so future strategies and LLM advisors can record plans before execution
- market events: `/market-events` stores local earnings, dividend, FOMC, CPI, jobs, and other risk events for strategy filters; `/market-events/import` ingests CSV-shaped batches with duplicate suppression
- covered call proposals: `GET /strategies/covered-call/preview` scans the latest local stock/ETF position snapshot for a covered lot and a liquid OTM call, including upcoming event warnings from `/market-events`; `POST /strategies/covered-call/propose` persists the candidate into the strategy experiment ledger for manual approval; `POST /strategies/covered-call/proposals/{proposal_id}/execute` submits a paper covered-call sell order only after that proposal is approved; `POST /strategies/covered-call/proposals/{proposal_id}/monitor` gives read-only take-profit / assignment-pressure / expiration-week guidance; `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose` records a manual-approval roll proposal with current buyback estimate and next OTM call candidate; `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute` executes an approved roll proposal by submitting buy-to-close first and only submitting sell-to-open when the buyback is already filled; `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue` refreshes a pending buyback order and submits the sell-to-open leg after it fills; `POST /strategies/covered-call/proposals/{proposal_id}/close` submits a paper buy-to-close limit order for an executed proposal
- dashboard experiment bench: `/` now includes a strategy experiment panel that surfaces pending proposals, recent runs, signal feed, and review feed for the selected paper account
- dashboard proposal controls: the strategy experiment panel now exposes approve / reject, covered-call execute / monitor / close / roll-propose, and covered-call roll execute / continue actions
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

The repo includes six regression workflows plus a single entrypoint:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
.venv\Scripts\python.exe scripts\run_regression.py real-paper
.venv\Scripts\python.exe scripts\run_regression.py real-preopen-board
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh
```

Available workflows:

- `bull-put-paper`: runs an in-memory bull put service regression through scheduled scan, spread open, spread close, parameter review, runtime PnL update, and strategy journal writes
- `bull-put-readiness`: runs the read-only bull put opening readiness check against an already running local API session; it defaults to `QQQ.US` so the check avoids scanning the full universe before the open
- `bull-put-real-paper`: hits the local API against the real Longbridge paper account and validates bull put runtime state plus live preview responses without placing option orders unless `--execute` is supplied
- `mock-ui`: starts the in-memory mock dashboard backend and drives a headless browser through the real-time macro board, save-current-board action, stored opening follow-through review card, option-chain analysis, strategy controls, strategy review, spread monitor, filled-order execution summary, journal submit, and submit / replace / cancel without touching the real paper account
- `real-paper`: by default prints a dry-run plan based on the latest quote; add `--execute` to actually send the paper order through the local API
- `real-preopen-board`: drives a headless browser against an already running local dashboard on `127.0.0.1:8000`, clicks `Load Live Macro`, and verifies the response is live fast-path data for the expected U.S. session date instead of a stored fallback
- `real-ui-refresh`: drives a headless browser against an already running local dashboard on `127.0.0.1:8000`, reloads it repeatedly, and reports dashboard-ready plus overlay-settled timings for the warm real instance

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
.venv\Scripts\python.exe scripts\run_regression.py mock-ui --json-output artifacts/mock-ui-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-paper --json-output artifacts/real-paper-dry-run.json
.venv\Scripts\python.exe scripts\run_regression.py real-preopen-board --expected-session-date 2026-05-29 --json-output artifacts/real-preopen-board-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh --json-output artifacts/real-ui-refresh-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-paper --execute --json-output artifacts/real-paper-executed.json
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

## Next milestones

1. Add provider-specific market/news/event adapters beyond local CSV import.
2. Add richer covered-call dashboards for proposal payload inspection, limit-price overrides, and roll-chain history.
3. Add authentication, audit logging, and strategy-level permission controls before any live execution path expands.

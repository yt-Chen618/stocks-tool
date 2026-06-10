# Session Summary

Last updated: 2026-06-10

## Project

- Name: `stocks-tool`
- Workspace: `C:\Users\dell\OneDrive - Duke University\桌面\stocks-tool`

## Current State

### Backend and database

- FastAPI application code is runnable.
- PostgreSQL is expected via Docker Compose for local development.
- Alembic initial migration is applied.
- Local startup command:

```powershell
uvicorn --app-dir src stocks_tool.main:app --reload
```

### Active API surfaces

- `watchlists`
- `broker-accounts`
- `account-snapshots`
- `account-snapshots/latest`
- `brokers/longbridge`
- `strategies`
- `strategies/experiment`
- `strategies/covered-call`
- `strategies/zero-dte-lottery`
- `market-events`
- `executions`
- `journals`
- `orders`

### Longbridge integration

- Longbridge paper account is connected.
- `.env` already contains:
  - `LONGBRIDGE_APP_KEY`
  - `LONGBRIDGE_APP_SECRET`
  - `LONGBRIDGE_PAPER_ACCESS_TOKEN`
- `LONGBRIDGE_ACCESS_TOKEN` is still empty.
- Local paper account id is aligned to the real paper account number:
  - `LBPT10087357`

### Implemented Longbridge capabilities

- `GET /brokers/longbridge/configuration`
- `GET /brokers/longbridge/quote?symbol=...&mode=paper`
- `POST /brokers/longbridge/account-sync/{external_account_id}?mode=paper`
- `POST /orders/sync/longbridge/{external_account_id}`
- internal option-market access for:
  - option expiry dates
  - option chain by expiry
  - option market snapshots with IV / OI / greeks
  - top-of-book bid/ask lookup
  - recent daily bars for moving-average filters

### Bull put spread execution

- A first-pass `paper_bull_put_v1` backend execution flow now exists.
- Routes:
  - `GET /strategies/bull-put/preview?external_account_id=LBPT10087357&symbol=QQQ.US&mode=paper`
  - `GET /strategies/bull-put/readiness?external_account_id=LBPT10087357&mode=paper`
  - `GET /strategies/bull-put/spreads`
  - `GET /strategies/bull-put/spreads/{spread_id}`
  - `GET /strategies/bull-put/runtime?external_account_id=LBPT10087357&mode=paper`
  - `POST /strategies/bull-put/execute`
  - `POST /strategies/bull-put/spreads/{spread_id}/refresh`
- `POST /strategies/bull-put/spreads/{spread_id}/monitor`
- `POST /strategies/bull-put/runtime/{external_account_id}`
- `POST /strategies/bull-put/runtime/{external_account_id}/scan`
- `POST /strategies/bull-put/runtime/{external_account_id}/review`
- `GET /strategies/experiment`
- `GET /strategies/controls`
- `GET /strategies/advisor-context`
- `POST /strategies/advisor/deepseek/dry-run`
- `POST /strategies/advisor/responses`
- `GET /strategies/advisor/runs`
- `GET /strategies/advisor/audit`
- `GET /strategies/covered-call/preview`
- `GET /strategies/covered-call/activity`
- `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile`
- `POST /strategies/covered-call/propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/monitor`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue`
- `POST /strategies/covered-call/proposals/{proposal_id}/close`
- `GET /market-events`
- `POST /market-events`
- `POST /market-events/import`
- `POST /market-events/import/provider`
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
- `GET /strategies/pre-open-risk`
- `GET /strategies/pre-open-runs`
- `POST /strategies/pre-open-runs/{external_account_id}/capture`
- `POST /strategies/pre-open-runs/{external_account_id}/review`
- Current scope:
  - paper-only
  - configured universe: `QQQ.US`, `SMH.US`, `SOXL.US`, `EWY.US`
  - entry caps: at most `2` active spreads per account, `1` active spread per symbol, and `1` active spread across the correlated `QQQ.US / SMH.US / SOXL.US` group
  - runtime controls: per-account auto-entry toggle, manual pause, kill switch, and paused-symbol list
  - per-day throttles: at most `1` new spread per day plus a runtime-tracked realized loss stop before new entries are blocked
  - target expiry window: `28-35 DTE`
  - same-expiry bull put spread only
  - width rule: `<75 -> 1`, `75-249.99 -> 2`, `>=250 -> 3`
  - short leg selection uses `abs(delta) 0.18-0.28` plus `open_interest >= 200`
  - option-leg liquidity checks now require tight positive bid/ask, fresh quote timestamps, and configured same-day volume minimums before a candidate can execute
  - trend filter uses price vs `20 DMA / 50 DMA`, prior-close drift, and gap-down guard
  - risk preview computes spread credit, max profit, max loss, break-even, and account risk percentage
  - new entries are hard-gated to regular U.S. options hours: `09:30-16:00 ET`
  - new entries also wait for the configured post-open confirmation window and stop before the close buffer, so manual paper execution does not chase the opening print or start a two-leg spread too late
  - execution buys the long put first, then sells the short put
  - long-leg and short-leg entries now use a bounded repricing ladder instead of a single static limit price
  - automatic entry scan can now run once per trading day during the configured `10:45-11:15 ET` window
  - exit monitor checks `50%` take-profit, `200%` stop-loss, short-strike breach, and `<= 7 DTE`
  - close sequencing buys back the short put first, then sells the long put
  - if the long close does not fill, the spread remains `exit_pending_long` for later cleanup
  - entry failures are persisted locally as `entry_failed`, `rolled_back`, or `rollback_failed`
  - spread lifecycle, linked local order ids, and entry metrics are stored in `bull_put_spreads`
  - runtime state is stored in `bull_put_strategy_runtime`
  - strategy-driven journal entries are now written automatically for spread opens, spread closes, scan skips, and periodic parameter reviews
  - periodic review now generates at most one parameter suggestion at a time and never changes runtime strategy parameters automatically
  - the pre-open board now also builds a SPY / QQQ option-chain analysis layer with front / next expiry ATM IV, put-skew, term-slope, and liquid-strike summaries
  - pre-open assessments are now persisted one run per target U.S. session date, with structured opening follow-through checkpoints at `09:30 / 09:45 / 10:00 ET`
  - holiday-aware scheduling now distinguishes normal Mondays from exchange holidays; for example, `2026-05-25` Memorial Day correctly rolls the next regular open to `2026-05-26`
- Current limitations:
  - the workflow still coordinates two separate option orders rather than a broker-native combo order

### Strategy experiment ledger

- A first-pass strategy experiment foundation now exists for future strategy families and LLM-assisted proposals.
- Tables:
  - `strategy_proposals`
  - `strategy_runs`
  - `strategy_signals`
  - `strategy_reviews`
- Current scope:
  - records proposals before execution, including action, rationale, confidence, expected max loss/profit, checks, and raw candidate/risk payloads
  - records strategy runs, signals, and reviews independently from the current bull put runtime table
  - dashboard renders the selected account's pending proposals, latest runs, signal feed, and review feed
  - approval/rejection is persisted, but approval still does not bypass any local strategy-specific readiness or risk checks
  - `GET /strategies/controls` exposes the current paper/live locks, scheduler state, covered-call automation flags, and permission boundaries for future UI and LLM advisor layers
  - `GET /strategies/advisor-context` packages controls, the strategy experiment snapshot, covered-call activity, recognized advisor sources, and hard rules into a read-only context for future DeepSeek/LLM prompts
  - proposal approval/rejection accepts an optional audit actor/note body and writes a `strategy_policy` review signal with the previous/new proposal status
  - LLM/advisor-sourced proposals such as `deepseek`, `llm`, `openai`, or `external_advisor` are treated as read-only advice until local deterministic checks and manual approval are present
  - advisor-sourced proposals must keep `approval_required=true`, cannot be created in live mode, and record a `strategy_policy` audit signal when accepted into the ledger
  - `POST /strategies/advisor/responses` records external advisor output as paper-only proposals or reviews after loading the local advisor context; it normalizes recognized sources such as `deepseek`, forces proposal `approval_required=true`, adds read-only/manual-approval checks, and does not touch any broker order path
  - `POST /strategies/advisor/deepseek/dry-run` loads the same local advisor context, calls the configured DeepSeek client, creates a persistent `strategy_advisor_runs` audit row, persists the recordable response payload back onto the run with `advisor_run_id`, and returns a recordable payload with `recorded=false` so the dashboard can preview the result before writing proposal/review ledger rows
  - `GET /strategies/advisor/runs` lists recent DeepSeek advisor run history with status, provider/model, response id, token/cache usage, proposal/review counts, context format, error messages, and record timestamps
  - `GET /strategies/advisor/audit` returns local advisor audit snapshots with response payloads, raw response content when available, token/cache deltas against the previous run, downstream proposal/review impact, record state, and paper-first/manual-approval checks
  - the DeepSeek advisor prompt now prioritizes `covered_call_activity.summary`, `covered_call_activity.lifecycle_tasks`, proposal statuses, and later close/lifecycle runs over older monitor signals, so closed or rolled covered-call history is not mistaken for an active position
  - the DeepSeek advisor client now sends a compact `compact_v1` context that preserves controls, hard rules, covered-call summary/current state, lifecycle tasks, latest monitor, recent proposal/run/signal/review summaries, and selected option/risk fields while omitting bulky `candidate_payload`, `risk_payload`, `raw_payload`, broker snapshots, and full option-chain details
  - the compact context also exposes covered-call `auto_propose_enabled` and `new_entry_scheduler_active`; when auto-propose is disabled, the prompt tells DeepSeek not to recommend waiting for scheduler-generated covered-call entry signals
  - DeepSeek advisor output is lightly normalized before intake validation: placeholder optional text such as `None`, `N/A`, or `no recommendation` is removed from recommendations, and placeholder required summaries are replaced with a concrete no-action summary so the dashboard does not render `None`
  - the dashboard Strategy Experiment Bench now includes explicit Load Context, Run DeepSeek, Record Output, and recent DeepSeek run history controls; Run DeepSeek is the only dashboard path that sends advisor context to DeepSeek, while Record Output only writes local proposals/reviews and marks the matching advisor run `recorded`
  - `scripts\run_regression.py advisor-intake --call-deepseek` now calls the same `/strategies/advisor/deepseek/dry-run` API path as the dashboard, so CLI dry-runs create the same advisor run history; the local report includes `/strategies/advisor/audit` when available and remains read-only unless `--record` is explicitly supplied

### Covered call proposals

- `covered_call_v1` now has a first-pass read-only proposal workflow on top of the strategy experiment ledger.
- Routes:
  - `GET /strategies/covered-call/preview?external_account_id=LBPT10087357&symbol=UNH.US&mode=paper`
  - `POST /strategies/covered-call/propose?external_account_id=LBPT10087357&symbol=UNH.US&mode=paper`
- Current scope:
  - reads the latest local account snapshot and requires an existing stock / ETF covered lot of at least `100` shares
  - reads local `/market-events` records and adds warnings for medium/high severity symbol-specific or market-wide events inside the configured blackout window
  - loads Longbridge quote, option expiries, option chain, and call market snapshots
  - selects a liquid out-of-the-money call using configured DTE, delta, OI, volume, bid, and bid/ask spread filters
  - computes premium income, assignment profit, zero-price max-loss framing, break-even, uncovered shares, and warning state
  - `propose` writes a strategy run, signal, and pending strategy proposal into the shared experiment ledger, and skips creating duplicate active sell proposals for the same symbol
  - `execute` submits a paper sell-call limit order only for an approved `covered_call_v1` proposal and rechecks the latest local share coverage before order submission; working sell orders keep the proposal `approved` until the order fills
  - `monitor` reloads the underlying and short-call quote for executed sell or roll proposals, estimates buyback debit / open PnL / premium capture, and returns hold / take-profit / assignment-pressure / expiration-week guidance
  - `roll-propose` creates a manual-approval strategy proposal that combines the current buyback estimate with a later OTM covered-call candidate
  - covered-call preview and roll-preview now filter the option chain to standard calls inside the configured OTM strike window before requesting Longbridge market snapshots, capped to a focused candidate subset, so long chains such as QQQ avoid the broker's per-minute option-security request limit
  - `roll-execute` executes an approved roll proposal by submitting the buy-to-close leg first, then submitting the sell-to-open leg only if the buyback order is already filled
  - `roll-continue` refreshes a pending buyback order and submits the sell-to-open leg once that buyback is filled
  - `close` submits a paper buy-to-close limit order for an executed sell or roll proposal and marks the proposal `closed` only when the close order is filled
  - covered-call open / roll / close order entry now checks a shared execution policy before order submission: live mode remains environment-locked, opening and roll orders cannot bypass manual approval, and advisor-sourced proposals without local checks are rejected before any broker call
  - completed roll executions mark the source proposal `rolled` only after the new short call fill is confirmed, while the newly opened roll proposal remains `executed` and monitorable
  - `roll-continue` can refresh an existing roll sell order id so a pending roll-open order is not duplicated while waiting for fill
  - optional lifecycle reconciliation can refresh pending initial sell orders, pending close orders, pending roll buyback orders, and pending roll sell orders in the background; when an initial sell fills it marks the proposal `executed`, and when a roll buyback fills with no sell order yet it can submit the approved roll sell-to-open leg and store the new order id in a lifecycle run
  - `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile` exposes the same pending lifecycle refresh path for manual use against an existing account without approving proposals or creating new initial sell proposals
  - `activity` aggregates covered-call proposal/run/signal/review history into a dedicated dashboard snapshot with active proposal, open covered-call, pending roll, close-run, pending lifecycle task, and latest-activity counts
  - dashboard covered-call activity includes a manual lifecycle refresh button backed by `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile`
  - covered-call activity also exposes `latest_monitor`, parsed from the latest monitor signal, so the dashboard can show monitor action, call mark, estimated open P/L, premium capture, DTE, and monitor timestamp without re-querying Longbridge
  - optional scheduler flags can scan for covered-call proposals, reconcile pending lifecycle orders, and monitor executed covered-call sell or roll proposals in the background, but they default to disabled and do not approve new proposals automatically

### Zero-DTE lottery preview and paper execution

- `zero_dte_lottery_v1` has a first-pass preview and paper execution workflow.
- Routes:
  - `GET /strategies/zero-dte-lottery/preview?external_account_id=LBPT10087357&symbol=QQQ.US&direction=auto&mode=paper`
  - `POST /strategies/zero-dte-lottery/execute`
  - `GET /strategies/zero-dte-lottery/runtime?external_account_id=LBPT10087357&mode=paper`
  - `POST /strategies/zero-dte-lottery/runtime/{external_account_id}`
  - `POST /strategies/zero-dte-lottery/runtime/{external_account_id}/scan`
- Current scope:
  - paper-only preview, paper buy-limit execution, controlled paper scan automation, in-process runtime auto-order control, and dashboard controls for preview / runtime switch / confirmed force scan; no proposal creation and no live mode
  - configured symbol universe starts with `QQQ.US`
  - selects same-day long calls or puts only
  - `direction=auto` uses the underlying's same-day change versus prior close; if the move is inside the configured threshold, preview skips instead of forcing a trade
  - `direction=call` or `direction=put` is available for manual what-if previews
  - contract count is `1`
  - ask-price / execution-limit premium cap is `$150` per candidate
  - execution re-runs preview before order submission, requires `confirm_paper_order=true` for direct manual API execution, and enforces at most `1` lottery trade per account per U.S. session date
  - filters candidates by same-day expiration, delta, quote freshness, open interest, volume, positive bid/ask, and bid/ask spread width
  - `scan` returns skip reasons when automation is disabled or outside the configured U.S. session window; `force=true` bypasses the disabled/window checks for an explicit manual paper scan
  - scheduler integration exists but defaults to off; enable through `POST /strategies/zero-dte-lottery/runtime/{external_account_id}` or with `ZERO_DTE_LOTTERY_STRATEGY__AUTO_EXECUTE_ENABLED=true`, with a default `900` second interval and `10:00-14:30 ET` scan window
  - `scripts\run_regression.py unattended-paper arm --zero-dte-lottery-auto-order on` explicitly arms the same paper auto-order switch for the running API process; `resume --zero-dte-lottery-auto-order off` turns it back off

### Market event calendar

- A first-pass local event calendar exists for strategy risk filters.
- Table:
  - `market_events`
- Routes:
  - `GET /market-events`
  - `POST /market-events`
  - `POST /market-events/import`
- Current scope:
  - manually or script-created events for `earnings`, `dividend`, `fomc`, `cpi`, `jobs`, and `other`
  - optional symbol, event time, source, severity, notes, and raw payload
  - batch import suppresses duplicates with the same symbol, event type, normalized title, and scheduled UTC time
  - provider import currently supports Financial Modeling Prep (`fmp`) earnings calendar plus relevant U.S. macro events from the economic calendar (`FOMC`, `CPI`, jobs/employment)
  - covered-call previews now surface event warnings from this calendar
  - CSV import helper: `.venv\Scripts\python.exe scripts\import_market_events.py --csv artifacts/market-events.csv`
  - provider import helper: `.venv\Scripts\python.exe scripts\import_market_events.py --provider fmp --start 2026-06-01 --end 2026-06-30 --symbols UNH.US,QQQ.US`
  - optional scheduler import settings:
    - `MARKET_EVENT_AUTO_IMPORT_ENABLED=true`
    - `MARKET_EVENT_IMPORT_CSV_PATH=artifacts/market-events.csv`
    - `MARKET_EVENT_IMPORT_INTERVAL_SECONDS=3600`
    - `MARKET_EVENT_PROVIDER_AUTO_IMPORT_ENABLED=true`
    - `MARKET_EVENT_PROVIDER=fmp`
    - `MARKET_EVENT_PROVIDER_SYMBOLS=UNH.US,QQQ.US`
    - `MARKET_EVENT_PROVIDER_LOOKAHEAD_DAYS=30`
    - `FMP_API_KEY=...`

### Automatic reconciliation

- A background reconciliation scheduler now starts with the FastAPI app.
- Active Longbridge paper accounts with `auto_reconcile_enabled=true` are polled automatically.
- The same background loop now also monitors open or exit-pending bull put spreads.
- The same background loop now also captures one pre-open downside assessment during the ET pre-open window and reviews opening follow-through after the regular session opens.
- The same background loop now also runs one bull put entry scan per account when the ET entry window is open.
- The same background loop now also triggers periodic bull put review checks per account.
- The same background loop can now run opt-in covered-call proposal scans, lifecycle reconciliation, and executed covered-call monitoring when `COVERED_CALL_STRATEGY__AUTO_PROPOSE_ENABLED=true`, `COVERED_CALL_STRATEGY__AUTO_LIFECYCLE_ENABLED=true`, or `COVERED_CALL_STRATEGY__AUTO_MONITOR_ENABLED=true`.
- The same background loop can now periodically import a configured local market-event CSV when `MARKET_EVENT_AUTO_IMPORT_ENABLED=true`, or FMP provider events when `MARKET_EVENT_PROVIDER_AUTO_IMPORT_ENABLED=true`.
- Automatic Longbridge scheduler tasks now apply an in-memory `account + task` backoff after timeout / circuit-open / connectivity failures so the same account does not retry every `15s` while the broker is unstable.
- The default Longbridge SDK request timeout is now `20s`, which gives background account/order/strategy loads more room to finish before timeout and backoff logic starts.
- Longbridge circuit breakers are now separated by channel (`account`, `trade`, `market-data`), so a failed account/order reconciliation no longer directly blocks quote-backed dashboard panels like the pre-open risk board.
- The scheduler now runs bull put monitor / scan / review and pre-open capture / review before account and order reconciliation so strategy and market-data tasks get first access to Longbridge when quote connectivity is unstable.
- `GET /strategies/pre-open-risk` now degrades in three steps instead of failing the board outright:
  - return the latest stored pre-open run as `stale` on transient Longbridge failures when a persisted run exists
  - return a `partial` board when only some proxy symbols are unavailable
  - return a structured `unavailable` board when live proxy data fails and no stored run exists yet
- The dashboard no longer auto-loads `Quick Quote` on first paint; quote refresh is now explicit button-click or trusted Enter only.
- The dashboard no longer auto-loads or auto-seeds the live pre-open board on first paint; stored pre-open runs still render immediately in the separate stored review card, while live macro refresh is manual through `Load Live Macro`.
- The dashboard pre-open refresh now requests the fast macro board path by default: proxy symbols load in one batched quote call and option overlays are skipped unless the user clicks `Load Option Overlays`.
- The dashboard can persist the current live or partial macro read through `Save Current Board`, which calls the pre-open capture route and updates the stored opening follow-through card.
- The homepage gives `pre-open-risk` a small timeout margin above the broker fail-fast window so the first degraded response lands as structured `unavailable` instead of a client-side `timed_out`.
- The HTML dashboard now serves versioned `app.css` and `app.js` URLs so browser tabs pick up fresh frontend assets after reload instead of reusing stale cached scripts.
- Default intervals:
  - scheduler poll loop: `15s`
  - account snapshot sync: `300s`
  - order sync: `300s`
  - working-order sync: `60s`
  - bull put spread monitor: `300s`
  - covered-call proposal scan: `3600s` when enabled
  - covered-call lifecycle reconciliation: `300s` when enabled
  - covered-call executed-proposal monitor: `900s` when enabled
  - market event CSV import: `3600s` when enabled
  - Longbridge SDK request timeout: `20s`
- Broker-account records now persist:
  - `account_sync_status`
  - `account_last_sync_attempt_at`
  - `account_last_synced_at`
  - `account_last_sync_error`
  - `orders_sync_status`
  - `orders_last_sync_attempt_at`
  - `orders_last_synced_at`
  - `orders_last_sync_error`
- The scheduler is disabled in pytest through `tests/conftest.py`.

### External automation note

- A Codex heartbeat automation named `US Preopen Market Check` is configured outside the repo.
- The device locale is `Asia/Shanghai`, so the automation does **not** use a single fixed local reminder time for U.S. pre-open work.
- Instead, it wakes at local `20:35` and `21:35` on weekdays, then checks whether the current `America/New_York` time is actually inside the `08:30-09:15 ET` U.S. pre-open window.
- This dual-window design is intentional so the same automation survives U.S. daylight-saving changes without needing manual edits each spring/fall.
- The automation also stays quiet on market holidays or other non-trading days; the `2026-05-25` Memorial Day closure is the current example that motivated this rule.

### Orders layer

Available endpoints:

- `GET /executions`
- `GET /journals`
- `GET /orders`
- `GET /orders/{order_id}`
- `POST /journals`
- `POST /orders/submit`
- `POST /orders/{order_id}/refresh`
- `POST /orders/{order_id}/replace`
- `POST /orders/{order_id}/cancel`
- `POST /orders/sync/longbridge/{external_account_id}`

Current behavior:

- Longbridge symbol format is broker-native, for example `AAPL.US` and `UNH.US`.
- `limit` and `market` orders are supported.
- `stop` orders are mapped to Longbridge `MIT` or `LIT`.
- Live trading is blocked while `ALLOW_LIVE_TRADING=false`.
- Order `raw_payload` has been cleaned up and no longer stores the earlier oversized enum tree for newly refreshed or newly submitted orders.
- The dashboard frontend now exercises submit, refresh, replace, and cancel against these endpoints.
- Execution summaries are now derived from broker order-detail snapshots using `executed_quantity`, `executed_price`, and broker `updated_at`.
- Executions are persisted in the new `executions` table and exposed through `GET /executions`.

### Journal and review workflow

- `GET /journals` lists order-linked or plan-linked notes.
- `POST /journals` creates a new journal entry.
- Current journal entry types:
  - `plan`
  - `review`
  - `note`
- Each entry stores:
  - `external_account_id`
  - `symbol`
  - optional `trade_plan_id`
  - optional `order_id`
  - optional `execution_id`
  - `title`
  - `notes`
  - `tags`
- The creation path validates account / order / execution consistency before persisting.

### Latest paper-account snapshot

- Manual paper-account sync was run on `2026-05-21`.
- Latest snapshot captured at: `2026-05-21T02:14:52.793714Z`
- Positions synced: `1`
- Current position summary:
  - `UNH.US`
  - Quantity: `10`
  - Market value: `$3,833.00`
  - Unrealized PnL: `-$53.50`

### Real paper-order validations already completed

1. Filled order
- Symbol: `UNH.US`
- Side: `buy`
- Quantity: `10`
- External order id: `1241720324853071872`
- Local order id: `cd3d12ba-944e-4e93-84d9-56f89e6a4327`
- Status: `filled`

2. Earlier submit -> replace -> cancel validation order
- Symbol: `UNH.US`
- Side: `buy`
- Quantity: `1`
- External order id: `1241723840942329856`
- Local order id: `d54e2052-02cf-4637-aaed-c83620eb22be`
- Final status: `canceled`

3. Real dashboard regression completed on `2026-05-21`
- Symbol: `UNH.US`
- Side: `buy`
- Submitted quantity / price: `1 @ 320.00`
- Replaced quantity / price: `2 @ 321.00`
- External order id: `1241940481017913344`
- Local order id: `9973705e-0f19-4a45-8abd-fd235c27ba26`
- Final status: `canceled`
- Verified in the dashboard UI:
  - selected order card transitioned from `SUBMITTED` to `CANCELED`
  - replace form was visible while the order was working
  - replace form was hidden after cancel
  - orders table reflected the updated quantity and limit price before cancel

## Frontend

A lightweight dashboard UI is available at:

- `http://localhost:8000/`

Swagger remains available at:

- `http://localhost:8000/docs`

Current dashboard capabilities:

- Select broker account
- Sync account
- Sync orders
- View automatic reconciliation state for the selected account
- View account metrics
- View holdings overview and current holdings cards
- View bull put runtime status, controls, last skip reason, latest review, and recent strategy notes
- View strategy experiment proposals, runs, signals, and reviews for the selected account
- View dedicated covered-call activity/history with proposal counts, open covered-call count, pending roll count, close-run count, pending close / roll lifecycle tasks, and latest proposal/run detail
- Approve / reject strategy proposals and run covered-call proposal actions from the strategy experiment bench, with compact covered-call payload details, optional limit-price overrides, and roll-chain references
- View upcoming market events used by strategy proposal risk warnings
- View bull put spread summary cards, latest exit action, and last monitor timestamp
- View a pre-open risk board with macro proxies plus `QQQ / SPY` directional put checks
- View plain-put action guidance, gap-chase risk, opening checkpoints, richer `QQQ / SPY` reference-put liquidity summaries, and a deeper option-chain analysis layer inside the pre-open board
- View Longbridge configuration status
- Load quick quote
- Submit `market`, `limit`, and `stop` paper orders
- Refresh, manage, replace, and cancel eligible orders from the dashboard
- Refresh and monitor bull put spreads from the dashboard
- Run an on-demand bull put strategy review from the dashboard
- View selected order details and broker status transitions
- View execution summary for the selected order
- Save `plan`, `review`, and `note` journal entries for the selected order
- View existing order-linked journal entries in the selected-order workflow
- View recent orders
- View watchlists
- View latest positions with type, market value, unrealized PnL, and weight

Frontend files:

- `src/stocks_tool/api/routes/ui.py`
- `src/stocks_tool/ui/static/app.css`
- `src/stocks_tool/ui/static/app.js`

### Recent work completed

- Added a dedicated frontend order ticket and selected-order workflow.
- Added order-level dashboard controls for refresh, replace, and cancel.
- Added holdings summary tiles and current holdings cards above the detailed positions table.
- Expanded the positions table to include asset type, unrealized PnL, and portfolio weight.
- Added broker-account reconciliation state persistence and a background polling scheduler.
- Added a dashboard reconciliation strip for `Auto Reconciliation`, `Account Sync`, and `Orders Sync`.
- Added execution persistence, `GET /executions`, and selected-order fill summary rendering.
- Added Alembic migration `20260522_0003_execution_ledger`.
- Added journal persistence, `GET /journals`, `POST /journals`, and selected-order journal/review rendering.
- Added Alembic migration `20260522_0004_journal_entries`.
- Added `paper_bull_put_v1` strategy configuration in `Settings`.
- Added Longbridge adapter support for option expiry dates, option chains, option market snapshots, option top-of-book lookup, and recent daily bars.
- Added a bull put spread service with preview, `POST /strategies/bull-put/execute`, `GET /strategies/bull-put/spreads`, `POST /strategies/bull-put/spreads/{spread_id}/refresh`, and `POST /strategies/bull-put/spreads/{spread_id}/monitor`.
- Added spread persistence through the new `bull_put_spreads` table and Alembic migration `20260522_0005_bull_put_spreads`.
- Added bull put runtime-state persistence through `bull_put_strategy_runtime` and Alembic migration `20260523_0006_bull_put_strategy_runtime`.
- Added two-leg paper entry coordination with long-leg-first execution and long-leg rollback when the short leg does not fill.
- Added spread exit monitoring with take-profit / stop-loss / short-strike breach / DTE rules plus short-first close sequencing.
- Wired the bull put exit monitor into the background reconciliation coordinator so open or exit-pending spreads are checked automatically.
- Added account-level, per-symbol, and correlated-group entry caps for bull put spreads.
- Added automatic daily bull put entry scans, per-day entry caps, daily realized-loss stops, and runtime controls for manual pause / kill switch / paused symbols.
- Added automatic strategy journaling for bull put opens, closes, scan skips, and parameter reviews.
- Added strategy runtime and controls routes under `/strategies/bull-put/runtime`.
- Added bull put review state persistence through Alembic migration `20260523_0007_bull_put_strategy_review_state`.
- Added dashboard spread-monitor visibility with bull put summary cards, latest exit action, and per-spread refresh / monitor actions.
- Added dashboard bull put runtime cards, control form, last skip reason, latest review, and recent strategy-note feed.
- Added `GET /strategies/pre-open-risk` plus a dashboard pre-open risk board that summarizes proxy tape weakness and short-dated `QQQ / SPY` reference puts.
- Added regular-session entry gating and bounded repricing ladders for bull put entry legs.
- Added option-leg liquidity and quote-freshness filters for bull put candidates, with configurable minimum same-day volume per leg.
- Added bull put preview timing visibility through `timing_ms` and short-lived locked-preview cache reuse for execute requests that include `candidate_token`.
- Added computed runtime-state fields for open-position awareness, daily-cap status, entry-block reason, next action, active/open spread counts, and next monitor time.
- Added strategy experiment persistence through `strategy_proposals`, `strategy_runs`, `strategy_signals`, and `strategy_reviews` plus Alembic migration `20260529_0009_strategy_experiment_tables`.
- Added strategy experiment routes under `/strategies/experiment`, `/strategies/proposals`, `/strategies/runs`, `/strategies/signals`, and `/strategies/reviews`.
- Added a dashboard strategy experiment bench for pending proposals, recent runs, signal feed, and review feed.
- Added DeepSeek advisor run persistence through `strategy_advisor_runs` plus Alembic migration `20260603_0011_strategy_advisor_runs`.
- Added `covered_call_v1` preview/propose routes that create strategy experiment runs, signals, and proposals for covered-call candidates.
- Added approved-proposal-only covered-call paper execution through `POST /strategies/covered-call/proposals/{proposal_id}/execute`.
- Added covered-call monitoring guidance through `POST /strategies/covered-call/proposals/{proposal_id}/monitor`.
- Added local market-event persistence through `market_events` plus `/market-events` list/create routes, and wired covered-call previews to warn on upcoming medium/high severity events.
- Added a dashboard market-event calendar panel and mock UI regression coverage for upcoming events.
- Added market-event batch ingestion through `/market-events/import`, duplicate suppression, and optional background CSV import scheduling.
- Added provider-backed market-event ingestion through `/market-events/import/provider`, a first FMP adapter for earnings plus U.S. macro events, script support for `--provider fmp`, and optional scheduler-backed provider imports.
- Added covered-call buy-to-close order submission for executed proposals.
- Added covered-call roll proposal generation for executed proposals; the route records buyback estimate, next-call candidate, run, signal, and pending strategy proposal without submitting either roll leg.
- Added approved covered-call roll execution; the route submits buy-to-close first and only submits sell-to-open when the buyback order is already filled.
- Added covered-call roll continuation for buyback orders that remain working after the initial roll submission.
- Added dashboard strategy proposal controls for approval / rejection plus covered-call execute, monitor, close, roll-propose, roll-execute, and roll-continue actions.
- Added richer covered-call proposal cards in the strategy experiment bench, including key candidate/risk payload fields, roll-from / roll-to summaries, roll-chain references, and optional limit-price prompts before covered-call execute / close / roll actions.
- Added `GET /strategies/covered-call/activity` plus a dedicated dashboard covered-call activity/history card backed by the strategy experiment ledger.
- Added covered-call pending lifecycle task visibility to the activity API and dashboard, including close order id, roll buyback order id, roll sell order id, sequence/status fields, and last refresh time sourced from strategy runs.
- Added a duplicate guard for covered-call proposal scans so repeated `propose` calls return the existing active proposal and record a skipped run/signal instead of creating a second active sell proposal for the same symbol.
- Added pending initial sell-order lifecycle handling for covered calls, so a submitted but unfilled sell-to-open order stays visible as an `open` lifecycle task and does not make the proposal monitorable until it fills.
- Added `scripts/import_market_events.py` for CSV-based local event calendar imports.
- Expanded the pre-open board with action guidance, gap-chase risk, opening checkpoints, and richer `QQQ / SPY` put liquidity metrics.
- Expanded the pre-open board again with a deeper option-chain analysis layer covering front / next expiry ATM IV, put-skew, term-slope, spread-bucket summaries, and most-liquid strikes for `QQQ / SPY`.
- Added `pre_open_assessment_runs` persistence, pre-open capture / review routes, and opening follow-through checkpoints at `09:30 / 09:45 / 10:00 ET`.
- Added holiday-aware target-session handling so the pre-open board and persisted runs correctly treat `2026-05-25` as a Memorial Day closure with the next open on `2026-05-26`.
- Added a `Stored Opening Follow-through` dashboard card that renders the latest persisted pre-open run for the selected broker account, including target session date, review status, stored summary, and checkpoint-by-checkpoint follow-through metrics.
- Split the dashboard macro workflow into `Load Live Macro` for the fast real-time proxy board, `Load Option Overlays` for slower option-chain detail, and `Save Current Board` for persisting the current live/partial read.
- Added `GET /strategies/bull-put/readiness` plus `scripts/run_bull_put_readiness_check.py` / `scripts/run_regression.py bull-put-readiness` so opening readiness can be checked without submitting orders; the script defaults to `QQQ.US` to avoid full-universe option-chain scans before the open.
- Decoupled `/` startup so local account data renders first and Longbridge-backed quote/pre-open overlays stay manual.
- Added `GET /account-snapshots/latest` so the dashboard can fetch the latest local snapshot summary without reloading the full snapshot-history payload on each refresh.
- Added explicit dashboard overlay states for `Quick Quote` and the real-time macro board, including `Live`, `Refreshing`, `Partial`, `Timed Out`, `Circuit Open`, and `Stale`, while preserving the last successful broker-backed data when a later refresh fails.
- Added bounded Longbridge SDK timeouts plus short per-channel circuit breakers so quote/connectivity failures fail fast instead of blocking the whole local API process; the default timeout is now `20s` so slow background loads have more room to complete.
- Added a service-level bull put regression workflow at `scripts/run_bull_put_strategy_regression.py` and exposed it through `scripts/run_regression.py bull-put-paper`.
- Added a real Longbridge bull put smoke script at `scripts/run_bull_put_real_paper_smoke.py` and exposed it through `scripts/run_regression.py bull-put-real-paper`.
- Added a headless browser-driven `mock-ui` regression that now also checks the real-time macro board, save-current-board action, stored opening follow-through review card, alongside strategy controls, strategy review, spread monitor, execution summary, journal submit, and submit / replace / cancel from the dashboard.
- Added `scripts/run_real_local_preopen_board_regression.py` plus `scripts/real_local_preopen_board_flow.js`, exposed as `scripts/run_regression.py real-preopen-board`, to click `Load Live Macro` on a real localhost dashboard and verify live fast-path data for the expected U.S. session date.
- Productized the regression scripts with a unified `scripts/run_regression.py` entrypoint, shared JSON report envelope, and optional `--json-output`.
- Updated the mock dashboard backend to expose reconciliation/account metadata, `GET /executions`, and `GET/POST /journals` so the mock workflow matches the current dashboard data surface.
- Added `tests/test_orders_api.py` for submit / replace / cancel route coverage.
- Added `tests/test_executions_api.py` for execution route coverage.
- Added `tests/test_journals_api.py` for journal route coverage.
- Added `tests/test_journal_service.py` for order / execution linkage validation.
- Added `tests/test_bull_put_strategy.py` for spread selection, risk gating, paper entry success, short-leg rollback, exit-monitor flows, and strategy review suggestions.
- Added `tests/test_strategies_api.py` for strategy preview, execute, monitor, and runtime-review route coverage.
- Added `tests/test_strategy_experiments_api.py` for the unified strategy experiment routes.
- Added `tests/test_ui_dashboard.py` to check the dashboard HTML for order-ticket, holdings, bull put strategy sections, and the pre-open risk board.
- Added `tests/test_reconciliation_services.py` for sync-state success/failure transitions.
- Latest local verification run after the strategy controls / audit boundary / advisor-context update:

```powershell
.venv\Scripts\python.exe -m pytest
```

- Result: `149 passed`
- Latest handoff consolidation verification on `2026-06-03`:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

- Result: `149 passed in 3.42s`
- Latest advisor-intake implementation verification on `2026-06-03`:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

- Result: `153 passed in 2.99s`
- Latest DeepSeek provider-client verification on `2026-06-03`:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

- Result: `158 passed in 3.63s`
- Added mock-transport tests for DeepSeek request construction, `v4 pro` model alias normalization, missing `DEEPSEEK_API_KEY`, HTTP error handling, and invalid JSON handling.
- Latest DeepSeek advisor dry-run/dashboard verification on `2026-06-03`:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_deepseek_advisor.py tests\test_strategy_experiments_api.py tests\test_ui_dashboard.py -q
```

- Result: `23 passed in 0.34s`
- Added route coverage for `POST /strategies/advisor/deepseek/dry-run`, prompt assertions for lifecycle/status priority rules, and dashboard HTML coverage for the DeepSeek dry-run controls.
- Full local verification after the DeepSeek dry-run dashboard update on `2026-06-03`:

```powershell
.venv\Scripts\python.exe -m pytest -q
node --check src\stocks_tool\ui\static\app.js
```

- Result: `161 passed in 3.38s`; JavaScript syntax check passed.
- Local `127.0.0.1:8000` smoke checks confirmed `/openapi.json` includes `/strategies/advisor/deepseek/dry-run`, `/` includes the DeepSeek dry-run controls, and a headless Playwright check could click `Load Context` without external DeepSeek calls or frontend console/page errors.
- Latest DeepSeek compact-context verification on `2026-06-03`:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_deepseek_advisor.py -q
```

- Result: `7 passed in 0.10s`; the broader advisor target set `tests\test_deepseek_advisor.py tests\test_strategy_experiments_api.py tests\test_strategy_advisor_intake.py` also passed with `28 passed in 0.28s`, and full regression passed with `162 passed in 3.37s` after the scheduler-guidance and placeholder-normalization refinements.
- Local offline size comparison against the running `LBPT10087357` advisor context showed full prompt JSON `67,955` characters vs compact prompt JSON `21,165` characters, a `68.9%` character reduction before tokenization. No external DeepSeek request was made for this measurement.
- Latest advisor-intake local API dry run on `2026-06-03`:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py advisor-intake
```

- Result from the running local `127.0.0.1:8000` instance: `passed`; the script loaded `/strategies/advisor-context` for `LBPT10087357`, confirmed `deepseek` is a recognized advisor source, confirmed the read-only hard rules, saw the recorded advisor review, and did not record any ledger rows because `--record` was not supplied.
- An approved real DeepSeek dry-run/record cycle was exercised manually from the dashboard before the formal run-ledger table was added. External DeepSeek calls still require explicit approval because they export local advisor context to the provider.
- Latest formal DeepSeek advisor-run ledger verification on `2026-06-03`:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_deepseek_advisor.py tests\test_strategy_advisor_intake.py tests\test_strategy_experiments_api.py tests\test_ui_dashboard.py -q
.venv\Scripts\python.exe -m pytest -q
node --check src\stocks_tool\ui\static\app.js
```

- Result: advisor/UI target set `31 passed in 0.54s`; full suite `164 passed in 3.52s`; JavaScript syntax check passed.
- Applied local migration `20260603_0011_strategy_advisor_runs` with `alembic upgrade head`; browser smoke on a temporary local server confirmed `/strategies/advisor/runs` no longer 500s after migration, the dashboard still renders the advisor panel on desktop/mobile, and no frontend console/page errors were observed. No external DeepSeek request was made during this formalization verification.
- Latest browser-regression run:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
```

- Result: `passed` and now includes the strategy experiment bench, covered-call activity card, real-time macro board, save-current-board action, stored opening follow-through review card, option-chain analysis, bull put strategy controls, skip-reason rendering, latest-review rendering, plus the macro board state surfaces
- Latest real local pre-open board regression:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py real-preopen-board --expected-session-date 2026-05-29
```

- Result from the long-running local `127.0.0.1:8000` instance: `passed`; the clicked `Load Live Macro` request returned `target_session_date="2026-05-29"`, `source_run_id=null`, `freshness_status="partial"`, and `include_option_overlays=false`.
- Latest bull put service-regression run:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper
```

- Result: `passed`
- Latest targeted strategy/API verification after adding the readiness check and entry timing guard:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_bull_put_strategy.py tests\test_strategies_api.py -q
```

- Result: `48 passed`
- Latest bull put real-paper smoke entrypoint:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
```

- Result from the live local API session: `passed` in dry-run mode after `OPRA US Options Quotes (OpenAPI)` was enabled
- Latest real local dashboard refresh regression:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py real-ui-refresh
```

- Result from the long-running local `127.0.0.1:8000` instance: `passed`; after the strategy experiment ledger landed, repeated dashboard refreshes showed `dashboard-ready 78-358 ms`, `overlay-settled 88-418 ms`, and `/strategies/experiment` averaging about `39 ms`.
- Warm-instance timing from repeated default-threshold runs:
  - dashboard-ready: `115-246 ms`
  - overlay-settled: `121-262 ms`
- After letting the `30s` Longbridge circuit-breaker window expire and rerunning on the same local instance, the regression still passed:
  - dashboard-ready: `121-231 ms`
  - overlay-settled: `129-248 ms`
- The current real local dashboard now settles with explicit degraded overlay states instead of hanging:
  - `Quick Quote`: `Idle` until the user explicitly loads a symbol
  - real-time macro board: `Unavailable` when broker proxy data is down and there is no stored seed run yet
- One earlier first-pass regression run saw a single `13.7s` outlier that was not reproduced by the later default-threshold reruns or the post-idle rerun.
- Verified current pre-open fallback behavior on a fresh temporary local server process:
  - `GET /strategies/pre-open-risk?external_account_id=LBPT10087357` now returns `200` with `freshness_status="error"` and a structured unavailable board when Longbridge connectivity fails before any first successful stored run exists
- Verified current browser-facing dashboard behavior on the long-running local `127.0.0.1:8000` instance after versioned static assets landed:
  - `#quote-card` stays on `Load a quote manually to keep the dashboard fast.`
  - `#preopen-assessment-card` renders the structured unavailable board instead of a client-side timed-out shell
- Verified the new strategy-first dashboard behavior:
  - mock browser regression now clicks `Load Live Macro` and `Save Current Board` explicitly instead of assuming a live pre-open auto-refresh
  - real localhost regression confirms the visible top macro board can show `05/29` live data while the lower stored follow-through card may still show the latest persisted `05/27` review until saved
  - full test suite passes with the manual macro flow, optional option overlays, and scheduler priority ordering
- Verified opening follow-through checkpoint degradation:
  - `review_pre_open_run()` no longer leaves `09:30 / 09:45 / 10:00 ET` checkpoints stuck in `pending` when one or two Longbridge proxy quotes time out
  - transient `SPY / SOXX / QQQ` quote failures now produce a captured partial checkpoint with missing fields noted in `detail`, so the run can keep progressing instead of surfacing a blanket `502`
- Note for local manual verification:
  - the user-facing `127.0.0.1:8000` process may still need a restart if it was not launched with `uvicorn --reload`; static `app.js` changes can appear immediately while the Python route/service changes stay on the older process
- Latest real execute attempts:
  - first end-to-end Longbridge paper bull put entry succeeded on `2026-05-29`
  - open spread id: `f9956612-218a-4b20-94f7-66ce556a202c`
  - selected spread: `QQQ.US` `708 / 705` put spread expiring `2026-06-26`
  - both entry legs filled, no working order was left behind
  - actual entry credit is `0.5200`; the spread now stores fill-based `max_profit`, `max_loss`, and `break_even`
  - preview/execute drift is now guarded by optional `candidate_token` and `minimum_net_credit` request fields
  - locked execute can now reuse the short-lived preview candidate and refresh only the selected option legs before order submission
  - future candidates are blocked when option quotes are stale, top-of-book is too wide, or same-day volume is below the configured minimums
  - runtime responses now report whether an open spread is being monitored, whether the daily entry cap is reached, and what next strategy action is expected
  - latest monitor snapshots are persisted in spread `raw_payload.monitor` and rendered in the dashboard monitor table
  - Longbridge SDK timestamps are normalized from broker wall-clock time into UTC before local persistence
- Latest covered-call paper proposal validation on `2026-06-02` after account sync:
  - synced paper account `LBPT10087357` successfully at `2026-06-02T13:37:27Z`
  - 100-share covered lots present for `CRCL.US`, `DRAM.US`, `EWY.US`, `PLTR.US`, `QQQ.US`, and `TSLA.US`; `UNH.US` still has only `10` shares
  - previews found eligible covered-call candidates for `QQQ.US`, `TSLA.US`, and `PLTR.US`
  - auto-symbol `POST /strategies/covered-call/propose` selected `QQQ.US` and created pending proposal `35f8f82e-f877-4cd2-8cc4-0faeb80d58a7` for `QQQ260626C764000.US`
  - a repeated `propose` call returned the same proposal and recorded a skipped duplicate run; activity stayed at `total_proposals=1`
  - the proposal was approved at `2026-06-02T13:50:01Z`
  - paper execution submitted sell order `14c4fb5f-06b3-48fd-8ac3-150ab35cdb1b` / external order `1246461314306408448` for `1` `QQQ260626C764000.US` at limit `6.78`
  - Longbridge order refresh showed remote status `NEW`, mapped locally to `submitted`, with `0` filled quantity; local proposal state was corrected back to `approved` and the order appears as an `open` lifecycle task until fill
  - manual `POST /strategies/covered-call/lifecycle/LBPT10087357/reconcile?limit=20` succeeded at `2026-06-02T14:21:07Z`, refreshed `1` pending sell order, executed `0`, and recorded an `open_lifecycle_refresh` run with `sequence_status=sell_submitted_waiting_fill`
  - direct order refresh at `2026-06-02T14:24:30Z` still showed remote status `NEW`, local `submitted`, executed quantity `0`, and limit `6.78`
  - a later manual lifecycle reconcile at `2026-06-02T14:37:04Z` refreshed the same pending sell order, saw it filled, marked proposal `35f8f82e-f877-4cd2-8cc4-0faeb80d58a7` `executed`, and cleared the pending `open` lifecycle task
  - local order list now shows order `14c4fb5f-06b3-48fd-8ac3-150ab35cdb1b` as `filled`; Longbridge remote status is `FILLED`, executed quantity `1`, executed price `6.7800`, remote updated time `2026-06-02T14:28:54Z`
  - first post-fill `POST /strategies/covered-call/proposals/35f8f82e-f877-4cd2-8cc4-0faeb80d58a7/monitor?record_signal=true` at `2026-06-02T14:37:48Z` returned `hold`, with underlying `743.680`, call mark `7.66`, estimated open P/L `-88.00`, premium capture `-12.98%`, and no take-profit / assignment-pressure / expiration-week trigger
  - monitor at `2026-06-02T14:57:08Z` still returned `hold`, with underlying `744.190`, call mark `7.87`, estimated open P/L `-109.00`, and premium capture `-16.08%`
  - a first `roll-propose` attempt exposed a Longbridge rate limit from requesting the full QQQ call chain; covered-call preview/roll-preview now prefilter call symbols by the configured OTM strike window before market-snapshot requests
  - retrying `POST /strategies/covered-call/proposals/35f8f82e-f877-4cd2-8cc4-0faeb80d58a7/roll-propose` at `2026-06-02T15:05Z` succeeded and created pending roll proposal `ea90299c-e66d-41d6-b9de-319dd8fa8fb9` from `QQQ260626C764000.US` to `QQQ260630C770000.US`
  - the roll proposal was approved at `2026-06-02T15:07Z`; `roll-execute` submitted buyback order `d7451941-c519-4842-8db0-6a5d228ed21a` / external order `1246480242005004288`, which filled, then submitted sell-to-open order `314e0e97-4524-4eaa-aacf-2423ddb9d9f7` / external order `1246480254315282432` at limit `6.88`
  - manual lifecycle reconcile at `2026-06-02T15:08Z` refreshed the pending roll legs, marked the source proposal `35f8f82e-f877-4cd2-8cc4-0faeb80d58a7` as `rolled`, and marked roll proposal `ea90299c-e66d-41d6-b9de-319dd8fa8fb9` as `executed`
  - latest monitor for the active roll proposal at `2026-06-02T15:09:46Z` returned `hold`, with underlying `744.800`, call mark `7.12`, estimated open P/L `-24.00`, premium capture `-3.49%`, and `28` DTE; `GET /strategies/covered-call/activity` now returns this as `latest_monitor`
  - local `.env` has covered-call auto-propose disabled while covered-call auto-monitor and auto-lifecycle are enabled; the local API was restarted and Settings loaded these flags as `False / True / True`
  - paper close validation was completed at `2026-06-02T15:23:09Z`: `POST /strategies/covered-call/proposals/ea90299c-e66d-41d6-b9de-319dd8fa8fb9/close` submitted buy-to-close order `8267012b-5ec8-4d55-bde9-abb005759e98` / external order `1246484182880747520` for `QQQ260630C770000.US` at limit `8.50`; the order filled immediately and the roll proposal status is now `closed`
  - after the close, `GET /strategies/covered-call/activity` reports `executed_positions=0`, `pending_rolls=0`, `close_runs=1`, and no pending lifecycle tasks
  - implementation note: the code-level FastAPI app and a temporary `127.0.0.1:8001` instance exposed the new `/strategies/controls` route, but the long-running `127.0.0.1:8000` process still served an older OpenAPI route set during verification; a full process restart is needed for the user-facing 8000 instance to expose the new controls and advisor-context routes

## Current phase consolidation

- The last committed handoff on `main` was clean before the current DeepSeek formalization edits.
- Current code and tests include the strategy controls, advisor-context, advisor audit snapshot, covered-call activity, and covered-call lifecycle routes.
- The active product boundary is still paper-first: advisor/LLM inputs may write proposals or reviews into the ledger through `POST /strategies/advisor/responses`, but must not execute orders directly.
- DeepSeek formalization is implemented with `strategy_advisor_runs`, `StrategyAdvisorRunStatus`, `GET /strategies/advisor/runs`, `GET /strategies/advisor/audit`, and migration `20260603_0011_strategy_advisor_runs`; the migration has been applied locally.
- The `advisor-intake` regression workflow can fetch advisor context from the local API, optionally call DeepSeek through the same dry-run API path as the dashboard, include the local advisor audit snapshot in its JSON report, and optionally record a provided or generated advisor response JSON only when `--record` is explicitly supplied.
- The dashboard can now load advisor context, run a DeepSeek dry-run through `POST /strategies/advisor/deepseek/dry-run`, preview token usage/cache hit/miss plus generated proposals/reviews, display recent DeepSeek run history, and explicitly record the output through `POST /strategies/advisor/responses`.
- Real DeepSeek calls export local advisor context to an external provider and should be run only after explicit approval for that data sharing.
- The covered-call paper validation cycle is closed with no active covered-call proposal, pending roll, or pending lifecycle task reported by the activity endpoint.
- Restart any long-running API process after pulling this change so OpenAPI and the dashboard pick up `/strategies/advisor/runs`, `/strategies/advisor/audit`, and the latest static asset version.
- A first-pass unattended paper workflow is now implemented through `scripts\run_regression.py unattended-paper`. It uses the local API to arm conservative overnight mode by disabling new bull put entries while leaving the FastAPI background scheduler responsible for monitoring existing paper spreads, covered-call lifecycle reconciliation, zero-DTE lottery paper auto-ordering only when explicitly armed, and account/order sync. `status` emits a morning/evening summary with `strategy_loop_checks` for paper-first controls, covered-call auto-propose, bull put runtime state, linked spread/lifecycle orders, executions, journals, and zero-DTE cap/one-trade guard; `resume` re-enables bull put auto-entry. Optional `--notification-channel dry-run|console|file` produces a local notification payload for arm/status/resume, failure status, strategy-loop warnings/failures, order/lifecycle drift, and the zero-DTE auto-order switch; email/push/SMS are reserved channels and are not active yet.
- `zero_dte_lottery_v1` preview, paper execution, manual scan, opt-in scheduler scan, runtime auto-order control, unattended script arming, and dashboard controls are implemented with a `$150` max premium cap, one-trade-per-day guard, strategy run/signal recording, and tests. Scheduler execution remains disabled by default.
- Latest paper-loop / advisor-audit / unattended-notification code-level verification on `2026-06-10`: targeted advisor-intake and unattended tests passed with `40 passed`; full test suite passed with `200 passed in 3.72s`; `node --check src\stocks_tool\ui\static\app.js` passed; `scripts\run_regression.py mock-ui` passed and covered dashboard preview plus confirmed force scan against the mock backend; `git diff --check` reported only CRLF normalization warnings.

## Known cleanup items

- Watchlists contain duplicate and test residue data from manual API exercises.
- `artifacts/` contains temporary screenshots from manual UI regression.
- There is no websocket push reconciliation yet.
- The bull put workflow still coordinates two separate option orders rather than a broker-native combo order.
- The unattended workflow now supports local dry-run/console/file notification payloads; external email/push/SMS delivery remains reserved for a later adapter.

## Recommended next steps

1. Stabilize the paper-account strategy loop for `LBPT10087357`: keep the product boundary paper-first, keep covered-call auto-propose disabled unless intentionally creating a new candidate, and use the dashboard plus runtime/activity endpoints to confirm bull put spreads, covered-call lifecycle tasks, zero-DTE runtime state, orders, executions, and journals agree before leaving the app unattended.
2. Exercise the unattended paper workflow end to end for a few real paper sessions: before leaving the app unattended overnight, run `.venv\Scripts\python.exe scripts\run_regression.py unattended-paper arm --json-output artifacts/unattended-paper-arm.json`, optionally add `--notification-channel dry-run` first and then `file` once the payload shape is accepted, keep the FastAPI scheduler process running, inspect `.venv\Scripts\python.exe scripts\run_regression.py unattended-paper status --json-output artifacts/unattended-paper-status.json` the next morning for account/order sync, open spread monitoring, lifecycle reconciliation, and zero-DTE switch state, then use `resume` only after deciding bull put auto-entry should be re-enabled.
3. Complete controlled zero-DTE lottery validation before treating it as an unattended feature: use the dashboard `Lottery Strategy` panel or the equivalent preview endpoint, test confirmed force scan through `POST /strategies/zero-dte-lottery/runtime/LBPT10087357/scan?symbol=QQQ.US&direction=auto&mode=paper&force=true`, execute a manual paper order only with `confirm_paper_order=true`, and verify the `$150` premium cap, one-trade-per-session guard, run/signal recording, and explicit auto-order switch behavior. To arm scheduler paper auto-ordering, use the dashboard control or `.venv\Scripts\python.exe scripts\run_regression.py unattended-paper arm --zero-dte-lottery-auto-order on --json-output artifacts/unattended-paper-lottery-on.json`; turn it back off with `.venv\Scripts\python.exe scripts\run_regression.py unattended-paper resume --zero-dte-lottery-auto-order off --json-output artifacts/unattended-paper-resume.json`.
4. Apply `alembic upgrade head` in every environment and restart the API/dashboard so `/strategies/advisor/runs`, `/strategies/advisor/audit`, and the run-history UI are available.
5. For the next explicitly approved DeepSeek run, confirm the run appears in history as `succeeded`, inspect `/strategies/advisor/audit` for token/cache usage, response content, record state, checks, and downstream proposal/review impact, then use Record Output only when the payload should be written locally.
6. Add external email/push/SMS notification delivery only after the local dry-run/console/file unattended payload has been exercised for a few paper sessions and the summary shape is stable.

# Session Summary

Last updated: 2026-05-24

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
- `brokers/longbridge`
- `strategies`
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
  - `GET /strategies/bull-put/spreads`
  - `GET /strategies/bull-put/spreads/{spread_id}`
  - `GET /strategies/bull-put/runtime?external_account_id=LBPT10087357&mode=paper`
  - `POST /strategies/bull-put/execute`
  - `POST /strategies/bull-put/spreads/{spread_id}/refresh`
- `POST /strategies/bull-put/spreads/{spread_id}/monitor`
- `POST /strategies/bull-put/runtime/{external_account_id}`
- `POST /strategies/bull-put/runtime/{external_account_id}/scan`
- `POST /strategies/bull-put/runtime/{external_account_id}/review`
- `GET /strategies/pre-open-risk`
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
  - trend filter uses price vs `20 DMA / 50 DMA`, prior-close drift, and gap-down guard
  - risk preview computes spread credit, max profit, max loss, break-even, and account risk percentage
  - new entries are hard-gated to regular U.S. options hours: `09:30-16:00 ET`
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
- Current limitations:
  - the workflow still coordinates two separate option orders rather than a broker-native combo order
  - real Longbridge paper preview now works, but the latest execute attempts on `QQQ.US` still ended `long_entry_unfilled`, so no bull put spread has opened end to end yet

### Automatic reconciliation

- A background reconciliation scheduler now starts with the FastAPI app.
- Active Longbridge paper accounts with `auto_reconcile_enabled=true` are polled automatically.
- The same background loop now also monitors open or exit-pending bull put spreads.
- The same background loop now also runs one bull put entry scan per account when the ET entry window is open.
- The same background loop now also triggers periodic bull put review checks per account.
- Default intervals:
  - scheduler poll loop: `15s`
  - account snapshot sync: `300s`
  - order sync: `300s`
  - working-order sync: `60s`
  - bull put spread monitor: `300s`
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
- Expanded the pre-open board with action guidance, gap-chase risk, opening checkpoints, and richer `QQQ / SPY` put liquidity metrics.
- Expanded the pre-open board again with a deeper option-chain analysis layer covering front / next expiry ATM IV, put-skew, term-slope, spread-bucket summaries, and most-liquid strikes for `QQQ / SPY`.
- Added a service-level bull put regression workflow at `scripts/run_bull_put_strategy_regression.py` and exposed it through `scripts/run_regression.py bull-put-paper`.
- Added a real Longbridge bull put smoke script at `scripts/run_bull_put_real_paper_smoke.py` and exposed it through `scripts/run_regression.py bull-put-real-paper`.
- Added a headless browser-driven `mock-ui` regression that now also checks the pre-open risk board, alongside strategy controls, strategy review, spread monitor, execution summary, journal submit, and submit / replace / cancel from the dashboard.
- Productized the regression scripts with a unified `scripts/run_regression.py` entrypoint, shared JSON report envelope, and optional `--json-output`.
- Updated the mock dashboard backend to expose reconciliation/account metadata, `GET /executions`, and `GET/POST /journals` so the mock workflow matches the current dashboard data surface.
- Added `tests/test_orders_api.py` for submit / replace / cancel route coverage.
- Added `tests/test_executions_api.py` for execution route coverage.
- Added `tests/test_journals_api.py` for journal route coverage.
- Added `tests/test_journal_service.py` for order / execution linkage validation.
- Added `tests/test_bull_put_strategy.py` for spread selection, risk gating, paper entry success, short-leg rollback, exit-monitor flows, and strategy review suggestions.
- Added `tests/test_strategies_api.py` for strategy preview, execute, monitor, and runtime-review route coverage.
- Added `tests/test_ui_dashboard.py` to check the dashboard HTML for order-ticket, holdings, bull put strategy sections, and the pre-open risk board.
- Added `tests/test_reconciliation_services.py` for sync-state success/failure transitions.
- Latest local verification run after the bull put review and smoke additions:

```powershell
.venv\Scripts\python.exe -m pytest
```

- Result: `47 passed`
- Latest browser-regression run:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
```

- Result: `passed` and now includes the pre-open risk board, option-chain analysis, bull put strategy controls, skip-reason rendering, and latest-review rendering
- Latest bull put service-regression run:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-paper
```

- Result: `passed`
- Latest bull put real-paper smoke entrypoint:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-real-paper
```

- Result from the live local API session: `passed` in dry-run mode after `OPRA US Options Quotes (OpenAPI)` was enabled
- Latest real execute attempts:
  - selected candidate remained `QQQ.US` bull put
  - no naked short was left behind
  - latest spread execute ended `entry_failed` with `long_entry_unfilled`

## Known cleanup items

- Watchlists contain duplicate and test residue data from manual API exercises.
- `artifacts/` contains temporary screenshots from manual UI regression.
- There is no websocket push reconciliation yet.
- The bull put workflow still coordinates two separate option orders rather than a broker-native combo order.

## Recommended next steps

1. Improve real paper bull put entry quality so the first protective long leg can fill more reliably during regular hours.
2. Add runtime controls and strategy activity views to any future authenticated user/session layer.

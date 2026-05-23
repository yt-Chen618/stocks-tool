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
- `GET /strategies/bull-put/preview?external_account_id=LBPT10087357&symbol=QQQ.US&mode=paper`
- `GET /strategies/bull-put/spreads`
- `GET /strategies/bull-put/spreads/{spread_id}`
- `POST /strategies/bull-put/execute`
- `POST /strategies/bull-put/spreads/{spread_id}/refresh`
- `POST /strategies/bull-put/spreads/{spread_id}/monitor`
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
- target expiration window: `28-35 DTE`
- short-leg filter: `abs(delta)` in `0.18-0.28`, `open_interest >= 200`
- width rule: `<75 -> 1`, `75-249.99 -> 2`, `>=250 -> 3`
- trend filter: price above `20 DMA`, `20 DMA > 50 DMA`, not more than `0.5%` below prior close, and not more than `2%` below the open
- risk model: conservative credit and per-trade account risk cap are enforced before the spread is marked eligible
- entry workflow: preview the candidate, buy the protective long put first, then sell the short put
- exit monitor: manual or scripted `monitor` calls evaluate `50%` take-profit, `200%` stop-loss, short-strike breach, and `<= 7 DTE`
- close workflow: buy back the short put first, then flatten the long put; if the long-leg close does not fill, the spread remains `exit_pending_long`
- scheduler: the existing background reconciliation loop now also checks open or exit-pending bull put spreads on the configured monitor interval
- rollback behavior: if the short leg fails to fill, the service attempts to flatten the long leg and marks the spread `rolled_back` or `rollback_failed`
- persistence: spread lifecycle, order ids, entry credit, and risk summary are stored in `bull_put_spreads`
- dashboard: the `/` workbench now shows bull put spread summary cards, latest exit action, and per-spread `refresh` / `monitor` controls

## Regression scripts

The repo includes two order/dashboard regression workflows plus a single entrypoint:

```powershell
.venv\Scripts\python.exe scripts\run_regression.py mock-ui
.venv\Scripts\python.exe scripts\run_regression.py real-paper
```

Available workflows:

- `mock-ui`: starts the in-memory mock dashboard backend and validates the dashboard shell, journal data surface, and submit / replace / cancel flow without touching the real paper account
- `real-paper`: by default prints a dry-run plan based on the latest quote; add `--execute` to actually send the paper order through the local API

Both scripts now emit the same JSON envelope shape:

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
.venv\Scripts\python.exe scripts\run_regression.py mock-ui --json-output artifacts/mock-ui-regression.json
.venv\Scripts\python.exe scripts\run_regression.py real-paper --json-output artifacts/real-paper-dry-run.json
.venv\Scripts\python.exe scripts\run_regression.py real-paper --execute --json-output artifacts/real-paper-executed.json
```

## Next milestones

1. Add automated browser regression for the dashboard submit/replace/cancel, spread monitor, and journal-review flows.
2. Add scheduler and ingestion workers for market/news/event data.
3. Add authentication, audit logging, and strategy-level permission controls.

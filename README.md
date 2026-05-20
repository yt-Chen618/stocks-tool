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
- `GET /orders`
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

## Next milestones

1. Add a background scheduler for order reconciliation runs.
2. Add scheduler and ingestion workers for market/news/event data.
3. Add Longbridge order push reconciliation loops.
4. Add authentication, audit logging, and strategy-level permission controls.
5. Expand broker adapters beyond Longbridge.

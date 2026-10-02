# Database Setup

This project assumes a local PostgreSQL instance managed by Docker Compose for development.

## Stack

- PostgreSQL 16
- SQLAlchemy 2.x
- Alembic
- `psycopg` driver

## First-pass tables

- `users`
- `broker_accounts`
- `watchlists`
- `watchlist_items`
- `trade_plans`
- `account_snapshots`
- `position_snapshots`
- `orders`
- `executions`
- `journal_entries`
- `bull_put_spreads`
- `bull_put_strategy_runtime`
- `pre_open_assessment_runs`
- `strategy_proposals`
- `strategy_runs`
- `strategy_signals`
- `strategy_reviews`
- `market_events`

## Local startup

1. Copy `.env.example` to `.env`.
2. Start PostgreSQL:

```bash
docker compose up -d db
```

3. Install the locked development environment:

```bash
python scripts/setup_environment.py --skip-browser
```

For an existing environment, run `uv sync --locked --extra dev`. Do not regenerate `uv.lock` implicitly.

4. Apply migrations:

```bash
.venv/Scripts/python.exe -m alembic upgrade head
```

5. Start the API:

```bash
.venv/Scripts/python.exe -m uvicorn --app-dir src stocks_tool.main:app --reload
```

## Notes

- The current Alembic head is `20261002_0019`. Revision `0017` preserves unknown-order coverage evidence, `0018` adds scoped history/decision indexes, and `0019` adds the Bull Put account/mode/created/id keyset index. Earlier migrations remain required for clean installs and upgrades.
- Use `.venv/bin/python` on Linux/macOS. Apply migrations to an isolated fixture database before upgrading an existing operator database; back up and compare row counts/full-row digests as described in `runtime-operations.md`.

- All timestamps are stored in UTC-capable columns.
- Monetary and quantity fields use fixed-point numeric columns.
- Broker-facing raw payloads are stored as `JSONB` to preserve reconciliation detail.
- On Windows, `127.0.0.1` is a safer default than `localhost` for PostgreSQL because `localhost` may resolve to IPv6 first and stall connection attempts.
- The schema is single-user friendly, but `user_id` and `broker_account_id` are already present so the app can expand later without a schema reset.

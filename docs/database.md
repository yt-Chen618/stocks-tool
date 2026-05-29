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

3. Install Python dependencies:

```bash
pip install -e .[dev]
```

If you pulled a newer revision that added broker SDK dependencies, rerun the same command to refresh the environment.

4. Apply migrations:

```bash
alembic upgrade head
```

5. Start the API:

```bash
uvicorn --app-dir src stocks_tool.main:app --reload
```

## Notes

- All timestamps are stored in UTC-capable columns.
- Monetary and quantity fields use fixed-point numeric columns.
- Broker-facing raw payloads are stored as `JSONB` to preserve reconciliation detail.
- On Windows, `127.0.0.1` is a safer default than `localhost` for PostgreSQL because `localhost` may resolve to IPv6 first and stall connection attempts.
- The schema is single-user friendly, but `user_id` and `broker_account_id` are already present so the app can expand later without a schema reset.

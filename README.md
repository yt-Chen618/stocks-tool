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
- a Longbridge adapter boundary with capability metadata
- in-memory repositories for early workflow validation
- architecture documentation for the next build phases

## Repository layout

```text
docs/
  architecture.md
src/stocks_tool/
  api/
  application/
  adapters/
  core/
  domain/
  ports/
  repositories/
tests/
```

## Quick start

1. Create a virtual environment.
2. Install the package in editable mode.
3. Copy `.env.example` to `.env` and fill broker credentials later.
4. Start the API server.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
copy .env.example .env
uvicorn stocks_tool.main:app --reload
```

Then open:

- `GET /health`
- `POST /research/rank`
- `POST /plans/draft`
- `POST /plans/validate`
- `GET /brokers/longbridge/profile`

## Next milestones

1. Replace in-memory repositories with Postgres-backed persistence.
2. Add scheduler and ingestion workers for market/news/event data.
3. Implement the Longbridge HTTP and WebSocket clients.
4. Add authentication, audit logging, and strategy-level permission controls.
5. Add paper-order submission and reconciliation loops.


# Architecture

## Product boundary

The system is a trading workbench, not an autonomous trading agent.

The first production-grade workflow is:

1. ingest market data and catalysts
2. score and rank candidate symbols
3. draft a structured trade plan
4. validate the plan against account and broker constraints
5. let the user approve the plan
6. convert the approved plan into a broker-specific order intent
7. later submit and reconcile paper or live orders through a guarded execution path

## Design principles

- paper-first before live execution
- broker interfaces behind explicit adapter ports
- risk checks must remain deterministic
- LLM-generated content can inform plans, but cannot bypass risk gates
- secrets and live-trading switches remain environment-controlled
- option workflows are modeled explicitly, not folded into stock logic

## First-pass modules

### `api`

FastAPI routes that expose health, research, planning, risk-check, and broker capability endpoints.

### `application`

Use-case and service layer that coordinates:

- candidate ranking
- plan drafting
- risk evaluation
- order intent preparation

### `domain`

Pydantic models and enums for:

- assets and option contracts
- trade plans
- account snapshots
- positions
- risk-check results
- order intents and receipts

### `ports`

Abstract interfaces for:

- broker adapters
- market-data providers
- news providers
- plan repositories

### `adapters`

Concrete infrastructure implementations. Current phase includes a Longbridge stub adapter that exposes capability metadata and configuration status without placing orders.

### `repositories`

An in-memory trade plan repository for early integration work. This is a temporary stand-in for Postgres.

## Target runtime topology

```text
Web / UI
  -> FastAPI
    -> application services
      -> repositories
      -> market/news adapters
      -> broker adapters

Background workers
  -> ingestion tasks
  -> event normalization
  -> order reconciliation

State
  -> Postgres
  -> Redis
```

## Immediate backlog

### Phase 1

- finalize the Python package skeleton
- wire config and capability endpoints
- define core trade-plan and risk-check schemas

### Phase 2

- add SQLAlchemy models and migrations
- implement watchlist, news item, and event persistence
- add Longbridge quote client

### Phase 3

- add paper execution path
- poll or subscribe to order updates
- implement reconciliation jobs

### Phase 4

- introduce user auth, audit logs, and approval workflows
- enable guarded live execution with environment-level locks
- add option-specific risk checks such as expiration and assignment handling

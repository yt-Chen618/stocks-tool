# API Route Inventory

Last updated: 2026-06-16

This inventory groups public routes by bounded context. Paths are part of the compatibility surface for the dashboard and regression scripts.

## UI and Health

- `GET /`
- `GET /health`
- `GET /docs`

## Research and Plans

- `POST /research/rank`
- `POST /plans/draft`
- `POST /plans/validate`

## Accounts and Brokers

- `GET /broker-accounts`
- `POST /broker-accounts`
- `GET /account-snapshots`
- `GET /account-snapshots/latest`
- `GET /brokers/profiles`
- `POST /brokers/longbridge/account-sync/{external_account_id}`
- `GET /brokers/longbridge/profile`
- `GET /brokers/longbridge/quote`
- `GET /brokers/longbridge/option-chain`

## Orders, Executions, and Journals

- `GET /orders`
- `POST /orders/submit`
- `POST /orders/{order_id}/refresh`
- `POST /orders/{order_id}/replace`
- `POST /orders/{order_id}/cancel`
- `POST /orders/sync/longbridge/{external_account_id}`
- `GET /executions`
- `GET /journals`
- `POST /journals`

## Market Events and Watchlists

- `GET /market-events`
- `POST /market-events`
- `POST /market-events/import`
- `POST /market-events/import/provider`
- `GET /watchlists`
- `POST /watchlists`

## Strategy Runtime

- `GET /strategies/controls`
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

## Advisor

- `GET /strategies/advisor-context`
- `POST /strategies/advisor/deepseek/dry-run`
- `GET /strategies/advisor/audit`
- `GET /strategies/advisor/runs`
- `GET /strategies/advisor/run-cards`
- `GET /strategies/advisor/playbooks`
- `POST /strategies/advisor/responses`

## Bull Put

- `GET /strategies/bull-put/preview`
- `GET /strategies/bull-put/readiness`
- `GET /strategies/bull-put/spreads`
- `GET /strategies/bull-put/spreads/{spread_id}`
- `GET /strategies/bull-put/dashboard`
- `GET /strategies/bull-put/runtime`
- `POST /strategies/bull-put/runtime/{external_account_id}`
- `POST /strategies/bull-put/runtime/{external_account_id}/scan`
- `POST /strategies/bull-put/runtime/{external_account_id}/review`
- `POST /strategies/bull-put/execute`
- `POST /strategies/bull-put/spreads/{spread_id}/refresh`
- `GET /strategies/bull-put/spreads/{spread_id}/recover-close/eligibility`
- `POST /strategies/bull-put/spreads/{spread_id}/recover-close`
- `POST /strategies/bull-put/spreads/{spread_id}/monitor`

## Covered Call

- `GET /strategies/covered-call/preview`
- `POST /strategies/covered-call/propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/monitor`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-propose`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-execute`
- `POST /strategies/covered-call/proposals/{proposal_id}/roll-continue`
- `POST /strategies/covered-call/proposals/{proposal_id}/close`
- `GET /strategies/covered-call/activity`
- `POST /strategies/covered-call/lifecycle/{external_account_id}/reconcile`

## Zero-DTE Lottery

- `GET /strategies/zero-dte-lottery/preview`
- `POST /strategies/zero-dte-lottery/execute`
- `GET /strategies/zero-dte-lottery/runtime`
- `POST /strategies/zero-dte-lottery/runtime/{external_account_id}`
- `POST /strategies/zero-dte-lottery/runtime/{external_account_id}/scan`

## Pre-Open

- `GET /strategies/pre-open-risk`
- `GET /strategies/pre-open-runs`
- `POST /strategies/pre-open-runs/{external_account_id}/capture`
- `POST /strategies/pre-open-runs/{external_account_id}/review`

## Operator

- `GET /ops/unattended-status`
- `GET /ops/scheduler`
- `GET /ops/audit`
- `GET /ops/audit/summary`

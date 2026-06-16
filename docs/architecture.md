# Architecture

Last updated: 2026-06-16

## Product Boundary

`stocks-tool` is a paper-first trading workbench for U.S. equities and options. It is not a live autonomous trading agent.

The current product loop is:

1. Load account, order, execution, journal, event, and strategy state.
2. Evaluate deterministic strategy checks for paper workflows.
3. Let the user approve or explicitly arm narrowly scoped automation.
4. Submit only guarded broker orders through the Longbridge adapter.
5. Reconcile broker state back into local orders, executions, strategy records, and operator-facing warnings.

DeepSeek/advisor output is read-only strategy input. It can record local proposals and reviews, but it must not submit broker orders or bypass deterministic checks.

## Runtime Shape

The application is a modular monolith:

```text
Dashboard (/)
  -> FastAPI routers
    -> application services
      -> domain models and lifecycle invariants
      -> repositories
      -> Longbridge / DeepSeek / market-event adapters
        -> PostgreSQL
        -> external providers

In-process scheduler
  -> nonblocking account/order sync dispatch
  -> bull put monitor, scan, review
  -> covered-call lifecycle reconciliation
  -> zero-DTE scan
  -> market-event import
```

Swagger remains at `/docs`. The dashboard remains at `/`.

## Bounded Contexts

| Context | Responsibility | Main Code |
| --- | --- | --- |
| Accounts | broker accounts, account snapshots, positions | `api/routes/account_snapshots.py`, `api/routes/broker_accounts.py`, Longbridge account sync |
| Orders | order intents, broker submission, refresh, replace, cancel | `api/routes/orders.py`, `application/services/orders.py` |
| Executions | broker fills and execution summaries | `api/routes/executions.py`, `application/services/execution.py` |
| Journals | user and system trade notes | `api/routes/journals.py`, `application/services/journal.py` |
| Market Events | earnings, macro events, provider imports | `api/routes/market_events.py`, market-event services |
| Strategy Runtime | shared controls, scheduler state, lifecycle checks | `application/services/reconciliation.py`, strategy services |
| Bull Put | candidate scan, paper entry, monitor, close, review, pre-open board | `application/services/bull_put_strategy.py` |
| Covered Call | preview, proposal, approval, open, monitor, roll, close | `application/services/covered_call_strategy.py` |
| Zero-DTE Lottery | same-day long-option preview and paper execution guard | `application/services/zero_dte_lottery_strategy.py` |
| Advisor | DeepSeek dry-run, advisor context, audit, local intake | `application/services/strategy_experiments.py`, `strategy_advisor_intake.py` |
| Broker Profile | broker capability, credential, and paper guard read model | `adapters/brokers/longbridge.py`, `api/routes/brokers.py` |
| Operator Audit | cross-module explanation events and unattended posture | `application/services/operator_status.py`, `/ops/*` |
| Dashboard | native browser workbench without a build step | `src/stocks_tool/ui/static/` |
| Regression/Ops | smoke scripts, JSON artifacts, unattended status | `scripts/`, `docs/regression-matrix.md` |

## API Router Map

The root app includes routers from `src/stocks_tool/api/routes`. Strategy routes are grouped behind the stable `/strategies` prefix:

- `/strategies/zero-dte-lottery/*`
- `/strategies/covered-call/*`
- `/strategies/advisor-context`
- `/strategies/advisor/*`
- `/strategies/experiment`, `/strategies/controls`, `/strategies/proposals`, `/strategies/runs`, `/strategies/signals`, `/strategies/reviews`
- `/strategies/pre-open-risk`, `/strategies/pre-open-runs*`
- `/strategies/bull-put/*`

Route paths are a compatibility surface. Internal route modules may change, but dashboard and regression scripts should not need URL changes for refactors.

## Vibe-Trading Inspired Read Models

The project borrows three high-value patterns from Vibe-Trading while keeping the current monolith and paper-first boundary:

- `BrokerProfile` makes connector/account posture explicit. The Longbridge paper profile for `LBPT10087357` uses `paper_guard=config_declared`; the SDK response is not treated as proof that an account is paper or live.
- `AdvisorRunCard` is a read projection over existing DeepSeek advisor run/audit data. It includes provider/model, context format/hash, token usage, output counts, recorded state, downstream ids, and warnings. It does not grant direct execution authority.
- `AdvisorPlaybook` is a static registry of allowed advisor task boundaries. It is exposed at `GET /strategies/advisor/playbooks` and currently includes `bull_put_v1`, `covered_call_v1`, and `zero_dte_lottery_v1`.
- `PaperMandate` joins enabled strategies, symbol universe, daily/risk caps, automation switches, manual pause, and kill switch state. `/strategies/controls` exposes the static policy view; `/ops/unattended-status` enriches it with runtime state.
- `StrategyAuditEvent` is an explanation layer assembled from durable `strategy_audit_events` plus synthetic compatibility projections from strategy signals, advisor runs, scheduler runs, and local order observations. It does not replace orders, executions, journals, scheduler rows, or strategy records.

## Durable Audit Ledger

New audit events are forward-only rows in `strategy_audit_events` after migration `20260616_0014_strategy_audit_events.py`. Durable writes currently cover proposal approve/reject, advisor proposal/run record, paper order submit/refresh/cancel, scheduler lifecycle advance, and bull put recover-close submit/reject/complete actions. `/ops/audit` merges durable rows with older synthetic projections and exposes `event_origin=durable|synthetic` plus filters for account, mode, source, strategy, action, warning-only, since, and limit. `/ops/audit/summary` groups the same event stream by account, mode, source, action, strategy, warning code, and event origin for operator evidence exports.

## Manual Recovery Boundary

`GET /strategies/bull-put/spreads/{spread_id}/recover-close/eligibility` is the read-only recovery drill surface for the dashboard. `POST /strategies/bull-put/spreads/{spread_id}/recover-close` is the paper-only manual recovery action for a specific bull put close failure. It refuses live mode, missing confirmation, account mismatch, `should_close=false`, a nonfailed old short close order, and any existing working replacement. It can submit a replacement short-leg buy-to-close and then uses the existing long-leg close flow if the replacement fills. This is not autonomous live trading and does not recover open spreads whose latest monitor no longer requires a close.

## Safety Posture

- The real local Longbridge paper account id used in examples is `LBPT10087357`.
- Paper mode is the default execution boundary.
- Live order submission is blocked unless environment configuration explicitly enables it.
- Bull put execution requires candidate locking and account/runtime caps.
- Zero-DTE execution is paper-only, one contract, one trade per account/session, and capped by premium.
- Covered-call broker order entry requires an approved local proposal and lifecycle reconciliation.
- Advisor and DeepSeek flows remain read-only until a separate local record action is explicitly requested; recorded proposals still require deterministic policy checks and manual approval.
- Operator posture is explained through `/ops/unattended-status`, including broker profiles, paper mandate state, audit summaries, scheduler summaries, lifecycle warnings, and a short `operator_posture_reason`.
- Operator checks and paper mandates may include reason codes and severity fields. Dashboard and unattended scripts consume the same explanation fields for broker degradation, scheduler backoff, manual pause, kill switch, advisor pending record, and manual action required states.
- `.env` secrets must not be printed or copied into chat or committed artifacts.

## Supporting Docs

- `docs/runtime-operations.md`: startup, scheduler, operator posture, and external dependency notes.
- `docs/strategy-lifecycle.md`: lifecycle state and invariant catalog.
- `docs/regression-matrix.md`: verification commands and what each gate proves.
- `docs/api-route-inventory.md`: grouped public route inventory.
- `docs/project-optimization-design.md`: current optimization plan and backlog.
- `docs/vibe-trading-inspired-roadmap.md`: durable roadmap for broker profile, run-card, mandate, audit, and operator posture work.
- `docs/session-summary.md`: current handoff log, not durable architecture.

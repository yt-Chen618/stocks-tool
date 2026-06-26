# Vibe-Trading Inspired Roadmap

Last updated: 2026-06-16

This roadmap borrows a few useful product patterns from HKUDS/Vibe-Trading without importing it as a dependency or turning `stocks-tool` into a general autonomous agent platform. The product boundary remains a paper-first strategy workbench for the local Longbridge paper account `LBPT10087357`.

## Adopted Ideas

- Connector/profile boundary: broker capability and credential posture should be visible before an operator interprets strategy automation state.
- Run card traceability: LLM/advisor work should have a compact card that explains input shape, model/provider, token usage, output count, recording state, downstream impact, and warnings.
- Mandate posture: unattended paper behavior should be explained by a small mandate view that joins account, strategy, symbol, cap, pause, and kill-switch state.
- Audit layer: cross-module events should explain why proposals, advisor records, scheduler runs, and paper order states changed without replacing the existing orders, executions, journals, or strategy tables.
- Operator UX: the dashboard should answer "why is this ready or not ready now" without making the user infer across several panels.

## Non-Goals

- No Vibe-Trading dependency.
- No MCP server/client mode for this repository in this planning slice.
- No React, Vite, or second frontend stack.
- No live autonomous trading.
- No advisor direct order execution.

## Implemented Thin Slice

- `BrokerProfile` now has the unified read shape: `id`, `broker`, `external_account_id`, `mode`, `capabilities`, `readonly`, `paper_guard`, `configured`, `credential_status`, and `notes`.
- Longbridge paper profile uses `paper_guard=config_declared` because the SDK response is not treated as structured proof of paper/live account type.
- `GET /brokers/profiles` returns the current read-only profile list while the legacy `GET /brokers/longbridge/profile` route remains available.
- `PaperMandate` is exposed from `/strategies/controls` and enriched in `/ops/unattended-status` with runtime pause and kill-switch state.
- `AdvisorRunCard` is exposed at `GET /strategies/advisor/run-cards` as a normalized view over existing advisor audit data.
- `StrategyAuditEvent` is exposed at `GET /ops/audit` and summarized in `/ops/unattended-status` by composing existing strategy signals, advisor runs, scheduler runs, and local order observations.
- The native dashboard consumes advisor run-cards and the operator status snapshot to show broker profile, scheduler posture, paper mandate, manual actions, and advisor last-run state.
- `scripts/run_unattended_paper.py` now includes operator status, broker profiles, paper mandate, audit events, and operator posture reason in its local reports and validation checks.
- `mock-ui` regression now seeds and asserts broker profile, operator status, audit, and advisor run-card rendering in the native dashboard.

## Operator Platform Hardening V2

- The in-process reconciliation scheduler keeps `run_once` work off the FastAPI event loop through `asyncio.to_thread()`, with a regression test that proves the event loop can still tick while the coordinator blocks.
- `strategy_audit_events` is now a forward-only durable audit ledger with migration `20260616_0014_strategy_audit_events.py`, a SQLAlchemy repository, and `/ops/audit` merge/filter support across durable and synthetic events.
- Durable audit writes cover proposal approve/reject, advisor record/proposal record, paper order submit/refresh/cancel, scheduler lifecycle advance, and bull put recover-close submit/reject/complete actions.
- `/ops/audit` supports `external_account_id`, `mode`, `source`, `strategy`, `action`, `warning_only`, `since`, and `limit`; events include `event_origin=durable|synthetic`.
- `PaperMandate` and `OperatorStatusCheck` now carry optional reason-code/severity fields. The dashboard and unattended paper script surface those codes for paused mandate, kill switch, scheduler backoff, manual action, advisor pending record, and related degraded states.
- `POST /strategies/bull-put/spreads/{spread_id}/recover-close` adds a guarded paper-only manual recovery path. It requires explicit paper confirmation, matching account, latest monitor `should_close=true`, an old short close order that is canceled/rejected/expired, and no working replacement.
- `GET /strategies/advisor/playbooks` exposes static advisor playbooks: `bull_put_v1`, `covered_call_v1`, and `zero_dte_lottery_v1`. Run-cards now include optional `playbook_id`, `recordable_status`, and `impact_summary`.
- `mock-ui` supports posture scenarios: `normal`, `degraded-broker`, `paused-mandate`, `advisor-pending-record`, `manual-action-required`, and `scheduler-backoff`.

## Operator Platform Hardening V3

- `GET /ops/audit/summary` adds grouped read-only audit evidence across account, mode, source, action, strategy, warning code, and `event_origin`.
- `/ops/audit` behavior is covered for limit validation, stable sorting, and durable-over-synthetic dedupe while keeping the old event list response shape.
- `GET /strategies/bull-put/spreads/{spread_id}/recover-close/eligibility` adds a paper-only read model for manual recovery readiness. The dashboard now shows old close order state, working replacement order id, rejection reason codes, and a disabled/enabled manual recovery form.
- `scripts\run_regression.py audit-export` exports local audit evidence; `scripts\run_regression.py scheduler-on-long-gate` starts a temporary scheduler-enabled API and runs `real-ui-refresh`, `unattended-paper status --notification-channel dry-run`, `bull-put-real-paper`, and `bull-put-recovery-drill`.
- `mock-ui` now includes recovery drill scenarios: `recover-eligible`, `recover-rejected`, and `recover-already-working`, in addition to the V2 posture scenarios.
- Advisor context and run history now show static playbook boundaries and the proposal/review-only guardrail. Advisor output still cannot submit broker orders and still requires explicit record/manual approval.

## Operator Platform Hardening V4

- The current large V2/V3 worktree is organized into reviewable release slices in `docs/worktree-release-slices.md`.
- `OperatorStatusCheck` now includes optional `reason_detail` populated from the backend reason-code catalog, so dashboard and unattended CLI evidence can display the same explanations instead of drifting around raw codes.
- `GET /ops/reason-codes` exposes the backend reason-code catalog as a read-only drift-check surface.
- `scripts\run_regression.py bull-put-recovery-drill` adds a read-only operator drill for recover-close eligibility. It classifies operator action and never calls the guarded POST recovery endpoint.
- `scripts\run_regression.py worktree-release-inventory`, `data-hygiene-audit`, `zero-dte-lottery-drill`, and `paper-session-gate` add machine-readable evidence for release slicing, local residue inspection, controlled zero-DTE preview-only drills, and morning/midday/evening paper session checks.
- `docs/operator-platform-v4-runbook.md` defines the morning, midday, evening, Longbridge backoff, recover-close, advisor pending-record, zero-DTE drill, and data-hygiene operating procedures.
- Advisor playbooks now share the explicit hard limit that advisor output cannot submit, cancel, replace, or recover broker orders.

## Operator Platform Reliability V8

- `GET /ops/consistency` adds a read-first ledger consistency report over zero-DTE manual-scan recording, covered-call order linkage, and bull put lifecycle-warning drift.
- `POST /ops/consistency/repairs/{repair_id}` is a guarded local-only repair surface. The first implemented repair covers missing zero-DTE manual-scan run/signal rows and never submits broker orders.
- `/ops/unattended-status` now includes consistency summary, primary blocker, local repair availability, and latest evidence timestamps so dashboard and CLI reports can explain why unattended posture is blocked without scanning strategy tables manually.
- The native dashboard Operator Console now includes Ledger Consistency alongside broker profile, scheduler posture, paper mandate, manual actions, and advisor last run.
- `paper-session-gate --strict`, `consistency-report`, and `operator-platform-v8` provide repeatable evidence loops. Routine gates still exclude DeepSeek calls and confirmed zero-DTE force scans.
- Mock UI coverage now includes `ledger-mismatch`, `repair-available`, `quote-cache-fallback`, and `scheduler-lease-active` scenarios.

## Phase Plan

### Phase 0: Docs-first alignment

Keep the roadmap, architecture, runtime, route inventory, and regression matrix aligned with code. This phase should not change execution behavior.

### Phase 1: Broker profile foundation

Keep the Longbridge adapter as the only concrete broker adapter, but surface a profile read model everywhere operator posture is explained. Tests should cover `LBPT10087357`, `paper_guard=config_declared`, configured credential status, and the profile list endpoint.

### Phase 2: Advisor run-card upgrade

Continue storing advisor runs in the existing advisor run ledger. Use run-cards as a read projection for dashboard and API consumers. The advisor may write local proposals/reviews only through explicit record actions and never directly places broker orders.

### Phase 3: Paper mandate lite and audit

Use `PaperMandate` as the canonical paper unattended explanation. Durable audit events now exist for new cross-module actions while historical synthetic projections remain available. The audit layer explains cross-module actions; it does not replace orders, executions, journals, scheduler runs, or strategy records.

### Phase 4: Operator posture consolidation

Have the dashboard, unattended script, and regression scenarios consume the same operator posture model. The scenario matrix now covers normal, degraded broker profile, paused mandate, advisor pending record, manual action required, and scheduler backoff.

## Regression Additions

- Broker profile resolution and `config_declared` paper guard.
- Advisor run-card projection and context hash stability.
- Strategy audit event serialization from existing ledgers.
- Operator posture consistency across `/strategies/controls`, `/ops/unattended-status`, `/ops/audit`, and dashboard rendering.
- Durable audit append/filter behavior and `event_origin` compatibility.
- Bull put recover-close accept/reject paths.
- Bull put recover-close eligibility and dashboard recovery drill rendering.
- Bull put recovery drill evidence through `scripts\run_regression.py bull-put-recovery-drill`.
- Zero-DTE lottery drill evidence through `scripts\run_regression.py zero-dte-lottery-drill`, preview-only by default.
- 60h completion audit evidence through `scripts\run_regression.py 60h-completion-audit`, which stays incomplete until every explicit requirement has strong evidence.
- Worktree release inventory, data hygiene audit, and paper session gate evidence.
- Advisor playbook registry and run-card V2 projection.
- Mock scenario matrix through `scripts\run_mock_ui_order_regression.py --scenario all`.
- Scheduler-on long gate through `scripts\run_regression.py scheduler-on-long-gate --iterations 2`.

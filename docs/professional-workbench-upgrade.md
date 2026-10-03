# Professional Workbench Upgrade

Approved: 2026-10-04. Baseline: `d2fb5a8eda93921744057e33409e3210e5243af4` (merged PR #1).
Branch: `codex/professional-workbench-20261004`.

## Objective

Deliver a comprehensible personal workbench: research a symbol, understand its chart,
compare strategies, verify historical behavior, inspect portfolio risk, and review
paper trading. The primary UX requirement is a chart/table with a permanently visible
plain-Chinese explanation of what it shows, what it means, and the available next action.
Preserve FastAPI, SQLAlchemy, PostgreSQL, native JavaScript, the five workspaces,
`/`, `/app`, `/docs`, and account `LBPT10087357`.

## Acceptance ledger

Each item requires current-source evidence. Historical campaign artifacts remain history.
The machine-readable checkpoint is `artifacts/professional-workbench-20261004/state.json`;
events are append-only in the adjacent `events.jsonl`. Do not duplicate live validation.

| ID | Required behavior | Acceptance |
| --- | --- | --- |
| P0.1 | Account snapshots have mode and trustworthy source provenance; unknown legacy data remains identifiable | Same-account paper/live and uploaded/legacy snapshot tests; additive migration preserves rows |
| P0.2 | Bull Put runtime reads and uniqueness include account, strategy, mode | Mode isolation and concurrency tests |
| P0.3 | Manual opening and Covered Call opening use current server evidence; action identity is server-derived | Stale/untrusted/nonpositive NAV fails before broker; exact replay does not call broker |
| P0.4 | Valid close/rollback remains usable without applying new-entry caps | Unknown outcome, quantity, identity, quarantine and existing quote guards still apply |
| P1.1 | Chinese-first redesigned shell with account, Paper, data time, posture and explicit execution | 1440/1024/760px visual and DOM evidence |
| P1.2 | Select symbol -> chart plus explanation -> strategy evaluation -> saved research case | Working safe demo; account-generation/race tests; human usability pending until actual review |
| P1.3 | Plain-language labels, visible explanations, time zones, missing/stale/zero distinction | No tooltip-only key meaning; Asia/Shanghai default and ET for market events; no model dependency |
| P2.1 | Durable account/mode scoped mutable screens and immutable research cases | New session reload, snapshot immutability, reference ownership and evidence traceability |
| P2.2 | Candidate comparison, complete bounded event timeline and Advisor/proposal links | Filters and old records work; no broker/model mutation on read |
| P3.1 | Portfolio history, allocation, concentration, expiry and known strategy risk | Aggregates reconcile to evidence; bounded history reads |
| P3.2 | NAV change is not return without cash flows; unknown fees/Greeks never become zero | Empty/partial/stale/mixed-mode/negative NAV tests and honest unavailable metrics |
| P3.3 | Execution/strategy/journal-linked review and scenario assumptions | Read-only traceable results |
| P4.1 | Dataset register/import/validate with immutable hashes, license, coverage and point-in-time evidence | Missing data blocks formal runs; no paid or automatic market-wide downloads |
| P4.2 | Pinned open-source LEAN Engine directly, offline single-task execution | Actual network-none fixture run, no broker credentials or production-ledger writes |
| P4.3 | Durable create/list/detail/cancel/compare and restart-safe task ownership | Interruption/cancel/concurrency/restart tests and semantic repeatability |
| P5.1 | Shared pure strategy rules and Bull Put/Covered Call/Zero-DTE research simulation | Preview/simulator parity and strategy-specific fixtures |
| P5.2 | Fees/slippage/partial legs/expiry/exercise/assignment/split/dividend/calendar handling | Explicit simulation assumptions; no look-ahead; stable results |
| P5.3 | Full authorized historical test 2020-01-01..2026-09-30 | BLOCKED_DATA until real underlying/options/security-master data passes coverage |
| P6.1 | Liveness/readiness, request IDs, sanitized errors, heartbeat and bounded latency observations | Dependency failure and safe shutdown tests |
| P6.2 | Backups plus manifest and isolated restore with row/constraint verification | No overwrite of operator database; retained historical data |
| P6.3 | Bounded capacity/reservation/history queries and fair >500 intent reconciliation | 100k query proof, >500 unresolved cases, concurrent event import |
| P7.1 | Current-source local P0, browser, PostgreSQL, migration and Windows/Linux evidence | Final checks, no stale source identity, no leaked owned processes |
| P7.2 | Publish reviewable changes and verify remote CI/artifacts | Draft PR only; no automatic merge |

## Implementation constraints

- Preserve existing safety entry points, idempotency, confirmation, candidate locking,
  parent/child intents, exact unknown-state recovery and mobile broker-write blocking.
- UI workspaces: 研究 / 策略 / 市场 / 持仓 / 运行与安全. Research handoff may prefill symbol only.
- Research screens/cases and backtest datasets/runs live in dedicated durable models.
  Backtests never write production orders, executions or trading intents.
- Opening authorization uses current server-acquired broker evidence; an uploaded payload
  cannot label itself trustworthy. Do not infer reduction from BUY/SELL alone.
- Changes to database contracts use Alembic and preserve historical migrations.
  Legacy ambiguous snapshot mode remains unknown rather than guessed paper.
- LEAN is a local compute adapter, not a second web service. Use a fixed image digest,
  no network, readonly inputs and a dedicated writable output directory. No paid CLI.
- Formal run manifests include source/image/data identity, parameters, fees, slippage,
  lifecycle assumptions and time range. Compare semantic output, not wall-clock metadata.
- First historical universe: QQQ, SPY, SMH, SOXL, EWY, AAPL as applicable to the strategy.
  Development 2020-2023, validation 2024, frozen holdout 2025-2026-09-30.
- Existing warm targets: research/core 3s, cached chart 2s, auxiliary 7s. Report external
  cold connection separately; never relax safety to pass latency.

## Explicit external gates

No additional paid subscription or dataset purchase is authorized. No usable licensed
multi-year options dataset is available. Fixture/synthetic validation cannot prove
historical strategy performance; P5.3 remains `BLOCKED_DATA` and the full objective is
incomplete until that requirement passes.

No live or paper broker order, model call, `.cn` switch, `.env` change, destructive
cleanup or automatic merge is authorized. Read-only real-market validation is reported
separately from fixture validation. A one-contract paper canary is a separate future
authorization gate. Zero-DTE execution stays locked even when research simulation works.

## Completion reporting

Report software delivery, real historical validation, real read-only operation, human
usability, and separately authorized paper execution as distinct evidence dimensions.
Do not redefine the objective around whichever subset passes first. No recurring chat
automation is created by this campaign; existing historical heartbeat evidence does not
count as current scheduling evidence.

# Project-wide Optimization Campaign

Approved: 2026-10-02. Baseline: `c16399542ea43837544a28676d36130f3e85ddcf`.
Integration branch: `codex/project-wide-optimization-20261002`.

## Objective and boundaries

Complete M0-M8 below, keeping FastAPI, SQLAlchemy, the native dashboard, existing public contracts, persisted-data integrity, and paper-first controls. Completion requires an independently validated final source snapshot and a draft PR with actual successful remote CI for that source. There is no turn-count or total-duration cutoff. Request/test timeouts remain failure diagnostics.

Real broker reads/writes, `.cn`, new strategies, Zero-DTE execution, live trading, automatic merging, `.env` changes, and destructive data cleanup are excluded. External-model behavior is tested with fixtures; do not call the real provider to validate refactors. The prior 550 tests / 27 P0 children / 18 posture scenarios are the baseline, not a substitute for new acceptance evidence.

## Milestones

| Phase | Required implementation | Acceptance |
| --- | --- | --- |
| M0 | Freeze baseline; incremental regression logs/events and atomic status; record child process identities; configure current-chat ten-minute heartbeat; verify publishing transport and create a draft PR. | Preserve completed children across interruption; distinguish running/interrupted/failed/passed; never duplicate an existing process. Record automation save, manual check and genuine scheduled wake separately. |
| M1 | One frontend trading-safety decision for button, confirmation and request entry; recheck after confirmation. Persist each complete Advisor dry-run result in one transaction. | Programmatic entry cannot bypass recovery/mobile/core/pending guards; account/mode/state changes cancel confirmation. Injected database errors leave no partial succeeded Advisor run. |
| M2 | Complete operator consistency judgement with bounded detail display; exact old-record links; global Covered Call activity and Advisor summaries; batched latest lifecycle runs for active proposals. | Old evidence outside the display window remains discoverable; global counts do not depend on display limit; historical closed runs are not all materialized. |
| M3 | Bull Put working set plus on-demand history page, old/just-completed detail feedback, and on-demand recovery eligibility. Add an account/mode/created/id index through an additive migration. | 10k/100k isolated PostgreSQL first/deep pages are indexed and bounded; no stale-account results; working/manual-action records remain visible and decisions never use page contents. |
| M4 | Separate Bull Put entry, then close/recovery orchestration behind the existing facade. Keep parent action prepare/replay/finalization in the facade and use existing child order/ledger/CAS rules. | Independently verify both slices: two legs, partial fill, rejected/unknown outcomes, rollback, recovery, CAS conflict, and monitor lease ownership. |
| M5 | Consolidate Covered Call open/close/roll/continue orchestration behind its facade; reuse candidate/policy modules and exact linked-order/reservation queries. | Preserve order provenance, quantities, account/mode, idempotency and no duplicate/new sell during bulk reconciliation. |
| M6 | Keep account-loader as sole account-context owner; progressively render core/auxiliary data without weakening readiness; extract remaining strategy views and remove duplicate same-generation detail reads. | One request set per selected order; healthy panels remain visible; late success/error/page responses cannot replace current context. |
| M7 | Share browser/report/server lifecycle helpers while retaining independent scenario state; expand deterministic SDK/queue/cache/quarantine/scheduler fault coverage. | Preserve all existing behavior assertions; expose stuck/ended/interrupted states; no owned server, browser or temporary-database leaks after validation. |
| M8 | Reconcile current versus historical docs and complete independent clean-checkout, local gates, remote CI, and requirement audit. | All evidence is tied to the final source; draft PR CI is actually green and artifacts readable; all milestones complete. |

## Interface decisions

- Add `GET /strategies/bull-put/spreads/paged`: required account, paper default, API limit 50/max 100, UI page 25, existing `CursorPage`, immutable `(created_at DESC, id DESC)` keyset scoped to account and mode. No additional history filter controls.
- Add read-only `working-spreads`: all account/mode-scoped active records or records with `manual_action_required=true`. Preserve old full-history/active/detail contracts. Keep the current/manual working area visible and history in an on-demand page; preserve action feedback through ID detail.
- Preserve operator display fields and add full total/failure/warning counts plus truncation. Overall status uses complete evidence; `limit` limits displayed details only. SQL links/aggregates and bounded legacy-metadata batches must not infer absence from a recent window.
- Allocate Advisor run identity before writing the complete response and status atomically. Preserve each dry-run call's meaning; no content-based deduplication or automatic provider retry.
- Preserve final regression JSON envelopes while adding run ID, source identity and child log references. A missing final manifest is never a pass.

## Ownership, monitoring, and recovery

Root integrates; at most three implementation agents and one independent reviewer. Assign file ownership and use isolated worktrees for overlapping seams. Root serializes heavy database and browser gates. Workers run focused tests and return commits plus evidence; they never push, migrate the operator database, or start external-provider workflows.

Canonical local run directory: `artifacts/project-wide-optimization/20261002-project-wide/`. Read `state.json` and `events.jsonl` before resuming. State records phase, owner, source identity, process ID/start identity, last progress, next action, evidence and remote CI identity. Child stdout/stderr are streamed to separate logs. Child start/end/state changes are checkpoints; long-running child processes report liveness every 30 seconds.

The native heartbeat returns to this same chat every ten minutes. It first checks current workers/processes and source identity, observes still-running processes without duplicating them, classifies exited processes without results as interrupted, and resumes only incomplete or invalidated work. Normal unchanged observations stay quiet; milestones, material failures, decisions and completion are reported. Saved configuration, manual verification and genuine scheduler-triggered execution remain separate evidence layers.

Code failures require a diagnosed fix before rerun. Confirmed transient infrastructure failures allow at most two retries with prior evidence retained. Safety/data-integrity failures stop the affected slice immediately. Independent work continues during an external block. If all remaining work is blocked, report that condition without marking the campaign complete. User pause/cancel stops new dispatch and disables this campaign's heartbeat after checkpointing.

## Delivery and final gate

Keep coherent commits on the integration branch and one draft PR against `main`; do not merge automatically. CI uses pull requests, main-branch push and manual dispatch, cancels only obsolete runs of the same group, and uploads isolated fixture evidence. Do not upload local `.env`, database backups or operator account data.

Final gate: clean locked install without credentials, full pytest/P0 and existing 18-scenario posture plus recovery DOM gates, 10k/100k history and lifecycle query proof, deterministic strategy flows, migration data-retention evidence, source-to-artifact identity checks, no owned process/temporary DB leaks, actual green remote CI and an auditable draft PR. Local-only success is not full completion. Stop the campaign heartbeat only after full completion or the user's pause/cancel.

At planning time, the GitHub connector could read the repository and reported push permission, but local Git HTTPS transport failed. Verify transport independently; connector permissions do not prove a push or remote CI run occurred.

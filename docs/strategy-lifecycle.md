# Strategy Lifecycle

Last updated: 2026-10-02

## Purpose

Strategy lifecycle state is safety-critical. It must be visible through the API, dashboard, unattended status, scheduler logs, and regression artifacts without each caller inventing its own interpretation.

## Common Warning Shape

Lifecycle warnings should use this shape when possible:

```json
{
  "code": "stable_warning_code",
  "message": "operator-readable summary",
  "manual_action_required": true,
  "strategy": "bull_put",
  "record_id": "local-record-id"
}
```

Callers may include extra context such as linked order ids, broker order status, spread status, or monitor reason.

## Bull Put Invariants

| Invariant | Expected State | Warning |
| --- | --- | --- |
| Open spread with `monitor.should_close=true` | a working close order exists, or a manual-action warning is present | `close_order_canceled_manual_action_needed` |
| `exit_pending_short` spread | short exit order id exists and remains refreshable | manual action if missing or failed |
| `exit_pending_long` spread | short close is filled and long close intent/order is linked | manual action if long leg is still exposed unexpectedly |
| Closed / rolled-back spread | no working close order is expected | warning only if stale working order is still linked |
| Entry candidate execution | candidate token and minimum credit constraints still match preview | reject execution if candidate drifted |
| Terminal spread | `closed`, `rolled_back`, and `entry_failed` never transition back to `open` | late fill requires manual action |
| Exit pending long | filled entry legs never overwrite the exit state | remain exit-pending until the long close is reconciled |
| Concurrent lifecycle worker | update succeeds only when the persisted `version` still matches | reload and re-evaluate after CAS conflict |
| Multi-leg action | one parent trade-action intent owns each leg's child order intent | unknown child keeps the parent and account blocked |

## Covered Call Invariants

| Invariant | Expected State | Warning |
| --- | --- | --- |
| Pending open proposal | linked sell-to-open order exists and can be reconciled | manual lifecycle refresh if missing/stale |
| Executed proposal | sell order is filled and proposal remains monitorable | lifecycle warning if order state contradicts proposal |
| Pending close | buy-to-close order exists and can be refreshed | manual action if canceled/rejected without replacement |
| Pending roll buyback | buyback order exists before any new sell-to-open | duplicate-order prevention warning |
| Pending roll open | buyback is filled and sell-to-open order exists or awaits explicit continuation | manual continuation warning |
| Covered shares | working short-call orders and unresolved sell-call intents consume the same share capacity as filled calls | reject over-allocation before submit |

## Zero-DTE Lottery Invariants

| Invariant | Expected State | Warning |
| --- | --- | --- |
| Preview | read-only candidate evaluation remains available | surface degraded broker data without submitting |
| Execute / force scan | disabled pending expiration lifecycle | return `zero_dte_execution_disabled_pending_lifecycle` |
| Auto-order switch | cannot be enabled | keep scheduler order calls at zero |
| Existing same-day position | visible as critical manual action | block new strategy entries |

## Current Canonical Consumers

- Bull Put's facade owns public validation and parent action prepare/replay/finalization. `bull_put/entry.py` owns entry sequencing, `bull_put/close.py` owns close/recovery sequencing, and `bull_put/execution.py` shares quote/order/CAS mechanics. Pre-open research remains in its existing module. Each extraction preserves the same order service and ledger.
- Covered Call's facade owns public action preparation and finalization; `covered_call/lifecycle.py` coordinates open, close, roll and continuation through its policy, order and record dependencies. Candidate selection and order identity checks remain in the existing candidate/policy/order-lifecycle modules.
- Lifecycle reconciliation queries active proposals first, then the latest run per proposal and run type. It never infers active state from a recent account-wide display window. Historical consistency is a different question: any valid historical order link can satisfy that check, so it streams all linked runs in bounded proposal batches.
- Covered Call continuation validates persisted linked IDs, account, mode, contract and quantity before advancing. Working orders and unresolved sell-call intents reserve shares; a bulk refresh never submits a new replacement sell order.

- Strategy services write normalized lifecycle facts into response payloads and `bull_put_spreads` summary columns where available.
- `SQLAlchemyBullPutSpreadRepository` derives bull put lifecycle summary fields from `raw_payload.monitor` / `raw_payload.lifecycle` on write, while preserving explicit summary fields for normalized-only records.
- `scripts/run_unattended_paper.py` validates unattended status and emits warning payloads.
- Operator status and bull put dashboard view models prefer normalized lifecycle fields and fall back to raw payloads for older records.
- Dashboard warning helpers render manual-action state for operator review.
- Regression tests lock the close-order drift scenario and should expand as invariants move into shared pure functions.

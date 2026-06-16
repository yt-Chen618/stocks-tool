# Strategy Lifecycle

Last updated: 2026-06-15

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

## Covered Call Invariants

| Invariant | Expected State | Warning |
| --- | --- | --- |
| Pending open proposal | linked sell-to-open order exists and can be reconciled | manual lifecycle refresh if missing/stale |
| Executed proposal | sell order is filled and proposal remains monitorable | lifecycle warning if order state contradicts proposal |
| Pending close | buy-to-close order exists and can be refreshed | manual action if canceled/rejected without replacement |
| Pending roll buyback | buyback order exists before any new sell-to-open | duplicate-order prevention warning |
| Pending roll open | buyback is filled and sell-to-open order exists or awaits explicit continuation | manual continuation warning |

## Zero-DTE Lottery Invariants

| Invariant | Expected State | Warning |
| --- | --- | --- |
| Auto-order switch | disabled by default and paper-only when enabled | block live mode |
| Daily cap | at most one lottery trade per account/session | reject duplicate session trade |
| Premium cap | ask/limit premium remains within cap | reject execution |
| Order confirmation | `confirm_paper_order=true` required for order placement | reject execution |

## Current Canonical Consumers

- Strategy services write normalized lifecycle facts into response payloads and `bull_put_spreads` summary columns where available.
- `SQLAlchemyBullPutSpreadRepository` derives bull put lifecycle summary fields from `raw_payload.monitor` / `raw_payload.lifecycle` on write, while preserving explicit summary fields for normalized-only records.
- `scripts/run_unattended_paper.py` validates unattended status and emits warning payloads.
- Operator status and bull put dashboard view models prefer normalized lifecycle fields and fall back to raw payloads for older records.
- Dashboard warning helpers render manual-action state for operator review.
- Regression tests lock the close-order drift scenario and should expand as invariants move into shared pure functions.

# Opening Readiness - 2026-05-29

## Code Baseline

- Latest commit: `1fb4d17`
- Strategy preflight commit: `ce89ecf`
- Readiness target optimization commit: `1fb4d17`
- Test baseline: `.venv\Scripts\python.exe -m pytest` -> `79 passed`

## Local API

- Target: `http://127.0.0.1:8000`
- Health check: `ok`
- Note: current `8000` service accepted readiness checks. The newest `symbol` query parameter is committed and will be available after a clean full API restart.

## Account And Orders

- Account: `LBPT10087357`
- Latest snapshot captured: `2026-05-29T05:18:11.793634Z`
- Cash balance: `1912916.0900`
- Net liquidation: `1916732.0900`
- Buying power: `1915587.2800`
- Positions: `1`
- Orders: `6` total, `5` canceled, `1` filled, `0` working
- Bull put spreads: `3` total, all `entry_failed`, `0` active or pending
- Runtime controls: `auto_entry_enabled=true`, `manual_pause=false`, `kill_switch_active=false`, `paused_symbols=[]`

## Longbridge Latency

- `quote_QQQ`: avg `5.98s`, max `6.62s`
- `quote_SPY`: avg `5.84s`, max `5.88s`
- `preopen_fast_batch_quotes`: avg `6.10s`, max `6.31s`
- `account_sync_paper`: avg `8.88s`, max `9.14s`
- `orders_sync_paper`: avg `2.13s`, max `2.14s`

## Macro Board

- Fast live macro board: `200`, `6.76s`
- Target session date: `2026-05-29`
- Freshness: `partial`
- Source run id: `null`
- Signals: `5`
- Summary: `The proxy set is mixed, so plain downside puts do not have a strong pre-open edge.`
- Saved current board: `captured=true`, target session date `2026-05-29`, review status `awaiting_open`
- Option overlays: skipped after a `180s` client timeout to keep opening prep unblocked

## Bull Put Readiness

- `09:35 ET` simulation: `blocked`
  - Reason: opening confirmation window, 15 minutes after the regular open
- `10:45 ET` simulation: `ready`
  - Preferred symbol: `QQQ.US`
  - Candidate: `QQQ260626P704000.US / QQQ260626P701000.US`
  - Expiry: `2026-06-26`
  - Width: `3`
  - Mid credit: `0.54`
  - Conservative credit: `0.44`
  - Max profit: `54.00`
  - Max loss: `256.00`
  - Account risk pct: `0.0001335606584434030110071355877`

## Tonight Command Sequence

```powershell
.venv\Scripts\python.exe scripts\run_regression.py bull-put-readiness --symbol QQQ.US --timeout-seconds 240
```

If readiness returns `ready`, preview:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/strategies/bull-put/preview?external_account_id=LBPT10087357&symbol=QQQ.US&mode=paper" -UseBasicParsing
```

Only if preview is still eligible, execute:

```powershell
Invoke-WebRequest -Method POST -Uri "http://127.0.0.1:8000/strategies/bull-put/execute" -ContentType "application/json" -Body '{"external_account_id":"LBPT10087357","symbol":"QQQ.US","mode":"paper","remark":"opening_test"}' -UseBasicParsing
```

Then immediately refresh/sync:

```powershell
Invoke-WebRequest -Method POST -Uri "http://127.0.0.1:8000/orders/sync/longbridge/LBPT10087357" -UseBasicParsing
Invoke-WebRequest -Uri "http://127.0.0.1:8000/strategies/bull-put/spreads?external_account_id=LBPT10087357" -UseBasicParsing
```

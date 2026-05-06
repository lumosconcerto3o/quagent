# QuAgent Local Deployment Runbook

## Overview

This runbook provides step-by-step instructions for verifying that a local QuAgent deployment is safe and ready for read-only dry-run operation.

## Prerequisites

- Python virtual environment activated (`.venv\Scripts\Activate.ps1` or equivalent)
- TWS Paper Trader running (for `--connect` checks only)
- Project root: `D:\quagent`

## Healthcheck Script

### Purpose

`scripts/quagent_healthcheck.py` determines whether the system is safe and ready for read-only dry-run operation. It performs a series of offline checks by default, with optional connectivity tests via `--connect`.

**This script never submits orders, never calls `ib.placeOrder()`, never calls `ib.cancelOrder()`, and never calls `reqGlobalCancel()`.**

### Quick Start (Offline Checks)

```powershell
cd D:\quagent
python scripts\quagent_healthcheck.py --config configs\paper.yaml
```

This runs all offline safety checks and prints a report. No TWS connection is needed.

### Full Check (With Connectivity)

```powershell
python scripts\quagent_healthcheck.py --config configs\paper.yaml --connect
```

This additionally checks TWS port reachability and IBKR account access.

### Full Check With Quote

```powershell
python scripts\quagent_healthcheck.py --config configs\paper.yaml --connect --symbol SPY
```

This also fetches a quote for the given symbol. An incomplete quote is reported as a warning, not a failure.

### Exit Codes

- `0` — all hard checks passed (warnings are OK)
- Non-zero — at least one hard safety check failed

---

## Offline Checks (Always Run)

These checks require no IBKR connectivity:

| Check | What It Verifies | Fail Condition |
|-------|-----------------|----------------|
| Project root detected | `app/` directory exists at project root | Project structure missing |
| Config file exists | Config YAML file found on disk | File path invalid |
| Config loads successfully | YAML parses without errors | Malformed YAML |
| Config mode is paper | `trading_mode: paper` | `trading_mode: live` |
| Read-only API required | `ibkr.read_only_api: true` | `false` or missing |
| Live trading disabled | `allow_live: false` | `true` |
| live.yaml safety | `configs/live.yaml` has `allow_live: false` | `allow_live: true` |
| Forbidden broker calls absent | No `ib.placeOrder(`, `ib.cancelOrder(`, `ib.reqGlobalCancel(` in `app/*.py` or `scripts/*.py` | Any forbidden call found |
| Required docs exist | `AI_CONTEXT.md`, `PROJECT_STATUS.md`, `SAFETY_INVARIANTS.md` | Any doc missing |

---

## Online Checks (With `--connect`)

These checks require TWS Paper Trader to be running:

| Check | What It Verifies | Fail Condition |
|-------|-----------------|----------------|
| TWS port reachable | TCP connection to host:port succeeds | Connection refused |
| Account summary readable | IBKRClient connects with `readonly=True`, reads managed accounts | Connection fails, no accounts |
| Quote (optional) | MarketDataManager fetches quote for symbol | Incomplete quote is WARN only |

### Connection Safety Guarantees

When `--connect` is used:

- `IBKRClient` is created with `read_only_api=True` (passed as `readonly=True` to `connectAsync`)
- `managedAccounts()` is called (read-only)
- `openTrades()` is **never** called
- `reqOpenOrders()` is **never** called
- `submit_order()` is **never** called
- `cancel_order()` is **never** called
- `placeOrder()` is **never** called
- `cancelOrder()` is **never** called
- `reqGlobalCancel()` is **never** called

---

## Example Output

### Offline-only (PASS)

```
==============================================================
  QUAGENT HEALTHCHECK
==============================================================
  [PASS] Project root detected  (D:\quagent)
  [PASS] Config file exists  (D:\quagent\configs\paper.yaml)
  [PASS] Config loads successfully
  [PASS] Config mode is paper
  [PASS] Read-only API required
  [PASS] Live trading disabled
  [PASS] live.yaml safety  (allow_live=false)
  [PASS] Forbidden broker calls absent
  [PASS] Required docs exist  (3 docs found)
==============================================================
  Final result: PASS
==============================================================
```

### With `--connect --symbol SPY`

```
==============================================================
  QUAGENT HEALTHCHECK
==============================================================
  [PASS] Project root detected  (D:\quagent)
  [PASS] Config file exists  (D:\quagent\configs\paper.yaml)
  [PASS] Config loads successfully
  [PASS] Config mode is paper
  [PASS] Read-only API required
  [PASS] Live trading disabled
  [PASS] live.yaml safety  (allow_live=false)
  [PASS] Forbidden broker calls absent
  [PASS] Required docs exist  (3 docs found)
  [PASS] TWS port reachable  (127.0.0.1:7497)
  [PASS] Account summary readable  (Managed accounts: DU123456)
  [WARN] Quote (SPY)  (quality=incomplete, is_stale=True)
==============================================================
  Final result: PASS
==============================================================
```

### Offline (FAIL example — broken config)

```
==============================================================
  QUAGENT HEALTHCHECK
==============================================================
  [PASS] Project root detected  (D:\quagent)
  [PASS] Config file exists  (D:\quagent\configs\paper.yaml)
  [PASS] Config loads successfully
  [FAIL] Config mode is paper  (trading_mode='live')
  [PASS] Read-only API required
  [FAIL] Live trading disabled  (allow_live=True)
==============================================================
  Final result: FAIL
==============================================================
```

---

## Running Tests

```powershell
cd D:\quagent
.\.venv\Scripts\Activate.ps1
pytest tests\test_quagent_healthcheck.py -v
```

All healthcheck tests are fully offline and use mocks. No TWS connection is required.

---

## Troubleshooting

### "Config file not found"

Verify the config path is correct:

```powershell
python scripts\quagent_healthcheck.py --config configs\paper.yaml
```

Ensure `configs\paper.yaml` exists in the project root.

### "TWS port reachable: FAIL"

TWS Paper Trader must be running and listening on the configured port (default `7497`). Check:

1. TWS is open and logged in
2. API settings: `Edit > Global Configuration > API > Settings`
3. Socket port matches config (`7497` for paper)
4. "Enable ActiveX and Socket Clients" is checked

### "Account summary readable: FAIL"

TWS may be blocking the connection. Verify:

1. TWS Read-Only API is enabled (checked in API settings)
2. Client ID is not already in use by another connection
3. TWS is not showing a popup/dialog blocking API

### "Quote incomplete: WARN"

Delayed quotes may not be available for all symbols. This is a warning, not a failure. Possible causes:

1. Market is closed and no delayed data is cached
2. Symbol is invalid or not found
3. IBKR delayed data service temporarily unavailable

---

## Safety Invariants

This healthcheck script respects all QuAgent safety invariants:

1. **No order submission** — `ib.placeOrder()` is never called
2. **No order cancellation** — `ib.cancelOrder()` is never called
3. **No global cancel** — `ib.reqGlobalCancel()` is never called
4. **Read-only by default** — `readonly=True` on all IBKR connections
5. **Paper mode required** — live mode is rejected
6. **allow_live must be false** — enforced in both `paper.yaml` and `live.yaml`
7. **Forbidden calls scanned** — source tree is scanned for dangerous patterns

See `docs/SAFETY_INVARIANTS.md` for the full list of safety rules.
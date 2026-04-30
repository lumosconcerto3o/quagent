# QuAgent Safety & Architecture Audit Report
**Date:** April 29, 2026  
**Status:** PRE-PRODUCTION REVIEW  
**Goal:** Identify safety gaps before any IBKR connection or order submission

---

## EXECUTIVE SUMMARY

**Overall Safety Rating:** ⚠️ **MEDIUM RISK** - Multiple safety gaps identified

**Key Findings:**
- ✅ Core architecture is sound (risk engine, OMS, execution engine properly separated)
- ✅ Paper/live separation implemented at config level
- ✅ Kill switch circuit breaker implemented
- ✅ All tests offline (no IBKR connection required)
- ⚠️ **CRITICAL:** Live trading config missing `allow_live=false` flag
- ⚠️ **CRITICAL:** No dry-run capability (all test orders could become real)
- ⚠️ **HIGH:** No asset class restrictions (options/futures/forex not blocked)
- ⚠️ **HIGH:** Execution engine doesn't check kill switch state
- ⚠️ **HIGH:** Emergency scripts missing safety features (dry-run, order cancellation)
- ⚠️ **MEDIUM:** No manual confirmation at execution (only at config level)
- ⚠️ **MEDIUM:** Market data sanity check incomplete (always passes)
- ⚠️ **MEDIUM:** Broker rejection handling minimal

---

## FILES INSPECTED

**Core Application (13 modules):**
- app/config.py
- app/schemas.py
- app/risk.py
- app/oms.py
- app/execution.py
- app/ibkr_client.py
- app/kill_switch.py
- app/storage.py
- app/main.py
- app/account.py
- app/market_data.py
- app/logger.py
- app/utils.py

**Scripts (5 utilities):**
- scripts/run_paper.py
- scripts/check_account.py
- scripts/submit_signal.py
- scripts/emergency_cancel_all.py
- scripts/emergency_flatten.py

**Configuration (2 YAML files):**
- configs/paper.yaml
- configs/live.yaml

**Tests (5 test modules):**
- tests/test_config.py
- tests/test_schemas.py
- tests/test_risk.py
- tests/test_oms.py
- tests/test_kill_switch.py

---

## CURRENT ARCHITECTURE SUMMARY

### Signal Flow
```
Signal Input
    ↓
TradingSystem.process_signal()
    ├─ Kill Switch Check
    ├─ Account Refresh
    ├─ RiskEngine.check_signal()  [Deterministic validation]
    ├─ OMS.create_order_from_signal()
    ├─ ExecutionEngine.execute_order()
    │   └─ IBKRClient.submit_order()  [STUB - not implemented]
    └─ Database.log_order()
```

### Configuration Hierarchy
```
QuAgentConfig (Pydantic)
├── trading_mode: "paper" or "live"
├── allow_live: bool  [Default: false]
├── ibkr: IBKRConfig
│   ├── host: "127.0.0.1"
│   ├── port: 7497 (paper) or 7496 (live)
│   └── client_id: int
├── account: AccountConfig
│   ├── max_position_size: float
│   ├── buying_power_limit: float
│   ├── max_daily_loss_pct: float
│   └── enable_safeguards: bool
├── logging: LoggingConfig
├── database: DatabaseConfig
└── trading: TradingConfig
```

---

## AUDIT FINDINGS

### A. CONFIG SCHEMA

**A.1: Current config structure**
- ✅ Uses `QuAgentConfig` base model with `trading_mode` field
- ✅ Pydantic validation on all fields
- ✅ Clear separation: trading_mode ("paper" vs "live"), allow_live flag

**A.2: Mode naming**
- ✅ Uses `trading_mode` (not just "mode")

**A.3: Risk limits naming**
- ✅ Uses `account.max_position_size` (appropriate for MVP)
- ❌ No `max_order_notional_usd` field (not enforced in notional terms)
- ❌ No separate checks for daily max loss in USD (only percentage)

**A.4: Live config safety - allow_live flag**
- ❌ **CRITICAL ISSUE**: `configs/live.yaml` does NOT contain `allow_live: false`
- ❌ Means live.yaml can be used without explicit flag setting
- ✅ Config loader checks it (`if trading_mode == 'live' and not allow_live: raise`)
- ⚠️ But the YAML file should explicitly set it for defense-in-depth

**A.5: Live trading requires manual confirmation**
- ⚠️ Only done at TradingSystem initialization (config validation)
- ❌ Not enforced at order submission time
- ❌ Scripts don't require `--confirm-live` flag to submit orders in live mode

**A.6: Paper and live separation**
- ✅ Separated at config level (trading_mode field)
- ✅ Different ports (7497 vs 7496)
- ✅ Different limits (paper: 10k, live: 5k)

---

### B. RISK ENGINE

**B.1: Does RiskEngine call IBKR directly?**
- ✅ NO - only uses data passed as parameters

**B.2: Reject unsupported asset classes**
- ❌ NO - no check for equities vs options vs futures vs forex
- ⚠️ MVP should block everything except equities (stocks)

**B.3: Reject short selling if disabled**
- ❌ NO - no short-selling flag in config
- ❌ System allows both BUY and SELL without checking config

**B.4: Reject missing stop loss when require_stop_loss=true**
- ❌ NO - no stop loss feature in MVP
- ❌ No require_stop_loss config field

**B.5: Reject orders above max_order_notional_usd**
- ❌ NO - `max_order_notional_usd` field doesn't exist
- ⚠️ Only checks position count, not notional value
- ⚠️ Issue: Could submit 10,000 x $1,000 stock (not caught by current max_position_size check)

**B.6: Check daily loss breaches**
- ✅ YES - `_check_daily_loss_limit()` checks `daily_realized_loss`
- ⚠️ ISSUE: `daily_realized_loss` is always 0 (never updated by system)
- ⚠️ Only updated via manual call to `record_trade()` from main.py

**B.7: Consume kill switch state**
- ❌ NO - RiskEngine doesn't check kill switch
- ✅ Kill switch checked in TradingSystem.process_signal() before risk check
- ⚠️ Not at the engine level (should be redundant check)

**B.8: Reject stale or incomplete market data**
- ❌ NO - `_check_market_sanity()` is incomplete placeholder
- ❌ Always returns `passed=True` regardless of actual data
- ⚠️ `# TODO: Fetch current price and validate` comment indicates unfinished

**B.9: All rejections have explicit reasons**
- ✅ YES - Every failure in `result.failures` includes detailed reason
- ✅ All check results logged with context

---

### C. ORDER MANAGEMENT SYSTEM (OMS)

**C.1: Does OMS call IBKR directly?**
- ✅ NO - only manages order records locally

**C.2: Explicit order status lifecycle**
- ✅ YES - OrderStatus enum: PENDING → SUBMITTED → FILLED / CANCELLED / REJECTED / ERROR

**C.3: Can invalid state transitions happen?**
- ✅ NO - `update_order_status()` uses proper enum and handles each status explicitly

**C.4: Can a rejected order be submitted later?**
- ⚠️ YES - Once rejected, new order must be created from new signal
- ✅ No silent re-use of rejected order (good)

**C.5: Local vs broker order ID tracking**
- ⚠️ **ISSUE** - Only has `order_id` (local sequence number)
- ❌ No separate tracking of broker's order ID (will be needed when IBKR connects)
- ⚠️ When ExecutionEngine calls `client.submit_order()`, IBKR returns order ID but it's not captured

---

### D. EXECUTION ENGINE

**D.1: Does execution.py call ib.placeOrder?**
- ⚠️ YES (future) - `await self.client.submit_order()` will eventually call IBKR
- ✅ Currently a TODO stub (safe now, dangerous when implemented)

**D.2: Is dry_run available?**
- ❌ **CRITICAL** - NO dry-run capability
- ❌ No way to test order submission without executing real orders

**D.3: Does dry_run default to true?**
- ❌ NO dry_run exists at all (so defaults to FALSE/LIVE)

**D.4: Can dry_run accidentally submit an order?**
- ✅ Not applicable (no dry_run)
- ⚠️ But the risk is REAL: any call to execute_order() will eventually submit to broker

**D.5: Does execution require OMS status VALIDATED before submission?**
- ❌ NO - Order created in OMS with status=PENDING, immediately submitted
- ❌ No intermediate VALIDATED state to gate execution
- ⚠️ Should be: PENDING → VALIDATED → SUBMITTED

**D.6: Does execution check kill switch before submission?**
- ❌ **HIGH PRIORITY** - NO
- ✅ Kill switch is checked in TradingSystem.process_signal() (upstream)
- ⚠️ But ExecutionEngine should also check for defense-in-depth
- ⚠️ If kill switch set AFTER signal passed to executor, order still submits

**D.7: Is live trading blocked unless allow_live=true?**
- ✅ YES - Checked in TradingSystem.__init__()
- ✅ Raises ValueError if live mode + allow_live=false
- ⚠️ Only at startup, not at execution time

**D.8: Is live trading blocked unless manual confirmation is present?**
- ❌ NO - Only safeguard is config validation
- ❌ No --confirm flag in execution scripts for live mode
- ⚠️ If TradingSystem() is created with live config + allow_live=true, orders submit without prompt

**D.9: Are market orders blocked in live mode?**
- ❌ NO - OrderType enum includes MARKET, no live-mode restriction
- ⚠️ Live should require LIMIT orders only

**D.10: Are options/futures/forex blocked in MVP?**
- ❌ NO - Signal schema only has `symbol: str` (no asset class field)
- ⚠️ No validation that symbol is valid equity ticker

**D.11: Are broker rejections handled and logged?**
- ⚠️ PARTIAL - Errors logged but no detailed broker error parsing
- ⚠️ Order marked as ERROR status with generic error_msg
- ❌ No retry logic or broker-specific error interpretation

---

### E. IBKR CLIENT

**E.1: Does it only manage connection lifecycle?**
- ✅ YES - connects, disconnects, fetches data, submits orders

**E.2: Does it contain any actual order placement method?**
- ⚠️ YES but it's a TODO stub:
  ```python
  async def submit_order(self, ...):
      # TODO: Implement ib_insync connection
      return None
  ```
- ✅ Currently returns None (safe), but will need real implementation

**E.3: Does it expose raw IBKR object?**
- ✅ NO - No public `ib` or `client` attribute
- ✅ Properly encapsulated

**E.4: Are connection failures handled clearly?**
- ✅ YES - Explicit try/except with logged errors
- ✅ Returns False/None on connection failure

---

### F. EMERGENCY SCRIPTS

**F.1: Does emergency_cancel_all.py require --confirm?**
- ✅ YES - Requires `--confirm` flag
- ✅ Prints warning if not confirmed

**F.2: Does emergency_flatten.py require --confirm?**
- ✅ YES - Requires `--confirm` flag
- ✅ Prints warning if not confirmed

**F.3: Does emergency_flatten.py support --dry-run?**
- ❌ NO - No dry-run flag
- ⚠️ HIGH PRIORITY: Should have --dry-run before confirming flatten

**F.4: Does emergency_flatten.py cancel open orders before flattening?**
- ❌ **CRITICAL ISSUE** - NO
- ❌ Workflow: immediately creates SELL/BUY signals for all positions
- ⚠️ Risk: Could submit 100 orders if 100 positions open, without cancelling pending orders
- ⚠️ Better flow: cancel all pending → then close positions

**F.5: Does emergency_flatten.py avoid options/futures/forex in MVP?**
- ❌ NO - No asset class checks
- ⚠️ Would try to close any symbol in account.positions

---

### G. TESTS

**G.1: Safety-critical behaviors currently tested**
- ✅ Config schema validation (test_config.py)
- ✅ Signal schema validation (test_schemas.py)
- ✅ Risk checks (position size, buying power, daily loss) (test_risk.py)
- ✅ OMS order lifecycle (test_oms.py)
- ✅ Kill switch behavior (test_kill_switch.py)
- ✅ Order status transitions

**G.2: Safety-critical tests MISSING**
- ❌ Live trading safeguards (allow_live enforcement)
- ❌ Dry-run functionality
- ❌ Asset class restrictions
- ❌ Manual confirmation flow
- ❌ Kill switch integration with execution
- ❌ Broker rejection handling
- ❌ Emergency flatten safety (cancel then flatten)
- ❌ Market data staleness check
- ❌ Notional order size limits
- ❌ Short selling restrictions (if disabled)

**G.3: Do tests require IBKR connection?**
- ✅ NO - All tests run offline

**G.4: Are all tests offline?**
- ✅ YES - 30 tests all pass without IBKR

**G.5: What tests should be added before paper order submission?**
- Test dry-run order creation
- Test that TradingSystem blocks live orders without allow_live=true
- Test kill switch blocks execution
- Test emergency_flatten dry-run
- Test emergency_flatten cancels pending before closing
- Test asset class rejection (should reject options)
- Test market order rejection in live mode
- Test broker error handling

---

## SAFETY ISSUES FOUND

### CRITICAL (Must fix before ANY order submission)

| Issue | Location | Severity | Impact |
|-------|----------|----------|--------|
| Live config missing `allow_live=false` | configs/live.yaml | CRITICAL | Could enable live trading without explicit flag |
| No dry-run capability | execution.py | CRITICAL | Impossible to test orders without submitting to broker |
| Execution doesn't check kill switch | execution.py | CRITICAL | Kill switch can be bypassed if set after signal passes |
| Emergency flatten doesn't cancel pending orders first | scripts/emergency_flatten.py | CRITICAL | Could submit many orders before flatten completes |

### HIGH PRIORITY (Should fix before live trading)

| Issue | Location | Severity | Impact |
|-------|----------|----------|--------|
| No order state validation before execution | execution.py | HIGH | Orders submit without VALIDATED state gate |
| No asset class restrictions | schemas.py / risk.py | HIGH | Could try to trade options/futures/forex in MVP |
| No market order blocking in live | execution.py | HIGH | Live mode allows market orders (gap fills, slippage risk) |
| No manual confirmation at execution | scripts/*.py | HIGH | Can submit live orders with single flag in config |
| No separate broker order ID tracking | oms.py | HIGH | Can't reconcile orders with broker after submission |

### MEDIUM PRIORITY (Should fix before full production)

| Issue | Location | Severity | Impact |
|-------|----------|----------|--------|
| Market data sanity check incomplete | risk.py | MEDIUM | Always passes, stale data not rejected |
| Daily loss tracking never updated | main.py | MEDIUM | Daily loss limit check always passes (not enforced) |
| No max notional order value check | risk.py | MEDIUM | Could submit huge orders (10k x $1000 stock) |
| Broker rejection handling minimal | execution.py | MEDIUM | Errors logged but not interpreted for retry/escalation |
| No short selling restrictions | config.py | MEDIUM | System allows selling without owning (margin default) |

---

## SCHEMA MISMATCHES FOUND

### Missing Fields in Config

```yaml
# Should add to AccountConfig:
max_order_notional_usd: 100000  # Max value per order
allow_short_selling: false      # Restrict to long-only
allow_margin: false             # Restrict to cash account
require_stop_loss: false        # Mandate stop loss in live

# Should add to TradingConfig:
dry_run: true                   # Default to dry-run for safety
```

### Missing Fields in Signal Schema

```python
# Should add to Signal:
asset_class: str = "STOCK"  # Restrict to STOCK in MVP
dry_run: bool = False       # Allow per-signal dry-run override
requires_stop_loss: bool = False  # For future use
```

### Missing Fields in Order Schema

```python
# Should add to Order:
broker_order_id: Optional[int] = None  # Separate from local order_id
broker_status: Optional[str] = None    # Sync with broker state
```

---

## TESTS CURRENTLY PASSING

```
tests/test_config.py ............................ 4 tests ✅
tests/test_schemas.py ........................... 6 tests ✅
tests/test_risk.py ............................. 8 tests ✅
tests/test_oms.py ............................. 7 tests ✅
tests/test_kill_switch.py ....................... 5 tests ✅

TOTAL: 30 tests pass offline ✅
```

---

## TESTS MISSING (Priority Order)

### Tier 1: MUST ADD before ANY paper order submission

1. **test_live_trading_requires_allow_live**
   - Verify TradingSystem raises error if trading_mode=live and allow_live=false

2. **test_execution_checks_kill_switch**
   - Verify ExecutionEngine blocks order if kill_switch active

3. **test_dry_run_does_not_submit**
   - Verify dry-run orders don't call client.submit_order()

4. **test_emergency_flatten_cancels_pending_first**
   - Verify flatten cancels open orders before creating close signals

5. **test_asset_class_restrictions**
   - Verify system rejects options/futures symbols

6. **test_live_blocks_market_orders**
   - Verify MARKET orders rejected in live mode

### Tier 2: SHOULD ADD for production readiness

7. test_daily_loss_tracking_enforced
8. test_broker_order_id_tracking
9. test_notional_order_limits
10. test_manual_confirmation_required_for_live
11. test_market_data_staleness_check
12. test_short_selling_restrictions
13. test_emergency_flatten_dry_run

---

## MINIMAL FIX PLAN (Ordered by Priority)

### PHASE 1: Critical Safety Fixes (DO NOT SKIP)

**Priority 1.1:** Add `allow_live: false` to live.yaml
- File: configs/live.yaml
- Change: Add explicit `allow_live: false`
- Risk: **PREVENTS ACCIDENTAL LIVE TRADING**

**Priority 1.2:** Implement dry-run mode
- Files: app/execution.py, app/schemas.py
- Changes:
  - Add `dry_run: bool = True` to QuAgentConfig
  - Add `dry_run: bool = False` to Signal schema
  - Modify execute_order() to skip client.submit_order() if dry_run=true
  - Add --dry-run flag to scripts
- Risk: **PREVENTS UNINTENDED BROKER SUBMISSION**

**Priority 1.3:** Add kill switch check to ExecutionEngine
- File: app/execution.py
- Change: Add `if self.risk_engine.kill_switch.is_triggered(): return False` in execute_order()
- Risk: **PREVENTS BYPASS OF CIRCUIT BREAKER**

**Priority 1.4:** Fix emergency_flatten to cancel pending first
- File: scripts/emergency_flatten.py
- Changes:
  - Call `await system.emergency_cancel_all()` before creating close signals
  - Add --dry-run flag support
- Risk: **PREVENTS ORDER EXPLOSION**

### PHASE 2: High Priority Fixes (Before Live)

**Priority 2.1:** Add order state VALIDATED gate
- Files: app/oms.py, app/execution.py
- Changes:
  - Add OrderStatus.VALIDATED state
  - Update create_order_from_signal() to set VALIDATED
  - Update execute_order() to check status is VALIDATED

**Priority 2.2:** Add asset class restrictions
- Files: app/schemas.py, app/risk.py
- Changes:
  - Add `asset_class: str = "STOCK"` to Signal
  - Add check in RiskEngine to reject non-STOCK
  - Add --asset-class validation in scripts

**Priority 2.3:** Block market orders in live mode
- Files: app/execution.py, app/risk.py
- Changes:
  - Add check: if trading_mode=live and order_type=MARKET: reject
  - Log as safety violation

**Priority 2.4:** Add manual --confirm-live flag
- Files: scripts/submit_signal.py, scripts/run_paper.py
- Changes:
  - Add --confirm-live flag required when trading_mode=live
  - Print confirmation prompt before execution

### PHASE 3: Medium Priority Fixes (Production)

**Priority 3.1:** Track broker_order_id separately
- Files: app/schemas.py, app/oms.py, app/execution.py
- Changes:
  - Add broker_order_id field to Order
  - Update execute_order() to capture returned order_id from client

**Priority 3.2:** Implement real market_sanity_check
- File: app/risk.py
- Changes:
  - Fetch current price from market_data
  - Reject if price stale (>60 seconds old)
  - Reject if price invalid (<=0)

**Priority 3.3:** Add notional order limits
- Files: app/config.py, app/risk.py
- Changes:
  - Add max_order_notional_usd to AccountConfig
  - Add check: quantity * price > max_notional? → reject

---

## EXACT POWERSHELL COMMANDS TO RUN

### 1. Verify Current State

```powershell
cd D:\quagent
$env:PYTHONPATH = ""

# Run all tests
pytest -v

# Expected: 30 tests pass

# Run specific test file
pytest tests/test_risk.py -v

# Check live config
Get-Content configs\live.yaml | Select-String "allow_live"

# Expected: (nothing - field is missing!)
```

### 2. Audit Checklist Verification

```powershell
# Check if dry_run exists in config
pytest tests/test_config.py::test_config_validation -v
# Expected: PASSED (but dry_run field not yet present)

# Check if kill switch is tested
pytest tests/test_kill_switch.py -v
# Expected: 5 tests PASS

# Check if emergency scripts require --confirm
Get-Content scripts\emergency_cancel_all.py | Select-String "confirm"
Get-Content scripts\emergency_flatten.py | Select-String "confirm"
# Expected: both should have --confirm flag

# List all Signal validations
pytest tests/test_schemas.py::test_signal_validation -v
# Expected: PASSED (but asset_class not yet validated)
```

### 3. Prepare for Fixes

```powershell
# Backup current configs
Copy-Item configs\live.yaml configs\live.yaml.backup
Copy-Item configs\paper.yaml configs\paper.yaml.backup

# Run tests before fixes
pytest -v --tb=short > audit_baseline.txt

# Check test count
pytest --collect-only | grep "test session starts" -A 5
# Expected: 30 tests
```

---

## NEXT STEPS

### If continuing with current implementation:

1. ⚠️ **DO NOT** submit ANY orders to IBKR until Priority 1 fixes complete
2. ⚠️ **DO NOT** enable live trading (allow_live=true) until Priority 2 fixes complete
3. ✅ Paper trading tests are safe (config defaults to paper mode)
4. ✅ Can continue testing risk engine and OMS logic offline

### If implementing fixes:

1. Start with Phase 1 (4 fixes, ~30 minutes)
2. Run full test suite after each fix
3. Add new tests for each fix
4. Phase 2 (~2 hours)
5. Phase 3 can be deferred (~1 hour each)

---

## CONCLUSION

**The infrastructure is architecturally sound**, but **several safety gaps exist before production use**.

**Status before IBKR connection:**
- ✅ Can safely test locally
- ✅ All core logic working
- ❌ NOT READY for paper trading without Phase 1 fixes
- ❌ NOT READY for live trading without Phase 1+2 fixes

**Recommendation:** Implement Phase 1 fixes (~1 hour), add 7 critical tests (~1 hour), then safe for paper trading.

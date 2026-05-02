# QuAgent Project Status

## Current Phase

Real-data dry-run pipeline implemented and verified.

## Completed

- Project skeleton
- Config system
- Logger
- SQLite storage
- Schemas
- RiskEngine safety patches
- OMS state machine
- ExecutionEngine dry-run safety
- Kill switch
- Emergency flatten dry-run planning
- IBKR read-only connection
- Read-only API compatibility
- Delayed market data support
- Account debug mode
- Real-data dry-run pipeline
- GitHub private repo setup

## Stable Checkpoints

- v0.1-readonly-stable
- v0.2-real-data-dry-run

## Latest Verified Test Status

Command:

pytest -v

Result:

112 passed

## Latest Verified Dry-Run

Command:

.venv\Scripts\python.exe scripts\real_data_dry_run.py --config configs\paper.yaml --symbol SPY

Verified result:

- Account summary was read from TWS paper.
- SPY delayed quote was complete.
- Risk decision passed.
- OMS local order was created.
- broker_order_id was None.
- Submitted to broker: NO.
- No ib.placeOrder call occurred.

## Current External Setup

- TWS paper account is available.
- TWS API socket: 127.0.0.1:7497
- TWS Read-Only API: enabled.
- SPY delayed quote can be fetched when IBKR delayed data is available.
- Account summary can be fetched.

## Useful Commands

Run tests:

cd D:\quagent
.\.venv\Scripts\Activate.ps1
pytest -v

Check account:

python scripts\check_account.py --config configs\paper.yaml

Check quote:

python scripts\check_account.py --config configs\paper.yaml --quote SPY

Run real-data dry-run:

.venv\Scripts\python.exe scripts\real_data_dry_run.py --config configs\paper.yaml --symbol SPY

Diagnose connection:

python scripts\diagnose_connection.py --port 7497

Safety grep:

Select-String -Path app\*.py,scripts\*.py -Pattern "placeOrder|cancelOrder|reqGlobalCancel"

## Next Phase

Audit and stabilize real-data dry-run semantics.

Before paper order execution, resolve or explicitly accept:

1. Dry-run output currently shows local OMS status SUBMITTED while broker submission is NO.
2. Confirm whether to rename local dry-run status to DRY_RUN_SUBMITTED or print it more clearly.
3. Confirm submit_order() remains disabled.
4. Confirm TWS Read-Only API remains enabled.
5. Do not implement real paper orders without a separate explicit phase.

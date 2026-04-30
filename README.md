# QuAgent - Quantitative Trading System for IBKR

A **safety-first** trading infrastructure for IBKR (Interactive Brokers) with paper trading, strict risk controls, and comprehensive logging.

**Key Features:**
- ✅ Paper trading first, live trading with explicit safeguards
- ✅ Deterministic risk checks (no AI agent order placement)
- ✅ Kill switch for emergency shutdown
- ✅ Complete trade logging to SQLite
- ✅ Structured logging to console + file
- ✅ Windows-ready (Python 3.11+)

## Project Structure

```
D:\quagent
├── app/                       # Core application modules
│   ├── __init__.py
│   ├── main.py                # Main TradingSystem orchestrator
│   ├── config.py              # Configuration loader + validation
│   ├── schemas.py             # Pydantic data models
│   ├── logger.py              # Structured logging
│   ├── utils.py               # Utilities
│   ├── ibkr_client.py         # IBKR connection wrapper
│   ├── account.py             # Account state management
│   ├── market_data.py         # Market data caching
│   ├── risk.py                # Deterministic risk checks
│   ├── oms.py                 # Order Management System
│   ├── execution.py           # Order execution engine
│   ├── kill_switch.py         # Emergency circuit breaker
│   └── storage.py             # SQLite database manager
│
├── configs/
│   ├── paper.yaml             # Paper trading config
│   └── live.yaml              # Live trading config (conservative)
│
├── scripts/
│   ├── run_paper.py             # Main paper trading loop
│   ├── check_account.py         # Read-only account/position/quote check
│   ├── diagnose_connection.py   # IBKR connection diagnostics
│   ├── submit_signal.py         # Submit a trading signal
│   ├── emergency_cancel_all.py  # Cancel all orders (requires --confirm)
│   └── emergency_flatten.py     # Close all equity positions (requires --confirm)
│
├── tests/
│   ├── test_config.py
│   ├── test_schemas.py
│   ├── test_risk.py
│   ├── test_oms.py
│   └── test_kill_switch.py
│
├── examples/
│   ├── sample_signal.json
│   ├── sample_bracket_signal.json
│   └── agent_signal_example.json
│
├── data/                      # SQLite database stored here
├── logs/                      # Log files stored here
├── requirements.txt
├── README.md
└── .env.example
```

## Windows Setup

### Prerequisites

- **Python 3.11+** - Download from https://www.python.org/downloads/ (Windows installer)
- **IB Gateway or TWS** - Running locally on port 7497 (paper) or 7496 (live)
- **Git** (optional) - For version control

### Step 1: Install Python Dependencies

Open PowerShell in `D:\quagent` and run:

```powershell
# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### Step 2: Configure IBKR Connection

Ensure **IB Gateway** or **TWS** is running and the API socket is enabled:

| Application | Mode  | Port |
|---|---|---|
| TWS           | Paper | 7497 |
| TWS           | Live  | 7496 |
| IB Gateway    | Paper | 4002 |
| IB Gateway    | Live  | 4001 |

In TWS/Gateway API settings, enable **"Enable ActiveX and Socket Clients"** and optionally
**"Read-Only API"** (recommended — prevents accidental orders from any API client).

### Step 3: Diagnose the connection (optional but recommended)

```powershell
cd D:\quagent
.\.venv\Scripts\Activate.ps1
python scripts/diagnose_connection.py --port 7497
```

### Step 4: Run read-only account check

> **Important:** All scripts must be run from the project root (`D:\quagent`), not from
> inside the `scripts\` folder. The scripts add `D:\quagent` to `sys.path` automatically
> so `import app` works without setting `PYTHONPATH` manually.

```powershell
cd D:\quagent
.\.venv\Scripts\Activate.ps1

# Check account, positions, open orders (read-only, no orders sent)
python scripts/check_account.py --config configs/paper.yaml

# With optional live quote
python scripts/check_account.py --config configs/paper.yaml --quote SPY

# Run main paper trading loop
python scripts/run_paper.py --config configs/paper.yaml
```

### Step 5: Run Tests

`tests/conftest.py` automatically adds the project root to `sys.path`. No manual
`PYTHONPATH` configuration required.

```powershell
# Run all tests (82 tests, offline, no IBKR connection needed)
pytest -v

# Run specific test module
pytest tests/test_risk.py -v

# Run with coverage report
pytest tests/ --cov=app

# Run with verbose output and short traceback
pytest tests/ -v -s
```

**Expected:** All 82 tests pass (100% offline, no IBKR connection needed) ✅

## Configuration

### Paper Trading (`configs/paper.yaml`)

Default configuration for safe testing:
- Port: `7497` (IB Gateway/TWS paper trading)
- Max position size: `10,000` shares
- Max daily loss: `2.0%`
- Safeguards: ✅ Enabled

### Live Trading (`configs/live.yaml`)

Extremely conservative configuration:
- Port: `7496` (IB Gateway live)
- Max position size: `5,000` shares (smaller)
- Max daily loss: `1.0%` (tighter)
- Requires explicit `allow_live=true` in config
- Manual confirmation at startup

## Signals & Orders

### Submit a Signal

```powershell
# Via JSON file
python scripts/submit_signal.py --file examples/sample_signal.json

# Via command line
python scripts/submit_signal.py --symbol AAPL --action BUY --quantity 100 --limit-price 150.00
```

### Signal Format (JSON)

```json
{
  "symbol": "AAPL",
  "action": "BUY",
  "quantity": 100,
  "limit_price": 150.00,
  "order_type": "LIMIT",
  "strategy_name": "manual_signal",
  "metadata": {
    "reason": "Example signal"
  }
}
```

## Risk Controls

The system enforces **deterministic risk checks**:

1. **Position Size Limit** - No order exceeding `max_position_size`
2. **Buying Power** - BUY orders check available funds
3. **Daily Loss Limit** - Stops trading if daily loss > threshold
4. **Existing Position** - Warns if stacking large positions

**All checks must pass (PASS) or signal is rejected (REJECT).**

## Emergency Controls

### Emergency Cancel All

```powershell
python scripts/emergency_cancel_all.py --confirm
```

Cancels all open orders immediately.

### Emergency Flatten

```powershell
python scripts/emergency_flatten.py --confirm
```

Closes all positions at market price.

### Kill Switch

When triggered:
- No new signals accepted
- All operations blocked
- Can only be reset manually

## Logging

- **Console:** Real-time logs to PowerShell
- **File:** `logs/trading.log` (rotating, 10 MB max, 5 backups)
- **Database:** `data/trading_log.sqlite` (all orders, executions, events)

## Database Queries

```powershell
# Via Python script
python -c "
from app.storage import Database
db = Database()
orders = db.get_orders(limit=10)
for o in orders:
    print(o)
"
```

Or use SQLite GUI:
- Download: https://www.sqlite.org/download.html
- Open: `data/trading_log.sqlite`

## Development

### Running Tests

```powershell
pytest tests/ -v
```

### Code Quality

```powershell
# Format code
black app/ scripts/ tests/

# Check style
flake8 app/ scripts/ tests/

# Type checking
mypy app/
```

### Adding New Features

1. Add schema in `app/schemas.py`
2. Add business logic in appropriate module
3. Write tests in `tests/test_*.py`
4. Update config if needed in `configs/*.yaml`

## Troubleshooting

### ModuleNotFoundError: No module named 'app' (when running scripts directly)

**Solution:** Always run scripts from the project root, not from inside `scripts\`:

```powershell
cd D:\quagent                         # must be here
python scripts/check_account.py ...   # not: cd scripts && python check_account.py
```

Each script adds `D:\quagent` to `sys.path` automatically via a bootstrap block at the
top. Running from the wrong directory makes `Path(__file__).resolve().parents[1]` point
to the wrong folder.

### Connection Error: "Failed to connect to IBKR"

**Solution:**
1. Run the connection diagnostic first: `python scripts/diagnose_connection.py`
2. Ensure IB Gateway/TWS is running and fully logged in (paper account)
3. Enable API: TWS → Edit → Global Configuration → API → Settings →
   "Enable ActiveX and Socket Clients"
4. Port: TWS paper = 7497, IB Gateway paper = 4002
5. Add 127.0.0.1 to Trusted IPs in the same API settings panel

### ModuleNotFoundError: No module named 'ib_insync'

**Solution:**
```powershell
pip install -r requirements.txt
```

### Kill Switch Active

**Solution:**
Reset via code:
```python
from app.kill_switch import KillSwitch
ks = KillSwitch()
ks.reset("manual_reset")
```

## Core Principles

1. **Safety First** - All else secondary
2. **Paper Trading First** - Live only after thorough testing
3. **No AI Order Placement** - Only deterministic risk checks
4. **Fail Closed** - When uncertain, reject trades
5. **Complete Logging** - Every signal, check, order, execution logged

## Next Steps

1. ✅ Test paper trading with sample signals
2. ✅ Verify account connectivity
3. ✅ Run full test suite
4. ⬜ Integrate with AI strategy engine (when ready)
5. ⬜ Deploy to live trading (with extreme caution)

## References

- **ib_insync**: https://github.com/erdewit/ib_insync
- **Pydantic**: https://docs.pydantic.dev/
- **IBKR API**: https://www.interactivebrokers.com/en/trading/ib-api.php


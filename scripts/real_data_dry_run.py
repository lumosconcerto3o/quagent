#!/usr/bin/env python
"""
Real-data dry-run signal pipeline.

Connects to TWS paper account in read-only mode, fetches live (delayed) market
data, runs the full risk + OMS + execution pipeline, and confirms no order is
ever submitted to the broker.

NEVER submits orders.  NEVER calls ib.placeOrder().
ExecutionEngine is always constructed with dry_run=True and guarded before use.

Usage:
    python scripts/real_data_dry_run.py --config configs/paper.yaml --symbol SPY
    python scripts/real_data_dry_run.py --config configs/paper.yaml --symbol AAPL

Safety guards:
    1. Aborts if config.trading_mode == 'live'.
    2. Aborts if IBKRClient.submit_order does not raise NotImplementedError
       (i.e. order submission has somehow been re-enabled).
    3. ExecutionEngine is constructed with dry_run=True and asserted before use.
    4. broker_order_id is verified to remain None after dry-run execution.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio
import json
from datetime import datetime, timezone

from app.config import load_config, QuAgentConfig
from app.ibkr_client import IBKRClient
from app.account import AccountManager
from app.market_data import MarketDataManager
from app.schemas import Signal, OrderAction, OrderType, OrderStatus, MarketQuote
from app.risk import RiskEngine
from app.oms import OrderManagementSystem
from app.execution import ExecutionEngine
from app.logger import get_logger

logger = get_logger(__name__)

_SEP = "=" * 62
_LINE = "-" * 62


# ------------------------------------------------------------------ #
# Guard helpers                                                        #
# ------------------------------------------------------------------ #

async def _verify_submit_disabled(client) -> None:
    """
    Safety guard: call submit_order with dummy args and expect NotImplementedError.
    If it does NOT raise, order submission has been re-enabled — abort immediately.
    """
    try:
        await client.submit_order("__guard__", "BUY", 0.0)
    except NotImplementedError:
        return  # correct — submission is disabled
    raise RuntimeError(
        "SAFETY VIOLATION: IBKRClient.submit_order did not raise NotImplementedError. "
        "Order submission appears to be enabled. Aborting dry-run pipeline."
    )


# ------------------------------------------------------------------ #
# Core pipeline (separated for testability)                           #
# ------------------------------------------------------------------ #

async def run_dry_run(
    config: QuAgentConfig,
    client: IBKRClient,
    account_mgr: AccountManager,
    market_mgr: MarketDataManager,
    symbol: str,
) -> dict:
    """
    Execute the full dry-run signal pipeline.

    Returns a result dict with diagnostic fields (see keys below).
    Raises ValueError  for configuration problems (e.g. live mode).
    Raises RuntimeError for safety violations  (e.g. submit_order re-enabled,
                         dry_run=False, unexpected broker_order_id).

    Result status values:
        "success"      — pipeline completed, order submitted in simulation only
        "failed"       — ExecutionEngine returned False (unexpected)
        "risk_failed"  — risk checks did not pass; no order created
        "aborted"      — aborted before order creation (incomplete quote, etc.)
    """
    # ── Safety guard 1: refuse live config ────────────────────────────
    if config.trading_mode == "live":
        raise ValueError(
            "Refusing to run: trading_mode is 'live'. "
            "This pipeline only runs in paper mode (trading_mode: paper)."
        )

    # ── Safety guard 2: verify submit_order permanently disabled ──────
    await _verify_submit_disabled(client)

    # ── Account data ───────────────────────────────────────────────────
    summary = await account_mgr.get_account_summary()
    positions = await account_mgr.get_positions()

    # ── Market quote ───────────────────────────────────────────────────
    quote = await market_mgr.get_stock_quote(symbol)

    if quote.get("quote_quality") != "complete":
        logger.warning(
            f"Quote for {symbol} is not complete "
            f"(quality={quote.get('quote_quality')}, is_stale={quote.get('is_stale')}). "
            "Aborting pipeline — cannot build a safe signal without a valid price."
        )
        return {
            "status": "aborted",
            "reason": "incomplete_quote",
            "symbol": symbol,
            "quote": quote,
        }

    # ── Build signal ───────────────────────────────────────────────────
    limit_price = float(quote["price"])
    signal = Signal(
        symbol=symbol,
        action=OrderAction.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=limit_price,
        asset_class="STK",
        strategy_name="real_data_dry_run",
    )

    market_quote = MarketQuote(
        symbol=symbol,
        price=float(quote["price"]),
        quote_quality=quote["quote_quality"],
        is_stale=bool(quote["is_stale"]),
    )

    # ── Risk check ─────────────────────────────────────────────────────
    risk = RiskEngine(config)
    positions_map = {p["symbol"]: p["quantity"] for p in positions}
    net_liq = float(summary.get("NetLiquidation", 0.0))
    avail_funds = float(summary.get("AvailableFunds", 0.0))

    risk_result = risk.check_signal(
        signal=signal,
        current_buying_power=avail_funds,
        current_positions=positions_map,
        portfolio_value=net_liq,
        market_data=market_quote,
    )

    if not risk_result.passed:
        return {
            "status": "risk_failed",
            "symbol": symbol,
            "quote": quote,
            "summary": summary,
            "signal": signal,
            "risk_passed": False,
            "risk_failures": risk_result.failures,
            "risk_warnings": risk_result.warnings,
            "broker_order_id": None,
            "dry_run_enforced": True,
        }

    # ── OMS + ExecutionEngine (dry_run=True enforced) ──────────────────
    oms = OrderManagementSystem()
    engine = ExecutionEngine(client, oms, risk, dry_run=True)

    # Safety guard 3: assert engine.dry_run before any execution attempt
    if not engine.dry_run:
        raise RuntimeError(
            "SAFETY VIOLATION: ExecutionEngine.dry_run is not True. Aborting."
        )

    order = oms.create_order_from_signal(signal)
    oms.update_order_status(order.order_id, OrderStatus.VALIDATED)

    success = await engine.execute_order(order)

    # Safety guard 4: broker_order_id must remain None in dry-run
    if order.broker_order_id is not None:
        raise RuntimeError(
            f"SAFETY VIOLATION: broker_order_id={order.broker_order_id} "
            "after dry-run execution. A real order submission must not have occurred."
        )

    return {
        "status": "success" if success else "failed",
        "symbol": symbol,
        "quote": quote,
        "summary": summary,
        "signal": signal,
        "risk_passed": True,
        "risk_warnings": risk_result.warnings,
        "order_id": order.order_id,
        "order_status": order.status.value,   # local OMS state; not a broker confirmation
        "broker_submission": False,            # no broker call was made
        "broker_order_id": order.broker_order_id,  # always None in dry-run
        "execution_mode": "DRY_RUN",
        "dry_run_enforced": engine.dry_run,
        "execution_success": success,
    }


# ------------------------------------------------------------------ #
# Audit report writer                                                  #
# ------------------------------------------------------------------ #

def _write_audit_report(
    result: dict,
    report_dir: Path,
    config_path: str,
    symbol: str,
) -> Path:
    """
    Write a JSON audit record for this dry-run run.

    broker_submission and broker_order_id are ALWAYS written as false/null
    regardless of what the result dict contains — these are safety invariants,
    not derived from runtime state.

    Returns the path of the written file.
    Never raises; logs a warning on write error instead.
    """
    report_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(tz=timezone.utc)
    ts_file = ts.strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"dry_run_{ts_file}_{symbol}.json"

    summary = result.get("summary") or {}
    quote = result.get("quote") or {}
    sig = result.get("signal")

    sig_dict = None
    if sig is not None:
        sig_dict = {
            "action": sig.action.value,
            "quantity": sig.quantity,
            "order_type": sig.order_type.value,
            "limit_price": sig.limit_price,
            "asset_class": sig.asset_class,
            "strategy_name": sig.strategy_name,
        }

    quote_dict = None
    if quote:
        quote_dict = {
            "quote_quality": quote.get("quote_quality"),
            "data_type": quote.get("data_type"),
            "price": quote.get("price"),
            "bid": quote.get("bid"),
            "ask": quote.get("ask"),
            "last": quote.get("last"),
            "close": quote.get("close"),
            "is_stale": quote.get("is_stale"),
            "timestamp": quote.get("timestamp"),
        }

    report = {
        "timestamp_utc": ts.isoformat(),
        "config_path": config_path,
        "symbol": result.get("symbol", symbol),
        "account_id": summary.get("account_id"),
        "net_liquidation": summary.get("NetLiquidation"),
        "available_funds": summary.get("AvailableFunds"),
        "quote": quote_dict,
        "signal": sig_dict,
        "risk_passed": result.get("risk_passed"),
        "risk_failures": result.get("risk_failures"),
        "risk_warnings": result.get("risk_warnings"),
        "oms_order_id": result.get("order_id"),
        "local_oms_status": result.get("order_status"),
        # Safety invariants — always false/null in dry-run, never derived from result
        "broker_submission": False,
        "broker_order_id": None,
        "execution_mode": "DRY_RUN",
        "dry_run_enforced": True,
        "final_status": result.get("status"),
        "reason": result.get("reason"),
        "safety_confirmation": "No broker order was submitted",
    }

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Audit report written: {report_path}")
    except OSError as exc:
        logger.warning(f"Could not write audit report to {report_path}: {exc}")

    return report_path


# ------------------------------------------------------------------ #
# Report formatter                                                     #
# ------------------------------------------------------------------ #

def _print_report(result: dict) -> None:
    """Print a formatted dry-run pipeline report to stdout."""
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    summary = result.get("summary") or {}
    quote = result.get("quote") or {}

    def _fmt(v) -> str:
        return f"${v:,.4f}" if v is not None else "N/A"

    print(f"\n{_SEP}")
    print(f"  DRY-RUN SIGNAL PIPELINE   [{ts}]")
    print(_SEP)

    status = result["status"]

    if status == "aborted":
        print(f"  STATUS  : ABORTED  ({result.get('reason', 'unknown')})")
        print(f"  Symbol  : {result.get('symbol', 'N/A')}")
        if quote:
            print(f"  Quote quality : {quote.get('quote_quality', 'N/A')}")
            print(f"  Is stale      : {quote.get('is_stale', 'N/A')}")
            err = quote.get("ibkr_error")
            if err:
                print(f"  IBKR error    : [{err['code']}] {err['message']}")
        print(_SEP)
        return

    # Account section
    print(f"  Account ID       : {summary.get('account_id', 'N/A')}")
    print(f"  Net Liquidation  : ${summary.get('NetLiquidation', 0):>14,.2f}")
    print(f"  Available Funds  : ${summary.get('AvailableFunds', 0):>14,.2f}")
    print(_LINE)

    # Quote section
    print(f"  Symbol           : {result.get('symbol', 'N/A')}")
    print(f"  Quote Quality    : {quote.get('quote_quality', 'N/A')}")
    print(f"  Data Type        : {quote.get('data_type', 'N/A')}")
    print(f"  Best Price       : {_fmt(quote.get('price'))}")
    print(
        f"  Bid / Ask / Last : "
        f"{_fmt(quote.get('bid'))} / {_fmt(quote.get('ask'))} / {_fmt(quote.get('last'))}"
    )
    print(_LINE)

    # Risk section
    if status == "risk_failed":
        print(f"  Risk Decision : FAILED")
        for f in result.get("risk_failures", []):
            print(f"    FAIL: {f}")
        for w in result.get("risk_warnings", []):
            print(f"    WARN: {w}")
        print(_SEP)
        return

    # Signal section
    sig = result.get("signal")
    if sig:
        print(f"  Signal Action    : {sig.action.value}")
        print(f"  Quantity         : {sig.quantity}")
        print(f"  Order Type       : {sig.order_type.value}")
        print(f"  Limit Price      : {_fmt(sig.limit_price)}")
        print(f"  Strategy         : {sig.strategy_name}")
    print(_LINE)

    # Execution section
    print(f"  Risk Decision    : PASSED")
    warnings = result.get("risk_warnings", [])
    if warnings:
        for w in warnings:
            print(f"    WARN: {w}")
    else:
        print(f"    (no warnings)")
    print(_LINE)
    print(f"  OMS Order ID          : {result.get('order_id', 'N/A')}")
    print(f"  Local OMS Status      : {result.get('order_status', 'N/A')}")
    print(f"  Broker Submission     : NO")
    print(f"  Broker Order ID       : {result.get('broker_order_id')}")
    print(f"  Execution Mode        : {result.get('execution_mode', 'UNKNOWN')}")
    print(f"  Safety Confirmation   : No broker order was submitted")
    print(_SEP)


# ------------------------------------------------------------------ #
# CLI entry point                                                      #
# ------------------------------------------------------------------ #

async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "QuAgent real-data dry-run pipeline — "
            "no order submission, no placeOrder call"
        )
    )
    parser.add_argument(
        "--config",
        default="configs/paper.yaml",
        help="Path to config YAML (default: configs/paper.yaml)",
    )
    parser.add_argument(
        "--symbol",
        default="SPY",
        metavar="SYMBOL",
        help="Symbol to test the pipeline against (default: SPY)",
    )
    parser.add_argument(
        "--report-dir",
        default="data/dry_run_reports",
        metavar="DIR",
        dest="report_dir",
        help="Directory for JSON audit reports (default: data/dry_run_reports)",
    )
    args = parser.parse_args()

    # ── Load config ────────────────────────────────────────────────────
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"[ERROR] Failed to load config '{args.config}': {exc}")
        return

    report_dir = Path(args.report_dir)

    # ── Build components ───────────────────────────────────────────────
    read_only = config.ibkr.read_only_api
    client = IBKRClient(
        host=config.ibkr.host,
        port=config.ibkr.port,
        client_id=config.ibkr.client_id,
        read_only_api=read_only,
    )
    account_mgr = AccountManager(client, read_only_api=read_only)
    market_mgr = MarketDataManager(
        client,
        data_type=config.market_data.data_type,
        stale_seconds=config.market_data.stale_seconds,
    )

    # ── Connect ────────────────────────────────────────────────────────
    symbol = args.symbol.upper()
    print(f"\nConnecting to IBKR at {config.ibkr.host}:{config.ibkr.port} ...")
    connected = await client.connect()
    if not connected:
        print("[ERROR] Connection failed. Is TWS / IB Gateway running?")
        return

    result = None
    try:
        result = await run_dry_run(config, client, account_mgr, market_mgr, symbol)
        _print_report(result)
    except (ValueError, RuntimeError) as exc:
        print(f"\n[ABORT] {exc}")
        result = {
            "status": "aborted",
            "reason": "safety_guard_triggered",
            "symbol": symbol,
        }
    finally:
        if result is not None:
            report_path = _write_audit_report(result, report_dir, args.config, symbol)
            print(f"\n  Audit report: {report_path}")
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

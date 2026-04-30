#!/usr/bin/env python
"""
Read-only account and market data check.
Connects to IBKR paper account, prints account summary, positions,
and open orders.  Optionally fetches a live quote.

Usage (run from project root):
    python scripts/check_account.py --config configs/paper.yaml
    python scripts/check_account.py --config configs/paper.yaml --quote SPY

This script NEVER submits or cancels orders.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio
from datetime import datetime, timezone

from app.config import load_config
from app.ibkr_client import IBKRClient
from app.account import AccountManager
from app.market_data import MarketDataManager
from app.logger import get_logger

logger = get_logger(__name__)

_SEP = "=" * 62
_LINE = "-" * 62


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="QuAgent read-only account check (no order submission)"
    )
    parser.add_argument(
        "--config",
        default="configs/paper.yaml",
        help="Path to config YAML (default: configs/paper.yaml)",
    )
    parser.add_argument(
        "--quote",
        metavar="SYMBOL",
        default=None,
        help="Fetch and print a live quote for SYMBOL (e.g. --quote SPY)",
    )
    parser.add_argument(
        "--debug-account-tags",
        action="store_true",
        dest="debug_account_tags",
        help=(
            "Print every raw accountValues tag returned by ib_insync. "
            "Use this when Net Liquidation / Buying Power show as zero."
        ),
    )
    args = parser.parse_args()

    # ── Load config ────────────────────────────────────────────────────
    try:
        config = load_config(args.config)
    except Exception as exc:
        print(f"[ERROR] Failed to load config '{args.config}': {exc}")
        return

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
    print(f"\nConnecting to IBKR at {config.ibkr.host}:{config.ibkr.port} …")
    connected = await client.connect()
    if not connected:
        print("[ERROR] Connection failed. Is TWS / IB Gateway running?")
        return

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # ── Account summary ────────────────────────────────────────────────
    summary = await account_mgr.get_account_summary()
    print(f"\n{_SEP}")
    print(f"  ACCOUNT SUMMARY   [{ts}]")
    print(_SEP)
    print(f"  Account ID       : {client.account_id or 'N/A'}")
    print(f"  Net Liquidation  : ${summary.get('NetLiquidation', 0):>14,.2f}")
    print(f"  Excess Liquidity : ${summary.get('ExcessLiquidity', 0):>14,.2f}")
    print(f"  Available Funds  : ${summary.get('AvailableFunds', 0):>14,.2f}")
    print(f"  Buying Power     : ${summary.get('BuyingPower', 0):>14,.2f}")
    print(f"  Total Cash       : ${summary.get('TotalCashValue', 0):>14,.2f}")

    # ── Positions ──────────────────────────────────────────────────────
    positions = await account_mgr.get_positions()
    print(f"\n  POSITIONS  ({len(positions)} open)")
    if positions:
        hdr = f"  {'Symbol':<10} {'Class':>5} {'Qty':>8} {'AvgCost':>10} {'Last':>8} {'MktVal':>12} {'UnrealPnL':>10}"
        print(_LINE)
        print(hdr)
        print(_LINE)
        for p in positions:
            print(
                f"  {p['symbol']:<10} {p.get('asset_class','STK'):>5} "
                f"{p['quantity']:>8.0f} ${p['avg_cost']:>9.2f} "
                f"${p['current_price']:>7.2f} ${p['market_value']:>11,.2f} "
                f"${p['unrealized_pnl']:>9,.2f}"
            )
    else:
        print("  (no open positions)")

    # ── Open orders ────────────────────────────────────────────────────
    if read_only:
        print(f"\n  OPEN ORDERS  (skipped — TWS Read-Only API is enabled)")
        print(f"  Set ibkr.read_only_api: false in config to enable this section.")
    else:
        open_orders = await account_mgr.get_open_orders()
        print(f"\n  OPEN ORDERS  ({len(open_orders)})")
        if open_orders:
            print(_LINE)
            for o in open_orders:
                lmt = f"@ ${o['limit_price']:.2f}" if o.get("limit_price") else ""
                print(
                    f"  [{o['order_id']}] {o['action']:4s} "
                    f"{o['quantity']:>8.0f} x {o['symbol']:<10} "
                    f"{o['order_type']:6s} {lmt}"
                )
        else:
            print("  (no open orders)")

    # ── Debug: raw account tags ────────────────────────────────────────
    if args.debug_account_tags:
        raw = await account_mgr.get_all_account_values()
        print(f"\n{_SEP}")
        print(f"  DEBUG: Raw Account Values  ({len(raw)} entries from ib.accountValues())")
        print(_SEP)
        if not raw:
            print("  (no entries — ib.accountValues() returned empty list)")
            print("  Possible cause: account data not yet received from TWS.")
            print("  Try adding a short sleep after connect() and re-running.")
        else:
            accounts_found = sorted({r["account"] for r in raw})
            currencies_found = sorted({r["currency"] for r in raw})
            target = client.account_id or "(none)"
            print(f"  Accounts   : {accounts_found}")
            print(f"  Currencies : {currencies_found}")
            print(f"  Configured account_id: {target}")
            print(f"  Summary uses: account={target}, currency in (USD, BASE, '')")
            print(_LINE)

            # Key financial tags shown prominently
            _KEY_TAGS = {
                "NetLiquidation", "ExcessLiquidity", "AvailableFunds",
                "BuyingPower", "TotalCashValue", "GrossPositionValue",
                "InitMarginReq", "MaintMarginReq",
            }
            key_entries = [r for r in raw if r["tag"] in _KEY_TAGS]
            other_entries = [r for r in raw if r["tag"] not in _KEY_TAGS]

            def _print_table(entries: list) -> None:
                for r in sorted(entries, key=lambda e: (e["tag"], e["currency"])):
                    acct = r["account"][:12]
                    tag = r["tag"][:34]
                    val = r["value"][:18]
                    ccy = r["currency"][:6]
                    print(f"  {acct:<12}  {tag:<34}  {val:<18}  {ccy}")

            if key_entries:
                print(f"  [Key financial tags]")
                print(f"  {'Account':<12}  {'Tag':<34}  {'Value':<18}  {'Ccy'}")
                print(f"  {'-'*12}  {'-'*34}  {'-'*18}  {'-'*6}")
                _print_table(key_entries)

            if other_entries:
                print(f"\n  [All other tags — {len(other_entries)} entries]")
                print(f"  {'Account':<12}  {'Tag':<34}  {'Value':<18}  {'Ccy'}")
                print(f"  {'-'*12}  {'-'*34}  {'-'*18}  {'-'*6}")
                _print_table(other_entries)

    # ── Optional quote ─────────────────────────────────────────────────
    if args.quote:
        sym = args.quote.upper()
        print(f"\n  QUOTE: {sym}")
        print(_LINE)
        quote = await market_mgr.get_stock_quote(sym)

        def _fmt(v) -> str:
            return f"${v:,.4f}" if v is not None else "N/A"

        _DT_LABEL = {
            "live":           "live (IBKR type 1 — requires subscription)",
            "frozen":         "frozen (IBKR type 2 — requires subscription)",
            "delayed":        "delayed 15-20 min (IBKR type 3 — free)",
            "delayed_frozen": "delayed frozen (IBKR type 4 — free)",
        }
        dt = quote.get("data_type", "unknown")
        print(f"  Data Type    : {_DT_LABEL.get(dt, dt)}")
        print(f"  Bid          : {_fmt(quote['bid'])}")
        print(f"  Ask          : {_fmt(quote['ask'])}")
        print(f"  Last         : {_fmt(quote['last'])}")
        print(f"  Prev Close   : {_fmt(quote['close'])}")
        print(f"  Best Price   : {_fmt(quote['price'])}")
        print(f"  Quality      : {quote['quote_quality']}")
        print(f"  Stale        : {quote['is_stale']}")
        print(f"  Timestamp    : {quote['timestamp'] or 'N/A'}")
        err = quote.get("ibkr_error")
        if err:
            print(f"  IBKR Error   : [{err['code']}] {err['message']}")
        else:
            print(f"  IBKR Error   : None")

    print(f"\n{_SEP}\n")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

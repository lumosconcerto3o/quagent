#!/usr/bin/env python
"""
Emergency flatten all positions.
Closes all open equity positions at market price.
Use with extreme caution.
"""

import argparse
import asyncio
from pathlib import Path
import sys
from typing import List, Optional, Set, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas import Position, Signal, OrderAction, OrderType
from app.logger import get_logger

logger = get_logger(__name__)

# Asset classes handled in the MVP.  Everything else is skipped with a warning.
_MVP_EQUITY_CLASSES: Set[str] = {"STK"}


def plan_flatten(
    positions: List[Position],
    allowed_asset_classes: Optional[Set[str]] = None,
) -> Tuple[List[Signal], List[Tuple[str, str]]]:
    """
    Compute close signals for a list of positions.

    This function is purely offline (no IBKR calls) and is safe to call in
    tests without a broker connection.

    Args:
        positions: Current open positions.
        allowed_asset_classes: Set of asset classes to flatten.
                               Defaults to {"STK"} (equity only).

    Returns:
        (signals_to_close, skipped) where skipped is a list of (symbol, reason).
    """
    if allowed_asset_classes is None:
        allowed_asset_classes = _MVP_EQUITY_CLASSES

    signals: List[Signal] = []
    skipped: List[Tuple[str, str]] = []

    for position in positions:
        asset_class = getattr(position, 'asset_class', 'STK')

        if asset_class not in allowed_asset_classes:
            reason = f"non-equity asset class: {asset_class}"
            skipped.append((position.symbol, reason))
            continue

        if position.quantity == 0:
            skipped.append((position.symbol, "zero quantity — nothing to close"))
            continue

        action = OrderAction.SELL if position.quantity > 0 else OrderAction.BUY
        qty = abs(position.quantity)

        signal = Signal(
            symbol=position.symbol,
            action=action,
            quantity=qty,
            # Use current_price so downstream notional checks have a reference price
            limit_price=position.current_price,
            order_type=OrderType.MARKET,
            asset_class=asset_class,
            strategy_name="emergency_flatten",
        )
        signals.append(signal)

    return signals, skipped


async def main():
    """Emergency flatten all equity positions."""
    # Import here to avoid circular imports at module load time
    from app.main import TradingSystem

    parser = argparse.ArgumentParser(
        description="EMERGENCY: Flatten all equity positions"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/paper.yaml",
        help="Path to config file",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm emergency flatten (required for live execution)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print intended actions without submitting any orders",
    )

    args = parser.parse_args()

    if not args.confirm and not args.dry_run:
        print("\n" + "!" * 60)
        print("EMERGENCY FLATTEN ALL EQUITY POSITIONS")
        print("!" * 60)
        print("This will close ALL open equity positions at market price.")
        print("Non-equity positions (options, futures, forex) are skipped.")
        print("Open orders for each symbol are cancelled before flattening.")
        print("")
        print("  --dry-run    Preview what would be closed (no orders sent)")
        print("  --confirm    Execute the flatten")
        print("!" * 60 + "\n")
        return

    try:
        logger.warning("Initializing emergency flatten...")
        system = TradingSystem()

        connected = await system.connect()
        if not connected:
            logger.error("Failed to connect to IBKR")
            return

        await system.account_manager.refresh()
        account = system.account_manager.get_account()

        if not account or not account.positions:
            logger.info("No open positions to flatten")
            await system.disconnect()
            return

        signals_to_close, skipped = plan_flatten(account.positions)

        # ── Dry-run path: print and return ──────────────────────────────
        if args.dry_run:
            print("\n[DRY RUN] Would close the following positions:")
            if signals_to_close:
                for sig in signals_to_close:
                    print(
                        f"  {sig.action.value:4s} {sig.quantity:>10.2f} x {sig.symbol}"
                        f"  (MARKET, ref_price=${sig.limit_price:.2f})"
                    )
            else:
                print("  (no equity positions to close)")

            if skipped:
                print("[DRY RUN] Would skip:")
                for symbol, reason in skipped:
                    print(f"  {symbol}: {reason}")

            print("[DRY RUN] No orders submitted.\n")
            await system.disconnect()
            return

        # ── Confirmed execution path ────────────────────────────────────
        # Step 1: Cancel open orders to avoid doubling up
        logger.warning("Cancelling all open orders before flattening...")
        cancelled = await system.execution_engine.cancel_all_orders()
        logger.warning(f"Cancelled {cancelled} open order(s)")

        # Step 2: Warn about skipped positions
        for symbol, reason in skipped:
            logger.warning(f"Skipping position {symbol}: {reason}")

        # Step 3: Flatten equity positions
        if not signals_to_close:
            logger.info("No equity positions to flatten after filtering")
            await system.disconnect()
            return

        logger.warning(f"Flattening {len(signals_to_close)} equity position(s)...")
        for signal in signals_to_close:
            logger.warning(
                f"Closing: {signal.action.value} {signal.quantity} x {signal.symbol}"
            )
            await system.process_signal(signal)

        logger.warning("Emergency flatten completed")
        await system.disconnect()

    except Exception as e:
        logger.error(f"Error during emergency flatten: {e}")


if __name__ == "__main__":
    asyncio.run(main())

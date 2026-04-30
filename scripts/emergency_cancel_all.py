#!/usr/bin/env python
"""
Emergency cancel all open orders.
Use with extreme caution.
"""

import argparse
import asyncio
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import TradingSystem
from app.logger import get_logger

logger = get_logger(__name__)


async def main():
    """Emergency cancel all orders."""
    parser = argparse.ArgumentParser(
        description="EMERGENCY: Cancel all open orders"
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
        help="Confirm emergency cancel (required)",
    )
    
    args = parser.parse_args()
    
    if not args.confirm:
        print("\n" + "!" * 60)
        print("EMERGENCY CANCEL ALL")
        print("!" * 60)
        print("This will cancel ALL open orders immediately.")
        print("Use --confirm to proceed.")
        print("!" * 60 + "\n")
        return
    
    try:
        logger.warning("Initializing emergency cancel...")
        system = TradingSystem()
        
        connected = await system.connect()
        if not connected:
            logger.error("Failed to connect to IBKR")
            return
        
        cancelled = await system.emergency_cancel_all()
        logger.warning(f"Cancelled {cancelled} orders")
        
        await system.disconnect()
    
    except Exception as e:
        logger.error(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())

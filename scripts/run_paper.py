#!/usr/bin/env python
"""
Run paper trading - main loop for the trading system.
"""

import asyncio
import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import TradingSystem
from app.logger import get_logger

logger = get_logger(__name__)


async def main():
    """Main loop for paper trading."""
    parser = argparse.ArgumentParser(description="Run QuAgent paper trading")
    parser.add_argument(
        "--config",
        type=str,
        default="configs/paper.yaml",
        help="Path to config file (relative to project root)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    
    args = parser.parse_args()
    
    # Initialize system
    try:
        system = TradingSystem()
        logger.info("Paper trading mode initialized")
        
        # Connect to IBKR
        connected = await system.connect()
        if not connected:
            logger.error("Failed to connect to IBKR")
            return
        
        logger.info("Connected to IBKR")
        
        # Main loop (placeholder - replace with actual trading logic)
        try:
            while True:
                logger.info("Checking for signals...")
                
                # Placeholder: Would fetch signals here
                await asyncio.sleep(system.config.trading.check_interval)
        
        except KeyboardInterrupt:
            logger.info("Shutdown requested")
        
        finally:
            await system.disconnect()
            logger.info("Disconnected from IBKR")
    
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

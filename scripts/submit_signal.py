#!/usr/bin/env python
"""
Submit a trading signal to the system.
Used for manual and agent-based signal injection.
"""

import json
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.main import TradingSystem
from app.schemas import Signal, OrderAction, OrderType
from app.logger import get_logger
import asyncio

logger = get_logger(__name__)


def load_signal_from_file(file_path: str) -> Signal:
    """Load signal from JSON file."""
    with open(file_path, 'r') as f:
        data = json.load(f)
    
    return Signal(
        symbol=data['symbol'],
        action=OrderAction(data['action']),
        quantity=data['quantity'],
        limit_price=data.get('limit_price'),
        order_type=OrderType(data.get('order_type', 'MARKET')),
        strategy_name=data.get('strategy_name', 'manual'),
        metadata=data.get('metadata', {}),
    )


def load_signal_from_args(symbol: str, action: str, quantity: float, limit_price: float = None) -> Signal:
    """Create signal from command-line arguments."""
    return Signal(
        symbol=symbol,
        action=OrderAction(action.upper()),
        quantity=quantity,
        limit_price=limit_price,
        order_type=OrderType.MARKET,
        strategy_name="manual",
    )


async def main():
    """Submit a signal to the trading system."""
    parser = argparse.ArgumentParser(
        description="Submit a trading signal to QuAgent"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="configs/paper.yaml",
        help="Path to config file",
    )
    
    # Either load from file or command line
    parser.add_argument(
        "--file",
        type=str,
        help="Load signal from JSON file",
    )
    
    # Or specify directly
    parser.add_argument("--symbol", type=str, help="Ticker symbol")
    parser.add_argument("--action", type=str, choices=["BUY", "SELL"], help="BUY or SELL")
    parser.add_argument("--quantity", type=float, help="Number of shares")
    parser.add_argument("--limit-price", type=float, help="Limit price (optional)")
    
    args = parser.parse_args()
    
    # Load signal
    try:
        if args.file:
            signal = load_signal_from_file(args.file)
            logger.info(f"Loaded signal from {args.file}")
        else:
            if not (args.symbol and args.action and args.quantity):
                logger.error("Either --file or (--symbol, --action, --quantity) required")
                sys.exit(1)
            signal = load_signal_from_args(args.symbol, args.action, args.quantity, args.limit_price)
        
        logger.info(f"Signal: {signal.action} {signal.quantity} x {signal.symbol}")
        
        # Initialize system and submit signal
        system = TradingSystem()
        
        # Note: In a real system, system would be already running
        # This is for manual signal injection
        logger.warning("⚠️  Note: This requires the main trading system to be running")
        logger.warning("In production, signals would be submitted via queue or API")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

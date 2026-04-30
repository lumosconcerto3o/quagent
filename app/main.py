"""
Main trading system orchestrator.
Coordinates all components: config, IBKR connection, account, risk, OMS, execution.
"""

from typing import Optional
import asyncio

from app.logger import get_logger, setup_logger
from app.config import get_config, QuAgentConfig
from app.ibkr_client import IBKRClient
from app.account import AccountManager
from app.market_data import MarketDataManager
from app.risk import RiskEngine
from app.oms import OrderManagementSystem
from app.execution import ExecutionEngine
from app.kill_switch import KillSwitch
from app.storage import Database
from app.schemas import Signal

logger = get_logger(__name__)


class TradingSystem:
    """
    Main trading system - orchestrates all components.
    """
    
    def __init__(self, config: Optional[QuAgentConfig] = None):
        """
        Initialize trading system.
        
        Args:
            config: QuAgent configuration (if None, loads from file)
        """
        self.config = config or get_config()
        
        # Setup logging
        setup_logger(
            "quagent",
            log_file=self.config.logging.file,
            level=self.config.logging.level,
        )
        
        logger.info("=" * 60)
        logger.info(f"Trading System Initializing (Mode: {self.config.trading_mode})")
        logger.info("=" * 60)
        
        # Verify live trading safeguard
        if self.config.trading_mode == 'live' and not self.config.allow_live:
            raise ValueError(
                "Live trading mode selected but allow_live=false in config. "
                "Set allow_live=true to enable live trading."
            )
        
        # Initialize components
        self.ibkr_client = IBKRClient(
            host=self.config.ibkr.host,
            port=self.config.ibkr.port,
            client_id=self.config.ibkr.client_id,
        )
        self.account_manager = AccountManager(self.ibkr_client)
        self.market_data = MarketDataManager(self.ibkr_client)
        self.risk_engine = RiskEngine(self.config)
        self.oms = OrderManagementSystem()
        self.execution_engine = ExecutionEngine(self.ibkr_client, self.oms, self.risk_engine)
        self.kill_switch = KillSwitch()
        self.database = Database(self.config.database.url.replace('sqlite:///', ''))
        
        logger.info("Trading System initialized")
    
    async def connect(self) -> bool:
        """
        Connect to IBKR.
        
        Returns:
            True if connection successful
        """
        return await self.ibkr_client.connect()
    
    async def disconnect(self) -> None:
        """Disconnect from IBKR."""
        await self.ibkr_client.disconnect()
    
    async def process_signal(self, signal: Signal) -> bool:
        """
        Process a trading signal:
        1. Risk check
        2. Create order
        3. Execute
        
        Args:
            signal: Trading signal
        
        Returns:
            True if signal processed successfully
        """
        if self.kill_switch.is_triggered():
            logger.error(
                f"Signal rejected: Kill switch active ({self.kill_switch.status.reason})"
            )
            return False
        
        try:
            # Refresh account data
            await self.account_manager.refresh()
            account = self.account_manager.get_account()
            
            if not account:
                logger.error("Failed to fetch account data")
                return False
            
            # Run risk checks
            current_positions = {
                p.symbol: p.quantity for p in account.positions
            }
            
            risk_result = self.risk_engine.check_signal(
                signal,
                account.available_funds,
                current_positions,
                account.total_value,
            )
            
            if not risk_result.passed:
                logger.warning(f"Signal rejected by risk check: {risk_result.failures}")
                self.database.log_event(
                    "signal_rejected",
                    f"Signal {signal.symbol} rejected: {risk_result.failures}",
                    severity="WARNING"
                )
                return False
            
            # Create order
            order = self.oms.create_order_from_signal(signal)
            
            # Execute order
            success = await self.execution_engine.execute_order(order)
            
            # Log to database
            self.database.log_order(order)
            
            if success:
                logger.info(f"Signal {signal.symbol} processed successfully")
                self.risk_engine.record_trade(
                    signal.symbol,
                    signal.quantity,
                    signal.limit_price or 0.0,
                    signal.action.value
                )
                self.database.log_event(
                    "signal_executed",
                    f"Signal {signal.symbol} executed",
                    severity="INFO"
                )
            
            return success
        
        except Exception as e:
            logger.error(f"Error processing signal: {e}")
            self.database.log_event(
                "signal_error",
                f"Error: {str(e)}",
                severity="ERROR"
            )
            return False
    
    async def emergency_cancel_all(self) -> int:
        """
        Emergency cancel all open orders.
        
        Returns:
            Number of orders cancelled
        """
        logger.critical("EMERGENCY CANCEL ALL TRIGGERED")
        self.kill_switch.trigger("Emergency cancel all", triggered_by="manual")
        return await self.execution_engine.cancel_all_orders()
    
    def get_account_summary(self) -> Optional[dict]:
        """Get current account summary."""
        account = self.account_manager.get_account()
        if not account:
            return None
        
        return {
            'account_id': account.account_id,
            'total_value': account.total_value,
            'buying_power': account.available_funds,
            'cash': account.cash,
            'positions': len(account.positions),
            'updated_at': account.timestamp.isoformat(),
        }

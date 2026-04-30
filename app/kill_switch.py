"""
Kill switch - emergency circuit breaker.
Stops all trading if triggered.
"""

from typing import Optional
from datetime import datetime

from app.logger import get_logger
from app.schemas import KillSwitchStatus

logger = get_logger(__name__)


class KillSwitch:
    """
    Emergency circuit breaker.
    When triggered, prevents all new orders and signals.
    """
    
    def __init__(self):
        """Initialize kill switch (disabled by default)."""
        self.status = KillSwitchStatus(enabled=False)
    
    def trigger(self, reason: str, triggered_by: str = "system") -> None:
        """
        Trigger the kill switch.
        
        Args:
            reason: Reason for triggering
            triggered_by: Who triggered it (manual, risk_check, etc.)
        """
        self.status = KillSwitchStatus(
            enabled=True,
            reason=reason,
            triggered_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        logger.critical(f"🚨 KILL SWITCH TRIGGERED by {triggered_by}: {reason}")
    
    def reset(self, confirmed_by: str = "manual") -> None:
        """
        Reset the kill switch (requires manual confirmation).
        
        Args:
            confirmed_by: Who reset it
        """
        self.status = KillSwitchStatus(enabled=False)
        logger.warning(f"Kill switch RESET by {confirmed_by}")
    
    def is_triggered(self) -> bool:
        """Check if kill switch is active."""
        return self.status.enabled
    
    def get_status(self) -> KillSwitchStatus:
        """Get kill switch status."""
        return self.status
    
    def require_enabled(self, operation_name: str) -> bool:
        """
        Check if kill switch allows operation. Logs if blocked.
        
        Args:
            operation_name: Name of operation attempting to run
        
        Returns:
            False if kill switch is active
        """
        if self.is_triggered():
            logger.error(
                f"Operation '{operation_name}' blocked by kill switch. "
                f"Reason: {self.status.reason}"
            )
            return False
        return True

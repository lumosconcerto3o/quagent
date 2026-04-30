"""
Pydantic schemas for QuAgent data models.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field, validator


class OrderStatus(str, Enum):
    """Order status enumeration."""
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class OrderAction(str, Enum):
    """Order action (BUY/SELL)."""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order type."""
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    TRAILING_STOP = "TRAILING_STOP"


class RiskCheckStatus(str, Enum):
    """Risk check result."""
    PASS = "PASS"
    REJECT = "REJECT"
    WARN = "WARN"


class Signal(BaseModel):
    """Trading signal."""
    symbol: str = Field(..., description="Ticker symbol")
    action: OrderAction = Field(..., description="BUY or SELL")
    quantity: float = Field(..., gt=0, description="Number of shares")
    limit_price: Optional[float] = Field(None, description="Limit price for limit orders")
    stop_loss: Optional[float] = Field(None, description="Stop loss price")
    order_type: OrderType = Field(default=OrderType.MARKET)
    asset_class: str = Field(default="STK", description="Asset class (STK, OPT, FUT, FOREX, ...)")
    strategy_name: str = Field(default="manual", description="Source strategy")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom metadata")

    class Config:
        use_enum_values = False


class MarketQuote(BaseModel):
    """Market quote passed to risk checks for sanity validation."""
    symbol: str
    price: float
    quote_quality: str = "complete"  # "complete" | "incomplete"
    is_stale: bool = False
    timestamp: Optional[datetime] = None


class Position(BaseModel):
    """Current position."""
    symbol: str
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    asset_class: str = "STK"

    class Config:
        use_enum_values = False


class Account(BaseModel):
    """Account information."""
    account_id: str
    buying_power: float
    available_funds: float
    total_value: float
    cash: float
    positions: List[Position] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Order(BaseModel):
    """Order record."""
    order_id: int
    symbol: str
    action: OrderAction
    quantity: float
    order_type: OrderType
    limit_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    broker_order_id: Optional[int] = None
    filled_quantity: float = 0.0
    filled_price: Optional[float] = None
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    filled_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    error_msg: Optional[str] = None
    
    class Config:
        use_enum_values = False


class Execution(BaseModel):
    """Order execution record."""
    execution_id: str
    order_id: int
    symbol: str
    action: OrderAction
    quantity: float
    price: float
    commission: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        use_enum_values = False


class RiskCheckResult(BaseModel):
    """Result of a risk check."""
    passed: bool
    checks: Dict[str, Any] = Field(default_factory=dict)
    failures: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class KillSwitchStatus(BaseModel):
    """Kill switch status."""
    enabled: bool
    reason: Optional[str] = None
    triggered_at: Optional[datetime] = None
    triggered_by: Optional[str] = None

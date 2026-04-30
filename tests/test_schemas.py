"""
Tests for data schemas and models.
"""

import pytest
from datetime import datetime

from app.schemas import (
    Signal,
    Order,
    Account,
    Position,
    OrderStatus,
    OrderAction,
    OrderType,
    RiskCheckResult,
)


def test_signal_creation():
    """Test creating a trading signal."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=100,
        limit_price=150.00,
        order_type=OrderType.LIMIT,
        strategy_name="test_strategy",
    )
    
    assert signal.symbol == "AAPL"
    assert signal.action == OrderAction.BUY
    assert signal.quantity == 100
    assert signal.limit_price == 150.00
    assert signal.order_type == OrderType.LIMIT


def test_signal_validation():
    """Test signal validation."""
    # Valid signal
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=100,
    )
    assert signal.order_type == OrderType.MARKET  # Default
    
    # Invalid quantity (must be > 0)
    with pytest.raises(ValueError):
        Signal(
            symbol="AAPL",
            action=OrderAction.BUY,
            quantity=0,
        )
    
    # Invalid action
    with pytest.raises(ValueError):
        Signal(
            symbol="AAPL",
            action="INVALID",
            quantity=100,
        )


def test_order_creation():
    """Test creating an order."""
    order = Order(
        order_id=1,
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=100,
        order_type=OrderType.MARKET,
        status=OrderStatus.PENDING,
    )
    
    assert order.order_id == 1
    assert order.status == OrderStatus.PENDING
    assert order.filled_quantity == 0.0


def test_position_creation():
    """Test creating a position."""
    position = Position(
        symbol="AAPL",
        quantity=100,
        avg_cost=150.00,
        current_price=155.00,
        market_value=15500.00,
        unrealized_pnl=500.00,
        unrealized_pnl_pct=3.33,
    )
    
    assert position.symbol == "AAPL"
    assert position.quantity == 100
    assert position.unrealized_pnl == 500.00


def test_account_creation():
    """Test creating account info."""
    account = Account(
        account_id="DU123456",
        buying_power=50000,
        available_funds=50000,
        total_value=100000,
        cash=100000,
    )
    
    assert account.account_id == "DU123456"
    assert account.total_value == 100000


def test_risk_check_result():
    """Test risk check result."""
    result = RiskCheckResult(passed=True)
    
    assert result.passed == True
    assert result.failures == []
    assert result.warnings == []
    
    # Add failures
    result.failures.append("Position too large")
    assert result.passed == True  # We need to explicitly set it to False
    
    result2 = RiskCheckResult(
        passed=False,
        failures=["Insufficient buying power"],
    )
    
    assert result2.passed == False
    assert len(result2.failures) == 1


def test_order_status_has_validated():
    """VALIDATED must exist in OrderStatus for the OMS transition guard."""
    assert OrderStatus.VALIDATED == "VALIDATED"


def test_order_has_broker_order_id():
    """Order must carry broker_order_id, defaulting to None."""
    order = Order(
        order_id=1,
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=10,
        order_type=OrderType.LIMIT,
        limit_price=150.0,
        status=OrderStatus.PENDING,
    )
    assert order.broker_order_id is None

    order.broker_order_id = 99
    assert order.broker_order_id == 99


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

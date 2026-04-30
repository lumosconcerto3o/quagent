"""
Tests for Order Management System.
"""

import pytest
from app.oms import OrderManagementSystem
from app.schemas import Signal, OrderAction, OrderType, OrderStatus


@pytest.fixture
def oms():
    """Create an OMS instance."""
    return OrderManagementSystem()


def test_create_order_from_signal(oms):
    """Test creating an order from a signal."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=100,
        limit_price=150.00,
        order_type=OrderType.LIMIT,
    )
    
    order = oms.create_order_from_signal(signal)
    
    assert order.order_id == 1
    assert order.symbol == "AAPL"
    assert order.action == OrderAction.BUY
    assert order.quantity == 100
    assert order.limit_price == 150.00
    assert order.status == OrderStatus.PENDING


def test_order_id_increments(oms):
    """Test that order IDs increment."""
    signal1 = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    signal2 = Signal(symbol="MSFT", action=OrderAction.BUY, quantity=50)
    
    order1 = oms.create_order_from_signal(signal1)
    order2 = oms.create_order_from_signal(signal2)
    
    assert order1.order_id == 1
    assert order2.order_id == 2


def test_get_order(oms):
    """Test retrieving an order."""
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    order = oms.create_order_from_signal(signal)
    
    retrieved = oms.get_order(1)
    assert retrieved is not None
    assert retrieved.order_id == 1
    
    # Non-existent order
    assert oms.get_order(999) is None


def test_update_order_status(oms):
    """Test updating order status through the valid lifecycle."""
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    order = oms.create_order_from_signal(signal)

    # PENDING → VALIDATED
    assert oms.update_order_status(order.order_id, OrderStatus.VALIDATED) is True
    order = oms.get_order(order.order_id)
    assert order.status == OrderStatus.VALIDATED

    # VALIDATED → SUBMITTED
    assert oms.update_order_status(order.order_id, OrderStatus.SUBMITTED) is True
    order = oms.get_order(order.order_id)
    assert order.status == OrderStatus.SUBMITTED

    # SUBMITTED → FILLED
    oms.update_order_status(
        order.order_id,
        OrderStatus.FILLED,
        filled_quantity=100,
        filled_price=150.50,
    )
    order = oms.get_order(order.order_id)
    assert order.status == OrderStatus.FILLED
    assert order.filled_quantity == 100
    assert order.filled_price == 150.50
    assert order.filled_at is not None


def test_cancel_order(oms):
    """Test cancelling an order."""
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    order = oms.create_order_from_signal(signal)
    
    oms.cancel_order(order.order_id)
    order = oms.get_order(order.order_id)
    
    assert order.status == OrderStatus.CANCELLED
    assert order.cancelled_at is not None


def test_get_open_orders(oms):
    """Test getting open orders."""
    signal1 = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    signal2 = Signal(symbol="MSFT", action=OrderAction.BUY, quantity=50)
    signal3 = Signal(symbol="GOOG", action=OrderAction.BUY, quantity=25)

    order1 = oms.create_order_from_signal(signal1)
    order2 = oms.create_order_from_signal(signal2)
    order3 = oms.create_order_from_signal(signal3)

    # Walk order2 through valid transitions to FILLED
    oms.update_order_status(order2.order_id, OrderStatus.VALIDATED)
    oms.update_order_status(order2.order_id, OrderStatus.SUBMITTED)
    oms.update_order_status(order2.order_id, OrderStatus.FILLED, filled_quantity=50, filled_price=100)

    # Cancel order3 (PENDING → CANCELLED is a valid transition)
    oms.cancel_order(order3.order_id)

    open_orders = oms.get_open_orders()

    assert len(open_orders) == 1
    assert open_orders[0].order_id == order1.order_id


def test_get_all_orders(oms):
    """Test getting all orders."""
    signal1 = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    signal2 = Signal(symbol="MSFT", action=OrderAction.BUY, quantity=50)
    
    oms.create_order_from_signal(signal1)
    oms.create_order_from_signal(signal2)
    
    all_orders = oms.get_all_orders()
    assert len(all_orders) == 2


def test_invalid_oms_state_transitions_blocked(oms):
    """Invalid transitions must be rejected and leave the order unchanged."""
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    order = oms.create_order_from_signal(signal)

    # PENDING → SUBMITTED is not allowed (must go through VALIDATED first)
    result = oms.update_order_status(order.order_id, OrderStatus.SUBMITTED)
    assert result is False

    order = oms.get_order(order.order_id)
    assert order.status == OrderStatus.PENDING  # unchanged


def test_rejected_order_cannot_be_submitted(oms):
    """A REJECTED order is terminal and must not transition to SUBMITTED."""
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    order = oms.create_order_from_signal(signal)

    oms.update_order_status(order.order_id, OrderStatus.REJECTED, error_msg="Risk check failed")

    result = oms.update_order_status(order.order_id, OrderStatus.SUBMITTED)
    assert result is False

    order = oms.get_order(order.order_id)
    assert order.status == OrderStatus.REJECTED  # unchanged


def test_filled_order_cannot_be_resubmitted(oms):
    """A FILLED order is terminal and must not transition to SUBMITTED."""
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100)
    order = oms.create_order_from_signal(signal)

    # Walk through valid transitions to FILLED
    oms.update_order_status(order.order_id, OrderStatus.VALIDATED)
    oms.update_order_status(order.order_id, OrderStatus.SUBMITTED)
    oms.update_order_status(
        order.order_id, OrderStatus.FILLED, filled_quantity=100, filled_price=150.0
    )

    result = oms.update_order_status(order.order_id, OrderStatus.SUBMITTED)
    assert result is False

    order = oms.get_order(order.order_id)
    assert order.status == OrderStatus.FILLED  # unchanged


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

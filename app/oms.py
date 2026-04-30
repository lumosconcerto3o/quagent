"""
Order Management System (OMS) - Signal to order conversion.
"""

from typing import Optional, List
from datetime import datetime

from app.logger import get_logger
from app.schemas import Signal, Order, OrderStatus, OrderType

logger = get_logger(__name__)

# Explicit allowlist of legal state transitions.
# Any transition not listed here is rejected.
_ALLOWED_TRANSITIONS: dict = {
    OrderStatus.PENDING: {
        OrderStatus.VALIDATED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
        OrderStatus.ERROR,
    },
    OrderStatus.VALIDATED: {
        OrderStatus.SUBMITTED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELLED,
        OrderStatus.ERROR,
    },
    OrderStatus.SUBMITTED: {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.ERROR,
    },
    OrderStatus.FILLED: set(),      # terminal
    OrderStatus.CANCELLED: set(),   # terminal
    OrderStatus.REJECTED: set(),    # terminal
    OrderStatus.ERROR: {OrderStatus.CANCELLED},
}


class OrderManagementSystem:
    """
    Order Management System: Converts signals to orders,
    tracks order lifecycle, and maintains order book.
    """

    def __init__(self):
        """Initialize OMS."""
        self.orders: dict = {}  # order_id -> Order
        self.next_order_id = 1

    def create_order_from_signal(self, signal: Signal) -> Order:
        """
        Convert a signal to an order.

        Args:
            signal: Trading signal

        Returns:
            Order object with PENDING status
        """
        order_id = self.next_order_id
        self.next_order_id += 1

        order = Order(
            order_id=order_id,
            symbol=signal.symbol,
            action=signal.action,
            quantity=signal.quantity,
            order_type=signal.order_type,
            limit_price=signal.limit_price,
            status=OrderStatus.PENDING,
        )

        self.orders[order_id] = order
        logger.info(
            f"Created order {order_id}: {signal.action} "
            f"{signal.quantity} x {signal.symbol}"
        )

        return order

    def get_order(self, order_id: int) -> Optional[Order]:
        """Get order by ID."""
        return self.orders.get(order_id)

    def update_order_status(
        self,
        order_id: int,
        status: OrderStatus,
        filled_quantity: float = 0.0,
        filled_price: Optional[float] = None,
        error_msg: Optional[str] = None,
    ) -> bool:
        """
        Update order status, enforcing the allowed transition table.

        Args:
            order_id: Order ID
            status: Requested new status
            filled_quantity: Number of shares filled (FILLED transitions)
            filled_price: Fill price (FILLED transitions)
            error_msg: Error message (REJECTED / ERROR transitions)

        Returns:
            True if transition applied; False if order not found or transition
            is not permitted.
        """
        order = self.orders.get(order_id)
        if not order:
            logger.error(f"Order {order_id} not found")
            return False

        allowed = _ALLOWED_TRANSITIONS.get(order.status, set())
        if status not in allowed:
            logger.error(
                f"Invalid transition {order.status.value} → {status.value} "
                f"for order {order_id} — rejected"
            )
            return False

        order.status = status

        if status == OrderStatus.FILLED:
            order.filled_quantity = filled_quantity
            order.filled_price = filled_price
            order.filled_at = datetime.utcnow()
            logger.info(
                f"Order {order_id} FILLED: "
                f"{filled_quantity} @ ${filled_price:.2f}"
            )

        elif status == OrderStatus.CANCELLED:
            order.cancelled_at = datetime.utcnow()
            logger.warning(f"Order {order_id} CANCELLED")

        elif status in (OrderStatus.REJECTED, OrderStatus.ERROR):
            order.error_msg = error_msg
            logger.error(f"Order {order_id} {status.value}: {error_msg}")

        elif status == OrderStatus.VALIDATED:
            logger.info(f"Order {order_id} VALIDATED")

        elif status == OrderStatus.SUBMITTED:
            logger.info(f"Order {order_id} SUBMITTED")

        return True

    def get_open_orders(self) -> List[Order]:
        """Get all open (not terminal) orders."""
        open_statuses = {
            OrderStatus.PENDING,
            OrderStatus.VALIDATED,
            OrderStatus.SUBMITTED,
        }
        return [o for o in self.orders.values() if o.status in open_statuses]

    def cancel_order(self, order_id: int) -> bool:
        """
        Mark order as cancelled.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if the CANCELLED transition was applied successfully
        """
        return self.update_order_status(order_id, OrderStatus.CANCELLED)

    def get_all_orders(self) -> List[Order]:
        """Get all orders."""
        return list(self.orders.values())

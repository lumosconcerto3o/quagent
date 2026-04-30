"""
Execution engine - executes orders via IBKR after risk checks pass.
"""

from typing import Optional
from datetime import datetime

from app.logger import get_logger
from app.schemas import Order, OrderStatus, RiskCheckResult
from app.ibkr_client import IBKRClient
from app.oms import OrderManagementSystem
from app.risk import RiskEngine

logger = get_logger(__name__)


class ExecutionEngine:
    """
    Executes orders via IBKR after risk checks pass.
    Defaults to dry_run=True: no real broker calls unless explicitly disabled.
    """

    def __init__(
        self,
        ibkr_client: IBKRClient,
        oms: OrderManagementSystem,
        risk_engine: RiskEngine,
        dry_run: bool = True,
        kill_switch=None,
    ):
        """
        Initialize execution engine.

        Args:
            ibkr_client: IBKR client
            oms: Order Management System
            risk_engine: Risk engine for checks
            dry_run: When True (default), broker submission is skipped entirely.
            kill_switch: Optional KillSwitch; if triggered, all executions are
                         blocked regardless of dry_run.
        """
        self.client = ibkr_client
        self.oms = oms
        self.risk_engine = risk_engine
        self.dry_run = dry_run
        self.kill_switch = kill_switch
        self.executions_today = 0

    async def execute_order(self, order: Order) -> bool:
        """
        Execute an order via IBKR.

        Gate 0 — Kill switch: if active, reject immediately.
        Gate 1 — Status: order must be in VALIDATED status.
        Gate 2 — Dry run: if dry_run=True, simulate submission without any
                 broker call and return True.
        Gate 3 — Live execution: call client.submit_order and store broker_order_id.

        Args:
            order: Order to execute (must have status VALIDATED)

        Returns:
            True if submission successful (or simulated in dry_run mode)
        """
        try:
            # Gate 0: Kill switch
            if self.kill_switch and self.kill_switch.is_triggered():
                reason = self.kill_switch.status.reason or "unknown"
                logger.error(
                    f"Order {order.order_id} blocked: kill switch active ({reason})"
                )
                self.oms.update_order_status(
                    order.order_id,
                    OrderStatus.REJECTED,
                    error_msg=f"Kill switch active: {reason}",
                )
                return False

            # Gate 1: Order must be VALIDATED before execution
            if order.status != OrderStatus.VALIDATED:
                logger.error(
                    f"Order {order.order_id} has status {order.status.value}, "
                    "expected VALIDATED — refusing execution"
                )
                return False

            logger.info(
                f"Executing order {order.order_id}: "
                f"{order.action} {order.quantity} x {order.symbol}"
            )

            # Gate 2: Dry run — simulate without touching the broker
            if self.dry_run:
                logger.info(
                    f"[DRY RUN] Simulated submission for order {order.order_id}: "
                    f"{order.action} {order.quantity} x {order.symbol} "
                    f"(broker call skipped, broker_order_id remains None)"
                )
                self.oms.update_order_status(order.order_id, OrderStatus.SUBMITTED)
                self.executions_today += 1
                return True

            # Gate 3: Live execution path (only reached when dry_run=False)
            if not self.client.is_connected():
                logger.error("IBKR client not connected, cannot execute")
                self.oms.update_order_status(
                    order.order_id,
                    OrderStatus.ERROR,
                    error_msg="Client not connected",
                )
                return False

            ibkr_order_id = await self.client.submit_order(
                symbol=order.symbol,
                action=order.action.value,
                quantity=order.quantity,
                order_type=order.order_type.value,
                limit_price=order.limit_price,
            )

            if ibkr_order_id:
                self.oms.update_order_status(order.order_id, OrderStatus.SUBMITTED)
                order.broker_order_id = ibkr_order_id
                self.executions_today += 1
                logger.info(
                    f"Order {order.order_id} submitted to IBKR "
                    f"(broker_order_id: {ibkr_order_id})"
                )
                return True
            else:
                self.oms.update_order_status(
                    order.order_id,
                    OrderStatus.ERROR,
                    error_msg="IBKR submission returned no order ID",
                )
                logger.error(f"Order {order.order_id} IBKR submission failed")
                return False

        except Exception as e:
            logger.error(f"Error executing order {order.order_id}: {e}")
            self.oms.update_order_status(
                order.order_id,
                OrderStatus.ERROR,
                error_msg=str(e),
            )
            return False

    async def cancel_order(self, order_id: int) -> bool:
        """
        Cancel an order via IBKR.

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancel successful
        """
        try:
            order = self.oms.get_order(order_id)
            if not order:
                logger.error(f"Order {order_id} not found in OMS")
                return False

            logger.warning(f"Cancelling order {order_id}...")
            result = await self.client.cancel_order(order_id)

            if result:
                self.oms.cancel_order(order_id)
                logger.warning(f"Order {order_id} cancelled")
                return True
            else:
                logger.error(f"Failed to cancel order {order_id}")
                return False

        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    async def cancel_all_orders(self) -> int:
        """
        Cancel all open orders (emergency use).

        Returns:
            Number of orders cancelled
        """
        logger.critical("EMERGENCY: Cancelling ALL open orders!")
        open_orders = self.oms.get_open_orders()

        cancelled_count = 0
        for order in open_orders:
            if await self.cancel_order(order.order_id):
                cancelled_count += 1

        logger.critical(f"Cancelled {cancelled_count} orders")
        return cancelled_count

    def get_execution_count_today(self) -> int:
        """Get number of executions today."""
        return self.executions_today

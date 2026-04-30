"""
IBKR connection and client abstraction layer.

READ-ONLY PHASE:
  - Connection lifecycle (connect / disconnect / reconnect / is_connected / get_ib)
  - Account data (get_account, get_positions, get_open_orders)
  - Price data  (get_price)

ORDER METHODS ARE EXPLICITLY DISABLED:
  - submit_order() raises NotImplementedError — ib.placeOrder() is never called.
  - cancel_order() raises NotImplementedError — ib.cancelOrder() is never called.
"""

import asyncio
import math
from typing import Optional, List

import ib_insync

from app.logger import get_logger
from app.schemas import Account, Position, Order, OrderStatus, OrderAction, OrderType

logger = get_logger(__name__)

_SUBMIT_DISABLED = (
    "Order submission is disabled in the read-only phase. "
    "IBKRClient.submit_order() must not be called. "
    "Enable after all safety reviews are complete."
)

_CANCEL_DISABLED = (
    "Broker-side order cancellation is disabled in the read-only phase. "
    "IBKRClient.cancel_order() must not be called."
)


class IBKRClient:
    """
    Abstraction layer for IBKR connections via ib_insync.

    READ-ONLY PHASE: connection lifecycle and data fetching only.
    submit_order() and cancel_order() raise NotImplementedError.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        read_only_api: bool = True,
    ):
        """
        Args:
            host: TWS / IB Gateway host
            port: 7497 for paper, 7496 for live
            client_id: Client ID for this session
            read_only_api: When True, passes readonly=True to connectAsync so
                           ib_insync never sends startup requests that require
                           TWS write access (open/completed orders sync).
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.read_only_api = read_only_api
        self.account_id: Optional[str] = None
        self._ib = ib_insync.IB()
        logger.info(
            f"IBKRClient initialised: {host}:{port} "
            f"(client_id={client_id}, read_only_api={read_only_api})"
        )

    # ------------------------------------------------------------------ #
    # Connection lifecycle                                                 #
    # ------------------------------------------------------------------ #

    async def connect(self) -> bool:
        """Connect to TWS / IB Gateway. Returns True on success."""
        try:
            logger.info(
                f"Connecting to IBKR at {self.host}:{self.port} "
                f"(client_id={self.client_id})..."
            )
            await self._ib.connectAsync(
                self.host,
                self.port,
                clientId=self.client_id,
                timeout=10,
                readonly=self.read_only_api,
            )
            accounts = self._ib.managedAccounts()
            self.account_id = accounts[0] if accounts else None
            logger.info(f"Connected to IBKR. Managed account: {self.account_id}")
            return True
        except Exception as exc:
            logger.error(
                f"Failed to connect to IBKR at {self.host}:{self.port}: {exc}"
            )
            return False

    async def disconnect(self) -> None:
        """Disconnect cleanly from TWS / IB Gateway."""
        if self._ib.isConnected():
            logger.info("Disconnecting from IBKR...")
            self._ib.disconnect()
            logger.info("Disconnected from IBKR")
        else:
            logger.debug("disconnect() called but already disconnected")

    async def reconnect(self) -> bool:
        """Disconnect then reconnect. Returns True on success."""
        await self.disconnect()
        await asyncio.sleep(1)
        return await self.connect()

    def is_connected(self) -> bool:
        """Reflect actual ib_insync connection state."""
        return self._ib.isConnected()

    def get_ib(self) -> ib_insync.IB:
        """Return the underlying ib_insync IB instance for direct access."""
        return self._ib

    # ------------------------------------------------------------------ #
    # Read-only data — account                                            #
    # ------------------------------------------------------------------ #

    async def get_account(self) -> Optional[Account]:
        """
        Build and return an Account snapshot from cached ib_insync data.
        Returns None when not connected or on error.
        """
        if not self.is_connected():
            logger.error("Not connected — cannot fetch account")
            return None
        try:
            val_map: dict = {}
            for v in self._ib.accountValues():
                if v.currency in ("USD", "BASE", ""):
                    try:
                        val_map[v.tag] = float(v.value)
                    except (ValueError, TypeError):
                        val_map[v.tag] = v.value

            def _f(tag: str, default: float = 0.0) -> float:
                v = val_map.get(tag, default)
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return default

            positions: List[Position] = []
            for item in self._ib.portfolio():
                try:
                    qty = float(item.position or 0)
                    if qty == 0:
                        continue
                    avg = float(item.averageCost or 0)
                    mkt_p = float(item.marketPrice or 0)
                    mkt_v = float(item.marketValue or 0)
                    upnl = float(item.unrealizedPNL or 0)
                    cost_basis = qty * avg
                    upnl_pct = (upnl / cost_basis * 100) if cost_basis != 0 else 0.0
                    positions.append(
                        Position(
                            symbol=item.contract.symbol,
                            quantity=qty,
                            avg_cost=avg,
                            current_price=mkt_p,
                            market_value=mkt_v,
                            unrealized_pnl=upnl,
                            unrealized_pnl_pct=upnl_pct,
                            asset_class=item.contract.secType or "STK",
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        f"Skipping portfolio item {item.contract.symbol}: {exc}"
                    )

            return Account(
                account_id=self.account_id or "UNKNOWN",
                buying_power=_f("BuyingPower"),
                available_funds=_f("AvailableFunds"),
                total_value=_f("NetLiquidation"),
                cash=_f("TotalCashValue"),
                positions=positions,
            )
        except Exception as exc:
            logger.error(f"Failed to build account snapshot: {exc}")
            return None

    async def get_positions(self) -> List[Position]:
        """Return positions from the current account snapshot."""
        account = await self.get_account()
        return account.positions if account else []

    async def get_open_orders(self) -> List[Order]:
        """
        Return open orders reported by IB as Order schema objects.
        READ-ONLY — never modifies, cancels, or submits orders.
        """
        if not self.is_connected():
            logger.error("Not connected — cannot fetch open orders")
            return []
        try:
            orders: List[Order] = []
            for trade in self._ib.openTrades():
                try:
                    action = (
                        OrderAction.BUY
                        if trade.order.action == "BUY"
                        else OrderAction.SELL
                    )
                    o_type = (
                        OrderType.LIMIT
                        if trade.order.orderType in ("LMT", "LIMIT")
                        else OrderType.MARKET
                    )
                    lmt = None
                    try:
                        lmt_raw = trade.order.lmtPrice
                        if lmt_raw and not math.isnan(float(lmt_raw)):
                            lmt = float(lmt_raw)
                    except (TypeError, ValueError):
                        pass
                    orders.append(
                        Order(
                            order_id=int(trade.order.orderId),
                            symbol=trade.contract.symbol,
                            action=action,
                            quantity=float(trade.order.totalQuantity),
                            order_type=o_type,
                            limit_price=lmt,
                            status=OrderStatus.SUBMITTED,
                            broker_order_id=int(trade.order.orderId),
                        )
                    )
                except Exception as exc:
                    logger.warning(f"Skipping open trade: {exc}")
            return orders
        except Exception as exc:
            logger.error(f"Failed to fetch open orders: {exc}")
            return []

    # ------------------------------------------------------------------ #
    # Read-only data — market data                                        #
    # ------------------------------------------------------------------ #

    async def get_price(self, symbol: str) -> Optional[float]:
        """
        Fetch last (or close) price for a stock symbol.
        Returns None when not connected or data unavailable.
        """
        if not self.is_connected():
            logger.error("Not connected — cannot fetch price")
            return None
        try:
            contract = ib_insync.Stock(symbol, "SMART", "USD")
            qualified = await self._ib.qualifyContractsAsync(contract)
            if not qualified:
                logger.warning(f"Could not qualify contract for {symbol}")
                return None
            tickers = await self._ib.reqTickersAsync(qualified[0])
            if not tickers:
                return None
            t = tickers[0]

            def _valid(v) -> bool:
                try:
                    return v is not None and not math.isnan(float(v)) and float(v) > 0
                except (TypeError, ValueError):
                    return False

            for candidate in (t.last, t.close):
                if _valid(candidate):
                    return float(candidate)
            return None
        except Exception as exc:
            logger.error(f"Failed to fetch price for {symbol}: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # DISABLED — order methods                                            #
    # ------------------------------------------------------------------ #

    async def submit_order(
        self,
        symbol: str,
        action: str,
        quantity: float,
        order_type: str = "MARKET",
        limit_price: Optional[float] = None,
    ) -> Optional[int]:
        """
        ORDER SUBMISSION IS DISABLED IN THE READ-ONLY PHASE.
        Raises NotImplementedError — ib.placeOrder() is never called.
        """
        raise NotImplementedError(_SUBMIT_DISABLED)

    async def cancel_order(self, order_id: int) -> bool:
        """
        BROKER-SIDE ORDER CANCELLATION IS DISABLED IN THE READ-ONLY PHASE.
        Raises NotImplementedError — ib.cancelOrder() is never called.
        """
        raise NotImplementedError(_CANCEL_DISABLED)

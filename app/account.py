"""
Account management and state tracking.
"""

from typing import Optional, Dict, List
from datetime import datetime

from app.logger import get_logger
from app.schemas import Account, Position
from app.ibkr_client import IBKRClient

logger = get_logger(__name__)


class AccountManager:
    """Manages account state and balance tracking."""

    def __init__(self, ibkr_client: IBKRClient, read_only_api: bool = True):
        """
        Args:
            ibkr_client: IBKR client instance
            read_only_api: When True, skip any API call that requires TWS write
                           access (openTrades, reqOpenOrders).  Defaults to True
                           to stay compatible with TWS Read-Only API mode.
        """
        self.client = ibkr_client
        self.read_only_api = read_only_api
        self.current_account: Optional[Account] = None
        self.positions: Dict[str, Position] = {}
        self.last_update: Optional[datetime] = None

    # ------------------------------------------------------------------ #
    # Cached snapshot (populated by refresh())                            #
    # ------------------------------------------------------------------ #

    async def refresh(self) -> bool:
        """
        Refresh account and position data from IBKR.
        Populates the in-memory cache used by get_account() / get_position().

        Returns:
            True if refresh successful
        """
        try:
            logger.debug("Refreshing account data...")
            account = await self.client.get_account()
            if account:
                self.current_account = account
                self.last_update = datetime.utcnow()
                self.positions = {pos.symbol: pos for pos in account.positions}
                logger.info(
                    f"Account refreshed: "
                    f"Value=${account.total_value:,.2f}, "
                    f"Positions={len(self.positions)}"
                )
                return True
            logger.warning("Failed to refresh account (None returned)")
            return False
        except Exception as exc:
            logger.error(f"Error refreshing account: {exc}")
            return False

    def get_account(self) -> Optional[Account]:
        """Return the cached Account snapshot (populated by refresh())."""
        return self.current_account

    def get_position(self, symbol: str) -> Optional[Position]:
        """Return cached Position for a symbol."""
        return self.positions.get(symbol)

    def get_available_buying_power(self) -> float:
        """Return available buying power from the cached snapshot."""
        if not self.current_account:
            return 0.0
        return self.current_account.available_funds

    def get_total_portfolio_value(self) -> float:
        """Return total portfolio value from the cached snapshot."""
        if not self.current_account:
            return 0.0
        return self.current_account.total_value

    def get_cash(self) -> float:
        """Return cash from the cached snapshot."""
        if not self.current_account:
            return 0.0
        return self.current_account.cash

    # ------------------------------------------------------------------ #
    # Live read-only methods — return plain dicts/floats, not Pydantic    #
    # ------------------------------------------------------------------ #

    async def get_all_account_values(self) -> List[dict]:
        """
        Return every raw AccountValue entry from ib_insync as a list of plain dicts,
        each containing {account, tag, value, currency}.

        Use this for debugging when get_account_summary() returns zero values — it
        shows exactly what data IB has delivered and with which currency codes.
        """
        if not self.client.is_connected():
            logger.error("Not connected — cannot fetch account values")
            return []
        try:
            ib = self.client.get_ib()
            return [
                {
                    "account": v.account,
                    "tag": v.tag,
                    "value": v.value,
                    "currency": v.currency,
                }
                for v in ib.accountValues()
            ]
        except Exception as exc:
            logger.error(f"Error fetching all account values: {exc}")
            return []

    async def get_account_summary(self) -> dict:
        """
        Return a fresh account summary as a plain dict keyed by IB tag name.
        Values are converted to float where possible.
        Returns {} when not connected or on error.

        Selection priority for each tag (highest wins):
          3 — configured account_id + currency in (USD, BASE, '')
          2 — configured account_id + any other currency
          1 — any account + currency in (USD, BASE, '')
          0 — any account + any other currency

        This avoids silently dropping data when IB delivers values under an
        unexpected currency code or when no account_id is configured yet.
        """
        if not self.client.is_connected():
            logger.error("Not connected — cannot fetch account summary")
            return {}
        try:
            ib = self.client.get_ib()
            target = self.client.account_id or ""

            # best[tag] = (score, converted_value)
            best: dict = {}

            for v in ib.accountValues():
                account_match = bool(target and v.account == target)
                is_base = v.currency in ("USD", "BASE", "")
                score = (2 if account_match else 0) + (1 if is_base else 0)

                prev_score, _ = best.get(v.tag, (-1, None))
                if score > prev_score:
                    try:
                        best[v.tag] = (score, float(v.value))
                    except (ValueError, TypeError):
                        best[v.tag] = (score, v.value)

            summary: dict = {"account_id": target or "unknown"}
            summary.update({tag: val for tag, (_, val) in best.items()})
            return summary
        except Exception as exc:
            logger.error(f"Error fetching account summary: {exc}")
            return {}

    async def get_net_liquidation(self) -> float:
        """Return net liquidation value in USD."""
        summary = await self.get_account_summary()
        try:
            return float(summary.get("NetLiquidation", 0.0))
        except (ValueError, TypeError):
            return 0.0

    async def get_available_funds(self) -> float:
        """Return available funds in USD."""
        summary = await self.get_account_summary()
        try:
            return float(summary.get("AvailableFunds", 0.0))
        except (ValueError, TypeError):
            return 0.0

    async def get_buying_power(self) -> float:
        """Return buying power in USD."""
        summary = await self.get_account_summary()
        try:
            return float(summary.get("BuyingPower", 0.0))
        except (ValueError, TypeError):
            return 0.0

    async def get_positions(self) -> List[dict]:
        """
        Return current open positions as a list of plain dicts.
        Never returns Pydantic models.
        Returns [] when not connected or on error.
        """
        if not self.client.is_connected():
            logger.error("Not connected — cannot fetch positions")
            return []
        try:
            ib = self.client.get_ib()
            result: List[dict] = []
            for item in ib.portfolio():
                try:
                    qty = float(item.position or 0)
                    if qty == 0:
                        continue
                    result.append(
                        {
                            "symbol": item.contract.symbol,
                            "asset_class": item.contract.secType or "STK",
                            "quantity": qty,
                            "avg_cost": float(item.averageCost or 0),
                            "current_price": float(item.marketPrice or 0),
                            "market_value": float(item.marketValue or 0),
                            "unrealized_pnl": float(item.unrealizedPNL or 0),
                        }
                    )
                except Exception as exc:
                    logger.warning(
                        f"Skipping portfolio item {item.contract.symbol}: {exc}"
                    )
            return result
        except Exception as exc:
            logger.error(f"Error fetching positions: {exc}")
            return []

    async def get_open_orders(self) -> List[dict]:
        """
        Return open orders reported by IB as a list of plain dicts.
        READ-ONLY — never modifies, cancels, or submits orders.

        Returns [] (without any API call) when read_only_api=True, because
        ib.openTrades() / reqOpenOrders() require TWS write access and trigger
        an "API write access" warning in Read-Only mode.

        Returns [] when not connected or on error.
        """
        if self.read_only_api:
            logger.info(
                "get_open_orders skipped — read_only_api=True prevents openTrades() call"
            )
            return []
        if not self.client.is_connected():
            logger.error("Not connected — cannot fetch open orders")
            return []
        try:
            ib = self.client.get_ib()
            result: List[dict] = []
            for trade in ib.openTrades():
                try:
                    lmt_price = None
                    try:
                        import math
                        raw = float(trade.order.lmtPrice or "nan")
                        if not math.isnan(raw):
                            lmt_price = raw
                    except (TypeError, ValueError):
                        pass
                    result.append(
                        {
                            "order_id": int(trade.order.orderId),
                            "symbol": trade.contract.symbol,
                            "action": trade.order.action,
                            "quantity": float(trade.order.totalQuantity),
                            "order_type": trade.order.orderType,
                            "limit_price": lmt_price,
                            "status": trade.orderStatus.status,
                        }
                    )
                except Exception as exc:
                    logger.warning(f"Skipping open trade entry: {exc}")
            return result
        except Exception as exc:
            logger.error(f"Error fetching open orders: {exc}")
            return []

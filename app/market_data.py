"""
Market data management.
"""

import math
from typing import Optional, Dict
from datetime import datetime, timezone

import ib_insync

from app.logger import get_logger
from app.ibkr_client import IBKRClient

logger = get_logger(__name__)

# Maps config data_type string → IBKR reqMarketDataType() integer code.
# 1 = live (requires paid subscription)
# 2 = frozen (requires paid subscription)
# 3 = delayed 15-20 min (free, no subscription needed)
# 4 = delayed frozen from last close (free)
_DATA_TYPE_CODE: dict = {
    "live": 1,
    "frozen": 2,
    "delayed": 3,
    "delayed_frozen": 4,
}

# Every dict returned by get_stock_quote() is guaranteed to contain these keys.
_QUOTE_FIELDS = (
    "symbol", "price", "bid", "ask", "last", "close",
    "timestamp", "quote_quality", "is_stale", "data_type", "ibkr_error",
)


def _safe_float(value) -> Optional[float]:
    """Return float if value is finite and positive, else None."""
    try:
        v = float(value)
        return v if (not math.isnan(v) and v > 0) else None
    except (TypeError, ValueError):
        return None


class MarketDataManager:
    """Manages market data and price information."""

    def __init__(
        self,
        ibkr_client: IBKRClient,
        data_type: str = "delayed",
        stale_seconds: int = 300,
    ):
        """
        Args:
            ibkr_client:   IBKR client instance
            data_type:     One of 'live', 'frozen', 'delayed', 'delayed_frozen'.
                           Determines the reqMarketDataType() code sent to TWS
                           before every ticker request. Defaults to 'delayed'
                           (IBKR type 3) which is free and needs no subscription.
            stale_seconds: Cache TTL in seconds for the legacy get_price() method.
        """
        self.client = ibkr_client
        self.data_type = data_type if data_type in _DATA_TYPE_CODE else "delayed"
        self.stale_seconds = stale_seconds
        self.price_cache: Dict[str, float] = {}
        self.cache_times: Dict[str, datetime] = {}

    # ------------------------------------------------------------------ #
    # Legacy single-price method (uses IBKRClient.get_price)              #
    # ------------------------------------------------------------------ #

    async def get_price(self, symbol: str, use_cache: bool = True) -> Optional[float]:
        """Get current price for a symbol, with a cache of stale_seconds."""
        if use_cache and symbol in self.price_cache:
            elapsed = (datetime.utcnow() - self.cache_times[symbol]).total_seconds()
            if elapsed < self.stale_seconds:
                logger.debug(f"Using cached price for {symbol}")
                return self.price_cache[symbol]

        price = await self.client.get_price(symbol)
        if price:
            self.price_cache[symbol] = price
            self.cache_times[symbol] = datetime.utcnow()
            logger.debug(f"Fetched price for {symbol}: ${price:.2f}")
        return price

    def get_cached_price(self, symbol: str) -> Optional[float]:
        """Return cached price without a network fetch."""
        return self.price_cache.get(symbol)

    def clear_cache(self) -> None:
        """Clear price cache."""
        self.price_cache.clear()
        self.cache_times.clear()

    # ------------------------------------------------------------------ #
    # Full quote — returns dict with all _QUOTE_FIELDS                    #
    # ------------------------------------------------------------------ #

    async def get_stock_quote(self, symbol: str) -> dict:
        """
        Fetch a full market snapshot for an equity.

        Before requesting the ticker, calls ib.reqMarketDataType(code) where
        code is determined by self.data_type:
            'delayed' (default) → code 3  (free, 15-20 min delayed)
            'delayed_frozen'    → code 4  (free, last-close delayed)
            'live'              → code 1  (requires paid subscription)
            'frozen'            → code 2  (requires paid subscription)

        All eleven fields in _QUOTE_FIELDS are always present in the result.

        quote_quality:
          'complete'   — at least one of bid/ask/last is a valid positive number
          'incomplete' — all price fields are missing, zero, or NaN

        ibkr_error:
          None if no IBKR error occurred during the request.
          {'code': int, 'message': str} if TWS reported an error (e.g. 10168).

        Never triggers any order. Read-only.
        """
        if not self.client.is_connected():
            logger.warning(f"Not connected — returning stale incomplete quote for {symbol}")
            return self._empty_quote(symbol, reason="not_connected")

        try:
            ib = self.client.get_ib()

            # ── Set market data type before any ticker request ─────────
            type_code = _DATA_TYPE_CODE.get(self.data_type, 3)
            ib.reqMarketDataType(type_code)
            logger.debug(
                f"reqMarketDataType({type_code}) set "
                f"(data_type='{self.data_type}') for {symbol}"
            )

            # ── Qualify contract ───────────────────────────────────────
            contract = ib_insync.Stock(symbol, "SMART", "USD")
            qualified = await ib.qualifyContractsAsync(contract)
            if not qualified:
                logger.warning(f"Could not qualify contract for {symbol}")
                return self._empty_quote(symbol, reason="contract_not_qualified")

            # ── Subscribe to errors for this request ───────────────────
            captured_errors: list = []

            def _on_error(reqId, errorCode, errorString, contract):
                captured_errors.append({"code": errorCode, "message": errorString})

            ib.errorEvent += _on_error
            try:
                tickers = await ib.reqTickersAsync(qualified[0])
            finally:
                ib.errorEvent -= _on_error

            # ── Extract prices ─────────────────────────────────────────
            if not tickers:
                first_error = captured_errors[0] if captured_errors else None
                q = self._empty_quote(symbol, reason="no_ticker_data")
                q["ibkr_error"] = first_error
                return q

            t = tickers[0]
            bid = _safe_float(t.bid)
            ask = _safe_float(t.ask)
            last = _safe_float(t.last)
            close = _safe_float(t.close)

            has_price = any(v is not None for v in (bid, ask, last))
            quote_quality = "complete" if has_price else "incomplete"

            # Best representative price: last > ask > bid > close
            price = next(
                (v for v in (last, ask, bid, close) if v is not None), 0.0
            )

            first_error = captured_errors[0] if captured_errors else None

            if first_error:
                logger.warning(
                    f"IBKR error during quote for {symbol}: "
                    f"[{first_error['code']}] {first_error['message']}"
                )

            return {
                "symbol": symbol,
                "price": price,
                "bid": bid,
                "ask": ask,
                "last": last,
                "close": close,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "quote_quality": quote_quality,
                "is_stale": False,
                "data_type": self.data_type,
                "ibkr_error": first_error,
            }

        except Exception as exc:
            logger.error(f"Error fetching quote for {symbol}: {exc}")
            return self._empty_quote(symbol, reason=str(exc))

    def _empty_quote(self, symbol: str, reason: str = "unknown") -> dict:
        """
        Return an unambiguously incomplete, stale quote with all required fields.
        ibkr_error is always None here; callers may overwrite it after the fact.
        """
        logger.warning(f"Returning empty quote for {symbol} (reason: {reason})")
        return {
            "symbol": symbol,
            "price": 0.0,
            "bid": None,
            "ask": None,
            "last": None,
            "close": None,
            "timestamp": None,
            "quote_quality": "incomplete",
            "is_stale": True,
            "data_type": self.data_type,
            "ibkr_error": None,
        }

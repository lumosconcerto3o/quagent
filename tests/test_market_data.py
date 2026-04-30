"""
Tests for MarketDataManager.
All tests are offline — IBKRClient and ib_insync are mocked.
"""

import math
import pytest
from unittest.mock import MagicMock, AsyncMock

from app.market_data import MarketDataManager
from app.ibkr_client import IBKRClient

_REQUIRED_FIELDS = {
    "symbol", "price", "bid", "ask", "last",
    "close", "timestamp", "quote_quality", "is_stale",
    "data_type", "ibkr_error",
}


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _make_manager(connected: bool = True, data_type: str = "delayed"):
    """Return a (MarketDataManager, mock_ib) pair."""
    mock_client = MagicMock(spec=IBKRClient)
    mock_client.is_connected.return_value = connected

    mock_ib = MagicMock()
    mock_client.get_ib.return_value = mock_ib

    return MarketDataManager(mock_client, data_type=data_type), mock_ib


def _setup_ticker(mock_ib, bid, ask, last, close):
    """Wire mock_ib to return a single Ticker with the given price fields."""
    fake_contract = MagicMock()
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=[fake_contract])

    ticker = MagicMock()
    ticker.bid = bid
    ticker.ask = ask
    ticker.last = last
    ticker.close = close
    mock_ib.reqTickersAsync = AsyncMock(return_value=[ticker])


# ------------------------------------------------------------------ #
# Required fields always present                                      #
# ------------------------------------------------------------------ #

async def test_quote_always_has_required_fields_when_disconnected():
    """An empty / stale quote must contain all required keys."""
    mgr, _ = _make_manager(connected=False)
    quote = await mgr.get_stock_quote("AAPL")
    assert _REQUIRED_FIELDS.issubset(quote.keys())


async def test_quote_always_has_required_fields_when_connected():
    """A successful quote must also contain all required keys."""
    mgr, mock_ib = _make_manager(connected=True)
    _setup_ticker(mock_ib, bid=149.9, ask=150.1, last=150.0, close=148.5)

    quote = await mgr.get_stock_quote("AAPL")
    assert _REQUIRED_FIELDS.issubset(quote.keys())


# ------------------------------------------------------------------ #
# quote_quality — incomplete                                          #
# ------------------------------------------------------------------ #

async def test_incomplete_quote_when_all_prices_nan():
    """When bid/ask/last are all NaN, quote_quality must be 'incomplete'."""
    mgr, mock_ib = _make_manager(connected=True)
    _setup_ticker(mock_ib, bid=float("nan"), ask=float("nan"),
                  last=float("nan"), close=float("nan"))

    quote = await mgr.get_stock_quote("AAPL")

    assert quote["quote_quality"] == "incomplete"
    assert quote["symbol"] == "AAPL"


async def test_incomplete_quote_when_disconnected():
    """A disconnected client must return is_stale=True and incomplete quality."""
    mgr, _ = _make_manager(connected=False)
    quote = await mgr.get_stock_quote("SPY")

    assert quote["quote_quality"] == "incomplete"
    assert quote["is_stale"] is True
    assert quote["price"] == 0.0


async def test_incomplete_quote_when_contract_not_qualified():
    """If contract qualification fails, quote must be incomplete."""
    mgr, mock_ib = _make_manager(connected=True)
    mock_ib.qualifyContractsAsync = AsyncMock(return_value=[])  # empty → not qualified

    quote = await mgr.get_stock_quote("INVALID")

    assert quote["quote_quality"] == "incomplete"
    assert quote["is_stale"] is True


# ------------------------------------------------------------------ #
# quote_quality — complete                                            #
# ------------------------------------------------------------------ #

async def test_complete_quote_when_prices_valid():
    """Valid bid/ask/last should produce a complete quote."""
    mgr, mock_ib = _make_manager(connected=True)
    _setup_ticker(mock_ib, bid=149.9, ask=150.1, last=150.0, close=148.5)

    quote = await mgr.get_stock_quote("AAPL")

    assert quote["quote_quality"] == "complete"
    assert quote["bid"] == 149.9
    assert quote["ask"] == 150.1
    assert quote["last"] == 150.0
    assert quote["close"] == 148.5
    assert quote["is_stale"] is False


async def test_best_price_prefers_last():
    """The 'price' field should prefer last over ask/bid/close."""
    mgr, mock_ib = _make_manager(connected=True)
    _setup_ticker(mock_ib, bid=149.9, ask=150.1, last=150.0, close=148.5)

    quote = await mgr.get_stock_quote("AAPL")
    assert quote["price"] == 150.0  # last is preferred


async def test_best_price_falls_back_to_ask_when_no_last():
    """When last is NaN, 'price' should fall back to ask."""
    mgr, mock_ib = _make_manager(connected=True)
    _setup_ticker(mock_ib, bid=149.9, ask=150.1, last=float("nan"), close=148.5)

    quote = await mgr.get_stock_quote("AAPL")
    assert quote["price"] == 150.1  # ask fallback
    assert quote["quote_quality"] == "complete"  # ask is still valid


# ------------------------------------------------------------------ #
# Stale flag                                                          #
# ------------------------------------------------------------------ #

async def test_is_stale_false_on_successful_fetch():
    """A successfully fetched quote must have is_stale=False."""
    mgr, mock_ib = _make_manager(connected=True)
    _setup_ticker(mock_ib, bid=100.0, ask=100.2, last=100.1, close=99.5)

    quote = await mgr.get_stock_quote("GOOG")
    assert quote["is_stale"] is False


# ------------------------------------------------------------------ #
# reqMarketDataType — called before every ticker request              #
# ------------------------------------------------------------------ #

async def test_delayed_mode_calls_req_market_data_type_3():
    """In delayed mode, ib.reqMarketDataType(3) must be called before reqTickersAsync."""
    mgr, mock_ib = _make_manager(data_type="delayed")
    _setup_ticker(mock_ib, bid=149.9, ask=150.1, last=150.0, close=148.5)

    await mgr.get_stock_quote("SPY")

    mock_ib.reqMarketDataType.assert_called_once_with(3)


async def test_delayed_frozen_mode_calls_req_market_data_type_4():
    """In delayed_frozen mode, ib.reqMarketDataType(4) must be called."""
    mgr, mock_ib = _make_manager(data_type="delayed_frozen")
    _setup_ticker(mock_ib, bid=149.9, ask=150.1, last=150.0, close=148.5)

    await mgr.get_stock_quote("SPY")

    mock_ib.reqMarketDataType.assert_called_once_with(4)


async def test_live_mode_calls_req_market_data_type_1():
    """In live mode, ib.reqMarketDataType(1) must be called."""
    mgr, mock_ib = _make_manager(data_type="live")
    _setup_ticker(mock_ib, bid=149.9, ask=150.1, last=150.0, close=148.5)

    await mgr.get_stock_quote("SPY")

    mock_ib.reqMarketDataType.assert_called_once_with(1)


async def test_incomplete_quote_after_delayed_request_with_nan_prices():
    """
    Even after reqMarketDataType(3), if all prices are NaN the quote must
    remain incomplete — delayed mode does not fake prices.
    """
    mgr, mock_ib = _make_manager(data_type="delayed")
    _setup_ticker(
        mock_ib,
        bid=float("nan"), ask=float("nan"),
        last=float("nan"), close=float("nan"),
    )

    quote = await mgr.get_stock_quote("XYZ")

    # reqMarketDataType was still called (we made the attempt)
    mock_ib.reqMarketDataType.assert_called_once_with(3)
    # But quality must be incomplete — no price was faked
    assert quote["quote_quality"] == "incomplete"
    assert quote["price"] == 0.0
    assert quote["bid"] is None
    assert quote["ask"] is None
    assert quote["last"] is None


async def test_quote_includes_data_type_field():
    """The 'data_type' field must reflect the configured type."""
    mgr_d, mock_ib_d = _make_manager(data_type="delayed")
    _setup_ticker(mock_ib_d, bid=10.0, ask=10.1, last=10.05, close=9.9)
    quote_d = await mgr_d.get_stock_quote("A")
    assert quote_d["data_type"] == "delayed"

    mgr_l, mock_ib_l = _make_manager(data_type="live")
    _setup_ticker(mock_ib_l, bid=10.0, ask=10.1, last=10.05, close=9.9)
    quote_l = await mgr_l.get_stock_quote("A")
    assert quote_l["data_type"] == "live"


async def test_ibkr_error_field_is_none_on_success():
    """When no IBKR error occurs, ibkr_error must be None."""
    mgr, mock_ib = _make_manager(data_type="delayed")
    _setup_ticker(mock_ib, bid=100.0, ask=100.2, last=100.1, close=99.5)

    quote = await mgr.get_stock_quote("AAPL")

    assert quote["ibkr_error"] is None


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])

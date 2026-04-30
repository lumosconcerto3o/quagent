"""
Tests for IBKRClient.
All tests are offline — ib_insync is mocked; no real broker connection required.
"""

import pytest
from collections import namedtuple
from unittest.mock import MagicMock, AsyncMock, call

from app.ibkr_client import IBKRClient


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _make_client() -> IBKRClient:
    """Return an IBKRClient whose internal _ib is replaced by a MagicMock."""
    client = IBKRClient(host="127.0.0.1", port=7497, client_id=1)
    mock_ib = MagicMock()
    mock_ib.isConnected.return_value = False
    client._ib = mock_ib
    return client


AccountValue = namedtuple("AccountValue", ["account", "tag", "value", "currency"])


# ------------------------------------------------------------------ #
# submit_order / cancel_order disabled                                #
# ------------------------------------------------------------------ #

async def test_submit_order_raises_not_implemented():
    """submit_order must raise NotImplementedError — ib.placeOrder() never called."""
    client = _make_client()
    client._ib.isConnected.return_value = True

    with pytest.raises(NotImplementedError) as exc_info:
        await client.submit_order("AAPL", "BUY", 100)

    assert "disabled" in str(exc_info.value).lower()
    client._ib.placeOrder.assert_not_called()


async def test_cancel_order_raises_not_implemented():
    """cancel_order must raise NotImplementedError — ib.cancelOrder() never called."""
    client = _make_client()
    client._ib.isConnected.return_value = True

    with pytest.raises(NotImplementedError) as exc_info:
        await client.cancel_order(999)

    assert "disabled" in str(exc_info.value).lower()
    client._ib.cancelOrder.assert_not_called()


async def test_submit_order_disabled_even_when_disconnected():
    """submit_order raises NotImplementedError regardless of connection state."""
    client = _make_client()
    client._ib.isConnected.return_value = False  # disconnected

    with pytest.raises(NotImplementedError):
        await client.submit_order("MSFT", "SELL", 50)


# ------------------------------------------------------------------ #
# Connection state                                                    #
# ------------------------------------------------------------------ #

def test_is_connected_delegates_to_ib():
    """is_connected() must mirror ib.isConnected() truthfully."""
    client = _make_client()

    client._ib.isConnected.return_value = False
    assert client.is_connected() is False

    client._ib.isConnected.return_value = True
    assert client.is_connected() is True


def test_get_ib_returns_internal_ib_object():
    """get_ib() must return the underlying ib_insync IB instance."""
    client = _make_client()
    assert client.get_ib() is client._ib


# ------------------------------------------------------------------ #
# Account data                                                        #
# ------------------------------------------------------------------ #

async def test_get_account_returns_none_when_disconnected():
    """get_account must return None when is_connected() is False."""
    client = _make_client()
    client._ib.isConnected.return_value = False

    result = await client.get_account()
    assert result is None


async def test_get_account_returns_account_object_when_connected():
    """get_account must build an Account from accountValues() and portfolio()."""
    client = _make_client()
    client._ib.isConnected.return_value = True
    client.account_id = "DU999999"

    client._ib.accountValues.return_value = [
        AccountValue("DU999999", "NetLiquidation", "100000.00", "USD"),
        AccountValue("DU999999", "AvailableFunds", "50000.00", "USD"),
        AccountValue("DU999999", "BuyingPower", "75000.00", "USD"),
        AccountValue("DU999999", "TotalCashValue", "50000.00", "USD"),
    ]
    client._ib.portfolio.return_value = []  # no positions for simplicity

    account = await client.get_account()

    assert account is not None
    assert account.account_id == "DU999999"
    assert account.total_value == 100000.0
    assert account.available_funds == 50000.0
    assert account.buying_power == 75000.0
    assert account.cash == 50000.0
    assert isinstance(account.positions, list)
    assert len(account.positions) == 0


async def test_get_account_maps_portfolio_items_to_positions():
    """Positions in the portfolio must appear in the returned Account."""
    client = _make_client()
    client._ib.isConnected.return_value = True
    client.account_id = "DU111111"

    client._ib.accountValues.return_value = [
        AccountValue("DU111111", "NetLiquidation", "200000.00", "USD"),
        AccountValue("DU111111", "AvailableFunds", "80000.00", "USD"),
        AccountValue("DU111111", "BuyingPower", "80000.00", "USD"),
        AccountValue("DU111111", "TotalCashValue", "80000.00", "USD"),
    ]

    contract = MagicMock()
    contract.symbol = "AAPL"
    contract.secType = "STK"

    portfolio_item = MagicMock()
    portfolio_item.contract = contract
    portfolio_item.position = 100.0
    portfolio_item.averageCost = 150.0
    portfolio_item.marketPrice = 155.0
    portfolio_item.marketValue = 15500.0
    portfolio_item.unrealizedPNL = 500.0

    client._ib.portfolio.return_value = [portfolio_item]

    account = await client.get_account()

    assert account is not None
    assert len(account.positions) == 1
    pos = account.positions[0]
    assert pos.symbol == "AAPL"
    assert pos.quantity == 100.0
    assert pos.avg_cost == 150.0


# ------------------------------------------------------------------ #
# readonly= passed to connectAsync                                    #
# ------------------------------------------------------------------ #

async def test_connect_async_receives_readonly_true_when_configured():
    """When read_only_api=True, connectAsync must receive readonly=True."""
    client = IBKRClient(host="127.0.0.1", port=7497, client_id=1, read_only_api=True)
    mock_ib = MagicMock()
    mock_ib.connectAsync = AsyncMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    client._ib = mock_ib

    await client.connect()

    mock_ib.connectAsync.assert_called_once()
    kwargs = mock_ib.connectAsync.call_args.kwargs
    assert kwargs.get("readonly") is True


async def test_connect_async_receives_readonly_false_when_configured_false():
    """When read_only_api=False, connectAsync must receive readonly=False."""
    client = IBKRClient(host="127.0.0.1", port=7497, client_id=1, read_only_api=False)
    mock_ib = MagicMock()
    mock_ib.connectAsync = AsyncMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    client._ib = mock_ib

    await client.connect()

    mock_ib.connectAsync.assert_called_once()
    kwargs = mock_ib.connectAsync.call_args.kwargs
    assert kwargs.get("readonly") is False


async def test_submit_order_still_raises_not_implemented():
    """submit_order still raises NotImplementedError after the readonly change."""
    client = IBKRClient(read_only_api=True)
    mock_ib = MagicMock()
    mock_ib.isConnected.return_value = True
    client._ib = mock_ib

    with pytest.raises(NotImplementedError):
        await client.submit_order("AAPL", "BUY", 10)

    mock_ib.placeOrder.assert_not_called()


async def test_cancel_order_still_raises_not_implemented():
    """cancel_order still raises NotImplementedError after the readonly change."""
    client = IBKRClient(read_only_api=True)
    mock_ib = MagicMock()
    mock_ib.isConnected.return_value = True
    client._ib = mock_ib

    with pytest.raises(NotImplementedError):
        await client.cancel_order(42)

    mock_ib.cancelOrder.assert_not_called()


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])

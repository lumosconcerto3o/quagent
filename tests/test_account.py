"""
Tests for AccountManager read-only methods.
All tests are offline — IBKRClient and ib_insync are mocked.
"""

import pytest
from collections import namedtuple
from unittest.mock import MagicMock

from app.account import AccountManager
from app.ibkr_client import IBKRClient

AccountValue = namedtuple("AccountValue", ["account", "tag", "value", "currency"])


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _connected_manager(read_only_api: bool = False):
    """
    Return (AccountManager, mock_ib) with a connected mock client.
    Defaults to read_only_api=False so existing open-orders tests exercise
    the real fetch path; use read_only_api=True to test the guard.
    """
    mock_client = MagicMock(spec=IBKRClient)
    mock_client.is_connected.return_value = True
    mock_client.account_id = "DU123456"

    mock_ib = MagicMock()
    mock_client.get_ib.return_value = mock_ib

    return AccountManager(mock_client, read_only_api=read_only_api), mock_ib


def _disconnected_manager(read_only_api: bool = False):
    """
    Return an AccountManager whose client reports disconnected.
    Defaults to read_only_api=False so tests verify the disconnection
    guard independently of the read-only guard.
    """
    mock_client = MagicMock(spec=IBKRClient)
    mock_client.is_connected.return_value = False
    return AccountManager(mock_client, read_only_api=read_only_api)


# ------------------------------------------------------------------ #
# get_account_summary                                                 #
# ------------------------------------------------------------------ #

async def test_account_summary_returns_plain_dict():
    """get_account_summary must return a plain dict, not a Pydantic model."""
    mgr, mock_ib = _connected_manager()
    mock_ib.accountValues.return_value = [
        AccountValue("DU123456", "NetLiquidation", "100000.00", "USD"),
        AccountValue("DU123456", "AvailableFunds", "50000.00", "USD"),
        AccountValue("DU123456", "BuyingPower", "75000.00", "USD"),
    ]

    summary = await mgr.get_account_summary()

    assert isinstance(summary, dict)
    assert summary.get("NetLiquidation") == 100000.0
    assert summary.get("AvailableFunds") == 50000.0
    assert summary.get("BuyingPower") == 75000.0


async def test_account_summary_empty_when_disconnected():
    """get_account_summary must return {} when not connected."""
    mgr = _disconnected_manager()
    assert await mgr.get_account_summary() == {}


# ------------------------------------------------------------------ #
# get_net_liquidation / get_available_funds / get_buying_power       #
# ------------------------------------------------------------------ #

async def test_get_net_liquidation_extracts_correct_tag():
    """get_net_liquidation must read NetLiquidation from account values."""
    mgr, mock_ib = _connected_manager()
    mock_ib.accountValues.return_value = [
        AccountValue("DU123456", "NetLiquidation", "123456.78", "USD"),
    ]
    assert await mgr.get_net_liquidation() == 123456.78


async def test_get_available_funds_extracts_correct_tag():
    mgr, mock_ib = _connected_manager()
    mock_ib.accountValues.return_value = [
        AccountValue("DU123456", "AvailableFunds", "42000.00", "USD"),
    ]
    assert await mgr.get_available_funds() == 42000.0


async def test_get_buying_power_extracts_correct_tag():
    mgr, mock_ib = _connected_manager()
    mock_ib.accountValues.return_value = [
        AccountValue("DU123456", "BuyingPower", "84000.00", "USD"),
    ]
    assert await mgr.get_buying_power() == 84000.0


# ------------------------------------------------------------------ #
# get_positions                                                       #
# ------------------------------------------------------------------ #

async def test_get_positions_returns_list_of_plain_dicts():
    """get_positions must return a list of plain dicts, not Pydantic models."""
    mgr, mock_ib = _connected_manager()

    contract = MagicMock()
    contract.symbol = "AAPL"
    contract.secType = "STK"

    item = MagicMock()
    item.contract = contract
    item.position = 100.0
    item.averageCost = 150.0
    item.marketPrice = 155.0
    item.marketValue = 15500.0
    item.unrealizedPNL = 500.0

    mock_ib.portfolio.return_value = [item]

    positions = await mgr.get_positions()

    assert isinstance(positions, list)
    assert len(positions) == 1
    pos = positions[0]
    assert isinstance(pos, dict)           # must be plain dict
    assert pos["symbol"] == "AAPL"
    assert pos["quantity"] == 100.0
    assert pos["asset_class"] == "STK"
    assert pos["avg_cost"] == 150.0
    assert pos["current_price"] == 155.0
    assert pos["market_value"] == 15500.0
    assert pos["unrealized_pnl"] == 500.0


async def test_get_positions_skips_zero_quantity():
    """Positions with zero quantity must not appear in the result."""
    mgr, mock_ib = _connected_manager()

    contract = MagicMock()
    contract.symbol = "MSFT"
    contract.secType = "STK"

    item = MagicMock()
    item.contract = contract
    item.position = 0.0  # zero quantity — should be skipped
    item.averageCost = 200.0
    item.marketPrice = 210.0
    item.marketValue = 0.0
    item.unrealizedPNL = 0.0

    mock_ib.portfolio.return_value = [item]

    positions = await mgr.get_positions()
    assert positions == []


async def test_get_positions_empty_when_disconnected():
    """get_positions must return [] when not connected."""
    mgr = _disconnected_manager()
    assert await mgr.get_positions() == []


# ------------------------------------------------------------------ #
# get_open_orders                                                     #
# ------------------------------------------------------------------ #

async def test_get_open_orders_returns_list_of_plain_dicts():
    """get_open_orders must return a list of plain dicts."""
    mgr, mock_ib = _connected_manager()

    contract = MagicMock()
    contract.symbol = "SPY"

    order = MagicMock()
    order.orderId = 101
    order.action = "BUY"
    order.totalQuantity = 50.0
    order.orderType = "LMT"
    order.lmtPrice = 420.0

    order_status = MagicMock()
    order_status.status = "Submitted"

    trade = MagicMock()
    trade.contract = contract
    trade.order = order
    trade.orderStatus = order_status

    mock_ib.openTrades.return_value = [trade]

    orders = await mgr.get_open_orders()

    assert isinstance(orders, list)
    assert len(orders) == 1
    o = orders[0]
    assert isinstance(o, dict)
    assert o["symbol"] == "SPY"
    assert o["action"] == "BUY"
    assert o["quantity"] == 50.0


async def test_get_open_orders_empty_when_disconnected():
    """get_open_orders must return [] when not connected."""
    mgr = _disconnected_manager()
    assert await mgr.get_open_orders() == []


# ------------------------------------------------------------------ #
# read_only_api guard                                                  #
# ------------------------------------------------------------------ #

async def test_get_open_orders_returns_empty_when_read_only():
    """When read_only_api=True, get_open_orders must return [] without any IB call."""
    mgr, mock_ib = _connected_manager(read_only_api=True)

    result = await mgr.get_open_orders()

    assert result == []
    mock_ib.openTrades.assert_not_called()


async def test_get_open_orders_calls_open_trades_when_not_read_only():
    """When read_only_api=False, get_open_orders must call ib.openTrades()."""
    mgr, mock_ib = _connected_manager(read_only_api=False)
    mock_ib.openTrades.return_value = []  # no open trades, but the call must happen

    await mgr.get_open_orders()

    mock_ib.openTrades.assert_called_once()


# ------------------------------------------------------------------ #
# get_all_account_values                                              #
# ------------------------------------------------------------------ #

async def test_get_all_account_values_returns_every_entry():
    """get_all_account_values must return all entries regardless of currency."""
    mgr, mock_ib = _connected_manager()
    mock_ib.accountValues.return_value = [
        AccountValue("DU123456", "NetLiquidation", "100000.00", "USD"),
        AccountValue("DU123456", "NetLiquidation", "100000.00", "BASE"),
        AccountValue("DU123456", "BuyingPower",    "50000.00",  "EUR"),  # non-standard ccy
    ]

    result = await mgr.get_all_account_values()

    assert len(result) == 3
    assert all(isinstance(r, dict) for r in result)
    required_keys = {"account", "tag", "value", "currency"}
    assert all(required_keys.issubset(r.keys()) for r in result)
    tags = {r["tag"] for r in result}
    assert "NetLiquidation" in tags
    assert "BuyingPower" in tags


async def test_get_all_account_values_empty_when_disconnected():
    """get_all_account_values must return [] when not connected."""
    mgr = _disconnected_manager()
    assert await mgr.get_all_account_values() == []


# ------------------------------------------------------------------ #
# get_account_summary — improved mapping                             #
# ------------------------------------------------------------------ #

async def test_account_summary_prefers_configured_account_id():
    """
    When multiple accounts appear in accountValues, the configured account_id
    must win over values from other accounts.
    """
    mgr, mock_ib = _connected_manager()  # account_id = "DU123456"
    mock_ib.accountValues.return_value = [
        AccountValue("DU999999", "NetLiquidation", "1.00",       "USD"),  # wrong account
        AccountValue("DU123456", "NetLiquidation", "100000.00",  "USD"),  # target account
    ]

    summary = await mgr.get_account_summary()

    assert summary.get("NetLiquidation") == 100000.0


async def test_account_summary_prefers_base_currency_over_other():
    """
    For the same tag and same account, BASE/USD currency must win over
    non-base currencies (e.g. EUR).
    """
    mgr, mock_ib = _connected_manager()
    mock_ib.accountValues.return_value = [
        AccountValue("DU123456", "NetLiquidation", "89000.00",  "EUR"),   # EUR variant
        AccountValue("DU123456", "NetLiquidation", "100000.00", "BASE"),  # BASE variant
    ]

    summary = await mgr.get_account_summary()

    assert summary.get("NetLiquidation") == 100000.0  # BASE preferred


async def test_account_summary_falls_back_when_no_configured_account():
    """
    When account_id is not yet set, values from any account must still be
    included so the summary is not empty.
    """
    mock_client = MagicMock(spec=IBKRClient)
    mock_client.is_connected.return_value = True
    mock_client.account_id = ""  # not yet known

    mock_ib = MagicMock()
    mock_ib.accountValues.return_value = [
        AccountValue("DU888888", "NetLiquidation", "200000.00", "USD"),
    ]
    mock_client.get_ib.return_value = mock_ib

    mgr = AccountManager(mock_client)
    summary = await mgr.get_account_summary()

    assert summary.get("NetLiquidation") == 200000.0


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])

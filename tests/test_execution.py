"""
Tests for ExecutionEngine safety gates.
All tests are offline — no IBKR connection required.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.execution import ExecutionEngine
from app.oms import OrderManagementSystem
from app.risk import RiskEngine
from app.kill_switch import KillSwitch
from app.ibkr_client import IBKRClient
from app.config import QuAgentConfig
from app.schemas import Signal, OrderAction, OrderType, OrderStatus


@pytest.fixture
def config():
    return QuAgentConfig(
        trading_mode='paper',
        account={
            'max_position_size': 10000,
            'buying_power_limit': 500000,
            'max_daily_loss_pct': 2.0,
            'max_order_notional_usd': 50000,
        }
    )


@pytest.fixture
def oms():
    return OrderManagementSystem()


@pytest.fixture
def risk_engine(config):
    return RiskEngine(config)


@pytest.fixture
def mock_ibkr():
    """Mock IBKRClient that reports connected and returns broker order ID 42."""
    client = MagicMock(spec=IBKRClient)
    client.is_connected.return_value = True
    client.submit_order = AsyncMock(return_value=42)
    return client


@pytest.fixture
def kill_switch():
    return KillSwitch()


def _make_validated_order(oms: OrderManagementSystem):
    """Helper: create and validate an order, returning the order object."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=10,
        limit_price=150.0,
    )
    order = oms.create_order_from_signal(signal)
    oms.update_order_status(order.order_id, OrderStatus.VALIDATED)
    return oms.get_order(order.order_id)


async def test_dry_run_defaults_to_true(mock_ibkr, oms, risk_engine):
    """ExecutionEngine must default dry_run=True."""
    engine = ExecutionEngine(mock_ibkr, oms, risk_engine)
    assert engine.dry_run is True


async def test_dry_run_does_not_call_submit_order(mock_ibkr, oms, risk_engine):
    """In dry_run mode, client.submit_order must never be called."""
    engine = ExecutionEngine(mock_ibkr, oms, risk_engine, dry_run=True)
    order = _make_validated_order(oms)

    result = await engine.execute_order(order)

    assert result is True
    mock_ibkr.submit_order.assert_not_called()


async def test_execution_blocked_when_kill_switch_active(mock_ibkr, oms, risk_engine, kill_switch):
    """ExecutionEngine must reject and mark REJECTED when kill switch is active."""
    kill_switch.trigger("Emergency stop", "test")
    engine = ExecutionEngine(mock_ibkr, oms, risk_engine, dry_run=True, kill_switch=kill_switch)
    order = _make_validated_order(oms)

    result = await engine.execute_order(order)

    assert result is False
    mock_ibkr.submit_order.assert_not_called()

    refreshed = oms.get_order(order.order_id)
    assert refreshed.status == OrderStatus.REJECTED


async def test_execution_requires_validated_status(mock_ibkr, oms, risk_engine):
    """ExecutionEngine must refuse orders that are not in VALIDATED status."""
    engine = ExecutionEngine(mock_ibkr, oms, risk_engine, dry_run=True)

    # Create an order but leave it in PENDING — not VALIDATED
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=10, limit_price=150.0)
    order = oms.create_order_from_signal(signal)
    assert order.status == OrderStatus.PENDING

    result = await engine.execute_order(order)

    assert result is False
    mock_ibkr.submit_order.assert_not_called()
    # Status must not have been changed by the refusal
    refreshed = oms.get_order(order.order_id)
    assert refreshed.status == OrderStatus.PENDING


async def test_dry_run_broker_order_id_remains_none(mock_ibkr, oms, risk_engine):
    """In dry_run mode, broker_order_id must remain None (no real submission)."""
    engine = ExecutionEngine(mock_ibkr, oms, risk_engine, dry_run=True)
    order = _make_validated_order(oms)

    await engine.execute_order(order)

    refreshed = oms.get_order(order.order_id)
    assert refreshed.broker_order_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

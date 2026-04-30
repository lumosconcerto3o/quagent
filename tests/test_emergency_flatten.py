"""
Tests for emergency_flatten.plan_flatten().
All tests are offline — no IBKR connection required.
plan_flatten() is a pure function that works only on Position data.
"""

import pytest
from app.schemas import Position, OrderAction, OrderType


def _pos(symbol: str, quantity: float, asset_class: str = "STK") -> Position:
    """Helper: build a minimal Position for testing."""
    abs_qty = abs(quantity)
    return Position(
        symbol=symbol,
        quantity=quantity,
        asset_class=asset_class,
        avg_cost=100.0,
        current_price=105.0,
        market_value=abs_qty * 105.0,
        unrealized_pnl=abs_qty * 5.0,
        unrealized_pnl_pct=5.0,
    )


def test_plan_flatten_returns_sell_for_long_position():
    """A long (positive quantity) equity position becomes a SELL signal."""
    from scripts.emergency_flatten import plan_flatten

    signals, skipped = plan_flatten([_pos("AAPL", 100)])

    assert len(signals) == 1
    assert len(skipped) == 0
    sig = signals[0]
    assert sig.symbol == "AAPL"
    assert sig.action == OrderAction.SELL
    assert sig.quantity == 100
    assert sig.order_type == OrderType.MARKET


def test_plan_flatten_returns_buy_for_short_position():
    """A short (negative quantity) equity position becomes a BUY signal."""
    from scripts.emergency_flatten import plan_flatten

    signals, skipped = plan_flatten([_pos("TSLA", -50)])

    assert len(signals) == 1
    sig = signals[0]
    assert sig.action == OrderAction.BUY
    assert sig.quantity == 50  # abs value


def test_plan_flatten_skips_non_equity():
    """Futures, forex, and options positions must be skipped with a reason."""
    from scripts.emergency_flatten import plan_flatten

    positions = [
        _pos("AAPL", 100, asset_class="STK"),
        _pos("ES", 2, asset_class="FUT"),
        _pos("EURUSD", 10000, asset_class="FOREX"),
        _pos("AAPL230120C00150000", 1, asset_class="OPT"),
    ]
    signals, skipped = plan_flatten(positions)

    assert len(signals) == 1
    assert signals[0].symbol == "AAPL"

    skipped_symbols = {s[0] for s in skipped}
    assert "ES" in skipped_symbols
    assert "EURUSD" in skipped_symbols
    assert "AAPL230120C00150000" in skipped_symbols


def test_plan_flatten_respects_custom_allowed_classes():
    """Passing a custom allowed_asset_classes set overrides the STK-only default."""
    from scripts.emergency_flatten import plan_flatten

    positions = [
        _pos("AAPL", 100, asset_class="STK"),
        _pos("GLD", 10, asset_class="ETF"),
    ]
    signals, skipped = plan_flatten(positions, allowed_asset_classes={"STK", "ETF"})

    assert len(signals) == 2
    assert len(skipped) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

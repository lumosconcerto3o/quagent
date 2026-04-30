"""
Tests for risk engine.
"""

import pytest
from app.config import QuAgentConfig
from app.kill_switch import KillSwitch
from app.risk import RiskEngine
from app.schemas import Signal, OrderAction, OrderType


@pytest.fixture
def config():
    """Create a test config."""
    return QuAgentConfig(
        trading_mode='paper',
        account={
            'max_position_size': 1000,
            'buying_power_limit': 50000,
            'max_daily_loss_pct': 2.0,
            'max_order_notional_usd': 50000,  # high cap so existing tests are not affected
        }
    )


@pytest.fixture
def risk_engine(config):
    """Create a risk engine."""
    return RiskEngine(config)


def test_position_size_check(risk_engine):
    """Test position size limit check."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=500,  # Within limit of 1000
    )
    
    result = risk_engine.check_signal(
        signal,
        current_buying_power=50000,
        current_positions={},
        portfolio_value=100000,
    )
    
    assert 'position_size' in result.checks
    assert result.checks['position_size']['passed'] == True


def test_position_size_violation(risk_engine):
    """Test position size limit violation."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=2000,  # Exceeds limit of 1000
    )
    
    result = risk_engine.check_signal(
        signal,
        current_buying_power=50000,
        current_positions={},
        portfolio_value=100000,
    )
    
    assert result.passed == False
    assert any("exceeds max" in str(f) for f in result.failures)


def test_buying_power_check(risk_engine):
    """Test buying power check."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=100,
        limit_price=150.00,
    )
    
    # Has sufficient buying power
    result = risk_engine.check_signal(
        signal,
        current_buying_power=50000,
        current_positions={},
        portfolio_value=100000,
    )
    
    assert result.checks['buying_power']['passed'] == True


def test_insufficient_buying_power(risk_engine):
    """Test insufficient buying power."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=100,
        limit_price=150.00,
    )
    
    # Insufficient buying power
    result = risk_engine.check_signal(
        signal,
        current_buying_power=1000,  # Too low
        current_positions={},
        portfolio_value=100000,
    )
    
    assert result.passed == False


def test_sell_skip_buying_power(risk_engine):
    """Test that SELL orders skip buying power check."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.SELL,
        quantity=100,
    )
    
    result = risk_engine.check_signal(
        signal,
        current_buying_power=0,  # No buying power
        current_positions={'AAPL': 100},
        portfolio_value=100000,
    )
    
    # Should pass because SELL doesn't need buying power
    assert result.checks['buying_power']['skipped'] == 'not a buy order'


def test_existing_position_warning(risk_engine):
    """Test warning for large existing positions."""
    signal = Signal(
        symbol="AAPL",
        action=OrderAction.BUY,
        quantity=100,
        limit_price=10.0,  # notional=$1,000 — well under the $50,000 test cap
    )

    result = risk_engine.check_signal(
        signal,
        current_buying_power=50000,
        current_positions={'AAPL': 600},  # Already 60% of max (500 threshold)
        portfolio_value=100000,
    )

    # Should pass but have a warning
    assert result.passed == True
    assert len(result.warnings) > 0


def test_record_trade(risk_engine):
    """Test recording a trade."""
    risk_engine.record_trade("AAPL", 100, 150.00, "BUY")
    
    assert len(risk_engine.trades_today) == 1
    assert risk_engine.daily_order_count == 1


def test_reset_daily_tracking(risk_engine):
    """Test resetting daily tracking."""
    risk_engine.record_trade("AAPL", 100, 150.00, "BUY")
    risk_engine.daily_realized_loss = 1.5
    
    risk_engine.reset_daily_tracking()
    
    assert len(risk_engine.trades_today) == 0
    assert risk_engine.daily_order_count == 0
    assert risk_engine.daily_realized_loss == 0.0


def test_risk_check_blocked_when_kill_switch_active():
    """Kill switch must cause check_signal to reject immediately."""
    config = QuAgentConfig(
        trading_mode='paper',
        account={
            'max_position_size': 1000,
            'buying_power_limit': 50000,
            'max_daily_loss_pct': 2.0,
            'max_order_notional_usd': 50000,
        }
    )
    ks = KillSwitch()
    ks.trigger("Emergency stop", "test")
    engine = RiskEngine(config, kill_switch=ks)

    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100, limit_price=150.0)
    result = engine.check_signal(signal, 50000, {}, 100000)

    assert result.passed is False
    assert any("kill switch" in f.lower() for f in result.failures)


def test_notional_usd_cap_enforced():
    """Orders whose notional exceeds max_order_notional_usd must be rejected."""
    config = QuAgentConfig(
        trading_mode='paper',
        account={
            'max_position_size': 10000,
            'buying_power_limit': 500000,
            'max_daily_loss_pct': 2.0,
            'max_order_notional_usd': 5000,
        }
    )
    engine = RiskEngine(config)

    # 100 shares @ $100 = $10,000 notional > $5,000 cap
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=100, limit_price=100.0)
    result = engine.check_signal(signal, 500000, {}, 1000000)

    assert result.passed is False
    assert any("notional" in f.lower() for f in result.failures)


def test_market_order_without_price_rejected():
    """A BUY MARKET order with no limit_price must be rejected (cannot verify notional)."""
    config = QuAgentConfig(
        trading_mode='paper',
        account={
            'max_position_size': 10000,
            'buying_power_limit': 500000,
            'max_daily_loss_pct': 2.0,
            'max_order_notional_usd': 5000,
        }
    )
    engine = RiskEngine(config)

    # MARKET order, no limit_price — unsafe, cannot verify notional
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=10)
    result = engine.check_signal(signal, 500000, {}, 1000000)

    assert result.passed is False
    assert any("limit_price" in f.lower() or "no price" in f.lower() or "buy order" in f.lower()
               for f in result.failures)


def test_asset_class_restriction():
    """Signals with a disallowed asset class must be rejected."""
    config = QuAgentConfig(
        trading_mode='paper',
        account={
            'max_position_size': 10000,
            'buying_power_limit': 500000,
            'max_daily_loss_pct': 2.0,
            'max_order_notional_usd': 50000,
            'allowed_asset_classes': ['STK'],
        }
    )
    engine = RiskEngine(config)

    # STK should pass the asset class check
    stk_signal = Signal(
        symbol="AAPL", action=OrderAction.BUY, quantity=10,
        limit_price=150.0, asset_class="STK",
    )
    result = engine.check_signal(stk_signal, 500000, {}, 1000000)
    assert result.checks['asset_class']['passed'] is True

    # OPT (option) must fail
    opt_signal = Signal(
        symbol="AAPL230120C00150000", action=OrderAction.BUY, quantity=1,
        limit_price=5.0, asset_class="OPT",
    )
    result = engine.check_signal(opt_signal, 500000, {}, 1000000)
    assert result.passed is False
    assert any("asset class" in f.lower() for f in result.failures)


def test_stop_loss_required_when_configured():
    """When require_stop_loss=True, signals without stop_loss must be rejected."""
    config = QuAgentConfig(
        trading_mode='paper',
        account={
            'max_position_size': 10000,
            'buying_power_limit': 500000,
            'max_daily_loss_pct': 2.0,
            'max_order_notional_usd': 50000,
            'require_stop_loss': True,
        }
    )
    engine = RiskEngine(config)

    # Signal without stop_loss
    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=10, limit_price=150.0)
    result = engine.check_signal(signal, 500000, {}, 1000000)
    assert result.passed is False
    assert any("stop loss" in f.lower() for f in result.failures)

    # Signal WITH stop_loss should pass that check
    signal_with_sl = Signal(
        symbol="AAPL", action=OrderAction.BUY, quantity=10,
        limit_price=150.0, stop_loss=140.0,
    )
    result2 = engine.check_signal(signal_with_sl, 500000, {}, 1000000)
    assert result2.checks['stop_loss']['passed'] is True


def test_market_sanity_fails_on_missing_price():
    """Market sanity check must record failure when a BUY order has no price."""
    config = QuAgentConfig(
        trading_mode='paper',
        account={'max_order_notional_usd': 50000}
    )
    engine = RiskEngine(config)

    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=10)  # no limit_price
    result = engine.check_signal(signal, 500000, {}, 1000000)

    assert result.checks['market_sanity']['passed'] is False


def test_market_sanity_fails_on_zero_or_negative_price():
    """Market sanity must reject a BUY order with limit_price <= 0."""
    config = QuAgentConfig(
        trading_mode='paper',
        account={'max_order_notional_usd': 50000}
    )
    engine = RiskEngine(config)

    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=10, limit_price=0.0)
    result = engine.check_signal(signal, 500000, {}, 1000000)

    assert result.passed is False
    assert result.checks['market_sanity']['passed'] is False


def test_market_sanity_fails_on_incomplete_quote_if_provided():
    """When a MarketQuote with quote_quality='incomplete' is passed, reject."""
    from app.schemas import MarketQuote
    config = QuAgentConfig(
        trading_mode='paper',
        account={'max_order_notional_usd': 50000}
    )
    engine = RiskEngine(config)

    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=10, limit_price=150.0)
    bad_quote = MarketQuote(symbol="AAPL", price=150.0, quote_quality="incomplete")

    result = engine.check_signal(signal, 500000, {}, 1000000, market_data=bad_quote)

    assert result.passed is False
    assert result.checks['market_sanity']['passed'] is False


def test_daily_loss_limit_actually_rejects(risk_engine):
    """After recording a loss that exceeds max_daily_loss_pct, new signals are rejected."""
    # The fixture's max_daily_loss_pct=2.0; a loss of 5.0 exceeds it
    risk_engine.record_trade("TSLA", 10, 200.0, "SELL", realized_pnl=-5.0)
    assert risk_engine.daily_realized_loss == 5.0

    signal = Signal(symbol="AAPL", action=OrderAction.BUY, quantity=10, limit_price=50.0)
    result = risk_engine.check_signal(signal, 50000, {}, 100000)

    assert result.passed is False
    assert any("daily loss" in f.lower() for f in result.failures)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

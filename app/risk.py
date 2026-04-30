"""
Risk management and deterministic checks.
Safety first - all checks must be explicit YES/NO.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime

from app.logger import get_logger
from app.schemas import Signal, RiskCheckResult, OrderAction, MarketQuote
from app.config import QuAgentConfig

logger = get_logger(__name__)


class RiskEngine:
    """
    Deterministic risk checking engine.
    All checks must be explicit and fail-closed.
    """

    def __init__(self, config: QuAgentConfig, kill_switch=None):
        """
        Initialize risk engine.

        Args:
            config: QuAgent configuration
            kill_switch: Optional KillSwitch instance; if provided and triggered,
                         all signals are rejected before any other check.
        """
        self.config = config
        self.account_config = config.account
        self.kill_switch = kill_switch
        self.daily_realized_loss = 0.0
        self.daily_order_count = 0
        self.trades_today: List[Dict[str, Any]] = []

    def check_signal(
        self,
        signal: Signal,
        current_buying_power: float,
        current_positions: Dict[str, float],
        portfolio_value: float,
        market_data: Optional[MarketQuote] = None,
    ) -> RiskCheckResult:
        """
        Run comprehensive risk checks on a signal.

        Args:
            signal: Trading signal
            current_buying_power: Available buying power
            current_positions: Current positions {symbol: quantity}
            portfolio_value: Total portfolio value
            market_data: Optional MarketQuote for enhanced sanity checks

        Returns:
            RiskCheckResult with detailed check information
        """
        result = RiskCheckResult(passed=True)

        try:
            # Check 0: Kill switch — fail immediately, skip remaining checks
            if self.kill_switch and self.kill_switch.is_triggered():
                reason = self.kill_switch.status.reason or "unknown"
                result.failures.append(f"Kill switch active: {reason}")
                result.passed = False
                logger.error(f"Risk check blocked by kill switch: {reason}")
                return result

            # Check 1: Asset class restriction
            self._check_asset_class(signal, result)

            # Check 2: Position size limit (shares)
            self._check_position_size(signal, result)

            # Check 3: Notional USD cap — also rejects BUY orders with no price
            self._check_notional_usd(signal, result)

            # Check 4: Buying power (uses limit_price; skipped if no price)
            self._check_buying_power(signal, current_buying_power, result)

            # Check 5: Existing position limits
            self._check_existing_position(signal, current_positions, result)

            # Check 6: Daily loss limit
            self._check_daily_loss_limit(result)

            # Check 7: Stop loss requirement
            self._check_stop_loss(signal, result)

            # Check 8: Market sanity (price validity, quote quality, staleness)
            self._check_market_sanity(signal, result, market_data)

            if result.failures:
                result.passed = False
                logger.warning(f"Risk check FAILED: {result.failures}")
            else:
                logger.info(f"Risk check PASSED for {signal.symbol} {signal.action}")

            return result

        except Exception as e:
            logger.error(f"Unexpected error in risk check: {e}")
            result.passed = False
            result.failures.append(f"Exception: {str(e)}")
            return result

    # ------------------------------------------------------------------ #
    # Individual checks                                                    #
    # ------------------------------------------------------------------ #

    def _check_asset_class(self, signal: Signal, result: RiskCheckResult) -> None:
        """Reject asset classes not on the allowed list."""
        allowed = self.account_config.allowed_asset_classes
        asset_class = signal.asset_class
        passed = asset_class in allowed

        if not passed:
            result.failures.append(
                f"Asset class '{asset_class}' not in allowed list {allowed}"
            )

        result.checks['asset_class'] = {
            'asset_class': asset_class,
            'allowed': allowed,
            'passed': passed,
        }

    def _check_position_size(self, signal: Signal, result: RiskCheckResult) -> None:
        """Check that order quantity doesn't exceed max position size (shares)."""
        max_size = self.account_config.max_position_size
        passed = signal.quantity <= max_size

        if not passed:
            result.failures.append(
                f"Position size {signal.quantity} exceeds max {max_size} shares"
            )

        result.checks['position_size'] = {
            'requested': signal.quantity,
            'max_allowed': max_size,
            'passed': passed,
        }

    def _check_notional_usd(self, signal: Signal, result: RiskCheckResult) -> None:
        """
        Check that order notional value does not exceed max_order_notional_usd.

        BUY orders with no limit_price are rejected: without a known price the
        notional cannot be verified, which is unsafe.
        SELL orders skip this check (no capital at risk from a sell).
        """
        if signal.action != OrderAction.BUY:
            result.checks['notional_usd'] = {'skipped': 'not a buy order'}
            return

        max_notional = self.account_config.max_order_notional_usd

        if signal.limit_price is None:
            result.failures.append(
                "BUY order has no limit_price; cannot verify notional value. "
                "Provide limit_price for all BUY orders."
            )
            result.checks['notional_usd'] = {
                'passed': False,
                'reason': 'no limit_price for BUY order',
            }
            return

        notional = signal.quantity * signal.limit_price
        passed = notional <= max_notional

        if not passed:
            result.failures.append(
                f"Order notional ${notional:,.2f} exceeds cap ${max_notional:,.2f}"
            )

        result.checks['notional_usd'] = {
            'notional': notional,
            'max_notional': max_notional,
            'passed': passed,
        }

    def _check_buying_power(
        self, signal: Signal, buying_power: float, result: RiskCheckResult
    ) -> None:
        """
        Check that we have enough buying power for the order.

        Skips if there is no limit_price (the notional check already rejects
        priceless BUY orders, so there is nothing to verify here).
        """
        if signal.action != OrderAction.BUY:
            result.checks['buying_power'] = {'skipped': 'not a buy order'}
            return

        if signal.limit_price is None:
            result.checks['buying_power'] = {
                'skipped': 'no limit_price; handled by notional check'
            }
            return

        required = signal.quantity * signal.limit_price * 1.01  # +1% buffer
        passed = buying_power >= required

        if not passed:
            result.failures.append(
                f"Insufficient buying power: need ${required:,.2f}, "
                f"have ${buying_power:,.2f}"
            )

        result.checks['buying_power'] = {
            'required': required,
            'available': buying_power,
            'passed': passed,
        }

    def _check_existing_position(
        self,
        signal: Signal,
        current_positions: Dict[str, float],
        result: RiskCheckResult,
    ) -> None:
        """Check position stacking rules."""
        current_qty = current_positions.get(signal.symbol, 0.0)
        max_size = self.account_config.max_position_size

        if current_qty >= 0.5 * max_size:
            result.warnings.append(
                f"Already holding {current_qty} shares of {signal.symbol}, "
                f"adding {signal.quantity} more"
            )

        result.checks['existing_position'] = {
            'current_qty': current_qty,
            'additional_qty': signal.quantity,
            'total_after': current_qty + signal.quantity,
        }

    def _check_daily_loss_limit(self, result: RiskCheckResult) -> None:
        """Check daily loss limit."""
        max_loss = self.account_config.max_daily_loss_pct
        passed = self.daily_realized_loss < max_loss

        if not passed:
            result.failures.append(
                f"Daily loss limit reached: {self.daily_realized_loss:.4f} "
                f"(max: {max_loss:.4f})"
            )

        result.checks['daily_loss_limit'] = {
            'current_loss': self.daily_realized_loss,
            'max_allowed': max_loss,
            'passed': passed,
        }

    def _check_stop_loss(self, signal: Signal, result: RiskCheckResult) -> None:
        """
        Reject signals that are missing a stop loss when require_stop_loss=True.
        Skipped entirely when require_stop_loss=False.
        """
        if not self.account_config.require_stop_loss:
            result.checks['stop_loss'] = {'skipped': 'not required by config'}
            return

        if signal.stop_loss is None:
            result.failures.append(
                "Stop loss is required (require_stop_loss=true) but not provided"
            )
            result.checks['stop_loss'] = {
                'passed': False,
                'reason': 'stop_loss not provided',
            }
            return

        if signal.stop_loss <= 0:
            result.failures.append(
                f"stop_loss {signal.stop_loss} must be > 0"
            )
            result.checks['stop_loss'] = {
                'stop_loss': signal.stop_loss,
                'passed': False,
                'reason': 'stop_loss <= 0',
            }
            return

        result.checks['stop_loss'] = {
            'stop_loss': signal.stop_loss,
            'passed': True,
        }

    def _check_market_sanity(
        self,
        signal: Signal,
        result: RiskCheckResult,
        market_data: Optional[MarketQuote] = None,
    ) -> None:
        """
        Validate price and, when market_data is provided, quote quality / staleness.

        BUY orders: limit_price must be present and strictly positive.
        SELL orders: no price requirement from this check alone.
        market_data (MarketQuote): if provided, price, is_stale, and quote_quality
            are also validated independently of the signal's limit_price.
        """
        # BUY orders require a positive limit_price
        if signal.action == OrderAction.BUY:
            if signal.limit_price is None:
                # Notional check already added a failure; record without duplicating
                result.checks['market_sanity'] = {
                    'symbol': signal.symbol,
                    'passed': False,
                    'reason': 'no price for BUY order',
                }
                return

            if signal.limit_price <= 0:
                result.failures.append(
                    f"limit_price {signal.limit_price} must be > 0 for {signal.symbol}"
                )
                result.checks['market_sanity'] = {
                    'symbol': signal.symbol,
                    'price': signal.limit_price,
                    'passed': False,
                    'reason': 'limit_price must be positive',
                }
                return

        # Enhanced validation when a MarketQuote is explicitly supplied
        if market_data is not None:
            if market_data.price <= 0:
                result.failures.append(
                    f"Market quote price {market_data.price} must be > 0 "
                    f"for {signal.symbol}"
                )
                result.checks['market_sanity'] = {
                    'symbol': signal.symbol,
                    'price': market_data.price,
                    'passed': False,
                    'reason': 'quote price <= 0',
                }
                return

            if market_data.is_stale:
                result.failures.append(
                    f"Market data for {signal.symbol} is stale"
                )
                result.checks['market_sanity'] = {
                    'symbol': signal.symbol,
                    'passed': False,
                    'reason': 'stale market data',
                }
                return

            if market_data.quote_quality != 'complete':
                result.failures.append(
                    f"Market quote quality for {signal.symbol} is "
                    f"'{market_data.quote_quality}', expected 'complete'"
                )
                result.checks['market_sanity'] = {
                    'symbol': signal.symbol,
                    'quote_quality': market_data.quote_quality,
                    'passed': False,
                    'reason': 'incomplete quote quality',
                }
                return

        result.checks['market_sanity'] = {
            'symbol': signal.symbol,
            'has_price': True,
            'passed': True,
        }

    # ------------------------------------------------------------------ #
    # Daily tracking                                                       #
    # ------------------------------------------------------------------ #

    def record_trade(
        self,
        symbol: str,
        quantity: float,
        price: float,
        action: str,
        realized_pnl: float = 0.0,
    ) -> None:
        """
        Record a completed trade for daily tracking.

        Args:
            symbol: Ticker symbol
            quantity: Number of shares
            price: Execution price
            action: BUY or SELL
            realized_pnl: Realized P&L for this trade (negative = loss).
                          When negative, daily_realized_loss is incremented by
                          the absolute loss amount.
        """
        self.trades_today.append({
            'symbol': symbol,
            'quantity': quantity,
            'price': price,
            'action': action,
            'realized_pnl': realized_pnl,
            'timestamp': datetime.utcnow(),
        })
        self.daily_order_count += 1

        if realized_pnl < 0:
            self.daily_realized_loss += abs(realized_pnl)

        logger.info(
            f"Recorded trade: {action} {quantity} x {symbol} @ ${price:.2f} "
            f"(pnl={realized_pnl:+.4f})"
        )

    def reset_daily_tracking(self) -> None:
        """Reset daily tracking (call at market close or new day)."""
        self.daily_realized_loss = 0.0
        self.daily_order_count = 0
        self.trades_today = []
        logger.info("Daily tracking reset")

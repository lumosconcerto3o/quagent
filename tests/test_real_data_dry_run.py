"""
Tests for the real_data_dry_run pipeline.
All tests are offline — no real IBKR connection required.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from app.config import QuAgentConfig
from scripts.real_data_dry_run import run_dry_run


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _paper_config() -> QuAgentConfig:
    """Minimal paper config with permissive risk limits."""
    return QuAgentConfig(
        trading_mode="paper",
        allow_live=False,
    )


def _live_config() -> QuAgentConfig:
    """Live config (allow_live=True to pass the Pydantic validator)."""
    return QuAgentConfig(trading_mode="live", allow_live=True)


def _make_client() -> MagicMock:
    """
    Mock IBKRClient whose submit_order raises NotImplementedError,
    matching the real IBKRClient behaviour.
    """
    client = MagicMock()
    client.is_connected.return_value = True
    client.submit_order = AsyncMock(side_effect=NotImplementedError("disabled"))
    return client


def _make_account_mgr(
    net_liq: float = 1_000_000.0,
    avail_funds: float = 500_000.0,
    positions: list = None,
) -> MagicMock:
    mgr = MagicMock()
    mgr.get_account_summary = AsyncMock(return_value={
        "account_id": "DU123456",
        "NetLiquidation": net_liq,
        "AvailableFunds": avail_funds,
    })
    mgr.get_positions = AsyncMock(return_value=positions or [])
    return mgr


def _make_market_mgr(
    quote_quality: str = "complete",
    price: float = 555.0,
    is_stale: bool = False,
) -> MagicMock:
    mgr = MagicMock()
    mgr.get_stock_quote = AsyncMock(return_value={
        "symbol": "SPY",
        "price": price,
        "bid": price - 0.01 if price > 0 else None,
        "ask": price + 0.01 if price > 0 else None,
        "last": price if price > 0 else None,
        "close": price - 0.50 if price > 0 else None,
        "timestamp": "2026-04-30T10:00:00+00:00",
        "quote_quality": quote_quality,
        "is_stale": is_stale,
        "data_type": "delayed",
        "ibkr_error": None,
    })
    return mgr


# ------------------------------------------------------------------ #
# Safety guard: live config refused                                   #
# ------------------------------------------------------------------ #

async def test_run_dry_run_refuses_live_config():
    """run_dry_run must raise ValueError when trading_mode is 'live'."""
    config = _live_config()

    with pytest.raises(ValueError, match="live"):
        await run_dry_run(
            config,
            MagicMock(),   # client — never reached
            MagicMock(),   # account_mgr — never reached
            MagicMock(),   # market_mgr — never reached
            "SPY",
        )


# ------------------------------------------------------------------ #
# Incomplete quote → pipeline aborts before order creation            #
# ------------------------------------------------------------------ #

async def test_run_dry_run_aborts_on_incomplete_quote():
    """Pipeline must abort and return status='aborted' when quote is incomplete."""
    result = await run_dry_run(
        _paper_config(),
        _make_client(),
        _make_account_mgr(),
        _make_market_mgr(quote_quality="incomplete", price=0.0, is_stale=True),
        "SPY",
    )

    assert result["status"] == "aborted"
    assert result["reason"] == "incomplete_quote"


async def test_run_dry_run_aborts_on_stale_incomplete_quote():
    """A stale incomplete quote must also trigger an abort."""
    result = await run_dry_run(
        _paper_config(),
        _make_client(),
        _make_account_mgr(),
        _make_market_mgr(quote_quality="incomplete", price=0.0, is_stale=True),
        "AAPL",
    )

    assert result["status"] == "aborted"
    assert "quote" in result


# ------------------------------------------------------------------ #
# dry_run=True enforced                                               #
# ------------------------------------------------------------------ #

async def test_run_dry_run_enforces_dry_run_true():
    """A successful pipeline must report dry_run_enforced=True."""
    result = await run_dry_run(
        _paper_config(),
        _make_client(),
        _make_account_mgr(),
        _make_market_mgr(),
        "SPY",
    )

    assert result["status"] == "success"
    assert result["dry_run_enforced"] is True


# ------------------------------------------------------------------ #
# No broker submission                                                #
# ------------------------------------------------------------------ #

async def test_run_dry_run_broker_order_id_is_none():
    """
    broker_order_id must be None — no order was submitted to the broker.
    submit_order is called exactly once (the safety guard check),
    never for real order execution.
    """
    client = _make_client()

    result = await run_dry_run(
        _paper_config(),
        client,
        _make_account_mgr(),
        _make_market_mgr(),
        "SPY",
    )

    assert result["status"] == "success"
    assert result["broker_order_id"] is None

    # The guard calls submit_order once with dummy args to verify it's disabled.
    # The execution engine (dry_run=True) never calls it again for real execution.
    client.submit_order.assert_called_once()


# ------------------------------------------------------------------ #
# Risk failure path                                                   #
# ------------------------------------------------------------------ #

async def test_run_dry_run_reports_risk_failure():
    """
    When risk checks fail (e.g. notional too high), the pipeline must
    return status='risk_failed' and list the failures — no order created.
    """
    from app.config import AccountConfig

    # Force a config where the notional cap is $1 so any real price fails
    config = QuAgentConfig(
        trading_mode="paper",
        allow_live=False,
        account=AccountConfig(max_order_notional_usd=1.0),
    )

    result = await run_dry_run(
        config,
        _make_client(),
        _make_account_mgr(),
        _make_market_mgr(price=555.0),
        "SPY",
    )

    assert result["status"] == "risk_failed"
    assert result["risk_passed"] is False
    assert len(result["risk_failures"]) > 0
    assert result["broker_order_id"] is None


# ------------------------------------------------------------------ #
# Full success path sanity check                                      #
# ------------------------------------------------------------------ #

async def test_run_dry_run_success_fields_present():
    """A successful dry-run result must contain all expected keys."""
    result = await run_dry_run(
        _paper_config(),
        _make_client(),
        _make_account_mgr(),
        _make_market_mgr(),
        "SPY",
    )

    assert result["status"] == "success"
    for key in (
        "symbol", "quote", "summary", "signal",
        "risk_passed", "order_id", "order_status",
        "broker_submission", "broker_order_id",
        "execution_mode", "dry_run_enforced", "execution_success",
    ):
        assert key in result, f"Missing key: {key}"


# ------------------------------------------------------------------ #
# Semantic clarity: local OMS status vs broker status                 #
# ------------------------------------------------------------------ #

async def test_run_dry_run_execution_mode_is_dry_run():
    """result['execution_mode'] must be 'DRY_RUN' — not 'LIVE' or absent."""
    result = await run_dry_run(
        _paper_config(),
        _make_client(),
        _make_account_mgr(),
        _make_market_mgr(),
        "SPY",
    )

    assert result["execution_mode"] == "DRY_RUN"


async def test_run_dry_run_broker_submission_is_false():
    """result['broker_submission'] must be False in dry-run mode."""
    result = await run_dry_run(
        _paper_config(),
        _make_client(),
        _make_account_mgr(),
        _make_market_mgr(),
        "SPY",
    )

    assert result["broker_submission"] is False


async def test_run_dry_run_local_oms_status_is_submitted():
    """
    The local OMS status is 'SUBMITTED' — this records the simulated
    execution in the local state machine only, not a broker confirmation.
    broker_submission=False and broker_order_id=None confirm no real submission.
    """
    result = await run_dry_run(
        _paper_config(),
        _make_client(),
        _make_account_mgr(),
        _make_market_mgr(),
        "SPY",
    )

    assert result["order_status"] == "SUBMITTED"   # local OMS tracking state
    assert result["broker_submission"] is False    # no broker call was made
    assert result["broker_order_id"] is None       # no broker order ID assigned

    assert result["symbol"] == "SPY"
    assert result["risk_passed"] is True
    assert result["execution_success"] is True


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v"])

"""
Tests for the QuAgent local deployment healthcheck.

All tests are offline — no real IBKR connection required.
Uses mocks/fakes for connection-dependent checks.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from scripts.quagent_healthcheck import (
    HealthcheckReport,
    check_project_root,
    check_config_exists,
    check_config_loads,
    check_mode_is_paper,
    check_read_only_api,
    check_live_trading_disabled,
    check_live_yaml,
    check_forbidden_broker_calls,
    check_required_docs,
    check_tws_port_reachable,
    run_offline_checks,
    run_online_checks,
)

# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #


def _has_fail(report: HealthcheckReport) -> bool:
    return any(c.status == "FAIL" for c in report.checks)


def _has_warn(report: HealthcheckReport) -> bool:
    return any(c.status == "WARN" for c in report.checks)


def _find_check(report: HealthcheckReport, name: str):
    """Find a check by name, or return None."""
    for c in report.checks:
        if c.name == name:
            return c
    return None


# ------------------------------------------------------------------ #
# 1. Healthcheck passes safe paper config                             #
# ------------------------------------------------------------------ #


def test_healthcheck_passes_safe_paper_config():
    """run_offline_checks with configs/paper.yaml should PASS all checks."""
    report = run_offline_checks("configs/paper.yaml")

    assert not _has_fail(
        report
    ), f"Unexpected FAIL: {[c for c in report.checks if c.status == 'FAIL']}"
    assert report.overall_pass

    # Verify specific checks
    assert _find_check(report, "Config mode is paper").status == "PASS"
    assert _find_check(report, "Read-only API required").status == "PASS"
    assert _find_check(report, "Live trading disabled").status == "PASS"
    assert _find_check(report, "Forbidden broker calls absent").status == "PASS"
    assert _find_check(report, "Required docs exist").status == "PASS"


# ------------------------------------------------------------------ #
# 2. Healthcheck fails live config                                    #
# ------------------------------------------------------------------ #


def test_healthcheck_fails_live_config(tmp_path):
    """A config with trading_mode=live must FAIL the mode check."""
    config_file = tmp_path / "bad_live.yaml"
    config_file.write_text(
        "trading_mode: live\nallow_live: true\nibkr:\n  read_only_api: true\n",
        encoding="utf-8",
    )

    report = HealthcheckReport()
    config_dict = {
        "trading_mode": "live",
        "allow_live": True,
        "ibkr": {"read_only_api": True},
    }
    check_mode_is_paper(report, config_dict)

    assert _has_fail(report)
    check = _find_check(report, "Config mode is paper")
    assert check.status == "FAIL"
    assert "live" in check.detail


def test_healthcheck_fails_allow_live_true(tmp_path):
    """A config with allow_live=true must FAIL the live trading disabled check."""
    report = HealthcheckReport()
    config_dict = {
        "trading_mode": "paper",
        "allow_live": True,
        "ibkr": {"read_only_api": True},
    }
    check_live_trading_disabled(report, config_dict)

    assert _has_fail(report)
    check = _find_check(report, "Live trading disabled")
    assert check.status == "FAIL"


# ------------------------------------------------------------------ #
# 3. Healthcheck fails read_only_api=false                            #
# ------------------------------------------------------------------ #


def test_healthcheck_fails_read_only_api_false():
    """read_only_api=false must FAIL the read-only API check."""
    report = HealthcheckReport()
    config_dict = {
        "trading_mode": "paper",
        "allow_live": False,
        "ibkr": {"read_only_api": False},
    }
    check_read_only_api(report, config_dict)

    assert _has_fail(report)
    check = _find_check(report, "Read-only API required")
    assert check.status == "FAIL"
    assert "False" in check.detail


def test_healthcheck_fails_read_only_api_missing():
    """Missing read_only_api must FAIL the read-only API check."""
    report = HealthcheckReport()
    config_dict = {
        "trading_mode": "paper",
        "allow_live": False,
        "ibkr": {},
    }
    check_read_only_api(report, config_dict)

    assert _has_fail(report)
    check = _find_check(report, "Read-only API required")
    assert check.status == "FAIL"


# ------------------------------------------------------------------ #
# 4. Healthcheck fails if forbidden real broker call is detected       #
# ------------------------------------------------------------------ #


def test_healthcheck_fails_on_forbidden_placeorder(tmp_path, monkeypatch):
    """A source file containing .placeOrder( must FAIL forbidden broker check."""
    # Create a fake app directory with a forbidden call
    fake_app = tmp_path / "app"
    fake_app.mkdir()
    bad_file = fake_app / "bad_module.py"
    bad_file.write_text(
        "async def do_it(ib):\n    ib.placeOrder(contract, order)\n",
        encoding="utf-8",
    )

    # Monkeypatch the scan dirs and get_relative_path to use tmp_path
    import scripts.quagent_healthcheck as hc

    monkeypatch.setattr(hc, "_SCAN_DIRS", ["app"])
    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    report = HealthcheckReport()
    check_forbidden_broker_calls(report)

    assert _has_fail(report)
    check = _find_check(report, "Forbidden broker calls absent")
    assert check.status == "FAIL"
    assert "placeOrder" in check.detail


def test_healthcheck_fails_on_forbidden_cancelorder(tmp_path, monkeypatch):
    """A source file containing .cancelOrder( must FAIL forbidden broker check."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()
    bad_file = fake_app / "bad_module.py"
    bad_file.write_text(
        "async def cancel(ib):\n    ib.cancelOrder(order_id)\n",
        encoding="utf-8",
    )

    import scripts.quagent_healthcheck as hc

    monkeypatch.setattr(hc, "_SCAN_DIRS", ["app"])
    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    report = HealthcheckReport()
    check_forbidden_broker_calls(report)

    assert _has_fail(report)
    check = _find_check(report, "Forbidden broker calls absent")
    assert check.status == "FAIL"
    assert "cancelOrder" in check.detail


def test_healthcheck_fails_on_forbidden_reqglobalcancel(tmp_path, monkeypatch):
    """A source file containing .reqGlobalCancel( must FAIL forbidden broker check."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()
    bad_file = fake_app / "bad_module.py"
    bad_file.write_text(
        "async def cancel_all(ib):\n    ib.reqGlobalCancel()\n",
        encoding="utf-8",
    )

    import scripts.quagent_healthcheck as hc

    monkeypatch.setattr(hc, "_SCAN_DIRS", ["app"])
    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    report = HealthcheckReport()
    check_forbidden_broker_calls(report)

    assert _has_fail(report)
    check = _find_check(report, "Forbidden broker calls absent")
    assert check.status == "FAIL"
    assert "reqGlobalCancel" in check.detail


def test_healthcheck_passes_when_forbidden_calls_in_comments(tmp_path, monkeypatch):
    """Forbidden patterns in comment lines should NOT trigger a FAIL."""
    fake_app = tmp_path / "app"
    fake_app.mkdir()
    ok_file = fake_app / "ok_module.py"
    ok_file.write_text(
        "# This file does not call ib.placeOrder()\n" "def hello():\n    pass\n",
        encoding="utf-8",
    )

    import scripts.quagent_healthcheck as hc

    monkeypatch.setattr(hc, "_SCAN_DIRS", ["app"])
    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    report = HealthcheckReport()
    check_forbidden_broker_calls(report)

    assert not _has_fail(report)
    check = _find_check(report, "Forbidden broker calls absent")
    assert check.status == "PASS"


# ------------------------------------------------------------------ #
# 5. Healthcheck warns but does not fail on incomplete quote           #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_healthcheck_warns_on_incomplete_quote(monkeypatch):
    """An incomplete quote should produce a WARN, not a FAIL, in connect mode."""
    mock_client = MagicMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.disconnect = AsyncMock()
    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_client.get_ib.return_value = mock_ib

    mock_market_mgr = MagicMock()
    mock_market_mgr.get_stock_quote = AsyncMock(
        return_value={
            "symbol": "SPY",
            "price": None,
            "bid": None,
            "ask": None,
            "last": None,
            "close": None,
            "timestamp": "2026-04-30T10:00:00+00:00",
            "quote_quality": "incomplete",
            "is_stale": True,
            "data_type": "delayed",
            "ibkr_error": None,
        }
    )

    with (
        patch("app.ibkr_client.IBKRClient", return_value=mock_client),
        patch("app.market_data.MarketDataManager", return_value=mock_market_mgr),
    ):
        from scripts.quagent_healthcheck import check_quote

        report = HealthcheckReport()
        await check_quote(
            report,
            "127.0.0.1",
            7497,
            1,
            True,
            "SPY",
            "delayed",
            300,
        )

    quote_check = _find_check(report, "Quote (SPY)")
    assert quote_check is not None
    assert quote_check.status == "WARN"
    assert not _has_fail(report)


# ------------------------------------------------------------------ #
# 6. Healthcheck checks required docs                                 #
# ------------------------------------------------------------------ #


def test_healthcheck_required_docs_pass():
    """check_required_docs should PASS when all docs exist in the real project."""
    report = HealthcheckReport()
    check_required_docs(report)

    check = _find_check(report, "Required docs exist")
    assert check.status == "PASS"


def test_healthcheck_required_docs_fail_when_missing(tmp_path, monkeypatch):
    """check_required_docs should FAIL when a required doc is missing."""
    import scripts.quagent_healthcheck as hc

    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    # Create only some of the required docs
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "AI_CONTEXT.md").write_text("test", encoding="utf-8")
    # Missing: PROJECT_STATUS.md, SAFETY_INVARIANTS.md

    report = HealthcheckReport()
    check_required_docs(report)

    assert _has_fail(report)
    check = _find_check(report, "Required docs exist")
    assert check.status == "FAIL"
    assert "Missing" in check.detail


# ------------------------------------------------------------------ #
# 7. Healthcheck connect path uses readonly=True with mocks            #
# ------------------------------------------------------------------ #


@pytest.mark.asyncio
async def test_healthcheck_connect_uses_readonly_true(monkeypatch):
    """The connect path must create IBKRClient with read_only_api=True."""
    mock_client = MagicMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.disconnect = AsyncMock()
    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_client.get_ib.return_value = mock_ib

    captured_kwargs = {}

    def capture_client(**kwargs):
        captured_kwargs.update(kwargs)
        return mock_client

    with patch("app.ibkr_client.IBKRClient", side_effect=capture_client):
        from scripts.quagent_healthcheck import check_ibkr_connection

        report = HealthcheckReport()
        result = await check_ibkr_connection(
            report,
            "127.0.0.1",
            7497,
            1,
            read_only_api=True,
        )

    assert captured_kwargs.get("read_only_api") is True
    assert result is not None

    account_check = _find_check(report, "Account summary readable")
    assert account_check.status == "PASS"


@pytest.mark.asyncio
async def test_healthcheck_connect_no_open_orders(monkeypatch):
    """The connect path must NOT call openTrades() or reqOpenOrders()."""
    mock_client = MagicMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.disconnect = AsyncMock()
    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_client.get_ib.return_value = mock_ib

    with patch("app.ibkr_client.IBKRClient", return_value=mock_client):
        from scripts.quagent_healthcheck import check_ibkr_connection

        report = HealthcheckReport()
        await check_ibkr_connection(
            report,
            "127.0.0.1",
            7497,
            1,
            read_only_api=True,
        )

    # managedAccounts() was called (read-only) — that's OK
    mock_ib.managedAccounts.assert_called_once()

    # openTrades() must NOT have been called
    mock_ib.openTrades.assert_not_called()

    # reqOpenOrders() must NOT have been called
    mock_ib.reqOpenOrders.assert_not_called()


@pytest.mark.asyncio
async def test_healthcheck_connect_no_submit_or_cancel(monkeypatch):
    """The connect path must NOT call submit_order() or cancel_order()."""
    mock_client = MagicMock()
    mock_client.connect = AsyncMock(return_value=True)
    mock_client.disconnect = AsyncMock()
    mock_ib = MagicMock()
    mock_ib.managedAccounts.return_value = ["DU123456"]
    mock_client.get_ib.return_value = mock_ib

    with patch("app.ibkr_client.IBKRClient", return_value=mock_client):
        from scripts.quagent_healthcheck import check_ibkr_connection

        report = HealthcheckReport()
        await check_ibkr_connection(
            report,
            "127.0.0.1",
            7497,
            1,
            read_only_api=True,
        )

    # submit_order and cancel_order must NOT have been called
    mock_client.submit_order.assert_not_called()
    mock_client.cancel_order.assert_not_called()


# ------------------------------------------------------------------ #
# 8. Script importable                                                #
# ------------------------------------------------------------------ #


def test_script_is_importable():
    """The healthcheck script must be importable without errors."""
    import scripts.quagent_healthcheck

    assert hasattr(scripts.quagent_healthcheck, "run_offline_checks")
    assert hasattr(scripts.quagent_healthcheck, "run_online_checks")
    assert hasattr(scripts.quagent_healthcheck, "HealthcheckReport")
    assert hasattr(scripts.quagent_healthcheck, "main")


# ------------------------------------------------------------------ #
# Additional: HealthcheckReport behavior                              #
# ------------------------------------------------------------------ #


def test_report_overall_pass_when_no_fails():
    """overall_pass should be True when no checks have FAIL status."""
    report = HealthcheckReport()
    report.add("Test 1", "PASS")
    report.add("Test 2", "WARN")
    assert report.overall_pass is True


def test_report_overall_fail_when_any_fail():
    """overall_pass should be False when any check has FAIL status."""
    report = HealthcheckReport()
    report.add("Test 1", "PASS")
    report.add("Test 2", "FAIL", "something broke")
    report.add("Test 3", "WARN")
    assert report.overall_pass is False


def test_report_warn_does_not_cause_fail():
    """Warnings alone should not cause overall_pass to be False."""
    report = HealthcheckReport()
    report.add("Test 1", "PASS")
    report.add("Test 2", "WARN", "just a warning")
    assert report.overall_pass is True


# ------------------------------------------------------------------ #
# Additional: config existence and loading                            #
# ------------------------------------------------------------------ #


def test_check_config_exists_passes_for_paper():
    """configs/paper.yaml should be found."""
    report = HealthcheckReport()
    result = check_config_exists(report, "configs/paper.yaml")

    assert result is not None
    check = _find_check(report, "Config file exists")
    assert check.status == "PASS"


def test_check_config_exists_fails_for_missing(tmp_path, monkeypatch):
    """A missing config file should FAIL."""
    import scripts.quagent_healthcheck as hc

    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    report = HealthcheckReport()
    result = check_config_exists(report, "configs/nonexistent.yaml")

    assert result is None
    check = _find_check(report, "Config file exists")
    assert check.status == "FAIL"


def test_check_config_loads_passes(tmp_path):
    """A valid YAML file should load successfully."""
    config_file = tmp_path / "good.yaml"
    config_file.write_text("trading_mode: paper\n", encoding="utf-8")

    report = HealthcheckReport()
    result = check_config_loads(report, config_file)

    assert result is not None
    assert result["trading_mode"] == "paper"
    check = _find_check(report, "Config loads successfully")
    assert check.status == "PASS"


# ------------------------------------------------------------------ #
# Additional: live.yaml safety check                                 #
# ------------------------------------------------------------------ #


def test_check_live_yaml_passes_with_allow_live_false(tmp_path, monkeypatch):
    """live.yaml with allow_live=false should PASS."""
    import scripts.quagent_healthcheck as hc

    live_path = tmp_path / "configs" / "live.yaml"
    live_path.parent.mkdir(parents=True)
    live_path.write_text(
        "trading_mode: live\nallow_live: false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    report = HealthcheckReport()
    check_live_yaml(report)

    check = _find_check(report, "live.yaml safety")
    assert check.status == "PASS"


def test_check_live_yaml_fails_with_allow_live_true(tmp_path, monkeypatch):
    """live.yaml with allow_live=true should FAIL."""
    import scripts.quagent_healthcheck as hc

    live_path = tmp_path / "configs" / "live.yaml"
    live_path.parent.mkdir(parents=True)
    live_path.write_text(
        "trading_mode: live\nallow_live: true\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    report = HealthcheckReport()
    check_live_yaml(report)

    check = _find_check(report, "live.yaml safety")
    assert check.status == "FAIL"


def test_check_live_yaml_passes_when_missing(tmp_path, monkeypatch):
    """Missing live.yaml should PASS (file not present is OK)."""
    import scripts.quagent_healthcheck as hc

    monkeypatch.setattr(hc, "get_relative_path", lambda p: tmp_path / p)

    report = HealthcheckReport()
    check_live_yaml(report)

    check = _find_check(report, "live.yaml safety")
    assert check.status == "PASS"


# ------------------------------------------------------------------ #
# Additional: TWS port reachability                                   #
# ------------------------------------------------------------------ #


def test_tws_port_reachable_passes_on_success():
    """When socket.connect_ex returns 0, port check should PASS."""
    report = HealthcheckReport()

    with patch("scripts.quagent_healthcheck.socket.socket") as mock_socket_cls:
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 0
        mock_socket_cls.return_value = mock_sock

        result = check_tws_port_reachable(report, "127.0.0.1", 7497)

    assert result is True
    check = _find_check(report, "TWS port reachable")
    assert check.status == "PASS"


def test_tws_port_reachable_fails_on_refused():
    """When socket.connect_ex returns non-zero, port check should FAIL."""
    report = HealthcheckReport()

    with patch("scripts.quagent_healthcheck.socket.socket") as mock_socket_cls:
        mock_sock = MagicMock()
        mock_sock.connect_ex.return_value = 10061
        mock_socket_cls.return_value = mock_sock

        result = check_tws_port_reachable(report, "127.0.0.1", 7497)

    assert result is False
    check = _find_check(report, "TWS port reachable")
    assert check.status == "FAIL"


if __name__ == "__main__":
    import pytest as _pytest

    _pytest.main([__file__, "-v"])

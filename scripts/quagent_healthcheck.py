#!/usr/bin/env python
"""
QuAgent local deployment healthcheck.

Determines whether the system is safe and ready for read-only dry-run operation.

NEVER submits orders.  NEVER calls ib.placeOrder().
NEVER cancels orders.   NEVER calls ib.cancelOrder().

Usage:
    python scripts/quagent_healthcheck.py --config configs/paper.yaml
    python scripts/quagent_healthcheck.py --config configs/paper.yaml --connect
    python scripts/quagent_healthcheck.py --config configs/paper.yaml --connect --symbol SPY

Safety guards:
    1. Verifies config.trading_mode is 'paper'.
    2. Verifies ibkr.read_only_api is True.
    3. Verifies allow_live is False.
    4. Scans source tree for forbidden broker calls.
    5. Verifies required docs exist.
    6. (optional) Connects to TWS with readonly=True for connectivity check.
    7. (optional) Fetches a quote; incomplete quote is WARN, not FAIL.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import asyncio
import ast
import socket
from dataclasses import dataclass, field
from typing import List, Optional

import yaml

from app.utils import get_relative_path
from app.logger import get_logger

logger = get_logger(__name__)

_SEP = "=" * 62


# ------------------------------------------------------------------ #
# Result tracking                                                      #
# ------------------------------------------------------------------ #


@dataclass
class CheckResult:
    name: str
    status: str  # "PASS", "WARN", "FAIL"
    detail: str = ""


@dataclass
class HealthcheckReport:
    checks: List[CheckResult] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.checks.append(CheckResult(name=name, status=status, detail=detail))

    @property
    def overall_pass(self) -> bool:
        return all(c.status != "FAIL" for c in self.checks)

    def print_report(self) -> None:
        print(f"\n{_SEP}")
        print("  QUAGENT HEALTHCHECK")
        print(_SEP)
        for c in self.checks:
            suffix = f"  ({c.detail})" if c.detail else ""
            print(f"  [{c.status:4s}] {c.name}{suffix}")
        print(_SEP)
        result = "PASS" if self.overall_pass else "FAIL"
        print(f"  Final result: {result}")
        print(f"{_SEP}\n")


# ------------------------------------------------------------------ #
# Individual checks (offline — no IBKR connection)                    #
# ------------------------------------------------------------------ #


def check_project_root(report: HealthcheckReport) -> None:
    """Verify project root is detected correctly."""
    root = get_relative_path(".")
    if root.exists() and (root / "app").is_dir():
        report.add("Project root detected", "PASS", str(root))
    else:
        report.add("Project root detected", "FAIL", f"Cannot find project root at {root}")


def check_config_exists(report: HealthcheckReport, config_path: str) -> Optional[Path]:
    """Verify config file exists. Returns resolved path or None."""
    resolved = get_relative_path(config_path)
    if resolved.exists():
        report.add("Config file exists", "PASS", str(resolved))
        return resolved
    else:
        report.add("Config file exists", "FAIL", f"File not found: {resolved}")
        return None


def check_config_loads(report: HealthcheckReport, config_file: Path) -> Optional[dict]:
    """Verify config loads successfully as YAML. Returns dict or None."""
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f) or {}
        report.add("Config loads successfully", "PASS")
        return config_dict
    except Exception as exc:
        report.add("Config loads successfully", "FAIL", str(exc))
        return None


def check_mode_is_paper(report: HealthcheckReport, config_dict: dict) -> None:
    """Verify config trading_mode is 'paper'."""
    mode = config_dict.get("trading_mode", "unknown")
    if mode == "paper":
        report.add("Config mode is paper", "PASS")
    else:
        report.add("Config mode is paper", "FAIL", f"trading_mode={mode!r}")


def check_read_only_api(report: HealthcheckReport, config_dict: dict) -> None:
    """Verify ibkr.read_only_api is True."""
    ibkr = config_dict.get("ibkr", {})
    read_only = ibkr.get("read_only_api", None)
    if read_only is True:
        report.add("Read-only API required", "PASS")
    else:
        report.add("Read-only API required", "FAIL", f"read_only_api={read_only!r}")


def check_live_trading_disabled(report: HealthcheckReport, config_dict: dict) -> None:
    """Verify allow_live is False in the loaded config."""
    allow_live = config_dict.get("allow_live", None)
    if allow_live is False:
        report.add("Live trading disabled", "PASS")
    else:
        report.add("Live trading disabled", "FAIL", f"allow_live={allow_live!r}")


def check_live_yaml(report: HealthcheckReport) -> None:
    """Check configs/live.yaml has allow_live=false if available."""
    live_path = get_relative_path("configs/live.yaml")
    if not live_path.exists():
        report.add("live.yaml safety", "PASS", "file not present (OK)")
        return
    try:
        with open(live_path, "r", encoding="utf-8") as f:
            live_dict = yaml.safe_load(f) or {}
        allow_live = live_dict.get("allow_live", None)
        if allow_live is False:
            report.add("live.yaml safety", "PASS", "allow_live=false")
        else:
            report.add("live.yaml safety", "FAIL", f"allow_live={allow_live!r}")
    except Exception as exc:
        report.add("live.yaml safety", "FAIL", str(exc))


_FORBIDDEN_METHODS = {"placeOrder", "cancelOrder", "reqGlobalCancel"}

# Directories to scan for forbidden calls
_SCAN_DIRS = ["app", "scripts"]


def _find_forbidden_calls_ast(content: str, filename: str) -> list:
    """
    Use Python AST parsing to find actual forbidden method calls in source code.
    Only matches real Call nodes — docstrings, comments, and string literals are ignored.
    """
    violations = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in _FORBIDDEN_METHODS:
                violations.append(f"{filename}:{node.lineno}: ib.{attr_name}()")

    return violations


def check_forbidden_broker_calls(report: HealthcheckReport) -> None:
    """
    Scan app/*.py and scripts/*.py for forbidden real broker call patterns.
    Uses AST parsing to find actual method calls — docstrings, comments,
    and string literals are not flagged.
    """
    violations = []
    for scan_dir in _SCAN_DIRS:
        dir_path = get_relative_path(scan_dir)
        if not dir_path.is_dir():
            continue
        for py_file in dir_path.glob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue
            violations.extend(_find_forbidden_calls_ast(content, py_file.name))

    if violations:
        detail = "; ".join(violations)
        report.add("Forbidden broker calls absent", "FAIL", detail)
    else:
        report.add("Forbidden broker calls absent", "PASS")


_REQUIRED_DOCS = [
    "docs/AI_CONTEXT.md",
    "docs/PROJECT_STATUS.md",
    "docs/SAFETY_INVARIANTS.md",
]


def check_required_docs(report: HealthcheckReport) -> None:
    """Verify required documentation files exist."""
    missing = []
    for doc in _REQUIRED_DOCS:
        if not get_relative_path(doc).exists():
            missing.append(doc)
    if missing:
        report.add("Required docs exist", "FAIL", f"Missing: {', '.join(missing)}")
    else:
        report.add("Required docs exist", "PASS", f"{len(_REQUIRED_DOCS)} docs found")


# ------------------------------------------------------------------ #
# Connection checks (optional --connect)                              #
# ------------------------------------------------------------------ #


def check_tws_port_reachable(
    report: HealthcheckReport,
    host: str,
    port: int,
    timeout: float = 5.0,
) -> bool:
    """Check whether TWS port is reachable via TCP."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            report.add("TWS port reachable", "PASS", f"{host}:{port}")
            return True
        else:
            report.add(
                "TWS port reachable", "FAIL", f"{host}:{port} — connection refused (code {result})"
            )
            return False
    except Exception as exc:
        report.add("TWS port reachable", "FAIL", f"{host}:{port} — {exc}")
        return False


async def check_ibkr_connection(
    report: HealthcheckReport,
    host: str,
    port: int,
    client_id: int,
    read_only_api: bool,
) -> Optional[object]:
    """
    Connect to IBKR with readonly=True, read managed accounts / account summary,
    then disconnect cleanly. Returns IBKRClient on success, None on failure.

    This must NOT request open orders if read_only_api=True.
    This must NOT submit orders.
    This must NOT cancel orders.
    """
    from app.ibkr_client import IBKRClient

    client = IBKRClient(
        host=host,
        port=port,
        client_id=client_id,
        read_only_api=read_only_api,
    )

    try:
        connected = await client.connect()
        if not connected:
            report.add("Account summary readable", "FAIL", "Connection failed")
            return None

        # Read managed accounts (lightweight, read-only)
        ib = client.get_ib()
        accounts = ib.managedAccounts()
        if accounts:
            report.add(
                "Account summary readable", "PASS", f"Managed accounts: {', '.join(accounts)}"
            )
        else:
            report.add("Account summary readable", "WARN", "No managed accounts returned")

        # Disconnect cleanly
        await client.disconnect()
        return client
    except Exception as exc:
        report.add("Account summary readable", "FAIL", str(exc))
        try:
            await client.disconnect()
        except Exception:
            pass
        return None


async def check_quote(
    report: HealthcheckReport,
    host: str,
    port: int,
    client_id: int,
    read_only_api: bool,
    symbol: str,
    data_type: str = "delayed",
    stale_seconds: int = 300,
) -> None:
    """
    Fetch a quote using existing MarketDataManager.
    Incomplete quote is WARN, not hard FAIL.
    """
    from app.ibkr_client import IBKRClient
    from app.market_data import MarketDataManager

    client = IBKRClient(
        host=host,
        port=port,
        client_id=client_id,
        read_only_api=read_only_api,
    )

    try:
        connected = await client.connect()
        if not connected:
            report.add(f"Quote ({symbol})", "WARN", "Could not connect for quote")
            return

        market_mgr = MarketDataManager(
            client,
            data_type=data_type,
            stale_seconds=stale_seconds,
        )

        quote = await market_mgr.get_stock_quote(symbol)
        quality = quote.get("quote_quality", "unknown")

        if quality == "complete":
            price = quote.get("price", "N/A")
            report.add(f"Quote ({symbol})", "PASS", f"quality=complete, price={price}")
        else:
            report.add(
                f"Quote ({symbol})",
                "WARN",
                f"quality={quality}, is_stale={quote.get('is_stale', 'N/A')}",
            )

        await client.disconnect()
    except Exception as exc:
        report.add(f"Quote ({symbol})", "WARN", str(exc))
        try:
            await client.disconnect()
        except Exception:
            pass


# ------------------------------------------------------------------ #
# Core runner                                                          #
# ------------------------------------------------------------------ #


def run_offline_checks(config_path: str) -> HealthcheckReport:
    """Run all offline (no IBKR connection) checks."""
    report = HealthcheckReport()

    check_project_root(report)
    config_file = check_config_exists(report, config_path)
    if config_file is None:
        return report

    config_dict = check_config_loads(report, config_file)
    if config_dict is None:
        return report

    check_mode_is_paper(report, config_dict)
    check_read_only_api(report, config_dict)
    check_live_trading_disabled(report, config_dict)
    check_live_yaml(report)
    check_forbidden_broker_calls(report)
    check_required_docs(report)

    return report


async def run_online_checks(
    report: HealthcheckReport,
    config_path: str,
    symbol: Optional[str] = None,
) -> None:
    """Run connection-based checks (--connect mode)."""
    try:
        with open(get_relative_path(config_path), "r", encoding="utf-8") as f:
            config_dict = yaml.safe_load(f) or {}
    except Exception as exc:
        report.add("TWS port reachable", "FAIL", f"Cannot load config: {exc}")
        return

    ibkr = config_dict.get("ibkr", {})
    host = ibkr.get("host", "127.0.0.1")
    port = ibkr.get("port", 7497)
    client_id = ibkr.get("client_id", 1)
    read_only_api = ibkr.get("read_only_api", True)

    port_ok = check_tws_port_reachable(report, host, port)
    if not port_ok:
        return

    await check_ibkr_connection(report, host, port, client_id, read_only_api)

    if symbol:
        md = config_dict.get("market_data", {})
        data_type = md.get("data_type", "delayed")
        stale_seconds = md.get("stale_seconds", 300)
        await check_quote(
            report,
            host,
            port,
            client_id,
            read_only_api,
            symbol.upper(),
            data_type,
            stale_seconds,
        )


# ------------------------------------------------------------------ #
# CLI entry point                                                      #
# ------------------------------------------------------------------ #


async def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "QuAgent local deployment healthcheck — "
            "verifies system is safe and ready for read-only dry-run"
        )
    )
    parser.add_argument(
        "--config",
        default="configs/paper.yaml",
        help="Path to config YAML (default: configs/paper.yaml)",
    )
    parser.add_argument(
        "--connect",
        action="store_true",
        default=False,
        help="Also check TWS connectivity (requires TWS to be running)",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        metavar="SYMBOL",
        help="Symbol to test quote fetch (requires --connect)",
    )
    args = parser.parse_args()

    # ── Offline checks ─────────────────────────────────────────────
    report = run_offline_checks(args.config)

    # ── Online checks (optional) ───────────────────────────────────
    if args.connect:
        symbol = args.symbol.upper() if args.symbol else None
        await run_online_checks(report, args.config, symbol)

    report.print_report()
    return 0 if report.overall_pass else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

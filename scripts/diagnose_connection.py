#!/usr/bin/env python
"""
IBKR connection diagnostics - read-only, no order submission.
Run this before attempting any IBKRClient connection.

Usage:
    python scripts/diagnose_connection.py
    python scripts/diagnose_connection.py --host 127.0.0.1 --port 7497 --client-id 1
"""

import argparse
import asyncio
import socket
import sys
from datetime import datetime, timezone

# ------------------------------------------------------------------ #
# Port reference table                                                #
# ------------------------------------------------------------------ #
KNOWN_PORTS = {
    7497: "TWS          - paper trading (default)",
    7496: "TWS          - live trading",
    4002: "IB Gateway   - paper trading",
    4001: "IB Gateway   - live trading",
}


def _tcp_probe(host: str, port: int, timeout: float = 3.0):
    """
    Raw TCP probe. Returns (reachable: bool, detail: str).
    Does not send any IBKR protocol bytes.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True, "TCP connection succeeded"
    except ConnectionRefusedError:
        return False, "Connection refused - nothing is listening on this port"
    except TimeoutError:
        return False, "Timed out - host unreachable or firewall dropping packets"
    except OSError as exc:
        return False, f"OS error {exc.errno}: {exc.strerror}"
    finally:
        try:
            s.close()
        except Exception:
            pass


def scan_all_ports(host: str) -> dict:
    """Probe all four standard IBKR ports. Returns {port: (ok, detail)}."""
    return {port: _tcp_probe(host, port) for port in KNOWN_PORTS}


async def try_ib_insync_connect(host: str, port: int, client_id: int):
    """
    Attempt a real ib_insync connect/disconnect.
    Never places an order. Returns (ok: bool, detail: str).
    """
    try:
        import ib_insync
        ib = ib_insync.IB()
        await ib.connectAsync(host, port, clientId=client_id, timeout=8, readonly=True)
        accounts = ib.managedAccounts()
        ib.disconnect()
        return True, f"Connected OK - managed accounts: {accounts}"
    except Exception as exc:
        return False, str(exc)


def sep(title: str = "") -> None:
    line = "=" * 62
    if title:
        print(f"\n{line}\n  {title}\n{line}")
    else:
        print(line)


def ok_marker(flag: bool) -> str:
    return "[OK]  " if flag else "[FAIL]"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IBKR connection diagnostics (read-only)"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7497)
    parser.add_argument("--client-id", type=int, default=1)
    args = parser.parse_args()

    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\nQuAgent IBKR Connection Diagnostics  [{ts}]")
    print(f"Target: {args.host}:{args.port}  client_id={args.client_id}")

    # ── 1. Scan all IBKR ports ─────────────────────────────────────────
    sep("1. Port scan (all standard IBKR ports)")
    scan = scan_all_ports(args.host)
    any_open = False
    for port, label in KNOWN_PORTS.items():
        ok, detail = scan[port]
        print(f"  {ok_marker(ok)} {port:5d}  {label}")
        print(f"               {detail}")
        if ok:
            any_open = True

    if not any_open:
        print("\n  WARNING: No IBKR ports are open on this host.")
        print("  TWS or IB Gateway does not appear to be running.")

    # ── 2. Check configured target port ───────────────────────────────
    sep(f"2. Target port  {args.host}:{args.port}")
    ok, detail = scan.get(args.port, _tcp_probe(args.host, args.port))
    print(f"  {ok_marker(ok)} {args.host}:{args.port}")
    print(f"               {detail}")
    target_ok = ok

    # ── 3. ib_insync connect attempt ───────────────────────────────────
    sep("3. ib_insync connect attempt (Read-Only API compatible)")
    print("  NOTE: this step only calls connectAsync + managedAccounts + disconnect.")
    print("  It does NOT call openTrades, reqOpenOrders, cancelOrder, or placeOrder.")
    print("  It is safe to run with TWS Read-Only API enabled.")
    if not target_ok:
        print("  SKIPPED - target port is not reachable (fix section 2 first)")
    else:
        print(f"  Trying ib_insync connectAsync("
              f"{args.host}, {args.port}, clientId={args.client_id}) ...")
        ib_ok, ib_detail = asyncio.run(
            try_ib_insync_connect(args.host, args.port, args.client_id)
        )
        print(f"  {ok_marker(ib_ok)} {ib_detail}")

    # ── 4. Root-cause checklist ────────────────────────────────────────
    sep("4. Root-cause checklist")
    items = [
        (
            "TWS or IB Gateway is open and fully logged in",
            [
                "Launch Trader Workstation (paper account) OR IB Gateway.",
                "Wait until the login screen clears and the main window loads.",
                "Paper TWS login: select 'Paper Trading' in the login dialog.",
            ],
        ),
        (
            "API socket server is enabled in TWS / Gateway",
            [
                "TWS:        Edit > Global Configuration > API > Settings",
                "IB Gateway: Configure > API > Settings",
                "  -> Check 'Enable ActiveX and Socket Clients'",
                "  -> Socket port: 7497 (paper TWS) or 4002 (paper Gateway)",
                "  -> Apply and restart TWS/Gateway if you change this setting.",
            ],
        ),
        (
            "'Read-Only API' is enabled (safety recommendation)",
            [
                "Same API settings panel:",
                "  -> Check 'Read-Only API'",
                "This prevents accidental order submission from any API client.",
            ],
        ),
        (
            "127.0.0.1 is in the Trusted IP list",
            [
                "API Settings > Trusted IPs",
                "  -> Add 127.0.0.1 if not present.",
                "Without this, TWS may silently refuse connections.",
            ],
        ),
        (
            f"client_id={args.client_id} is not already in use",
            [
                "Each active ib_insync session needs a unique client_id.",
                "If another script is running with client_id=1, change",
                "  configs/paper.yaml  ibkr.client_id to 2 (or any free number).",
            ],
        ),
        (
            "configs/paper.yaml port matches the running application",
            [
                "  TWS paper      -> port 7497   (current config: "
                + str(args.port) + ")",
                "  IB Gateway paper -> port 4002",
                "Update ibkr.port in configs/paper.yaml to match.",
            ],
        ),
    ]
    for i, (check, lines) in enumerate(items, 1):
        print(f"\n  [{i}] {check}")
        for line in lines:
            print(f"       {line}")

    # ── 5. Commands to re-test ─────────────────────────────────────────
    sep("5. Re-test after fixing")
    print("  # Re-run this diagnostic against TWS (port 7497):")
    print("  python scripts/diagnose_connection.py --port 7497")
    print()
    print("  # Or against IB Gateway paper (port 4002):")
    print("  python scripts/diagnose_connection.py --port 4002")
    print()
    print("  # If diagnostic passes, check account (read-only):")
    print("  python scripts/check_account.py --config configs/paper.yaml")
    print("  python scripts/check_account.py --config configs/paper.yaml --quote SPY")
    print()
    sep()


if __name__ == "__main__":
    main()

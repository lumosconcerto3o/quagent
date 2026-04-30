"""
Verify that every CLI script can be imported without ModuleNotFoundError.

All tests are offline — no IBKR connection is made.
The tests load each script as a module via importlib, which executes the
path-bootstrap block and all top-level imports, but does NOT call main()
or asyncio.run() because those are inside `if __name__ == "__main__":`.
"""

import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    """Load a script file as a module without running its __main__ block."""
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_script_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_check_account_importable():
    """scripts/check_account.py must import cleanly and expose main()."""
    mod = _load("check_account")
    assert callable(mod.main)


def test_diagnose_connection_importable():
    """scripts/diagnose_connection.py must import cleanly and expose main()."""
    mod = _load("diagnose_connection")
    assert callable(mod.main)


def test_emergency_flatten_importable():
    """scripts/emergency_flatten.py must import cleanly and expose plan_flatten()."""
    mod = _load("emergency_flatten")
    assert callable(mod.plan_flatten)
    assert callable(mod.main)


def test_emergency_cancel_all_importable():
    """scripts/emergency_cancel_all.py must import cleanly and expose main()."""
    mod = _load("emergency_cancel_all")
    assert callable(mod.main)


def test_submit_signal_importable():
    """scripts/submit_signal.py must import cleanly and expose main()."""
    mod = _load("submit_signal")
    assert callable(mod.main)


def test_run_paper_importable():
    """scripts/run_paper.py must import cleanly and expose main()."""
    mod = _load("run_paper")
    assert callable(mod.main)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

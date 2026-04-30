"""
Utility functions for QuAgent.
"""

from pathlib import Path
from typing import Any


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def ensure_dir_exists(path: str) -> Path:
    """Ensure a directory exists, create if necessary."""
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def get_relative_path(relative_path: str) -> Path:
    """Get an absolute path from a relative path (relative to project root)."""
    return get_project_root() / relative_path


def format_currency(value: float, decimals: int = 2) -> str:
    """Format a number as currency."""
    return f"${value:,.{decimals}f}"


def format_percentage(value: float, decimals: int = 2) -> str:
    """Format a number as percentage."""
    return f"{value:.{decimals}f}%"


def safe_dict_get(d: dict, *keys: str, default: Any = None) -> Any:
    """Safely navigate nested dictionary."""
    current = d
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current

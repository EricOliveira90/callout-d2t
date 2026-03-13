"""Common Jinja filters shared across all strategies."""

import json
from datetime import datetime


def dateformat(value: datetime, fmt: str = "%Y-%m-%d") -> str:
    """Format a datetime value."""
    return value.strftime(fmt)


def as_currency(value: float, symbol: str = "$") -> str:
    """Format a number as currency."""
    return f"{symbol}{value:,.2f}"


def as_pct(value: float, decimals: int = 1) -> str:
    """Format a number as a percentage."""
    return f"{value:.{decimals}f}%"


def jsonify(value, **kwargs) -> str:
    """Serialize a value to JSON."""
    return json.dumps(value, default=str, **kwargs)


COMMON_FILTERS: dict[str, callable] = {
    "dateformat": dateformat,
    "as_currency": as_currency,
    "as_pct": as_pct,
    "jsonify": jsonify,
}

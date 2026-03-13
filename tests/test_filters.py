# tests/test_filters.py
import json
from datetime import datetime

from d2t.filters import COMMON_FILTERS


def test_dateformat_default():
    dt = datetime(2026, 3, 12, 14, 30)
    result = COMMON_FILTERS["dateformat"](dt)
    assert result == "2026-03-12"


def test_dateformat_custom():
    dt = datetime(2026, 3, 12, 14, 30)
    result = COMMON_FILTERS["dateformat"](dt, "%Y/%m/%d %H:%M")
    assert result == "2026/03/12 14:30"


def test_as_currency_default():
    result = COMMON_FILTERS["as_currency"](1234.5)
    assert result == "$1,234.50"


def test_as_currency_custom_symbol():
    result = COMMON_FILTERS["as_currency"](1234.5, symbol="EUR ")
    assert result == "EUR 1,234.50"


def test_as_pct_default():
    result = COMMON_FILTERS["as_pct"](12.345)
    assert result == "12.3%"


def test_as_pct_custom_decimals():
    result = COMMON_FILTERS["as_pct"](12.345, decimals=2)
    assert result == "12.35%"


def test_jsonify():
    data = {"a": 1, "b": [2, 3]}
    result = COMMON_FILTERS["jsonify"](data)
    assert json.loads(result) == data

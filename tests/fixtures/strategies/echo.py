# tests/fixtures/strategies/echo.py
"""A minimal strategy that echoes its inputs for testing."""

from d2t.strategy import AnalysisStrategy


class Echo(AnalysisStrategy):
    """A minimal strategy that echoes its inputs for testing."""

    def __init__(self, prefix=""):
        self.prefix = prefix

    def process(self, inputs):
        rows = inputs["main"]
        return {
            "prefix": self.prefix,
            "rows": rows,
            "count": len(rows),
        }

    def get_filters(self):
        return {"echo_upper": lambda v: str(v).upper()}

# tests/fixtures/strategies/failing.py
"""A strategy that always raises during process()."""

from d2t.strategy import AnalysisStrategy
from d2t.errors import StrategyProcessingError


class Failing(AnalysisStrategy):
    """A strategy that always fails during processing."""

    def process(self, inputs):
        raise StrategyProcessingError("Intentional failure for testing")

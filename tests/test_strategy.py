# tests/test_strategy.py
from pathlib import Path

import pytest

from d2t.strategy import AnalysisStrategy, load_strategy, list_strategies, coerce_param
from d2t.errors import UnknownStrategyError

FIXTURES = Path(__file__).parent / "fixtures"


class TestAnalysisStrategyABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            AnalysisStrategy()

    def test_get_filters_default_empty(self):
        class Minimal(AnalysisStrategy):
            def process(self, inputs):
                return {}

        s = Minimal()
        assert s.get_filters() == {}
        assert s.get_globals() == {}


class TestCoerceParam:
    def test_coerce_int(self):
        assert coerce_param("42") == 42

    def test_coerce_float(self):
        assert coerce_param("3.14") == 3.14

    def test_coerce_bool_true(self):
        assert coerce_param("true") is True

    def test_coerce_bool_false(self):
        assert coerce_param("false") is False

    def test_coerce_string(self):
        assert coerce_param("hello") == "hello"


class TestLoadStrategy:
    def test_load_from_external_dir(self):
        strategy = load_strategy(
            "echo",
            params={},
            strategy_dirs=[FIXTURES / "strategies"],
        )
        assert isinstance(strategy, AnalysisStrategy)

    def test_load_with_params(self):
        strategy = load_strategy(
            "echo",
            params={"prefix": "test"},
            strategy_dirs=[FIXTURES / "strategies"],
        )
        result = strategy.process({"main": [{"a": 1}]})
        assert result["prefix"] == "test"

    def test_raises_unknown_strategy(self):
        with pytest.raises(UnknownStrategyError):
            load_strategy("nonexistent", params={}, strategy_dirs=[])

    def test_external_dir_shadows_builtin(self):
        # External dirs are searched first
        strategy = load_strategy(
            "echo",
            params={},
            strategy_dirs=[FIXTURES / "strategies"],
        )
        # Should find the fixture version, not a built-in (which doesn't exist for "echo")
        assert isinstance(strategy, AnalysisStrategy)


class TestListStrategies:
    def test_list_from_external_dir(self):
        strategies = list_strategies(strategy_dirs=[FIXTURES / "strategies"])
        names = [s["name"] for s in strategies]
        assert "echo" in names

    def test_list_includes_docstring(self):
        strategies = list_strategies(strategy_dirs=[FIXTURES / "strategies"])
        echo = next(s for s in strategies if s["name"] == "echo")
        assert "minimal" in echo["description"].lower()

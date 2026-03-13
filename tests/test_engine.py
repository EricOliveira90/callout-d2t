# tests/test_engine.py
from pathlib import Path

import pytest
from jinja2 import UndefinedError

from d2t.engine import build_environment, render
from d2t.errors import UnknownTemplateError, TemplateRenderError

FIXTURES = Path(__file__).parent / "fixtures"


class TestBuildEnvironment:
    def test_creates_environment_with_common_filters(self):
        env = build_environment(template_dirs=[FIXTURES / "templates"])
        assert "as_currency" in env.filters
        assert "as_pct" in env.filters
        assert "dateformat" in env.filters
        assert "jsonify" in env.filters

    def test_registers_strategy_filters(self):
        extra_filters = {"double": lambda v: v * 2}
        env = build_environment(
            template_dirs=[FIXTURES / "templates"],
            strategy_filters=extra_filters,
        )
        assert "double" in env.filters

    def test_registers_now_global(self):
        env = build_environment(template_dirs=[FIXTURES / "templates"])
        assert "now" in env.globals

    def test_uses_strict_undefined(self):
        env = build_environment(template_dirs=[FIXTURES / "templates"])
        template = env.get_template("simple.j2")
        with pytest.raises(UndefinedError):
            template.render()  # missing 'count' and 'rows'


class TestRender:
    def test_renders_template_with_context(self):
        context = {
            "count": 2,
            "rows": [
                {"name": "Alice", "value": 10},
                {"name": "Bob", "value": 20},
            ],
        }
        result = render(
            template_name="simple",
            context=context,
            template_dirs=[FIXTURES / "templates"],
        )
        assert "Count: 2" in result
        assert "Alice: 10" in result
        assert "Bob: 20" in result

    def test_raises_unknown_template(self):
        with pytest.raises(UnknownTemplateError):
            render(
                template_name="nonexistent",
                context={},
                template_dirs=[FIXTURES / "templates"],
            )

    def test_raises_template_render_error_on_undefined(self):
        with pytest.raises(TemplateRenderError):
            render(
                template_name="simple",
                context={},  # missing required vars
                template_dirs=[FIXTURES / "templates"],
            )

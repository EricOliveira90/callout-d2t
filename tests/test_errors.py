# tests/test_errors.py
from d2t.errors import (
    D2tError,
    InputNotFoundError,
    InputParseError,
    UnknownStrategyError,
    StrategyProcessingError,
    UnknownTemplateError,
    TemplateRenderError,
    UnknownRecipeError,
    RecipeConfigError,
    format_error,
)


def test_base_error_has_exit_code():
    err = D2tError("something broke")
    assert err.exit_code == 1
    assert str(err) == "something broke"


def test_input_not_found_error():
    err = InputNotFoundError("sales.csv")
    assert err.exit_code == 10


def test_input_parse_error():
    err = InputParseError("bad csv")
    assert err.exit_code == 11


def test_unknown_strategy_error():
    err = UnknownStrategyError("foo", available=["bar", "baz"])
    assert err.exit_code == 20
    assert "foo" in str(err)
    assert "bar" in str(err)


def test_strategy_processing_error():
    err = StrategyProcessingError("key error")
    assert err.exit_code == 21


def test_unknown_template_error():
    err = UnknownTemplateError("missing.j2", available=["report.j2", "summary.j2"])
    assert err.exit_code == 30
    assert "missing.j2" in str(err)
    assert "report.j2" in str(err)


def test_template_render_error():
    err = TemplateRenderError("'total' is undefined")
    assert err.exit_code == 31


def test_unknown_recipe_error():
    err = UnknownRecipeError("bad_recipe", available=["good_recipe"])
    assert err.exit_code == 40
    assert "bad_recipe" in str(err)
    assert "good_recipe" in str(err)


def test_recipe_config_error():
    err = RecipeConfigError("invalid yaml")
    assert err.exit_code == 41


def test_format_error():
    err = InputNotFoundError("sales.csv")
    result = format_error(err)
    assert result == "d2t: error[10]: sales.csv"

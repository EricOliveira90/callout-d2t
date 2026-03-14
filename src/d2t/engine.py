"""Jinja2 environment setup and rendering."""

import datetime
from pathlib import Path

from jinja2 import (
    ChoiceLoader,
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateNotFound,
    TemplateRuntimeError,
    TemplateSyntaxError,
    UndefinedError,
)

from d2t.errors import UnknownTemplateError, TemplateRenderError
from d2t.filters import COMMON_FILTERS


def _builtin_template_dir() -> Path:
    """Return the path to the built-in templates directory."""
    return Path(__file__).parent / "templates"


def build_environment(
    template_dirs: list[Path] | None = None,
    strategy_filters: dict | None = None,
    strategy_globals: dict | None = None,
) -> Environment:
    """Build a Jinja2 Environment with loaders, filters, and globals."""
    search_paths = [str(d) for d in (template_dirs or [])]
    builtin = _builtin_template_dir()
    if builtin.is_dir():
        search_paths.append(str(builtin))

    loader = (
        ChoiceLoader([FileSystemLoader(p) for p in search_paths])
        if search_paths
        else None
    )

    env = Environment(
        loader=loader,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )

    # Common filters
    env.filters.update(COMMON_FILTERS)

    # Strategy filters
    if strategy_filters:
        env.filters.update(strategy_filters)

    # Globals
    env.globals["now"] = datetime.datetime.now()
    if strategy_globals:
        env.globals.update(strategy_globals)

    return env


def render(
    template_name: str,
    context: dict,
    template_dirs: list[Path] | None = None,
    strategy_filters: dict | None = None,
    strategy_globals: dict | None = None,
) -> str:
    """Load a template by name and render it with the given context."""
    env = build_environment(template_dirs, strategy_filters, strategy_globals)

    try:
        template = env.get_template(f"{template_name}.j2")
    except TemplateNotFound:
        available = sorted(env.loader.list_templates()) if env.loader else []
        public = [t for t in available if not t.startswith("_")]
        raise UnknownTemplateError(f"{template_name}.j2", available=public)

    try:
        return template.render(**context)
    except (
        UndefinedError,
        TemplateSyntaxError,
        TemplateRuntimeError,
        TypeError,
        ValueError,
        AttributeError,
    ) as e:
        raise TemplateRenderError(str(e)) from e

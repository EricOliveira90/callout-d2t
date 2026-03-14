# src/d2t/strategy.py
"""Analysis strategy base class and dynamic loader."""

import importlib
import importlib.util
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable

from d2t.errors import UnknownStrategyError


class AnalysisStrategy(ABC):
    """Base class for analysis strategies."""

    @abstractmethod
    def process(self, inputs: dict[str, list[dict]]) -> dict:
        """Transform named inputs into a template context dict."""
        ...

    def get_filters(self) -> dict[str, Callable]:
        """Return custom Jinja filters this strategy provides."""
        return {}

    def get_globals(self) -> dict[str, Any]:
        """Return custom Jinja globals this strategy provides."""
        return {}


def coerce_param(value: str):
    """Coerce a string param to int, float, bool, or leave as string."""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _find_strategy_class(module) -> type[AnalysisStrategy] | None:
    """Find the first AnalysisStrategy subclass in a module."""
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (
            isinstance(attr, type)
            and issubclass(attr, AnalysisStrategy)
            and attr is not AnalysisStrategy
        ):
            return attr
    return None


def _load_from_file(name: str, directory: Path):
    """Load a strategy module from a .py file using spec_from_file_location.

    WARNING: This executes arbitrary Python code from the given directory.
    Only load strategies from directories you trust.
    """
    file_path = directory / f"{name}.py"
    if not file_path.exists():
        return None

    spec = importlib.util.spec_from_file_location(
        f"d2t_external_strategy_{name}", file_path
    )
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return _find_strategy_class(module)


def _load_builtin(name: str):
    """Load a built-in strategy via importlib.import_module."""
    try:
        module = importlib.import_module(f"d2t.strategies.{name}")
    except ModuleNotFoundError:
        return None
    return _find_strategy_class(module)


def load_strategy(
    name: str,
    params: dict[str, str],
    strategy_dirs: list[Path] | None = None,
) -> AnalysisStrategy:
    """
    Load and instantiate a strategy by name.

    Search order: strategy_dirs (left to right), then built-in strategies.
    """
    coerced_params = {k: coerce_param(v) if isinstance(v, str) else v for k, v in params.items()}

    # Search external dirs first
    for d in strategy_dirs or []:
        cls = _load_from_file(name, Path(d))
        if cls is not None:
            return cls(**coerced_params)

    # Then built-in
    cls = _load_builtin(name)
    if cls is not None:
        return cls(**coerced_params)

    available = [s["name"] for s in list_strategies(strategy_dirs)]
    raise UnknownStrategyError(name, available=available)


def list_strategies(
    strategy_dirs: list[Path] | None = None,
) -> list[dict[str, str]]:
    """List all available strategies with name and description."""
    seen = set()
    results = []

    # External dirs first
    for d in strategy_dirs or []:
        d = Path(d)
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.py")):
            if f.name.startswith("_"):
                continue
            name = f.stem
            if name in seen:
                continue
            cls = _load_from_file(name, d)
            if cls is not None:
                seen.add(name)
                results.append({
                    "name": name,
                    "description": (cls.__doc__ or "").strip(),
                })

    # Built-in strategies
    builtin_dir = Path(__file__).parent / "strategies"
    if builtin_dir.is_dir():
        for f in sorted(builtin_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            name = f.stem
            if name in seen:
                continue
            cls = _load_builtin(name)
            if cls is not None:
                seen.add(name)
                results.append({
                    "name": name,
                    "description": (cls.__doc__ or "").strip(),
                })

    return results

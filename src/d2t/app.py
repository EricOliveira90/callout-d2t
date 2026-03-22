"""Streamlit UI for d2t report generation."""

from pathlib import Path

from d2t.engine import render
from d2t.input import parse_csv
from d2t.recipe import load_recipe
from d2t.strategy import load_strategy

# Known abbreviations that should stay uppercase
_ABBREVIATIONS = {"wbr", "gms", "yoy", "wow"}


def recipe_display_name(key: str) -> str:
    """Convert a recipe key like 'wbr_gms_callout' to 'WBR GMS Callout'."""
    words = key.split("_")
    return " ".join(w.upper() if w in _ABBREVIATIONS else w.capitalize() for w in words)


def generate_report(
    recipe_name: str,
    main_file_path: Path,
    param_overrides: dict[str, str],
) -> str:
    """Run the d2t pipeline for a recipe and return the rendered output.

    Args:
        recipe_name: Key from config.yaml (e.g. 'wbr_gms_callout').
        main_file_path: Path to the uploaded CSV/TSV file on disk.
        param_overrides: User-provided param overrides (string values).

    Returns:
        Rendered report text.
    """
    recipe_data = load_recipe(recipe_name)

    # Build strategy params: recipe defaults + relations + user overrides
    strategy_params = dict(recipe_data["params"])
    if recipe_data.get("relations"):
        strategy_params["relations"] = recipe_data["relations"]
    strategy_params.update(param_overrides)

    # Parse the main input file
    parsed_inputs = {"main": parse_csv(main_file_path)}

    # Auto-load default inputs (e.g. lookup file) when not provided by user
    for inp_def in recipe_data.get("inputs", []):
        name = inp_def["name"]
        default = inp_def.get("default_path")
        if default and name not in parsed_inputs:
            parsed_inputs[name] = parse_csv(Path(default))

    # Load strategy, process, render
    strat = load_strategy(recipe_data["strategy"], strategy_params)
    context = strat.process(parsed_inputs)
    output = render(
        template_name=recipe_data["template"],
        context=context,
        strategy_filters=strat.get_filters(),
        strategy_globals=strat.get_globals(),
    )
    return output

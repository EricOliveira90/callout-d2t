"""Recipe loading from config.yaml."""

from pathlib import Path

import yaml

from d2t.errors import UnknownRecipeError, RecipeConfigError


def _default_config_path() -> Path:
    """Return the path to the built-in config.yaml."""
    return Path(__file__).parent / "config.yaml"


def _load_config(config_path: Path | None = None) -> dict:
    """Load and parse config.yaml."""
    path = config_path or _default_config_path()
    if not path.exists():
        raise RecipeConfigError(f"Config file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise RecipeConfigError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(config, dict) or "recipes" not in config:
        raise RecipeConfigError(f"Config file {path} must contain a 'recipes' key")

    return config


def load_recipe(name: str, config_path: Path | None = None) -> dict:
    """
    Load a named recipe from config.yaml.

    Returns a dict with keys: description, strategy, template, inputs, params.
    """
    config = _load_config(config_path)
    recipes = config["recipes"]

    if name not in recipes:
        available = list(recipes.keys())
        raise UnknownRecipeError(name, available=available)

    recipe = recipes[name]
    return {
        "description": recipe.get("description", ""),
        "strategy": recipe["strategy"],
        "template": recipe["template"],
        "inputs": recipe.get("inputs", []),
        "params": recipe.get("params", {}),
    }


def list_recipes(config_path: Path | None = None) -> list[dict]:
    """List all available recipes with metadata."""
    config = _load_config(config_path)
    results = []
    for name, recipe in config["recipes"].items():
        results.append({
            "name": name,
            "description": recipe.get("description", ""),
            "strategy": recipe["strategy"],
            "template": recipe["template"],
            "inputs": recipe.get("inputs", []),
        })
    return results

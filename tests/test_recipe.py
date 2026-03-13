# tests/test_recipe.py
from pathlib import Path

import pytest

from d2t.recipe import load_recipe, list_recipes
from d2t.errors import UnknownRecipeError, RecipeConfigError

FIXTURES = Path(__file__).parent / "fixtures"


class TestLoadRecipe:
    def test_loads_recipe_by_name(self):
        recipe = load_recipe("test_echo", config_path=FIXTURES / "config.yaml")
        assert recipe["strategy"] == "echo"
        assert recipe["template"] == "simple"
        assert recipe["params"]["prefix"] == "test"

    def test_recipe_has_description(self):
        recipe = load_recipe("test_echo", config_path=FIXTURES / "config.yaml")
        assert "description" in recipe

    def test_recipe_has_inputs(self):
        recipe = load_recipe("test_echo", config_path=FIXTURES / "config.yaml")
        assert len(recipe["inputs"]) == 1
        assert recipe["inputs"][0]["name"] == "main"

    def test_raises_unknown_recipe(self):
        with pytest.raises(UnknownRecipeError) as exc_info:
            load_recipe("nonexistent", config_path=FIXTURES / "config.yaml")
        assert "test_echo" in str(exc_info.value)

    def test_raises_on_missing_config_file(self):
        with pytest.raises(RecipeConfigError):
            load_recipe("foo", config_path=Path("nonexistent.yaml"))

    def test_raises_on_malformed_yaml(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(": : : invalid yaml [[[")
        with pytest.raises(RecipeConfigError):
            load_recipe("foo", config_path=bad)

    def test_raises_on_missing_recipes_key(self, tmp_path):
        bad = tmp_path / "no_recipes.yaml"
        bad.write_text("something_else: true\n")
        with pytest.raises(RecipeConfigError):
            load_recipe("foo", config_path=bad)


class TestListRecipes:
    def test_lists_all_recipes(self):
        recipes = list_recipes(config_path=FIXTURES / "config.yaml")
        names = [r["name"] for r in recipes]
        assert "test_echo" in names
        assert "multi_input" in names

    def test_recipe_entry_has_fields(self):
        recipes = list_recipes(config_path=FIXTURES / "config.yaml")
        entry = next(r for r in recipes if r["name"] == "test_echo")
        assert "description" in entry
        assert "strategy" in entry
        assert "template" in entry
        assert "inputs" in entry

"""Tests for the Streamlit app helpers."""

from pathlib import Path

import pytest

from d2t.app import generate_report, recipe_display_name


def test_wbr_gms_callout():
    assert recipe_display_name("wbr_gms_callout") == "WBR GMS Callout"


def test_wbr_gms_detailed():
    assert recipe_display_name("wbr_gms_detailed") == "WBR GMS Detailed"


def test_product_selection_callout():
    assert recipe_display_name("product_selection_callout") == "Product Selection Callout"


def test_product_selection_detailed():
    assert recipe_display_name("product_selection_detailed") == "Product Selection Detailed"


def test_generic_snake_case():
    assert recipe_display_name("some_other_recipe") == "Some Other Recipe"


def test_generate_report_bad_recipe():
    """Unknown recipe raises an error."""
    with pytest.raises(Exception):
        generate_report(
            recipe_name="nonexistent_recipe",
            main_file_path=Path("dummy.csv"),
            param_overrides={},
        )

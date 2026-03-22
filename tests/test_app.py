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


def test_monthly_revenue():
    assert recipe_display_name("monthly_revenue") == "Monthly Revenue"


def test_generic_snake_case():
    assert recipe_display_name("some_other_recipe") == "Some Other Recipe"


def test_generate_report_monthly_revenue(tmp_path):
    """generate_report runs the full pipeline for a simple recipe."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("region,revenue\nNorth,100\nSouth,200\n")

    result = generate_report(
        recipe_name="monthly_revenue",
        main_file_path=csv_file,
        param_overrides={},
    )
    assert isinstance(result, str)
    assert "North" in result
    assert "South" in result


def test_generate_report_with_param_override(tmp_path):
    """CLI param overrides are applied."""
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("cat,amount\nA,10\nB,20\n")

    result = generate_report(
        recipe_name="monthly_revenue",
        main_file_path=csv_file,
        param_overrides={"group_col": "cat", "value_col": "amount"},
    )
    assert "A" in result
    assert "B" in result


def test_generate_report_bad_recipe():
    """Unknown recipe raises an error."""
    with pytest.raises(Exception):
        generate_report(
            recipe_name="nonexistent_recipe",
            main_file_path=Path("dummy.csv"),
            param_overrides={},
        )

"""Tests for the Streamlit app helpers."""

from d2t.app import recipe_display_name


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

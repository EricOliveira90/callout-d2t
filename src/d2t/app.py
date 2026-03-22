"""Streamlit UI for d2t report generation."""

# Known abbreviations that should stay uppercase
_ABBREVIATIONS = {"wbr", "gms", "yoy", "wow"}


def recipe_display_name(key: str) -> str:
    """Convert a recipe key like 'wbr_gms_callout' to 'WBR GMS Callout'."""
    words = key.split("_")
    return " ".join(w.upper() if w in _ABBREVIATIONS else w.capitalize() for w in words)

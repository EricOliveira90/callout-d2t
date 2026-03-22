# D2T Streamlit UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Streamlit GUI so non-technical colleagues can generate d2t reports by uploading a file, picking a recipe, and clicking Run.

**Architecture:** A single Streamlit app (`src/d2t/app.py`) wraps the existing pipeline functions (`load_recipe`, `parse_csv`, `load_strategy`, `render`) with no logic duplication. Two testable helper functions are extracted: `recipe_display_name()` for human-readable recipe labels, and `generate_report()` for pipeline orchestration.

**Tech Stack:** Streamlit (optional `[gui]` dependency), existing d2t pipeline (Click, Jinja2, PyYAML)

**Spec:** `docs/superpowers/specs/2026-03-22-d2t-streamlit-ui-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/d2t/app.py` | Create | Streamlit UI + `generate_report()` + `recipe_display_name()` |
| `tests/test_app.py` | Create | Tests for `generate_report()` and `recipe_display_name()` |
| `pyproject.toml` | Modify | Add `gui` optional dependency |
| `run_d2t.bat` | Create | Windows launcher script |
| `setup.bat` | Create | One-time install script |

No changes to: `cli.py`, `recipe.py`, `strategy.py`, `engine.py`, `input.py`, `filters.py`, `errors.py`, `config.yaml`, or any strategy/template files.

---

### Task 1: Add Streamlit optional dependency

**Files:**
- Modify: `pyproject.toml:18` (add `gui` extra alongside existing `dev` extra)

- [ ] **Step 1: Add `gui` extra to pyproject.toml**

In `pyproject.toml`, add after the existing `dev` extra:

```toml
gui = [
    "streamlit>=1.28",
]
```

- [ ] **Step 2: Install the new extra**

Run: `pip install -e ".[gui]"`
Expected: streamlit installs successfully

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add streamlit as optional gui dependency"
```

---

### Task 2: Write `recipe_display_name()` with tests

**Files:**
- Create: `src/d2t/app.py` (start with just this function)
- Create: `tests/test_app.py`

- [ ] **Step 1: Write failing tests for recipe_display_name**

Create `tests/test_app.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Write minimal implementation**

Create `src/d2t/app.py`:

```python
"""Streamlit UI for d2t report generation."""

# Known abbreviations that should stay uppercase
_ABBREVIATIONS = {"wbr", "gms", "yoy", "wow"}


def recipe_display_name(key: str) -> str:
    """Convert a recipe key like 'wbr_gms_callout' to 'WBR GMS Callout'."""
    words = key.split("_")
    return " ".join(w.upper() if w in _ABBREVIATIONS else w.capitalize() for w in words)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/d2t/app.py tests/test_app.py
git commit -m "feat(gui): add recipe_display_name helper with tests"
```

---

### Task 3: Write `generate_report()` with tests

**Files:**
- Modify: `src/d2t/app.py` (add function)
- Modify: `tests/test_app.py` (add tests)

- [ ] **Step 1: Write failing test for generate_report**

The test uses the existing `monthly_revenue` recipe with a simple CSV to verify the full pipeline works. Add to `tests/test_app.py`:

```python
import tempfile
from pathlib import Path

from d2t.app import generate_report


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
    import pytest
    with pytest.raises(Exception):
        generate_report(
            recipe_name="nonexistent_recipe",
            main_file_path=Path("dummy.csv"),
            param_overrides={},
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_app.py::test_generate_report_monthly_revenue -v`
Expected: FAIL with `ImportError` (function doesn't exist yet)

- [ ] **Step 3: Write the implementation**

Add to `src/d2t/app.py`:

```python
from pathlib import Path

from d2t.recipe import load_recipe
from d2t.input import parse_csv
from d2t.strategy import load_strategy
from d2t.engine import render


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
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/test_app.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/d2t/app.py tests/test_app.py
git commit -m "feat(gui): add generate_report pipeline function with tests"
```

---

### Task 4: Write the Streamlit UI

**Files:**
- Modify: `src/d2t/app.py` (add Streamlit UI code)

- [ ] **Step 1: Add the Streamlit UI**

Append to `src/d2t/app.py`, after all the helper functions:

```python
def main():
    """Streamlit app entry point."""
    import streamlit as st
    import tempfile

    from d2t.errors import InputNotFoundError, InputParseError

    st.set_page_config(page_title="D2T Report Generator", layout="centered")
    st.title("D2T Report Generator")
    st.caption("Generate WBR reports from CSV/TSV data.")

    # Load available recipes
    from d2t.recipe import list_recipes

    available = list_recipes()
    recipe_keys = [r["name"] for r in available]
    recipe_labels = [recipe_display_name(k) for k in recipe_keys]
    label_to_key = dict(zip(recipe_labels, recipe_keys))

    # Recipe selector
    selected_label = st.selectbox("Recipe", recipe_labels)
    selected_key = label_to_key[selected_label]
    recipe_data = load_recipe(selected_key)
    st.caption(recipe_data.get("description", ""))

    # File uploader
    main_input = next(
        (i for i in recipe_data.get("inputs", []) if i["name"] == "main"), None
    )
    upload_label = main_input["description"] if main_input else "Upload data file"
    uploaded_file = st.file_uploader(upload_label, type=["csv", "tsv"])

    # Advanced parameters
    param_overrides = {}
    recipe_params = recipe_data.get("params", {})
    if recipe_params:
        with st.expander("Advanced Parameters", expanded=False):
            for key, default in recipe_params.items():
                value = st.text_input(key, value=str(default))
                if value != str(default):
                    param_overrides[key] = value

    # Run button
    run_disabled = uploaded_file is None
    if st.button("Generate Report", disabled=run_disabled):
        # Write uploaded file to temp file so parse_csv can read it
        suffix = "." + (uploaded_file.name.rsplit(".", 1)[-1] if "." in uploaded_file.name else "csv")
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(uploaded_file.getbuffer())
            tmp_path = Path(tmp.name)

        try:
            with st.spinner("Generating report..."):
                output = generate_report(
                    recipe_name=selected_key,
                    main_file_path=tmp_path,
                    param_overrides=param_overrides,
                )

            # Display output in two tabs
            # Note: st.code() includes a built-in copy icon in the top-right corner,
            # which serves as the "Copy to clipboard" feature from the spec.
            tab_preview, tab_raw = st.tabs(["Preview", "Raw Markdown"])
            with tab_preview:
                st.markdown(output)
            with tab_raw:
                st.code(output, language="markdown")

        except (InputNotFoundError, InputParseError) as e:
            st.error("Could not read file. Make sure it's a valid CSV or TSV.")
            with st.expander("Show details"):
                st.code(str(e))
        except Exception as e:
            st.error(f"Report generation failed: {e}")
            with st.expander("Show details"):
                import traceback
                st.code(traceback.format_exc())
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test the app manually**

Run: `streamlit run src/d2t/app.py`
Expected: Browser opens, shows recipe dropdown, file uploader, and Generate Report button. Upload a test CSV and verify output renders.

- [ ] **Step 3: Commit**

```bash
git add src/d2t/app.py
git commit -m "feat(gui): add Streamlit UI for d2t report generation"
```

---

### Task 5: Create launcher and setup scripts

**Files:**
- Create: `run_d2t.bat`
- Create: `setup.bat`

- [ ] **Step 1: Create run_d2t.bat**

Create `run_d2t.bat` at project root:

```bat
@echo off
cd /d "%~dp0"
streamlit run src\d2t\app.py
```

- [ ] **Step 2: Create setup.bat**

Create `setup.bat` at project root:

```bat
@echo off
echo Installing d2t with GUI dependencies...
pip install -e "%~dp0.[gui]"
echo.
echo Done! Double-click run_d2t.bat to start the app.
pause
```

- [ ] **Step 3: Verify launcher works**

Double-click `run_d2t.bat` (or run it from terminal).
Expected: Streamlit starts and browser opens.

- [ ] **Step 4: Commit**

```bash
git add run_d2t.bat setup.bat
git commit -m "feat(gui): add Windows launcher and setup scripts"
```

---

### Task 6: End-to-end verification

- [ ] **Step 1: Run all tests**

Run: `pytest -v`
Expected: All tests pass (existing + new app tests)

- [ ] **Step 2: Verify CLI still works**

Run: `d2t list recipes`
Expected: All 5 recipes listed, no errors

- [ ] **Step 3: Verify app end-to-end**

Run: `streamlit run src/d2t/app.py`
Test each recipe with a real data file:
1. Select "WBR GMS Callout", upload a GMS TSV, verify output
2. Select "Product Selection Callout", upload a selection TSV, verify output
3. Verify "Copy to clipboard" works from the Raw Markdown tab

- [ ] **Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix(gui): address issues found during e2e verification"
```

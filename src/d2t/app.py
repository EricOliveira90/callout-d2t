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
                value = st.text_input(key, value=str(default), key=f"{selected_key}_{key}")
                if value != str(default):
                    param_overrides[key] = value

    # Run button
    run_disabled = uploaded_file is None
    if st.button("Generate Report", disabled=run_disabled):
        tmp_path = None
        try:
            # Write uploaded file to temp file so parse_csv can read it
            suffix = "." + (uploaded_file.name.rsplit(".", 1)[-1] if "." in uploaded_file.name else "csv")
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded_file.getbuffer())
                tmp_path = Path(tmp.name)

            with st.spinner("Generating report..."):
                output = generate_report(
                    recipe_name=selected_key,
                    main_file_path=tmp_path,
                    param_overrides=param_overrides,
                )

            # Display raw output in a styled text area
            st.markdown(
                '<div style="font-family: Arial, sans-serif; background: #f8f9fa; '
                'border: 1px solid #ddd; border-radius: 4px; padding: 1em; '
                'white-space: pre-wrap; line-height: 1.6;">'
                + output.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                + "</div>",
                unsafe_allow_html=True,
            )

            # Offer download as Markdown file
            md_filename = f"{selected_key}_output.md"
            st.download_button(
                label="📥 Download as Markdown",
                data=output,
                file_name=md_filename,
                mime="text/markdown",
            )

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
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

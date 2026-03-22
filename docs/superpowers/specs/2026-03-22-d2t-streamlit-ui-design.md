# D2T Streamlit UI Design

## Problem

The d2t CLI tool generates WBR reports from CSV/TSV data, but colleagues who aren't comfortable with the command line can't use it. We need a simple GUI that lets 5-15 non-technical users upload a file, pick a recipe, and get their report.

## Solution

A Streamlit web app that wraps the existing d2t pipeline. Users double-click a `.bat` file, a browser tab opens with a form, and they can generate reports without touching the terminal.

## User Flow

1. **Pick a recipe** — dropdown with the 4 recipes (WBR GMS Callout, WBR GMS Detailed, Product Selection Callout, Product Selection Detailed). Recipe description shown below.
2. **Upload the main file** — drag-and-drop area accepting `.csv` / `.tsv`.
3. **Optional parameters** — expandable "Advanced Parameters" section with all recipe params pre-filled with defaults. Most users never open this.
4. **Run** — click "Generate Report". Disabled until a file is uploaded.
5. **Output** — rendered output shown in two tabs: "Preview" (rendered Markdown) and "Raw Markdown" (copyable code block). A "Copy to clipboard" button.

The lookup file (`PF-to-GL.csv`) uses its default path from config — users never see it.

## Architecture

The Streamlit app is a thin wrapper around the existing d2t pipeline. No logic duplication.

```
app.py (Streamlit UI)
  |
  +-- recipe.py   -> load_recipe() to get params, inputs, descriptions
  +-- input.py    -> read_csv() to parse uploaded file
  +-- strategy.py -> load_strategy() + strategy.process()
  +-- engine.py   -> render() to produce output
```

### Data flow

1. User selects recipe -> `load_recipe(name)` returns strategy name, template name, default params, input definitions
2. User uploads file -> saved to a temp file, path passed to `read_csv()`
3. User clicks Run -> `load_strategy(strategy_name)` instantiated with merged params (defaults + user overrides)
4. Strategy's `process(inputs)` produces context dict
5. `render(template_name, context, filters, globals)` produces output string
6. Output displayed in Streamlit

### Error handling

- File parsing errors -> `st.error("Could not read file. Make sure it's a valid CSV or TSV.")`
- Strategy/template errors -> show d2t's error message in `st.error()`, with a "Show details" expander for the full traceback
- No raw stack traces by default

## UI Layout

Top to bottom, single centered column:

1. **Title** — "D2T Report Generator", one-line subtitle
2. **Recipe selector** — `st.selectbox` with human-readable names derived from recipe keys (e.g., `wbr_gms_callout` -> "WBR GMS Callout"). Description text below.
3. **File uploader** — `st.file_uploader` accepting `.csv, .tsv`. Label shows input description from config.
4. **Advanced Parameters** — `st.expander("Advanced Parameters", expanded=False)`. Each param as a `st.text_input` pre-filled with default. Only shown if recipe has params.
5. **Run button** — `st.button("Generate Report")`. Disabled until file is uploaded.
6. **Output area** (after run):
   - Two tabs: "Preview" (`st.markdown`) and "Raw Markdown" (`st.code`)
   - "Copy to clipboard" button

## File Changes

### New files

- `src/d2t/app.py` — the Streamlit app (single file, entire UI)
- `run_d2t.bat` — launcher: `streamlit run src/d2t/app.py`
- `setup.bat` — one-time install: `pip install -e ".[gui]"`

### Modified files

- `pyproject.toml` — add `streamlit` as an optional dependency under a `[gui]` extra

### No changes to

- `cli.py`, `recipe.py`, `strategy.py`, `engine.py`, `input.py`, `filters.py`, `errors.py`
- Any strategy or template files
- `config.yaml`

## Packaging & Distribution

1. Zip the project folder (or share via network drive)
2. One-time setup: colleagues run `setup.bat` (requires Python pre-installed)
3. Day-to-day: double-click `run_d2t.bat` -> browser opens

## Recipe Display Names

Derived from recipe keys by replacing underscores with spaces and title-casing, then applying known abbreviations (WBR, GMS). Each recipe's `description` field from config.yaml is shown as helper text below the dropdown.

## Dependencies

- `streamlit` added as optional: `pip install -e ".[gui]"`
- The CLI continues to work without streamlit installed
- No other new dependencies

## Scope Exclusions

- No authentication or multi-user support
- No file output / save-to-disk from the UI (copy-paste workflow only)
- No custom strategy/template directory selection in the UI (use CLI for that)
- No auto-update mechanism

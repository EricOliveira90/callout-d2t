# d2t — Data-to-Text CLI Tool Design Spec

## Overview

`d2t` is a Python CLI tool that transforms structured CSV data into natural language text using Jinja2 templates. It implements a three-stage pipeline: input parsing, analysis (strategy), and text rendering (template). The tool is designed primarily for AI agent consumption via subprocess invocation.

## Architecture

### Pipeline

```
CLI parses args
  → recipe.py resolves recipe (if --recipe)
  → input.py reads & parses named CSV files → dict[str, list[dict]]
  → strategy.py loads strategy module, calls process(inputs) → dict
  → engine.py builds Jinja Environment, renders template with context → str
  → stdout
```

### Package Structure

```
d2t/
├── pyproject.toml              # Package metadata, click entry point
├── src/
│   └── d2t/
│       ├── __init__.py
│       ├── cli.py              # Click CLI (d2t run, d2t list)
│       ├── input.py            # CSV parsing, named input resolution
│       ├── strategy.py         # Strategy base class + dynamic loader
│       ├── engine.py           # Jinja Environment setup + rendering
│       ├── recipe.py           # Recipe loading from config.yaml
│       ├── errors.py           # Custom exceptions + exit code mapping
│       ├── filters.py          # Common Jinja filters (currency, pct, date)
│       ├── strategies/         # Built-in analysis strategies (package data)
│       │   ├── __init__.py
│       │   ├── sum_by_group.py
│       │   └── ...
│       ├── templates/          # Built-in Jinja .j2 templates (package data)
│       │   ├── _macros/
│       │   │   ├── formatting.j2
│       │   │   └── tables.j2
│       │   └── monthly_report.j2
│       └── config.yaml         # Built-in recipes (package data)
└── tests/
    ├── fixtures/               # Test CSV files and strategy/template pairs
    ├── test_input.py
    ├── test_strategy.py
    ├── test_engine.py
    ├── test_recipe.py
    ├── test_errors.py
    └── test_cli.py
```

- `src/` layout prevents accidental imports from the project root.
- `strategies/`, `templates/`, and `config.yaml` live **inside** `src/d2t/` as package data so they are resolvable at runtime after `pip install` via `importlib.resources`.
- `filters.py` holds common Jinja filters shared across all strategies.

## CLI Interface

### `d2t run` — Execute a pipeline

```bash
# Via recipe (primary usage)
d2t run --recipe monthly_revenue --input main=sales.csv

# Via explicit strategy + template
d2t run --strategy sum_by_group --template monthly_report \
        --input main=sales.csv --input baseline=targets.csv \
        --param group_col=region --param value_col=revenue

# With external strategy/template directories
d2t run --recipe monthly_revenue --input main=sales.csv \
        --strategy-dir ./my_strategies --template-dir ./my_templates
```

**Flags:**

| Flag | Short | Repeatable | Description |
|------|-------|------------|-------------|
| `--recipe` | `-r` | No | Named recipe from config.yaml |
| `--strategy` | `-s` | No | Strategy module name (required if no recipe) |
| `--template` | `-t` | No | Template name without `.j2` (required if no recipe) |
| `--input` | `-i` | Yes | `name=path` format. At least one required. Default name is `main` if no `=` present. |
| `--param` | `-p` | Yes | `key=value` strategy parameters |
| `--strategy-dir` | — | Yes | Additional strategy search paths |
| `--template-dir` | — | Yes | Additional template search paths |
| `--dry-run` | — | No | Validate inputs, strategy, template without rendering |
| `--verbose` | — | No | Print full tracebacks on error |
| `--version` | — | No | Print version and exit (sourced from `pyproject.toml`) |

### `d2t list` — Discover available components

```bash
d2t list strategies              # Name + docstring for each strategy
d2t list templates               # Available .j2 files
d2t list recipes                 # Recipe name + strategy + template + expected inputs
d2t list strategies --strategy-dir ./custom  # Include custom dirs
d2t list recipes --json          # JSON output for agent consumption
```

The `d2t list` subcommands support a `--json` flag that outputs structured JSON to stdout. This follows the CLI Guidelines requirement for machine-readable output and is critical for agent discovery. The `d2t run` command does **not** have a `--json` flag — its stdout is always the rendered text.

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General/unexpected error |
| 2 | Usage error (bad flags, missing required args) |
| 10 | Input file not found |
| 11 | Input parse error (malformed CSV) |
| 20 | Unknown strategy |
| 21 | Strategy processing error |
| 30 | Unknown template |
| 31 | Template rendering error (e.g., undefined variable) |
| 40 | Unknown recipe |
| 41 | Recipe config parse error |

## Core Components

### `input.py` — Named Input Resolution

- Parses `name=path` pairs from `--input` flags.
- If no `=` is present, defaults to key `"main"`.
- Use `--input main=-` or `--input -` to read from stdin (Unix convention).
- Each CSV is read and auto-coerced (numeric strings to int/float).
- Returns `dict[str, list[dict]]` — keys are input names, values are parsed rows.

### `strategy.py` — Strategy Base Class & Loader

```python
class AnalysisStrategy(ABC):
    @abstractmethod
    def process(self, inputs: dict[str, list[dict]]) -> dict:
        """Takes named inputs, returns template context dict."""
        ...

    def get_filters(self) -> dict[str, Callable]:
        return {}

    def get_globals(self) -> dict[str, Any]:
        return {}
```

**Example strategy accessing named inputs:**

```python
class CompareRevenue(AnalysisStrategy):
    def process(self, inputs):
        current = inputs["main"]           # required input
        baseline = inputs.get("baseline", [])  # optional input
        # ... analysis logic ...
        return {"current_total": ..., "baseline_total": ..., "delta": ...}
```

**Loader behavior:**
- Scans `--strategy-dir` paths (left to right), then built-in `strategies/` directory.
- First match wins — custom strategies can shadow built-in ones.
- For built-in strategies: uses standard `importlib.import_module` (they are inside the `d2t` package).
- For external `--strategy-dir` strategies: uses `importlib.util.spec_from_file_location` to load `.py` files by path. External strategies must `from d2t.strategy import AnalysisStrategy` (i.e., `d2t` must be installed or on `PYTHONPATH`).
- Finds the first `AnalysisStrategy` subclass in the named module.
- Instantiates with `--param` key-value pairs as constructor kwargs. All `--param` values arrive as strings — the loader performs basic coercion (int, float, bool) before passing to the constructor. Strategies that need complex types should parse from strings in `__init__`.

### `engine.py` — Jinja Environment & Rendering

- Builds `Environment` with `ChoiceLoader` over `--template-dir` paths (first) + built-in templates (fallback).
- Built-in template path resolved via `importlib.resources` (works after `pip install`).
- Configuration: `StrictUndefined`, `trim_blocks=True`, `lstrip_blocks=True`, `keep_trailing_newline=True`.
- Registers: common filters from `filters.py`, strategy filters from `get_filters()`, strategy globals from `get_globals()`, `now` timestamp.
- Loads template by name (appends `.j2`), calls `render(**context)`, returns string.

### `recipe.py` — Recipe Loading

Reads `config.yaml` (located inside the `d2t` package, resolved via `importlib.resources`) and resolves strategy, template, default params, and expected inputs.

```yaml
recipes:
  monthly_revenue:
    description: "Monthly revenue breakdown by region"
    strategy: sum_by_group
    template: monthly_report
    inputs:
      - name: main
        description: "Sales data with region and revenue columns"
        required: true
      - name: baseline
        description: "Prior period for comparison"
        required: false
    params:
      group_col: region
      value_col: revenue
```

- `inputs` documents what the recipe expects. Surfaced via `d2t list recipes`.
- `params` are defaults. CLI `--param` flags override them.
- `description` is shown in `d2t list recipes` for agent discovery.

### `errors.py` — Exceptions & Exit Codes

Each exception class maps to a specific exit code. The CLI's top-level handler catches them, prints a consistent message to stderr, and exits with the mapped code.

**Error format:** `d2t: error[CODE]: message`

```
d2t: error[10]: Input file not found: sales.csv
d2t: error[20]: Unknown strategy: 'foo'. Available: sum_by_group, time_series
d2t: error[31]: Template rendering error in monthly_report.j2: 'total' is undefined
```

When strategy or template is not found, the error lists available options so agents can self-correct.

### `filters.py` — Common Jinja Filters

Shared filters available to all templates regardless of strategy:

- `dateformat(value: datetime, fmt: str = "%Y-%m-%d") -> str` — format datetime values
- `as_currency(value: float, symbol: str = "$") -> str` — format as currency string (e.g., `"$1,234.56"`)
- `as_pct(value: float, decimals: int = 1) -> str` — format as percentage (e.g., `"12.3%"`)
- `jsonify(value: Any, **kwargs) -> str` — serialize to JSON string via `json.dumps`

Strategies can register additional filters via `get_filters()`.

## Strategy Extensibility

Custom strategies require:
1. A `.py` file in a directory pointed to by `--strategy-dir`
2. A class that subclasses `AnalysisStrategy`
3. The standard `process(inputs) → dict` contract

Same for templates: custom `.j2` files in a `--template-dir` directory. Searched first via `ChoiceLoader`, built-in as fallback.

No plugin registry, no entry points, no config needed.

**Security note:** `--strategy-dir` causes the CLI to import and execute arbitrary Python code from the specified directory. This is equivalent to running a Python script — the security boundary is the calling user's permissions.

## Agent Experience Design

- **Discovery:** `d2t list` subcommands let agents explore capabilities. `--help` at every level. `--json` on `d2t list` for machine-readable output.
- **Validation:** `--dry-run` validates everything without rendering. Exit 0 means "this would succeed."
- **Actionable errors:** Missing components list what IS available.
- **No interactive prompts.** Every failure is a non-zero exit + stderr message.
- **Stdout is sacred.** For `d2t run`, only the rendered text. All diagnostics go to stderr.
- **Idempotency:** `d2t run` is a pure function with no side effects — inherently idempotent and safe to retry.
- **File output:** Handled by shell redirection (`d2t run ... > output.txt`). No `--output` flag.

## Testing Strategy

### Unit Tests

- `test_input.py` — CSV parsing, numeric coercion, named input resolution, malformed CSV, missing files
- `test_strategy.py` — Loader discovery, constructor params, `--strategy-dir` search order, shadowing
- `test_engine.py` — Environment setup, filter registration, StrictUndefined, rendering
- `test_recipe.py` — Recipe loading, missing recipe, param override merging, input validation
- `test_errors.py` — Exception-to-exit-code mapping, error message formatting

### Integration Tests

- `test_cli.py` — End-to-end via Click's `CliRunner`: recipe invocation, explicit strategy+template, `--dry-run`, `list` subcommands, exit codes for each failure mode

### Test Data

- `tests/fixtures/` with small CSV files and simple strategy/template pairs.
- No mocks for Jinja or file system — test directly.

## Dependencies

- **click** — CLI framework (subcommands, help generation)
- **jinja2** — Template engine
- **pyyaml** — Recipe config parsing
- **pytest** — Testing (dev dependency)

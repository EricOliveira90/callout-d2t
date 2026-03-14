## The Idea (input prompt for this report)

Consider the following logic flow:
1. A SQL query extracts data in a specific format from the database
2. An analysis strategy (i.e. code) process the data in a specific format and translate it into another processed format
3. A "Writing" strategy (i.e. code) takes the processed data in a known format and transforms it into statements following a specific template, putting the right data in the right places

Write a detailed approach of how can I use Jinja (https://github.com/pallets/jinja) to implement a CLI tool for step 2 and 3. The tool would receive the output of the SQL query as input, and based on a matching analysis strategy (step 2) and output template (step 3), it would fill the template and the right data and output the text. I could then have a library of pre-made analysis and templates storage for quick usage. Analyze the repo to better understand it.

## The Core Insight

Jinja is not just an HTML template engine — it's a general-purpose text templating system. Its `Environment` + `FileSystemLoader` architecture is built exactly for what you're describing: loading reusable templates from disk, injecting processed data, and rendering arbitrary text output. The key Jinja features that map to your pipeline are:

- **`FileSystemLoader`** — loads templates from a directory on disk, enabling your "library of pre-made templates"
- **Custom filters** (`env.filters`) — pure Python functions registered on the environment, perfect for your "analysis strategies" that transform raw SQL data into processed data
- **Custom globals** (`env.globals`) — Python functions/values available inside every template
- **`Environment.get_template()` + `template.render()`** — the load-and-fill cycle that drives the whole pipeline
- **Macros and template inheritance** — DRY primitives for composing complex output templates from smaller reusable pieces

The design philosophy here is: **analysis strategies are Python modules that register Jinja filters/globals, and writing strategies are Jinja template files on disk**. The CLI wires them together.

---

## Architecture

```
┌─────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  SQL Output  │─────▸│ Analysis Strategy │─────▸│  Output Template  │─────▸ Text
│  (CSV/JSON)  │      │  (Python module)  │      │  (Jinja .j2 file) │
└─────────────┘      └──────────────────┘      └──────────────────┘
       stdin               Step 2                     Step 3
    or --input         registered as              loaded by
                     filters/globals           FileSystemLoader
```

### Directory Layout

```
my-report-tool/
├── cli.py                    # CLI entry point
├── strategies/               # Analysis strategies (Step 2)
│   ├── __init__.py
│   ├── base.py               # Abstract base class for strategies
│   ├── sum_by_group.py       # Example: group + aggregate
│   ├── time_series.py        # Example: resample time data
│   └── pivot_table.py        # Example: pivot rows into columns
├── templates/                # Output templates (Step 3)
│   ├── _macros/              # Shared macros (reusable fragments)
│   │   ├── tables.j2         # Table formatting macros
│   │   └── formatting.j2     # Number/date formatting macros
│   ├── monthly_report.j2     # Full report template
│   ├── slack_summary.j2      # Slack-friendly summary
│   ├── csv_export.j2         # Re-export as transformed CSV
│   └── email_digest.j2       # Email body template
├── config.yaml               # Optional: named "recipes" (strategy + template pairs)
└── pyproject.toml
```

The `strategies/` directory holds Python modules — each one is an analysis strategy. The `templates/` directory holds Jinja `.j2` files — each one is a writing strategy. The CLI's job is to: read input → run a strategy → render a template.

---

## Step-by-Step Design

### 1. Input Parsing (reading SQL output)

The CLI accepts SQL query output as either CSV (the most universal `\copy` / `psql` output format) or JSON. It normalizes everything into a Python list of dicts — the universal intermediate format that both strategies and templates can work with.

```python
import csv
import json
import sys
import io

def parse_input(source, fmt="csv"):
    """Parse SQL output into list[dict]. The universal intermediate format."""
    raw = source.read() if hasattr(source, 'read') else source

    if fmt == "json":
        data = json.loads(raw)
        # Handle both [{...}, ...] and {"rows": [{...}, ...]}
        return data if isinstance(data, list) else data["rows"]

    # CSV is the default — works with psql \copy, DBeaver export, etc.
    reader = csv.DictReader(io.StringIO(raw))
    rows = []
    for row in reader:
        # Auto-coerce numeric strings to numbers
        coerced = {}
        for k, v in row.items():
            try:
                coerced[k] = int(v)
            except (ValueError, TypeError):
                try:
                    coerced[k] = float(v)
                except (ValueError, TypeError):
                    coerced[k] = v
        rows.append(coerced)
    return rows
```

### 2. Analysis Strategies (Step 2 — Python modules)

Each strategy is a Python module that exposes a single contract: a `process(rows)` function that takes the raw list-of-dicts and returns a processed data structure, plus an optional `filters()` function that returns custom Jinja filters.

**The base contract:**

```python
# strategies/base.py
from abc import ABC, abstractmethod

class AnalysisStrategy(ABC):
    """
    Base class for analysis strategies.

    A strategy does two things:
    1. process(rows) — transforms raw SQL rows into a processed data structure.
       The return value becomes the template context under the key "data".
    2. get_filters() — returns a dict of custom Jinja filters that templates
       can use for presentation-layer transformations.
    """

    @abstractmethod
    def process(self, rows: list[dict]) -> dict:
        """
        Transform raw rows into processed data.

        Args:
            rows: List of dicts from the SQL query output.

        Returns:
            A dict that will be merged into the Jinja template context.
            Convention: the top-level keys become template variables.
            Example: {"summary": {...}, "groups": [...], "totals": {...}}
        """
        ...

    def get_filters(self) -> dict:
        """
        Return custom Jinja filters this strategy provides.
        Override to add strategy-specific filters.

        Returns:
            Dict mapping filter_name -> callable.
        """
        return {}

    def get_globals(self) -> dict:
        """
        Return custom Jinja globals this strategy provides.
        Override to add strategy-specific global functions/values.
        """
        return {}
```

**Example concrete strategy:**

```python
# strategies/sum_by_group.py
from collections import defaultdict
from strategies.base import AnalysisStrategy

class SumByGroup(AnalysisStrategy):
    """
    Groups rows by a key column and sums a value column.
    Useful for: revenue by region, count by status, etc.

    Expected SQL columns: at least one grouping column + one numeric column.
    The CLI passes --params to configure which columns to use.
    """

    def __init__(self, group_col="group", value_col="value"):
        self.group_col = group_col
        self.value_col = value_col

    def process(self, rows):
        groups = defaultdict(float)
        for row in rows:
            key = row[self.group_col]
            groups[key] += float(row[self.value_col])

        sorted_groups = sorted(groups.items(), key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in sorted_groups)

        return {
            "groups": [{"name": k, "value": v, "pct": v / total * 100 if total else 0}
                       for k, v in sorted_groups],
            "total": total,
            "count": len(sorted_groups),
        }

    def get_filters(self):
        return {
            "as_currency": lambda v, symbol="$": f"{symbol}{v:,.2f}",
            "as_pct": lambda v, decimals=1: f"{v:.{decimals}f}%",
        }
```

**Why this works with Jinja:** The `process()` return value becomes the template rendering context. The `get_filters()` return value gets registered on the Jinja `Environment`. This means templates can do both `{{ data.total | as_currency }}` (using a strategy-provided filter) and `{{ data.groups | length }}` (using Jinja's built-in filters). The strategy controls the data shape; the template controls the presentation.

### 3. Output Templates (Step 3 — Jinja `.j2` files)

Templates are plain Jinja files stored in `templates/`. They receive the processed data as their context and produce the final text output. Because Jinja was designed for text generation (not just HTML), templates can produce Markdown, plain text, Slack markup, CSV, LaTeX, or anything else.

**Example template:**

```jinja
{# templates/monthly_report.j2 #}
{# Expects context from SumByGroup strategy: groups, total, count #}
{% from '_macros/formatting.j2' import hr, heading %}

{{ heading("Monthly Revenue Report") }}

Total revenue: {{ total | as_currency }}
Number of regions: {{ count }}

{{ hr() }}

{% for g in groups %}
{{ "%-20s" | format(g.name) }}  {{ g.value | as_currency }}  ({{ g.pct | as_pct }})
{% endfor %}

{{ hr() }}
Generated: {{ now | dateformat("%Y-%m-%d %H:%M") }}
```

**Shared macros file:**

```jinja
{# templates/_macros/formatting.j2 #}

{% macro heading(text, char="=") -%}
{{ text }}
{{ char * text|length }}
{%- endmacro %}

{% macro hr(char="-", width=60) -%}
{{ char * width }}
{%- endmacro %}

{% macro table(headers, rows, widths=none) -%}
{% for h in headers %}{{ "%-*s" | format(widths[loop.index0] if widths else 20, h) }}{% endfor %}
{{ "-" * (widths | sum if widths else headers|length * 20) }}
{% for row in rows %}
{% for cell in row %}{{ "%-*s" | format(widths[loop.index0] if widths else 20, cell) }}{% endfor %}
{% endfor %}
{%- endmacro %}
```

This is where Jinja's **macro system** shines. The `{% from ... import ... %}` statement lets templates pull in reusable formatting functions from shared files, exactly like Python imports. The `_macros/` directory becomes your formatting utility library.

### 4. The CLI Wiring (bringing it all together)

The CLI is the orchestrator. It uses Jinja's `Environment` and `FileSystemLoader` to wire strategies to templates.

```python
#!/usr/bin/env python3
# cli.py
"""
Usage:
    cat query_output.csv | python cli.py --strategy sum_by_group --template monthly_report
    python cli.py --input data.csv --strategy sum_by_group --template monthly_report -o report.txt
    python cli.py --recipe monthly_revenue  # uses config.yaml to resolve strategy + template

Strategy params:
    python cli.py --strategy sum_by_group --param group_col=region --param value_col=revenue ...
"""

import argparse
import sys
import importlib
import json
import datetime
from pathlib import Path

import yaml  # pip install pyyaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, ChoiceLoader

# ─── Paths ───────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
STRATEGIES   = BASE_DIR / "strategies"
TEMPLATES    = BASE_DIR / "templates"

# ─── Strategy Registry ───────────────────────────────────────────────

def load_strategy(name: str, params: dict):
    """
    Dynamically import a strategy module and instantiate its class.

    Convention: strategies/<name>.py must contain a class whose name is the
    PascalCase version of <name>. E.g., sum_by_group.py → SumByGroup.
    """
    module = importlib.import_module(f"strategies.{name}")

    # Find the strategy class (first subclass of AnalysisStrategy in the module)
    from strategies.base import AnalysisStrategy
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (isinstance(attr, type)
                and issubclass(attr, AnalysisStrategy)
                and attr is not AnalysisStrategy):
            return attr(**params)

    raise ValueError(f"No AnalysisStrategy subclass found in strategies/{name}.py")


# ─── Jinja Environment Setup ────────────────────────────────────────

def build_environment(strategy, extra_template_dirs=None):
    """
    Build a Jinja Environment wired with:
    - FileSystemLoader pointed at the templates/ directory
    - Custom filters from the strategy
    - Common global functions (date formatting, etc.)
    """
    search_paths = [str(TEMPLATES)]
    if extra_template_dirs:
        search_paths.extend(extra_template_dirs)

    env = Environment(
        loader=FileSystemLoader(search_paths),
        # StrictUndefined makes missing variables an error, not silent empty string.
        # This is critical for data pipelines — you want to know if a template
        # references a variable the strategy didn't provide.
        undefined=StrictUndefined,
        # trim_blocks + lstrip_blocks clean up whitespace around {% %} tags,
        # so the output doesn't have blank lines from control flow statements.
        trim_blocks=True,
        lstrip_blocks=True,
        # Keep trailing newline so output files end with newline (Unix convention)
        keep_trailing_newline=True,
    )

    # Register strategy-specific filters
    env.filters.update(strategy.get_filters())

    # Register strategy-specific globals
    env.globals.update(strategy.get_globals())

    # Register common globals available to ALL templates
    env.globals["now"] = datetime.datetime.now()

    # Register common filters available to ALL templates
    env.filters["dateformat"] = lambda v, fmt="%Y-%m-%d": v.strftime(fmt)
    env.filters["jsonify"] = lambda v, **kw: json.dumps(v, default=str, **kw)

    return env


# ─── Main Pipeline ──────────────────────────────────────────────────

def run_pipeline(input_source, strategy_name, template_name,
                 strategy_params=None, input_format="csv",
                 extra_template_dirs=None):
    """
    The full pipeline:
    1. Parse input (SQL output → list[dict])
    2. Run analysis strategy (list[dict] → processed dict)
    3. Render Jinja template (processed dict → text)
    """
    strategy_params = strategy_params or {}

    # Step 1: Parse
    rows = parse_input(input_source, fmt=input_format)

    # Step 2: Analyze
    strategy = load_strategy(strategy_name, strategy_params)
    context = strategy.process(rows)

    # Step 3: Render
    env = build_environment(strategy, extra_template_dirs)
    template = env.get_template(f"{template_name}.j2")
    return template.render(**context)


# ─── CLI ─────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Transform SQL output through analysis strategies and Jinja templates."
    )
    # Input
    p.add_argument("--input", "-i", type=argparse.FileType("r"), default=sys.stdin,
                   help="Input file (default: stdin)")
    p.add_argument("--format", "-f", choices=["csv", "json"], default="csv",
                   help="Input format (default: csv)")

    # Pipeline selection
    p.add_argument("--strategy", "-s", help="Analysis strategy name (module in strategies/)")
    p.add_argument("--template", "-t", help="Output template name (file in templates/, without .j2)")
    p.add_argument("--recipe", "-r", help="Named recipe from config.yaml (overrides --strategy and --template)")

    # Strategy parameters
    p.add_argument("--param", "-p", action="append", default=[],
                   help="Strategy parameter as key=value (repeatable)")

    # Output
    p.add_argument("--output", "-o", type=argparse.FileType("w"), default=sys.stdout,
                   help="Output file (default: stdout)")

    # Extra paths
    p.add_argument("--template-dir", action="append", default=[],
                   help="Additional template search directory (repeatable)")

    return p.parse_args()


def load_recipe(recipe_name):
    """Load a named recipe from config.yaml."""
    config_path = BASE_DIR / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"config.yaml not found at {config_path}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    recipes = config.get("recipes", {})
    if recipe_name not in recipes:
        available = ", ".join(recipes.keys()) or "(none)"
        raise KeyError(f"Recipe '{recipe_name}' not found. Available: {available}")

    return recipes[recipe_name]


def main():
    args = parse_args()

    # Resolve recipe if given
    if args.recipe:
        recipe = load_recipe(args.recipe)
        strategy_name = recipe["strategy"]
        template_name = recipe["template"]
        strategy_params = recipe.get("params", {})
    else:
        if not args.strategy or not args.template:
            print("Error: --strategy and --template are required (or use --recipe)", file=sys.stderr)
            sys.exit(1)
        strategy_name = args.strategy
        template_name = args.template
        strategy_params = dict(kv.split("=", 1) for kv in args.param)

    output = run_pipeline(
        input_source=args.input.read(),
        strategy_name=strategy_name,
        template_name=template_name,
        strategy_params=strategy_params,
        input_format=args.format,
        extra_template_dirs=args.template_dir,
    )

    args.output.write(output)


if __name__ == "__main__":
    main()
```

### 5. The Recipe Config (named strategy+template pairs)

```yaml
# config.yaml
# Named recipes for one-command usage.
# Each recipe binds a strategy, its params, and an output template.

recipes:
  monthly_revenue:
    strategy: sum_by_group
    template: monthly_report
    params:
      group_col: region
      value_col: revenue

  daily_slack_digest:
    strategy: time_series
    template: slack_summary
    params:
      date_col: created_at
      value_col: signups
      freq: daily

  quarterly_pivot:
    strategy: pivot_table
    template: email_digest
    params:
      index_col: product
      columns_col: quarter
      value_col: revenue
```

This lets users run `cat data.csv | python cli.py --recipe monthly_revenue` and get the full pipeline without remembering strategy names or parameters.

---

## How Jinja's Architecture Maps to Your Requirements

### Requirement → Jinja Feature

| Your requirement | Jinja mechanism | Why it fits |
|---|---|---|
| "Library of pre-made templates" | `FileSystemLoader` pointed at `templates/` | Templates are plain files on disk. Add a new `.j2` file and it's immediately available. The loader auto-discovers them. |
| "Putting the right data in the right places" | `template.render(**context)` | The processed dict from your strategy becomes the template's namespace. `{{ total }}` resolves to `context["total"]`. |
| "Analysis strategies that process data" | Custom filters via `env.filters` + strategy `process()` | Heavy transformation happens in Python before rendering. Lighter formatting (currency, percentages) happens as Jinja filters during rendering. |
| "Matching strategy to template" | Recipe config or CLI flags | The CLI resolves which strategy + template pair to use. The strategy's `process()` output shape must match what the template expects — this is the "contract" between them. |
| "Known format between steps" | Strategy return type convention | Strategies always return a dict. Templates always receive that dict as their context. The dict's shape IS the interface contract. |

### Why Separate `process()` From Filters

This is a deliberate architectural split:

- **`process()`** does the heavy analytical work — grouping, aggregation, joins, statistical calculations, pivoting. It runs once and produces the data structure the template needs. This is Step 2.
- **Filters** do lightweight, presentation-layer transformations — formatting a number as currency, truncating a string, formatting a date. They run per-value inside the template. This is the bridge between Step 2 and Step 3.
- **Templates** control layout and structure — what goes where, how sections are arranged, what gets included/excluded conditionally. This is Step 3.

This separation means you can reuse the same analysis strategy with different templates (monthly report vs. Slack summary vs. CSV export) and reuse the same template with different strategies (as long as they produce the same context shape).

---

## Key Jinja Features You Should Leverage

### `StrictUndefined` for safety

By default, Jinja renders undefined variables as empty strings — dangerous for data pipelines because you silently get missing data in your output. `StrictUndefined` raises an error immediately if a template references a variable the strategy didn't provide. This turns template-strategy contract mismatches into loud failures.

### `trim_blocks` + `lstrip_blocks` for clean output

Without these, every `{% if %}` and `{% for %}` block leaves blank lines in the output. With both enabled, control flow tags don't affect whitespace in the rendered output. Essential for producing clean plaintext/Markdown.

### Template inheritance for report families

If you have multiple templates that share a structure (header, footer, metadata section), use Jinja's `{% extends %}` / `{% block %}` system:

```jinja
{# templates/_base_report.j2 #}
{% block header %}Report generated: {{ now | dateformat }}{% endblock %}

{% block body %}{% endblock %}

{% block footer %}---
End of report.{% endblock %}
```

```jinja
{# templates/monthly_report.j2 #}
{% extends "_base_report.j2" %}

{% block body %}
Total revenue: {{ total | as_currency }}
... (report-specific content)
{% endblock %}
```

### Macros for reusable formatting fragments

Use `{% macro %}` for snippets you reuse across templates but that aren't full templates themselves — like formatting a key-value pair, a table row, or a section divider:

```jinja
{# templates/_macros/tables.j2 #}
{% macro kv_line(label, value, width=30) -%}
{{ "%-*s" | format(width, label + ":") }} {{ value }}
{%- endmacro %}
```

Then in any template: `{% from '_macros/tables.j2' import kv_line %}` and use `{{ kv_line("Revenue", total | as_currency) }}`.

### `ChoiceLoader` for user overrides

If you want users to be able to override built-in templates without modifying the library:

```python
loader = ChoiceLoader([
    FileSystemLoader(user_template_dir),    # checked first
    FileSystemLoader(builtin_template_dir), # fallback
])
```

This is how you'd support per-project template customization on top of your shared library.

---

## Adding a New Strategy+Template Pair (the workflow)

1. **Write the SQL query** and verify its output format (columns and types).
2. **Create a strategy module** in `strategies/`:
   - Subclass `AnalysisStrategy`.
   - Implement `process(rows)` that takes the raw rows and returns the processed data dict.
   - Optionally add `get_filters()` for presentation-layer helpers.
3. **Create a template** in `templates/`:
   - Reference the keys from the strategy's return dict.
   - Use built-in and strategy-provided filters.
   - Import shared macros as needed.
4. **Optionally add a recipe** to `config.yaml` for one-command usage.
5. **Run it:**
   ```bash
   psql -c "SELECT region, revenue FROM sales" --csv | python cli.py --recipe monthly_revenue
   ```

---

## Extension Points

### Multi-format output from one strategy

A single strategy can feed multiple templates. The strategy defines the data shape; templates define presentation:

```bash
# Same data, three different outputs
cat data.csv | python cli.py -s sum_by_group -t monthly_report -o report.txt
cat data.csv | python cli.py -s sum_by_group -t slack_summary -o slack.md
cat data.csv | python cli.py -s sum_by_group -t csv_export -o processed.csv
```

### Chaining strategies (pipeline composition)

If you need multi-step analysis, strategies can compose:

```python
# strategies/enriched_summary.py
class EnrichedSummary(AnalysisStrategy):
    def process(self, rows):
        # First pass: group
        from strategies.sum_by_group import SumByGroup
        grouped = SumByGroup(group_col="region", value_col="revenue").process(rows)

        # Second pass: enrich with rankings
        for i, g in enumerate(grouped["groups"], 1):
            g["rank"] = i

        return grouped
```

### Integration with `do` extension for in-template side effects

Jinja's `do` extension (`jinja2.ext.do`) allows executing Python expressions inside templates without printing output. Useful for accumulating state during iteration:

```python
env = Environment(extensions=["jinja2.ext.do"], ...)
```

```jinja
{% set ns = namespace(running_total=0) %}
{% for g in groups %}
{% do ns.update(running_total=ns.running_total + g.value) %}
{{ g.name }}: {{ g.value | as_currency }} (cumulative: {{ ns.running_total | as_currency }})
{% endfor %}
```

### Listing available strategies and templates

```bash
python cli.py --list-strategies   # scans strategies/ for AnalysisStrategy subclasses
python cli.py --list-templates    # calls env.list_templates() — built into Jinja's FileSystemLoader
python cli.py --list-recipes      # reads config.yaml
```

`FileSystemLoader.list_templates()` is a built-in Jinja method that returns all template filenames the loader can find — no custom code needed.

---

## Summary

The entire tool is built on three Jinja primitives:

1. **`FileSystemLoader`** manages your template library as files on disk.
2. **`env.filters` / `env.globals`** injects your analysis strategy's processing and formatting into the template rendering context.
3. **`template.render(**context)`** fills the template with processed data and produces the final text.

Everything else — the CLI argument parsing, the strategy class hierarchy, the recipe config — is just plumbing to wire these three primitives together in a user-friendly way. Jinja handles the hard parts: template loading, caching, inheritance, macros, whitespace control, undefined variable safety, and the actual rendering engine.

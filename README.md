# d2t — Data-to-Text CLI

A Python CLI tool that transforms CSV data into natural language text using [Jinja2](https://github.com/pallets/jinja) templates. Built for AI agent workflows.

## How It Works

```
CSV file → Analysis Strategy (Python) → Jinja2 Template → Text output
```

1. **Input:** Read one or more named CSV files
2. **Analyze:** A strategy module processes the raw data into a structured context
3. **Render:** A Jinja2 template turns that context into prose, reports, summaries, or any text format

## Quick Start

```bash
pip install -e .

# Run a pre-configured recipe
d2t run --recipe monthly_revenue --input main=sales.csv

# Or specify strategy + template explicitly
d2t run -s sum_by_group -t monthly_report -i main=sales.csv -p group_col=region -p value_col=revenue
```

## Key Concepts

- **Strategies** — Python modules that transform raw CSV rows into a processed data dict. Each strategy defines its own analysis logic (grouping, aggregation, comparison, etc.).
- **Templates** — Jinja2 `.j2` files that render the processed data into text. One strategy can feed many templates (report, Slack summary, CSV export).
- **Recipes** — Pre-configured strategy + template + parameter bundles in `config.yaml` for one-flag invocation.

## Discovery

```bash
d2t list strategies    # Available analysis strategies
d2t list templates     # Available output templates
d2t list recipes       # Pre-configured recipes
d2t list recipes --json  # Machine-readable output
```

## Extensibility

Add custom strategies and templates without modifying the package:

```bash
d2t run -s my_analysis -t my_report -i main=data.csv \
    --strategy-dir ./my_strategies --template-dir ./my_templates
```

A custom strategy is a Python file with a class that subclasses `AnalysisStrategy` and implements `process(inputs) -> dict`. A custom template is a `.j2` file.

## Design

- Rendered text goes to **stdout**; errors and diagnostics go to **stderr**
- Granular exit codes for programmatic error handling
- `--dry-run` validates the full pipeline without rendering
- `--help` at every command level
- No interactive prompts

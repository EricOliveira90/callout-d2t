# src/d2t/cli.py
"""Click CLI for d2t."""

import json
import sys
from pathlib import Path

import click

from d2t import __version__
from d2t.errors import D2tError, format_error
from d2t.input import parse_named_inputs, parse_csv
from d2t.strategy import load_strategy, list_strategies
from d2t.engine import render
from d2t.recipe import load_recipe, list_recipes


@click.group()
@click.version_option(version=__version__, prog_name="d2t")
@click.option("--verbose", is_flag=True, default=False, help="Print full tracebacks on error.")
@click.pass_context
def cli(ctx, verbose):
    """d2t — Transform CSV data into text via Jinja2 templates."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.option("--recipe", "-r", default=None, help="Named recipe from config.yaml.")
@click.option("--strategy", "-s", default=None, help="Analysis strategy name.")
@click.option("--template", "-t", default=None, help="Template name (without .j2).")
@click.option("--input", "-i", "inputs", multiple=True, required=True, help="Input as name=path (repeatable).")
@click.option("--param", "-p", "params", multiple=True, help="Strategy param as key=value (repeatable).")
@click.option("--strategy-dir", "strategy_dirs", multiple=True, help="Additional strategy search directory.")
@click.option("--template-dir", "template_dirs", multiple=True, help="Additional template search directory.")
@click.option("--output", "-o", "output_path", default=None, type=click.Path(), help="Write output to file (e.g. report.md).")
@click.option("--dry-run", is_flag=True, default=False, help="Validate without rendering.")
@click.pass_context
def run(ctx, recipe, strategy, template, inputs, params, strategy_dirs, template_dirs, output_path, dry_run):
    """Execute a data-to-text pipeline.

    Examples:

        d2t run --recipe wbr_gms_callout --input main=sales.csv
    """
    verbose = ctx.obj["verbose"]

    try:
        # Resolve recipe or explicit strategy+template
        if recipe:
            recipe_data = load_recipe(recipe)
            strategy_name = recipe_data["strategy"]
            template_name = recipe_data["template"]
            strategy_params = dict(recipe_data["params"])
            # Pass relations to strategy when defined
            if recipe_data.get("relations"):
                strategy_params["relations"] = recipe_data["relations"]
        else:
            if not strategy or not template:
                raise click.UsageError("--strategy and --template are required (or use --recipe).")
            strategy_name = strategy
            template_name = template
            strategy_params = {}

        # Merge CLI params (override recipe defaults)
        for p in params:
            key, sep, value = p.partition("=")
            if not sep or not key:
                raise click.UsageError(
                    f"Invalid --param format: '{p}'. Expected key=value."
                )
            strategy_params[key] = value

        # Parse inputs
        parsed_inputs = parse_named_inputs(list(inputs))

        # Auto-load default inputs from recipe when not provided by user
        if recipe:
            for inp_def in recipe_data.get("inputs", []):
                name = inp_def["name"]
                default = inp_def.get("default_path")
                if default and name not in parsed_inputs:
                    parsed_inputs[name] = parse_csv(Path(default))

        # Load strategy
        strat_dirs = [Path(d) for d in strategy_dirs]
        strat = load_strategy(strategy_name, strategy_params, strat_dirs)

        if dry_run:
            # Validate template exists by building env and getting template
            tmpl_dirs = [Path(d) for d in template_dirs]
            from d2t.engine import build_environment
            from jinja2 import TemplateNotFound
            env = build_environment(
                template_dirs=tmpl_dirs,
                strategy_filters=strat.get_filters(),
                strategy_globals=strat.get_globals(),
            )
            try:
                env.get_template(f"{template_name}.j2")
            except TemplateNotFound:
                from d2t.errors import UnknownTemplateError
                available = sorted(env.loader.list_templates()) if env.loader else []
                public = [t for t in available if not t.startswith("_")]
                raise UnknownTemplateError(f"{template_name}.j2", available=public)
            click.echo("Dry run: OK", err=True)
            return

        # Run pipeline
        try:
            context = strat.process(parsed_inputs)
        except D2tError:
            raise  # Re-raise d2t errors as-is (e.g., StrategyProcessingError)
        except Exception as e:
            from d2t.errors import StrategyProcessingError
            raise StrategyProcessingError(str(e)) from e
        tmpl_dirs = [Path(d) for d in template_dirs]
        output = render(
            template_name=template_name,
            context=context,
            template_dirs=tmpl_dirs,
            strategy_filters=strat.get_filters(),
            strategy_globals=strat.get_globals(),
        )

        if output_path:
            Path(output_path).write_text(output, encoding="utf-8")
            click.echo(f"Output written to {output_path}", err=True)
        else:
            click.echo(output, nl=False)

    except click.UsageError:
        raise  # Let click handle usage errors (exit code 2)
    except D2tError as e:
        click.echo(format_error(e), err=True)
        if verbose:
            import traceback
            traceback.print_exc(file=sys.stderr)
        sys.exit(e.exit_code)
    except Exception as e:
        click.echo(f"d2t: error[1]: {e}", err=True)
        if verbose:
            import traceback
            traceback.print_exc(file=sys.stderr)
        sys.exit(1)


@cli.group(name="list")
def list_cmd():
    """Discover available strategies, templates, and recipes."""
    pass


@list_cmd.command()
@click.option("--strategy-dir", "strategy_dirs", multiple=True, help="Additional strategy search directory.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def strategies(strategy_dirs, as_json):
    """List available analysis strategies."""
    dirs = [Path(d) for d in strategy_dirs]
    items = list_strategies(dirs)

    if as_json:
        click.echo(json.dumps(items, indent=2))
    else:
        if not items:
            click.echo("No strategies found.", err=True)
            return
        for item in items:
            desc = item["description"] or "(no description)"
            click.echo(f"  {item['name']:<20s} {desc}")


@list_cmd.command()
@click.option("--template-dir", "template_dirs", multiple=True, help="Additional template search directory.")
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def templates(template_dirs, as_json):
    """List available output templates."""
    from d2t.engine import build_environment

    dirs = [Path(d) for d in template_dirs]
    env = build_environment(template_dirs=dirs)
    items = sorted(env.loader.list_templates()) if env.loader else []
    # Filter out internal macros
    public = [t for t in items if not t.startswith("_")]

    if as_json:
        click.echo(json.dumps(public, indent=2))
    else:
        if not public:
            click.echo("No templates found.", err=True)
            return
        for name in public:
            click.echo(f"  {name}")


@list_cmd.command()
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON.")
def recipes(as_json):
    """List available recipes from config.yaml."""
    try:
        items = list_recipes()
    except Exception as e:
        click.echo(f"d2t: error: {e}", err=True)
        return

    if as_json:
        click.echo(json.dumps(items, indent=2))
    else:
        if not items:
            click.echo("No recipes found.", err=True)
            return
        for item in items:
            desc = item.get("description", "")
            inputs_str = ", ".join(
                inp["name"] + ("*" if inp.get("required") else "")
                for inp in item.get("inputs", [])
            )
            click.echo(
                f"  {item['name']:<20s} [{item['strategy']}] -> [{item['template']}]"
                f"  inputs: {inputs_str or '(none)'}"
            )
            if desc:
                click.echo(f"  {'':20s} {desc}")

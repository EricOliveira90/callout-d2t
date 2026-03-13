# tests/test_cli.py
import json
from pathlib import Path

from click.testing import CliRunner

from d2t.cli import cli

FIXTURES = Path(__file__).parent / "fixtures"


class TestRunCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_run_with_explicit_strategy_and_template(self):
        result = self.runner.invoke(cli, [
            "run",
            "-s", "echo",
            "-t", "echo_report",
            "-i", f"main={FIXTURES / 'sales.csv'}",
            "--strategy-dir", str(FIXTURES / "strategies"),
            "--template-dir", str(FIXTURES / "templates"),
        ])
        assert result.exit_code == 0
        assert "Count: 4" in result.output

    def test_run_with_params(self):
        result = self.runner.invoke(cli, [
            "run",
            "-s", "echo",
            "-t", "echo_report",
            "-i", f"main={FIXTURES / 'sales.csv'}",
            "-p", "prefix=hello",
            "--strategy-dir", str(FIXTURES / "strategies"),
            "--template-dir", str(FIXTURES / "templates"),
        ])
        assert result.exit_code == 0

    def test_run_missing_strategy_and_template(self):
        result = self.runner.invoke(cli, [
            "run",
            "-i", f"main={FIXTURES / 'sales.csv'}",
        ])
        assert result.exit_code != 0

    def test_run_unknown_strategy(self):
        result = self.runner.invoke(cli, [
            "run",
            "-s", "nonexistent",
            "-t", "simple",
            "-i", f"main={FIXTURES / 'sales.csv'}",
            "--template-dir", str(FIXTURES / "templates"),
        ])
        assert result.exit_code == 20

    def test_run_unknown_template(self):
        result = self.runner.invoke(cli, [
            "run",
            "-s", "echo",
            "-t", "nonexistent",
            "-i", f"main={FIXTURES / 'sales.csv'}",
            "--strategy-dir", str(FIXTURES / "strategies"),
        ])
        assert result.exit_code == 30

    def test_run_missing_input_file(self):
        result = self.runner.invoke(cli, [
            "run",
            "-s", "echo",
            "-t", "simple",
            "-i", "main=does_not_exist.csv",
            "--strategy-dir", str(FIXTURES / "strategies"),
            "--template-dir", str(FIXTURES / "templates"),
        ])
        assert result.exit_code == 10

    def test_run_dry_run(self):
        result = self.runner.invoke(cli, [
            "run",
            "-s", "echo",
            "-t", "echo_report",
            "-i", f"main={FIXTURES / 'sales.csv'}",
            "--strategy-dir", str(FIXTURES / "strategies"),
            "--template-dir", str(FIXTURES / "templates"),
            "--dry-run",
        ])
        assert result.exit_code == 0
        assert "Dry run: OK" in result.output  # goes to stderr, but CliRunner mixes them

    def test_run_with_builtin_recipe(self):
        result = self.runner.invoke(cli, [
            "run",
            "-r", "monthly_revenue",
            "-i", f"main={FIXTURES / 'sales.csv'}",
        ])
        assert result.exit_code == 0
        assert "Monthly Report" in result.output

    def test_run_strategy_processing_error(self):
        result = self.runner.invoke(cli, [
            "run",
            "-s", "failing",
            "-t", "echo_report",
            "-i", f"main={FIXTURES / 'sales.csv'}",
            "--strategy-dir", str(FIXTURES / "strategies"),
            "--template-dir", str(FIXTURES / "templates"),
        ])
        assert result.exit_code == 21


class TestListCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_list_strategies(self):
        result = self.runner.invoke(cli, [
            "list", "strategies",
            "--strategy-dir", str(FIXTURES / "strategies"),
        ])
        assert result.exit_code == 0
        assert "echo" in result.output

    def test_list_strategies_json(self):
        result = self.runner.invoke(cli, [
            "list", "strategies",
            "--strategy-dir", str(FIXTURES / "strategies"),
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        names = [s["name"] for s in data]
        assert "echo" in names

    def test_list_templates(self):
        result = self.runner.invoke(cli, [
            "list", "templates",
            "--template-dir", str(FIXTURES / "templates"),
        ])
        assert result.exit_code == 0
        assert "simple.j2" in result.output

    def test_list_templates_json(self):
        result = self.runner.invoke(cli, [
            "list", "templates",
            "--template-dir", str(FIXTURES / "templates"),
            "--json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "simple.j2" in data

    def test_list_recipes(self):
        result = self.runner.invoke(cli, ["list", "recipes"])
        assert result.exit_code == 0
        assert "monthly_revenue" in result.output

    def test_list_recipes_json(self):
        result = self.runner.invoke(cli, ["list", "recipes", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        names = [r["name"] for r in data]
        assert "monthly_revenue" in names


class TestVersionFlag:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

# tests/test_input.py
import os
from pathlib import Path

import pytest

from d2t.input import parse_named_inputs, parse_csv
from d2t.errors import InputNotFoundError, InputParseError

FIXTURES = Path(__file__).parent / "fixtures"


class TestParseCsv:
    def test_parses_csv_to_list_of_dicts(self):
        rows = parse_csv(FIXTURES / "sales.csv")
        assert len(rows) == 4
        assert rows[0]["region"] == "North"

    def test_auto_coerces_integers(self):
        rows = parse_csv(FIXTURES / "sales.csv")
        assert rows[0]["revenue"] == 150000
        assert isinstance(rows[0]["revenue"], int)

    def test_auto_coerces_floats(self):
        rows = parse_csv(FIXTURES / "sales.csv")
        assert rows[0]["rate"] == 12.5
        assert isinstance(rows[0]["rate"], float)

    def test_raises_on_missing_file(self):
        with pytest.raises(InputNotFoundError):
            parse_csv(Path("nonexistent.csv"))

    def test_raises_on_empty_file(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("")
        with pytest.raises(InputParseError):
            parse_csv(bad)

    def test_raises_on_malformed_csv(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("a,b\n1,2,3\n4\n")
        with pytest.raises(InputParseError):
            parse_csv(bad)


class TestParseNamedInputs:
    def test_single_input_without_name_defaults_to_main(self):
        raw = [str(FIXTURES / "sales.csv")]
        result = parse_named_inputs(raw)
        assert "main" in result
        assert len(result["main"]) == 4

    def test_single_input_with_name(self):
        raw = [f"sales={FIXTURES / 'sales.csv'}"]
        result = parse_named_inputs(raw)
        assert "sales" in result

    def test_multiple_named_inputs(self):
        raw = [
            f"main={FIXTURES / 'sales.csv'}",
            f"baseline={FIXTURES / 'targets.csv'}",
        ]
        result = parse_named_inputs(raw)
        assert "main" in result
        assert "baseline" in result
        assert len(result["main"]) == 4
        assert len(result["baseline"]) == 4

    def test_stdin_input(self, monkeypatch):
        csv_content = "name,value\nfoo,1\nbar,2\n"
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(csv_content))
        raw = ["-"]
        result = parse_named_inputs(raw)
        assert "main" in result
        assert len(result["main"]) == 2

    def test_named_stdin_input(self, monkeypatch):
        csv_content = "name,value\nfoo,1\n"
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(csv_content))
        raw = ["data=-"]
        result = parse_named_inputs(raw)
        assert "data" in result

    def test_duplicate_input_name_last_wins(self):
        raw = [
            f"main={FIXTURES / 'sales.csv'}",
            f"main={FIXTURES / 'targets.csv'}",
        ]
        result = parse_named_inputs(raw)
        assert "main" in result
        # Last value wins — targets.csv has 'target' column, not 'units'
        assert "target" in result["main"][0]

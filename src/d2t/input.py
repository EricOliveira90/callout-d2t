# src/d2t/input.py
"""CSV parsing and named input resolution."""

import csv
import io
import sys
from pathlib import Path

from d2t.errors import InputNotFoundError, InputParseError


def _coerce_value(value: str):
    """Try to coerce a string to int, then float, else return as-is.

    Strings with leading zeros (e.g., zip codes like '07302') are preserved
    as strings to avoid silent data loss.
    """
    stripped = value.strip()
    # Don't coerce strings with leading zeros (e.g., zip codes, IDs)
    if len(stripped) > 1 and stripped.startswith("0") and not stripped.startswith("0."):
        return stripped
    try:
        return int(stripped)
    except (ValueError, TypeError):
        try:
            return float(stripped)
        except (ValueError, TypeError):
            return value


def parse_csv(path: Path) -> list[dict]:
    """Parse a CSV or TSV file into a list of dicts with auto-coerced values.

    The delimiter is chosen automatically based on file extension:
    ``.tsv`` files use tab, everything else uses comma.
    """
    if not path.exists():
        raise InputNotFoundError(str(path))

    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    text = path.read_text(encoding="utf-8")
    return _parse_csv_text(text, source=str(path), delimiter=delimiter)


def _parse_csv_text(
    text: str, source: str = "<stdin>", delimiter: str = ","
) -> list[dict]:
    """Parse CSV/TSV text into a list of dicts."""
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise InputParseError(f"No columns found in {source}")

    expected_cols = len(reader.fieldnames)
    rows = []
    for line_num, row in enumerate(reader, start=2):
        if None in row or len(row) != expected_cols:
            raise InputParseError(
                f"Malformed row at line {line_num} in {source}: "
                f"expected {expected_cols} columns"
            )
        rows.append({k: _coerce_value(v) for k, v in row.items()})

    if not rows:
        raise InputParseError(f"No data rows found in {source}")

    return rows


def parse_named_inputs(raw_inputs: list[str]) -> dict[str, list[dict]]:
    """
    Parse --input flag values into named datasets.

    Formats:
      --input sales.csv          → name="main", path="sales.csv"
      --input main=sales.csv     → name="main", path="sales.csv"
      --input -                  → name="main", read from stdin
      --input data=-             → name="data", read from stdin
    """
    result = {}
    for raw in raw_inputs:
        if "=" in raw:
            name, path_str = raw.split("=", 1)
        else:
            name, path_str = "main", raw

        if path_str == "-":
            text = sys.stdin.read()
            result[name] = _parse_csv_text(text)
        else:
            result[name] = parse_csv(Path(path_str))

    return result

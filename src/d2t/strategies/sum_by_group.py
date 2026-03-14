# src/d2t/strategies/sum_by_group.py
"""Groups rows by a key column and sums a value column.

Useful for: revenue by region, count by status, etc.
Expects at least one grouping column and one numeric column in the input.
"""

import math
from collections import defaultdict

from d2t.errors import StrategyProcessingError
from d2t.strategy import AnalysisStrategy


class SumByGroup(AnalysisStrategy):
    """Groups rows by a key column and sums a value column."""

    def __init__(self, group_col="group", value_col="value"):
        self.group_col = group_col
        self.value_col = value_col

    def process(self, inputs):
        # Validate that the required 'main' input is present
        if "main" not in inputs:
            available = ", ".join(inputs.keys()) or "(none)"
            raise StrategyProcessingError(
                f"Strategy requires an input named 'main', but got: {available}. "
                f"Use --input main=<file>."
            )

        rows = inputs["main"]

        # Validate that required columns exist
        if rows:
            first = rows[0]
            for col_name, col_label in [
                (self.group_col, "group_col"),
                (self.value_col, "value_col"),
            ]:
                if col_name not in first:
                    raise StrategyProcessingError(
                        f"Column '{col_name}' ({col_label}) not found. "
                        f"Available columns: {', '.join(first.keys())}"
                    )

        groups = defaultdict(float)
        for row in rows:
            key = row[self.group_col]
            try:
                groups[key] += float(row[self.value_col])
            except (ValueError, TypeError) as e:
                raise StrategyProcessingError(
                    f"Non-numeric value in column '{self.value_col}': "
                    f"{row[self.value_col]!r}"
                ) from e

        sorted_groups = sorted(groups.items(), key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in sorted_groups)

        return {
            "groups": [
                {
                    "name": k,
                    "value": v,
                    "pct": (
                        v / total * 100
                        if not math.isclose(total, 0.0, abs_tol=1e-9)
                        else 0.0
                    ),
                }
                for k, v in sorted_groups
            ],
            "total": total,
            "count": len(sorted_groups),
        }

    def get_filters(self):
        return {}

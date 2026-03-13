# src/d2t/strategies/sum_by_group.py
"""Groups rows by a key column and sums a value column.

Useful for: revenue by region, count by status, etc.
Expects at least one grouping column and one numeric column in the input.
"""

from collections import defaultdict

from d2t.strategy import AnalysisStrategy


class SumByGroup(AnalysisStrategy):
    """Groups rows by a key column and sums a value column."""

    def __init__(self, group_col="group", value_col="value"):
        self.group_col = group_col
        self.value_col = value_col

    def process(self, inputs):
        rows = inputs["main"]
        groups = defaultdict(float)
        for row in rows:
            key = row[self.group_col]
            groups[key] += float(row[self.value_col])

        sorted_groups = sorted(groups.items(), key=lambda x: x[1], reverse=True)
        total = sum(v for _, v in sorted_groups)

        return {
            "groups": [
                {
                    "name": k,
                    "value": v,
                    "pct": v / total * 100 if total else 0,
                }
                for k, v in sorted_groups
            ],
            "total": total,
            "count": len(sorted_groups),
        }

    def get_filters(self):
        return {}

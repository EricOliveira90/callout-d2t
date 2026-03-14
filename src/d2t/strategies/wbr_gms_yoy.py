"""Computes YoY GMS performance by product group for a WBR callout.

Expects a CSV with year, product_group, seller_name, channel, and
net_ordered_gms_usd columns. Computes total GMS for the latest year,
compares to the previous year, and identifies top contributors and
offenders per category with their top seller drivers.
"""

from collections import defaultdict

from d2t.errors import StrategyProcessingError
from d2t.strategy import AnalysisStrategy


def _compact_currency(value, symbol="$", signed=True):
    """Format a number with K/MM/B suffix for compact display."""
    abs_val = abs(value)

    if abs_val >= 1_000_000_000:
        formatted = f"{abs_val / 1_000_000_000:.2f}B"
    elif abs_val >= 1_000_000:
        formatted = f"{abs_val / 1_000_000:.2f}MM"
    elif abs_val >= 1_000:
        formatted = f"{abs_val / 1_000:.1f}K"
    else:
        formatted = f"{abs_val:.2f}"

    if signed:
        sign = "-" if value < 0 else "+"
        return f"{sign}{symbol}{formatted}"
    return f"{symbol}{formatted}"


def _signed_pct(value):
    """Format a percentage with explicit +/- sign."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


class WbrGmsYoy(AnalysisStrategy):
    """Computes YoY GMS performance by product group for a WBR callout."""

    def __init__(
        self,
        year_col="year",
        product_group_col="product_group",
        seller_name_col="seller_name",
        channel_col="channel",
        gms_col="net_ordered_gms_usd",
        period_label="Period",
    ):
        self.year_col = year_col
        self.product_group_col = product_group_col
        self.seller_name_col = seller_name_col
        self.channel_col = channel_col
        self.gms_col = gms_col
        self.period_label = period_label

    def process(self, inputs):
        if "main" not in inputs:
            available = ", ".join(inputs.keys()) or "(none)"
            raise StrategyProcessingError(
                f"Strategy requires an input named 'main', but got: {available}. "
                f"Use --input main=<file>."
            )

        rows = inputs["main"]

        if not rows:
            raise StrategyProcessingError("Input 'main' is empty — no rows to process.")

        # Validate columns
        first = rows[0]
        required_cols = [
            (self.year_col, "year_col"),
            (self.product_group_col, "product_group_col"),
            (self.seller_name_col, "seller_name_col"),
            (self.channel_col, "channel_col"),
            (self.gms_col, "gms_col"),
        ]
        for col_name, col_label in required_cols:
            if col_name not in first:
                raise StrategyProcessingError(
                    f"Column '{col_name}' ({col_label}) not found. "
                    f"Available columns: {', '.join(first.keys())}"
                )

        # --- Step 1: Identify latest and previous year ---
        years = set()
        for row in rows:
            try:
                years.add(int(row[self.year_col]))
            except (ValueError, TypeError) as e:
                raise StrategyProcessingError(
                    f"Non-integer value in year column '{self.year_col}': {row[self.year_col]!r}"
                ) from e

        sorted_years = sorted(years, reverse=True)
        if len(sorted_years) < 2:
            raise StrategyProcessingError(
                f"Need at least 2 distinct years for YoY comparison, "
                f"but found: {sorted_years}"
            )

        latest_year = sorted_years[0]
        previous_year = sorted_years[1]

        # --- Step 2: Split rows by year ---
        latest_rows = []
        prev_rows = []
        for row in rows:
            y = int(row[self.year_col])
            if y == latest_year:
                latest_rows.append(row)
            elif y == previous_year:
                prev_rows.append(row)

        # --- Step 3: Compute totals ---
        def safe_gms(row):
            try:
                return float(row[self.gms_col])
            except (ValueError, TypeError) as e:
                raise StrategyProcessingError(
                    f"Non-numeric value in GMS column '{self.gms_col}': {row[self.gms_col]!r}"
                ) from e

        total_gms = sum(safe_gms(r) for r in latest_rows)
        prev_total_gms = sum(safe_gms(r) for r in prev_rows)
        yoy_delta = total_gms - prev_total_gms
        yoy_pct = (yoy_delta / prev_total_gms * 100) if prev_total_gms != 0 else 0.0

        # --- Step 4: Group by product_group per year ---
        def group_by_category(row_list):
            """Returns {product_group: total_gms}"""
            groups = defaultdict(float)
            for row in row_list:
                groups[row[self.product_group_col]] += safe_gms(row)
            return groups

        latest_by_cat = group_by_category(latest_rows)
        prev_by_cat = group_by_category(prev_rows)

        all_categories = set(latest_by_cat.keys()) | set(prev_by_cat.keys())

        # --- Step 5: For each category, find top seller by YoY delta ---
        def group_by_seller(row_list, category):
            """Returns {(seller_name, channel): total_gms} for a given category."""
            sellers = defaultdict(lambda: {"gms": 0.0, "channel": ""})
            for row in row_list:
                if row[self.product_group_col] == category:
                    key = row[self.seller_name_col]
                    sellers[key]["gms"] += safe_gms(row)
                    sellers[key]["channel"] = row[self.channel_col]
            return sellers

        categories = []
        for cat in all_categories:
            cat_gms = latest_by_cat.get(cat, 0.0)
            cat_prev_gms = prev_by_cat.get(cat, 0.0)
            cat_yoy_delta = cat_gms - cat_prev_gms
            cat_yoy_pct = (cat_yoy_delta / cat_prev_gms * 100) if cat_prev_gms != 0 else 0.0

            # Find top seller driver
            latest_sellers = group_by_seller(latest_rows, cat)
            prev_sellers = group_by_seller(prev_rows, cat)
            all_sellers = set(latest_sellers.keys()) | set(prev_sellers.keys())

            top_seller_name = ""
            top_seller_channel = ""
            top_seller_yoy_delta = 0.0

            if all_sellers:
                seller_deltas = []
                for seller in all_sellers:
                    s_gms = latest_sellers.get(seller, {"gms": 0.0, "channel": ""})["gms"]
                    s_prev = prev_sellers.get(seller, {"gms": 0.0, "channel": ""})["gms"]
                    s_channel = (
                        latest_sellers.get(seller, {"channel": ""})["channel"]
                        or prev_sellers.get(seller, {"channel": ""})["channel"]
                    )
                    seller_deltas.append({
                        "seller_name": seller,
                        "channel": s_channel,
                        "yoy_delta": s_gms - s_prev,
                    })

                # Pick seller with largest absolute delta in the same direction as category
                if cat_yoy_delta >= 0:
                    # For positive categories, pick seller with largest positive delta
                    sorted_sellers = sorted(seller_deltas, key=lambda s: s["yoy_delta"], reverse=True)
                else:
                    # For negative categories, pick seller with largest negative delta
                    sorted_sellers = sorted(seller_deltas, key=lambda s: s["yoy_delta"])

                top = sorted_sellers[0]
                top_seller_name = top["seller_name"]
                top_seller_channel = top["channel"]
                top_seller_yoy_delta = top["yoy_delta"]

            categories.append({
                "product_group": cat,
                "gms": cat_gms,
                "prev_gms": cat_prev_gms,
                "yoy_delta": cat_yoy_delta,
                "yoy_pct": cat_yoy_pct,
                "top_seller_name": top_seller_name,
                "top_seller_channel": top_seller_channel,
                "top_seller_yoy_delta": top_seller_yoy_delta,
                "is_positive": cat_yoy_delta >= 0,
            })

        # Sort by absolute delta descending
        categories.sort(key=lambda c: abs(c["yoy_delta"]), reverse=True)

        positive_categories = [c for c in categories if c["is_positive"]]
        negative_categories = [c for c in categories if not c["is_positive"]]

        return {
            "period_label": self.period_label,
            "latest_year": latest_year,
            "previous_year": previous_year,
            "total_gms": total_gms,
            "prev_total_gms": prev_total_gms,
            "yoy_delta": yoy_delta,
            "yoy_pct": yoy_pct,
            "categories": categories,
            "positive_categories": positive_categories,
            "negative_categories": negative_categories,
        }

    def get_filters(self):
        return {
            "compact_currency": _compact_currency,
            "signed_pct": _signed_pct,
        }

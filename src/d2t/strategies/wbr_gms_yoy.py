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
        program_col="program",
        gms_col="net_ordered_gms_usd",
        period_label="Period",
        lookup_group_col="gl_product_group",
        lookup_desc_col="gl_category_description",
        relations=None,
    ):
        self.year_col = year_col
        self.product_group_col = product_group_col
        self.seller_name_col = seller_name_col
        self.channel_col = channel_col
        self.program_col = program_col
        self.gms_col = gms_col
        self.period_label = period_label
        self.lookup_group_col = lookup_group_col
        self.lookup_desc_col = lookup_desc_col
        self.relations = relations or []

    def _find_relation(self, main_key):
        """Find the first relation matching a given main_key column name."""
        for rel in self.relations:
            if rel.get("main_key") == main_key:
                return rel
        return None

    def _build_lookup(self, inputs):
        """Build a product-group-id → description mapping from the lookup input.

        When a ``relation`` is configured for the ``product_group_col``, the
        relation's ``lookup_key`` and ``group_by`` columns are used instead of
        the legacy ``lookup_group_col`` / ``lookup_desc_col`` params.  This
        supports 1:n relationships where many product-group IDs map to the
        same description and the output should group by ``group_by``.

        Returns an empty dict when no ``lookup`` input is provided.
        """
        # Determine which lookup input, key column, and description column to use
        relation = self._find_relation(self.product_group_col)
        if relation:
            lookup_input_name = relation.get("lookup_input", "lookup")
            lookup_key_col = relation["lookup_key"]
            lookup_desc_col = relation["group_by"]
        else:
            lookup_input_name = "lookup"
            lookup_key_col = self.lookup_group_col
            lookup_desc_col = self.lookup_desc_col

        if lookup_input_name not in inputs:
            return {}

        lookup_rows = inputs[lookup_input_name]
        mapping = {}
        for row in lookup_rows:
            key = self._normalize_product_group(row.get(lookup_key_col))
            desc = row.get(lookup_desc_col, str(key))
            mapping[key] = desc
        return mapping

    def _normalize_product_group(self, raw_value):
        """Normalize a product group value to int when possible for consistent lookup."""
        try:
            return int(float(str(raw_value)))
        except (ValueError, TypeError):
            return raw_value

    def _resolve_product_group(self, raw_value, lookup):
        """Return the human-readable description for a product group, or the raw value."""
        key = self._normalize_product_group(raw_value)
        if lookup and key in lookup:
            return lookup[key]
        return str(key)

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

        # Build optional product-group lookup
        pg_lookup = self._build_lookup(inputs)

        # Normalize product_group values in every row so grouping is consistent
        for row in rows:
            row[self.product_group_col] = self._resolve_product_group(
                row[self.product_group_col], pg_lookup
            )

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

        # Check if program column exists in data
        has_program_col = self.program_col in first

        # --- Step 5: For each category, find top seller by YoY delta ---
        def group_by_seller(row_list, category):
            """Returns {seller_name: {gms, channel, program}} for a given category."""
            sellers = defaultdict(lambda: {"gms": 0.0, "channel": "", "program": ""})
            for row in row_list:
                if row[self.product_group_col] == category:
                    key = row[self.seller_name_col]
                    sellers[key]["gms"] += safe_gms(row)
                    sellers[key]["channel"] = row[self.channel_col]
                    if has_program_col:
                        sellers[key]["program"] = row[self.program_col]
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
            top_seller_program = ""
            top_seller_yoy_delta = 0.0

            if all_sellers:
                seller_deltas = []
                for seller in all_sellers:
                    s_default = {"gms": 0.0, "channel": "", "program": ""}
                    s_gms = latest_sellers.get(seller, s_default)["gms"]
                    s_prev = prev_sellers.get(seller, s_default)["gms"]
                    s_channel = (
                        latest_sellers.get(seller, s_default)["channel"]
                        or prev_sellers.get(seller, s_default)["channel"]
                    )
                    s_program = (
                        latest_sellers.get(seller, s_default)["program"]
                        or prev_sellers.get(seller, s_default)["program"]
                    )
                    seller_deltas.append({
                        "seller_name": seller,
                        "channel": s_channel,
                        "program": s_program,
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
                top_seller_program = top["program"]
                top_seller_yoy_delta = top["yoy_delta"]

            categories.append({
                "product_group": cat,
                "gms": cat_gms,
                "prev_gms": cat_prev_gms,
                "yoy_delta": cat_yoy_delta,
                "yoy_pct": cat_yoy_pct,
                "top_seller_name": top_seller_name,
                "top_seller_channel": top_seller_channel,
                "top_seller_program": top_seller_program,
                "top_seller_yoy_delta": top_seller_yoy_delta,
                "is_positive": cat_yoy_delta >= 0,
            })

        # Sort by absolute delta descending
        categories.sort(key=lambda c: abs(c["yoy_delta"]), reverse=True)

        positive_categories = [c for c in categories if c["is_positive"]]
        negative_categories = [c for c in categories if not c["is_positive"]]

        # --- Step 6: Detailed seller breakdown per category ---
        for cat_entry in categories:
            cat = cat_entry["product_group"]
            latest_sellers = group_by_seller(latest_rows, cat)
            prev_sellers_map = group_by_seller(prev_rows, cat)
            all_cat_sellers = set(latest_sellers.keys()) | set(prev_sellers_map.keys())

            sellers_detail = []
            for seller in all_cat_sellers:
                s_default = {"gms": 0.0, "channel": "", "program": ""}
                s_gms = latest_sellers.get(seller, s_default)["gms"]
                s_prev = prev_sellers_map.get(seller, s_default)["gms"]
                s_channel = (
                    latest_sellers.get(seller, s_default)["channel"]
                    or prev_sellers_map.get(seller, s_default)["channel"]
                )
                s_program = (
                    latest_sellers.get(seller, s_default)["program"]
                    or prev_sellers_map.get(seller, s_default)["program"]
                )
                s_delta = s_gms - s_prev
                s_pct = (s_delta / s_prev * 100) if s_prev != 0 else 0.0
                sellers_detail.append({
                    "seller_name": seller,
                    "channel": s_channel,
                    "program": s_program,
                    "gms": s_gms,
                    "prev_gms": s_prev,
                    "yoy_delta": s_delta,
                    "yoy_pct": s_pct,
                })
            sellers_detail.sort(key=lambda s: abs(s["yoy_delta"]), reverse=True)

            # Limit to top 20 and bottom 20 sellers by YoY delta
            positive_sellers = [s for s in sellers_detail if s["yoy_delta"] >= 0]
            negative_sellers = [s for s in sellers_detail if s["yoy_delta"] < 0]
            # Sort each group by delta magnitude descending
            positive_sellers.sort(key=lambda s: s["yoy_delta"], reverse=True)
            negative_sellers.sort(key=lambda s: s["yoy_delta"])  # most negative first

            top_n = 20
            top_sellers = positive_sellers[:top_n]
            bottom_sellers = negative_sellers[:top_n]

            cat_entry["sellers"] = sellers_detail
            cat_entry["top_sellers"] = top_sellers
            cat_entry["bottom_sellers"] = bottom_sellers
            cat_entry["total_seller_count"] = len(sellers_detail)
            cat_entry["sellers_truncated"] = len(sellers_detail) > (top_n * 2)

        # --- Step 7: Channel-level aggregation ---
        def group_by_channel(row_list):
            """Returns {channel: total_gms}"""
            channels = defaultdict(float)
            for row in row_list:
                channels[row[self.channel_col]] += safe_gms(row)
            return channels

        latest_by_channel = group_by_channel(latest_rows)
        prev_by_channel = group_by_channel(prev_rows)
        all_channel_keys = set(latest_by_channel.keys()) | set(prev_by_channel.keys())

        channels = []
        for ch in all_channel_keys:
            ch_gms = latest_by_channel.get(ch, 0.0)
            ch_prev = prev_by_channel.get(ch, 0.0)
            ch_delta = ch_gms - ch_prev
            ch_pct = (ch_delta / ch_prev * 100) if ch_prev != 0 else 0.0
            channels.append({
                "channel": ch,
                "gms": ch_gms,
                "prev_gms": ch_prev,
                "yoy_delta": ch_delta,
                "yoy_pct": ch_pct,
            })
        channels.sort(key=lambda c: abs(c["yoy_delta"]), reverse=True)

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
            "channels": channels,
        }

    def get_filters(self):
        return {
            "compact_currency": _compact_currency,
            "signed_pct": _signed_pct,
        }

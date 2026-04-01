"""Computes YoY GMS performance by product group for a WBR callout.

Expects a CSV with year, product_group, seller_name, channel, and
net_ordered_gms_usd columns. Computes total GMS for the latest year,
compares to the previous year, and identifies top contributors and
offenders per category with their top seller drivers.

When a ``goals`` input and ``start_date``/``end_date`` params are provided,
the strategy also computes vs-goal metrics and uses goal delta (instead of
YoY delta) to rank categories as positive/negative contributors.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from d2t.errors import StrategyProcessingError
from d2t.strategy import AnalysisStrategy

# Month names for period label
_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


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


def _parse_date(value):
    """Parse a YYYY-MM-DD string into a date object."""
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError) as e:
        raise StrategyProcessingError(
            f"Invalid date format: {value!r}. Expected YYYY-MM-DD."
        ) from e


def _sunday_week_number(d):
    """Return the 1-based week number where weeks run Sunday–Saturday.

    The week is identified by the Saturday that ends it.  WK1 is the week
    whose Saturday falls in the first 7 days that include Jan 1.  This means
    WK1 may start on a Sunday in the previous year (e.g. 2025-12-28 for
    year 2026 when Jan 1 is a Thursday).

    Algorithm: find the Saturday of the week containing *d*, then count how
    many weeks that Saturday is from the first Saturday >= Jan 1 of that
    Saturday's year.
    """
    # Saturday of the week containing d (weeks run Sun–Sat)
    # d.weekday(): Mon=0 … Sun=6.  Saturday=5.
    days_to_sat = (5 - d.weekday()) % 7
    sat = d + timedelta(days=days_to_sat)

    # The year is determined by the Saturday
    year = sat.year
    jan1 = date(year, 1, 1)

    # First Saturday on or after Jan 1
    first_sat_offset = (5 - jan1.weekday()) % 7
    first_sat = jan1 + timedelta(days=first_sat_offset)

    # Week number = 1 + number of full weeks between first_sat and sat
    return 1 + (sat - first_sat).days // 7


def _compute_period_label(start, end):
    """Compute a human-readable period label from start/end dates.

    Rules (checked in order):
    - Single week (Sun–Sat, 7 days): ``WK13``
    - Full calendar month: ``March``
    - Full quarter: ``Q2``
    - YTD from Jan 1 to end of a week (Saturday): ``WK13 YTD``
    - Fallback: date range string
    """
    days = (end - start).days + 1

    # Single week: starts on Sunday, ends on Saturday, exactly 7 days
    if days == 7 and start.weekday() == 6 and end.weekday() == 5:
        wk = _sunday_week_number(end)
        return f"WK{wk}"

    # Full calendar month: 1st to last day of month
    if start.day == 1:
        import calendar
        _, last_day = calendar.monthrange(start.year, start.month)
        if end == date(start.year, start.month, last_day):
            return _MONTH_NAMES[start.month]

    # Full quarter
    quarter_starts = {1: date(start.year, 1, 1), 2: date(start.year, 4, 1),
                      3: date(start.year, 7, 1), 4: date(start.year, 10, 1)}
    for q, q_start in quarter_starts.items():
        import calendar
        q_end_month = q_start.month + 2
        _, q_last_day = calendar.monthrange(q_start.year, q_end_month)
        q_end = date(q_start.year, q_end_month, q_last_day)
        if start == q_start and end == q_end:
            return f"Q{q}"

    # YTD: starts Jan 1, ends on a Saturday
    if start == date(start.year, 1, 1) and end.weekday() == 5:
        wk = _sunday_week_number(end)
        return f"WK{wk} YTD"

    # Fallback
    return f"{start.strftime('%b %d')}–{end.strftime('%b %d')}"


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
        start_date=None,
        end_date=None,
        goals_activity_day_col="activity_day",
        goals_product_group_col="product_group",
        goals_gms_col="net_ordered_gms_usd",
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
        self.start_date = start_date
        self.end_date = end_date
        self.goals_activity_day_col = goals_activity_day_col
        self.goals_product_group_col = goals_product_group_col
        self.goals_gms_col = goals_gms_col

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

        # Collect the raw (normalized) numeric product_group codes before
        # resolving to descriptions — needed later for goals filtering.
        raw_pg_codes = set()
        for row in rows:
            raw_pg_codes.add(self._normalize_product_group(row[self.product_group_col]))

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

        # --- Step 8: Goals processing (when goals input + dates are provided) ---
        has_goals = "goals" in inputs and self.start_date and self.end_date
        total_goal_gms = 0.0
        goal_delta = 0.0
        goal_pct = 0.0
        goal_by_cat = {}
        period_label = self.period_label

        if has_goals:
            start = _parse_date(self.start_date)
            end = _parse_date(self.end_date)

            # Compute period label from dates
            period_label = _compute_period_label(start, end)

            # Parse and filter goals rows by date range and product_group
            goals_rows = inputs["goals"]
            if not goals_rows:
                raise StrategyProcessingError("Input 'goals' is empty — no rows to process.")

            # Parse activity_day in goals (handles M/D/YYYY format)
            def parse_activity_day(raw):
                """Parse activity_day which may be M/D/YYYY or YYYY-MM-DD."""
                s = str(raw).strip()
                for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(s, fmt).date()
                    except ValueError:
                        continue
                raise StrategyProcessingError(
                    f"Cannot parse activity_day: {raw!r}. "
                    f"Expected M/D/YYYY or YYYY-MM-DD."
                )

            # Filter goals by date range AND by the product_group numeric
            # codes present in the main input.  We normalise the goals'
            # product_group to an int so it can be compared with the raw
            # codes collected earlier, then resolve to the human-readable
            # description (same lookup used for the main input).
            filtered_goals = []
            for row in goals_rows:
                # Check product_group membership first (cheap)
                norm_pg = self._normalize_product_group(
                    row[self.goals_product_group_col]
                )
                if norm_pg not in raw_pg_codes:
                    continue
                # Then check date range
                day = parse_activity_day(row[self.goals_activity_day_col])
                if start <= day <= end:
                    # Resolve to description for consistent grouping
                    row[self.goals_product_group_col] = self._resolve_product_group(
                        row[self.goals_product_group_col], pg_lookup
                    )
                    filtered_goals.append(row)

            # Aggregate goal GMS by category
            goal_by_cat = defaultdict(float)
            for row in filtered_goals:
                cat = row[self.goals_product_group_col]
                try:
                    goal_by_cat[cat] += float(row[self.goals_gms_col])
                except (ValueError, TypeError) as e:
                    raise StrategyProcessingError(
                        f"Non-numeric value in goals GMS column "
                        f"'{self.goals_gms_col}': {row[self.goals_gms_col]!r}"
                    ) from e

            total_goal_gms = sum(goal_by_cat.values())
            goal_delta = total_gms - total_goal_gms
            goal_pct = (goal_delta / total_goal_gms * 100) if total_goal_gms != 0 else 0.0

            # Add goal metrics to each category
            for cat_entry in categories:
                cat = cat_entry["product_group"]
                cat_goal = goal_by_cat.get(cat, 0.0)
                cat_goal_delta = cat_entry["gms"] - cat_goal
                cat_goal_pct = (cat_goal_delta / cat_goal * 100) if cat_goal != 0 else 0.0
                cat_entry["goal_gms"] = cat_goal
                cat_entry["goal_delta"] = cat_goal_delta
                cat_entry["goal_pct"] = cat_goal_pct
                # When goals are available, positive/negative is based on goal delta
                cat_entry["is_positive"] = cat_goal_delta >= 0

            # For categories that are negative vs goal, re-pick the top
            # seller driver as the one with the largest negative YoY delta
            # (i.e. the seller dragging the category down the most).
            for cat_entry in categories:
                if not cat_entry["is_positive"]:
                    cat = cat_entry["product_group"]
                    latest_sellers = group_by_seller(latest_rows, cat)
                    prev_sellers_for_cat = group_by_seller(prev_rows, cat)
                    all_s = set(latest_sellers.keys()) | set(prev_sellers_for_cat.keys())
                    if all_s:
                        s_deltas = []
                        for seller in all_s:
                            s_def = {"gms": 0.0, "channel": "", "program": ""}
                            s_gms = latest_sellers.get(seller, s_def)["gms"]
                            s_prev = prev_sellers_for_cat.get(seller, s_def)["gms"]
                            s_ch = (
                                latest_sellers.get(seller, s_def)["channel"]
                                or prev_sellers_for_cat.get(seller, s_def)["channel"]
                            )
                            s_prog = (
                                latest_sellers.get(seller, s_def)["program"]
                                or prev_sellers_for_cat.get(seller, s_def)["program"]
                            )
                            s_deltas.append({
                                "seller_name": seller,
                                "channel": s_ch,
                                "program": s_prog,
                                "yoy_delta": s_gms - s_prev,
                            })
                        # Pick seller with largest negative YoY delta
                        s_deltas.sort(key=lambda s: s["yoy_delta"])
                        top = s_deltas[0]
                        cat_entry["top_seller_name"] = top["seller_name"]
                        cat_entry["top_seller_channel"] = top["channel"]
                        cat_entry["top_seller_program"] = top["program"]
                        cat_entry["top_seller_yoy_delta"] = top["yoy_delta"]

            # Re-sort categories by absolute goal delta (not YoY)
            categories.sort(key=lambda c: abs(c["goal_delta"]), reverse=True)
            positive_categories = [c for c in categories if c["is_positive"]]
            negative_categories = [c for c in categories if not c["is_positive"]]

            # --- Channel-level goal aggregation ---
            # Goals are at the product_group level; distribute to channels
            # using the current-year channel mix per product_group.
            # Build a mapping: (product_group, channel) → share of category GMS
            cat_channel_gms = defaultdict(lambda: defaultdict(float))
            for row in latest_rows:
                cat_channel_gms[row[self.product_group_col]][row[self.channel_col]] += safe_gms(row)

            goal_by_channel = defaultdict(float)
            for cat_name, cat_goal_val in goal_by_cat.items():
                cat_total = sum(cat_channel_gms[cat_name].values())
                if cat_total == 0:
                    continue
                for ch_name, ch_gms_val in cat_channel_gms[cat_name].items():
                    share = ch_gms_val / cat_total
                    goal_by_channel[ch_name] += cat_goal_val * share

            for ch_entry in channels:
                ch_goal = goal_by_channel.get(ch_entry["channel"], 0.0)
                ch_goal_delta = ch_entry["gms"] - ch_goal
                ch_goal_pct = (ch_goal_delta / ch_goal * 100) if ch_goal != 0 else 0.0
                ch_entry["goal_gms"] = ch_goal
                ch_entry["goal_delta"] = ch_goal_delta
                ch_entry["goal_pct"] = ch_goal_pct

            # Re-sort channels by absolute goal delta
            channels.sort(key=lambda c: abs(c["goal_delta"]), reverse=True)
        else:
            # No goals — add empty goal fields for template compatibility
            for cat_entry in categories:
                cat_entry["goal_gms"] = 0.0
                cat_entry["goal_delta"] = 0.0
                cat_entry["goal_pct"] = 0.0
            for ch_entry in channels:
                ch_entry["goal_gms"] = 0.0
                ch_entry["goal_delta"] = 0.0
                ch_entry["goal_pct"] = 0.0

        return {
            "period_label": period_label,
            "latest_year": latest_year,
            "previous_year": previous_year,
            "total_gms": total_gms,
            "prev_total_gms": prev_total_gms,
            "yoy_delta": yoy_delta,
            "yoy_pct": yoy_pct,
            "total_goal_gms": total_goal_gms,
            "goal_delta": goal_delta,
            "goal_pct": goal_pct,
            "has_goals": has_goals,
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

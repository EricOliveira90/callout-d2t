"""WoW + YoY variance analysis for Amazon Product Selection (ASIN counts) — v2.

Consumes up to four pre-aggregated inputs produced by the unified-selection SQL:

- ``main``    — one row per ``period × pf × gl × metric`` with channel
                columns (``dom, fba, sf, es, ss, ooc, mfn_ooc, narf``).
                Periods: ``CWCY``, ``LWCY``, ``LW1CY``, ``LW2CY``, ``CWLY``.
- ``sellers`` — same shape plus ``mcid`` and ``seller_name``, pre-filtered
                to the union of top-10 CWCY DOM, top-10 WoW drop, and
                top-10 WoW growth sellers per ``(metric, gl)``.
- ``churn``   — BA seller churn CSV: one row per ``pf × gl × seller`` with
                ``new_asins``, ``retained_asins``, ``churned_asins``,
                ``net_change``.  Compares CWCY vs LWCY at ASIN × seller
                grain (DOM scope).
- ``goals``   — selection goals CSV: one row per ``Metric × Ref_week ×
                date_value × PF × GL`` with channel target columns.

Analytical modules (PRD v2):
  Module 2 — BA-to-AWAS Conversion Engine
  Module 3 — Churn Annotator
  Module 4 — Channel Mix Analyzer
  Module 5 — FTAC/AWAS Ratio Tracker
  Module 6 — Goal Tracker
  Module 7 — Text Assembler (Jinja template)
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from d2t.errors import StrategyProcessingError
from d2t.strategy import AnalysisStrategy

# Metric display labels
METRIC_LABELS = {
    "ba": "BA DOM",
    "awas": "AWAS",
    "ftac": "FTAC",
}

# Period tokens — 4 CY weeks + 1 LY
CWCY = "CWCY"
LWCY = "LWCY"
LW1CY = "LW1CY"
LW2CY = "LW2CY"
CWLY = "CWLY"

# Ordered list of the 4 consecutive CY weeks (oldest → newest)
CY_WEEKS = [LW2CY, LW1CY, LWCY, CWCY]

# Month names for period label
_MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ---------------------------------------------------------------------------
# Formatting helpers (exposed as Jinja filters)
# ---------------------------------------------------------------------------

def _compact_k(value, decimals=1, signed=False):
    """Format a number with a 'k' suffix (e.g. 761600 -> '761.6k')."""
    abs_val = abs(value)
    if abs_val >= 1_000:
        formatted = f"{abs_val / 1_000:.{decimals}f}k"
    else:
        if abs_val == int(abs_val):
            formatted = f"{int(abs_val)}"
        else:
            formatted = f"{abs_val:.{decimals}f}"

    if signed:
        sign = "+" if value >= 0 else "-"
        return f"{sign}{formatted}"
    return f"-{formatted}" if value < 0 else formatted


def _signed_k(value, decimals=1):
    """compact_k with forced +/- sign."""
    return _compact_k(value, decimals=decimals, signed=True)


def _signed_pct(value):
    """Format a percentage with explicit +/- sign."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _signed_pp(value):
    """Format a percentage-point change with explicit +/- sign."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}pp"


def _wow_fmt(value, decimals=1):
    """Signed k with ' WoW' suffix."""
    return f"{_signed_k(value, decimals)} WoW"


# ---------------------------------------------------------------------------
# Period label helpers
# ---------------------------------------------------------------------------

def _parse_date(value):
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError) as e:
        raise StrategyProcessingError(
            f"Invalid date format: {value!r}. Expected YYYY-MM-DD."
        ) from e


def _sunday_week_number(d):
    """1-based WK# for weeks running Sun-Sat, identified by their Saturday."""
    days_to_sat = (5 - d.weekday()) % 7
    sat = d + timedelta(days=days_to_sat)
    year = sat.year
    jan1 = date(year, 1, 1)
    first_sat_offset = (5 - jan1.weekday()) % 7
    first_sat = jan1 + timedelta(days=first_sat_offset)
    return 1 + (sat - first_sat).days // 7


def _compute_period_label(start, end):
    """Human-readable period label from start/end dates."""
    days = (end - start).days + 1
    if days == 7 and start.weekday() == 6 and end.weekday() == 5:
        return f"WK{_sunday_week_number(end)}"
    if start.day == 1:
        import calendar
        _, last_day = calendar.monthrange(start.year, start.month)
        if end == date(start.year, start.month, last_day):
            return _MONTH_NAMES[start.month]
    import calendar
    quarter_starts = {1: date(start.year, 1, 1), 2: date(start.year, 4, 1),
                      3: date(start.year, 7, 1), 4: date(start.year, 10, 1)}
    for q, q_start in quarter_starts.items():
        q_end_month = q_start.month + 2
        _, q_last_day = calendar.monthrange(q_start.year, q_end_month)
        q_end = date(q_start.year, q_end_month, q_last_day)
        if start == q_start and end == q_end:
            return f"Q{q}"
    if start == date(start.year, 1, 1) and end.weekday() == 5:
        return f"WK{_sunday_week_number(end)} YTD"
    return f"{start.strftime('%b %d')}-{end.strftime('%b %d')}"


# ---------------------------------------------------------------------------
# Channel configuration
# ---------------------------------------------------------------------------
DOMESTIC_CHANNELS = [
    ("fba", "FBA"),
    ("sf", "Seller Flex"),
    ("es", "MFN Easy Ship"),
    ("ss", "MFN Self Ship"),
]

# Goals CSV column name → internal channel key (strip whitespace on lookup)
GOALS_CHANNEL_MAP = {
    "3P DOM": "dom",
    "FBA": "fba",
    "SF": "sf",
    "ES": "es",
    "MFN SS": "ss",
}


class ProductSelectionWowYoy(AnalysisStrategy):
    """WoW + YoY Product Selection callout by GL with seller drivers and v2 analytics."""

    # Default thresholds — all configurable via recipe params
    DEFAULT_THRESHOLDS = {
        "opposite_seller_threshold": 0.8,       # counter-seller magnitude ratio
        "conversion_single_week_pct": 10.0,     # BA-to-AWAS single-week relative change %
        "conversion_consecutive_weeks": 3,       # BA-to-AWAS consecutive trend weeks
        "churn_ratio_threshold": 0.5,            # seller churn ratio gate (50%)
        "channel_pf_abs_floor": 0.4,             # PF Signal A: channel delta / PF delta floor
        "channel_pf_growth_mult": 1.3,           # PF Signal A: channel growth rate / PF growth rate
        "channel_pf_counter_trend_pct": 1.5,     # PF Signal B: counter-trend % of own LW
        "channel_gl_abs_floor": 0.4,             # GL: channel delta / GL delta floor
        "channel_gl_growth_mult": 1.5,           # GL: channel growth rate / GL growth rate
        "ftac_awas_consecutive_weeks": 3,        # FTAC/AWAS consecutive trend weeks
        "ftac_awas_cumulative_pct": 15.0,        # FTAC/AWAS cumulative relative change %
        "goal_off_track_floor_pct": 3.0,         # vs Goal: absolute floor %
        "goal_off_track_relative_mult": 2.0,     # vs Goal: relative context multiplier
    }

    def __init__(
        self,
        period_col="period",
        pf_col="pf",
        gl_col="gl",
        metric_col="metric",
        dom_col="dom",
        mcid_col="mcid",
        seller_name_col="seller_name",
        metrics="ba,awas,ftac",
        period_label="Period",
        lookup_group_col="gl_product_group",
        lookup_desc_col="gl_category_description",
        relations=None,
        start_date=None,
        end_date=None,
        # Goals CSV column names
        goals_metric_col="Metric",
        goals_ref_week_col="Ref_week",
        goals_date_value_col="date_value",
        goals_pf_col="PF",
        goals_gl_col="GL",
        # Churn CSV column names
        churn_pf_col="pf",
        churn_gl_col="gl",
        churn_mcid_col="mcid",
        churn_seller_name_col="seller_name",
        churn_new_col="new_asins",
        churn_retained_col="retained_asins",
        churn_churned_col="churned_asins",
        churn_net_col="net_change",
        # Configurable thresholds (all can be overridden)
        opposite_seller_threshold=None,
        conversion_single_week_pct=None,
        conversion_consecutive_weeks=None,
        churn_ratio_threshold=None,
        channel_pf_abs_floor=None,
        channel_pf_growth_mult=None,
        channel_pf_counter_trend_pct=None,
        channel_gl_abs_floor=None,
        channel_gl_growth_mult=None,
        ftac_awas_consecutive_weeks=None,
        ftac_awas_cumulative_pct=None,
        goal_off_track_floor_pct=None,
        goal_off_track_relative_mult=None,
        # Goal week matching
        goal_ref_week=None,
    ):
        self.period_col = period_col
        self.pf_col = pf_col
        self.gl_col = gl_col
        self.metric_col = metric_col
        self.dom_col = dom_col
        self.mcid_col = mcid_col
        self.seller_name_col = seller_name_col

        if isinstance(metrics, str):
            self.metrics = [m.strip().lower() for m in metrics.split(",") if m.strip()]
        else:
            self.metrics = [str(m).lower() for m in metrics]

        self.period_label = period_label
        self.lookup_group_col = lookup_group_col
        self.lookup_desc_col = lookup_desc_col
        self.relations = relations or []
        self.start_date = start_date
        self.end_date = end_date

        # Goals CSV columns
        self.goals_metric_col = goals_metric_col
        self.goals_ref_week_col = goals_ref_week_col
        self.goals_date_value_col = goals_date_value_col
        self.goals_pf_col = goals_pf_col
        self.goals_gl_col = goals_gl_col

        # Churn CSV columns
        self.churn_pf_col = churn_pf_col
        self.churn_gl_col = churn_gl_col
        self.churn_mcid_col = churn_mcid_col
        self.churn_seller_name_col = churn_seller_name_col
        self.churn_new_col = churn_new_col
        self.churn_retained_col = churn_retained_col
        self.churn_churned_col = churn_churned_col
        self.churn_net_col = churn_net_col

        # Thresholds: use provided value or fall back to defaults
        defs = self.DEFAULT_THRESHOLDS
        self.opposite_seller_threshold = float(
            opposite_seller_threshold if opposite_seller_threshold is not None
            else defs["opposite_seller_threshold"]
        )
        self.conversion_single_week_pct = float(
            conversion_single_week_pct if conversion_single_week_pct is not None
            else defs["conversion_single_week_pct"]
        )
        self.conversion_consecutive_weeks = int(
            conversion_consecutive_weeks if conversion_consecutive_weeks is not None
            else defs["conversion_consecutive_weeks"]
        )
        self.churn_ratio_threshold = float(
            churn_ratio_threshold if churn_ratio_threshold is not None
            else defs["churn_ratio_threshold"]
        )
        self.channel_pf_abs_floor = float(
            channel_pf_abs_floor if channel_pf_abs_floor is not None
            else defs["channel_pf_abs_floor"]
        )
        self.channel_pf_growth_mult = float(
            channel_pf_growth_mult if channel_pf_growth_mult is not None
            else defs["channel_pf_growth_mult"]
        )
        self.channel_pf_counter_trend_pct = float(
            channel_pf_counter_trend_pct if channel_pf_counter_trend_pct is not None
            else defs["channel_pf_counter_trend_pct"]
        )
        self.channel_gl_abs_floor = float(
            channel_gl_abs_floor if channel_gl_abs_floor is not None
            else defs["channel_gl_abs_floor"]
        )
        self.channel_gl_growth_mult = float(
            channel_gl_growth_mult if channel_gl_growth_mult is not None
            else defs["channel_gl_growth_mult"]
        )
        self.ftac_awas_consecutive_weeks = int(
            ftac_awas_consecutive_weeks if ftac_awas_consecutive_weeks is not None
            else defs["ftac_awas_consecutive_weeks"]
        )
        self.ftac_awas_cumulative_pct = float(
            ftac_awas_cumulative_pct if ftac_awas_cumulative_pct is not None
            else defs["ftac_awas_cumulative_pct"]
        )
        self.goal_off_track_floor_pct = float(
            goal_off_track_floor_pct if goal_off_track_floor_pct is not None
            else defs["goal_off_track_floor_pct"]
        )
        self.goal_off_track_relative_mult = float(
            goal_off_track_relative_mult if goal_off_track_relative_mult is not None
            else defs["goal_off_track_relative_mult"]
        )

        self.goal_ref_week = int(goal_ref_week) if goal_ref_week is not None else None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _find_relation(self, main_key):
        for rel in self.relations:
            if rel.get("main_key") == main_key:
                return rel
        return None

    def _build_gl_lookup(self, inputs):
        """gl numeric code -> human-readable category description."""
        relation = self._find_relation(self.gl_col)
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

        mapping = {}
        for row in inputs[lookup_input_name]:
            key = self._norm_int(row.get(lookup_key_col))
            desc = row.get(lookup_desc_col, str(key))
            mapping[key] = desc
        return mapping

    @staticmethod
    def _norm_int(raw):
        try:
            return int(float(str(raw)))
        except (ValueError, TypeError):
            return raw

    def _resolve_gl(self, raw, lookup):
        key = self._norm_int(raw)
        if lookup and key in lookup:
            return lookup[key]
        return str(key)

    @staticmethod
    def _safe_int(row, col):
        val = row.get(col)
        if val is None or val == "":
            return 0
        try:
            return int(float(str(val)))
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_float(row, col):
        val = row.get(col)
        if val is None or val == "":
            return 0.0
        try:
            return float(str(val))
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _pct(cur, prev):
        if prev == 0:
            return 0.0
        return (cur - prev) / prev * 100

    @staticmethod
    def _validate_cols(rows, required, input_name):
        first = rows[0]
        missing = [c for c in required if c not in first]
        if missing:
            raise StrategyProcessingError(
                f"Input '{input_name}' missing column(s) {missing}. "
                f"Available: {', '.join(first.keys())}"
            )

    # ------------------------------------------------------------------
    # Module 6: Goal Tracker — index goals data
    # ------------------------------------------------------------------

    def _build_goals_index(self, inputs, gl_lookup):
        """Build goals index: goals_idx[metric_lower][(pf, gl_desc)][channel_key] = goal_value.

        Returns empty dict if goals input is missing or cannot be matched.
        """
        if "goals" not in inputs or not inputs["goals"]:
            return {}

        goals_rows = inputs["goals"]
        first = goals_rows[0]

        # Check required columns exist
        required = [self.goals_metric_col, self.goals_pf_col, self.goals_gl_col]
        missing = [c for c in required if c not in first]
        if missing:
            return {}  # Degrade gracefully

        # Determine which ref_week to use
        target_week = self.goal_ref_week

        # Build mapping of column names (strip whitespace) to channel keys
        col_to_channel = {}
        for col_name in first.keys():
            stripped = col_name.strip()
            if stripped in GOALS_CHANNEL_MAP:
                col_to_channel[col_name] = GOALS_CHANNEL_MAP[stripped]

        # goals_idx[metric][(pf, gl_desc)] = {dom: val, fba: val, ...}
        goals_idx = defaultdict(dict)
        for row in goals_rows:
            # Filter by ref_week if specified
            if target_week is not None:
                row_week = self._safe_int(row, self.goals_ref_week_col)
                if row_week != target_week:
                    continue

            metric_raw = str(row[self.goals_metric_col]).strip().lower()
            pf = str(row[self.goals_pf_col]).strip()
            gl_raw = str(row[self.goals_gl_col]).strip()
            gl_desc = self._resolve_gl(gl_raw, gl_lookup)

            channel_goals = {}
            for col_name, ch_key in col_to_channel.items():
                val = self._safe_float(row, col_name)
                if val > 0:
                    channel_goals[ch_key] = val

            if channel_goals:
                goals_idx[metric_raw][(pf, gl_desc)] = channel_goals

        return dict(goals_idx)

    # ------------------------------------------------------------------
    # Module 3: Churn Annotator — index churn data
    # ------------------------------------------------------------------

    def _build_churn_index(self, inputs, gl_lookup):
        """Build churn index: churn_idx[(pf, gl_desc, mcid)] = {new, retained, churned, net, seller_name}.

        Returns empty dict if churn input is missing.
        """
        if "churn" not in inputs or not inputs["churn"]:
            return {}

        churn_rows = inputs["churn"]
        first = churn_rows[0]
        required = [self.churn_pf_col, self.churn_gl_col, self.churn_mcid_col,
                     self.churn_new_col, self.churn_churned_col, self.churn_net_col]
        missing = [c for c in required if c not in first]
        if missing:
            return {}  # Degrade gracefully

        churn_idx = {}
        for row in churn_rows:
            pf = str(row[self.churn_pf_col]).strip()
            gl_desc = self._resolve_gl(row[self.churn_gl_col], gl_lookup)
            mcid = str(row[self.churn_mcid_col])
            seller_name = str(row.get(self.churn_seller_name_col, "Unknown"))

            churn_idx[(pf, gl_desc, mcid)] = {
                "new_asins": self._safe_int(row, self.churn_new_col),
                "retained_asins": self._safe_int(row, self.churn_retained_col),
                "churned_asins": self._safe_int(row, self.churn_churned_col),
                "net_change": self._safe_int(row, self.churn_net_col),
                "seller_name": seller_name,
            }

        return churn_idx

    # ------------------------------------------------------------------
    # Module 2: BA-to-AWAS Conversion Engine
    # ------------------------------------------------------------------

    def _compute_conversion(self, main_idx, level_key):
        """Compute BA-to-AWAS conversion ratio and trend for a given PF or GL.

        Args:
            main_idx: dict mapping metric -> period -> level_key -> {dom, fba, ...}
            level_key: the PF or GL key to analyze

        Returns:
            dict with conversion analysis or None if not enough data.
        """
        ba_data = main_idx.get("ba", {})
        awas_data = main_idx.get("awas", {})

        # Collect 4-week series of (ba_dom, awas_dom)
        ratios = []
        for period in CY_WEEKS:
            ba_dom = ba_data.get(period, {}).get(level_key, {}).get("dom", 0)
            awas_dom = awas_data.get(period, {}).get(level_key, {}).get("dom", 0)
            if ba_dom > 0:
                ratios.append({"period": period, "ba": ba_dom, "awas": awas_dom,
                               "ratio": awas_dom / ba_dom})
            else:
                ratios.append({"period": period, "ba": ba_dom, "awas": awas_dom,
                               "ratio": 0.0})

        if len(ratios) < 2:
            return None

        # Current week (CWCY) vs last week (LWCY)
        cw_ratio = ratios[-1]["ratio"]
        lw_ratio = ratios[-2]["ratio"]

        if lw_ratio == 0:
            single_week_rel_change = 0.0
        else:
            single_week_rel_change = abs((cw_ratio - lw_ratio) / lw_ratio * 100)

        # WoW pp change
        wow_pp = (cw_ratio - lw_ratio) * 100

        # Determine which leg drives the shift
        ba_cw = ratios[-1]["ba"]
        ba_lw = ratios[-2]["ba"]
        awas_cw = ratios[-1]["awas"]
        awas_lw = ratios[-2]["awas"]

        ba_growth = self._pct(ba_cw, ba_lw) if ba_lw else 0.0
        awas_growth = self._pct(awas_cw, awas_lw) if awas_lw else 0.0

        # Diagnosis
        diagnosis = ""
        if wow_pp < 0:
            if ba_growth > awas_growth:
                diagnosis = "BA growing faster than AWAS \u2014 catalog bloat signal"
            elif awas_growth < 0 and ba_growth >= 0:
                diagnosis = "AWAS declining while BA stable \u2014 demand/health problem"
            else:
                diagnosis = "Conversion ratio declining"
        elif wow_pp > 0:
            if awas_growth > ba_growth:
                diagnosis = "AWAS growing faster than BA \u2014 improving conversion"
            else:
                diagnosis = "Conversion ratio improving"

        # Check 3-consecutive-week trend (requires 4 data points → 3 deltas)
        consecutive_trend = False
        consecutive_direction = None
        if len(ratios) >= 4:
            deltas = [ratios[i + 1]["ratio"] - ratios[i]["ratio"] for i in range(len(ratios) - 1)]
            # Check last N deltas for same direction
            n = self.conversion_consecutive_weeks
            if len(deltas) >= n:
                last_n = deltas[-n:]
                if all(d > 0 for d in last_n):
                    consecutive_trend = True
                    consecutive_direction = "improving"
                elif all(d < 0 for d in last_n):
                    consecutive_trend = True
                    consecutive_direction = "declining"

        # Gate: surface if single-week > threshold OR consecutive trend
        triggered = (single_week_rel_change > self.conversion_single_week_pct
                     or consecutive_trend)

        if not triggered:
            return None

        return {
            "cw_ratio": cw_ratio,
            "lw_ratio": lw_ratio,
            "wow_pp": wow_pp,
            "single_week_rel_change": single_week_rel_change,
            "consecutive_trend": consecutive_trend,
            "consecutive_direction": consecutive_direction,
            "diagnosis": diagnosis,
            "ba_growth": ba_growth,
            "awas_growth": awas_growth,
        }

    # ------------------------------------------------------------------
    # Module 4: Channel Mix Analyzer
    # ------------------------------------------------------------------

    def _analyze_channel_mix(self, cw_channels, lw_channels, dom_wow_delta, level="pf"):
        """Analyze channel mix for disproportionate contribution and counter-trends.

        Args:
            cw_channels: dict channel_key -> cw_value
            lw_channels: dict channel_key -> lw_value
            dom_wow_delta: total DOM WoW delta
            level: "pf" or "gl" (determines thresholds)

        Returns:
            dict with signal_a (list), signal_b (list) annotations.
        """
        signals_a = []  # Disproportionate contribution
        signals_b = []  # Counter-trend (PF only)

        all_channels = sorted(set(cw_channels.keys()) | set(lw_channels.keys()))
        lw_total = sum(lw_channels.get(ch, 0) for ch in all_channels)

        if lw_total == 0 or dom_wow_delta == 0:
            return {"signal_a": signals_a, "signal_b": signals_b}

        dom_direction_positive = dom_wow_delta > 0

        # GL growth rate: (CW/LW - 1) as a percentage
        cw_total = sum(cw_channels.get(ch, 0) for ch in all_channels)
        gl_growth_rate = (cw_total / lw_total - 1) * 100 if lw_total else 0.0

        for ch_key in all_channels:
            ch_label = dict(DOMESTIC_CHANNELS).get(ch_key, ch_key)
            ch_cw = cw_channels.get(ch_key, 0)
            ch_lw = lw_channels.get(ch_key, 0)
            ch_delta = ch_cw - ch_lw

            # Signal A: two-condition gate, same direction only
            if level == "gl":
                abs_floor = self.channel_gl_abs_floor
                growth_mult = self.channel_gl_growth_mult
            else:
                abs_floor = self.channel_pf_abs_floor
                growth_mult = self.channel_pf_growth_mult

            # Condition 1: channel_delta / dom_delta >= floor (same direction)
            abs_share = ch_delta / dom_wow_delta
            if abs_share >= abs_floor:
                # Condition 2: channel growth rate >= multiplier * overall growth rate
                ch_growth_rate = (ch_cw / ch_lw - 1) * 100 if ch_lw else 0.0
                # Condition 3: channel delta >= 1% of overall LW base
                if (gl_growth_rate != 0
                        and ch_growth_rate / gl_growth_rate >= growth_mult
                        and abs(ch_delta) >= lw_total * 0.01):
                    signals_a.append({
                        "channel": ch_label,
                        "channel_key": ch_key,
                        "change_share": abs_share * 100,
                        "lw_share": (ch_lw / lw_total * 100) if lw_total else 0,
                        "ratio": ch_growth_rate / gl_growth_rate,
                        "growth_rate": ch_growth_rate,
                        "delta": ch_delta,
                    })

            # Signal B: counter-trend (PF level only)
            if level == "pf":
                ch_moves_opposite = (
                    (dom_direction_positive and ch_delta < 0)
                    or (not dom_direction_positive and ch_delta > 0)
                )
                if ch_moves_opposite and ch_lw > 0:
                    pct_of_own_lw = abs(ch_delta) / ch_lw * 100
                    if pct_of_own_lw >= self.channel_pf_counter_trend_pct:
                        signals_b.append({
                            "channel": ch_label,
                            "channel_key": ch_key,
                            "delta": ch_delta,
                            "pct_of_own_lw": pct_of_own_lw,
                        })

        return {"signal_a": signals_a, "signal_b": signals_b}

    # ------------------------------------------------------------------
    # Module 5: FTAC/AWAS Ratio Tracker
    # ------------------------------------------------------------------

    def _compute_ftac_awas_ratio(self, main_idx, level_key):
        """Compute FTAC/AWAS ratio trend for a given PF or GL.

        Returns dict with trend info or None if gate doesn't trigger.
        """
        ftac_data = main_idx.get("ftac", {})
        awas_data = main_idx.get("awas", {})

        ratios = []
        for period in CY_WEEKS:
            ftac_dom = ftac_data.get(period, {}).get(level_key, {}).get("dom", 0)
            awas_dom = awas_data.get(period, {}).get(level_key, {}).get("dom", 0)
            if awas_dom > 0:
                ratios.append({"period": period, "ratio": ftac_dom / awas_dom,
                               "ftac": ftac_dom, "awas": awas_dom})
            else:
                ratios.append({"period": period, "ratio": 0.0,
                               "ftac": ftac_dom, "awas": awas_dom})

        if len(ratios) < 4:
            return None

        # 3 deltas from 4 data points
        deltas = [ratios[i + 1]["ratio"] - ratios[i]["ratio"] for i in range(len(ratios) - 1)]

        n = self.ftac_awas_consecutive_weeks
        if len(deltas) < n:
            return None

        last_n = deltas[-n:]

        # Check consecutive same direction
        all_up = all(d > 0 for d in last_n)
        all_down = all(d < 0 for d in last_n)

        if not (all_up or all_down):
            return None

        # Cumulative relative change across the N deltas
        start_ratio = ratios[-(n + 1)]["ratio"]
        end_ratio = ratios[-1]["ratio"]

        if start_ratio == 0:
            return None

        cumulative_rel_change = abs((end_ratio - start_ratio) / start_ratio * 100)

        if cumulative_rel_change <= self.ftac_awas_cumulative_pct:
            return None

        direction = "improved" if all_up else "declined"
        return {
            "direction": direction,
            "weeks": n,
            "start_ratio": start_ratio,
            "end_ratio": end_ratio,
            "start_pct": start_ratio * 100,
            "end_pct": end_ratio * 100,
            "cumulative_pp": (end_ratio - start_ratio) * 100,
            "cumulative_rel_change": cumulative_rel_change,
        }

    # ------------------------------------------------------------------
    # Module 6: Goal Tracker — compute vs-goal annotations
    # ------------------------------------------------------------------

    def _compute_vs_goal(self, actual_dom, goal_channels, actual_channels, level_key=None):
        """Compute vs-goal inline text and off-track channel flags.

        Args:
            actual_dom: actual DOM value
            goal_channels: dict channel_key -> goal_value (from goals CSV)
            actual_channels: dict channel_key -> actual_value
            level_key: for context in annotations

        Returns:
            dict with vs_goal_inline, off_track_channels, or None if no goals.
        """
        if not goal_channels:
            return None

        dom_goal = goal_channels.get("dom")
        if not dom_goal or dom_goal == 0:
            return None

        dom_pct_vs_goal = (actual_dom - dom_goal) / dom_goal * 100
        dom_on_or_above = dom_pct_vs_goal >= 0

        # Inline text for PF headline
        vs_goal_inline = f"{dom_pct_vs_goal:+.1f}% vs. Goal"

        # Off-track channels: only flag misses
        off_track = []
        for ch_key, ch_label in DOMESTIC_CHANNELS:
            ch_goal = goal_channels.get(ch_key)
            ch_actual = actual_channels.get(ch_key, 0)

            if not ch_goal or ch_goal == 0:
                continue

            ch_pct_vs_goal = (ch_actual - ch_goal) / ch_goal * 100

            # Only flag misses (negative deviation)
            if ch_pct_vs_goal >= 0:
                continue

            ch_miss_pct = abs(ch_pct_vs_goal)

            # Condition 1: absolute floor — channel > X% below goal
            if ch_miss_pct <= self.goal_off_track_floor_pct:
                continue

            # Condition 2: relative context — channel miss >= Nx PF DOM miss
            # OR Condition 3: PF DOM at/above goal (waive condition 2)
            dom_miss_pct = abs(dom_pct_vs_goal) if dom_pct_vs_goal < 0 else 0
            if dom_on_or_above:
                # PF on/above goal — any channel > floor is flagged
                pass
            elif dom_miss_pct > 0 and ch_miss_pct >= self.goal_off_track_relative_mult * dom_miss_pct:
                # Channel miss is disproportionate
                pass
            else:
                continue

            off_track.append({
                "channel": ch_label,
                "channel_key": ch_key,
                "actual": ch_actual,
                "goal": ch_goal,
                "pct_vs_goal": ch_pct_vs_goal,
            })

        return {
            "vs_goal_inline": vs_goal_inline,
            "dom_pct_vs_goal": dom_pct_vs_goal,
            "dom_on_or_above": dom_on_or_above,
            "off_track_channels": off_track,
        }

    # ------------------------------------------------------------------
    # main
    # ------------------------------------------------------------------

    def process(self, inputs):  # noqa: C901
        if "main" not in inputs or not inputs["main"]:
            available = ", ".join(inputs.keys()) or "(none)"
            raise StrategyProcessingError(
                f"Strategy requires a non-empty 'main' input. Got: {available}."
            )

        main_rows = inputs["main"]
        seller_rows = inputs.get("sellers", []) or []

        self._validate_cols(
            main_rows,
            [self.period_col, self.pf_col, self.gl_col, self.metric_col, self.dom_col]
            + [c for c, _ in DOMESTIC_CHANNELS],
            "main",
        )
        if seller_rows:
            self._validate_cols(
                seller_rows,
                [self.period_col, self.gl_col,
                 self.mcid_col, self.seller_name_col, self.dom_col],
                "sellers",
            )

        # Period label from start/end dates (if provided)
        period_label = self.period_label
        if self.start_date and self.end_date:
            period_label = _compute_period_label(
                _parse_date(self.start_date), _parse_date(self.end_date)
            )

        gl_lookup = self._build_gl_lookup(inputs)
        goals_idx = self._build_goals_index(inputs, gl_lookup)
        churn_idx = self._build_churn_index(inputs, gl_lookup)

        # Valid periods for v2 (accept both v1 3-period and v2 5-period data)
        valid_periods = {CWCY, LWCY, LW1CY, LW2CY, CWLY}

        # ---- Index main rows by (metric, period, gl_desc) ----
        # main_idx[metric][period][gl_desc] = {dom, fba, sf, es, ss}
        main_idx = defaultdict(lambda: defaultdict(dict))
        # Also track PF for each GL
        gl_to_pf = {}
        for r in main_rows:
            metric = str(r[self.metric_col]).lower()
            if metric not in self.metrics:
                continue
            period = str(r[self.period_col]).upper()
            if period not in valid_periods:
                continue
            gl_desc = self._resolve_gl(r[self.gl_col], gl_lookup)
            pf = str(r.get(self.pf_col, "")).strip()
            if pf:
                gl_to_pf[gl_desc] = pf

            bucket = main_idx[metric][period].setdefault(
                gl_desc,
                {"dom": 0, "fba": 0, "sf": 0, "es": 0, "ss": 0},
            )
            bucket["dom"] += self._safe_int(r, self.dom_col)
            for col, _ in DOMESTIC_CHANNELS:
                bucket[col] += self._safe_int(r, col)

        # ---- Index seller rows by (metric, period, gl_desc, mcid) ----
        seller_idx = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
        seller_names = {}
        for r in seller_rows:
            metric = str(r.get(self.metric_col, "ba")).lower()
            if metric not in self.metrics:
                continue
            period = str(r[self.period_col]).upper()
            if period not in valid_periods:
                continue
            gl_desc = self._resolve_gl(r[self.gl_col], gl_lookup)
            mcid = str(r[self.mcid_col])
            name = str(r[self.seller_name_col] or "Unknown")
            seller_names.setdefault(mcid, name)

            entry = seller_idx[metric][period][gl_desc].setdefault(
                mcid, {"dom": 0}
            )
            entry["dom"] += self._safe_int(r, self.dom_col)

        # ---- Build per-metric output ----
        metrics_out = {}
        for metric in self.metrics:
            metrics_out[metric] = self._build_metric(
                metric, main_idx, seller_idx[metric], seller_names,
                gl_to_pf, goals_idx, churn_idx,
            )

        return {
            "period_label": period_label,
            "metrics": metrics_out,
        }

    # ------------------------------------------------------------------
    # per-metric builder
    # ------------------------------------------------------------------

    def _build_metric(self, metric, main_idx, metric_sellers, seller_names,
                      gl_to_pf, goals_idx, churn_idx):
        label = METRIC_LABELS.get(metric, metric.upper())
        metric_main = main_idx.get(metric, {})

        cw = metric_main.get(CWCY, {})
        lw = metric_main.get(LWCY, {})
        ly = metric_main.get(CWLY, {})

        # ---- Totals ----
        cw_total = sum(b["dom"] for b in cw.values())
        lw_total = sum(b["dom"] for b in lw.values())
        ly_total = sum(b["dom"] for b in ly.values())

        wow_delta = cw_total - lw_total
        wow_pct = self._pct(cw_total, lw_total)
        yoy_delta = cw_total - ly_total
        yoy_pct = self._pct(cw_total, ly_total)

        # ---- PF-level aggregation for conversion / FTAC ratio / goals ----
        # Collect all PFs
        all_pfs = set()
        for gl_desc, pf in gl_to_pf.items():
            all_pfs.add(pf)

        # Build PF-level aggregated main_idx for conversion/FTAC analysis
        # pf_main_idx[metric][period][pf] = {dom, fba, sf, es, ss}
        pf_main_idx = defaultdict(lambda: defaultdict(dict))
        for m in self.metrics:
            m_data = main_idx.get(m, {})
            for period in m_data:
                for gl_desc, bucket in m_data[period].items():
                    pf = gl_to_pf.get(gl_desc, "")
                    if not pf:
                        continue
                    pf_bucket = pf_main_idx[m][period].setdefault(
                        pf, {"dom": 0, "fba": 0, "sf": 0, "es": 0, "ss": 0}
                    )
                    for k in pf_bucket:
                        pf_bucket[k] += bucket.get(k, 0)

        # ---- PF-level annotations ----
        pf_annotations = {}
        for pf in all_pfs:
            ann = {}

            # Module 2: Conversion (only for BA metric context, but compute for all)
            if metric == "ba":
                conv = self._compute_conversion(pf_main_idx, pf)
                if conv:
                    ann["conversion"] = conv

            # Module 5: FTAC/AWAS ratio (only relevant context)
            if metric == "ftac":
                ftac_ratio = self._compute_ftac_awas_ratio(pf_main_idx, pf)
                if ftac_ratio:
                    ann["ftac_awas_ratio"] = ftac_ratio

            # Module 4: Channel mix at PF level
            pf_cw_channels = {}
            pf_lw_channels = {}
            m_data = main_idx.get(metric, {})
            for gl_desc, bucket in m_data.get(CWCY, {}).items():
                if gl_to_pf.get(gl_desc) == pf:
                    for ch_key, _ in DOMESTIC_CHANNELS:
                        pf_cw_channels[ch_key] = pf_cw_channels.get(ch_key, 0) + bucket.get(ch_key, 0)
            for gl_desc, bucket in m_data.get(LWCY, {}).items():
                if gl_to_pf.get(gl_desc) == pf:
                    for ch_key, _ in DOMESTIC_CHANNELS:
                        pf_lw_channels[ch_key] = pf_lw_channels.get(ch_key, 0) + bucket.get(ch_key, 0)

            pf_dom_cw = sum(pf_cw_channels.values())
            pf_dom_lw = sum(pf_lw_channels.values())
            pf_dom_delta = pf_dom_cw - pf_dom_lw

            channel_mix = self._analyze_channel_mix(pf_cw_channels, pf_lw_channels, pf_dom_delta, level="pf")
            if channel_mix["signal_a"] or channel_mix["signal_b"]:
                ann["channel_mix"] = channel_mix

            # Module 6: vs Goal at PF level
            metric_goals = goals_idx.get(metric, {})
            # Try to find goal for this PF (aggregate across GLs if needed)
            pf_goal_channels = {}
            for (g_pf, g_gl), g_channels in metric_goals.items():
                if g_pf == pf:
                    for ch_key, val in g_channels.items():
                        pf_goal_channels[ch_key] = pf_goal_channels.get(ch_key, 0) + val

            pf_actual_channels = dict(pf_cw_channels)
            pf_actual_dom = pf_dom_cw

            vs_goal = self._compute_vs_goal(pf_actual_dom, pf_goal_channels, pf_actual_channels)
            if vs_goal:
                ann["vs_goal"] = vs_goal

            if ann:
                pf_annotations[pf] = ann

        # ---- GL-level contributors / offenders by WoW DOM delta ----
        all_gls = sorted(set(cw.keys()) | set(lw.keys()) | set(ly.keys()))
        gl_entries = []
        for gl in all_gls:
            cw_dom = cw.get(gl, {}).get("dom", 0)
            lw_dom = lw.get(gl, {}).get("dom", 0)
            ly_dom = ly.get(gl, {}).get("dom", 0)
            gl_wow = cw_dom - lw_dom
            gl_yoy = cw_dom - ly_dom
            pf = gl_to_pf.get(gl, "")

            # Channel split
            channels = []
            cw_ch = {}
            lw_ch = {}
            for col, ch_label in DOMESTIC_CHANNELS:
                c_cw = cw.get(gl, {}).get(col, 0)
                c_lw = lw.get(gl, {}).get(col, 0)
                c_ly = ly.get(gl, {}).get(col, 0)
                cw_ch[col] = c_cw
                lw_ch[col] = c_lw
                channels.append({
                    "channel": ch_label,
                    "channel_key": col,
                    "cw": c_cw, "lw": c_lw, "ly": c_ly,
                    "wow_delta": c_cw - c_lw,
                    "wow_pct": self._pct(c_cw, c_lw),
                    "yoy_delta": c_cw - c_ly,
                    "yoy_pct": self._pct(c_cw, c_ly),
                })

            # Top seller drivers for this GL
            top_dir, top_opp = self._pick_sellers(
                metric_sellers, gl, gl_wow, seller_names, churn_idx, pf, metric
            )

            # GL-level annotations
            gl_ann = {}

            # Module 2: Conversion at GL level
            if metric == "ba":
                conv = self._compute_conversion(main_idx, gl)
                if conv:
                    gl_ann["conversion"] = conv

            # Module 5: FTAC/AWAS at GL level
            if metric == "ftac":
                ftac_ratio = self._compute_ftac_awas_ratio(main_idx, gl)
                if ftac_ratio:
                    gl_ann["ftac_awas_ratio"] = ftac_ratio

            # Module 4: Channel mix at GL level
            channel_mix_gl = self._analyze_channel_mix(cw_ch, lw_ch, gl_wow, level="gl")
            if channel_mix_gl["signal_a"]:
                gl_ann["channel_mix"] = channel_mix_gl

            # Module 6: vs Goal at GL level
            metric_goals = goals_idx.get(metric, {})
            gl_goal_channels = metric_goals.get((pf, gl), {})
            gl_actual_channels = dict(cw_ch)
            vs_goal_gl = self._compute_vs_goal(cw_dom, gl_goal_channels, gl_actual_channels)
            if vs_goal_gl:
                gl_ann["vs_goal"] = vs_goal_gl

            gl_entries.append({
                "name": gl,
                "pf": pf,
                "cw": cw_dom,
                "lw": lw_dom,
                "ly": ly_dom,
                "wow_delta": gl_wow,
                "wow_pct": self._pct(cw_dom, lw_dom),
                "yoy_delta": gl_yoy,
                "yoy_pct": self._pct(cw_dom, ly_dom),
                "is_positive": gl_wow >= 0,
                "channels": channels,
                "top_seller": top_dir,
                "opposite_seller": top_opp,
                "annotations": gl_ann,
            })

        # Sort by absolute WoW delta, split into positive / negative
        gl_entries.sort(key=lambda g: abs(g["wow_delta"]), reverse=True)
        positive = [g for g in gl_entries if g["is_positive"]]
        negative = [g for g in gl_entries if not g["is_positive"]]

        return {
            "label": label,
            "cw_total": cw_total,
            "lw_total": lw_total,
            "ly_total": ly_total,
            "wow_delta": wow_delta,
            "wow_pct": wow_pct,
            "yoy_delta": yoy_delta,
            "yoy_pct": yoy_pct,
            "direction_wow": "increased" if wow_delta >= 0 else "decreased",
            "direction_yoy": "increased" if yoy_delta >= 0 else "decreased",
            "categories": gl_entries,
            "positive_categories": positive,
            "negative_categories": negative,
            "pf_annotations": pf_annotations,
        }

    # ------------------------------------------------------------------
    # seller driver selection (Module 3: with churn annotations)
    # ------------------------------------------------------------------

    def _pick_sellers(self, metric_sellers, gl, gl_wow_delta, seller_names,
                      churn_idx=None, pf="", metric=""):
        """Pick top seller in GL direction, and top in opposite direction
        if its |delta| >= threshold * |top_direction_delta|.

        When churn data is available and metric is 'ba', annotates sellers
        with churn info when churn_ratio >= threshold.

        Returns (top_dir, top_opp) — each a dict or None.
        """
        cw = metric_sellers.get(CWCY, {}).get(gl, {})
        lw = metric_sellers.get(LWCY, {}).get(gl, {})
        mcids = set(cw.keys()) | set(lw.keys())
        if not mcids:
            return None, None

        deltas = []
        for mcid in mcids:
            s_cw = cw.get(mcid, {}).get("dom", 0)
            s_lw = lw.get(mcid, {}).get("dom", 0)
            seller_entry = {
                "mcid": mcid,
                "seller_name": seller_names.get(mcid, "Unknown"),
                "cw": s_cw,
                "lw": s_lw,
                "wow_delta": s_cw - s_lw,
                "wow_pct": self._pct(s_cw, s_lw),
            }

            # Module 3: Churn annotation (BA metric only)
            if churn_idx and metric == "ba":
                churn_key = (pf, gl, mcid)
                churn_data = churn_idx.get(churn_key)
                if churn_data:
                    new = churn_data["new_asins"]
                    churned = churn_data["churned_asins"]
                    churn_ratio = churned / new if new > 0 else 0.0
                    if churn_ratio >= self.churn_ratio_threshold:
                        seller_entry["churn"] = {
                            "new_asins": new,
                            "retained_asins": churn_data["retained_asins"],
                            "churned_asins": churned,
                            "net_change": churn_data["net_change"],
                            "churn_ratio": churn_ratio,
                        }

            deltas.append(seller_entry)

        # Direction: match GL direction (ties -> treat as positive)
        want_positive = gl_wow_delta >= 0

        if want_positive:
            directional = sorted(deltas, key=lambda s: (-s["wow_delta"], s["mcid"]))
            opposite = sorted(deltas, key=lambda s: (s["wow_delta"], s["mcid"]))
        else:
            directional = sorted(deltas, key=lambda s: (s["wow_delta"], s["mcid"]))
            opposite = sorted(deltas, key=lambda s: (-s["wow_delta"], s["mcid"]))

        top_dir = directional[0] if directional else None

        # Only keep directional if its delta is non-zero and matches direction
        if top_dir:
            if want_positive and top_dir["wow_delta"] <= 0:
                top_dir = None
            elif not want_positive and top_dir["wow_delta"] >= 0:
                top_dir = None

        top_opp = None
        if top_dir and opposite:
            candidate = opposite[0]
            if want_positive and candidate["wow_delta"] < 0:
                if abs(candidate["wow_delta"]) >= self.opposite_seller_threshold * abs(top_dir["wow_delta"]):
                    top_opp = candidate
            elif not want_positive and candidate["wow_delta"] > 0:
                if abs(candidate["wow_delta"]) >= self.opposite_seller_threshold * abs(top_dir["wow_delta"]):
                    top_opp = candidate

        return top_dir, top_opp

    # ------------------------------------------------------------------
    # Jinja filters
    # ------------------------------------------------------------------

    def get_filters(self):
        return {
            "compact_k": _compact_k,
            "signed_k": _signed_k,
            "signed_pct": _signed_pct,
            "signed_pp": _signed_pp,
            "wow_fmt": _wow_fmt,
        }

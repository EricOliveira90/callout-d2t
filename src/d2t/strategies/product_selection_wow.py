"""Week-over-Week variance analysis for Amazon Product Selection metrics.

Filters for domestic market (is_dom=1, excluding is_narf=1 and mfn_ooc=1),
computes WoW changes for BA, AWAGV, AWAS, and FTAC metrics, and identifies
top drivers and detractors by product group with channel-level insights.
"""

from collections import defaultdict

from d2t.errors import StrategyProcessingError
from d2t.strategy import AnalysisStrategy

# ---------------------------------------------------------------------------
# Channel column → human-readable label (defaults)
# ---------------------------------------------------------------------------
DEFAULT_CHANNEL_COLS = ["is_fba", "is_fbaos", "is_es", "is_ss"]
DEFAULT_CHANNEL_LABELS = ["FBA", "Seller Flex", "MFN Easy Ship", "MFN Self Ship"]

# Metric column → display label
METRIC_LABELS = {
    "ba": "BA DOM",
    "awagv": "AWAGV",
    "awas": "AWAS",
    "ftac": "FTAC",
    "ftac_total": "FTAC",
}


# ---------------------------------------------------------------------------
# Formatting helpers (exposed as Jinja filters)
# ---------------------------------------------------------------------------

def _compact_k(value, decimals=1, signed=False):
    """Format a number with a 'k' suffix.

    Examples:
        761600  → '761.6k'
        2300    → '2.3k'
        573     → '573'       (below 1 000, no suffix)
        -235    → '-235'
    """
    abs_val = abs(value)
    if abs_val >= 1_000:
        formatted = f"{abs_val / 1_000:.{decimals}f}k"
    else:
        # Below 1k – use integer if whole, else one decimal
        if abs_val == int(abs_val):
            formatted = f"{int(abs_val)}"
        else:
            formatted = f"{abs_val:.{decimals}f}"

    if signed:
        sign = "+" if value >= 0 else "-"
        return f"{sign}{formatted}"
    else:
        return f"-{formatted}" if value < 0 else formatted


def _signed_k(value, decimals=1):
    """Shorthand: compact_k with forced +/- sign."""
    return _compact_k(value, decimals=decimals, signed=True)


def _signed_pct(value):
    """Format a percentage with explicit +/- sign (e.g. +1.8%, -4.3%)."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _wow_fmt(value, decimals=1):
    """Format a WoW delta: signed k with ' WoW' suffix."""
    return f"{_signed_k(value, decimals)} WoW"


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------

class ProductSelectionWow(AnalysisStrategy):
    """WoW variance analysis for Product Selection metrics (domestic only)."""

    def __init__(
        self,
        period_col="period",
        product_group_col="product_group",
        is_dom_col="is_dom",
        is_narf_col="is_narf",
        mfn_ooc_col="mfn_ooc",
        metrics="ba,awagv,awas,ftac",
        channel_cols=None,
        channel_labels=None,
        lookup_group_col="gl_product_group",
        lookup_desc_col="gl_category_description",
        top_drivers=2,
        top_detractors=1,
        period_label="Period",
        relations=None,
    ):
        self.period_col = period_col
        self.product_group_col = product_group_col
        self.is_dom_col = is_dom_col
        self.is_narf_col = is_narf_col
        self.mfn_ooc_col = mfn_ooc_col

        # Metrics can be passed as comma-separated string or list
        if isinstance(metrics, str):
            self.metrics = [m.strip() for m in metrics.split(",") if m.strip()]
        else:
            self.metrics = list(metrics)

        # Channel columns / labels
        if channel_cols is None:
            self.channel_cols = list(DEFAULT_CHANNEL_COLS)
        elif isinstance(channel_cols, str):
            self.channel_cols = [c.strip() for c in channel_cols.split(",") if c.strip()]
        else:
            self.channel_cols = list(channel_cols)

        if channel_labels is None:
            self.channel_labels = list(DEFAULT_CHANNEL_LABELS)
        elif isinstance(channel_labels, str):
            self.channel_labels = [l.strip() for l in channel_labels.split(",") if l.strip()]
        else:
            self.channel_labels = list(channel_labels)

        if len(self.channel_cols) != len(self.channel_labels):
            raise StrategyProcessingError(
                f"channel_cols ({len(self.channel_cols)}) and channel_labels "
                f"({len(self.channel_labels)}) must have the same length."
            )

        self.lookup_group_col = lookup_group_col
        self.lookup_desc_col = lookup_desc_col
        self.top_drivers = int(top_drivers)
        self.top_detractors = int(top_detractors)
        self.period_label = period_label
        self.relations = relations or []

    # ----- helpers -----

    def _build_lookup(self, inputs):
        """Build product_group_id → description mapping from optional lookup input."""
        if "lookup" not in inputs:
            return {}
        lookup_rows = inputs["lookup"]
        if not lookup_rows:
            return {}
        first = lookup_rows[0]
        if self.lookup_group_col not in first or self.lookup_desc_col not in first:
            raise StrategyProcessingError(
                f"Lookup table must contain '{self.lookup_group_col}' and "
                f"'{self.lookup_desc_col}'. Available: {', '.join(first.keys())}"
            )
        mapping = {}
        for row in lookup_rows:
            try:
                key = int(float(str(row[self.lookup_group_col])))
            except (ValueError, TypeError):
                continue
            mapping[key] = str(row[self.lookup_desc_col])
        return mapping

    @staticmethod
    def _norm_pg(raw):
        """Normalise a product_group value to int."""
        try:
            return int(float(str(raw)))
        except (ValueError, TypeError):
            return raw

    def _resolve_pg(self, raw, lookup):
        key = self._norm_pg(raw)
        if lookup and key in lookup:
            return lookup[key]
        return str(key)

    @staticmethod
    def _safe_float(row, col):
        try:
            return float(row[col])
        except (ValueError, TypeError) as e:
            raise StrategyProcessingError(
                f"Non-numeric value in column '{col}': {row[col]!r}"
            ) from e

    @staticmethod
    def _flag_true(row, col):
        """Return True if a flag column is truthy (1 / 1.0 / '1')."""
        try:
            return int(float(str(row[col]))) == 1
        except (ValueError, TypeError):
            return False

    def _pct(self, cur, prev):
        if prev == 0:
            return 0.0
        return (cur - prev) / prev * 100

    # ----- channel helpers -----

    def _channel_for_row(self, row):
        """Return the human-readable channel label for a row.

        Checks channel flag columns in order; returns the first that is 1.
        Falls back to 'Other' if none match.
        """
        for col, label in zip(self.channel_cols, self.channel_labels):
            if col in row and self._flag_true(row, col):
                return label
        return "Other"

    # ----- main processing -----

    def process(self, inputs):  # noqa: C901 (complexity acceptable for a strategy)
        if "main" not in inputs:
            available = ", ".join(inputs.keys()) or "(none)"
            raise StrategyProcessingError(
                f"Strategy requires an input named 'main', but got: {available}. "
                f"Use --input main=<file>."
            )

        rows = inputs["main"]
        if not rows:
            raise StrategyProcessingError("Input 'main' is empty — no rows to process.")

        pg_lookup = self._build_lookup(inputs)

        # --- Validate required columns ---
        first = rows[0]
        required = [self.period_col, self.product_group_col, self.is_dom_col,
                     self.is_narf_col, self.mfn_ooc_col] + self.metrics
        for col in required:
            if col not in first:
                raise StrategyProcessingError(
                    f"Column '{col}' not found. Available: {', '.join(first.keys())}"
                )

        # --- Filter for domestic, exclude narf & mfn_ooc ---
        filtered = []
        for row in rows:
            if (self._flag_true(row, self.is_dom_col)
                    and not self._flag_true(row, self.is_narf_col)
                    and not self._flag_true(row, self.mfn_ooc_col)):
                filtered.append(row)

        if not filtered:
            raise StrategyProcessingError(
                "No rows remain after domestic filtering "
                "(is_dom=1, is_narf≠1, mfn_ooc≠1)."
            )

        # --- Resolve product group names ---
        for row in filtered:
            row[self.product_group_col] = self._resolve_pg(
                row[self.product_group_col], pg_lookup
            )

        # --- Split by period ---
        cw_rows = [r for r in filtered if str(r[self.period_col]).upper() == "CW"]
        lw_rows = [r for r in filtered if str(r[self.period_col]).upper() == "LW"]

        if not cw_rows:
            raise StrategyProcessingError("No rows with period='CW' after filtering.")
        if not lw_rows:
            raise StrategyProcessingError("No rows with period='LW' after filtering.")

        # --- Build metric results ---
        metrics_out = {}

        for metric in self.metrics:
            label = METRIC_LABELS.get(metric, metric.upper())

            # ---- Macro totals ----
            cw_total = sum(self._safe_float(r, metric) for r in cw_rows)
            lw_total = sum(self._safe_float(r, metric) for r in lw_rows)
            wow_delta = cw_total - lw_total
            wow_pct = self._pct(cw_total, lw_total)

            # ---- Micro: by product group ----
            def _sum_by_pg(row_list):
                groups = defaultdict(float)
                for r in row_list:
                    groups[r[self.product_group_col]] += self._safe_float(r, metric)
                return groups

            cw_by_pg = _sum_by_pg(cw_rows)
            lw_by_pg = _sum_by_pg(lw_rows)
            all_pgs = sorted(set(cw_by_pg.keys()) | set(lw_by_pg.keys()))

            all_groups = []
            for pg in all_pgs:
                cw_val = cw_by_pg.get(pg, 0.0)
                lw_val = lw_by_pg.get(pg, 0.0)
                delta = cw_val - lw_val
                pct = self._pct(cw_val, lw_val)

                # Channel breakdown for this PG
                ch_cw = defaultdict(float)
                ch_lw = defaultdict(float)
                for r in cw_rows:
                    if r[self.product_group_col] == pg:
                        ch_cw[self._channel_for_row(r)] += self._safe_float(r, metric)
                for r in lw_rows:
                    if r[self.product_group_col] == pg:
                        ch_lw[self._channel_for_row(r)] += self._safe_float(r, metric)

                ch_all = sorted(set(ch_cw.keys()) | set(ch_lw.keys()))
                channels = []
                for ch in ch_all:
                    c_cw = ch_cw.get(ch, 0.0)
                    c_lw = ch_lw.get(ch, 0.0)
                    c_delta = c_cw - c_lw
                    c_pct = self._pct(c_cw, c_lw)
                    channels.append({
                        "channel": ch,
                        "cw": c_cw,
                        "lw": c_lw,
                        "wow_delta": c_delta,
                        "wow_pct": c_pct,
                    })
                channels.sort(key=lambda c: abs(c["wow_delta"]), reverse=True)

                # Top channel for insight
                top_ch = channels[0] if channels else None
                # Contribution of top channel to PG delta
                if top_ch and delta != 0:
                    top_ch_contribution_pct = (top_ch["wow_delta"] / delta * 100) if delta != 0 else 0.0
                else:
                    top_ch_contribution_pct = 0.0

                # Build a concise channel insight string
                channel_insight = ""
                if top_ch and top_ch["wow_delta"] != 0:
                    direction = "growth" if top_ch["wow_delta"] > 0 else "decline"
                    channel_insight = (
                        f"{top_ch['channel']} was the primary channel driver "
                        f"({_signed_k(top_ch['wow_delta'])} WoW)"
                    )

                all_groups.append({
                    "name": pg,
                    "cw": cw_val,
                    "lw": lw_val,
                    "wow_delta": delta,
                    "wow_pct": pct,
                    "channels": channels,
                    "channel_insight": channel_insight,
                    "top_channel": top_ch,
                    "top_channel_contribution_pct": top_ch_contribution_pct,
                })

            # Sort by absolute delta descending
            all_groups.sort(key=lambda g: abs(g["wow_delta"]), reverse=True)

            # Drivers (positive delta, sorted by delta desc)
            positive = [g for g in all_groups if g["wow_delta"] > 0]
            positive.sort(key=lambda g: g["wow_delta"], reverse=True)
            drivers = positive[: self.top_drivers]

            # Detractors (negative delta, sorted by delta asc — most negative first)
            negative = [g for g in all_groups if g["wow_delta"] < 0]
            negative.sort(key=lambda g: g["wow_delta"])
            detractors = negative[: self.top_detractors]

            # ---- Channel totals (across all PGs) ----
            ch_total_cw = defaultdict(float)
            ch_total_lw = defaultdict(float)
            for r in cw_rows:
                ch_total_cw[self._channel_for_row(r)] += self._safe_float(r, metric)
            for r in lw_rows:
                ch_total_lw[self._channel_for_row(r)] += self._safe_float(r, metric)

            all_ch_keys = sorted(set(ch_total_cw.keys()) | set(ch_total_lw.keys()))
            all_channels = []
            for ch in all_ch_keys:
                c_cw = ch_total_cw.get(ch, 0.0)
                c_lw = ch_total_lw.get(ch, 0.0)
                c_delta = c_cw - c_lw
                c_pct = self._pct(c_cw, c_lw)
                # Contribution to total WoW delta
                contribution = (c_delta / wow_delta * 100) if wow_delta != 0 else 0.0
                all_channels.append({
                    "channel": ch,
                    "cw": c_cw,
                    "lw": c_lw,
                    "wow_delta": c_delta,
                    "wow_pct": c_pct,
                    "contribution_pct": contribution,
                })
            all_channels.sort(key=lambda c: abs(c["wow_delta"]), reverse=True)

            # ---- Assemble metric context ----
            metrics_out[metric] = {
                "label": label,
                "cw_total": cw_total,
                "lw_total": lw_total,
                "wow_delta": wow_delta,
                "wow_pct": wow_pct,
                "direction": "increased" if wow_delta >= 0 else "decreased",
                "drivers": drivers,
                "detractors": detractors,
                "all_groups": all_groups,
                "all_channels": all_channels,
            }

        return {
            "period_label": self.period_label,
            "metrics": metrics_out,
        }

    def get_filters(self):
        return {
            "compact_k": _compact_k,
            "signed_k": _signed_k,
            "signed_pct": _signed_pct,
            "wow_fmt": _wow_fmt,
        }

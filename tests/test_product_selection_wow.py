"""Tests for the product_selection_wow strategy."""

import math
from pathlib import Path

import pytest

from d2t.errors import StrategyProcessingError
from d2t.input import parse_csv
from d2t.strategies.product_selection_wow import (
    ProductSelectionWow,
    _compact_k,
    _signed_k,
    _signed_pct,
    _wow_fmt,
)

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CSV = FIXTURES / "product_selection_sample.csv"
LOOKUP_CSV = Path(__file__).parent.parent / "csv-static" / "PF-to-GL.csv"


# ---------------------------------------------------------------------------
# Filter unit tests
# ---------------------------------------------------------------------------

class TestCompactK:
    def test_large_number(self):
        assert _compact_k(761600) == "761.6k"

    def test_thousands(self):
        assert _compact_k(2300) == "2.3k"

    def test_below_thousand_integer(self):
        assert _compact_k(573) == "573"

    def test_below_thousand_float(self):
        assert _compact_k(573.5) == "573.5"

    def test_negative(self):
        assert _compact_k(-235) == "-235"

    def test_negative_thousands(self):
        assert _compact_k(-2300) == "-2.3k"

    def test_signed_positive(self):
        assert _compact_k(2300, signed=True) == "+2.3k"

    def test_signed_negative(self):
        assert _compact_k(-2300, signed=True) == "-2.3k"

    def test_zero(self):
        assert _compact_k(0) == "0"

    def test_zero_signed(self):
        assert _compact_k(0, signed=True) == "+0"


class TestSignedK:
    def test_positive(self):
        assert _signed_k(2300) == "+2.3k"

    def test_negative(self):
        assert _signed_k(-235) == "-235"


class TestSignedPct:
    def test_positive(self):
        assert _signed_pct(1.8) == "+1.8%"

    def test_negative(self):
        assert _signed_pct(-4.3) == "-4.3%"

    def test_zero(self):
        assert _signed_pct(0.0) == "+0.0%"


class TestWowFmt:
    def test_positive(self):
        assert _wow_fmt(2300) == "+2.3k WoW"

    def test_negative(self):
        assert _wow_fmt(-235) == "-235 WoW"


# ---------------------------------------------------------------------------
# Strategy processing tests
# ---------------------------------------------------------------------------

class TestProductSelectionWowStrategy:
    """Tests using the sample fixture CSV."""

    @pytest.fixture()
    def strategy(self):
        return ProductSelectionWow()

    @pytest.fixture()
    def strategy_with_lookup(self):
        return ProductSelectionWow()

    @pytest.fixture()
    def inputs(self):
        return {"main": parse_csv(SAMPLE_CSV)}

    @pytest.fixture()
    def inputs_with_lookup(self):
        result = {"main": parse_csv(SAMPLE_CSV)}
        if LOOKUP_CSV.exists():
            result["lookup"] = parse_csv(LOOKUP_CSV)
        return result

    def test_process_returns_metrics(self, strategy, inputs):
        ctx = strategy.process(inputs)
        assert "metrics" in ctx
        for metric in ["ba", "awagv", "awas", "ftac"]:
            assert metric in ctx["metrics"], f"Missing metric: {metric}"

    def test_metric_structure(self, strategy, inputs):
        ctx = strategy.process(inputs)
        m = ctx["metrics"]["ba"]
        assert "label" in m
        assert "cw_total" in m
        assert "lw_total" in m
        assert "wow_delta" in m
        assert "wow_pct" in m
        assert "direction" in m
        assert "drivers" in m
        assert "detractors" in m
        assert "all_groups" in m
        assert "all_channels" in m

    def test_domestic_filter_excludes_narf_and_ooc(self, strategy, inputs):
        """Rows with is_narf=1 or mfn_ooc=1 should be excluded."""
        ctx = strategy.process(inputs)
        ba = ctx["metrics"]["ba"]
        # The sample has 2 non-domestic rows (1 narf, 1 mfn_ooc)
        # CW domestic BA rows sum:
        # HI: 120k + 80k + 45.2k + 12k = 257.2k
        # Tools: 95k + 55k + 20k = 170k
        # Toys: 60k + 45k + 8k = 113k
        # Auto: 40k + 15k + 6.4k = 61.4k
        # Home: 50k + 30k = 80k
        # Total CW = 681.6k
        expected_cw = 257200 + 170000 + 113000 + 61400 + 80000
        assert math.isclose(ba["cw_total"], expected_cw, rel_tol=1e-9)

    def test_wow_delta_is_correct(self, strategy, inputs):
        ctx = strategy.process(inputs)
        ba = ctx["metrics"]["ba"]
        expected_delta = ba["cw_total"] - ba["lw_total"]
        assert math.isclose(ba["wow_delta"], expected_delta, rel_tol=1e-9)

    def test_wow_pct_is_correct(self, strategy, inputs):
        ctx = strategy.process(inputs)
        ba = ctx["metrics"]["ba"]
        expected_pct = (ba["wow_delta"] / ba["lw_total"]) * 100
        assert math.isclose(ba["wow_pct"], expected_pct, rel_tol=1e-6)

    def test_drivers_are_sorted_descending(self, strategy, inputs):
        ctx = strategy.process(inputs)
        for metric in ["ba", "ftac", "awas"]:
            drivers = ctx["metrics"][metric]["drivers"]
            if len(drivers) >= 2:
                assert drivers[0]["wow_delta"] >= drivers[1]["wow_delta"], (
                    f"{metric}: drivers not sorted descending"
                )

    def test_detractors_have_negative_delta(self, strategy, inputs):
        ctx = strategy.process(inputs)
        for metric in ["ba", "ftac", "awas"]:
            for det in ctx["metrics"][metric]["detractors"]:
                assert det["wow_delta"] < 0, (
                    f"{metric}: detractor {det['name']} has non-negative delta"
                )

    def test_all_groups_have_channels(self, strategy, inputs):
        ctx = strategy.process(inputs)
        ba = ctx["metrics"]["ba"]
        for g in ba["all_groups"]:
            assert isinstance(g["channels"], list)
            assert len(g["channels"]) > 0, f"Group {g['name']} has no channels"

    def test_channel_labels_present(self, strategy, inputs):
        ctx = strategy.process(inputs)
        ba = ctx["metrics"]["ba"]
        channel_names = {ch["channel"] for ch in ba["all_channels"]}
        # The sample data has rows with is_fba, is_fbaos, is_es, is_ss
        expected = {"FBA", "Seller Flex", "MFN Easy Ship", "MFN Self Ship"}
        assert channel_names & expected, f"Expected some of {expected}, got {channel_names}"

    def test_lookup_resolves_names(self, strategy_with_lookup, inputs_with_lookup):
        if "lookup" not in inputs_with_lookup:
            pytest.skip("PF-to-GL.csv not found")
        ctx = strategy_with_lookup.process(inputs_with_lookup)
        ba = ctx["metrics"]["ba"]
        group_names = {g["name"] for g in ba["all_groups"]}
        # Product group 60 → Home Improvement, 21 → Toys, etc.
        assert "Home Improvement" in group_names
        assert "Toys" in group_names

    def test_direction_field(self, strategy, inputs):
        ctx = strategy.process(inputs)
        for metric in ["ba", "ftac", "awas"]:
            m = ctx["metrics"][metric]
            if m["wow_delta"] >= 0:
                assert m["direction"] == "increased"
            else:
                assert m["direction"] == "decreased"

    def test_top_drivers_limit(self, inputs):
        strat = ProductSelectionWow(top_drivers=1, top_detractors=1)
        ctx = strat.process(inputs)
        for metric in ["ba", "ftac", "awas"]:
            assert len(ctx["metrics"][metric]["drivers"]) <= 1

    def test_channel_contribution_sums_roughly(self, strategy, inputs):
        """Channel contributions should approximately sum to 100%."""
        ctx = strategy.process(inputs)
        for metric in ["ba", "ftac", "awas"]:
            m = ctx["metrics"][metric]
            if m["wow_delta"] == 0:
                continue
            total_contrib = sum(ch["contribution_pct"] for ch in m["all_channels"])
            assert math.isclose(total_contrib, 100.0, abs_tol=1.0), (
                f"{metric}: channel contributions sum to {total_contrib}%, expected ~100%"
            )

    def test_get_filters(self, strategy):
        filters = strategy.get_filters()
        assert "compact_k" in filters
        assert "signed_k" in filters
        assert "signed_pct" in filters
        assert "wow_fmt" in filters


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

class TestProductSelectionWowErrors:
    def test_missing_main_input(self):
        strat = ProductSelectionWow()
        with pytest.raises(StrategyProcessingError, match="main"):
            strat.process({"other": []})

    def test_empty_main_input(self):
        strat = ProductSelectionWow()
        with pytest.raises(StrategyProcessingError, match="empty"):
            strat.process({"main": []})

    def test_missing_column(self):
        strat = ProductSelectionWow()
        rows = [{"period": "CW", "product_group": 60}]  # missing other cols
        with pytest.raises(StrategyProcessingError, match="not found"):
            strat.process({"main": rows})

    def test_no_domestic_rows(self):
        strat = ProductSelectionWow()
        rows = [{
            "period": "CW", "product_group": 60,
            "is_fba": 0, "is_fbaos": 0, "is_es": 0, "is_ss": 1,
            "is_narf": 0, "mfn_ooc": 0, "is_ooc": 0, "mfn_dom": 0,
            "is_dom": 0, "is_ef_dom": 0,
            "ba": 100, "awagv": 10, "awas": 20, "ftac": 5,
        }]
        with pytest.raises(StrategyProcessingError, match="No rows remain"):
            strat.process({"main": rows})

    def test_no_cw_rows(self):
        strat = ProductSelectionWow()
        rows = [{
            "period": "LW", "product_group": 60,
            "is_fba": 0, "is_fbaos": 0, "is_es": 0, "is_ss": 1,
            "is_narf": 0, "mfn_ooc": 0, "is_ooc": 0, "mfn_dom": 1,
            "is_dom": 1, "is_ef_dom": 0,
            "ba": 100, "awagv": 10, "awas": 20, "ftac": 5,
        }]
        with pytest.raises(StrategyProcessingError, match="CW"):
            strat.process({"main": rows})

"""
tests/test_decisions.py — every verdict path, both layers.

Run from project root:
    python -m unittest tests/test_decisions.py
"""

from __future__ import annotations
import sys
import unittest
from pathlib import Path

# Make project root importable when running unittest from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.formulas import ProductEconomics, CampaignMetrics
from core.decision_engine import evaluate, Verdict
from core.store_lifecycle import assess_store, cumulative_poas_for_store, StoreVerdict


# ---- Campaign-level (decision_engine.py) ----

# Reusable BBQ-niche economics: S$39 cast iron restorer, S$11 COGS,
# 2.9% + S$0.30 payment fee on S$39 = ~S$1.43.
def bbq_econ() -> ProductEconomics:
    return ProductEconomics(selling_price=39.0, cogs=11.0, payment_fee=1.43)


class CampaignVerdictTests(unittest.TestCase):
    def test_scale_when_roas_well_above_break_even(self):
        # break-even ROAS = 39/(39-11-1.43) ≈ 1.47. 1.5x = ~2.20.
        # 11 orders * $39 = $429, spend $180 → ROAS 2.38. POAS = 11*26.57/180 = 1.62.
        m = CampaignMetrics(day=9, ad_spend=180, impressions=45000, clicks=560,
                            sessions=520, add_to_carts=48, orders=11, revenue=429)
        result = evaluate(bbq_econ(), m)
        self.assertEqual(result["verdict"], Verdict.SCALE.value)

    def test_kill_when_unprofitable_past_profit_gate(self):
        # Day 9, ROAS 0.5 — well below break-even.
        m = CampaignMetrics(day=9, ad_spend=200, impressions=20000, clicks=300,
                            sessions=280, add_to_carts=20, orders=3, revenue=100)
        result = evaluate(bbq_econ(), m)
        self.assertEqual(result["verdict"], Verdict.KILL.value)

    def test_iterate_when_ctr_below_floor(self):
        # 0.5% CTR on 10k impressions — below 1% floor.
        m = CampaignMetrics(day=3, ad_spend=60, impressions=10000, clicks=50,
                            sessions=45, add_to_carts=2, orders=0, revenue=0)
        result = evaluate(bbq_econ(), m)
        self.assertEqual(result["verdict"], Verdict.ITERATE.value)
        self.assertIn("CTR", result["reason"])

    def test_iterate_when_funnel_weak(self):
        # Good CTR (3%) but only 1 ATC and 0 orders on 250 sessions.
        m = CampaignMetrics(day=4, ad_spend=80, impressions=8000, clicks=240,
                            sessions=250, add_to_carts=1, orders=0, revenue=0)
        result = evaluate(bbq_econ(), m)
        self.assertEqual(result["verdict"], Verdict.ITERATE.value)
        self.assertIn("Funnel", result["reason"])

    def test_keep_when_too_early(self):
        # Day 2, low volume, no statistical signal yet.
        m = CampaignMetrics(day=2, ad_spend=40, impressions=500, clicks=10,
                            sessions=8, add_to_carts=1, orders=0, revenue=0)
        result = evaluate(bbq_econ(), m)
        self.assertEqual(result["verdict"], Verdict.KEEP.value)

    def test_no_kill_before_profit_gate_day(self):
        # Day 5: bad ROAS but profit gate is day 7 — should not KILL yet.
        m = CampaignMetrics(day=5, ad_spend=120, impressions=12000, clicks=180,
                            sessions=160, add_to_carts=8, orders=1, revenue=39)
        result = evaluate(bbq_econ(), m)
        self.assertNotEqual(result["verdict"], Verdict.KILL.value)


# ---- Store-level (store_lifecycle.py) ----

class StoreVerdictTests(unittest.TestCase):
    def test_keep_during_grace_period(self):
        result = assess_store(
            store_state={"day_since_launch": 5},
            product_verdicts=[{"verdict": "KILL"}, {"verdict": "ITERATE"}],
            aggregated={"total_orders": 0, "total_spend": 100, "total_revenue": 0,
                        "cumulative_poas": 0.0},
        )
        # Inside grace: bad numbers must NOT trigger DUMP.
        self.assertEqual(result["verdict"], StoreVerdict.KEEP_TESTING.value)

    def test_scale_store_when_any_product_scales(self):
        # Even on day 4, a SCALE verdict short-circuits everything.
        result = assess_store(
            store_state={"day_since_launch": 4},
            product_verdicts=[{"verdict": "KILL"}, {"verdict": "SCALE"}],
            aggregated={"total_orders": 12, "total_spend": 180, "total_revenue": 470,
                        "cumulative_poas": 1.6},
        )
        self.assertEqual(result["verdict"], StoreVerdict.SCALE_STORE.value)

    def test_dump_on_hard_stop(self):
        # Day 21 hits hard stop. No SCALE anywhere → DUMP.
        result = assess_store(
            store_state={"day_since_launch": 21},
            product_verdicts=[{"verdict": "KEEP"}, {"verdict": "ITERATE"}],
            aggregated={"total_orders": 18, "total_spend": 500, "total_revenue": 600,
                        "cumulative_poas": 0.95},
        )
        self.assertEqual(result["verdict"], StoreVerdict.DUMP.value)
        self.assertIn("hard stop", result["reason"])

    def test_dump_on_low_orders_after_grace(self):
        # Day 16 (past grace), only 4 orders — below floor of 10.
        result = assess_store(
            store_state={"day_since_launch": 16},
            product_verdicts=[{"verdict": "KEEP"}, {"verdict": "KEEP"}],
            aggregated={"total_orders": 4, "total_spend": 350, "total_revenue": 120,
                        "cumulative_poas": 0.6},
        )
        self.assertEqual(result["verdict"], StoreVerdict.DUMP.value)
        self.assertIn("orders", result["reason"])

    def test_dump_on_low_poas_after_grace(self):
        # Orders fine, POAS 0.5 — below 0.7 floor.
        result = assess_store(
            store_state={"day_since_launch": 17},
            product_verdicts=[{"verdict": "KEEP"}, {"verdict": "KEEP"}],
            aggregated={"total_orders": 14, "total_spend": 420, "total_revenue": 450,
                        "cumulative_poas": 0.5},
        )
        self.assertEqual(result["verdict"], StoreVerdict.DUMP.value)
        self.assertIn("POAS", result["reason"])

    def test_iterate_store_when_all_weak_but_within_floors(self):
        # All products weak (KILL/ITERATE) but orders/POAS still pass.
        result = assess_store(
            store_state={"day_since_launch": 15},
            product_verdicts=[{"verdict": "ITERATE"}, {"verdict": "KILL"}],
            aggregated={"total_orders": 12, "total_spend": 320, "total_revenue": 360,
                        "cumulative_poas": 0.8},
        )
        self.assertEqual(result["verdict"], StoreVerdict.ITERATE_STORE.value)

    def test_keep_testing_when_healthy_after_grace(self):
        result = assess_store(
            store_state={"day_since_launch": 16},
            product_verdicts=[{"verdict": "KEEP"}, {"verdict": "ITERATE"}],
            aggregated={"total_orders": 22, "total_spend": 380, "total_revenue": 720,
                        "cumulative_poas": 0.95},
        )
        self.assertEqual(result["verdict"], StoreVerdict.KEEP_TESTING.value)


class CumulativePoasTests(unittest.TestCase):
    def test_weighted_correctly_by_spend(self):
        per_product = [
            {"orders": 10, "contribution_margin": 20.0, "ad_spend": 100.0},  # CM 200
            {"orders": 5,  "contribution_margin": 30.0, "ad_spend": 100.0},  # CM 150
        ]
        # (200 + 150) / 200 = 1.75
        self.assertAlmostEqual(cumulative_poas_for_store(per_product), 1.75)

    def test_zero_spend_returns_zero(self):
        self.assertEqual(cumulative_poas_for_store([]), 0.0)


if __name__ == "__main__":
    unittest.main()

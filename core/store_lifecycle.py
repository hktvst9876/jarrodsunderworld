"""
core/store_lifecycle.py — DETERMINISTIC store-level verdict.

A store gets DUMPED if, after grace period, the niche isn't working at the
*store* level — independent of any single product's verdict. This is what
implements the "run 2-3 weeks, dump if not hitting criterion" rule.

  KEEP_TESTING : still inside grace window OR metrics within tolerance.
  ITERATE_STORE: every product is weak (KILL/ITERATE) but POAS not catastrophic;
                 swap creative/products once before dumping.
  DUMP         : hard stop reached, OR orders/POAS floor missed after grace.
  SCALE_STORE  : at least one product hit SCALE — concentrate budget on winners.

Inputs:
  store_state: {"day_since_launch": int}
  product_verdicts: [{"verdict": "KILL"|"ITERATE"|"KEEP"|"SCALE", ...}, ...]
  aggregated: {"total_orders": int,
               "total_spend": float,
               "total_revenue": float,
               "cumulative_poas": float}   # caller computes from per-product CM
"""

from __future__ import annotations
from enum import Enum

from config import STORE, StoreThresholds


class StoreVerdict(str, Enum):
    KEEP_TESTING = "KEEP_TESTING"
    ITERATE_STORE = "ITERATE_STORE"
    DUMP = "DUMP"
    SCALE_STORE = "SCALE_STORE"


def assess_store(store_state: dict, product_verdicts: list[dict],
                 aggregated: dict, t: StoreThresholds = STORE) -> dict:
    day = store_state["day_since_launch"]
    snapshot = {
        "day": day,
        "total_orders": aggregated["total_orders"],
        "total_spend": round(aggregated["total_spend"], 2),
        "total_revenue": round(aggregated["total_revenue"], 2),
        "cumulative_poas": round(aggregated["cumulative_poas"], 3),
        "product_verdicts": [pv["verdict"] for pv in product_verdicts],
    }

    # SCALE always wins — if any product is profitable enough to scale,
    # the store is a keeper regardless of the rest.
    if any(pv["verdict"] == "SCALE" for pv in product_verdicts):
        return _result(StoreVerdict.SCALE_STORE, snapshot, day,
            "At least one product hit SCALE. Concentrate budget on winners; "
            "promote it to status='hero' and reduce spend on the rest.")

    # Hard stop — reached the 21-day deadline without a winner.
    if day >= t.hard_stop_days:
        return _result(StoreVerdict.DUMP, snapshot, day,
            f"Day {day} hit hard stop ({t.hard_stop_days} days) without a SCALE "
            f"verdict on any product. Niche failed the test. Rotate to next.")

    # Grace period — never dump before this, even if numbers look bad.
    if day < t.grace_period_days:
        return _result(StoreVerdict.KEEP_TESTING, snapshot, day,
            f"Day {day} < grace period ({t.grace_period_days}). Keep gathering data.")

    # After grace, enforce floors.
    if aggregated["total_orders"] < t.min_total_orders_after_grace:
        return _result(StoreVerdict.DUMP, snapshot, day,
            f"Only {aggregated['total_orders']} orders by day {day} "
            f"(floor: {t.min_total_orders_after_grace}). No demand signal — dump.")

    if aggregated["cumulative_poas"] < t.min_cumulative_poas_after_grace:
        return _result(StoreVerdict.DUMP, snapshot, day,
            f"Cumulative POAS {aggregated['cumulative_poas']:.2f} below floor "
            f"{t.min_cumulative_poas_after_grace}. Burning money on contribution-margin basis — dump.")

    # All products weak but metrics survived the floors → one iteration chance.
    if product_verdicts and all(pv["verdict"] in ("KILL", "ITERATE")
                                for pv in product_verdicts):
        return _result(StoreVerdict.ITERATE_STORE, snapshot, day,
            "All products are KILL/ITERATE. Swap creative or add new SKUs from "
            "the backlog once before dumping the store.")

    return _result(StoreVerdict.KEEP_TESTING, snapshot, day,
        f"Day {day}: {aggregated['total_orders']} orders, "
        f"cumulative POAS {aggregated['cumulative_poas']:.2f}. Within tolerance.")


def cumulative_poas_for_store(per_product: list[dict]) -> float:
    """Compute the store's blended POAS from per-product (orders, cm, spend).

    per_product: [{"orders": int, "contribution_margin": float, "ad_spend": float}, ...]
    """
    total_cm = sum(p["orders"] * p["contribution_margin"] for p in per_product)
    total_spend = sum(p["ad_spend"] for p in per_product)
    return (total_cm / total_spend) if total_spend else 0.0


def _result(verdict: StoreVerdict, metrics: dict, day: int, reason: str) -> dict:
    return {"verdict": verdict.value, "reason": reason, "metrics": metrics, "day": day}


if __name__ == "__main__":
    import json
    # demo: day 16, no SCALE yet, decent volume → KEEP_TESTING
    demo = assess_store(
        store_state={"day_since_launch": 16},
        product_verdicts=[{"verdict": "KEEP"}, {"verdict": "ITERATE"}],
        aggregated={"total_orders": 22, "total_spend": 380.0,
                    "total_revenue": 720.0, "cumulative_poas": 0.95},
    )
    print(json.dumps(demo, indent=2))

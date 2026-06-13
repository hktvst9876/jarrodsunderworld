"""
core/decision_engine.py — DETERMINISTIC campaign-level verdict.

Math decides. The LLM only narrates downstream. Never let an LLM override this.
"""

from __future__ import annotations
from enum import Enum

from core.formulas import (
    ProductEconomics, CampaignMetrics,
    contribution_margin, cm_percent, break_even_roas,
    ctr, atc_rate, cvr, roas, cac, poas,
)
from config import CAMPAIGN, CampaignThresholds


class Verdict(str, Enum):
    KILL = "KILL"
    ITERATE = "ITERATE"
    KEEP = "KEEP"
    SCALE = "SCALE"


def evaluate(e: ProductEconomics, m: CampaignMetrics,
             t: CampaignThresholds = CAMPAIGN) -> dict:
    be_roas = break_even_roas(e)
    metrics = {
        "ctr": ctr(m),
        "atc_rate": atc_rate(m),
        "cvr": cvr(m),
        "roas": roas(m),
        "poas": poas(m, e),
        "cac": cac(m),
        "contribution_margin": round(contribution_margin(e), 2),
        "cm_percent": round(cm_percent(e), 4),
        "break_even_roas": round(be_roas, 2),
    }

    # Profit / scale gate — only if we have real volume.
    if m.orders > 0 and m.ad_spend > 0:
        if metrics["roas"] >= t.scale_roas_multiple * be_roas and metrics["poas"] > 1:
            return _result(Verdict.SCALE, metrics, m.day,
                f"ROAS {metrics['roas']:.2f} >= {t.scale_roas_multiple}x break-even "
                f"({be_roas:.2f}) and POAS {metrics['poas']:.2f} > 1.")
        if m.day >= t.profit_gate_day and metrics["roas"] < be_roas:
            return _result(Verdict.KILL, metrics, m.day,
                f"Day {m.day}: ROAS {metrics['roas']:.2f} below break-even "
                f"{be_roas:.2f}. Not profitable.")

    # Creative gate.
    if m.impressions >= t.min_impressions_for_ctr and metrics["ctr"] < t.min_ctr:
        return _result(Verdict.ITERATE, metrics, m.day,
            f"CTR {metrics['ctr']*100:.2f}% below {t.min_ctr*100:.0f}% floor on "
            f"{m.impressions} impressions. Fix creative, then kill if still low.")

    # Funnel gate.
    if m.sessions >= t.min_sessions_for_cvr and (
        metrics["cvr"] < t.min_cvr or metrics["atc_rate"] < t.min_atc_rate
    ):
        return _result(Verdict.ITERATE, metrics, m.day,
            f"Funnel weak on {m.sessions} sessions: ATC {metrics['atc_rate']*100:.1f}%, "
            f"CVR {metrics['cvr']*100:.1f}%. Fix offer/landing page, then kill if still low.")

    return _result(Verdict.KEEP, metrics, m.day,
                   "Within test window; keep gathering data.")


def _result(verdict: Verdict, metrics: dict, day: int, reason: str) -> dict:
    return {"verdict": verdict.value, "reason": reason, "metrics": metrics, "day": day}


if __name__ == "__main__":
    import json
    econ = ProductEconomics(selling_price=39.0, cogs=11.0, payment_fee=1.43)
    mock = CampaignMetrics(day=9, ad_spend=180.0, impressions=45000, clicks=560,
                           sessions=520, add_to_carts=48, orders=11, revenue=429.0)
    print(json.dumps(evaluate(econ, mock), indent=2))

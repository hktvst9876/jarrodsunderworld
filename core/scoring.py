"""
core/scoring.py — product scoring via Anthropic.

Input: product dict + trend signals
Output: score dict with margin/demand/differentiation/fulfillment/competition subscores + final_score
"""

from __future__ import annotations
import json
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CLAUDE_REASONING_MODEL
from research.trends import TrendSignals

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


SCORE_SYSTEM_PROMPT = """You are a product-research analyst for a lean dropshipping operation in SG. Score a candidate product for paid-traffic testing.

Apply AUTO-REJECT red flags FIRST — if any are true, set auto_reject=true and all sub-scores to 0:
- retail price under S$15
- heavy, oversized, or fragile
- saturated on Amazon with Prime shipping
- no differentiation from competitors

Otherwise score each 0–100:
- margin_score: contribution-margin % (>=40% → ~100, <=15% → 0)
- demand_trend_score: rising search/social interest + low competition = high
- differentiation_wow_score: hard to find locally, scroll-stopping
- fulfillment_score: lightweight, durable, ships fast from supplier
- competition_gap_score: interest climbing while competition low

Compute:
final_score = 0.30*margin + 0.25*demand_trend + 0.20*differentiation_wow + 0.15*fulfillment + 0.10*competition_gap

Respond with ONLY JSON, no markdown:
{"auto_reject": bool, "margin_score": int, "demand_trend_score": int, "differentiation_wow_score": int, "fulfillment_score": int, "competition_gap_score": int, "final_score": float, "rationale": "string"}
"""


def score_product(product: dict, trend_signals: TrendSignals,
                  model: str = CLAUDE_REASONING_MODEL) -> dict:
    """
    product: {"name", "selling_price", "cogs", "description", "image_urls": []}
    trend_signals: TrendSignals dataclass
    returns: {"auto_reject": bool, "margin_score": int, ..., "final_score": float}
    """
    client = anthropic.Anthropic()
    user_msg = json.dumps({
        "product": product,
        "trend_signals": {
            "search_interest_rising": trend_signals.search_interest_rising,
            "competition_level": trend_signals.competition_level,
            "seasonality": trend_signals.seasonality,
            "reddit_mention_count": trend_signals.reddit_mention_count,
            "tiktok_search_volume_approx": trend_signals.tiktok_search_volume_approx,
            "notes": trend_signals.notes,
        }
    }, indent=2)

    try:
        msg = client.messages.create(
            model=model,
            max_tokens=500,
            system=SCORE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = msg.content[0].text.strip()
        # Strip markdown fences if LLM wrapped it anyway.
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        return result
    except (anthropic.APIError, json.JSONDecodeError, IndexError) as exc:
        return {
            "auto_reject": True,
            "margin_score": 0,
            "demand_trend_score": 0,
            "differentiation_wow_score": 0,
            "fulfillment_score": 0,
            "competition_gap_score": 0,
            "final_score": 0,
            "rationale": f"Scoring failed: {exc}",
        }


if __name__ == "__main__":
    from research.trends import bbq_niche_manual_signals
    from db.store import init_db, add_store, add_product

    signals_by_product = bbq_niche_manual_signals()

    # Demo: score 3 products.
    demo_products = [
        {
            "name": "Disposable foil grill",
            "selling_price": 35.0,
            "cogs": 8.0,
            "description": "One-time use disposable BBQ grill for picnics",
            "image_urls": [],
        },
        {
            "name": "Cast iron restorer",
            "selling_price": 45.0,
            "cogs": 12.0,
            "description": "Premium cast iron cookware restoration cream",
            "image_urls": [],
        },
        {
            "name": "Apple wood chips",
            "selling_price": 28.0,
            "cogs": 6.0,
            "description": "Premium apple wood smoking chips",
            "image_urls": [],
        },
    ]

    print("Scoring BBQ products...\n")
    for prod in demo_products:
        sig = signals_by_product[prod["name"]]
        score = score_product(prod, sig)
        print(f"{prod['name']}: final_score={score['final_score']:.1f} (auto_reject={score['auto_reject']})")
        print(f"  rationale: {score['rationale']}\n")

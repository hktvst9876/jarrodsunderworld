"""
llm/creative.py — ad creative generation for short-form video (TikTok/Reels).

Produces three distinct ad angles per product. Uses the router so the
provider is swappable via config.PROVIDER_MAP["creative_text"].
"""

from __future__ import annotations
import json

from llm.router import ask_json, TaskType
from llm.prompts import CREATIVE_GENERATION


def generate_creative(product: dict) -> list[dict]:
    """
    product: dict with at least {"name", "selling_price", "description"}.
    Returns list of angle dicts: [{"name", "hook", "script", "caption"}, ...]
    Falls back to rule-based angles if LLM is unavailable.
    """
    user_msg = json.dumps({
        "name": product.get("name"),
        "selling_price": product.get("selling_price"),
        "description": product.get("description", ""),
        "cogs": product.get("cogs"),
    }, indent=2)

    result = ask_json(
        TaskType.CREATIVE_TEXT,
        system=CREATIVE_GENERATION,
        user=user_msg,
        max_tokens=600,
        tier="reasoning",
    )

    if "_error" in result or "angles" not in result:
        return _fallback_angles(product)

    return result["angles"]


def _fallback_angles(product: dict) -> list[dict]:
    name = product.get("name", "Product")
    price = product.get("selling_price", 0)
    return [
        {
            "name": "Problem-solution",
            "hook": f"Struggling with your BBQ setup? This changes everything.",
            "script": (
                f"Introduce the problem. Show {name} solving it in seconds. "
                f"End with a before/after moment."
            ),
            "caption": f"Upgrade your BBQ game for S${price:.0f}. Link in bio.",
        },
        {
            "name": "Social proof",
            "hook": f"Why every SG BBQ host has this on their list.",
            "script": (
                f"Show 3 quick testimonial-style cuts of {name} in action. "
                f"Real settings: East Coast Park, condo pit, home garden."
            ),
            "caption": f"S${price:.0f} and ships free. Tap to shop.",
        },
        {
            "name": "Curiosity / reveal",
            "hook": "You've been doing it wrong this whole time.",
            "script": (
                f"Tease the common mistake. Reveal {name} as the fix. "
                f"Show the satisfying result. CTA to shop."
            ),
            "caption": f"Only S${price:.0f}. Limited stock — grab yours now.",
        },
    ]


if __name__ == "__main__":
    demo = {
        "name": "Charcoal Chimney Starter",
        "selling_price": 39.0,
        "cogs": 10.0,
        "description": "Fast charcoal lighting chimney — no lighter fluid needed.",
    }
    angles = generate_creative(demo)
    for i, a in enumerate(angles, 1):
        print(f"\nAngle {i}: {a['name']}")
        print(f"  Hook:    {a['hook']}")
        print(f"  Script:  {a['script']}")
        print(f"  Caption: {a['caption']}")

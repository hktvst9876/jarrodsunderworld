"""
integrations/carousell_helper.py — Carousell listing draft generator.

Carousell has NO public seller API and their ToS forbids scraping. Auto-listing
risks an account ban. This helper instead:

  1. Uses Claude to draft a Carousell-shaped listing (title, description,
     hashtags, meetup suggestion).
  2. Writes the draft to a .txt file you can copy-paste into the app.

You list manually in the app. Takes ~2 min per item.
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from llm.client import ask_json, has_api_key
from llm.prompts import CAROUSELL_LISTING

DRAFTS_DIR = Path(__file__).resolve().parent.parent / "carousell_drafts"


def draft_listing(product: dict) -> dict:
    """
    product: {"name", "selling_price", "description", "image_urls": [...]}
    Returns: {"title", "description", "hashtags": [...], "meetup_suggestion"}
    """
    if not has_api_key():
        return _fallback_listing(product)

    user_msg = json.dumps(product, indent=2)
    result = ask_json(system=CAROUSELL_LISTING, user=user_msg, max_tokens=400)
    if "_error" in result:
        return _fallback_listing(product)
    return result


def _fallback_listing(product: dict) -> dict:
    name = product.get("name", "Product")
    price = product.get("selling_price", 0)
    return {
        "title": f"{name} — S${price:.0f}",
        "description": product.get("description", "")
                       + "\n\nDelivery: mail or East/Central meetup.",
        "hashtags": ["bbq", "outdoors", "sg", "grilling", "smoker"],
        "meetup_suggestion": "Tampines / Bedok / Tanah Merah MRT",
    }


def write_draft_file(product: dict, listing: dict) -> Path:
    """Save the listing as a human-readable .txt for copy-paste."""
    DRAFTS_DIR.mkdir(exist_ok=True)
    slug = product.get("name", "product").lower().replace(" ", "-")
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    path = DRAFTS_DIR / f"{slug}-{ts}.txt"

    lines = [
        f"CAROUSELL LISTING DRAFT — {product.get('name')}",
        "=" * 60,
        "",
        f"TITLE:",
        listing["title"],
        "",
        f"PRICE: S${product.get('selling_price', 0):.2f}",
        "",
        "DESCRIPTION:",
        listing["description"],
        "",
        "HASHTAGS:",
        " ".join(f"#{h}" for h in listing.get("hashtags", [])),
        "",
        "MEETUP:",
        listing.get("meetup_suggestion", ""),
        "",
        "IMAGES TO UPLOAD:",
    ]
    for url in product.get("image_urls", []):
        lines.append(f"  - {url}")
    lines.append("")
    lines.append("=" * 60)
    lines.append("Copy-paste into Carousell app. Upload images manually.")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


if __name__ == "__main__":
    demo_product = {
        "name": "Apple Wood Smoking Chips (1kg)",
        "selling_price": 28.0,
        "description": "Premium apple wood chips for smoking meats, fish, cheese.",
        "image_urls": ["https://example.com/applewood.jpg"],
    }
    listing = draft_listing(demo_product)
    path = write_draft_file(demo_product, listing)
    print(f"Draft saved: {path}")
    print(json.dumps(listing, indent=2))

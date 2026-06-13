"""
scripts/score_backlog.py — score all candidate BBQ products via Anthropic.

Reads research/trends.py manual signals + a candidate product list,
scores each one, writes rows into the products table with status='backlog'
ordered by final_score.

Usage:
    python -m scripts.score_backlog                  # scores into a new "backlog" store
    python -m scripts.score_backlog --store-id 1     # scores into existing store
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.store import init_db, add_store, add_product, connect
from core.scoring import score_product
from research.trends import bbq_niche_manual_signals
from config import NICHE_V1, STORE_NAME_V1, BUDGET


# BBQ candidate products. Price/cost based on AliExpress/CJ Dropshipping research.
# fulfillment_shipping = 0 because we ship from CJ SG warehouse (free) or include
# in cost. Adjust when you have real supplier quotes.
CANDIDATES = [
    {"name": "Disposable foil grill", "selling_price": 35.0, "cogs": 8.0,
     "description": "One-time use foil BBQ grill, perfect for East Coast Park picnics. Lightweight, no cleanup."},
    {"name": "Cast iron restorer", "selling_price": 45.0, "cogs": 12.0,
     "description": "Professional-grade cast iron cookware restoration cream. Safe for Lodge, Le Creuset."},
    {"name": "Apple wood chips", "selling_price": 28.0, "cogs": 6.0,
     "description": "Premium apple wood smoking chips, 1kg bag. Sweet smoke for pork, chicken, cheese."},
    {"name": "Silicone basting brush", "selling_price": 18.0, "cogs": 4.0,
     "description": "Heat-resistant silicone basting brush set."},
    {"name": "Magnetic grill thermometer", "selling_price": 42.0, "cogs": 11.0,
     "description": "Magnetic-mount digital thermometer for BBQ grills."},
    {"name": "BBQ glove set", "selling_price": 32.0, "cogs": 9.0,
     "description": "Heat-resistant BBQ gloves, kevlar lined, up to 500F."},
    {"name": "Charcoal chimney starter", "selling_price": 39.0, "cogs": 10.0,
     "description": "Fast charcoal lighting chimney, no lighter fluid needed."},
    {"name": "Jerky-making kit", "selling_price": 55.0, "cogs": 14.0,
     "description": "Complete kit: cure salt, smoking rack, instructions for homemade jerky."},
    {"name": "Bamboo BBQ skewers", "selling_price": 12.0, "cogs": 2.0,
     "description": "Pre-soaked bamboo skewers, 100-pack."},
    {"name": "BBQ meat thermometer (wireless)", "selling_price": 65.0, "cogs": 18.0,
     "description": "Bluetooth wireless meat thermometer, phone app integration."},
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-id", type=int,
                        help="Existing store ID to add products to.")
    parser.add_argument("--threshold", type=float, default=70.0,
                        help="Minimum final_score to add to backlog.")
    parser.add_argument("--live-trends", action="store_true",
                        help="Enrich signals with live Google Trends data (slow, rate-limited).")
    args = parser.parse_args()

    init_db()
    signals_by_product = bbq_niche_manual_signals()

    # Get or create store.
    if args.store_id:
        store_id = args.store_id
        print(f"Adding to store #{store_id}")
    else:
        store_id = add_store(
            name=STORE_NAME_V1,
            niche=NICHE_V1,
            budget_cap_sgd=BUDGET.per_store_total_sgd,
        )
        print(f"Created store #{store_id} ({STORE_NAME_V1})")

    print(f"\nScoring {len(CANDIDATES)} BBQ products...\n")
    if args.live_trends:
        print("  (fetching live Google Trends — this takes ~30s)\n")

    scored = []
    for product in CANDIDATES:
        sig_key = product["name"].split(" (")[0]  # match without parenthesised suffix
        sig = signals_by_product.get(sig_key) or signals_by_product.get(product["name"])
        if not sig:
            from research.trends import TrendSignals
            sig = TrendSignals(product_name=product["name"])

        if args.live_trends:
            from research.trends import enrich_signals_with_trends
            sig = enrich_signals_with_trends(sig)

        result = score_product(product, sig)
        scored.append((product, sig, result))

        flag = "🔴 REJECT" if result.get("auto_reject") else "  "
        print(f"{flag}  {product['name']:35s}  score={result.get('final_score', 0):5.1f}")
        print(f"      {result.get('rationale', '')}")
        print()

    # Sort by score and write top ones into DB.
    scored.sort(key=lambda x: x[2].get("final_score", 0), reverse=True)

    added = 0
    print(f"\nAdding products with score >= {args.threshold} to backlog...\n")
    for product, sig, result in scored:
        if result.get("auto_reject") or result.get("final_score", 0) < args.threshold:
            continue
        pid = add_product(
            store_id=store_id,
            name=product["name"],
            selling_price=product["selling_price"],
            cogs=product["cogs"],
            payment_fee=product["selling_price"] * 0.029 + 0.30,
            score=result["final_score"],
            source="manual",
        )
        added += 1
        print(f"  + product #{pid} {product['name']} (score {result['final_score']:.1f})")

    print(f"\n{added} products added to backlog for store #{store_id}.")
    print("\nNext: pick the top product, then launch via main.py launch <product_id>")


if __name__ == "__main__":
    main()

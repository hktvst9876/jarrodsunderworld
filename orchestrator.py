"""
orchestrator.py — the daily loop.

For each live store:
  1. sync_metrics()         — pull yesterday's data from Meta into daily_metrics
  2. evaluate per product   — deterministic KILL/ITERATE/KEEP/SCALE
  3. assess store           — deterministic DUMP/SCALE_STORE/KEEP/ITERATE_STORE
  4. narrate                — LLM writes 2-3 sentence explanation (CAN'T change verdict)
  5. queue approvals        — money-touching actions need human tap
  6. notify Telegram        — daily summary + push pending approvals
"""

from __future__ import annotations
import json
from datetime import datetime

from db.store import (
    connect, get_store, get_products_for_store,
    aggregated_store_metrics, log_daily_metrics,
    record_decision, queue_approval,
)
from core.decision_engine import evaluate
from core.store_lifecycle import assess_store, cumulative_poas_for_store
from core.formulas import ProductEconomics, CampaignMetrics
from approvals.telegram_bot import push_pending_approvals
from notify import send_daily_summary
from llm.narration import narrate_campaign, narrate_store


def sync_meta_metrics(store_id: int) -> int:
    """Pull yesterday's Meta insights for every product in this store that
    has a meta_campaign_id, and insert into daily_metrics. Returns rows synced."""
    from integrations import ads_meta

    store = get_store(store_id)
    if not store or not store.get("launched_at"):
        return 0

    launch = datetime.fromisoformat(store["launched_at"])
    day = max(0, (datetime.utcnow() - launch).days)

    conn = connect()
    products = conn.execute(
        "SELECT id, meta_campaign_id FROM products "
        "WHERE store_id=? AND meta_campaign_id IS NOT NULL "
        "AND status IN ('testing', 'hero')",
        (store_id,),
    ).fetchall()
    conn.close()

    synced = 0
    for p in products:
        try:
            ins = ads_meta.fetch_yesterday_insights(p["meta_campaign_id"])
            log_daily_metrics(
                product_id=p["id"],
                channel="meta",
                day=day,
                date=ins["date"],
                ad_spend=ins["spend"],
                impressions=ins["impressions"],
                clicks=ins["clicks"],
                sessions=ins["clicks"],   # Shopify sessions ≈ clicks in v1
                add_to_carts=ins["add_to_carts"],
                orders=ins["orders"],
                revenue=ins["revenue"],
            )
            synced += 1
        except Exception as exc:
            print(f"  Meta sync failed for product {p['id']}: {exc}")
    return synced


def run_daily(store_id: int) -> dict:
    """Run the daily verdict loop for one live store. Returns the store verdict."""
    store = get_store(store_id)
    if not store:
        raise ValueError(f"Store {store_id} not found")
    if store["status"] != "live":
        print(f"Store {store_id} ({store['name']}) status={store['status']}, skipping")
        return {}

    # 1. Sync metrics from external platforms.
    print(f"[{store['name']}] syncing Meta metrics...")
    try:
        synced = sync_meta_metrics(store_id)
        print(f"  synced {synced} products")
    except Exception as exc:
        print(f"  Meta sync error (continuing with DB state): {exc}")

    # 2. Evaluate each product.
    products = get_products_for_store(store_id, statuses=("testing", "hero"))
    if not products:
        print(f"[{store['name']}] no testing products, nothing to evaluate")
        return {}

    product_verdicts = []
    per_product_stats = []

    for prod in products:
        conn = connect()
        m_row = conn.execute(
            "SELECT * FROM daily_metrics WHERE product_id=? ORDER BY date DESC LIMIT 1",
            (prod["id"],),
        ).fetchone()
        conn.close()

        if not m_row:
            product_verdicts.append({
                "product_id": prod["id"], "name": prod["name"],
                "verdict": "KEEP", "reason": "No metrics yet.",
            })
            continue

        econ = ProductEconomics(
            selling_price=prod["selling_price"], cogs=prod["cogs"],
            fulfillment_shipping=prod.get("fulfillment_shipping") or 0,
            payment_fee=prod.get("payment_fee") or 0,
            platform_fee=prod.get("platform_fee") or 0,
        )
        campaign = CampaignMetrics(
            day=m_row["day"], ad_spend=m_row["ad_spend"],
            impressions=m_row["impressions"], clicks=m_row["clicks"],
            sessions=m_row["sessions"], add_to_carts=m_row["add_to_carts"],
            orders=m_row["orders"], revenue=m_row["revenue"],
        )

        verdict = evaluate(econ, campaign)
        product_verdicts.append({
            "product_id": prod["id"], "name": prod["name"],
            "verdict": verdict["verdict"], "reason": verdict["reason"],
        })

        record_decision(
            store_id=store_id, product_id=prod["id"],
            level="product", day=m_row["day"],
            verdict=verdict["verdict"], reason=verdict["reason"],
            metrics=verdict["metrics"],
        )

        per_product_stats.append({
            "orders": m_row["orders"],
            "ad_spend": m_row["ad_spend"],
            "contribution_margin": (
                econ.selling_price - econ.cogs - econ.fulfillment_shipping
                - econ.payment_fee - econ.platform_fee
            ),
        })

        # Queue product-level approvals.
        if verdict["verdict"] == "KILL":
            queue_approval(
                action="kill_product",
                payload={"reason": verdict["reason"]},
                store_id=store_id, product_id=prod["id"],
            )
        elif verdict["verdict"] == "SCALE":
            queue_approval(
                action="raise_budget",
                payload={"new_daily_budget_sgd": 35.0,
                         "reason": verdict["reason"]},
                store_id=store_id, product_id=prod["id"],
            )
        elif verdict["verdict"] == "ITERATE":
            queue_approval(
                action="update_creative",
                payload={"reason": verdict["reason"]},
                store_id=store_id, product_id=prod["id"],
            )

    # 3. Roll up to store level.
    agg = aggregated_store_metrics(store_id)
    agg["cumulative_poas"] = cumulative_poas_for_store(per_product_stats)

    launch = datetime.fromisoformat(store["launched_at"]) if store["launched_at"] else datetime.utcnow()
    day = max(0, (datetime.utcnow() - launch).days)

    store_verdict = assess_store(
        store_state={"day_since_launch": day},
        product_verdicts=product_verdicts,
        aggregated=agg,
    )

    record_decision(
        store_id=store_id, level="store", day=day,
        verdict=store_verdict["verdict"], reason=store_verdict["reason"],
        metrics=store_verdict["metrics"],
    )

    # 4. LLM narration (explain only — never overrides).
    narration = narrate_store(store_verdict, product_verdicts)
    store_verdict["narration"] = narration

    # 5. Queue store-level approval if needed.
    if store_verdict["verdict"] == "DUMP":
        queue_approval(
            action="dump_store",
            payload={"reason": store_verdict["reason"], "day": day,
                     "narration": narration},
            store_id=store_id,
        )

    # 6. Notify.
    send_daily_summary(store, store_verdict, product_verdicts)
    push_pending_approvals()

    return store_verdict


def run_all_live_stores() -> None:
    conn = connect()
    stores = conn.execute("SELECT id, name FROM stores WHERE status='live'").fetchall()
    conn.close()
    if not stores:
        print("No live stores.")
        return
    for row in stores:
        print(f"\n--- {row['name']} (id={row['id']}) ---")
        try:
            verdict = run_daily(row["id"])
            print(f"  verdict: {verdict.get('verdict')} — {verdict.get('reason')}")
        except Exception as exc:
            print(f"  ERROR: {exc}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        result = run_daily(int(sys.argv[1]))
        print(json.dumps(result, indent=2, default=str))
    else:
        run_all_live_stores()

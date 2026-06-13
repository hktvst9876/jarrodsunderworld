"""
approvals/executor.py — execute approved actions against live APIs.

Nothing runs until a human taps [Approve] in Telegram. This module reads
approval rows with status='approved' and calls the real APIs.

Actions:
  launch_store    — mark store live in DB + set deadline
  launch_product  — Shopify product create + Meta campaign/adset create + activate
  kill_product    — Meta campaign pause + product status → killed
  raise_budget    — Meta adset daily budget raise
  dump_store      — pause all live campaigns + mark store killed
  update_creative — operator notification only (no API in v1)

Usage:
  python main.py execute              # run all approved rows
  python main.py execute --dry-run    # preview without touching any API
"""

from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.store import (
    connect, kill_store, launch_store,
    set_product_status, set_product_external_ids,
)


def execute_approved_actions(dry_run: bool = False) -> list[dict]:
    """Run every approved-but-unexecuted approval row. Returns execution results."""
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM approvals WHERE status='approved' ORDER BY created_at"
    ).fetchall()
    conn.close()

    if not rows:
        print("No approved actions pending.")
        return []

    results = []
    for row in rows:
        r = dict(row)
        try:
            result = _dispatch(r, dry_run=dry_run)
            if not dry_run:
                _mark_executed(r["id"])
            results.append({
                "id": r["id"], "action": r["action"],
                "status": "dry_run" if dry_run else "executed",
                "result": result,
            })
            tag = "DRY" if dry_run else "OK"
            print(f"  [{tag}] #{r['id']} {r['action']}")
        except Exception as exc:
            results.append({
                "id": r["id"], "action": r["action"],
                "status": "error", "error": str(exc),
            })
            print(f"  [ERR] #{r['id']} {r['action']}: {exc}")

    return results


def execute_one(approval_id: int, dry_run: bool = False) -> dict:
    """Execute a single approval by ID. Called from the Telegram bot after a tap."""
    conn = connect()
    row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError(f"Approval #{approval_id} not found")
    r = dict(row)
    if r["status"] != "approved":
        raise ValueError(
            f"Approval #{approval_id} status={r['status']!r}; can only execute 'approved' rows"
        )
    result = _dispatch(r, dry_run=dry_run)
    if not dry_run:
        _mark_executed(approval_id)
    return result


# ---- internal ----------------------------------------------------------------

def _mark_executed(approval_id: int) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE approvals SET status='executed', resolved_at=? WHERE id=?",
            (datetime.utcnow().isoformat(), approval_id),
        )
    conn.close()


def _dispatch(approval: dict, dry_run: bool) -> dict:
    action = approval["action"]
    payload = json.loads(approval["payload_json"]) if approval["payload_json"] else {}
    store_id = approval.get("store_id")
    product_id = approval.get("product_id")

    dispatch = {
        "launch_store":    lambda: _exec_launch_store(store_id, payload, dry_run),
        "launch_product":  lambda: _exec_launch_product(store_id, product_id, payload, dry_run),
        "kill_product":    lambda: _exec_kill_product(product_id, payload, dry_run),
        "raise_budget":    lambda: _exec_raise_budget(product_id, payload, dry_run),
        "dump_store":      lambda: _exec_dump_store(store_id, payload, dry_run),
        "update_creative": lambda: _exec_update_creative(product_id, payload),
    }
    fn = dispatch.get(action)
    if fn is None:
        raise ValueError(f"Unknown action: {action!r}")
    return fn()


def _exec_launch_store(store_id: int, payload: dict, dry_run: bool) -> dict:
    shopify_domain = payload.get("shopify_domain") or os.environ.get("SHOPIFY_STORE_DOMAIN", "")
    if dry_run:
        print(f"    DRY RUN: launch_store #{store_id} domain={shopify_domain}")
        return {"dry_run": True}
    launch_store(store_id, shopify_domain, hard_stop_days=21)
    return {"launched": True, "store_id": store_id, "shopify_domain": shopify_domain}


def _exec_launch_product(store_id: int, product_id: int, payload: dict,
                          dry_run: bool) -> dict:
    from integrations import shopify, ads_meta

    conn = connect()
    prod = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    conn.close()
    if not prod:
        raise ValueError(f"Product #{product_id} not found")

    name = payload.get("product_name", prod["name"])
    price = float(payload.get("selling_price", prod["selling_price"]))
    daily_budget = float(payload.get("daily_budget_sgd", 25.0))

    # 1. Shopify — creates in DRAFT status; human publishes via Shopify admin.
    shopify_result = shopify.create_product(
        name=name,
        price=price,
        cost=prod["cogs"],
        sku=prod["sku"],
        dry_run=dry_run,
    )

    # 2. Meta — campaign + adset created PAUSED, then activated here.
    safe_name = name.lower().replace(" ", "-")[:40]
    campaign_id = ads_meta.create_campaign(
        name=f"{safe_name}-test",
        daily_budget_sgd=daily_budget,
        dry_run=dry_run,
    )
    adset_id = ads_meta.create_adset(
        campaign_id=campaign_id,
        name="sg-25-55",
        daily_budget_sgd=daily_budget,
        dry_run=dry_run,
    )
    ads_meta.activate_campaign(campaign_id, dry_run=dry_run)

    # 3. Persist IDs + flip product to 'testing'.
    if not dry_run:
        set_product_external_ids(
            product_id,
            shopify_product_id=shopify_result.get("product_id"),
            shopify_variant_id=shopify_result.get("variant_id"),
            meta_campaign_id=campaign_id,
            meta_adset_id=adset_id,
        )
        set_product_status(product_id, "testing")

    return {
        "shopify_product_id": shopify_result.get("product_id"),
        "shopify_handle": shopify_result.get("handle"),
        "meta_campaign_id": campaign_id,
        "meta_adset_id": adset_id,
    }


def _exec_kill_product(product_id: int, payload: dict, dry_run: bool) -> dict:
    from integrations import ads_meta

    conn = connect()
    prod = conn.execute(
        "SELECT meta_campaign_id FROM products WHERE id=?", (product_id,)
    ).fetchone()
    conn.close()

    if prod and prod["meta_campaign_id"]:
        ads_meta.pause_campaign(prod["meta_campaign_id"], dry_run=dry_run)

    if not dry_run:
        set_product_status(product_id, "killed")

    return {"killed": True, "product_id": product_id}


def _exec_raise_budget(product_id: int, payload: dict, dry_run: bool) -> dict:
    from integrations import ads_meta

    new_budget = float(payload.get("new_daily_budget_sgd", 35.0))

    conn = connect()
    prod = conn.execute(
        "SELECT meta_campaign_id, meta_adset_id FROM products WHERE id=?", (product_id,)
    ).fetchone()
    conn.close()

    adset_id = prod["meta_adset_id"] if prod else None
    if not adset_id:
        return {
            "note": "meta_adset_id not stored — raise budget manually in Meta Ads Manager.",
            "campaign_id": prod["meta_campaign_id"] if prod else None,
            "target_budget_sgd": new_budget,
        }

    ads_meta.raise_budget(adset_id, new_budget, dry_run=dry_run)
    return {"raised_budget_sgd": new_budget, "adset_id": adset_id}


def _exec_dump_store(store_id: int, payload: dict, dry_run: bool) -> dict:
    from integrations import ads_meta

    conn = connect()
    products = conn.execute(
        "SELECT id, meta_campaign_id FROM products "
        "WHERE store_id=? AND meta_campaign_id IS NOT NULL "
        "AND status IN ('testing', 'hero')",
        (store_id,),
    ).fetchall()
    conn.close()

    paused = 0
    errors = []
    for p in products:
        try:
            ads_meta.pause_campaign(p["meta_campaign_id"], dry_run=dry_run)
            if not dry_run:
                set_product_status(p["id"], "killed")
            paused += 1
        except Exception as exc:
            errors.append(f"product #{p['id']}: {exc}")
            print(f"    WARNING: could not pause product #{p['id']}: {exc}")

    if not dry_run:
        kill_store(store_id, payload.get("reason", "Dumped by operator"))

    return {
        "store_id": store_id,
        "campaigns_paused": paused,
        "errors": errors,
    }


def _exec_update_creative(product_id: int, payload: dict) -> dict:
    return {
        "action_required": (
            "Update ad creative in Meta Ads Manager for this product, "
            "then re-evaluate in 3-5 days."
        ),
        "reason": payload.get("reason", ""),
        "product_id": product_id,
    }


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(f"Executing approved actions {'(DRY RUN) ' if dry else ''}...\n")
    results = execute_approved_actions(dry_run=dry)
    import json as _j
    print("\n" + _j.dumps(results, indent=2, default=str))

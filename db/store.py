"""
db/store.py — SQLite helpers. Thin wrappers; raw SQL kept readable.
"""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).parent / "store_tester.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = connect()
    with conn:
        conn.executescript(SCHEMA_PATH.read_text())
        # Idempotent migrations for columns added after initial schema.
        for migration in _MIGRATIONS:
            try:
                conn.execute(migration)
            except Exception:
                pass
    conn.close()


_MIGRATIONS = [
    "ALTER TABLE products ADD COLUMN meta_adset_id TEXT",
]


def add_store(name: str, niche: str, budget_cap_sgd: float, region: str = "SG") -> int:
    conn = connect()
    with conn:
        cur = conn.execute(
            "INSERT INTO stores (name, niche, region, budget_cap_sgd) VALUES (?, ?, ?, ?)",
            (name, niche, region, budget_cap_sgd),
        )
    conn.close()
    return cur.lastrowid


def launch_store(store_id: int, shopify_domain: str, hard_stop_days: int) -> None:
    now = datetime.utcnow()
    deadline = now + timedelta(days=hard_stop_days)
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE stores SET status='live', shopify_domain=?, launched_at=?, deadline_at=? WHERE id=?",
            (shopify_domain, now.isoformat(), deadline.isoformat(), store_id),
        )
    conn.close()


def kill_store(store_id: int, reason: str) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE stores SET status='killed', killed_at=?, kill_reason=? WHERE id=?",
            (datetime.utcnow().isoformat(), reason, store_id),
        )
    conn.close()


def add_product(store_id: int, name: str, selling_price: float, cogs: float,
                fulfillment_shipping: float = 0.0, payment_fee: float = 0.0,
                platform_fee: float = 0.0, score: float | None = None,
                source: str = "manual", sku: str | None = None) -> int:
    conn = connect()
    with conn:
        cur = conn.execute(
            """INSERT INTO products
               (store_id, name, sku, selling_price, cogs, fulfillment_shipping,
                payment_fee, platform_fee, score, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (store_id, name, sku, selling_price, cogs, fulfillment_shipping,
             payment_fee, platform_fee, score, source),
        )
    conn.close()
    return cur.lastrowid


def set_product_external_ids(product_id: int, *, shopify_product_id: str | None = None,
                             shopify_variant_id: str | None = None,
                             meta_campaign_id: str | None = None,
                             meta_adset_id: str | None = None,
                             tiktok_campaign_id: str | None = None) -> None:
    """Update external platform IDs after launching a product."""
    fields, vals = [], []
    if shopify_product_id is not None:
        fields.append("shopify_product_id=?"); vals.append(shopify_product_id)
    if shopify_variant_id is not None:
        fields.append("shopify_variant_id=?"); vals.append(shopify_variant_id)
    if meta_campaign_id is not None:
        fields.append("meta_campaign_id=?"); vals.append(meta_campaign_id)
    if meta_adset_id is not None:
        fields.append("meta_adset_id=?"); vals.append(meta_adset_id)
    if tiktok_campaign_id is not None:
        fields.append("tiktok_campaign_id=?"); vals.append(tiktok_campaign_id)
    if not fields:
        return
    vals.append(product_id)
    conn = connect()
    with conn:
        conn.execute(f"UPDATE products SET {', '.join(fields)} WHERE id=?", vals)
    conn.close()


def set_product_status(product_id: int, status: str) -> None:
    if status not in ("backlog", "testing", "killed", "hero"):
        raise ValueError(f"invalid status: {status!r}")
    conn = connect()
    with conn:
        conn.execute("UPDATE products SET status=? WHERE id=?", (status, product_id))
    conn.close()


def log_daily_metrics(product_id: int, channel: str, day: int, date: str,
                      ad_spend: float, impressions: int, clicks: int,
                      sessions: int, add_to_carts: int, orders: int,
                      revenue: float) -> None:
    conn = connect()
    with conn:
        conn.execute(
            """INSERT OR REPLACE INTO daily_metrics
               (product_id, channel, day, date, ad_spend, impressions, clicks,
                sessions, add_to_carts, orders, revenue)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (product_id, channel, day, date, ad_spend, impressions, clicks,
             sessions, add_to_carts, orders, revenue),
        )
    conn.close()


def record_decision(store_id: int, level: str, verdict: str, reason: str,
                    metrics: dict, day: int, product_id: int | None = None) -> int:
    conn = connect()
    with conn:
        cur = conn.execute(
            """INSERT INTO decisions
               (store_id, product_id, level, day, verdict, reason, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (store_id, product_id, level, day, verdict, reason, json.dumps(metrics)),
        )
    conn.close()
    return cur.lastrowid


def queue_approval(action: str, payload: dict, store_id: int | None = None,
                   product_id: int | None = None) -> int:
    conn = connect()
    with conn:
        cur = conn.execute(
            """INSERT INTO approvals (store_id, product_id, action, payload_json)
               VALUES (?, ?, ?, ?)""",
            (store_id, product_id, action, json.dumps(payload)),
        )
    conn.close()
    return cur.lastrowid


def pending_approvals() -> list[sqlite3.Row]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM approvals WHERE status='pending' ORDER BY created_at"
    ).fetchall()
    conn.close()
    return rows


def resolve_approval(approval_id: int, status: str, resolved_by: str) -> None:
    if status not in ("approved", "rejected"):
        raise ValueError(f"invalid status {status!r}")
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE approvals SET status=?, resolved_at=?, resolved_by=? WHERE id=?",
            (status, datetime.utcnow().isoformat(), resolved_by, approval_id),
        )
    conn.close()


def get_store(store_id: int) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_products_for_store(store_id: int, statuses: tuple[str, ...] = ("testing", "hero")) -> list[dict]:
    conn = connect()
    placeholders = ",".join("?" for _ in statuses)
    rows = conn.execute(
        f"SELECT * FROM products WHERE store_id=? AND status IN ({placeholders})",
        (store_id, *statuses),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def aggregated_store_metrics(store_id: int) -> dict[str, Any]:
    """Roll all daily_metrics rows under a store up to totals + cumulative POAS."""
    conn = connect()
    row = conn.execute(
        """SELECT
              COALESCE(SUM(m.ad_spend), 0)    AS spend,
              COALESCE(SUM(m.orders), 0)      AS orders,
              COALESCE(SUM(m.revenue), 0)     AS revenue,
              COALESCE(SUM(m.sessions), 0)    AS sessions
           FROM daily_metrics m
           JOIN products p ON p.id = m.product_id
           WHERE p.store_id = ?""",
        (store_id,),
    ).fetchone()
    conn.close()

    spend = row["spend"] or 0.0
    orders = row["orders"] or 0
    revenue = row["revenue"] or 0.0

    # Cumulative POAS needs contribution-margin per product. Computed in caller
    # because per-product CM differs; here we expose the raw totals.
    return {
        "total_spend": spend,
        "total_orders": orders,
        "total_revenue": revenue,
        "total_sessions": row["sessions"] or 0,
        "blended_roas": (revenue / spend) if spend else 0.0,
    }


if __name__ == "__main__":
    init_db()
    print(f"Initialised DB at {DB_PATH}")

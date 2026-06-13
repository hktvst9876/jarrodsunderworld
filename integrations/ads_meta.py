"""
integrations/ads_meta.py — Meta Marketing API (Facebook + Instagram).

Operations:
  create_campaign()         — create a SALES-objective campaign
  create_adset()            — daily budget, audience, placements
  create_ad()               — wire creative + adset together
  fetch_yesterday_insights()— pull yesterday's impressions/clicks/spend/orders
  pause_campaign()          — used when KILL verdict fires
  raise_budget()            — used when SCALE verdict fires

Token: developers.facebook.com → Tools → Graph API Explorer → grant scopes:
  ads_management, ads_read, business_management
Long-lived token via OAuth flow.

Endpoint base: https://graph.facebook.com/v21.0/

NOTE: This is a scaffold. Full campaign creation needs ad accounts, pixel,
pages, audiences — set those up in Meta Business Manager first, then put
the IDs into .env (META_AD_ACCOUNT_ID, META_PAGE_ID, META_PIXEL_ID).
"""

from __future__ import annotations
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")
API_VERSION = "v21.0"
BASE = f"https://graph.facebook.com/{API_VERSION}"


def _check_creds() -> None:
    if not ACCESS_TOKEN or not AD_ACCOUNT_ID:
        raise RuntimeError("META_ACCESS_TOKEN and META_AD_ACCOUNT_ID required in .env")


def _params() -> dict:
    return {"access_token": ACCESS_TOKEN}


# ---------- Campaign / Adset / Ad creation ----------

def create_campaign(name: str, daily_budget_sgd: float = 25.0,
                    objective: str = "OUTCOME_SALES",
                    dry_run: bool = False) -> str:
    """Create a campaign. Returns campaign_id."""
    if dry_run:
        return f"dry_run_campaign_{name}"
    _check_creds()
    r = requests.post(
        f"{BASE}/{AD_ACCOUNT_ID}/campaigns",
        params=_params(),
        data={
            "name": name,
            "objective": objective,
            "status": "PAUSED",   # never auto-launch; human approval flips to ACTIVE
            "special_ad_categories": "[]",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["id"]


def create_adset(campaign_id: str, name: str, daily_budget_sgd: float = 25.0,
                 country: str = "SG", optimization: str = "OFFSITE_CONVERSIONS",
                 pixel_id: str | None = None,
                 dry_run: bool = False) -> str:
    """Create an ad set under a campaign. Returns adset_id."""
    if dry_run:
        return f"dry_run_adset_{name}"
    _check_creds()
    pixel_id = pixel_id or os.environ.get("META_PIXEL_ID", "")
    if not pixel_id:
        raise RuntimeError("META_PIXEL_ID required for OFFSITE_CONVERSIONS optimization")

    # Daily budget in MINOR currency unit (cents). SGD has 2 decimals.
    daily_budget_cents = int(daily_budget_sgd * 100)

    targeting = {
        "geo_locations": {"countries": [country]},
        "age_min": 25,
        "age_max": 55,
        "publisher_platforms": ["facebook", "instagram"],
    }
    r = requests.post(
        f"{BASE}/{AD_ACCOUNT_ID}/adsets",
        params=_params(),
        data={
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": daily_budget_cents,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": optimization,
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": str(targeting).replace("'", '"'),
            "status": "PAUSED",
            "promoted_object": str({"pixel_id": pixel_id, "custom_event_type": "PURCHASE"}).replace("'", '"'),
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["id"]


def create_ad(adset_id: str, name: str, creative_id: str,
              dry_run: bool = False) -> str:
    """Wire an existing creative to an ad set. Returns ad_id."""
    if dry_run:
        return f"dry_run_ad_{name}"
    _check_creds()
    r = requests.post(
        f"{BASE}/{AD_ACCOUNT_ID}/ads",
        params=_params(),
        data={
            "name": name,
            "adset_id": adset_id,
            "creative": f'{{"creative_id": "{creative_id}"}}',
            "status": "PAUSED",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()["id"]


# ---------- Insights (metric pull) ----------

INSIGHT_FIELDS = ",".join([
    "impressions", "clicks", "spend",
    "actions",            # contains add_to_cart, purchase counts
    "action_values",      # revenue
    "date_start", "date_stop",
])


def fetch_yesterday_insights(campaign_id: str) -> dict:
    """
    Pull yesterday's metrics for a campaign.

    Returns dict with: impressions, clicks, spend, add_to_carts, orders, revenue.
    Missing fields default to 0 so the orchestrator can write the row safely.
    """
    _check_creds()
    yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    r = requests.get(
        f"{BASE}/{campaign_id}/insights",
        params={
            **_params(),
            "fields": INSIGHT_FIELDS,
            "time_range": f'{{"since":"{yesterday}","until":"{yesterday}"}}',
            "level": "campaign",
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json().get("data", [])
    if not data:
        return _empty_metrics()

    row = data[0]
    actions = {a["action_type"]: int(a["value"]) for a in row.get("actions", [])}
    action_values = {a["action_type"]: float(a["value"]) for a in row.get("action_values", [])}

    return {
        "impressions": int(row.get("impressions", 0)),
        "clicks": int(row.get("clicks", 0)),
        "spend": float(row.get("spend", 0)),
        "add_to_carts": actions.get("add_to_cart", 0),
        "orders": actions.get("purchase", 0),
        "revenue": action_values.get("purchase", 0.0),
        "date": row.get("date_start", yesterday),
    }


def _empty_metrics() -> dict:
    return {
        "impressions": 0, "clicks": 0, "spend": 0.0,
        "add_to_carts": 0, "orders": 0, "revenue": 0.0,
        "date": (datetime.utcnow() - timedelta(days=1)).date().isoformat(),
    }


# ---------- Control actions (called after human approval) ----------

def pause_campaign(campaign_id: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"DRY RUN: would pause campaign {campaign_id}")
        return
    _check_creds()
    r = requests.post(f"{BASE}/{campaign_id}",
                      params=_params(), data={"status": "PAUSED"}, timeout=15)
    r.raise_for_status()


def activate_campaign(campaign_id: str, dry_run: bool = False) -> None:
    if dry_run:
        print(f"DRY RUN: would activate campaign {campaign_id}")
        return
    _check_creds()
    r = requests.post(f"{BASE}/{campaign_id}",
                      params=_params(), data={"status": "ACTIVE"}, timeout=15)
    r.raise_for_status()


def raise_budget(adset_id: str, new_daily_budget_sgd: float,
                 dry_run: bool = False) -> None:
    if dry_run:
        print(f"DRY RUN: would raise adset {adset_id} budget to {new_daily_budget_sgd:.2f}")
        return
    _check_creds()
    r = requests.post(f"{BASE}/{adset_id}",
                      params=_params(),
                      data={"daily_budget": int(new_daily_budget_sgd * 100)},
                      timeout=15)
    r.raise_for_status()


if __name__ == "__main__":
    print("Meta ads — dry run demo")
    cid = create_campaign("smokehousesg-castiron-test", dry_run=True)
    asid = create_adset(cid, "sg-25-55", dry_run=True)
    aid = create_ad(asid, "creative-A", "creative_12345", dry_run=True)
    print(f"campaign={cid} adset={asid} ad={aid}")

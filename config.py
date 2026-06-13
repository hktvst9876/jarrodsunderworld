"""
config.py — strategy expressed as numbers.

Two layers of thresholds:
  CampaignThresholds — per product/campaign verdicts (KILL/ITERATE/KEEP/SCALE).
  StoreThresholds    — per store verdict (DUMP/SCALE_STORE/KEEP_TESTING/ITERATE_STORE).

Region: SG. Currency: SGD. Year-round BBQ demand (no seasonality dip).
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class CampaignThresholds:
    min_ctr: float = 0.01
    min_atc_rate: float = 0.05
    min_cvr: float = 0.01
    scale_roas_multiple: float = 1.5
    profit_gate_day: int = 7
    min_impressions_for_ctr: int = 1000
    min_sessions_for_cvr: int = 200


@dataclass(frozen=True)
class StoreThresholds:
    grace_period_days: int = 14
    hard_stop_days: int = 21
    min_total_orders_after_grace: int = 10
    min_cumulative_poas_after_grace: float = 0.7


@dataclass(frozen=True)
class BudgetCaps:
    per_store_total_sgd: float = 1500.0
    daily_ad_spend_sgd: float = 25.0
    sample_inventory_sgd: float = 100.0


CAMPAIGN = CampaignThresholds()
STORE = StoreThresholds()
BUDGET = BudgetCaps()

REGION = "SG"
NICHE_V1 = "bbq_outdoor_cooking"
STORE_NAME_V1 = "smokehousesg"
FIRST_AD_CHANNEL = "meta"

CLAUDE_REASONING_MODEL = "claude-sonnet-4-6"
CLAUDE_CHEAP_MODEL = "claude-haiku-4-5-20251001"

# -------------------------------------------------------------------------
# Brain switchboard. Maps task types -> provider name. Edit ONE row to swap.
# DECISION-class tasks (decision/narration/scoring/strategy) are LOCKED to
# providers with supports_decisions=True (currently Claude only). The router
# in llm/router.py refuses to dispatch them anywhere else.
# Other task types are free to swap to "openai" (or any registered provider).
# -------------------------------------------------------------------------
PROVIDER_MAP = {
    # Locked
    "decision":       "anthropic",
    "narration":      "anthropic",
    "scoring":        "anthropic",
    "strategy":       "anthropic",
    # Swappable — change these to "openai" to use GPT for the heavy lifting
    "creative_text":  "anthropic",
    "bulk_classify":  "anthropic",
    "trend_summary":  "anthropic",
}

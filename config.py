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

DEEPSEEK_REASONING_MODEL = "deepseek-reasoner"
DEEPSEEK_CHEAP_MODEL = "deepseek-chat"

# -------------------------------------------------------------------------
# Brain switchboard. Maps task types -> provider name. Edit ONE row to swap.
# DECISION-class tasks (decision/narration/scoring/strategy) require a
# provider with supports_decisions=True. DeepSeekProvider has this enabled.
# Switch any value to "anthropic" or "openai" to use a different provider.
# -------------------------------------------------------------------------
PROVIDER_MAP = {
    "decision":       "deepseek",
    "narration":      "deepseek",
    "scoring":        "deepseek",
    "strategy":       "deepseek",
    "creative_text":  "deepseek",
    "bulk_classify":  "deepseek",
    "trend_summary":  "deepseek",
}

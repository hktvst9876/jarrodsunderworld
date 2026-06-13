"""
core/formulas.py — pure math, no I/O. Lifted from the playbook's Formula Reference.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ProductEconomics:
    selling_price: float
    cogs: float
    fulfillment_shipping: float = 0.0
    payment_fee: float = 0.0
    platform_fee: float = 0.0


@dataclass
class CampaignMetrics:
    day: int
    ad_spend: float
    impressions: int
    clicks: int
    sessions: int
    add_to_carts: int
    orders: int
    revenue: float


def contribution_margin(e: ProductEconomics) -> float:
    return e.selling_price - e.cogs - e.fulfillment_shipping - e.payment_fee - e.platform_fee


def cm_percent(e: ProductEconomics) -> float:
    return contribution_margin(e) / e.selling_price if e.selling_price else 0.0


def break_even_roas(e: ProductEconomics) -> float:
    cmp_ = cm_percent(e)
    return (1 / cmp_) if cmp_ > 0 else float("inf")


def ctr(m: CampaignMetrics) -> float:
    return m.clicks / m.impressions if m.impressions else 0.0


def atc_rate(m: CampaignMetrics) -> float:
    return m.add_to_carts / m.sessions if m.sessions else 0.0


def cvr(m: CampaignMetrics) -> float:
    return m.orders / m.sessions if m.sessions else 0.0


def roas(m: CampaignMetrics) -> float:
    return m.revenue / m.ad_spend if m.ad_spend else 0.0


def cac(m: CampaignMetrics) -> float:
    return m.ad_spend / m.orders if m.orders else float("inf")


def poas(m: CampaignMetrics, e: ProductEconomics) -> float:
    """Profit on ad spend = (orders * CM) / ad spend."""
    return (m.orders * contribution_margin(e)) / m.ad_spend if m.ad_spend else 0.0

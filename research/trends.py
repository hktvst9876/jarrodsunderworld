"""
research/trends.py — trend signals for product scoring.

Data sources:
  1. Google Trends (via pytrends) — search volume trend direction
  2. Manual input (hardcoded for v1) — qualitative signals

fetch_google_trends(keyword) — live call, rate-limited; use sparingly.
bbq_niche_manual_signals()  — v1 hardcoded baseline; replace with scraper in v2.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class TrendSignals:
    product_name: str
    search_interest_rising: bool = False
    competition_level: str = "medium"  # low | medium | high
    seasonality: str = "year_round"     # year_round | seasonal
    reddit_mention_count: int = 0
    tiktok_search_volume_approx: int = 0
    notes: str = ""


def fetch_google_trends(keyword: str, geo: str = "SG",
                        timeframe: str = "today 3-m") -> dict:
    """
    Pull Google Trends data for a keyword in a region.

    Returns:
      {"rising": bool, "avg_interest": float, "peak_interest": int, "error": str | None}

    rising = True if the last week's interest is above the 3-month average.
    Requires pytrends. Rate-limited by Google — add delays between calls.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        return {"rising": False, "avg_interest": 0.0, "peak_interest": 0, "error": "pytrends not installed"}

    try:
        pt = TrendReq(hl="en-SG", tz=480, timeout=(10, 25))
        pt.build_payload([keyword], cat=0, timeframe=timeframe, geo=geo)
        df = pt.interest_over_time()

        if df.empty or keyword not in df.columns:
            return {"rising": False, "avg_interest": 0.0, "peak_interest": 0, "error": "no data"}

        series = df[keyword]
        avg = float(series.mean())
        peak = int(series.max())
        recent_avg = float(series.iloc[-4:].mean())  # last ~4 weeks
        rising = recent_avg > avg

        return {"rising": rising, "avg_interest": round(avg, 1),
                "peak_interest": peak, "error": None}
    except Exception as exc:
        return {"rising": False, "avg_interest": 0.0, "peak_interest": 0, "error": str(exc)}


def enrich_signals_with_trends(signals: TrendSignals, geo: str = "SG") -> TrendSignals:
    """
    Overwrite search_interest_rising with live Google Trends data.
    Falls back to the existing manual value on error.
    """
    import time
    time.sleep(1)   # polite rate-limit buffer between calls
    result = fetch_google_trends(signals.product_name, geo=geo)
    if result["error"]:
        return signals  # keep manual value
    return TrendSignals(
        product_name=signals.product_name,
        search_interest_rising=result["rising"],
        competition_level=signals.competition_level,
        seasonality=signals.seasonality,
        reddit_mention_count=signals.reddit_mention_count,
        tiktok_search_volume_approx=signals.tiktok_search_volume_approx,
        notes=signals.notes + f" [gtrends avg={result['avg_interest']} peak={result['peak_interest']}]",
    )


def bbq_niche_manual_signals() -> dict[str, TrendSignals]:
    """Hardcoded BBQ niche signals for v1 demo. Replace with scraper in v2."""
    return {
        "Disposable foil grill": TrendSignals(
            product_name="Disposable foil grill",
            search_interest_rising=True,
            competition_level="low",
            seasonality="year_round",
            reddit_mention_count=15,
            tiktok_search_volume_approx=2500,
            notes="East Coast Park + condo BBQ pits. Daiso doesn't carry. Gap exists.",
        ),
        "Cast iron restorer": TrendSignals(
            product_name="Cast iron restorer",
            search_interest_rising=False,
            competition_level="low",
            seasonality="year_round",
            reddit_mention_count=8,
            tiktok_search_volume_approx=800,
            notes="Lodge + Le Creuset fans. Small niche but passionate.",
        ),
        "Apple wood chips": TrendSignals(
            product_name="Apple wood chips",
            search_interest_rising=True,
            competition_level="medium",
            seasonality="year_round",
            reddit_mention_count=22,
            tiktok_search_volume_approx=1200,
            notes="Smoker community on r/singapore and FB groups.",
        ),
        "Silicone basting brush": TrendSignals(
            product_name="Silicone basting brush",
            search_interest_rising=False,
            competition_level="high",
            seasonality="year_round",
            reddit_mention_count=3,
            tiktok_search_volume_approx=500,
            notes="Commodity item. Many sellers.",
        ),
        "Magnetic grill thermometer": TrendSignals(
            product_name="Magnetic grill thermometer",
            search_interest_rising=True,
            competition_level="medium",
            seasonality="year_round",
            reddit_mention_count=12,
            tiktok_search_volume_approx=900,
            notes="Premium meat griller crowd. Growing.",
        ),
        "BBQ glove set": TrendSignals(
            product_name="BBQ glove set (heat-resistant)",
            search_interest_rising=False,
            competition_level="high",
            seasonality="year_round",
            reddit_mention_count=2,
            tiktok_search_volume_approx=400,
            notes="Amazon dominates.",
        ),
        "Charcoal chimney starter": TrendSignals(
            product_name="Charcoal chimney starter",
            search_interest_rising=True,
            competition_level="low",
            seasonality="year_round",
            reddit_mention_count=18,
            tiktok_search_volume_approx=600,
            notes="BBQ purists prefer this. Growing interest.",
        ),
        "Jerky-making kit": TrendSignals(
            product_name="Jerky cure + smoking kit",
            search_interest_rising=True,
            competition_level="medium",
            seasonality="year_round",
            reddit_mention_count=25,
            tiktok_search_volume_approx=1500,
            notes="DIY smoking trend growing on TikTok.",
        ),
        "Bamboo BBQ skewers": TrendSignals(
            product_name="Bamboo BBQ skewers (10-pack)",
            search_interest_rising=False,
            competition_level="high",
            seasonality="year_round",
            reddit_mention_count=1,
            tiktok_search_volume_approx=200,
            notes="Ultra-commodity. Low differentiation.",
        ),
        "BBQ meat thermometer (wireless)": TrendSignals(
            product_name="Wireless meat thermometer",
            search_interest_rising=True,
            competition_level="medium",
            seasonality="year_round",
            reddit_mention_count=20,
            tiktok_search_volume_approx=2200,
            notes="Tech-forward griller. Growing. Premium price point OK.",
        ),
    }


if __name__ == "__main__":
    signals = bbq_niche_manual_signals()
    for name, sig in signals.items():
        print(f"{name}: rising={sig.search_interest_rising}, comp={sig.competition_level}")

"""
notify.py — outbound messages that DON'T need approval (just FYI).

For the daily verdict summary the orchestrator sends each morning.
Approval flow is in approvals/telegram_bot.py.
"""

from __future__ import annotations
import json
from approvals.telegram_bot import send_message


def daily_verdict_summary(store: dict, store_verdict: dict,
                          product_verdicts: list[dict]) -> str:
    """Format the morning verdict into a readable Telegram message."""
    emoji = {
        "SCALE_STORE": "🚀", "KEEP_TESTING": "🟢",
        "ITERATE_STORE": "🟡", "DUMP": "🔴",
    }.get(store_verdict["verdict"], "ℹ️")

    metrics = store_verdict["metrics"]
    lines = [
        f"{emoji} *Day {metrics['day']} — `{store['name']}`*",
        f"verdict: *{store_verdict['verdict']}*",
        f"_{store_verdict['reason']}_",
        "",
        f"• orders: {metrics['total_orders']}",
        f"• spend: S${metrics['total_spend']:.2f}",
        f"• revenue: S${metrics['total_revenue']:.2f}",
        f"• POAS: {metrics['cumulative_poas']:.2f}",
    ]
    if product_verdicts:
        lines.append("")
        lines.append("*per product:*")
        for pv in product_verdicts:
            lines.append(f"• {pv.get('name', '?')} → {pv['verdict']}")
    return "\n".join(lines)


def send_daily_summary(store: dict, store_verdict: dict,
                       product_verdicts: list[dict]) -> None:
    send_message(daily_verdict_summary(store, store_verdict, product_verdicts))


if __name__ == "__main__":
    demo_store = {"name": "smokehousesg", "id": 1}
    demo_sv = {
        "verdict": "KEEP_TESTING",
        "reason": "Day 16: 22 orders, cumulative POAS 0.95. Within tolerance.",
        "metrics": {"day": 16, "total_orders": 22, "total_spend": 380.0,
                    "total_revenue": 720.0, "cumulative_poas": 0.95},
    }
    demo_pv = [
        {"name": "Cast iron restorer", "verdict": "KEEP"},
        {"name": "Apple wood chips",   "verdict": "ITERATE"},
    ]
    print(daily_verdict_summary(demo_store, demo_sv, demo_pv))

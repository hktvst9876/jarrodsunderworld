"""
llm/narration.py — turn deterministic verdicts into human-readable summaries.

Uses the router (llm.router) so the brain is swappable. Narration is a
DECISION-class task, so the router will reject any provider that isn't Claude.
"""

from __future__ import annotations
import json

from llm.router import ask_json, TaskType
from llm.prompts import VERDICT_NARRATION, STORE_NARRATION


def _api_key_present() -> bool:
    import os
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def narrate_campaign(decision: dict) -> dict:
    """decision: output of core.decision_engine.evaluate()"""
    if not _api_key_present():
        return _fallback(decision)

    result = ask_json(
        TaskType.NARRATION,
        system=VERDICT_NARRATION,
        user=json.dumps(decision, indent=2),
        max_tokens=300,
    )
    if "_error" in result:
        return _fallback(decision)
    return result


def narrate_store(store_verdict: dict, product_verdicts: list[dict]) -> dict:
    if not _api_key_present():
        return _fallback(store_verdict)

    payload = {"store_verdict": store_verdict, "product_verdicts": product_verdicts}
    result = ask_json(
        TaskType.NARRATION,
        system=STORE_NARRATION,
        user=json.dumps(payload, indent=2),
        max_tokens=300,
    )
    if "_error" in result:
        return _fallback(store_verdict)
    return result


def _fallback(decision: dict) -> dict:
    return {
        "summary": decision.get("reason", ""),
        "next_step": _fallback_next_step(decision.get("verdict")),
    }


def _fallback_next_step(verdict: str | None) -> str:
    return {
        "KILL": "Pause campaign. Try a new product from backlog.",
        "ITERATE": "Swap creative or fix landing page, then re-run for 3-5 more days.",
        "KEEP": "Keep gathering data. Re-evaluate tomorrow.",
        "SCALE": "Raise budget 25%. Monitor POAS daily.",
        "DUMP": "Close store. Pick next niche from backlog.",
        "SCALE_STORE": "Promote winning product. Add second ad channel.",
        "KEEP_TESTING": "No action — keep monitoring.",
        "ITERATE_STORE": "Add new SKU or refresh creatives once before dumping.",
    }.get(verdict or "", "Review metrics manually.")

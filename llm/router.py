"""
llm/router.py — the brain switchboard.

Every AI call in the codebase goes through `route()`, which:
  1. Maps a TaskType to a provider (Claude / OpenAI / others).
  2. Enforces the golden rule: DECISION-tagged tasks ONLY go to providers
     with supports_decisions=True. Today that's Claude alone.
  3. Reads the mapping from config.PROVIDER_MAP so you can swap brains
     by editing ONE line (or one env var) — no code changes elsewhere.

Swap example — use GPT-4o for creative work but keep Claude on decisions:
    # config.py
    PROVIDER_MAP = {
        TaskType.DECISION:       "anthropic",   # locked, can't change
        TaskType.NARRATION:      "anthropic",
        TaskType.SCORING:        "anthropic",
        TaskType.CREATIVE_TEXT:  "openai",      # <-- changed
        TaskType.BULK_CLASSIFY:  "openai",
        TaskType.TREND_SUMMARY:  "openai",
    }

That's it. Everything downstream keeps working.
"""

from __future__ import annotations
from enum import Enum

from llm.providers.base import AIProvider
from llm.providers.anthropic_provider import ClaudeProvider
from llm.providers.openai_provider import GPTProvider


class TaskType(str, Enum):
    # ---- Locked to Claude (decision-class) ----
    DECISION = "decision"          # any verdict-adjacent reasoning
    NARRATION = "narration"        # explains a verdict to the operator
    SCORING = "scoring"            # final product score (gates spending)
    STRATEGY = "strategy"          # next-step recommendation
    # ---- Open to any provider ----
    CREATIVE_TEXT = "creative_text"   # ad copy, captions, listing text
    BULK_CLASSIFY = "bulk_classify"   # high-volume, quality-tolerant
    TREND_SUMMARY = "trend_summary"   # summarize scraped notes


# Provider registry — add a new vendor here.
_REGISTRY: dict[str, AIProvider] = {
    "anthropic": ClaudeProvider(),
    "openai": GPTProvider(),
    # Add more here when you want them:
    # "google": GeminiProvider(),
    # "mistral": MistralProvider(),
}


# Tasks that MUST go to a provider with supports_decisions=True.
_DECISION_TASKS = {TaskType.DECISION, TaskType.NARRATION,
                   TaskType.SCORING, TaskType.STRATEGY}


# Default mapping. Override via config.PROVIDER_MAP if it exists.
_DEFAULT_MAP: dict[TaskType, str] = {
    TaskType.DECISION:       "anthropic",
    TaskType.NARRATION:      "anthropic",
    TaskType.SCORING:        "anthropic",
    TaskType.STRATEGY:       "anthropic",
    TaskType.CREATIVE_TEXT:  "anthropic",
    TaskType.BULK_CLASSIFY:  "anthropic",
    TaskType.TREND_SUMMARY:  "anthropic",
}


def _load_map() -> dict[TaskType, str]:
    """Merge config.PROVIDER_MAP (str keys) over _DEFAULT_MAP (TaskType keys)."""
    try:
        from config import PROVIDER_MAP   # type: ignore
        merged = dict(_DEFAULT_MAP)
        for k, v in PROVIDER_MAP.items():
            try:
                merged[TaskType(k)] = v
            except ValueError:
                # Unknown task name in config — ignore, use default.
                pass
        return merged
    except (ImportError, AttributeError):
        return _DEFAULT_MAP


def get_provider(task: TaskType) -> AIProvider:
    """Resolve a task type to a concrete provider, enforcing the decision lock."""
    mapping = _load_map()
    name = mapping.get(task, "anthropic")
    provider = _REGISTRY.get(name)
    if provider is None:
        raise RuntimeError(
            f"Unknown provider '{name}' for task {task.value}. "
            f"Available: {list(_REGISTRY)}"
        )
    if task in _DECISION_TASKS and not provider.supports_decisions:
        raise RuntimeError(
            f"GOLDEN RULE VIOLATION: task {task.value} routed to '{name}' which has "
            f"supports_decisions=False. Decision-class tasks must go to Claude. "
            f"Edit config.PROVIDER_MAP."
        )
    return provider


def ask_json(task: TaskType, system: str, user: str, *,
             max_tokens: int = 600, tier: str = "reasoning") -> dict:
    """Single-entry JSON call. Use this from every callsite."""
    return get_provider(task).ask_json(system, user,
                                       max_tokens=max_tokens, tier=tier)


def ask_text(task: TaskType, system: str, user: str, *,
             max_tokens: int = 400, tier: str = "reasoning") -> str:
    """Single-entry text call."""
    return get_provider(task).ask_text(system, user,
                                       max_tokens=max_tokens, tier=tier)


def status() -> dict:
    """Diagnostic: which providers are available + the current mapping."""
    mapping = _load_map()
    return {
        "providers": {n: p.available() for n, p in _REGISTRY.items()},
        "mapping": {t.value: mapping[t] for t in TaskType},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(status(), indent=2))

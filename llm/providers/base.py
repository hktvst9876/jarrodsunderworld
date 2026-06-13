"""
llm/providers/base.py — abstract interface every brain implements.

Every provider exposes the same two methods so the router can swap them
without the rest of the codebase noticing.

Adding a new brain (Mistral, Cohere, local Ollama) = subclass + register.
"""

from __future__ import annotations
from abc import ABC, abstractmethod


class AIProvider(ABC):
    """All AI providers (Claude, GPT, Gemini, ...) implement this surface."""

    name: str = "base"
    supports_decisions: bool = False   # Router refuses DECISION calls if False.

    @abstractmethod
    def ask_json(self, system: str, user: str, *,
                 max_tokens: int = 600, tier: str = "reasoning") -> dict:
        """
        Call the model and return parsed JSON.

        tier: "reasoning" (best/largest model) | "cheap" (smallest/fastest).
        Return {"_error": "..."} on failure — caller decides what to do.
        """

    @abstractmethod
    def ask_text(self, system: str, user: str, *,
                 max_tokens: int = 400, tier: str = "reasoning") -> str:
        """Plain text response (no JSON parsing)."""

    @abstractmethod
    def available(self) -> bool:
        """True if the API key is present and the SDK is importable."""

"""
llm/providers/anthropic_provider.py — Claude (Anthropic) brain.

This is the only provider with supports_decisions=True. The router enforces
the "math decides, Claude narrates" rule by refusing DECISION-tagged calls
on any other provider.
"""

from __future__ import annotations
import json
import os
import time

from llm.providers.base import AIProvider


class ClaudeProvider(AIProvider):
    name = "anthropic"
    supports_decisions = True   # Locked: only Claude can take DECISION tasks.

    def __init__(self,
                 reasoning_model: str = "claude-sonnet-4-6",
                 cheap_model: str = "claude-haiku-4-5-20251001"):
        self.reasoning_model = reasoning_model
        self.cheap_model = cheap_model
        self._client = None

    def available(self) -> bool:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return False
        try:
            import anthropic  # noqa: F401
            return True
        except ImportError:
            return False

    def _client_or_init(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _model_for(self, tier: str) -> str:
        return self.cheap_model if tier == "cheap" else self.reasoning_model

    def ask_json(self, system: str, user: str, *,
                 max_tokens: int = 600, tier: str = "reasoning") -> dict:
        import anthropic
        client = self._client_or_init()
        last_err = None
        for attempt in range(3):
            try:
                msg = client.messages.create(
                    model=self._model_for(tier),
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = msg.content[0].text.strip()
                text = text.replace("```json", "").replace("```", "").strip()
                return json.loads(text)
            except anthropic.RateLimitError as exc:
                last_err = exc
                time.sleep(2 ** attempt)
            except (anthropic.APIError, json.JSONDecodeError, IndexError) as exc:
                last_err = exc
                if attempt == 2:
                    break
                time.sleep(1)
        return {"_error": f"{type(last_err).__name__}: {last_err}"}

    def ask_text(self, system: str, user: str, *,
                 max_tokens: int = 400, tier: str = "reasoning") -> str:
        import anthropic
        client = self._client_or_init()
        try:
            msg = client.messages.create(
                model=self._model_for(tier),
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return msg.content[0].text.strip()
        except (anthropic.APIError, IndexError) as exc:
            return f"(LLM unavailable: {exc})"

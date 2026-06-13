"""
llm/providers/deepseek_provider.py — DeepSeek brain (OpenAI-compatible API).

supports_decisions = True. All task types including DECISION/NARRATION/SCORING
can route here.
"""

from __future__ import annotations
import json
import os
import time

from llm.providers.base import AIProvider


class DeepSeekProvider(AIProvider):
    name = "deepseek"
    supports_decisions = True

    def __init__(self,
                 reasoning_model: str = "deepseek-reasoner",
                 cheap_model: str = "deepseek-chat"):
        self.reasoning_model = reasoning_model
        self.cheap_model = cheap_model
        self._client = None

    def available(self) -> bool:
        if not os.environ.get("DEEPSEEK_API_KEY"):
            return False
        try:
            import openai  # noqa: F401
            return True
        except ImportError:
            return False

    def _client_or_init(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=os.environ.get("DEEPSEEK_API_KEY"),
                base_url="https://api.deepseek.com",
            )
        return self._client

    def _model_for(self, tier: str) -> str:
        return self.cheap_model if tier == "cheap" else self.reasoning_model

    def ask_json(self, system: str, user: str, *,
                 max_tokens: int = 600, tier: str = "reasoning") -> dict:
        import openai
        client = self._client_or_init()
        last_err = None
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=self._model_for(tier),
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                text = resp.choices[0].message.content.strip()
                return json.loads(text)
            except openai.RateLimitError as exc:
                last_err = exc
                time.sleep(2 ** attempt)
            except (openai.APIError, json.JSONDecodeError, IndexError, AttributeError) as exc:
                last_err = exc
                if attempt == 2:
                    break
                time.sleep(1)
        return {"_error": f"{type(last_err).__name__}: {last_err}"}

    def ask_text(self, system: str, user: str, *,
                 max_tokens: int = 400, tier: str = "reasoning") -> str:
        import openai
        client = self._client_or_init()
        try:
            resp = client.chat.completions.create(
                model=self._model_for(tier),
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content.strip()
        except (openai.APIError, IndexError, AttributeError) as exc:
            return f"(LLM unavailable: {exc})"

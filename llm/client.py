"""
llm/client.py — thin Anthropic SDK wrapper.

Centralises model selection (Sonnet for reasoning, Haiku for cheap), retries,
and defensive JSON parsing so the rest of the codebase doesn't repeat itself.
"""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CLAUDE_REASONING_MODEL, CLAUDE_CHEAP_MODEL

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def ask_json(system: str, user: str, *, cheap: bool = False,
             max_tokens: int = 600, retries: int = 2) -> dict:
    """
    Call Claude and parse the response as JSON.
    Strips markdown fences if model wraps the JSON.
    Returns {} on permanent failure (caller decides what to do).
    """
    model = CLAUDE_CHEAP_MODEL if cheap else CLAUDE_REASONING_MODEL

    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            msg = client().messages.create(
                model=model,
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
            if attempt == retries:
                break
            time.sleep(1)

    return {"_error": f"{type(last_err).__name__}: {last_err}"}


def ask_text(system: str, user: str, *, cheap: bool = False,
             max_tokens: int = 400) -> str:
    """Plain text response (no JSON parsing)."""
    model = CLAUDE_CHEAP_MODEL if cheap else CLAUDE_REASONING_MODEL
    try:
        msg = client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text.strip()
    except (anthropic.APIError, IndexError) as exc:
        return f"(LLM unavailable: {exc})"


def has_api_key() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY"))

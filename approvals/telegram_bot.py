"""
approvals/telegram_bot.py — the one-tap human-approval gate.

Two roles:
  1. push_pending_approvals() — orchestrator calls this. For every row in
     approvals with status='pending' that hasn't been posted yet, send the
     user a Telegram message with inline [Approve] / [Reject] buttons.
  2. poll_loop()              — long-running worker on your laptop (or a free
     Render/Fly.io VM later). Polls Telegram for button taps and writes the
     resolution back to the DB.

No external bot-framework dependency: raw HTTPS calls via `requests`. Keeps
the deploy story simple and the code obvious.

Setup (one time):
  1. On Telegram, message @BotFather → /newbot → save the token.
  2. Message your new bot ANY text once, then visit:
       https://api.telegram.org/bot<TOKEN>/getUpdates
     Copy the "chat":{"id":...} number — that's your TELEGRAM_CHAT_ID.
  3. Put both in .env. Done.
"""

from __future__ import annotations
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.store import (
    connect, pending_approvals, resolve_approval,
)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
API = f"https://api.telegram.org/bot{BOT_TOKEN}"
POLL_TIMEOUT_S = 25


# Risky actions that are not auto-recoverable. Used to format messages with
# stronger warnings — the bot still requires the same tap, just louder.
HIGH_STAKES = {"launch_store", "launch_product", "raise_budget", "dump_store"}


def _check_creds() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env"
        )


def send_message(text: str, parse_mode: str = "Markdown") -> dict:
    """Plain notification — daily verdict summary, errors, etc."""
    _check_creds()
    r = requests.post(
        f"{API}/sendMessage",
        json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode},
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _format_approval(approval: dict) -> str:
    payload = json.loads(approval["payload_json"]) if approval["payload_json"] else {}
    action = approval["action"]
    bang = "⚠️ *HIGH-STAKES*" if action in HIGH_STAKES else "ℹ️"
    lines = [
        f"{bang} approval #{approval['id']} — `{action}`",
        "",
    ]
    if approval.get("store_id"):
        lines.append(f"*store_id:* {approval['store_id']}")
    if approval.get("product_id"):
        lines.append(f"*product_id:* {approval['product_id']}")
    if payload:
        lines.append("*payload:*")
        lines.append("```json")
        lines.append(json.dumps(payload, indent=2))
        lines.append("```")
    return "\n".join(lines)


def _inline_keyboard(approval_id: int) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"approve:{approval_id}"},
            {"text": "❌ Reject",  "callback_data": f"reject:{approval_id}"},
        ]]
    }


def push_approval(approval: dict) -> None:
    """Send ONE approval to Telegram with inline buttons."""
    _check_creds()
    r = requests.post(
        f"{API}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": _format_approval(approval),
            "parse_mode": "Markdown",
            "reply_markup": _inline_keyboard(approval["id"]),
        },
        timeout=15,
    )
    r.raise_for_status()


def push_pending_approvals() -> int:
    """Push every still-pending approval. Idempotent enough for v1 — duplicates
    just mean the user sees the same row twice if both prompts arrive before a tap.
    Add a 'pushed_at' column later to dedupe."""
    rows = pending_approvals()
    for row in rows:
        push_approval(dict(row))
    return len(rows)


def _handle_callback(callback: dict) -> None:
    """Resolve an approval when a button is tapped, then execute if approved."""
    data = callback.get("data", "")
    if ":" not in data:
        return
    action, sid = data.split(":", 1)
    try:
        approval_id = int(sid)
    except ValueError:
        return

    status = "approved" if action == "approve" else "rejected"
    user = callback.get("from", {})
    resolved_by = f"{user.get('username') or user.get('id', 'unknown')}"

    try:
        resolve_approval(approval_id, status, resolved_by)
    except Exception as exc:
        _answer_callback(callback["id"], f"Error: {exc}")
        return

    _answer_callback(callback["id"], f"#{approval_id} → {status}")

    # Auto-execute approved actions immediately after the tap.
    if status == "approved":
        try:
            from approvals.executor import execute_one
            result = execute_one(approval_id)
            exec_note = result.get("action_required") or "Done."
            send_message(
                f"✅ #{approval_id} executed.\n_{exec_note}_",
                parse_mode="Markdown",
            )
        except Exception as exc:
            send_message(
                f"⚠️ #{approval_id} approved but execution failed:\n`{exc}`\n"
                f"Run `python main.py execute` to retry.",
                parse_mode="Markdown",
            )
    # Edit the original message to reflect resolution.
    msg = callback.get("message", {})
    if msg.get("message_id"):
        requests.post(
            f"{API}/editMessageReplyMarkup",
            json={"chat_id": CHAT_ID, "message_id": msg["message_id"],
                  "reply_markup": {"inline_keyboard": []}},
            timeout=10,
        )
        requests.post(
            f"{API}/sendMessage",
            json={"chat_id": CHAT_ID,
                  "text": f"#{approval_id} → *{status}* by `{resolved_by}`",
                  "parse_mode": "Markdown",
                  "reply_to_message_id": msg["message_id"]},
            timeout=10,
        )


def _answer_callback(callback_id: str, text: str) -> None:
    try:
        requests.post(
            f"{API}/answerCallbackQuery",
            json={"callback_query_id": callback_id, "text": text},
            timeout=10,
        )
    except requests.RequestException:
        pass


def poll_loop() -> None:
    """Long-poll Telegram for button taps. Run as a foreground process."""
    _check_creds()
    print(f"Bot polling. Chat: {CHAT_ID}. Ctrl+C to stop.")
    offset = 0
    while True:
        try:
            r = requests.get(
                f"{API}/getUpdates",
                params={"offset": offset, "timeout": POLL_TIMEOUT_S,
                        "allowed_updates": json.dumps(["callback_query", "message"])},
                timeout=POLL_TIMEOUT_S + 5,
            )
            r.raise_for_status()
            updates = r.json().get("result", [])
            for upd in updates:
                offset = upd["update_id"] + 1
                if "callback_query" in upd:
                    _handle_callback(upd["callback_query"])
                elif "message" in upd:
                    _handle_text(upd["message"])
        except requests.RequestException as exc:
            print(f"poll error: {exc}; sleeping 5s")
            time.sleep(5)


def _handle_text(message: dict) -> None:
    text = (message.get("text") or "").strip()
    if text == "/pending":
        rows = pending_approvals()
        if not rows:
            send_message("No pending approvals.")
            return
        for row in rows:
            push_approval(dict(row))
    elif text == "/status":
        send_message(_status_summary())
    elif text in ("/start", "/help"):
        send_message(
            "*Store-tester bot*\n"
            "I send you approvals before any money moves.\n\n"
            "/pending — re-send all pending approvals\n"
            "/status — current store summary\n"
        )


def _status_summary() -> str:
    """One-line snapshot of live stores. Cheap query, safe to call from phone."""
    conn = connect()
    rows = conn.execute(
        "SELECT id, name, status, launched_at, deadline_at FROM stores ORDER BY id DESC LIMIT 5"
    ).fetchall()
    conn.close()
    if not rows:
        return "No stores yet."
    lines = ["*Recent stores:*"]
    for r in rows:
        lines.append(f"• #{r['id']} `{r['name']}` — {r['status']}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Quick check: post a fake approval row to Telegram.
        from db.store import init_db, queue_approval
        init_db()
        aid = queue_approval(
            action="launch_product",
            payload={"product": "Disposable foil grill", "channel": "meta",
                     "daily_budget_sgd": 20, "creative_id": "ad_001"},
        )
        push_pending_approvals()
        print(f"Posted approval #{aid} to Telegram. Tap the button, then run poll_loop().")
    else:
        poll_loop()

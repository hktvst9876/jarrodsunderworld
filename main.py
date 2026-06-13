"""
main.py — CLI entry for the store-tester.

Commands:
  init                              Initialise SQLite DB
  score                             Score BBQ candidates → populate backlog
  status                            Print all stores + recent verdicts
  launch <product_id>               Queue launch_product approval
  daily [store_id]                  Run daily verdict loop
  dump <store_id>                   Manually queue dump_store approval
  bot                               Start Telegram approval bot poll loop
  carousell <product_id>            Generate Carousell listing draft

Examples:
  python main.py init
  python main.py score
  python main.py status
  python main.py launch 3
  python main.py daily
  python main.py bot
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows console defaults to cp1252; force UTF-8 so emoji in verdicts don't crash.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def cmd_init(_args) -> None:
    from db.store import init_db
    init_db()
    print("DB initialised.")


def cmd_score(_args) -> None:
    from scripts.score_backlog import main as run_score
    sys.argv = ["score_backlog"]
    run_score()


def cmd_status(_args) -> None:
    from db.store import connect
    conn = connect()
    stores = conn.execute("SELECT * FROM stores ORDER BY id DESC").fetchall()
    if not stores:
        print("No stores yet. Run: python main.py score")
        return
    for s in stores:
        print(f"\n=== store #{s['id']} {s['name']} ({s['status']}) ===")
        if s["launched_at"]:
            print(f"  launched {s['launched_at']}, deadline {s['deadline_at']}")
        prods = conn.execute(
            "SELECT id, name, status, score FROM products WHERE store_id=? ORDER BY score DESC",
            (s["id"],),
        ).fetchall()
        for p in prods:
            print(f"  - #{p['id']:3d} [{p['status']:8s}] {p['name']:35s} score={p['score'] or 0:5.1f}")
        latest_decision = conn.execute(
            "SELECT verdict, reason, created_at FROM decisions "
            "WHERE store_id=? AND level='store' ORDER BY created_at DESC LIMIT 1",
            (s["id"],),
        ).fetchone()
        if latest_decision:
            print(f"  latest store verdict: {latest_decision['verdict']} — {latest_decision['reason']}")
    conn.close()


def cmd_launch(args) -> None:
    from db.store import connect, queue_approval, get_store
    conn = connect()
    prod = conn.execute("SELECT * FROM products WHERE id=?", (args.product_id,)).fetchone()
    conn.close()
    if not prod:
        print(f"Product #{args.product_id} not found.")
        return

    store = get_store(prod["store_id"])
    if store["status"] == "planning":
        # Queue store launch first.
        sid = queue_approval(
            action="launch_store",
            payload={"store_name": store["name"], "niche": store["niche"]},
            store_id=store["id"],
        )
        print(f"Queued launch_store approval #{sid}")

    aid = queue_approval(
        action="launch_product",
        payload={
            "product_name": prod["name"],
            "selling_price": prod["selling_price"],
            "cogs": prod["cogs"],
            "channel": "meta",
            "daily_budget_sgd": 25.0,
        },
        store_id=prod["store_id"],
        product_id=prod["id"],
    )
    print(f"Queued launch_product approval #{aid}. Open Telegram to approve.")


def cmd_daily(args) -> None:
    from orchestrator import run_daily, run_all_live_stores
    if args.store_id:
        result = run_daily(args.store_id)
        print(json.dumps(result, indent=2, default=str))
    else:
        run_all_live_stores()


def cmd_dump(args) -> None:
    from db.store import queue_approval, get_store
    store = get_store(args.store_id)
    if not store:
        print(f"Store #{args.store_id} not found.")
        return
    aid = queue_approval(
        action="dump_store",
        payload={"reason": "Manual dump requested via CLI"},
        store_id=args.store_id,
    )
    print(f"Queued dump_store approval #{aid} for store #{args.store_id}.")


def cmd_bot(_args) -> None:
    from approvals.telegram_bot import poll_loop
    poll_loop()


def cmd_execute(args) -> None:
    from approvals.executor import execute_approved_actions
    results = execute_approved_actions(dry_run=args.dry_run)
    import json
    print(json.dumps(results, indent=2, default=str))


def cmd_creative(args) -> None:
    from db.store import connect
    from llm.creative import generate_creative
    conn = connect()
    prod = conn.execute("SELECT * FROM products WHERE id=?", (args.product_id,)).fetchone()
    conn.close()
    if not prod:
        print(f"Product #{args.product_id} not found.")
        return
    angles = generate_creative(dict(prod))
    for i, angle in enumerate(angles, 1):
        print(f"\n--- Angle {i}: {angle.get('name')} ---")
        print(f"Hook:    {angle.get('hook')}")
        print(f"Script:  {angle.get('script')}")
        print(f"Caption: {angle.get('caption')}")


def cmd_carousell(args) -> None:
    from db.store import connect
    from integrations.carousell_helper import draft_listing, write_draft_file
    conn = connect()
    prod = conn.execute("SELECT * FROM products WHERE id=?", (args.product_id,)).fetchone()
    conn.close()
    if not prod:
        print(f"Product #{args.product_id} not found.")
        return
    product_dict = {
        "name": prod["name"],
        "selling_price": prod["selling_price"],
        "description": "",  # populate when Shopify integration runs
        "image_urls": [],
    }
    listing = draft_listing(product_dict)
    path = write_draft_file(product_dict, listing)
    print(f"Carousell draft saved to {path}")


def main() -> None:
    p = argparse.ArgumentParser(prog="store-tester")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Initialise DB").set_defaults(func=cmd_init)
    sub.add_parser("score", help="Score BBQ candidates").set_defaults(func=cmd_score)
    sub.add_parser("status", help="Show all stores + recent verdicts").set_defaults(func=cmd_status)
    sub.add_parser("bot", help="Start Telegram approval bot").set_defaults(func=cmd_bot)

    execute_p = sub.add_parser("execute", help="Execute all approved actions")
    execute_p.add_argument("--dry-run", action="store_true",
                           help="Preview without calling any API")
    execute_p.set_defaults(func=cmd_execute)

    creative_p = sub.add_parser("creative", help="Generate ad creative angles for a product")
    creative_p.add_argument("product_id", type=int)
    creative_p.set_defaults(func=cmd_creative)

    launch = sub.add_parser("launch", help="Queue launch_product approval")
    launch.add_argument("product_id", type=int)
    launch.set_defaults(func=cmd_launch)

    daily = sub.add_parser("daily", help="Run daily verdict loop")
    daily.add_argument("store_id", type=int, nargs="?")
    daily.set_defaults(func=cmd_daily)

    dump = sub.add_parser("dump", help="Manually queue dump_store")
    dump.add_argument("store_id", type=int)
    dump.set_defaults(func=cmd_dump)

    car = sub.add_parser("carousell", help="Draft a Carousell listing")
    car.add_argument("product_id", type=int)
    car.set_defaults(func=cmd_carousell)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

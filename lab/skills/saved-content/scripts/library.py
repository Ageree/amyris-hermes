#!/usr/bin/env python3
"""Saved-content item store. One JSON file, atomic rewrites, pure-function updates."""
import argparse, json, os, sys, tempfile
from datetime import datetime, timedelta

INTERVALS_DAYS = [1, 3, 7]      # FR-010 cadence; index past end => archive
MAX_IGNORES = 3                 # FR-012

def load(db):
    if not os.path.exists(db):
        return []
    with open(db) as f:
        return json.load(f)

def save(db, items):
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(db)) or ".")
    with os.fdopen(fd, "w") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    os.replace(tmp, db)

def make_item(items, url, essence, steps, category, now):
    due = (datetime.fromisoformat(now) + timedelta(days=INTERVALS_DAYS[0])).isoformat()
    return {"id": (max((i["id"] for i in items), default=0) + 1),
            "url": url, "essence": essence, "steps": steps, "category": category,
            "saved_at": now,
            "resurface": {"interval_index": 0, "next_due": due, "ignores": 0, "archived": False}}

def cmd_add(a):
    items = load(a.db)
    item = make_item(items, a.url, a.essence, json.loads(a.steps), a.category, a.now)
    save(a.db, items + [item])
    return item

def cmd_list(a):
    return load(a.db)

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add")
    for f in ("--url", "--essence", "--steps", "--category", "--now"):
        pa.add_argument(f, required=True)
    sub.add_parser("list")
    for sp in sub.choices.values():
        sp.add_argument("--db", default=os.path.expanduser("~/.hermes/saved-content/items.json"))
    a = p.parse_args()
    print(json.dumps({"add": cmd_add, "list": cmd_list}[a.cmd](a), ensure_ascii=False))

if __name__ == "__main__":
    main()

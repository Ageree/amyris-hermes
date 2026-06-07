#!/usr/bin/env python3
"""Saved-content item store. One JSON file, atomic rewrites, pure-function updates."""
import argparse, json, os, tempfile
from datetime import datetime, timedelta

INTERVALS_DAYS = [1, 3, 7]      # FR-010 cadence; index past end => archive
MAX_IGNORES = 3                 # FR-012


def default_db() -> str:
    """Return the default DB path, honoring HERMES_HOME for per-container isolation."""
    home = os.environ.get("HERMES_HOME") or os.path.expanduser("~/.hermes")
    return os.path.join(home, "saved-content", "items.json")

def load(db):
    if not os.path.exists(db):
        return []
    with open(db) as f:
        return json.load(f)

def save(db, items):
    d = os.path.dirname(os.path.abspath(db))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d)
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

def _with_resurface(item, **changes):
    return {**item, "resurface": {**item["resurface"], **changes}}

def cmd_due(a):
    items, now = load(a.db), a.now
    due = [i for i in items if not i["resurface"]["archived"]
           and i["resurface"]["next_due"] <= now]
    def bump(i):
        ign = i["resurface"]["ignores"] + 1
        if ign >= MAX_IGNORES:
            return _with_resurface(i, ignores=ign, archived=True)
        days = INTERVALS_DAYS[i["resurface"]["interval_index"]]
        nxt = (datetime.fromisoformat(now) + timedelta(days=days)).isoformat()
        return _with_resurface(i, ignores=ign, next_due=nxt)
    due_ids = {i["id"] for i in due}
    save(a.db, [bump(i) if i["id"] in due_ids else i for i in items])
    return due

def cmd_engage(a):
    items, iid = load(a.db), int(a.id)
    def adv(i):
        idx = i["resurface"]["interval_index"] + 1
        if idx >= len(INTERVALS_DAYS):
            return _with_resurface(i, interval_index=idx, ignores=0, archived=True)
        nxt = (datetime.fromisoformat(a.now) + timedelta(days=INTERVALS_DAYS[idx])).isoformat()
        return _with_resurface(i, interval_index=idx, ignores=0, next_due=nxt)
    new = [adv(i) if i["id"] == iid else i for i in items]
    save(a.db, new)
    match = next((i for i in new if i["id"] == iid), None)
    if match is None:
        raise SystemExit(f"id {iid} not found")
    return match

def cmd_archive(a):
    items, iid = load(a.db), int(a.id)
    new = [_with_resurface(i, archived=True) if i["id"] == iid else i for i in items]
    save(a.db, new)
    match = next((i for i in new if i["id"] == iid), None)
    if match is None:
        raise SystemExit(f"id {iid} not found")
    return match

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    pa = sub.add_parser("add")
    for f in ("--url", "--essence", "--steps", "--category", "--now"):
        pa.add_argument(f, required=True)
    sub.add_parser("list")
    pd = sub.add_parser("due")
    pd.add_argument("--now", required=True)
    pe = sub.add_parser("engage")
    pe.add_argument("--id", required=True)
    pe.add_argument("--now", required=True)
    par = sub.add_parser("archive")
    par.add_argument("--id", required=True)
    for sp in sub.choices.values():
        sp.add_argument("--db", default=default_db())
    a = p.parse_args()
    print(json.dumps({"add": cmd_add, "list": cmd_list,
                      "due": cmd_due, "engage": cmd_engage, "archive": cmd_archive}[a.cmd](a),
                     ensure_ascii=False))

if __name__ == "__main__":
    main()

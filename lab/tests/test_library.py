import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "skills/saved-content/scripts/library.py"

def run(args, db):
    out = subprocess.run([sys.executable, str(SCRIPT), *args, "--db", str(db)],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)

def test_add_returns_item_with_id_and_resurface_state(tmp_path):
    db = tmp_path / "items.json"
    item = run(["add", "--url", "https://x.com/a/status/1", "--essence", "Бэклинки через Common Crawl",
                "--steps", '["установить пакет","запустить скрипт"]', "--category", "dev",
                "--now", "2026-06-07T12:00:00"], db)
    assert item["id"] == 1
    assert item["url"] == "https://x.com/a/status/1"
    assert item["resurface"] == {"interval_index": 0, "next_due": "2026-06-08T12:00:00",
                                 "ignores": 0, "archived": False}

def test_list_returns_all_items(tmp_path):
    db = tmp_path / "items.json"
    run(["add", "--url", "u1", "--essence", "e1", "--steps", "[]", "--category", "c",
         "--now", "2026-06-07T12:00:00"], db)
    run(["add", "--url", "u2", "--essence", "e2", "--steps", "[]", "--category", "c",
         "--now", "2026-06-07T12:00:00"], db)
    items = run(["list"], db)
    assert [i["id"] for i in items] == [1, 2]

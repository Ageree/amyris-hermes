import json, os, subprocess, sys
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


def _add(db, now="2026-06-07T12:00:00"):
    return run(["add", "--url", "u", "--essence", "e", "--steps", "[]",
                "--category", "c", "--now", now], db)

def test_due_returns_item_after_interval_and_counts_ignore(tmp_path):
    db = tmp_path / "items.json"
    _add(db)                                                   # next_due = 06-08T12:00
    assert run(["due", "--now", "2026-06-08T11:00:00"], db) == []
    due = run(["due", "--now", "2026-06-08T13:00:00"], db)
    assert len(due) == 1 and due[0]["id"] == 1
    item = run(["list"], db)[0]
    assert item["resurface"]["ignores"] == 1
    assert item["resurface"]["next_due"] == "2026-06-09T13:00:00"   # same 1d interval again

def test_three_ignores_archives_item(tmp_path):
    db = tmp_path / "items.json"
    _add(db)
    run(["due", "--now", "2026-06-08T13:00:00"], db)
    run(["due", "--now", "2026-06-09T14:00:00"], db)
    run(["due", "--now", "2026-06-10T15:00:00"], db)
    assert run(["list"], db)[0]["resurface"]["archived"] is True
    assert run(["due", "--now", "2026-06-30T12:00:00"], db) == []

def test_engage_advances_interval_and_resets_ignores(tmp_path):
    db = tmp_path / "items.json"
    _add(db)
    run(["due", "--now", "2026-06-08T13:00:00"], db)           # ignores=1
    out = run(["engage", "--id", "1", "--now", "2026-06-08T14:00:00"], db)
    r = out["resurface"]
    assert r == {"interval_index": 1, "next_due": "2026-06-11T14:00:00",
                 "ignores": 0, "archived": False}              # 3d interval

def test_engage_past_last_interval_archives(tmp_path):
    db = tmp_path / "items.json"
    _add(db)
    run(["engage", "--id", "1", "--now", "2026-06-08T14:00:00"], db)  # -> 3d
    run(["engage", "--id", "1", "--now", "2026-06-11T15:00:00"], db)  # -> 7d
    out = run(["engage", "--id", "1", "--now", "2026-06-18T16:00:00"], db)
    assert out["resurface"]["archived"] is True

def test_archive_command(tmp_path):
    db = tmp_path / "items.json"
    _add(db)
    out = run(["archive", "--id", "1"], db)
    assert out["resurface"]["archived"] is True

def test_engage_unknown_id_errors_cleanly(tmp_path):
    db = tmp_path / "items.json"
    _add(db)
    out = subprocess.run([sys.executable, str(SCRIPT), "engage", "--id", "999",
                          "--now", "2026-06-08T14:00:00", "--db", str(db)],
                         capture_output=True, text=True)
    assert out.returncode != 0
    assert "999" in out.stderr and "not found" in out.stderr
    assert "Traceback" not in out.stderr


# --- TDD: default_db() must honor HERMES_HOME (fleet isolation fix) ---

sys.path.insert(0, str(SCRIPT.parent))
from library import default_db


def test_default_db_falls_back_to_dot_hermes(monkeypatch):
    """Without HERMES_HOME set, default_db() returns ~/.hermes/saved-content/items.json."""
    monkeypatch.delenv("HERMES_HOME", raising=False)
    result = default_db()
    expected = os.path.join(os.path.expanduser("~/.hermes"), "saved-content", "items.json")
    assert result == expected


def test_default_db_respects_hermes_home(tmp_path, monkeypatch):
    """With HERMES_HOME=X, default_db() returns X/saved-content/items.json."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    result = default_db()
    assert result == str(tmp_path / "saved-content" / "items.json")


def test_add_without_db_flag_writes_to_hermes_home(tmp_path, monkeypatch):
    """A no-`--db` add subprocess writes to HERMES_HOME/saved-content/items.json."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    env = {**os.environ, "HERMES_HOME": str(tmp_path)}
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "add",
         "--url", "https://example.com/1",
         "--essence", "fleet isolation test",
         "--steps", "[]",
         "--category", "test",
         "--now", "2026-06-08T10:00:00"],
        capture_output=True, text=True, env=env,
    )
    assert out.returncode == 0, out.stderr
    db_path = tmp_path / "saved-content" / "items.json"
    assert db_path.exists(), f"Expected db at {db_path}"
    items = json.loads(db_path.read_text())
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/1"

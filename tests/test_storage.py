"""The SQLite storage layer: migrations, keeping history, privacy (clear)."""
import sqlite3

import pytest

from jarvis import storage


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    yield
    storage.close()


def test_new_database_gets_every_migration():
    c = storage.conn()
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(storage.MIGRATIONS)


def test_old_database_is_upgraded_without_losing_rows(tmp_path):
    db = tmp_path / "assistant.db"
    c = sqlite3.connect(db)
    c.executescript(storage.MIGRATIONS[0])
    c.execute("PRAGMA user_version = 1")
    c.execute("INSERT INTO events(type, data) VALUES ('user', '{\"type\": \"user\", \"text\": \"old\"}')")
    c.commit()
    c.close()
    assert storage.migrate(sqlite3.connect(db)) == len(storage.MIGRATIONS)
    assert storage.recent_events()[0]["text"] == "old"


def test_history_survives_and_skips_noise():
    storage.add_event({"type": "user", "text": "hello"})
    storage.add_event({"type": "level", "v": 0.3})           # not kept
    storage.add_event({"type": "confirm", "question": "x"})  # approval prompts are never replayed
    storage.add_event({"type": "jarvis", "text": "hi!"})
    storage.close()                                           # like an app restart
    evs = storage.recent_events()
    assert [e["type"] for e in evs] == ["user", "jarvis"] and evs[0]["date"]


def test_clear_history():
    storage.add_event({"type": "user", "text": "private"})
    assert storage.clear_events() == 1 and storage.count_events() == 0

"""Local database (SQLite, assistant.db in the data folder).

Things that grow over time and need searching live here instead of JSON files. The schema has numbered
migrations (PRAGMA user_version), so a newer app upgrades an older database in place and never loses data.
Everything stays on this PC.

Tables
- events: the conversation and activity history (what you said, the answers, actions taken), so the
  Conversations page and the Activity feed survive a restart.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

_LOCK = threading.RLock()
_CONN: sqlite3.Connection | None = None
_PATH: Path | None = None

MIGRATIONS: list[str] = [
    # 1: conversation + activity history
    """CREATE TABLE events (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
           type TEXT NOT NULL,
           data TEXT NOT NULL);
       CREATE INDEX events_type ON events(type);""",
]

# event types worth keeping across restarts (not live captions, levels, approval prompts...)
KEEP_TYPES = {"user", "jarvis", "tool", "tool_result", "notify", "error"}


def path() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "assistant.db"


def conn() -> sqlite3.Connection:
    """The shared connection (opened and upgraded on first use)."""
    global _CONN, _PATH
    with _LOCK:
        p = path()
        if _CONN is None or _PATH != p:
            p.parent.mkdir(parents=True, exist_ok=True)
            c = sqlite3.connect(p, check_same_thread=False, timeout=10)
            c.execute("PRAGMA journal_mode=WAL")
            migrate(c)
            _CONN, _PATH = c, p
        return _CONN


def migrate(c: sqlite3.Connection) -> int:
    """Apply any migrations this database hasn't had yet. Returns the schema version."""
    version = c.execute("PRAGMA user_version").fetchone()[0]
    for n, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        with c:                                   # each migration is all-or-nothing
            c.executescript(sql)
            c.execute(f"PRAGMA user_version = {n}")
    return c.execute("PRAGMA user_version").fetchone()[0]


def close() -> None:
    global _CONN, _PATH
    with _LOCK:
        if _CONN is not None:
            _CONN.close()
        _CONN = _PATH = None


# ---------------- events (history) ----------------
def add_event(ev: dict) -> None:
    if ev.get("type") not in KEEP_TYPES:
        return
    try:
        with _LOCK:
            c = conn()
            with c:
                c.execute("INSERT INTO events(type, data) VALUES (?, ?)", (ev["type"], json.dumps(ev, ensure_ascii=False)))
    except sqlite3.Error as e:
        print(f"[storage] couldn't save an event: {e}")


def recent_events(n: int = 200) -> list[dict]:
    """The last n kept events, oldest first, each with 'date' (YYYY-MM-DD) added."""
    try:
        with _LOCK:
            rows = conn().execute("SELECT at, data FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    except sqlite3.Error as e:
        print(f"[storage] couldn't read the history: {e}")
        return []
    out = []
    for at, data in reversed(rows):
        try:
            ev = json.loads(data)
        except json.JSONDecodeError:
            continue
        ev["date"] = at[:10]
        out.append(ev)
    return out


def update_text(event_id: str, text: str) -> None:
    """A message was rewritten (e.g. into Urdu script): keep the new text."""
    try:
        with _LOCK:
            c = conn()
            with c:
                c.execute("UPDATE events SET data = json_set(data, '$.text', ?) WHERE json_extract(data, '$.id') = ?",
                          (text, event_id))
    except sqlite3.Error as e:
        print(f"[storage] couldn't update an event: {e}")


def clear_events() -> int:
    with _LOCK:
        c = conn()
        with c:
            n = c.execute("DELETE FROM events").rowcount
        c.execute("VACUUM")
    return n


def count_events() -> int:
    with _LOCK:
        return conn().execute("SELECT COUNT(*) FROM events").fetchone()[0]

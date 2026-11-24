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
    # 2: long-term memories (moved here from memory.json, which is kept as memory.json.imported)
    """CREATE TABLE memories (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           fact TEXT NOT NULL,
           category TEXT NOT NULL DEFAULT 'other',
           importance INTEGER NOT NULL DEFAULT 1,        -- 1 normal, 2 important, 3 key
           source TEXT NOT NULL DEFAULT 'assistant',     -- you | assistant | suggested | imported
           created TEXT NOT NULL,
           updated TEXT NOT NULL,
           uses INTEGER NOT NULL DEFAULT 0);
       CREATE INDEX memories_category ON memories(category);""",
    # 3: skills = your own instructions: "always" rules (every reply) or routines you run by name
    """CREATE TABLE skills (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL UNIQUE COLLATE NOCASE,
           instructions TEXT NOT NULL,
           mode TEXT NOT NULL DEFAULT 'ask',             -- always | ask
           enabled INTEGER NOT NULL DEFAULT 1,
           created TEXT NOT NULL,
           updated TEXT NOT NULL,
           uses INTEGER NOT NULL DEFAULT 0);""",
    # 4: workspaces = saved window layouts ("Study": Chrome on the left, VS Code on the right)
    """CREATE TABLE workspaces (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL UNIQUE COLLATE NOCASE,
           layout TEXT NOT NULL,                         -- JSON list of windows (app, exe, place on screen)
           created TEXT NOT NULL,
           updated TEXT NOT NULL,
           uses INTEGER NOT NULL DEFAULT 0);""",
    # 5: automations = several safe steps under one name, run by hand, at a time, or when the app opens
    """CREATE TABLE automations (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL UNIQUE COLLATE NOCASE,
           steps TEXT NOT NULL,                          -- JSON list of steps (see automations.py)
           trigger TEXT NOT NULL,                        -- JSON: manual | time | startup
           enabled INTEGER NOT NULL DEFAULT 0,
           created TEXT NOT NULL,
           updated TEXT NOT NULL,
           last_run TEXT,
           last_ok INTEGER,
           last_result TEXT,
           last_day TEXT,                                -- the day its timed run last started (once a day)
           runs INTEGER NOT NULL DEFAULT 0);""",
    # 6: your own agents (the ready-made ones are in agents.py)
    """CREATE TABLE agents (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL UNIQUE COLLATE NOCASE,
           role TEXT NOT NULL,
           tools TEXT NOT NULL,                          -- JSON list, checked again on every run
           memory INTEGER NOT NULL DEFAULT 0,            -- may see your memories
           created TEXT NOT NULL,
           updated TEXT NOT NULL,
           runs INTEGER NOT NULL DEFAULT 0);""",
    # 7: planner (see planner.py): tasks and the calendar
    """CREATE TABLE tasks (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           title TEXT NOT NULL,
           notes TEXT NOT NULL DEFAULT '',
           project TEXT NOT NULL DEFAULT '',
           due TEXT,                                     -- a day or a moment, local time
           priority INTEGER NOT NULL DEFAULT 1,          -- 1 normal, 2 important, 3 urgent
           done INTEGER NOT NULL DEFAULT 0,
           done_at TEXT,
           reminded TEXT,                                -- the due time it was reminded of
           created TEXT NOT NULL,
           updated TEXT NOT NULL);
       CREATE TABLE calendar (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           title TEXT NOT NULL,
           place TEXT NOT NULL DEFAULT '',
           notes TEXT NOT NULL DEFAULT '',
           start TEXT NOT NULL,
           end TEXT NOT NULL,
           all_day INTEGER NOT NULL DEFAULT 0,
           repeat TEXT NOT NULL DEFAULT 'none',
           until TEXT,
           remind INTEGER,                               -- minutes before; NULL = no reminder
           reminded TEXT,                                -- the start it was last reminded of
           created TEXT NOT NULL,
           updated TEXT NOT NULL);""",
    # 8: word index of the documents in the folders you chose (see docindex.py)
    """CREATE TABLE doc_folders (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           path TEXT NOT NULL UNIQUE COLLATE NOCASE,
           added TEXT NOT NULL);
       CREATE TABLE docs (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           path TEXT NOT NULL UNIQUE COLLATE NOCASE,
           folder INTEGER NOT NULL,
           mtime INTEGER NOT NULL,
           size INTEGER NOT NULL,
           read_at TEXT NOT NULL,
           error TEXT NOT NULL DEFAULT '');
       CREATE VIRTUAL TABLE doc_text USING fts5(text, doc UNINDEXED, part UNINDEXED, tokenize = 'unicode61 remove_diacritics 2');""",
    # 9: goals, habits, journal, money (see life.py); amounts are hundredths
    """CREATE TABLE goals (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           title TEXT NOT NULL,
           why TEXT NOT NULL DEFAULT '',
           area TEXT NOT NULL DEFAULT '',
           target REAL,
           progress REAL NOT NULL DEFAULT 0,
           unit TEXT NOT NULL DEFAULT '',
           due TEXT,
           steps TEXT NOT NULL DEFAULT '[]',
           done INTEGER NOT NULL DEFAULT 0,
           done_at TEXT,
           created TEXT NOT NULL);
       CREATE TABLE habits (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL,
           per_week INTEGER NOT NULL DEFAULT 7,
           remind TEXT NOT NULL DEFAULT '',
           reminded TEXT,
           created TEXT NOT NULL);
       CREATE TABLE habit_log (
           habit INTEGER NOT NULL,
           day TEXT NOT NULL,
           PRIMARY KEY (habit, day)) WITHOUT ROWID;
       CREATE TABLE journal (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           day TEXT NOT NULL,
           mood INTEGER,
           text TEXT NOT NULL DEFAULT '',
           created TEXT NOT NULL);
       CREATE INDEX journal_day ON journal(day);
       CREATE TABLE money (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           day TEXT NOT NULL,
           kind TEXT NOT NULL CHECK (kind IN ('in', 'out')),
           amount INTEGER NOT NULL CHECK (amount > 0),
           category TEXT NOT NULL,
           note TEXT NOT NULL DEFAULT '',
           bill INTEGER,
           bill_month TEXT,
           created TEXT NOT NULL);
       CREATE INDEX money_day ON money(day);
       CREATE TABLE budgets (
           category TEXT PRIMARY KEY COLLATE NOCASE,
           amount INTEGER NOT NULL);
       CREATE TABLE bills (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL,
           amount INTEGER NOT NULL,
           category TEXT NOT NULL,
           due INTEGER NOT NULL,
           remind INTEGER NOT NULL DEFAULT 2,
           start TEXT NOT NULL,                           -- the first month to pay
           reminded TEXT,
           created TEXT NOT NULL);""",
    # 10: clock (timers, stopwatch, focus minutes) and news (own sources, stories kept)
    """CREATE TABLE timers (
           id INTEGER PRIMARY KEY,                         -- numbers are used again: "timer 1" stays easy to say
           kind TEXT NOT NULL,
           label TEXT NOT NULL,
           total REAL NOT NULL,
           due REAL,                                       -- running: the moment it ends
           left REAL,                                      -- paused: the seconds it has left
           extra TEXT NOT NULL DEFAULT '{}');
       CREATE TABLE stopwatch (
           id INTEGER PRIMARY KEY CHECK (id = 1),
           started REAL,
           banked REAL NOT NULL DEFAULT 0,
           laps TEXT NOT NULL DEFAULT '[]');
       CREATE TABLE focus_log (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           day TEXT NOT NULL,
           minutes INTEGER NOT NULL,
           label TEXT NOT NULL DEFAULT '');
       CREATE INDEX focus_day ON focus_log(day);
       CREATE TABLE news_feeds (
           id INTEGER PRIMARY KEY AUTOINCREMENT,
           name TEXT NOT NULL,
           url TEXT NOT NULL UNIQUE);
       CREATE TABLE news_saved (
           link TEXT PRIMARY KEY,
           title TEXT NOT NULL,
           source TEXT NOT NULL DEFAULT '',
           about TEXT NOT NULL DEFAULT '',
           at TEXT NOT NULL DEFAULT '',
           saved TEXT NOT NULL,
           read INTEGER NOT NULL DEFAULT 0);""",
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

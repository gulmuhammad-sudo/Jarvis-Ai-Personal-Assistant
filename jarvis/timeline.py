"""The timeline: everything that happened, day by day, from the records the app keeps anyway: the conversation
(assistant.db), the record of actions and approvals (audit.log) and the uses of the microphone and the screen.
Search, take one thing or a day out of the conversation, your most used requests, and a CSV.

The record of actions can only be cleared as a whole (privacy.clear), and that leaves a line saying so.
"""
from __future__ import annotations

import csv
import json
import os
import re
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from . import privacy

KINDS = {"you": "You", "answer": "Answers", "action": "Actions", "approval": "Approvals", "reminder": "Reminders", "change": "Changes", "use": "Microphone and screen", "error": "Problems"}
_EVENTS = {"user": "you", "jarvis": "answer", "notify": "reminder", "error": "error"}
_TALK = {"you", "answer", "reminder", "error"}
_RECORD = {"action", "approval", "change"}
MAX_DAY, MAX_FOUND = 600, 200
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple, list[dict]]] = {}

_WORDS = {
    "emergency_stop": "Stop was pressed", "history_cleared": "The conversation history was cleared", "permission_changed": "A permission was changed", "record_cleared": "The record of actions was cleared",
    "cleared": "Something kept was cleared", "keeping_changed": "How long things are kept was changed", "old_things_cleared": "Old things were cleared", "mail_connected": "Gmail was connected",
    "mail_disconnected": "Gmail was disconnected", "journal_ai": "Who may read the journal was changed", "fitness_ai": "Who may read the fitness notes was changed", "meeting_writing_started": "A meeting is written down",
    "meeting_writing_ended": "A meeting isn't written down any more", "screen_recording_started": "A screen recording started", "screen_recording_ended": "The screen recording ended", "image_made_online": "A picture was made online",
    "agent_start": "An agent started", "agent_end": "An agent finished", "automation_start": "An automation started", "automation_end": "An automation finished", "timeline_removed": "Taken out of the conversation history",
    "permission_hour": "A permission was given for an hour", "permissions_asked_again": "All permissions ask again",
}


def day(value: Any) -> str:
    """A real day, YYYY-MM-DD."""
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise ValueError("That isn't a day.") from None


def _next(d: str) -> str:
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def _record() -> list[dict]:
    """The record of actions, oldest first (read again only when the file changed)."""
    from . import audit
    out: list[dict] = []
    with _LOCK:
        for f in (audit.file().with_name("audit.old.log"), audit.file()):
            try:
                st = f.stat()
                sig = (st.st_mtime_ns, st.st_size)
                if _CACHE.get(str(f), (None, []))[0] != sig:
                    rows = []
                    for line in audit._lines(f):
                        try:
                            e = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(e, dict) and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", str(e.get("time") or "")):
                            rows.append(e)
                    _CACHE[str(f)] = (sig, rows)
                out += _CACHE[str(f)][1]
            except OSError:
                _CACHE.pop(str(f), None)
    return out


def _line(e: dict) -> dict:
    """One line of the record, for people."""
    ev, rest = str(e.get("event") or ""), {k: v for k, v in e.items() if k not in ("time", "event")}
    more = "\n".join(f"{k}: {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}" for k, v in rest.items() if v not in (None, "", {}, []))
    if ev == "tool":
        args = e.get("args") if isinstance(e.get("args"), dict) else {}
        text = ", ".join(f"{k}: {v}" for k, v in args.items() if v not in (None, "", "…"))
        return {"kind": "action", "title": str(e.get("tool") or "").replace("_", " "), "text": text[:300], "ok": bool(e.get("ok")), "more": more}
    if ev == "approval":
        return {"kind": "approval", "title": "Allowed" if e.get("granted") else "Not allowed", "text": str(e.get("question") or "")[:300], "ok": bool(e.get("granted")), "more": more}
    if ev == "blocked":
        return {"kind": "approval", "title": "Refused", "text": f"{e.get('tool') or ''}: {e.get('reason') or ''}"[:300], "ok": False, "more": more}
    title = "Local only was turned " + ("on" if e.get("on") else "off") if ev == "local_only" else _WORDS.get(ev) or ev.replace("_", " ").capitalize()
    text = "" if ev == "local_only" else ", ".join(str(v) for v in rest.values() if isinstance(v, (str, int, float)) and not isinstance(v, bool) and v != "")
    return {"kind": "action" if ev.startswith(("agent_", "automation_start", "automation_end")) else "change", "title": title, "text": text[:300], "ok": e.get("ok") is not False, "more": more}


def _events(where: str = "", args: tuple = (), limit: int = 5000) -> list[dict]:
    from . import storage
    with storage._LOCK:
        rows = storage.conn().execute(f"SELECT id, at, type, data FROM events WHERE type IN ('user', 'jarvis', 'notify', 'error') {where} ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    out = []
    for i, at, kind, data in rows:
        try:
            ev = json.loads(data)
        except json.JSONDecodeError:
            continue
        text = str(ev.get("text") or ev.get("message") or "")
        if text:
            out.append({"id": f"e{i}", "at": at, "kind": _EVENTS[kind], "title": {"user": "You", "jarvis": str(ev.get("provider") or "Answer"), "notify": "Reminder", "error": "Problem"}[kind], "text": text,
                        "ok": kind != "error", "more": "", "how": str(ev.get("source") or "") if kind == "user" else ""})
    return out


def _uses(where: str, args: tuple) -> list[dict]:
    from . import storage
    with storage._LOCK:
        rows = storage.conn().execute(f"SELECT id, what, why, start, end FROM sensor_log WHERE {where} ORDER BY id DESC LIMIT 1000", args).fetchall()
    out = []
    for i, what, why, start, stop in rows:
        sec = privacy.seconds(start, stop)
        long = f"{sec // 3600} h {sec % 3600 // 60} min" if sec >= 3600 else f"{sec // 60} min" if sec >= 60 else f"{sec} s" if sec else ""
        out.append({"id": f"u{i}", "at": start, "kind": "use", "title": {"mic": "Microphone", "screen": "Screen", "clipboard": "Clipboard"}.get(what, what), "text": why + (f" ({long})" if long else ""), "ok": True, "more": ""})
    return out


def _from_record() -> list[dict]:
    return [{"id": f"a{i}", "at": e["time"], **_line(e)} for i, e in enumerate(_record())]


def _kinds(value: Any) -> set[str]:
    return {k for k in value if k in KINDS} if isinstance(value, list) and value else set(KINDS)


def _sorted(rows: list[dict]) -> list[dict]:
    return sorted(rows, key=lambda r: (r["at"], int(r["id"][1:])), reverse=True)


def of_day(d: Any, kinds: Any = None) -> list[dict]:
    """One day, newest first."""
    d, want, rows = day(d), _kinds(kinds), []
    if want & _TALK:
        rows += _events("AND at >= ? AND at < ?", (d, _next(d)))
    if "use" in want:
        rows += _uses("start >= ? AND start < ?", (d, _next(d)))
    if want & _RECORD:
        rows += [{"id": f"a{i}", "at": e["time"], **_line(e)} for i, e in enumerate(_record()) if e["time"].startswith(d)]
    return _sorted([r for r in rows if r["kind"] in want])[:MAX_DAY]


def search(words: Any, kinds: Any = None) -> list[dict]:
    """Everything with all these words, newest first."""
    ws = [w.casefold() for w in str(words or "").split()[:10]]
    if not ws:
        raise ValueError("What should I look for?")
    want, rows = _kinds(kinds), []
    if want & _TALK:
        rows += _events(limit=20000)
    if "use" in want:
        rows += _uses("1 = 1", ())
    if want & _RECORD:
        rows += _from_record()
    return _sorted([r for r in rows if r["kind"] in want and all(w in f"{r['title']} {r['text']} {r['more']}".casefold() for w in ws)])[:MAX_FOUND]


def days(n: int = 35, today: date | None = None) -> list[dict]:
    """How much there is on each of the last days (for the strip), oldest first."""
    from . import storage
    today = today or date.today()
    line = [(today - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]
    with storage._LOCK:
        per = dict(storage.conn().execute("SELECT substr(at, 1, 10), COUNT(*) FROM events WHERE type IN ('user', 'jarvis', 'notify', 'error') AND at >= ? GROUP BY 1", (line[0],)).fetchall())
    for e in _record():
        if e["time"][:10] >= line[0]:
            per[e["time"][:10]] = per.get(e["time"][:10], 0) + 1
    return [{"day": d, "n": per.get(d, 0)} for d in line]


def often(n: int = 8, back: int = 60, today: date | None = None) -> list[dict]:
    """What you ask most (at least twice)."""
    got: dict[str, dict] = {}
    for r in _events("AND type = 'user' AND at >= ?", (((today or date.today()) - timedelta(days=back)).isoformat(),)):
        key = " ".join(re.sub(r"[^\w\s]", " ", r["text"].casefold()).split())
        if key and len(r["text"]) <= 160 and r["how"] != "scheduled":
            g = got.setdefault(key, {"text": r["text"].strip(), "n": 0})
            g["n"] += 1
    return sorted((g for g in got.values() if g["n"] > 1), key=lambda g: -g["n"])[:n]


def remove(ref: Any = None, whole_day: Any = None) -> list[dict]:
    """Take one thing, or a day, out of the conversation. Returns what went ([{type, time, text}])."""
    from . import audit, storage
    if whole_day:
        d = day(whole_day)
        where, args = "at >= ? AND at < ?", (d, _next(d))
    else:
        m = re.fullmatch(r"e(\d{1,15})", str(ref or ""))
        if not m:
            raise ValueError("Only things from the conversation can be taken out one by one. The record of actions is cleared as a whole (Kept here).")
        where, args = "id = ?", (int(m[1]),)
    with storage._LOCK:
        c = storage.conn()
        rows = c.execute(f"SELECT type, data FROM events WHERE {where}", args).fetchall()
        with c:
            c.execute(f"DELETE FROM events WHERE {where}", args)
    gone = []
    for kind, data in rows:
        try:
            ev = json.loads(data)
        except json.JSONDecodeError:
            ev = {}
        gone.append({"type": kind, "time": ev.get("time"), "text": ev.get("text")})
    if gone:
        audit.record("timeline_removed", things=len(gone), **({"day": str(args[0])} if whole_day else {}))
    return gone


def export(rows: list[dict], name: str = "Timeline", folder: Path | None = None) -> Path:
    """As CSV in Documents. Never over an existing file."""
    from .life import _safe_cell
    folder = folder or Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    folder.mkdir(parents=True, exist_ok=True)
    for n in range(1, 100):
        p = folder / f"{name}{f' ({n})' if n > 1 else ''}.csv"
        try:
            with open(p, "x", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["When", "Kind", "Title", "Text"])
                w.writerows([[r["at"], KINDS[r["kind"]], _safe_cell(r["title"]), _safe_cell(r["text"])] for r in rows])
            return p
        except FileExistsError:
            continue
    raise ValueError("There are too many exports with this name in Documents.")


def load(d: dict) -> dict:
    """For the page: one day, or a search."""
    words = " ".join(str(d.get("query") or "").split())[:200]
    when = day(d["day"]) if d.get("day") else date.today().isoformat()
    rows = search(words, d.get("kinds")) if words else of_day(when, d.get("kinds"))
    return {"rows": rows, "day": when, "query": words, "days": days(), "kinds": KINDS, "often": often(), "today": date.today().isoformat(), "most": MAX_FOUND if words else MAX_DAY}


def for_ai(words: str = "", when: str = "", limit: int = 40) -> str:
    """The conversation only (what you said and the answers), for an answer."""
    rows = (search(words, ["you", "answer"]) if words else of_day(when or date.today().isoformat(), ["you", "answer"]))[:limit]
    return "\n".join(f"[{r['at'][:16]}] {'User' if r['kind'] == 'you' else 'Assistant'}: {' '.join(r['text'].split())[:300]}" for r in reversed(rows))

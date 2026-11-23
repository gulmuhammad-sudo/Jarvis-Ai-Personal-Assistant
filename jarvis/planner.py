"""Planner (Phase 7): tasks in projects, a calendar, and one agenda that puts them next to alarms and prayers.

Everything is in the local database (tables tasks, calendar); nothing goes online. Times are the PC's local time, kept as
text: a day "2026-11-24", a moment "2026-11-24T17:30". A repeating event keeps its first start; its later days are worked
out when asked for (a monthly event on the 31st simply skips shorter months).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

MAX_TITLE = 160
MAX_NOTES = 2000
MAX_TASKS = 2000
MAX_EVENTS = 2000
REPEATS = ("none", "daily", "weekly", "monthly", "yearly")
CATCH_UP = timedelta(minutes=10)            # a reminder missed by a little (PC asleep) still comes; later it's dropped
PRIORITY = {1: "normal", 2: "important", 3: "urgent"}


# ---------------- reading dates and times ----------------
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def parse_day(text: Any, today: date | None = None) -> date:
    """2026-11-24, 24/11/2026, 24 nov, today / aaj, tomorrow / kal, or a weekday (the next one; today doesn't count)."""
    today = today or date.today()
    t = " ".join(str(text or "").strip().lower().split())
    if t in ("today", "aaj", "آج"):
        return today
    if t in ("tomorrow", "kal", "کل"):             # in a plan "kal" means tomorrow
        return today + timedelta(days=1)
    if t in ("day after tomorrow", "parson", "پرسوں"):
        return today + timedelta(days=2)
    m = re.fullmatch(r"(?:next |on )?([a-z]{3,9})", t)
    if m:
        hits = [i for i, d in enumerate(_DAYS) if d.startswith(m.group(1))]
        if len(hits) == 1:
            return today + timedelta(days=(hits[0] - today.weekday() - 1) % 7 + 1)
    try:
        return date.fromisoformat(t[:10]) if re.match(r"\d{4}-\d\d-\d\d", t) else _other_day(t, today)
    except ValueError:
        raise ValueError(f"I don't understand the day {str(text)!r}. Use e.g. 2026-11-24, today, tomorrow or friday.") from None


def _other_day(t: str, today: date) -> date:
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", t)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))          # day first
    for fmt in ("%d %b %Y", "%d %B %Y"):
        for s in (t, f"{t} {today.year}"):
            try:
                d = datetime.strptime(s, fmt).date()
                # "5 jan" said in December means the coming January
                return d.replace(year=d.year + 1) if s != t and d < today - timedelta(days=1) else d
            except ValueError:
                pass
    raise ValueError


def parse_clock(text: Any) -> str:
    from .schedule import _parse_time
    return _parse_time(str(text))


def moment(day: Any, clock: Any = "", today: date | None = None) -> str:
    """'2026-11-24' or '2026-11-24T17:30' from a day and an optional time ('' = none)."""
    s = str(day or "").strip()
    m = re.fullmatch(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d)(?::\d\d)?", s)
    if m and not clock:
        return f"{date.fromisoformat(m.group(1))}T{parse_clock(m.group(2))}"
    d = parse_day(s, today)
    return f"{d}T{parse_clock(clock)}" if str(clock or "").strip() else d.isoformat()


def when(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def _text(value: Any, limit: int, what: str, need: bool = False) -> str:
    s = str(value or "").strip()
    s = " ".join(s.split()) if limit <= MAX_TITLE else s
    if need and not s:
        raise ValueError(f"{what} is missing.")
    if len(s) > limit:
        raise ValueError(f"{what} is too long (up to {limit} characters).")
    return s


def _db():
    from . import storage
    return storage.conn(), storage._LOCK


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------- tasks ----------------
_T = "id, title, notes, project, due, priority, done, done_at, created, updated"


def _task(r) -> dict:
    return {"id": r[0], "title": r[1], "notes": r[2], "project": r[3], "due": r[4], "priority": r[5], "done": bool(r[6]), "done_at": r[7],
            "created": r[8], "updated": r[9]}


def get_task(task_id: int) -> dict | None:
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_T} FROM tasks WHERE id = ?", (int(task_id),)).fetchone()
    return _task(r) if r else None


def list_tasks(project: str | None = None, done: bool | None = False, query: str = "", limit: int = 500) -> list[dict]:
    """Open tasks first by due day (none last) and importance; done ones newest first."""
    c, lock = _db()
    with lock:
        rows = [_task(r) for r in c.execute(f"SELECT {_T} FROM tasks").fetchall()]
    words = [w for w in query.lower().split() if w]
    rows = [t for t in rows if (done is None or t["done"] == done) and (project is None or t["project"].lower() == project.lower())
            and all(w in f"{t['title']} {t['notes']} {t['project']}".lower() for w in words)]
    rows.sort(key=lambda t: t["done_at"] or "", reverse=True)
    rows.sort(key=lambda t: (t["done"], "" if t["done"] else (t["due"] or "9999"), 0 if t["done"] else -t["priority"]))
    return rows[:limit]


def projects() -> list[dict]:
    out: dict[str, dict] = {}
    for t in list_tasks(done=None, limit=MAX_TASKS):
        if t["project"]:
            p = out.setdefault(t["project"].lower(), {"name": t["project"], "open": 0, "done": 0})
            p["done" if t["done"] else "open"] += 1
    return sorted(out.values(), key=lambda p: p["name"].lower())


def find_task(ref: Any, done: bool | None = False) -> dict | None:
    """By number, exact title, or the only one whose title contains the words."""
    s = str(ref or "").strip().lstrip("#")
    if s.isdigit():
        return get_task(int(s))
    items = list_tasks(done=done)
    exact = [t for t in items if t["title"].lower() == s.lower()]
    part = [t for t in items if s and all(w in t["title"].lower() for w in s.lower().split())]
    return exact[0] if len(exact) == 1 else part[0] if len(part) == 1 else None


def _priority(v: Any) -> int:
    names = {"normal": 1, "important": 2, "urgent": 3, "low": 1, "high": 3}
    try:
        p = names.get(str(v).lower()) or int(v)
    except (TypeError, ValueError):
        p = 0
    if p not in PRIORITY:
        raise ValueError("Importance is 1 (normal), 2 (important) or 3 (urgent).")
    return p


def save_task(title: Any = None, notes: Any = None, project: Any = None, due: Any = None, priority: Any = None,
              task_id: int | None = None) -> dict:
    """Add a task, or change the given fields of one (None = leave; due '' = no due day)."""
    c, lock = _db()
    old = get_task(task_id) if task_id is not None else None
    if task_id is not None and not old:
        raise ValueError("That task is gone.")
    base = old or {"title": "", "notes": "", "project": "", "due": None, "priority": 1}
    row = {
        "title": _text(title if title is not None else base["title"], MAX_TITLE, "The task", True),
        "notes": _text(notes if notes is not None else base["notes"], MAX_NOTES, "The note"),
        "project": _text(project if project is not None else base["project"], 40, "The project name"),
        "due": base["due"] if due is None else (moment(due) if str(due).strip() else None),
        "priority": base["priority"] if priority in (None, "") else _priority(priority),
    }
    same = next((p["name"] for p in projects() if p["name"].lower() == row["project"].lower()), None)
    row["project"] = same or row["project"]                   # one spelling per project
    with lock, c:
        if old:
            # a new due time may remind again
            c.execute("UPDATE tasks SET title = ?, notes = ?, project = ?, due = ?, priority = ?, updated = ?, "
                      "reminded = CASE WHEN due IS ? THEN reminded ELSE NULL END WHERE id = ?",
                      (*row.values(), _now(), row["due"], task_id))
        else:
            if c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] >= MAX_TASKS:
                raise ValueError("There are too many tasks; delete some old ones first.")
            task_id = c.execute("INSERT INTO tasks(title, notes, project, due, priority, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (*row.values(), _now(), _now())).lastrowid
    return get_task(task_id)


def set_done(task_id: int, done: bool = True) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("UPDATE tasks SET done = ?, done_at = ?, updated = ? WHERE id = ?",
                              (int(bool(done)), _now() if done else None, _now(), int(task_id))).rowcount)


def delete_task(task_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("DELETE FROM tasks WHERE id = ?", (int(task_id),)).rowcount)


def say_when(text: str | None, today: date | None = None) -> str:
    if not text:
        return ""
    today = today or date.today()
    d = when(text)
    n = (d.date() - today).days
    day = {0: "today", 1: "tomorrow", -1: "yesterday"}.get(n) or (f"{d:%A}" if 1 < n < 7 else f"{d:%a %d %b}" + (f" {d.year}" if d.year != today.year else ""))
    return day + (f" at {d:%H:%M}" if "T" in text else "")


def overdue(t: dict, now: datetime | None = None) -> bool:
    if t["done"] or not t["due"]:
        return False
    now = now or datetime.now()
    d = when(t["due"])
    return d < now if "T" in t["due"] else d.date() < now.date()


def describe_task(t: dict) -> str:
    return (f"#{t['id']} {t['title']}" + (f" [{t['project']}]" if t["project"] else "") + (f", due {say_when(t['due'])}" if t["due"] else "")
            + (" (overdue)" if overdue(t) else "") + (f", {PRIORITY[t['priority']]}" if t["priority"] > 1 else "") + (" (done)" if t["done"] else ""))


# ---------------- calendar ----------------
_E = "id, title, place, notes, start, end, all_day, repeat, until, remind, created, updated"


def _event(r) -> dict:
    return {"id": r[0], "title": r[1], "place": r[2], "notes": r[3], "start": r[4], "end": r[5], "all_day": bool(r[6]), "repeat": r[7],
            "until": r[8], "remind": r[9], "created": r[10], "updated": r[11]}


def get_event(event_id: int) -> dict | None:
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_E} FROM calendar WHERE id = ?", (int(event_id),)).fetchone()
    return _event(r) if r else None


def all_events() -> list[dict]:
    c, lock = _db()
    with lock:
        return [_event(r) for r in c.execute(f"SELECT {_E} FROM calendar ORDER BY start").fetchall()]


def _starts(e: dict, first: date, last: date):
    """The days from first to last on which the event starts."""
    s = when(e["start"]).date()
    end = min(last, date.fromisoformat(e["until"])) if e["until"] else last
    if e["repeat"] == "none":
        if first <= s <= last:
            yield s
        return
    if e["repeat"] in ("daily", "weekly"):
        step = 1 if e["repeat"] == "daily" else 7
        d = s if s >= first else s + timedelta(days=-(-(first - s).days // step) * step)
        while d <= end:
            yield d
            d += timedelta(days=step)
        return
    y, m = (s.year, s.month) if s >= first else (first.year, s.month if e["repeat"] == "yearly" else first.month)
    while date(y, m, 1) <= end:
        try:
            d = date(y, m, s.day)
            if max(first, s) <= d <= end:
                yield d
        except ValueError:                       # 31 June, 29 February
            pass
        if e["repeat"] == "yearly":
            y += 1
        else:
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def occurrences(first: date, last: date, events: list[dict] | None = None) -> list[dict]:
    """Every event day that touches first..last, in order (an event over midnight or several days counts on each)."""
    out = []
    for e in all_events() if events is None else events:
        s, f = when(e["start"]), when(e["end"])
        length = f - s
        for d in _starts(e, first - timedelta(days=max(0, length.days + 1)), last):
            a = datetime.combine(d, s.time())
            b = a + length
            touches = b.date() if b.time() != datetime.min.time() or b == a else (b - timedelta(seconds=1)).date()
            if touches >= first and a.date() <= last:
                out.append({**e, "start": a.isoformat(timespec="minutes"), "end": b.isoformat(timespec="minutes"), "first_start": e["start"]})
    return sorted(out, key=lambda o: (o["start"][:10], not o["all_day"], o["start"]))


def conflicts(e: dict, days: int = 30) -> list[dict]:
    """Timed events at the same time as e, on its first day and (if it repeats) the next 30 days."""
    if e["all_day"]:
        return []
    s = when(e["start"])
    first, last = s.date(), (s + timedelta(days=days if e["repeat"] != "none" else 1)).date()
    mine = [(o["start"], o["end"]) for o in occurrences(first, last, [e])]
    found: dict[int, dict] = {}
    for o in occurrences(first, last):
        if o["id"] != e["id"] and not o["all_day"] and o["id"] not in found and any(o["start"] < b and a < o["end"] for a, b in mine):
            found[o["id"]] = o
    return list(found.values())


def save_event(title: Any = None, day: Any = None, time: Any = None, end_time: Any = None, minutes: Any = None, place: Any = None,
               notes: Any = None, repeat: Any = None, until: Any = None, remind: Any = None, event_id: int | None = None) -> dict:
    """Add an event, or change the given fields of one (None = leave). time '' = all day."""
    old = get_event(event_id) if event_id is not None else None
    if event_id is not None and not old:
        raise ValueError("That event is gone.")
    if not old and day in (None, ""):
        raise ValueError("Which day?")
    if old:
        s, f = when(old["start"]), when(old["end"])
        day = s.date().isoformat() if day in (None, "") else day
        if time is None:
            time = "" if old["all_day"] else f"{s:%H:%M}"
        if minutes in (None, "") and end_time in (None, "") and time and not old["all_day"]:
            minutes = int((f - s).total_seconds() // 60)
    start = moment(day, time or "")
    all_day = "T" not in start
    a = datetime.fromisoformat(start)
    if all_day:
        b = a + timedelta(days=1)
    elif end_time not in (None, ""):
        b = datetime.combine(a.date(), datetime.strptime(parse_clock(end_time), "%H:%M").time())
        if b <= a:
            b += timedelta(days=1)                # over midnight
    else:
        try:
            n = int(minutes) if minutes not in (None, "") else 60
        except (TypeError, ValueError):
            n = 0
        if not 1 <= n <= 7 * 24 * 60:
            raise ValueError("The length must be between 1 minute and a week.")
        b = a + timedelta(minutes=n)
    rep = str(repeat if repeat not in (None, "") else (old["repeat"] if old else "none")).lower()
    if rep not in REPEATS:
        raise ValueError(f"Repeat is one of: {', '.join(REPEATS)}.")
    end_rep = old["until"] if old and until is None else (parse_day(until).isoformat() if until not in (None, "") else None)
    if rep == "none":
        end_rep = None
    if end_rep and end_rep < a.date().isoformat():
        raise ValueError("It can't stop repeating before it starts.")
    if remind is None:
        rem = old["remind"] if old else (None if all_day else 15)
    elif str(remind).strip() in ("", "-1", "none", "off"):
        rem = None
    else:
        try:
            rem = int(remind)
        except (TypeError, ValueError):
            rem = -1
        if not 0 <= rem <= 7 * 24 * 60:
            raise ValueError("Remind between 0 minutes and a week before.")
    row = (_text(title if title is not None else (old or {}).get("title"), MAX_TITLE, "The title", True),
           _text(place if place is not None else (old or {}).get("place"), MAX_TITLE, "The place"),
           _text(notes if notes is not None else (old or {}).get("notes"), MAX_NOTES, "The note"),
           a.isoformat(timespec="minutes"), b.isoformat(timespec="minutes"), int(all_day), rep, end_rep, rem)
    c, lock = _db()
    with lock, c:
        if old:
            c.execute("UPDATE calendar SET title = ?, place = ?, notes = ?, start = ?, end = ?, all_day = ?, repeat = ?, until = ?, remind = ?, "
                      "updated = ?, reminded = NULL WHERE id = ?", (*row, _now(), event_id))
        else:
            if c.execute("SELECT COUNT(*) FROM calendar").fetchone()[0] >= MAX_EVENTS:
                raise ValueError("There are too many events; delete some old ones first.")
            event_id = c.execute("INSERT INTO calendar(title, place, notes, start, end, all_day, repeat, until, remind, created, updated) "
                                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (*row, _now(), _now())).lastrowid
    return get_event(event_id)


def delete_event(event_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("DELETE FROM calendar WHERE id = ?", (int(event_id),)).rowcount)


def find_event(ref: Any) -> dict | None:
    s = str(ref or "").strip().lstrip("#")
    if s.isdigit():
        return get_event(int(s))
    items = all_events()
    exact = [e for e in items if e["title"].lower() == s.lower()]
    part = [e for e in items if s and all(w in e["title"].lower() for w in s.lower().split())]
    return exact[0] if len(exact) == 1 else part[0] if len(part) == 1 else None


def describe_event(e: dict, with_day: bool = True) -> str:
    a, b = when(e["start"]), when(e["end"])
    t = "all day" if e["all_day"] else f"{a:%H:%M}-{b:%H:%M}"
    return (f"#{e['id']} " + (f"{say_when(e['start'][:10])} " if with_day else "") + f"{t} {e['title']}" + (f" at {e['place']}" if e["place"] else "")
            + (f" (repeats {e['repeat']}" + (f" until {e['until']}" if e["until"] else "") + ")" if e["repeat"] != "none" else ""))


# ---------------- the agenda ----------------
def agenda(day: date | None = None, days: int = 1, extra: bool = True) -> list[dict]:
    """Each day: its events, its tasks, and (extra) its alarms and prayers. Overdue tasks come with today."""
    from . import schedule
    first = day or date.today()
    days = max(1, min(int(days), 42))
    last = first + timedelta(days=days - 1)
    occ, open_tasks, today = occurrences(first, last), list_tasks(), date.today()
    out = []
    for n in range(days):
        d = first + timedelta(days=n)
        iso = d.isoformat()
        evs = [o for o in occ if o["start"][:10] <= iso and (o["end"] > f"{iso}T00:00" or o["start"][:10] == iso)]
        tasks = [t for t in open_tasks if t["due"] and (t["due"][:10] == iso or (d == today and t["due"][:10] < iso))]
        row = {"day": iso, "events": evs, "tasks": tasks, "alarms": [], "prayers": []}
        if extra:
            for a in schedule.list_alarms():
                on = a.get("enabled", True) and (a.get("date") == iso if a["repeat"] == "once" else d.weekday() in a["days"])
                if on:
                    row["alarms"].append({"time": a["time"], "label": a["label"]})
            if d == today and schedule.Scheduler.prayers_on():
                try:
                    row["prayers"] = [{"time": t, "label": p} for p, t in schedule.prayer_times(d).items() if p in schedule.PRAYERS]
                except Exception:                 # offline: the agenda still shows
                    pass
        out.append(row)
    return out


def describe_agenda(rows: list[dict], prayers: bool = False) -> str:
    out = []
    for r in rows:
        items = [describe_event(e, False) for e in r["events"]] + [f"task {describe_task(t)}" for t in r["tasks"]] + \
                [f"{a['time']} alarm: {a['label']}" for a in r["alarms"]] + ([f"{p['time']} {p['label']}" for p in r["prayers"]] if prayers else [])
        if items or len(rows) == 1:
            out.append(f"{say_when(r['day']).capitalize()} ({r['day']}): " + ("; ".join(items) if items else "nothing planned"))
    return "\n".join(out) or "Nothing planned in those days."


def upcoming(now: datetime | None = None, hours: int = 24) -> list[dict]:
    """The next events and timed tasks, for the Timeline on the Command Center."""
    now = now or datetime.now()
    end = now + timedelta(hours=hours)
    items = [(when(o["start"]), o["title"], "event") for o in occurrences(now.date(), end.date()) if not o["all_day"]]
    items += [(when(t["due"]), t["title"], "task") for t in list_tasks() if t["due"] and "T" in t["due"]]
    return [{"due": a.strftime("%H:%M"), "message": title, "kind": kind, "repeat": "", "left": int((a - now).total_seconds())}
            for a, title, kind in sorted(items) if now <= a <= end][:6]


# ---------------- reminders ----------------
def tick(now: datetime, notify: Callable[[str, str], None]) -> int:
    """Called every few seconds: remind of events (their minutes before) and of tasks with a time. Each once."""
    sent = 0
    c, lock = _db()
    with lock:
        events = [(_event(r[:-1]), r[-1]) for r in c.execute(f"SELECT {_E}, reminded FROM calendar WHERE remind IS NOT NULL").fetchall()]
        tasks = [(_task(r[:-1]), r[-1]) for r in c.execute(f"SELECT {_T}, reminded FROM tasks WHERE done = 0 AND due LIKE '%T%'").fetchall()]
    for e, last in events:
        ahead = timedelta(minutes=e["remind"])
        for o in occurrences(now.date(), (now + ahead).date() + timedelta(days=1), [e]):
            a = when(o["start"])
            if timedelta(0) <= now - (a - ahead) <= CATCH_UP and now < a + timedelta(minutes=1) and (last or "") < o["start"]:
                with lock, c:
                    c.execute("UPDATE calendar SET reminded = ? WHERE id = ?", (o["start"], e["id"]))
                mins = int((a - now).total_seconds() + 59) // 60
                at = f"{a:%H:%M}" if a.date() == now.date() else say_when(o["start"], now.date())
                notify(f"Reminder: {e['title']}" + (f" in {mins} minutes" if 0 < mins <= 120 else "" if mins > 0 else " now") + f" ({at})"
                       + (f", {e['place']}" if e["place"] else "") + ".", "reminder")
                sent += 1
                break
    for t, last in tasks:
        if timedelta(0) <= now - when(t["due"]) <= CATCH_UP and last != t["due"]:
            with lock, c:
                c.execute("UPDATE tasks SET reminded = ? WHERE id = ?", (t["due"], t["id"]))
            notify(f"Reminder: task due now: {t['title']}.", "reminder")
            sent += 1
    return sent

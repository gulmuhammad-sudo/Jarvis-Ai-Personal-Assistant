"""People and companion (Phase 8): who matters to you, their days, a daily check-in, and how the assistant talks with you.

Local database (people); nothing goes online by itself. People are private: no agent or automation has them.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .planner import CATCH_UP, _db, _now, _text, parse_clock

MAX_PEOPLE = 1000
REMIND_DAYS = (0, 1, 3, 7)
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")

# how it talks with you: added to the assistant's instructions
TONES = {
    "butler": ("Butler", "calm, courteous and a little dryly witty, like a loyal British butler"),
    "warm": ("Warm friend", "warm, caring and personal, like a good friend; ask how things went when it fits"),
    "cheerful": ("Cheerful", "cheerful, upbeat and encouraging, with a light touch"),
    "calm": ("Calm", "calm, gentle and unhurried, with plain words"),
    "professional": ("Professional", "professional, neutral and to the point, without small talk"),
}
HUMOUR = {"none": "No jokes.", "some": "A little humour now and then is welcome.", "lots": "Be playful and joke often, but never about what hurts."}
LENGTH = {"short": "Keep answers as short as possible.", "normal": "", "long": "Explain a little more than you need to; they like detail."}
CARE = ("If the user seems very low, frightened or in danger, be kind and take it seriously: listen first, don't lecture, don't play doctor, and encourage them to "
        "reach someone they trust or the local emergency number right now. You are an AI companion, not a replacement for people; say so if they ask.")


# ---------------- settings ----------------
def settings() -> dict:
    from . import schedule
    pick = lambda key, options, usual: v if (v := schedule.get_setting(key)) in options else usual          # noqa: E731
    return {"tone": pick("companion_tone", TONES, "butler"), "humour": pick("companion_humour", HUMOUR, "some"), "length": pick("companion_length", LENGTH, "normal"),
            "checkin": schedule.get_setting("companion_checkin") or "", "use_names": schedule.get_setting("companion_people") is True,
            "birthday_at": schedule.get_setting("birthday_at") or "09:00"}


def save_settings(d: dict) -> bool:
    """True if the assistant's instructions change with it."""
    from . import schedule
    before = prompt()
    for k, options in (("tone", TONES), ("humour", HUMOUR), ("length", LENGTH)):
        if k in d:
            if d[k] not in options:
                raise ValueError(f"Choose one of: {', '.join(options)}.")
            schedule.set_setting("companion_" + k, d[k])
    if "checkin" in d:
        t = str(d["checkin"] or "").strip()
        schedule.set_setting("companion_checkin", parse_clock(t) if t else None)
    if "birthday_at" in d:
        schedule.set_setting("birthday_at", parse_clock(str(d["birthday_at"])))
    if "use_names" in d:
        schedule.set_setting("companion_people", d["use_names"] is True)
    return prompt() != before


def prompt() -> str:
    """For the assistant's instructions. The usual settings add only the last line."""
    s = settings()
    out = []
    if s["tone"] != "butler":
        out.append(f"Your manner with the user: {TONES[s['tone']][1]}. (This goes before the manner described above.)")
    if s["humour"] != "some":
        out.append(HUMOUR[s["humour"]])
    if LENGTH[s["length"]]:
        out.append(LENGTH[s["length"]])
    if s["use_names"] and (rows := people()[:40]):
        out.append("People who matter to the user: " + "; ".join(p["name"] + (f" ({p['relation']})" if p["relation"] else "") for p in rows) + ".")
    return "\n" + "\n".join([*out, CARE]) + "\n"


# ---------------- birthdays ----------------
def parse_birthday(text: Any) -> str:
    """'' / 2001-05-14 / 14 May / 14 May 2001 / 14-05-2001 -> 'YYYY-MM-DD', or '--MM-DD' without a year."""
    t = " ".join(str(text or "").strip().lower().replace(",", " ").split())
    if not t:
        return ""
    y = m = d = None
    if g := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t):
        y, m, d = map(int, g.groups())
    elif g := re.fullmatch(r"--(\d\d)-(\d\d)", t):
        m, d = map(int, g.groups())
    elif g := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{4}))?", t):
        d, m, y = int(g.group(1)), int(g.group(2)), int(g.group(3)) if g.group(3) else None            # day first
    elif g := re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]{3,9})(?: (\d{4}))?", t):
        hits = [i + 1 for i, x in enumerate(MONTHS) if x.startswith(g.group(2))]
        d, m, y = int(g.group(1)), hits[0] if len(hits) == 1 else None, int(g.group(3)) if g.group(3) else None
    elif g := re.fullmatch(r"([a-z]{3,9}) (\d{1,2})(?:st|nd|rd|th)?(?: (\d{4}))?", t):
        hits = [i + 1 for i, x in enumerate(MONTHS) if x.startswith(g.group(1))]
        m, d, y = hits[0] if len(hits) == 1 else None, int(g.group(2)), int(g.group(3)) if g.group(3) else None
    try:
        real = date(y or 2000, m, d)                       # 2000: a leap year, so 29 February is a birthday too
        if y is not None and not date(1900, 1, 1) <= real <= date.today():
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(f"I don't understand the birthday {str(text)[:30]!r}. Use e.g. 14 May, or 14 May 2001.") from None
    return real.isoformat() if y else f"--{m:02d}-{d:02d}"


def next_birthday(b: str, today: date | None = None) -> tuple[date, int | None] | None:
    """(the next one, the age then if the year is known). 29 February is kept on 28 February in other years."""
    if not b:
        return None
    today = today or date.today()
    y, m, d = (None, int(b[2:4]), int(b[5:7])) if b.startswith("--") else (int(b[:4]), int(b[5:7]), int(b[8:10]))
    for year in (today.year, today.year + 1):
        try:
            when = date(year, m, d)
        except ValueError:
            when = date(year, 2, 28)
        if when >= today:
            return when, (year - y if y else None)
    return None


# ---------------- people ----------------
_P = "id, name, relation, birthday, phone, notes, remind, created"


def _row(r, today: date | None = None) -> dict:
    p = dict(zip(("id", "name", "relation", "birthday", "phone", "notes", "remind", "created"), r))
    nxt = next_birthday(p["birthday"], today)
    p["next"], p["age"] = (nxt[0].isoformat(), nxt[1]) if nxt else ("", None)
    p["in_days"] = (nxt[0] - (today or date.today())).days if nxt else None
    return p


def people(query: str = "", today: date | None = None) -> list[dict]:
    c, lock = _db()
    with lock:
        rows = [_row(r, today) for r in c.execute(f"SELECT {_P} FROM people ORDER BY name COLLATE NOCASE").fetchall()]
    words = str(query or "").casefold().split()
    return [p for p in rows if all(w in f"{p['name']} {p['relation']} {p['notes']}".casefold() for w in words)]


def get(person_id: Any) -> dict | None:
    return next((p for p in people() if p["id"] == int(person_id)), None)


def find(ref: Any) -> dict | None:
    rows, s = people(), str(ref if ref is not None else "").strip()
    if s.lstrip("#").isdigit():
        return next((p for p in rows if p["id"] == int(s.lstrip("#"))), None)
    low = s.casefold()
    for hits in ([p for p in rows if p["name"].casefold() == low], [p for p in rows if low and low in p["relation"].casefold().split()], [p for p in rows if low and all(w in p["name"].casefold() for w in low.split())]):
        if len(hits) == 1:
            return hits[0]
    return None


def save(name: Any = None, relation: Any = None, birthday: Any = None, phone: Any = None, notes: Any = None, remind: Any = None, person_id: int | None = None) -> dict:
    old = get(person_id) if person_id is not None else None
    if person_id is not None and not old:
        raise ValueError("That person is gone.")
    o = old or {"name": "", "relation": "", "birthday": "", "phone": "", "notes": "", "remind": 1}
    n = _text(o["name"] if name is None else name, 80, "The name", True)
    ph = _text(o["phone"] if phone is None else phone, 40, "The phone number")
    if ph and not re.fullmatch(r"[+\d][\d\s()/-]{3,38}", ph):
        raise ValueError("That doesn't look like a phone number.")
    r = o["remind"] if remind in (None, "") else int(remind) if str(remind).strip().lstrip("-").isdigit() else 99
    if r not in (*REMIND_DAYS, -1):
        raise ValueError("The reminder: on the day, or 1, 3 or 7 days before (or never).")
    if any(p["name"].casefold() == n.casefold() and p["id"] != person_id for p in people()):
        raise ValueError(f"{n} is already there.")
    row = (n, _text(o["relation"] if relation is None else relation, 60, "The relation"), o["birthday"] if birthday is None else parse_birthday(birthday), ph,
           _text(o["notes"] if notes is None else notes, 2000, "The notes"), r)
    c, lock = _db()
    with lock, c:
        if person_id is None:
            if c.execute("SELECT count(*) FROM people").fetchone()[0] >= MAX_PEOPLE:
                raise ValueError(f"That's {MAX_PEOPLE} people.")
            person_id = c.execute("INSERT INTO people (name, relation, birthday, phone, notes, remind, created) VALUES (?, ?, ?, ?, ?, ?, ?)", (*row, _now())).lastrowid
        else:
            c.execute("UPDATE people SET name = ?, relation = ?, birthday = ?, phone = ?, notes = ?, remind = ? WHERE id = ?", (*row, person_id))
    return get(person_id)


def delete(person_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM people WHERE id = ?", (int(person_id),)).rowcount > 0


def _when(n: int) -> str:
    return "today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days"


def describe(p: dict) -> str:
    b = ""
    if p["next"]:
        b = f", birthday {date.fromisoformat(p['next']):%d %B} ({_when(p['in_days'])}" + (f", turns {p['age']}" if p["age"] else "") + ")"
    return f"{p['name']}" + (f" ({p['relation']})" if p["relation"] else "") + b + (f". {p['notes']}" if p["notes"] else "")


def coming(days: int = 60, today: date | None = None) -> list[dict]:
    return sorted((p for p in people(today=today) if p["in_days"] is not None and p["in_days"] <= days), key=lambda p: p["in_days"])


# ---------------- reminders, check-in ----------------
CHECKINS = ("How are you today?", "How is your day going?", "Just checking in: how are you feeling?", "A quick hello: how are things?", "How was your day so far?", "I hope the day is treating you well. How are you?",
            "Anything on your mind today?")


def tick(now: datetime, notify: Callable[[str, str], None]) -> int:
    from . import schedule
    s, sent, today = settings(), 0, now.date()
    at = lambda hhmm: datetime.combine(today, datetime.strptime(hhmm, "%H:%M").time())                  # noqa: E731
    if now >= at(s["birthday_at"]):
        said = schedule.get_setting("birthdays_said")
        said = said if isinstance(said, dict) else {}
        new = {}
        for p in coming(7, today):
            key = f"{p['next']}:{'day' if p['in_days'] == 0 else 'before'}"
            due = p["remind"] >= 0 and (p["in_days"] == 0 or p["in_days"] <= p["remind"])
            if due and said.get(str(p["id"])) not in (key, f"{p['next']}:day"):
                new[str(p["id"])] = key
                turns = f" ({p['age']})" if p["age"] else ""
                notify(f"Today is {p['name']}'s birthday{turns}." if p["in_days"] == 0 else f"Reminder: {p['name']}'s birthday{turns} is {_when(p['in_days'])}.", "reminder")
                sent += 1
        if new:
            schedule.set_setting("birthdays_said", {**dict(list(said.items())[-300:]), **new})
    if s["checkin"] and timedelta(0) <= now - at(s["checkin"]) <= CATCH_UP and schedule.get_setting("checkin_said") != today.isoformat():
        schedule.set_setting("checkin_said", today.isoformat())
        notify(CHECKINS[today.toordinal() % len(CHECKINS)], "info")
        sent += 1
    return sent


def load(query: str = "") -> dict:
    return {"people": people(query), "coming": coming(), "settings": settings(), "tones": {k: v[0] for k, v in TONES.items()}, "humour": list(HUMOUR), "length": list(LENGTH)}


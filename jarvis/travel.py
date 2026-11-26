"""Travel (Phase 8): trips with a day-by-day plan, a packing list, a papers checklist and a budget.

Everything is in the local database (trips, trip_items); nothing is booked, bought or paid. Only the Weather button (and the
assistant, when asked) sends the destination's name to the weather service. Passport numbers and the like have no place here.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Callable

from . import planner
from .planner import _db, _now, _text, parse_clock, parse_day

MAX_TRIPS, MAX_ITEMS = 300, 400
KINDS = ("plan", "pack", "papers")
# packing lists to start from (what is already there is never added twice)
BASE = ["phone and charger", "power bank", "toothbrush and toothpaste", "medicines", "glasses / lenses", "underwear and socks", "night clothes", "shoes", "cash and cards"]
LISTS: dict[str, list[str]] = {
    "basic": BASE,
    "summer": [*BASE, "light clothes", "sunglasses", "sunscreen", "cap", "water bottle"],
    "winter": [*BASE, "jacket", "sweaters", "gloves", "warm hat", "thick socks", "lip balm"],
    "business": [*BASE, "laptop and charger", "formal clothes", "formal shoes", "visiting cards", "notebook and pen"],
    "umrah": [*BASE, "ihram (two sets)", "ihram belt", "comfortable sandals", "unscented soap and shampoo", "small prayer mat", "dua book", "bag for shoes", "nail clipper and scissors"],
    "family": [*BASE, "children's clothes", "snacks", "toys and games", "wet wipes", "first-aid kit"],
}
PAPERS = ["ID card", "tickets", "hotel booking"]
PAPERS_ABROAD = ["passport (valid 6 months more)", "visa", "tickets", "hotel booking", "travel insurance", "copies of papers (kept apart)"]


# ---------------- trips ----------------
_T = "id, title, place, abroad, start, end, notes, budget, created"


def _trip(r) -> dict:
    t = dict(zip(("id", "title", "place", "abroad", "start", "end", "notes", "budget", "created"), r))
    t["abroad"] = bool(t["abroad"])
    t["days"] = (date.fromisoformat(t["end"]) - date.fromisoformat(t["start"])).days + 1
    return t


def trips(today: date | None = None) -> list[dict]:
    """Coming and running ones first (the nearest first), then the past (the newest first)."""
    today = today or date.today()
    c, lock = _db()
    with lock:
        rows = [_trip(r) for r in c.execute(f"SELECT {_T} FROM trips").fetchall()]
        counts = {(a, k): (n, d or 0) for a, k, n, d in c.execute("SELECT trip, kind, count(*), sum(done) FROM trip_items GROUP BY trip, kind").fetchall()}
    for t in rows:
        left = (date.fromisoformat(t["start"]) - today).days
        t["state"] = "past" if t["end"] < today.isoformat() else "now" if left <= 0 else "coming"
        t["in_days"] = left
        for k in KINDS:
            t[k] = {"n": counts.get((t["id"], k), (0, 0))[0], "done": counts.get((t["id"], k), (0, 0))[1]}
    return sorted((t for t in rows if t["state"] != "past"), key=lambda t: t["start"]) + sorted((t for t in rows if t["state"] == "past"), key=lambda t: t["start"], reverse=True)


def get(trip_id: Any) -> dict | None:
    return next((t for t in trips() if t["id"] == int(trip_id)), None)


def find(ref: Any) -> dict | None:
    """By number, whole name, or words that fit only one (a coming one before a past one). Nothing said: the next one."""
    rows, s = trips(), str(ref if ref is not None else "").strip()
    if not s:
        return next((t for t in rows if t["state"] != "past"), None)
    if s.lstrip("#").isdigit():
        return next((t for t in rows if t["id"] == int(s.lstrip("#"))), None)
    low = s.casefold()
    hits = [t for t in rows if t["title"].casefold() == low] or [t for t in rows if all(w in f"{t['title']} {t['place']}".casefold() for w in low.split())]
    ahead = [t for t in hits if t["state"] != "past"]
    return hits[0] if len(hits) == 1 else ahead[0] if len(ahead) == 1 else None


def save(title: Any = None, place: Any = None, start: Any = None, end: Any = None, notes: Any = None, budget: Any = None, abroad: Any = None, trip_id: int | None = None) -> dict:
    old = get(trip_id) if trip_id is not None else None
    if trip_id is not None and not old:
        raise ValueError("That trip is gone.")
    o = old or {"title": "", "place": "", "start": "", "end": "", "notes": "", "budget": None, "abroad": False}
    pl = _text(o["place"] if place is None else place, 100, "The place")
    ti = _text(o["title"] if title is None else title, 100, "The trip's name") or (f"Trip to {pl}" if pl else "")
    if not ti:
        raise ValueError("Where is the trip to?")
    s = parse_day(start) if start else (date.fromisoformat(o["start"]) if o["start"] else None)
    if not s:
        raise ValueError("When does the trip start?")
    e = parse_day(end) if end else date.fromisoformat(o["end"]) if o["end"] and not start else s + timedelta(days=(old["days"] - 1) if old else 0)
    if not s <= e <= s + timedelta(days=365):
        raise ValueError("The trip must end after it starts (and within a year).")
    b = o["budget"]
    if budget is not None:
        from .life import amount
        b = amount(budget) if str(budget).strip() else None
    row = (ti, pl, int(bool(o["abroad"] if abroad is None else abroad)), s.isoformat(), e.isoformat(), _text(o["notes"] if notes is None else notes, 4000, "The notes"), b)
    c, lock = _db()
    with lock, c:
        if trip_id is None:
            if c.execute("SELECT count(*) FROM trips").fetchone()[0] >= MAX_TRIPS:
                raise ValueError(f"That's {MAX_TRIPS} trips. Remove some first.")
            trip_id = c.execute("INSERT INTO trips (title, place, abroad, start, end, notes, budget, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*row, _now())).lastrowid
        else:
            c.execute("UPDATE trips SET title = ?, place = ?, abroad = ?, start = ?, end = ?, notes = ?, budget = ? WHERE id = ?", (*row, trip_id))
    return get(trip_id)


def delete(trip_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        c.execute("DELETE FROM trip_items WHERE trip = ?", (int(trip_id),))
        return c.execute("DELETE FROM trips WHERE id = ?", (int(trip_id),)).rowcount > 0


# ---------------- plan, packing, papers ----------------
def items(trip_id: Any, kind: str = "") -> list[dict]:
    c, lock = _db()
    with lock:
        rows = c.execute("SELECT id, kind, day, at, text, place, done FROM trip_items WHERE trip = ?" + (" AND kind = ?" if kind else ""),
                         (int(trip_id), kind) if kind else (int(trip_id),)).fetchall()
    out = [dict(zip(("id", "kind", "day", "at", "text", "place", "done"), r)) | {"done": bool(r[6])} for r in rows]
    return sorted(out, key=lambda x: (x["kind"], x["day"] or "", x["at"] or "", x["id"]))


def _in_trip(t: dict, day: Any) -> str:
    """A day of the trip: a date, or its number (1 = the first)."""
    s = str(day if day is not None else "").strip().lower()
    m = re.fullmatch(r"(?:day\s*)?(\d{1,3})", s)
    d = date.fromisoformat(t["start"]) + timedelta(days=int(m.group(1)) - 1) if m else parse_day(s) if s else date.fromisoformat(t["start"])
    if not t["start"] <= d.isoformat() <= t["end"]:
        raise ValueError(f"That day isn't in the trip ({t['start']} to {t['end']}).")
    return d.isoformat()


def add_item(trip_id: Any, kind: str, text: Any, day: Any = "", at: Any = "", place: Any = "") -> dict | None:
    """None: it is already on the list."""
    t = get(trip_id)
    if not t:
        raise ValueError("That trip is gone.")
    if kind not in KINDS:
        raise ValueError("plan, pack or papers.")
    tx = _text(text, 160, "What", True)
    d = _in_trip(t, day) if kind == "plan" else None
    hour = parse_clock(str(at)) if kind == "plan" and str(at or "").strip() else None
    pl = _text(place, 120, "The place") if kind == "plan" else ""
    rows = items(t["id"])
    if len(rows) >= MAX_ITEMS:
        raise ValueError(f"That's {MAX_ITEMS} things in one trip.")
    if any(x["kind"] == kind and x["text"].casefold() == tx.casefold() and x["day"] == d and x["at"] == hour for x in rows):
        return None
    c, lock = _db()
    with lock, c:
        i = c.execute("INSERT INTO trip_items (trip, kind, day, at, text, place, done) VALUES (?, ?, ?, ?, ?, ?, 0)", (t["id"], kind, d, hour, tx, pl)).lastrowid
    return next(x for x in items(t["id"]) if x["id"] == i)


def tick_item(item_id: Any, on: bool = True) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("UPDATE trip_items SET done = ? WHERE id = ?", (int(bool(on)), int(item_id))).rowcount > 0


def delete_item(item_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM trip_items WHERE id = ?", (int(item_id),)).rowcount > 0


def find_item(trip_id: Any, text: Any, kind: str = "") -> dict | None:
    rows, low = items(trip_id, kind), str(text or "").strip().casefold()
    hits = [x for x in rows if x["text"].casefold() == low] or [x for x in rows if low and all(w in x["text"].casefold() for w in low.split())]
    return hits[0] if len(hits) == 1 else None


def add_list(trip_id: Any, name: str) -> int:
    t = get(trip_id)
    if not t:
        raise ValueError("That trip is gone.")
    if name == "papers":
        things, kind = (PAPERS_ABROAD if t["abroad"] else PAPERS), "papers"
    elif name in LISTS:
        things, kind = LISTS[name], "pack"
    else:
        raise ValueError(f"Lists: {', '.join(LISTS)} or papers.")
    return sum(1 for x in things if add_item(t["id"], kind, x))


# ---------------- money, weather, time, calendar ----------------
def spent(trip: dict) -> int:
    """What Planner › Money has under the trip's name as category (hundredths)."""
    c, lock = _db()
    with lock:
        return c.execute("SELECT coalesce(sum(amount), 0) FROM money WHERE kind = 'out' AND category = ? COLLATE NOCASE", (trip["title"][:40],)).fetchone()[0]


_weather: dict[str, tuple[float, list[dict]]] = {}


def weather(place: str) -> list[dict]:
    """Today and the next two days at the destination (wttr.in; the only thing here that goes online)."""
    import time
    import urllib.parse
    from . import schedule
    key = place.strip().casefold()
    if not key:
        raise ValueError("Where to? Write the place first.")
    hit = _weather.get(key)
    if hit and time.time() - hit[0] < 1800:
        return hit[1]
    try:
        d = schedule._get_json(f"https://wttr.in/{urllib.parse.quote(place.strip())}?format=j1", ua={"User-Agent": "curl/8"})
        out = [{"day": x["date"], "min": int(x["mintempC"]), "max": int(x["maxtempC"]), "rain": max(int(h.get("chanceofrain", 0)) for h in x["hourly"]),
                "text": x["hourly"][min(4, len(x["hourly"]) - 1)]["weatherDesc"][0]["value"].strip()[:60]} for x in d["weather"][:3]]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        raise ValueError("The weather there can't be found right now.") from None
    _weather[key] = (time.time(), out)
    return out


def time_there(place: str) -> dict | None:
    from . import clock
    for part in (place, *re.split(r"[,/]", place)):
        try:
            return clock.place_time(clock.find_place(part))
        except Exception:
            continue
    return None


def to_calendar(trip_id: Any) -> dict:
    """The trip as an event on each of its days; once."""
    t = get(trip_id)
    if not t:
        raise ValueError("That trip is gone.")
    have = {o["start"][:10] for o in planner.occurrences(date.fromisoformat(t["start"]), date.fromisoformat(t["end"])) if o["title"] == t["title"]}
    n = 0
    for i in range(min(t["days"], 60)):
        d = (date.fromisoformat(t["start"]) + timedelta(days=i)).isoformat()
        if d not in have:
            planner.save_event(title=t["title"], day=d, place=t["place"], remind=-1)
            n += 1
    return {"added": n, "there": len(have)}


# ---------------- telling ----------------
def describe(t: dict) -> str:
    when = "now" if t["state"] == "now" else f"in {t['in_days']} day{'' if t['in_days'] == 1 else 's'}" if t["state"] == "coming" else "past"
    return (f"#{t['id']} {t['title']}" + (f" ({t['place']})" if t["place"] and t["place"].casefold() not in t["title"].casefold() else "") +
            f": {t['start']} to {t['end']}, {t['days']} day{'' if t['days'] == 1 else 's'}, {when}. Packed {t['pack']['done']} of {t['pack']['n']}, papers {t['papers']['done']} of {t['papers']['n']}.")


def describe_full(t: dict) -> str:
    out = [describe(t)]
    if t["budget"]:
        from .life import show
        out.append(f"Budget {show(t['budget'])}, spent {show(spent(t))} (Money, category {t['title'][:40]}).")
    if t["notes"]:
        out.append("Notes: " + t["notes"])
    rows = items(t["id"])
    for k, name in (("plan", "Plan"), ("pack", "To pack"), ("papers", "Papers")):
        got = [x for x in rows if x["kind"] == k]
        if got:
            out.append(f"{name}: " + "; ".join((f"{x['day']} " + (f"{x['at']} " if x["at"] else "") if k == "plan" else "") + x["text"] + (f" at {x['place']}" if x["place"] else "") + (" (done)" if x["done"] else "") for x in got))
    return "\n".join(out)


def load(trip_id: Any = None) -> dict:
    from .life import settings, show
    rows = trips()
    t = next((x for x in rows if trip_id not in (None, "") and x["id"] == int(trip_id)), None)
    if t:
        t = {**t, "items": items(t["id"]), "spent": spent(t), "spent_text": show(spent(t)), "budget_text": show(t["budget"]) if t["budget"] else "",
             "budget_raw": f"{t['budget'] / 100:g}" if t["budget"] else "", "there": time_there(t["place"])}
    return {"trips": rows, "trip": t, "lists": list(LISTS), "currency": settings()["currency"]}


def tick(now: datetime, notify: Callable[[str, str], None]) -> int:
    """The day before a trip, from ten in the morning: once."""
    if now.hour < 10:
        return 0
    from . import schedule
    said = schedule.get_setting("trips_said")
    said = said if isinstance(said, dict) else {}
    sent, tomorrow = 0, (now.date() + timedelta(days=1)).isoformat()
    for t in trips(now.date()):
        if t["start"] == tomorrow and said.get(str(t["id"])) != t["start"]:
            said[str(t["id"])] = t["start"]
            left, papers = t["pack"]["n"] - t["pack"]["done"], t["papers"]["n"] - t["papers"]["done"]
            notify(f"Reminder: {t['title']} starts tomorrow." + (f" {left} thing{'' if left == 1 else 's'} left to pack." if left else "") + (f" {papers} paper{'' if papers == 1 else 's'} not ticked." if papers else ""), "reminder")
            sent += 1
    if sent:
        schedule.set_setting("trips_said", dict(list(said.items())[-50:]))
    return sent

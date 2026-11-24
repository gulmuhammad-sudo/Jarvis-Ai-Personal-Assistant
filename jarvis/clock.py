"""Clock (Phase 8): timers that survive a restart, focus rounds, the stopwatch, ringing with snooze, and the time elsewhere.

Everything is in the local database (timers, stopwatch, focus_log); nothing goes online. (Alarms are in schedule.py.)
A running timer keeps the moment it is due, a paused one the seconds it has left. Moments are PC time in seconds, so a
timer runs on while the PC sleeps or the app is closed.
"""
from __future__ import annotations

import functools
import json
import math
import threading
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from . import schedule
from .planner import _db

MAX_SECONDS = 7 * 86400
MAX_TIMERS = 30
MAX_LABEL = 120
MAX_LAPS = 200
LATE = 10 * 60                      # a timer that ended a little ago (PC asleep) still rings; later it's only told
FORGET = 24 * 3600                  # ...and after a day not even that
RING_EVERY = 12                     # seconds between rings
RING_MINUTES = (0, 1, 2, 5)         # how long it rings until you stop it (0 = once)
FOCUS = {"work": (1, 180, 25), "rest": (1, 60, 5), "rounds": (1, 12, 4)}        # minutes, minutes, rounds: least, most, usual


def _int(value: Any, low: int, high: int, what: str) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    try:
        n = int(str(value).strip())
    except ValueError:
        raise ValueError(f"{what} must be a whole number from {low} to {high}.") from None
    if not low <= n <= high:
        raise ValueError(f"{what} must be a whole number from {low} to {high}.")
    return n


def _seconds(value: Any) -> float:
    try:
        s = float(value)
    except (TypeError, ValueError):
        raise ValueError("How long? Give the seconds, e.g. 300.") from None
    if not math.isfinite(s) or not 0 < s <= MAX_SECONDS:
        raise ValueError("Timers can be from 1 second up to 7 days. For a clock time, use an alarm.")
    return s


def say(seconds: float) -> str:
    s = max(0, int(seconds + 0.5))
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return " ".join(f"{n} {w}{'' if n == 1 else 's'}" for n, w in ((h, "hour"), (m, "minute"), (s, "second")) if n) or "0 seconds"


# ---------------- timers ----------------
_T = "id, kind, label, total, due, left, extra"
_WAKE = threading.Condition()
_CHANGED: Callable[[], None] | None = None         # the page is told (hud.py)


def _changed() -> None:
    with _WAKE:
        _WAKE.notify_all()
    if _CHANGED:
        try:
            _CHANGED()
        except Exception as e:
            print(f"[clock] {type(e).__name__}: {e}")


def _row(r, now: float) -> dict:
    left = r[5] if r[4] is None else max(0.0, r[4] - now)
    return {"id": r[0], "kind": r[1], "label": r[2], "total": r[3], "due": r[4], "left": left, "paused": r[4] is None,
            "extra": json.loads(r[6] or "{}")}


def timers(now: float | None = None) -> list[dict]:
    now = now or time.time()
    c, lock = _db()
    with lock:
        rows = [_row(r, now) for r in c.execute(f"SELECT {_T} FROM timers").fetchall()]
    return sorted(rows, key=lambda t: (t["paused"], t["left"], t["id"]))


def get(ref: Any) -> dict | None:
    """By number, whole name, or words that fit only one. Nothing said: the only one there is."""
    rows = timers()
    s = str(ref if ref is not None else "").strip().lstrip("#")
    if not s:
        return rows[0] if len(rows) == 1 else None
    if s.isdigit():
        return next((t for t in rows if t["id"] == int(s)), None)
    low = s.casefold()
    for hits in ([t for t in rows if t["label"].casefold() == low], [t for t in rows if all(w in t["label"].casefold() for w in low.split())]):
        if len(hits) == 1:
            return hits[0]
    return None


def add(seconds: Any, label: Any = "", kind: str = "timer", extra: dict | None = None) -> dict:
    s = _seconds(seconds)
    label = " ".join(str(label or "").split())[:MAX_LABEL] or "Timer"
    c, lock = _db()
    with lock, c:
        if c.execute("SELECT count(*) FROM timers").fetchone()[0] >= MAX_TIMERS:
            raise ValueError(f"There are already {MAX_TIMERS} timers. Cancel some first.")
        tid = c.execute("INSERT INTO timers (kind, label, total, due, extra) VALUES (?, ?, ?, ?, ?)",
                        (kind, label, s, time.time() + s, json.dumps(extra or {}))).lastrowid
    _changed()
    return next(t for t in timers() if t["id"] == tid)


def pause(timer_id: Any, on: bool = True) -> dict:
    now = time.time()
    c, lock = _db()
    with lock, c:
        if on:
            c.execute("UPDATE timers SET left = max(0, due - ?), due = NULL WHERE id = ? AND due IS NOT NULL", (now, int(timer_id)))
        else:
            c.execute("UPDATE timers SET due = ? + left, left = NULL WHERE id = ? AND due IS NULL", (now, int(timer_id)))
        r = c.execute(f"SELECT {_T} FROM timers WHERE id = ?", (int(timer_id),)).fetchone()
    if not r:
        raise ValueError("That timer is gone.")
    _changed()
    return _row(r, now)


def extend(timer_id: Any, seconds: Any) -> dict:
    """A minute more (or less: it never goes under one second)."""
    now = time.time()
    c, lock = _db()
    with lock, c:
        r = c.execute(f"SELECT {_T} FROM timers WHERE id = ?", (int(timer_id),)).fetchone()
        if not r:
            raise ValueError("That timer is gone.")
        t = _row(r, now)
        try:
            left = max(1.0, t["left"] + float(seconds))
        except (TypeError, ValueError):
            raise ValueError("How many seconds more?") from None
        if not left <= MAX_SECONDS:
            raise ValueError("Timers can be up to 7 days.")
        c.execute("UPDATE timers SET due = ?, left = ?, total = max(total, ?) WHERE id = ?",
                  (None if t["paused"] else now + left, left if t["paused"] else None, left, t["id"]))
    _changed()
    return next(x for x in timers() if x["id"] == t["id"])


def cancel(timer_id: Any) -> dict | None:
    t = next((x for x in timers() if x["id"] == int(timer_id)), None)
    if not t or not _take(t["id"]):
        return None
    if t["kind"] == "focus":
        _log_focus((t["total"] - t["left"]) / 60, t["label"])          # what was done counts
    _changed()
    return t


def _take(timer_id: int) -> bool:
    """Remove it; True for the one that did (so it can't end twice)."""
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM timers WHERE id = ?", (timer_id,)).rowcount > 0


def describe(t: dict) -> str:
    what = {"focus": "Focus round {round} of {rounds}", "break": "Break after round {round}"}.get(t["kind"], "").format(**{"round": 1, "rounds": 1, **t["extra"]})
    name = f"{what}: {t['label']}" if what and t["label"] != "Focus" else what or t["label"]
    return f"#{t['id']} {name}: {say(t['left'])} left" + (" (paused)" if t["paused"] else f", ends {datetime.fromtimestamp(t['due']):%a %d %b %H:%M:%S}" if t["left"] > 43200
                                                          else f", ends {datetime.fromtimestamp(t['due']):%H:%M:%S}")


# ---------------- focus rounds ----------------
def focus(work: Any = None, rest: Any = None, rounds: Any = None, label: Any = "") -> dict:
    got = {k: _int(v if v not in (None, "") else usual, low, high, {"work": "Focus minutes", "rest": "Break minutes", "rounds": "Rounds"}[k])
           for (k, (low, high, usual)), v in zip(FOCUS.items(), (work, rest, rounds))}
    if any(t["kind"] in ("focus", "break") for t in timers()):
        raise ValueError("Focus rounds are already running. Stop them first.")
    return add(got["work"] * 60, label or "Focus", "focus", {**got, "round": 1})


def focus_stop() -> dict | None:
    t = next((t for t in timers() if t["kind"] in ("focus", "break")), None)
    return cancel(t["id"]) if t else None


def focus_skip() -> dict | None:
    """On to the next: a round ends early (what was done counts), or the break does."""
    t = next((t for t in timers() if t["kind"] in ("focus", "break")), None)
    if not t or not _take(t["id"]):
        return None
    if t["kind"] == "focus":
        _log_focus((t["total"] - t["left"]) / 60, t["label"])
    nxt = _next_part(t)
    _changed()
    return nxt or {}


def _next_part(t: dict) -> dict | None:
    x = t["extra"]
    if t["kind"] == "focus":
        return add(x["rest"] * 60, t["label"], "break", x) if x["round"] < x["rounds"] else None
    return add(x["work"] * 60, t["label"], "focus", {**x, "round": x["round"] + 1})


def _log_focus(minutes: float, label: str, at: datetime | None = None) -> None:
    if minutes >= 1:
        c, lock = _db()
        with lock, c:
            c.execute("INSERT INTO focus_log (day, minutes, label) VALUES (?, ?, ?)", ((at or datetime.now()).date().isoformat(), int(minutes + 1e-6), label))


def focus_days(days: int = 7, today: date | None = None) -> list[dict]:
    today = today or date.today()
    first = today - timedelta(days=days - 1)
    c, lock = _db()
    with lock:
        got = dict(c.execute("SELECT day, sum(minutes) FROM focus_log WHERE day >= ? GROUP BY day", (first.isoformat(),)).fetchall())
    return [{"day": d, "minutes": got.get(d, 0)} for d in ((first + timedelta(days=i)).isoformat() for i in range(days))]


# ---------------- ending ----------------
def run_due(done: Callable[[str, str, bool], None], now: float | None = None) -> int:
    """End what is due. done(text, label, ring): told, and rung unless it is an old one."""
    now = now or time.time()
    n = 0
    for t in timers(now):
        if t["paused"] or t["due"] > now:
            continue
        if not _take(t["id"]):
            continue
        n += 1
        late = now - t["due"]
        try:
            _ended(t, late, done)
        except Exception as e:                       # one that fails never holds up the others
            print(f"[clock] {type(e).__name__}: {e}")
    if n:
        _changed()
    return n


def _ended(t: dict, late: float, done: Callable[[str, str, bool], None]) -> None:
    at = datetime.fromtimestamp(t["due"])
    if t["kind"] == "focus":
        _log_focus(t["total"] / 60, t["label"], at)
    if late > LATE:                                  # the app was closed or the PC asleep
        if late <= FORGET:
            what = {"focus": "Your focus round", "break": "Your break"}.get(t["kind"], f'The timer "{t["label"]}"')
            done(f"{what} ended at {at:%H:%M}, while the app or the PC was off.", t["label"], False)
        return
    x = t["extra"]
    if t["kind"] == "focus":
        nxt = _next_part(t)
        if nxt:
            done(f"Focus round {x['round']} of {x['rounds']} is done. Break: {x['rest']} minute{'' if x['rest'] == 1 else 's'}.", "Focus round done", True)
        else:
            done(f"All {x['rounds']} focus rounds are done. Well done." if x["rounds"] > 1 else "Your focus time is done. Well done.", "Focus done", True)
    elif t["kind"] == "break":
        _next_part(t)
        done(f"The break is over. Focus round {x['round'] + 1} of {x['rounds']} starts now.", "Break over", True)
    else:
        done(f"Reminder: {t['label']}" if t["label"] != "Timer" else "Your timer is done.", t["label"], True)


_GEN = 0


def stop() -> None:
    """End the thread (tests; a second start also ends the first)."""
    global _GEN, _CHANGED
    _GEN, _CHANGED = _GEN + 1, None
    with _WAKE:
        _WAKE.notify_all()


def start(done: Callable[[str, str, bool], None], changed: Callable[[], None] | None = None) -> threading.Thread:
    """The thread that ends timers on time."""
    global _CHANGED
    stop()
    _CHANGED, mine = changed, _GEN

    def loop() -> None:
        while mine == _GEN:
            try:
                run_due(done)
                running = [t["due"] for t in timers() if not t["paused"]]
                wait = min([30.0] + [max(0.02, d - time.time()) for d in running])      # (30 s: the PC's clock may be changed)
            except Exception as e:
                print(f"[clock] {type(e).__name__}: {e}")
                wait = 5.0
            with _WAKE:
                if mine == _GEN:
                    _WAKE.wait(wait)

    t = threading.Thread(target=loop, name="clock", daemon=True)
    t.start()
    return t


# ---------------- ringing ----------------
def ring_minutes() -> int:
    m = schedule.get_setting("ring_minutes", 2)
    return m if m in RING_MINUTES else 2


def set_ring_minutes(value: Any) -> int:
    m = _int(value, 0, 5, "Minutes")
    if m not in RING_MINUTES:
        raise ValueError("It can ring once, or for 1, 2 or 5 minutes.")
    schedule.set_setting("ring_minutes", m)
    return m


class Ringer:
    """Rings again and again until it is stopped, snoozed, or its time is over."""

    def __init__(self, play: Callable[[str, bool], None], changed: Callable[[list[dict]], None],
                 missed: Callable[[str], None], quiet: Callable[[], bool] = lambda: False):
        self.play, self.changed, self.missed, self.quiet = play, changed, missed, quiet
        self._lock = threading.Lock()
        self._rings: dict[int, dict] = {}
        self._next = 1
        self._last: dict | None = None               # so that "snooze" a moment later still knows what rang

    def list(self) -> list[dict]:
        with self._lock:
            return [{k: r[k] for k in ("id", "label", "what", "at")} for r in self._rings.values()]

    def start(self, label: str, what: str = "timer") -> int:
        r = {"label": label, "what": what, "at": datetime.now().strftime("%H:%M"), "started": time.time(), "off": threading.Event()}
        with self._lock:
            r["id"], self._next = self._next, self._next + 1
            self._rings[r["id"]] = r
            self._last = r
        self.changed(self.list())
        threading.Thread(target=self._ring, args=(r,), name="ring", daemon=True).start()
        return r["id"]

    def _ring(self, r: dict) -> None:
        end = time.time() + ring_minutes() * 60
        first = True
        while True:
            try:
                self.play(r["label"], first)
            except Exception as e:
                print(f"[clock] couldn't ring: {e}")
            first = False
            if time.time() + RING_EVERY > end or self.quiet():      # in a call it rings once
                r["off"].wait(min(RING_EVERY, 30))
                break
            if r["off"].wait(RING_EVERY):
                break
        with self._lock:
            mine = self._rings.pop(r["id"], None) is not None
        if mine:                                                     # nobody stopped it
            self.changed(self.list())
            if r["what"] == "alarm" and ring_minutes():
                self.missed(f"Nobody stopped the alarm \"{r['label']}\" ({r['at']}).")

    def stop(self, ring_id: Any = None) -> list[dict]:
        with self._lock:
            gone = [self._rings.pop(i) for i in list(self._rings) if ring_id in (None, "") or i == int(ring_id)]
        for r in gone:
            r["off"].set()
        if gone:
            self.changed(self.list())
        return gone

    def snooze(self, minutes: Any = 5, ring_id: Any = None) -> dict:
        m = _int(minutes if minutes not in (None, "") else 5, 1, 120, "Snooze minutes")
        gone = self.stop(ring_id)
        if not gone and ring_id in (None, "") and self._last and time.time() - self._last["started"] < 15 * 60:
            gone = [self._last]
        if not gone:
            raise ValueError("Nothing is ringing.")
        t = [add(m * 60, g["label"], "snooze") for g in gone][0]
        self._last = None                            # snoozed: not again
        return t


# ---------------- stopwatch ----------------
def stopwatch(now: float | None = None) -> dict:
    now = now or time.time()
    c, lock = _db()
    with lock:
        r = c.execute("SELECT started, banked, laps FROM stopwatch WHERE id = 1").fetchone() or (None, 0.0, "[]")
    return {"running": r[0] is not None, "elapsed": max(0.0, r[1] + (now - r[0] if r[0] is not None else 0.0)), "laps": json.loads(r[2])}


def stopwatch_do(action: str, now: float | None = None) -> dict:
    now = now or time.time()
    s = stopwatch(now)
    started, banked, laps = (now if s["running"] else None), s["elapsed"], s["laps"]
    if action == "start":
        started = now
    elif action == "stop":
        started = None
    elif action == "reset":
        started, banked, laps = None, 0.0, []
    elif action == "lap":
        if not s["running"]:
            raise ValueError("The stopwatch isn't running.")
        if len(laps) >= MAX_LAPS:
            raise ValueError(f"That's {MAX_LAPS} laps already.")
        laps = [*laps, round(s["elapsed"], 2)]
    else:
        raise ValueError("Unknown action.")
    c, lock = _db()
    with lock, c:
        c.execute("INSERT OR REPLACE INTO stopwatch (id, started, banked, laps) VALUES (1, ?, ?, ?)", (started, banked, json.dumps(laps)))
    _changed()
    return stopwatch(now)


def exact(seconds: float) -> str:
    cs = int(seconds * 100 + 0.5)
    h, m, s, cs = cs // 360000, cs % 360000 // 6000, cs % 6000 // 100, cs % 100
    return (f"{h}:{m:02d}" if h else f"{m:02d}") + f":{s:02d}.{cs:02d}"


def describe_stopwatch(s: dict) -> str:
    text = f"The stopwatch {'is running' if s['running'] else 'is stopped'} at {exact(s['elapsed'])}."
    if s["laps"]:
        last = [0.0, *s["laps"]]
        text += " Laps: " + ", ".join(f"{i}: {exact(b - a)}" for i, (a, b) in enumerate(zip(last, last[1:]), 1)) + "."
    return text


# ---------------- the time elsewhere ----------------
# place -> Windows' own time zone (its summer-time rules come with Windows updates: nothing to download)
ZONES: dict[str, str] = {
    "Karachi": "Pakistan Standard Time", "Lahore": "Pakistan Standard Time", "Islamabad": "Pakistan Standard Time", "Makkah": "Arab Standard Time",
    "Madinah": "Arab Standard Time", "Riyadh": "Arab Standard Time", "Jeddah": "Arab Standard Time", "Kuwait City": "Arab Standard Time",
    "Doha": "Arab Standard Time", "Baghdad": "Arabic Standard Time", "Dubai": "Arabian Standard Time", "Abu Dhabi": "Arabian Standard Time",
    "Muscat": "Arabian Standard Time", "Tehran": "Iran Standard Time", "Kabul": "Afghanistan Standard Time", "Delhi": "India Standard Time",
    "Mumbai": "India Standard Time", "Colombo": "Sri Lanka Standard Time", "Kathmandu": "Nepal Standard Time", "Dhaka": "Bangladesh Standard Time",
    "Tashkent": "West Asia Standard Time", "Baku": "Azerbaijan Standard Time", "Istanbul": "Turkey Standard Time", "Jerusalem": "Israel Standard Time",
    "Amman": "Jordan Standard Time", "Beirut": "Middle East Standard Time", "Cairo": "Egypt Standard Time", "Nairobi": "E. Africa Standard Time",
    "Lagos": "W. Central Africa Standard Time", "Johannesburg": "South Africa Standard Time", "Casablanca": "Morocco Standard Time",
    "London": "GMT Standard Time", "Dublin": "GMT Standard Time", "Lisbon": "GMT Standard Time", "Paris": "Romance Standard Time",
    "Madrid": "Romance Standard Time", "Brussels": "Romance Standard Time", "Berlin": "W. Europe Standard Time", "Rome": "W. Europe Standard Time",
    "Amsterdam": "W. Europe Standard Time", "Vienna": "W. Europe Standard Time", "Zurich": "W. Europe Standard Time",
    "Stockholm": "W. Europe Standard Time", "Oslo": "W. Europe Standard Time", "Copenhagen": "Romance Standard Time", "Warsaw": "Central European Standard Time",
    "Athens": "GTB Standard Time", "Helsinki": "FLE Standard Time", "Kyiv": "FLE Standard Time", "Moscow": "Russian Standard Time",
    "Bangkok": "SE Asia Standard Time", "Jakarta": "SE Asia Standard Time", "Kuala Lumpur": "Singapore Standard Time", "Singapore": "Singapore Standard Time",
    "Manila": "Singapore Standard Time", "Hong Kong": "China Standard Time", "Beijing": "China Standard Time", "Shanghai": "China Standard Time",
    "Taipei": "Taipei Standard Time", "Seoul": "Korea Standard Time", "Tokyo": "Tokyo Standard Time", "Perth": "W. Australia Standard Time",
    "Sydney": "AUS Eastern Standard Time", "Melbourne": "AUS Eastern Standard Time", "Auckland": "New Zealand Standard Time",
    "New York": "Eastern Standard Time", "Washington": "Eastern Standard Time", "Toronto": "Eastern Standard Time", "Miami": "Eastern Standard Time",
    "Chicago": "Central Standard Time", "Houston": "Central Standard Time", "Denver": "Mountain Standard Time", "Los Angeles": "Pacific Standard Time",
    "San Francisco": "Pacific Standard Time", "Seattle": "Pacific Standard Time", "Vancouver": "Pacific Standard Time",
    "Mexico City": "Central Standard Time (Mexico)", "Sao Paulo": "E. South America Standard Time", "Buenos Aires": "Argentina Standard Time",
    "UTC": "UTC",
}
ALIASES = {"mecca": "Makkah", "makka": "Makkah", "medina": "Madinah", "madina": "Madinah", "new delhi": "Delhi", "kiev": "Kyiv", "nyc": "New York", "la": "Los Angeles",
           "bombay": "Mumbai", "uk": "London", "england": "London", "pakistan": "Karachi", "saudi arabia": "Riyadh", "saudia": "Riyadh", "uae": "Dubai",
           "india": "Delhi", "japan": "Tokyo", "turkey": "Istanbul", "germany": "Berlin", "france": "Paris", "qatar": "Doha", "egypt": "Cairo", "gmt": "UTC"}
MAX_PLACES = 10
DEFAULT_PLACES = ["Makkah", "Dubai", "London", "New York"]


@functools.lru_cache(maxsize=None)
def _zone(name: str):
    import win32timezone
    return win32timezone.TimeZoneInfo(name)


def find_place(text: Any) -> str:
    t = " ".join(str(text or "").strip().casefold().split())
    if t in ALIASES:
        return ALIASES[t]
    hits = [p for p in ZONES if p.casefold() == t] or [p for p in ZONES if len(t) > 2 and p.casefold().startswith(t)]
    if len(hits) != 1:
        raise ValueError(f"I don't know the time in {t.title()[:40]!r}. Try a big city, e.g. Karachi, London or New York." if t else "Which city?")
    return hits[0]


def place_time(place: str, now: datetime | None = None) -> dict:
    there = (now or datetime.now(timezone.utc)).astimezone(_zone(ZONES[place]))
    here = (now or datetime.now(timezone.utc)).astimezone()
    return {"place": place, "offset": int(there.utcoffset().total_seconds() // 60), "time": there.strftime("%H:%M"), "day": there.strftime("%a %d %b"),
            "ahead": int((there.utcoffset() - here.utcoffset()).total_seconds() // 60)}


def describe_place(p: dict) -> str:
    h = abs(p["ahead"])
    gap = "the same time as here" if not h else f"{h // 60}{':%02d' % (h % 60) if h % 60 else ''} hour{'' if h == 60 else 's'} {'ahead' if p['ahead'] > 0 else 'behind'}"
    return f"{p['place']}: {p['time']}, {p['day']} ({gap})"


def places() -> list[str]:
    got = schedule.get_setting("world_places")
    return [p for p in got if p in ZONES][:MAX_PLACES] if isinstance(got, list) else list(DEFAULT_PLACES)


def add_place(text: Any) -> str:
    p, now = find_place(text), places()
    if p in now:
        raise ValueError(f"{p} is already there.")
    if len(now) >= MAX_PLACES:
        raise ValueError(f"That's {MAX_PLACES} places. Remove one first.")
    schedule.set_setting("world_places", [*now, p])
    return p


def remove_place(text: Any) -> None:
    schedule.set_setting("world_places", [p for p in places() if p != str(text)])


# ---------------- the page ----------------
def load() -> dict:
    now = time.time()
    world = []
    for p in places():
        try:
            world.append(place_time(p))
        except Exception as e:                       # a Windows without that zone
            print(f"[clock] {p}: {type(e).__name__}: {e}")
    alarms = []
    for a in schedule.list_alarms():
        nf = schedule.next_fire(a)
        alarms.append({"id": a["id"], "time": a["time"], "label": a["label"], "repeat": a["repeat"], "days": a["days"], "enabled": a.get("enabled", True),
                       "next": nf.strftime("%a %d %b, %H:%M") if nf else ""})
    return {"now": now, "timers": timers(now), "stopwatch": stopwatch(now), "alarms": sorted(alarms, key=lambda a: a["time"]), "world": world,
            "all_places": sorted(ZONES), "focus": focus_days(), "ring_minutes": ring_minutes()}

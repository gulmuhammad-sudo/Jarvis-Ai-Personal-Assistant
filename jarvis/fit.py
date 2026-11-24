"""Fitness (Phase 8): weight, water, steps, sleep and workouts, with daily targets. No doctor: numbers only, no advice.

Everything is in the local database (fit_log, workouts); nothing goes online. Health is private: the assistant can write what
it is told, but it reads nothing back until the owner allows it (Daily › Fitness). No agent or automation has it.
"""
from __future__ import annotations

import csv
import math
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .planner import CATCH_UP, _db, _now, parse_clock

MAX_ROWS = 50_000
# what is measured: (least, most, decimals, unit, added up over the day?)
KINDS: dict[str, tuple[float, float, int, str, bool]] = {
    "weight": (20, 400, 1, "kg", False), "water": (10, 10_000, 0, "ml", True), "steps": (1, 200_000, 0, "steps", True), "sleep": (0.1, 24, 2, "hours", False),
}
LABELS = {"weight": "Weight", "water": "Water", "steps": "Steps", "sleep": "Sleep"}
WORKOUTS = ("walk", "run", "cycle", "swim", "gym", "strength", "yoga", "football", "cricket", "badminton", "stretching", "other")
TARGETS = {"water": (200, 10_000, 2000), "steps": (500, 100_000, 8000), "sleep": (3, 14, 8), "workout": (10, 2000, 150)}      # workout: minutes a week
_UNITS = {"weight": {"kg": 1, "kgs": 1, "kilo": 1, "kilos": 1, "kilogram": 1, "kilograms": 1, "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237},
          "water": {"ml": 1, "l": 1000, "litre": 1000, "litres": 1000, "liter": 1000, "liters": 1000, "glass": 250, "glasses": 250, "cup": 250, "cups": 250, "bottle": 500, "bottles": 500},
          "steps": {"steps": 1, "step": 1}, "sleep": {"hours": 1, "hour": 1, "h": 1, "hrs": 1, "minutes": 1 / 60, "min": 1 / 60, "mins": 1 / 60, "m": 1 / 60}}


# ---------------- reading numbers ----------------
def _num(value: Any, what: str) -> float:
    s = str(value if value is not None else "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    s = re.sub(r"(?<=\d),(?=\d{3}(\D|$))", "", s).replace(",", ".")
    try:
        x = float(s)
    except ValueError:
        raise ValueError(f"{what} must be a number.") from None
    if not math.isfinite(x):
        raise ValueError(f"{what} must be a number.")
    return x


def amount(kind: str, value: Any, unit: Any = "") -> float:
    """250, '2 glasses', '1.5 l', '7h 30m', '7:30', '154 lb' in the kind's own unit."""
    if kind not in KINDS:
        raise ValueError(f"I can note {', '.join(KINDS)} and workouts.")
    s = str(value if value is not None else "").strip().lower()
    u = str(unit or "").strip().lower()
    if kind == "sleep":
        m = re.fullmatch(r"(\d{1,2}):([0-5]\d)", s) or re.fullmatch(r"(\d{1,2})\s*h(?:ours?|rs?)?\s*(\d{1,2})\s*m?(?:in(?:ute)?s?)?", s)
        if m:
            s, u = str(int(m.group(1)) + int(m.group(2)) / 60), "hours"
    m = re.fullmatch(r"([\d.,۰-۹٠-٩]+)\s*([a-z]+)", s)
    if m:
        s, u = m.group(1), m.group(2)
    if u and u not in _UNITS[kind]:
        raise ValueError(f"I don't know the unit {u[:20]!r} for {kind}.")
    low, high, digits, base, _ = KINDS[kind]
    x = round(_num(s, LABELS[kind]) * _UNITS[kind].get(u, 1), digits)
    if not low <= x <= high:
        raise ValueError(f"{LABELS[kind]}: from {low:g} to {high:g} {base}.")
    return x


def show(kind: str, x: float) -> str:
    if kind == "sleep":
        mins = round(x * 60)
        return f"{mins // 60} h {mins % 60} min" if mins % 60 else f"{mins // 60} h"
    if kind == "water":
        return f"{x / 1000:g} l" if x >= 1000 else f"{x:g} ml"
    return f"{x:,.{KINDS[kind][2]}f} {KINDS[kind][3]}" if kind != "weight" else f"{x:g} kg"


def _day(value: Any) -> str:
    from .life import _past_day
    return _past_day(value, "The day")


# ---------------- settings ----------------
def targets() -> dict[str, float]:
    from . import schedule
    got = schedule.get_setting("fit_targets")
    got = got if isinstance(got, dict) else {}
    out = {}
    for k, (low, high, usual) in TARGETS.items():
        v = got.get(k, usual)
        out[k] = v if isinstance(v, (int, float)) and not isinstance(v, bool) and low <= v <= high else usual
    return out


def settings() -> dict:
    from . import schedule
    h = schedule.get_setting("fit_height")
    return {"targets": targets(), "height": h if isinstance(h, (int, float)) and not isinstance(h, bool) and 80 <= h <= 250 else None,
            "ai": schedule.get_setting("fit_ai") is True, "water_every": _water_every(), "water_from": schedule.get_setting("fit_water_from") or "09:00",
            "water_to": schedule.get_setting("fit_water_to") or "21:00", "move": schedule.get_setting("fit_move") or ""}


def _water_every() -> int:
    from . import schedule
    n = schedule.get_setting("fit_water_every", 0)
    return n if n in (0, 1, 2, 3, 4) and not isinstance(n, bool) else 0


def save_settings(d: dict) -> None:
    from . import schedule
    if isinstance(d.get("targets"), dict):
        new = targets()
        for k, v in d["targets"].items():
            if k not in TARGETS:
                raise ValueError("I don't know that target.")
            low, high, _ = TARGETS[k]
            x = round(_num(v, "The target"), 1)
            if not low <= x <= high:
                raise ValueError(f"The target for {k}: from {low:g} to {high:g}.")
            new[k] = x
        schedule.set_setting("fit_targets", new)
    if "height" in d:
        if str(d["height"] or "").strip():
            h = round(_num(d["height"], "Your height"), 1)
            if not 80 <= h <= 250:
                raise ValueError("Your height: from 80 to 250 cm.")
            schedule.set_setting("fit_height", h)
        else:
            schedule.set_setting("fit_height", None)
    if "ai" in d:
        schedule.set_setting("fit_ai", d["ai"] is True)
    if "water_every" in d:
        n = str(d["water_every"]).strip()
        if n not in ("0", "1", "2", "3", "4"):
            raise ValueError("Water reminders: off, or every 1 to 4 hours.")
        schedule.set_setting("fit_water_every", int(n))
    times = {k: parse_clock(str(d[k])) for k in ("water_from", "water_to") if d.get(k)}
    if times:
        a, b = times.get("water_from") or settings()["water_from"], times.get("water_to") or settings()["water_to"]
        if a >= b:
            raise ValueError("The first water reminder must be before the last one.")
        for k, v in times.items():
            schedule.set_setting("fit_" + k, v)
    if "move" in d:
        t = str(d["move"] or "").strip()
        schedule.set_setting("fit_move", parse_clock(t) if t else None)


# ---------------- measurements ----------------
def _row(r) -> dict:
    return {"id": r[0], "kind": r[1], "day": r[2], "value": r[3], "text": show(r[1], r[3])}


def add(kind: Any, value: Any, day: Any = "", unit: Any = "") -> dict:
    """Water and steps add up over the day; weight and sleep replace what the day had."""
    k = str(kind or "").strip().lower()
    x, d = amount(k, value, unit), _day(day)
    c, lock = _db()
    with lock, c:
        if c.execute("SELECT count(*) FROM fit_log").fetchone()[0] >= MAX_ROWS:
            raise ValueError("There are too many entries.")
        if not KINDS[k][4]:
            c.execute("DELETE FROM fit_log WHERE kind = ? AND day = ?", (k, d))
        else:
            so_far = c.execute("SELECT coalesce(sum(value), 0) FROM fit_log WHERE kind = ? AND day = ?", (k, d)).fetchone()[0]
            if so_far + x > KINDS[k][1]:
                raise ValueError(f"That would be {show(k, so_far + x)} on one day. Is it right? Remove something first.")
        rid = c.execute("INSERT INTO fit_log (kind, day, value, created) VALUES (?, ?, ?, ?)", (k, d, x, _now())).lastrowid
    return {"id": rid, "kind": k, "day": d, "value": x, "text": show(k, x), "total": day_total(k, d)}


def day_total(kind: str, day: str) -> float:
    c, lock = _db()
    with lock:
        return c.execute("SELECT coalesce(sum(value), 0) FROM fit_log WHERE kind = ? AND day = ?", (kind, day)).fetchone()[0]


def delete(row_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM fit_log WHERE id = ?", (int(row_id),)).rowcount > 0


def rows(kind: str = "", limit: int = 60) -> list[dict]:
    c, lock = _db()
    with lock:
        return [_row(r) for r in c.execute("SELECT id, kind, day, value FROM fit_log" + (" WHERE kind = ?" if kind else "") + " ORDER BY day DESC, id DESC LIMIT ?",
                                           ((kind, limit) if kind else (limit,))).fetchall()]


def series(kind: str, days: int = 30, today: date | None = None) -> list[dict]:
    today = today or date.today()
    first = today - timedelta(days=days - 1)
    c, lock = _db()
    with lock:
        got = dict(c.execute("SELECT day, sum(value) FROM fit_log WHERE kind = ? AND day >= ? GROUP BY day", (kind, first.isoformat())).fetchall())
    return [{"day": d, "value": got.get(d)} for d in ((first + timedelta(days=i)).isoformat() for i in range(days))]


# ---------------- workouts ----------------
def add_workout(what: Any, minutes: Any, day: Any = "", distance: Any = None, note: Any = "", workout_id: int | None = None) -> dict:
    w = " ".join(str(what or "").lower().split())
    w = {"walking": "walk", "running": "run", "cycling": "cycle", "swimming": "swim", "weights": "strength", "stretch": "stretching", "jogging": "run"}.get(w, w)
    if not w or len(w) > 40:
        raise ValueError("What was it? e.g. walk, run, gym, cricket.")
    m = _num(minutes, "Minutes")
    if not 1 <= m <= 1440:
        raise ValueError("Minutes: from 1 to 1440.")
    km = None
    if str(distance if distance is not None else "").strip():
        km = round(_num(distance, "The distance"), 2)
        if not 0.01 <= km <= 1000:
            raise ValueError("The distance: from 0.01 to 1000 km.")
    n = " ".join(str(note or "").split())
    if len(n) > 300:
        raise ValueError("The note is too long (up to 300 characters).")
    d = _day(day)
    c, lock = _db()
    with lock, c:
        if workout_id is None:
            if c.execute("SELECT count(*) FROM workouts").fetchone()[0] >= MAX_ROWS:
                raise ValueError("There are too many entries.")
            workout_id = c.execute("INSERT INTO workouts (day, what, minutes, km, note, created) VALUES (?, ?, ?, ?, ?, ?)", (d, w, round(m), km, n, _now())).lastrowid
        elif not c.execute("UPDATE workouts SET day = ?, what = ?, minutes = ?, km = ?, note = ? WHERE id = ?", (d, w, round(m), km, n, workout_id)).rowcount:
            raise ValueError("That workout is gone.")
    return next(x for x in workouts(limit=MAX_ROWS) if x["id"] == workout_id)


def workouts(limit: int = 60, first: str = "") -> list[dict]:
    c, lock = _db()
    with lock:
        got = c.execute("SELECT id, day, what, minutes, km, note FROM workouts WHERE day >= ? ORDER BY day DESC, id DESC LIMIT ?", (first, limit)).fetchall()
    out = []
    for r in got:
        x = dict(zip(("id", "day", "what", "minutes", "km", "note"), r))
        x["pace"] = f"{int(r[3] / r[4])}:{int(r[3] / r[4] * 60 % 60):02d} min/km" if r[4] and r[2] in ("walk", "run") and r[3] / r[4] < 60 else ""
        out.append(x)
    return out


def delete_workout(workout_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM workouts WHERE id = ?", (int(workout_id),)).rowcount > 0


def week_minutes(today: date | None = None) -> int:
    today = today or date.today()
    return sum(w["minutes"] for w in workouts(MAX_ROWS, (today - timedelta(days=today.weekday())).isoformat()) if w["day"] <= today.isoformat())


# ---------------- how it goes ----------------
def bmi(weight: float | None, height: float | None) -> float | None:
    return round(weight / (height / 100) ** 2, 1) if weight and height else None


def overview(today: date | None = None) -> dict:
    today = today or date.today()
    t, s = targets(), settings()
    day = today.isoformat()
    last = next(iter(rows("weight", 1)), None)
    month = next((x["value"] for x in series("weight", 30, today) if x["value"]), None)
    out = {"today": {k: day_total(k, day) for k in ("water", "steps", "sleep")}, "targets": t, "week": week_minutes(today),
           "weight": last["value"] if last else None, "weight_day": last["day"] if last else None,
           "change": round(last["value"] - month, 1) if last and month else None, "bmi": bmi(last["value"] if last else None, s["height"])}
    out["text"] = {k: show(k, v) for k, v in out["today"].items()}
    out["averages"] = {}
    for k in ("water", "steps", "sleep"):
        got = [x["value"] for x in series(k, 7, today) if x["value"]]
        out["averages"][k] = show(k, sum(got) / len(got)) if got else ""
    return out


def describe(o: dict) -> str:
    t = o["targets"]
    parts = [f"Today: water {o['text']['water']} of {show('water', t['water'])}, steps {o['today']['steps']:,.0f} of {t['steps']:,.0f}, sleep {o['text']['sleep'] if o['today']['sleep'] else 'not noted'} (target {show('sleep', t['sleep'])}).",
             f"Workouts this week: {o['week']} of {t['workout']:g} minutes."]
    if o["weight"]:
        parts.append(f"Weight: {o['weight']:g} kg on {o['weight_day']}" + (f", {o['change']:+g} kg in 30 days" if o["change"] else "") + (f", BMI {o['bmi']}" if o["bmi"] else "") + ".")
    avg = ", ".join(f"{k} {v}" for k, v in o["averages"].items() if v)
    return " ".join(parts) + (f" Averages of the last 7 days (days with an entry): {avg}." if avg else "")


def load() -> dict:
    return {"overview": overview(), "settings": settings(), "series": {k: series(k) for k in KINDS}, "rows": rows(limit=40), "workouts": workouts(30), "kinds": WORKOUTS}


def export(folder: Path | None = None) -> Path:
    """Everything as CSV in your Documents folder. Never over an existing file."""
    from .life import _safe_cell
    folder = folder or Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    folder.mkdir(parents=True, exist_ok=True)
    data = [["Day", "What", "Value", "Unit", "Km", "Note"]]
    data += [[r["day"], r["kind"], f"{r['value']:g}", KINDS[r["kind"]][3], "", ""] for r in reversed(rows(limit=MAX_ROWS))]
    data += [[w["day"], _safe_cell(w["what"]), w["minutes"], "minutes", w["km"] or "", _safe_cell(w["note"])] for w in reversed(workouts(MAX_ROWS))]
    for n in range(1, 100):
        p = folder / f"My fitness {date.today().isoformat()}{f' ({n})' if n > 1 else ''}.csv"
        try:
            with open(p, "x", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows(data)
            return p
        except FileExistsError:
            continue
    raise ValueError("There are too many exports of today in Documents.")


# ---------------- reminders ----------------
def tick(now: datetime, notify: Callable[[str, str], None]) -> int:
    """Water every few hours (until the target is reached), and a time to move. Each once."""
    from . import schedule
    s, sent = settings(), 0
    at = lambda hhmm: datetime.combine(now.date(), datetime.strptime(hhmm, "%H:%M").time())           # noqa: E731
    if s["water_every"]:
        t, end, key = at(s["water_from"]), at(s["water_to"]), ""
        while t <= end and t <= now:
            if now - t <= CATCH_UP:
                key = t.isoformat(timespec="minutes")
            t += timedelta(hours=s["water_every"])
        if key and schedule.get_setting("fit_water_said") != key:
            schedule.set_setting("fit_water_said", key)
            if day_total("water", now.date().isoformat()) < s["targets"]["water"]:
                notify("Reminder: time for some water.", "reminder")
                sent += 1
    if s["move"] and timedelta(0) <= now - at(s["move"]) <= CATCH_UP and schedule.get_setting("fit_move_said") != now.date().isoformat():
        schedule.set_setting("fit_move_said", now.date().isoformat())
        if not any(w["day"] == now.date().isoformat() for w in workouts(5, now.date().isoformat())):
            notify("Reminder: time to move a little.", "reminder")
            sent += 1
    return sent

"""Goals and habits, journal and mood, money (Phase 7, part 3): the Planner page's other three tabs.

Everything is in the local database (tables goals, habits, habit_log, journal, money, budgets, bills); nothing goes online.
What you ask the assistant about goes to the AI with your message, like your tasks do. The journal is closed to the AI until you
allow it (setting journal_ai): until then it can only add what you tell it to write.

Money: you write down what you spend and get; nothing is connected to a bank and nothing is ever paid. Amounts are whole
hundredths (paisa, cents) so sums are exact. One currency, only a sign in front of the number.
"""
from __future__ import annotations

import csv
import json
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from . import planner
from .planner import MAX_NOTES, MAX_TITLE, _db, _now, _text, parse_clock, parse_day, say_when

MAX_GOALS, MAX_HABITS, MAX_STEPS = 200, 60, 40
MAX_ENTRIES, MAX_ENTRY = 20_000, 10_000
MAX_MONEY, MAX_BILLS = 100_000, 100
MAX_AMOUNT = 10**11                          # hundredths: a thousand million
MOODS = {1: "very low", 2: "low", 3: "okay", 4: "good", 5: "great"}
_MOOD_WORDS = {"very low": 1, "awful": 1, "terrible": 1, "low": 2, "bad": 2, "sad": 2, "okay": 3, "ok": 3, "fine": 3, "normal": 3, "good": 4,
               "happy": 4, "great": 5, "very good": 5, "excellent": 5}


# ---------------- settings ----------------
def settings() -> dict:
    from . import schedule
    return {"currency": schedule.get_setting("life_currency") or "Rs", "journal_ai": schedule.get_setting("journal_ai") is True,
            "journal_remind": schedule.get_setting("journal_remind") or ""}


def save_settings(d: dict) -> None:
    from . import schedule
    if "currency" in d:
        s = str(d["currency"] or "").strip()
        if not re.fullmatch(r"[^\W\d_]{1,5}\.?|[$€£¥₹₨﷼]", s):
            raise ValueError("The currency is up to five letters or a sign, like Rs, PKR, USD or $.")
        schedule.set_setting("life_currency", s)
    if "journal_ai" in d:
        schedule.set_setting("journal_ai", d["journal_ai"] is True)
    if "journal_remind" in d:
        t = str(d["journal_remind"] or "").strip()
        schedule.set_setting("journal_remind", parse_clock(t) if t else None)


def _whole(value: Any, low: int, high: int, what: str) -> int:
    try:
        n = int(value)
        if isinstance(value, bool) or (isinstance(value, float) and value != n):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{what} must be a whole number from {low} to {high}.") from None
    if not low <= n <= high:
        raise ValueError(f"{what} must be a whole number from {low} to {high}.")
    return n


def _past_day(value: Any, what: str) -> str:
    """A day that isn't in the future ('' = today). In the past, "kal" means yesterday."""
    today = date.today()
    s = str(value or "").strip().lower()
    if s in ("kal", "کل", "yesterday"):
        return (today - timedelta(days=1)).isoformat()
    if s in ("parson", "پرسوں", "day before yesterday"):
        return (today - timedelta(days=2)).isoformat()
    d = parse_day(s.removeprefix("last ") or "today", today)
    if d > today and s not in ("tomorrow", "day after tomorrow") and re.fullmatch(r"(on |last )?[a-z]+", s):      # "friday": the one that was
        d -= timedelta(days=7)
    if d > today:
        raise ValueError(f"{what} can't be in the future.")
    if d < date(1970, 1, 1):
        raise ValueError(f"{what} is too long ago.")
    return d.isoformat()


def _one_spelling(table: str, column: str, value: str) -> str:
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {column} FROM {table} WHERE {column} = ? COLLATE NOCASE LIMIT 1", (value,)).fetchone()
    return r[0] if r and value else value


def _find(items: list[dict], ref: Any, key: str) -> dict | None:
    """By number, whole name, or words that fit only one."""
    s = str(ref if ref is not None else "").strip().lstrip("#")
    if s.isdigit():
        return next((i for i in items if i["id"] == int(s)), None)
    low = s.casefold()
    exact = [i for i in items if i[key].casefold() == low]
    part = [i for i in items if low and all(w in i[key].casefold() for w in low.split())]
    return exact[0] if len(exact) == 1 else part[0] if len(part) == 1 else None


# ---------------- goals ----------------
_G = "id, title, why, area, target, progress, unit, due, steps, done, done_at, created"


def _goal(r) -> dict:
    steps = json.loads(r[8] or "[]")
    g = {"id": r[0], "title": r[1], "why": r[2], "area": r[3], "target": r[4], "progress": r[5], "unit": r[6], "due": r[7], "steps": steps,
         "done": bool(r[9]), "done_at": r[10], "created": r[11]}
    if g["done"]:
        pct = 100
    elif g["target"]:
        pct = int(max(0.0, min(1.0, g["progress"] / g["target"])) * 100)
    else:
        pct = int(100 * sum(1 for s in steps if s["done"]) / len(steps)) if steps else 0
    return {**g, "percent": pct}


def goals(done: bool | None = None) -> list[dict]:
    c, lock = _db()
    with lock:
        rows = [_goal(r) for r in c.execute(f"SELECT {_G} FROM goals").fetchall()]
    if done is not None:
        rows = [g for g in rows if g["done"] == done]
    return sorted(rows, key=lambda g: (g["done"], g["due"] or "9999", g["id"]) if not g["done"] else (True, "", -g["id"]))


def get_goal(goal_id: int) -> dict | None:
    return next((g for g in goals() if g["id"] == int(goal_id)), None)


def find_goal(ref: Any, done: bool | None = None) -> dict | None:
    return _find(goals(done), ref, "title")


def _number(value: Any, what: str) -> float | None:
    if value in (None, ""):
        return None
    try:
        n = float(str(value).replace(",", "")) if not isinstance(value, bool) else float("nan")
    except ValueError:
        n = float("nan")
    if not -1e9 <= n <= 1e9:                     # (also refuses nan)
        raise ValueError(f"{what} must be a number.")
    return n


def _steps(value: Any, old: list[dict]) -> list[dict]:
    """A list (or lines) of steps; ones already there keep their tick."""
    items = value if isinstance(value, list) else str(value).splitlines()
    out, was = [], {s["text"].casefold(): s["done"] for s in old}
    for i in items:
        text = _text(i.get("text") if isinstance(i, dict) else i, MAX_TITLE, "A step")
        if text:
            out.append({"text": text, "done": bool(i["done"]) if isinstance(i, dict) and "done" in i else was.get(text.casefold(), False)})
    if len(out) > MAX_STEPS:
        raise ValueError(f"Up to {MAX_STEPS} steps.")
    return out


def save_goal(title: Any = None, why: Any = None, area: Any = None, target: Any = None, unit: Any = None, due: Any = None, steps: Any = None,
              progress: Any = None, goal_id: int | None = None) -> dict:
    """Add a goal, or change the given fields of one (None = leave; '' = clear)."""
    old = get_goal(goal_id) if goal_id is not None else None
    if goal_id is not None and not old:
        raise ValueError("That goal is gone.")
    o = old or {"title": "", "why": "", "area": "", "target": None, "unit": "", "due": None, "steps": [], "progress": 0.0}
    tgt = o["target"] if target is None else _number(target, "The target")
    if tgt is not None and tgt <= 0:
        raise ValueError("The target must be more than 0.")
    prog = o["progress"] if progress is None else (_number(progress, "The progress") or 0.0)
    row = (_text(o["title"] if title is None else title, MAX_TITLE, "The goal", True), _text(o["why"] if why is None else why, MAX_NOTES, "The reason"),
           _one_spelling("goals", "area", _text(o["area"] if area is None else area, 40, "The area")), tgt, prog,
           _text(o["unit"] if unit is None else unit, 20, "The unit"), o["due"] if due is None else (parse_day(due).isoformat() if str(due).strip() else None),
           json.dumps(o["steps"] if steps is None else _steps(steps, o["steps"]), ensure_ascii=False))
    c, lock = _db()
    with lock, c:
        if old:
            c.execute("UPDATE goals SET title = ?, why = ?, area = ?, target = ?, progress = ?, unit = ?, due = ?, steps = ? WHERE id = ?", (*row, goal_id))
        else:
            if c.execute("SELECT COUNT(*) FROM goals").fetchone()[0] >= MAX_GOALS:
                raise ValueError("There are too many goals; delete some old ones first.")
            goal_id = c.execute("INSERT INTO goals(title, why, area, target, progress, unit, due, steps, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                (*row, _now())).lastrowid
    return get_goal(goal_id)


def goal_step(goal_id: int, number: Any, done: bool = True) -> dict:
    g = get_goal(goal_id)
    if not g:
        raise ValueError("That goal is gone.")
    if not g["steps"]:
        raise ValueError("That goal has no steps.")
    n = _whole(number, 1, len(g["steps"]), "The step")
    g["steps"][n - 1]["done"] = bool(done)
    return save_goal(steps=g["steps"], goal_id=goal_id)


def goal_done(goal_id: int, done: bool = True) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("UPDATE goals SET done = ?, done_at = ? WHERE id = ?", (int(bool(done)), _now() if done else None, int(goal_id))).rowcount)


def goal_delete(goal_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("DELETE FROM goals WHERE id = ?", (int(goal_id),)).rowcount)


def _n(x: float) -> str:
    return f"{x:,.2f}".rstrip("0").rstrip(".")


def describe_goal(g: dict) -> str:
    part = f"{_n(g['progress'])} of {_n(g['target'])}{' ' + g['unit'] if g['unit'] else ''}, " if g["target"] else ""
    steps = "; steps: " + ", ".join(f"{i}. {s['text']}{' (done)' if s['done'] else ''}" for i, s in enumerate(g["steps"], 1)) if g["steps"] else ""
    return f"#{g['id']} {g['title']}: {part}{g['percent']}%" + (f", by {say_when(g['due'])}" if g["due"] else "") + (" (reached)" if g["done"] else "") + steps


# ---------------- habits ----------------
def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def streak(days: set[str], per_week: int, today: date) -> tuple[int, int]:
    """(now, best). Every day: days in a row, today not counted against you yet. Else: weeks in a row (Mon-Sun) with enough days."""
    if not days:
        return 0, 0
    if per_week >= 7:
        have = sorted(date.fromisoformat(d) for d in days)
        step = timedelta(days=1)
        last = today if today.isoformat() in days else today - step
    else:
        count: dict[date, int] = {}
        for d in days:
            w = _monday(date.fromisoformat(d))
            count[w] = count.get(w, 0) + 1
        have = sorted(w for w, n in count.items() if n >= per_week)
        step = timedelta(days=7)
        last = _monday(today) if _monday(today) in have else _monday(today) - step
    best = run = 0
    prev = None
    for d in have:
        run = run + 1 if prev is not None and d - prev == step else 1
        best, prev = max(best, run), d
    now, every = 0, set(have)
    while last in every:
        now, last = now + 1, last - step
    return now, best


def habits(today: date | None = None, shown: int = 14) -> list[dict]:
    today = today or date.today()
    c, lock = _db()
    with lock:
        rows = c.execute("SELECT id, name, per_week, remind, created FROM habits ORDER BY id").fetchall()
        logs: dict[int, set[str]] = {}
        for h, d in c.execute("SELECT habit, day FROM habit_log").fetchall():
            logs.setdefault(h, set()).add(d)
    out = []
    for i, name, per_week, remind, created in rows:
        days = {d for d in logs.get(i, set()) if d <= today.isoformat()}
        now, best = streak(days, per_week, today)
        week = [(_monday(today) + timedelta(days=n)).isoformat() for n in range(7)]
        out.append({"id": i, "name": name, "per_week": per_week, "remind": remind, "created": created, "today": today.isoformat() in days,
                    "week": sum(d in days for d in week), "streak": now, "best": best, "unit": "days" if per_week >= 7 else "weeks", "total": len(days),
                    "days": [{"day": (d := (today - timedelta(days=n)).isoformat()), "on": d in days} for n in range(shown - 1, -1, -1)]})
    return out


def find_habit(ref: Any) -> dict | None:
    return _find(habits(), ref, "name")


def save_habit(name: Any = None, per_week: Any = None, remind: Any = None, habit_id: int | None = None) -> dict:
    old = next((h for h in habits() if h["id"] == habit_id), None) if habit_id is not None else None
    if habit_id is not None and not old:
        raise ValueError("That habit is gone.")
    name = _text(old["name"] if old and name is None else name, 60, "The habit", True)
    per = _whole(per_week, 1, 7, "Times a week") if per_week not in (None, "") else (old["per_week"] if old else 7)
    rem = (old["remind"] if old else "") if remind is None else (parse_clock(remind) if str(remind).strip() else "")
    c, lock = _db()
    with lock, c:
        if any(h["name"].casefold() == name.casefold() and h["id"] != habit_id for h in habits()):
            raise ValueError("You already have that habit.")
        if old:
            c.execute("UPDATE habits SET name = ?, per_week = ?, remind = ? WHERE id = ?", (name, per, rem, habit_id))
        else:
            if c.execute("SELECT COUNT(*) FROM habits").fetchone()[0] >= MAX_HABITS:
                raise ValueError(f"Up to {MAX_HABITS} habits.")
            habit_id = c.execute("INSERT INTO habits(name, per_week, remind, created) VALUES (?, ?, ?, ?)", (name, per, rem, _now())).lastrowid
    return next(h for h in habits() if h["id"] == habit_id)


def habit_mark(habit_id: int, day: Any = "", on: bool = True) -> dict:
    d = _past_day(day, "The day")
    c, lock = _db()
    with lock, c:
        if not c.execute("SELECT 1 FROM habits WHERE id = ?", (int(habit_id),)).fetchone():
            raise ValueError("That habit is gone.")
        if on:
            c.execute("INSERT OR IGNORE INTO habit_log(habit, day) VALUES (?, ?)", (int(habit_id), d))
        else:
            c.execute("DELETE FROM habit_log WHERE habit = ? AND day = ?", (int(habit_id), d))
    return next(h for h in habits() if h["id"] == int(habit_id))


def habit_delete(habit_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        c.execute("DELETE FROM habit_log WHERE habit = ?", (int(habit_id),))
        return bool(c.execute("DELETE FROM habits WHERE id = ?", (int(habit_id),)).rowcount)


def describe_habit(h: dict) -> str:
    how = "every day" if h["per_week"] == 7 else f"{h['per_week']} times a week"
    return (f"#{h['id']} {h['name']} ({how}): " + ("done today" if h["today"] else "not yet today") + f", {h['week']} this week, "
            f"streak {h['streak']} {h['unit'] if h['streak'] != 1 else h['unit'][:-1]} (best {h['best']})")


# ---------------- journal ----------------
def mood_of(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    s = " ".join(str(value).strip().lower().split())
    return _MOOD_WORDS[s] if s in _MOOD_WORDS else _whole(value, 1, 5, "The mood")


def _entry(r) -> dict:
    return {"id": r[0], "day": r[1], "mood": r[2], "text": r[3], "created": r[4]}


def entries(query: str = "", first: str = "", last: str = "", limit: int = 200) -> list[dict]:
    """Newest first."""
    c, lock = _db()
    with lock:
        rows = [_entry(r) for r in c.execute("SELECT id, day, mood, text, created FROM journal WHERE day >= ? AND day <= ? ORDER BY day DESC, id DESC",
                                             (first or "0000", last or "9999")).fetchall()]
    words = str(query or "").casefold().split()
    return [e for e in rows if all(w in e["text"].casefold() or w == MOODS.get(e["mood"]) for w in words)][:limit]


def save_entry(text: Any = None, mood: Any = None, day: Any = None, entry_id: int | None = None) -> dict:
    c, lock = _db()
    with lock:
        r = c.execute("SELECT id, day, mood, text, created FROM journal WHERE id = ?", (entry_id,)).fetchone() if entry_id is not None else None
    old = _entry(r) if r else None
    if entry_id is not None and not old:
        raise ValueError("That entry is gone.")
    body = _text(old["text"] if old and text is None else text, MAX_ENTRY, "The entry")
    m = old["mood"] if old and mood is None else mood_of(mood)
    if not body and m is None:
        raise ValueError("Write something or choose a mood.")
    d = old["day"] if old and day in (None, "") else _past_day(day, "The day")
    with lock, c:
        if old:
            c.execute("UPDATE journal SET day = ?, mood = ?, text = ? WHERE id = ?", (d, m, body, entry_id))
        else:
            if c.execute("SELECT COUNT(*) FROM journal").fetchone()[0] >= MAX_ENTRIES:
                raise ValueError("The journal is full.")
            entry_id = c.execute("INSERT INTO journal(day, mood, text, created) VALUES (?, ?, ?, ?)", (d, m, body, _now())).lastrowid
        return _entry(c.execute("SELECT id, day, mood, text, created FROM journal WHERE id = ?", (entry_id,)).fetchone())


def entry_delete(entry_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("DELETE FROM journal WHERE id = ?", (int(entry_id),)).rowcount)


def moods(today: date | None = None, days: int = 30) -> dict:
    """The average mood of each of the last days (None = none written), and the average of them all."""
    today = today or date.today()
    c, lock = _db()
    with lock:
        rows = dict(c.execute("SELECT day, AVG(mood) FROM journal WHERE mood IS NOT NULL AND day >= ? AND day <= ? GROUP BY day",
                              ((today - timedelta(days=days - 1)).isoformat(), today.isoformat())).fetchall())
    out = [{"day": (d := (today - timedelta(days=n)).isoformat()), "mood": round(rows[d], 1) if d in rows else None} for n in range(days - 1, -1, -1)]
    return {"days": out, "average": round(sum(rows.values()) / len(rows), 1) if rows else None, "written": len(rows)}


# ---------------- money ----------------
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬", "01234567890123456789.,")
_TIMES = {"k": 1000, "thousand": 1000, "hazar": 1000, "hazaar": 1000, "ہزار": 1000, "lakh": 100_000, "lac": 100_000, "لاکھ": 100_000,
          "million": 10**6, "m": 10**6, "crore": 10**7, "کروڑ": 10**7}


def amount(value: Any) -> int:
    """1500, "1,500.50", "Rs 1.5k", "2 lakh" -> hundredths."""
    s = "" if isinstance(value, bool) or value is None else str(value).strip().lower().translate(_DIGITS)
    m = re.fullmatch(r"(?:rs\.?|pkr|usd|inr|eur|gbp|aed|sar|[$€£¥₹₨])?\s*(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)\s*"
                     rf"({'|'.join(_TIMES)})?\s*(?:rs\.?|pkr|usd|rupees?|rupay|روپے|dollars?|/-)?", s)
    try:
        n = Decimal(m.group(1).replace(",", "")) * _TIMES.get(m.group(2), 1) * 100 if m else Decimal(0)
    except InvalidOperation:
        n = Decimal(0)
    whole = int(n.to_integral_value(rounding="ROUND_HALF_UP")) if n else 0
    if not m or whole < 1:
        raise ValueError(f"I don't understand the amount {str(value)!r}. Use a number like 1500 or 1,500.50.")
    if whole > MAX_AMOUNT:
        raise ValueError("That amount is too big.")
    return whole


def show(n: int, sign: str | None = None) -> str:
    sign = sign or settings()["currency"]
    s = f"{abs(n) // 100:,}" + (f".{abs(n) % 100:02d}" if n % 100 else "")
    return f"{'-' if n < 0 else ''}{sign}{'' if len(sign) == 1 else ' '}{s}"


def month_of(value: Any = "", today: date | None = None) -> str:
    today = today or date.today()
    s = str(value or "").strip().lower()
    if s in ("", "this month", "this", "now"):
        return today.isoformat()[:7]
    if s in ("last month", "last", "pichle mahine"):
        return (today.replace(day=1) - timedelta(days=1)).isoformat()[:7]
    m = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-\d\d)?", s)
    if m and 1 <= int(m.group(2)) <= 12 and 1970 <= int(m.group(1)) <= 9998:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    for fmt in ("%B %Y", "%b %Y", "%B", "%b"):
        try:
            d = datetime.strptime(s if "%Y" in fmt else f"{s} {today.year}", fmt if "%Y" in fmt else fmt + " %Y")
            if "%Y" not in fmt and d.date() > today:
                d = d.replace(year=d.year - 1)          # "december" in November: last year's
            return d.strftime("%Y-%m")
        except ValueError:
            pass
    raise ValueError(f"I don't understand the month {str(value)!r}. Use e.g. 2026-11, november or last month.")


def month_add(month: str, n: int) -> str:
    y, m = map(int, month.split("-"))
    i = y * 12 + m - 1 + n
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


_M = "id, day, kind, amount, category, note, bill, bill_month"


def _row(r) -> dict:
    return {"id": r[0], "day": r[1], "kind": r[2], "amount": r[3], "category": r[4], "note": r[5], "bill": r[6], "bill_month": r[7]}


def get_money(entry_id: int) -> dict | None:
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_M} FROM money WHERE id = ?", (int(entry_id),)).fetchone()
    return _row(r) if r else None


def list_money(month: str = "", query: str = "", limit: int = 500) -> list[dict]:
    c, lock = _db()
    with lock:
        rows = [_row(r) for r in c.execute(f"SELECT {_M} FROM money WHERE day LIKE ? ORDER BY day DESC, id DESC", (f"{month}%",)).fetchall()]
    words = str(query or "").casefold().split()
    return [r for r in rows if all(w in f"{r['category']} {r['note']}".casefold() for w in words)][:limit]


def save_money(value: Any = None, kind: Any = None, category: Any = None, note: Any = None, day: Any = None, entry_id: int | None = None) -> dict:
    old = get_money(entry_id) if entry_id is not None else None
    if entry_id is not None and not old:
        raise ValueError("That entry is gone.")
    k = str(kind or (old["kind"] if old else "out")).lower()
    k = {"spent": "out", "expense": "out", "income": "in", "got": "in"}.get(k, k)
    if k not in ("in", "out"):
        raise ValueError("Is it money in or money out?")
    n = old["amount"] if old and value in (None, "") else amount(value)
    cat = _one_spelling("money", "category", _text(old["category"] if old and category is None else category, 40, "The category")) or ("Income" if k == "in" else "Other")
    row = (old["day"] if old and day in (None, "") else _past_day(day, "The day"), k, n, cat, _text(old["note"] if old and note is None else note, 200, "The note"))
    c, lock = _db()
    with lock, c:
        if old:
            c.execute("UPDATE money SET day = ?, kind = ?, amount = ?, category = ?, note = ? WHERE id = ?", (*row, entry_id))
        else:
            if c.execute("SELECT COUNT(*) FROM money").fetchone()[0] >= MAX_MONEY:
                raise ValueError("There are too many entries.")
            entry_id = c.execute("INSERT INTO money(day, kind, amount, category, note, created) VALUES (?, ?, ?, ?, ?, ?)", (*row, _now())).lastrowid
    return get_money(entry_id)


def just_added(value: Any, kind: str, category: str, note: str, day: Any, seconds: int = 90) -> dict | None:
    """The same entry from a moment ago (the AI sometimes asks for a thing twice)."""
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_M} FROM money WHERE created >= ? AND amount = ? AND kind = ? AND day = ? AND category = ? COLLATE NOCASE AND note = ? COLLATE NOCASE",
                      ((datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds"), amount(value), kind, _past_day(day, "The day"),
                       " ".join(str(category or "").split()) or ("Income" if kind == "in" else "Other"), " ".join(str(note or "").split()))).fetchone()
    return _row(r) if r else None


def money_delete(entry_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("DELETE FROM money WHERE id = ?", (int(entry_id),)).rowcount)


def set_budget(category: Any, value: Any) -> None:
    cat = _text(category, 40, "The category", True)
    cat = _one_spelling("money", "category", cat)
    c, lock = _db()
    if value in (None, "", 0, "0"):
        with lock, c:
            c.execute("DELETE FROM budgets WHERE category = ?", (cat,))
        return
    n = amount(value)
    with lock, c:
        c.execute("INSERT INTO budgets(category, amount) VALUES (?, ?) ON CONFLICT(category) DO UPDATE SET amount = excluded.amount", (cat, n))


def summary(month: str = "", months: int = 6) -> dict:
    month = month or month_of()
    c, lock = _db()
    with lock:
        sums = {(m, k): n for m, k, n in c.execute("SELECT substr(day, 1, 7), kind, SUM(amount) FROM money GROUP BY 1, 2").fetchall()}
        cats = c.execute("SELECT category, SUM(amount) FROM money WHERE kind = 'out' AND day LIKE ? GROUP BY category COLLATE NOCASE ORDER BY 2 DESC", (f"{month}%",)).fetchall()
        budgets = dict(c.execute("SELECT category, amount FROM budgets").fetchall())
        names = [r[0] for r in c.execute("SELECT category FROM money GROUP BY category COLLATE NOCASE ORDER BY COUNT(*) DESC LIMIT 60").fetchall()]
    low = {k.casefold(): v for k, v in budgets.items()}
    rows = [{"category": k, "spent": n, "budget": low.pop(k.casefold(), None)} for k, n in cats]
    rows += [{"category": k, "spent": 0, "budget": v} for k, v in budgets.items() if k.casefold() in low]
    i, o = sums.get((month, "in"), 0), sums.get((month, "out"), 0)
    return {"month": month, "in": i, "out": o, "left": i - o, "categories": rows, "names": names, "budget": sum(budgets.values()),
            "trend": [{"month": m, "in": sums.get((m, "in"), 0), "out": sums.get((m, "out"), 0)} for m in (month_add(month, n) for n in range(1 - months, 1))]}


def describe_summary(s: dict) -> str:
    sign = settings()["currency"]
    out = [f"{s['month']}: money in {show(s['in'], sign)}, out {show(s['out'], sign)}, left {show(s['left'], sign)}."]
    for r in s["categories"][:15]:
        over = f" of a budget of {show(r['budget'], sign)}" + (", over by " + show(r["spent"] - r["budget"], sign) if r["spent"] > r["budget"] else "") if r["budget"] else ""
        out.append(f"- {r['category']}: {show(r['spent'], sign)}{over}")
    return "\n".join(out)


def describe_money(r: dict) -> str:
    return f"#{r['id']} {r['day']} {'+' if r['kind'] == 'in' else '-'}{show(r['amount'])} {r['category']}" + (f" ({r['note']})" if r["note"] else "")


# ---------------- bills ----------------
def due_day(month: str, day: int) -> date:
    """The 31st in a shorter month is its last day."""
    y, m = map(int, month.split("-"))
    last = (date(y + m // 12, m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(day, last))


def bills(today: date | None = None) -> list[dict]:
    """Each bill with the first month not paid yet (older ones first)."""
    today = today or date.today()
    c, lock = _db()
    with lock:
        rows = c.execute("SELECT id, name, amount, category, due, remind, start FROM bills").fetchall()
        paid: dict[int, set[str]] = {}
        for b, m in c.execute("SELECT bill, bill_month FROM money WHERE bill IS NOT NULL").fetchall():
            paid.setdefault(b, set()).add(m)
    out = []
    for i, name, n, cat, due, remind, start in rows:
        month = start
        while month in paid.get(i, set()):
            month = month_add(month, 1)
        d = due_day(month, due)
        out.append({"id": i, "name": name, "amount": n, "category": cat, "day": due, "remind": remind, "month": month, "due": d.isoformat(),
                    "days": (d - today).days})
    return sorted(out, key=lambda b: (b["due"], b["id"]))


def find_bill(ref: Any) -> dict | None:
    return _find(bills(), ref, "name")


def save_bill(name: Any = None, value: Any = None, category: Any = None, day: Any = None, remind: Any = None, bill_id: int | None = None) -> dict:
    old = next((b for b in bills() if b["id"] == bill_id), None) if bill_id is not None else None
    if bill_id is not None and not old:
        raise ValueError("That bill is gone.")
    nm = _text(old["name"] if old and name is None else name, 60, "The bill's name", True)
    n = old["amount"] if old and value in (None, "") else amount(value)
    cat = _one_spelling("money", "category", _text(old["category"] if old and category is None else category, 40, "The category")) or "Bills"
    d = old["day"] if old and day in (None, "") else _whole(day, 1, 31, "The day of the month")
    rem = _whole(remind, 0, 14, "Remind days before") if remind not in (None, "") else (old["remind"] if old else 2)
    c, lock = _db()
    with lock, c:
        if any(b["name"].casefold() == nm.casefold() and b["id"] != bill_id for b in bills()):
            raise ValueError("You already have a bill with that name.")
        if old:
            c.execute("UPDATE bills SET name = ?, amount = ?, category = ?, due = ?, remind = ? WHERE id = ?", (nm, n, cat, d, rem, bill_id))
        else:
            if c.execute("SELECT COUNT(*) FROM bills").fetchone()[0] >= MAX_BILLS:
                raise ValueError(f"Up to {MAX_BILLS} bills.")
            today, this = date.today(), month_of()
            start = this if due_day(this, d) >= today else month_add(this, 1)      # made after its day: from next month
            bill_id = c.execute("INSERT INTO bills(name, amount, category, due, remind, start, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (nm, n, cat, d, rem, start, _now())).lastrowid
    return next(b for b in bills() if b["id"] == bill_id)


def bill_paid(bill_id: int, value: Any = None, day: Any = None) -> dict:
    """You paid it (the app pays nothing): writes the money out and moves on to the next month."""
    b = next((b for b in bills() if b["id"] == int(bill_id)), None)
    if not b:
        raise ValueError("That bill is gone.")
    if b["days"] > 45:
        raise ValueError(f"{b['name']} is already written as paid until {say_when(b['due'])}.")
    row = save_money(show(b["amount"], "Rs") if value in (None, "") else value, "out", b["category"], b["name"], day)
    c, lock = _db()
    with lock, c:
        c.execute("UPDATE money SET bill = ?, bill_month = ? WHERE id = ?", (b["id"], b["month"], row["id"]))
    return get_money(row["id"])


def bill_skip(bill_id: int) -> dict:
    b = next((b for b in bills() if b["id"] == int(bill_id)), None)
    if not b:
        raise ValueError("That bill is gone.")
    c, lock = _db()
    with lock, c:
        c.execute("UPDATE bills SET start = ? WHERE id = ?", (month_add(b["month"], 1), b["id"]))
    return next(x for x in bills() if x["id"] == b["id"])


def bill_delete(bill_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        c.execute("UPDATE money SET bill = NULL, bill_month = NULL WHERE bill = ?", (int(bill_id),))        # what was paid stays
        return bool(c.execute("DELETE FROM bills WHERE id = ?", (int(bill_id),)).rowcount)


def describe_bill(b: dict) -> str:
    when = "overdue since " + say_when(b["due"]) if b["days"] < 0 else "due " + say_when(b["due"])
    return f"#{b['id']} {b['name']}: {show(b['amount'])}, {when}"


# ---------------- files ----------------
def _safe_cell(text: str) -> str:
    """Excel would run a cell that starts like a formula."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export(what: str, folder: Path | None = None) -> Path:
    """Money as CSV, or the journal as text, in your Documents folder. Never over an existing file."""
    folder = folder or Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    folder.mkdir(parents=True, exist_ok=True)
    if what == "money":
        rows = [["Day", "In or out", "Amount", "Category", "Note"]] + [
            [r["day"], r["kind"], f"{r['amount'] // 100}.{r['amount'] % 100:02d}", _safe_cell(r["category"]), _safe_cell(r["note"])]
            for r in reversed(list_money(limit=MAX_MONEY))]
        name, ext = "My money", ".csv"
    elif what == "journal":
        items = reversed(entries(limit=MAX_ENTRIES))
        text = "\n\n".join(e["day"] + (f" ({MOODS[e['mood']]})" if e["mood"] else "") + "\n" + e["text"] for e in items)
        name, ext = "My journal", ".txt"
    else:
        raise ValueError("Export money or the journal.")
    stem = f"{name} {date.today().isoformat()}"
    for n in range(1, 100):
        p = folder / f"{stem}{f' ({n})' if n > 1 else ''}{ext}"
        try:
            with open(p, "x", encoding="utf-8-sig", newline="" if ext == ".csv" else None) as f:
                if ext == ".csv":
                    csv.writer(f).writerows(rows)
                else:
                    f.write(text + "\n")
            return p
        except FileExistsError:
            continue
    raise ValueError("There are too many exports of today in Documents.")


# ---------------- reminders ----------------
def tick(now: datetime, notify: Callable[[str, str], None]) -> int:
    """Called every few seconds: habits and the journal at their time, bills in the morning. Each once."""
    from . import schedule
    sent, today = 0, now.date().isoformat()
    c, lock = _db()

    def at(clock: str) -> bool:
        t = datetime.combine(now.date(), datetime.strptime(clock, "%H:%M").time())
        return timedelta(0) <= now - t <= planner.CATCH_UP
    with lock:
        marks = dict(c.execute("SELECT id, reminded FROM habits").fetchall())
        said = dict(c.execute("SELECT id, reminded FROM bills").fetchall())
    for h in habits(now.date()) if marks else []:
        if h["remind"] and at(h["remind"]) and not h["today"] and marks.get(h["id"]) != today and (h["per_week"] == 7 or h["week"] < h["per_week"]):
            with lock, c:
                c.execute("UPDATE habits SET reminded = ? WHERE id = ?", (today, h["id"]))
            notify(f"Reminder: {h['name']}." + (f" Your streak is {h['streak']} {h['unit']}." if h["streak"] > 1 else ""), "reminder")
            sent += 1
    t = settings()["journal_remind"]
    if t and at(t) and schedule.get_setting("journal_reminded") != today:
        schedule.set_setting("journal_reminded", today)
        if not entries(first=today, last=today, limit=1):
            notify("Reminder: how was your day? Write a few lines in your journal.", "reminder")
            sent += 1
    if now.hour >= 9:
        for b in bills(now.date()) if said else []:
            stage = "due" if b["days"] <= 0 else "soon" if b["days"] <= b["remind"] else ""
            key = f"{b['month']}:{stage}"
            if stage and b["days"] >= -7 and said.get(b["id"]) != key:
                with lock, c:
                    c.execute("UPDATE bills SET reminded = ? WHERE id = ?", (key, b["id"]))
                when = "is due today" if b["days"] == 0 else f"was due {say_when(b['due'], now.date())}" if b["days"] < 0 else f"is due {say_when(b['due'], now.date())}"
                notify(f"Reminder: {b['name']} ({show(b['amount'])}) {when}.", "reminder")
                sent += 1
    return sent

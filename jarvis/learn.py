"""Learning (Phase 8): decks of flashcards that come back just before you would forget them.

Everything is in the local database (decks, cards, reviews); nothing goes online. The timing is the well-known SM-2 idea:
each card has an ease and an interval; a card you knew comes back after a longer time, one you didn't comes back today.
"""
from __future__ import annotations

import csv
import io
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from .planner import CATCH_UP, _db, _now, parse_clock

MAX_DECKS, MAX_CARDS, MAX_SIDE, MAX_NAME = 200, 20_000, 1000, 60
MAX_IMPORT = 2_000_000
NEW_A_DAY = (0, 200, 15)                     # least, most, usual
GRADES = {1: "again", 2: "hard", 3: "good", 4: "easy"}
_WORDS = {"again": 1, "wrong": 1, "no": 1, "forgot": 1, "hard": 2, "almost": 2, "good": 3, "right": 3, "yes": 3, "correct": 3, "easy": 4}
LEARNING = 10 * 60                           # seconds until a card you didn't know comes again
MAX_DAYS = 3650


# ---------------- small things ----------------
def _side(value: Any, what: str) -> str:
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    if not s:
        raise ValueError(f"{what} is missing.")
    if len(s) > MAX_SIDE:
        raise ValueError(f"{what} is too long (up to {MAX_SIDE} characters).")
    return s


def grade_of(value: Any) -> int:
    s = str(value if value is not None else "").strip().lower()
    g = int(s) if s in ("1", "2", "3", "4") else _WORDS.get(s, 0)
    if not g:
        raise ValueError("How well did it go? again, hard, good or easy (1 to 4).")
    return g


def new_a_day() -> int:
    from . import schedule
    n = schedule.get_setting("learn_new", NEW_A_DAY[2])
    return n if isinstance(n, int) and not isinstance(n, bool) and NEW_A_DAY[0] <= n <= NEW_A_DAY[1] else NEW_A_DAY[2]


def settings() -> dict:
    from . import schedule
    return {"new": new_a_day(), "remind": schedule.get_setting("learn_remind") or ""}


def save_settings(d: dict) -> None:
    from . import schedule
    if "new" in d:
        try:
            n = int(str(d["new"]).strip())
        except ValueError:
            n = -1
        if not NEW_A_DAY[0] <= n <= NEW_A_DAY[1]:
            raise ValueError(f"New cards a day: {NEW_A_DAY[0]} to {NEW_A_DAY[1]}.")
        schedule.set_setting("learn_new", n)
    if "remind" in d:
        t = str(d["remind"] or "").strip()
        schedule.set_setting("learn_remind", parse_clock(t) if t else None)


# ---------------- decks ----------------
def _deck_rows() -> list[tuple]:
    c, lock = _db()
    with lock:
        return c.execute("SELECT id, name FROM decks ORDER BY name COLLATE NOCASE").fetchall()


def decks(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    c, lock = _db()
    with lock:
        counts = {r[0]: r[1:] for r in c.execute(
            "SELECT deck, count(*), sum(due IS NULL), sum(due IS NOT NULL AND due <= ?), sum(days >= 21) FROM cards GROUP BY deck", (now.isoformat(timespec="seconds"),)).fetchall()}
    left = _new_left(now)
    out = []
    for did, name in _deck_rows():
        total, new, due, known = (x or 0 for x in counts.get(did, (0, 0, 0, 0)))
        out.append({"id": did, "name": name, "cards": total, "new": new, "due": due, "known": known, "today": due + min(new, left.get(did, new_a_day()))})
    return out


def find_deck(ref: Any) -> dict | None:
    """By number, whole name, or words that fit only one."""
    rows, s = decks(), str(ref if ref is not None else "").strip()
    if s.lstrip("#").isdigit() and any(d["id"] == int(s.lstrip("#")) for d in rows):
        return next(d for d in rows if d["id"] == int(s.lstrip("#")))
    low = s.casefold()
    for hits in ([d for d in rows if d["name"].casefold() == low], [d for d in rows if low and all(w in d["name"].casefold() for w in low.split())]):
        if len(hits) == 1:
            return hits[0]
    return None


def save_deck(name: Any, deck_id: int | None = None) -> dict:
    n = " ".join(str(name or "").split())
    if not n or len(n) > MAX_NAME:
        raise ValueError(f"Give the deck a name (up to {MAX_NAME} characters).")
    rows = _deck_rows()
    if any(r[1].casefold() == n.casefold() and r[0] != deck_id for r in rows):
        raise ValueError(f"There is already a deck called {n}.")
    if deck_id is None and len(rows) >= MAX_DECKS:
        raise ValueError(f"That's {MAX_DECKS} decks. Remove one first.")
    c, lock = _db()
    with lock, c:
        if deck_id is None:
            deck_id = c.execute("INSERT INTO decks (name, created) VALUES (?, ?)", (n, _now())).lastrowid
        elif not c.execute("UPDATE decks SET name = ? WHERE id = ?", (n, deck_id)).rowcount:
            raise ValueError("That deck is gone.")
    return next(d for d in decks() if d["id"] == deck_id)


def delete_deck(deck_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        c.execute("DELETE FROM cards WHERE deck = ?", (int(deck_id),))
        return c.execute("DELETE FROM decks WHERE id = ?", (int(deck_id),)).rowcount > 0


def deck_for(name: Any) -> dict:
    """The deck of that name, made if it isn't there."""
    return find_deck(name) or save_deck(name)


# ---------------- cards ----------------
_C = "id, deck, front, back, due, days, ease, reps, lapses"


def _card(r) -> dict:
    return dict(zip(("id", "deck", "front", "back", "due", "days", "ease", "reps", "lapses"), r))


def cards(deck_id: int | None = None, query: str = "", limit: int = 500) -> list[dict]:
    q, args = f"SELECT {_C} FROM cards", []
    where = []
    if deck_id is not None:
        where.append("deck = ?")
        args.append(int(deck_id))
    for w in str(query or "").split()[:8]:
        where.append("(front LIKE ? ESCAPE '\\' OR back LIKE ? ESCAPE '\\')")
        args += ["%" + re.sub(r"([\\%_])", r"\\\1", w) + "%"] * 2
    c, lock = _db()
    with lock:
        return [_card(r) for r in c.execute(q + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()]


def get_card(card_id: Any) -> dict | None:
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_C} FROM cards WHERE id = ?", (int(card_id),)).fetchone()
    return _card(r) if r else None


def add_cards(deck_id: int, pairs: list[tuple[Any, Any]]) -> tuple[int, int]:
    """(added, already there). All of them are checked first."""
    clean = [(_side(f, "The front"), _side(b, "The back")) for f, b in pairs]
    if not clean:
        raise ValueError("There are no cards in that.")
    c, lock = _db()
    with lock, c:
        if not c.execute("SELECT 1 FROM decks WHERE id = ?", (deck_id,)).fetchone():
            raise ValueError("That deck is gone.")
        if c.execute("SELECT count(*) FROM cards").fetchone()[0] + len(clean) > MAX_CARDS:
            raise ValueError(f"That's more than {MAX_CARDS} cards.")
        have = {f.casefold() for f, in c.execute("SELECT front FROM cards WHERE deck = ?", (deck_id,)).fetchall()}
        n = 0
        for f, b in clean:
            if f.casefold() in have:
                continue
            have.add(f.casefold())
            c.execute("INSERT INTO cards (deck, front, back, created) VALUES (?, ?, ?, ?)", (deck_id, f, b, _now()))
            n += 1
    return n, len(clean) - n


def update_card(card_id: int, front: Any, back: Any) -> dict:
    f, b = _side(front, "The front"), _side(back, "The back")
    c, lock = _db()
    with lock, c:
        if not c.execute("UPDATE cards SET front = ?, back = ? WHERE id = ?", (f, b, int(card_id))).rowcount:
            raise ValueError("That card is gone.")
    return get_card(card_id)


def delete_card(card_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM cards WHERE id = ?", (int(card_id),)).rowcount > 0


# ---------------- what is next ----------------
def _new_left(now: datetime) -> dict[int, int]:
    """New cards each deck may still show today."""
    c, lock = _db()
    with lock:
        seen = dict(c.execute("SELECT deck, count(*) FROM reviews WHERE day = ? AND was_new = 1 GROUP BY deck", (now.date().isoformat(),)).fetchall())
    return {did: max(0, new_a_day() - seen.get(did, 0)) for did, _ in _deck_rows()}


def due(deck_id: int | None = None, now: datetime | None = None, limit: int = 200) -> list[dict]:
    """Cards to look at now: what is due first (longest waiting first), then new ones (up to the day's number)."""
    now = now or datetime.now()
    at = now.isoformat(timespec="seconds")
    c, lock = _db()
    args = [] if deck_id is None else [int(deck_id)]
    only = "" if deck_id is None else " AND deck = ?"
    with lock:
        old = [_card(r) for r in c.execute(f"SELECT {_C} FROM cards WHERE due IS NOT NULL AND due <= ?{only} ORDER BY due LIMIT ?", (at, *args, limit)).fetchall()]
        fresh = [_card(r) for r in c.execute(f"SELECT {_C} FROM cards WHERE due IS NULL{only} ORDER BY id LIMIT ?", (*args, 5000)).fetchall()]
    left, new = _new_left(now), []
    for x in fresh:
        if left.get(x["deck"], 0) > 0:
            left[x["deck"]] -= 1
            new.append(x)
    return (old + new)[:limit]


def next_soon(deck_id: int | None = None, now: datetime | None = None) -> int | None:
    """Seconds until the next card you didn't know comes again (None: none today)."""
    now = now or datetime.now()
    c, lock = _db()
    with lock:
        r = c.execute("SELECT min(due) FROM cards WHERE due > ? AND days = 0" + ("" if deck_id is None else " AND deck = ?"),
                      (now.isoformat(timespec="seconds"), *([] if deck_id is None else [int(deck_id)]))).fetchone()[0]
    return max(1, int((datetime.fromisoformat(r) - now).total_seconds())) if r else None


def schedule_next(card: dict, grade: int) -> tuple[int, float]:
    """(days until it comes back, its new ease). 0 days: again today."""
    ease = max(1.3, min(3.0, card["ease"] + {1: -0.2, 2: -0.15, 3: 0.0, 4: 0.15}[grade]))
    if grade == 1:
        return 0, ease
    old = card["days"]
    if old == 0:                                        # new, or being learned again
        days = {2: 1, 3: 1, 4: 4}[grade]
    elif old == 1:
        days = {2: 2, 3: 3, 4: 6}[grade]
    else:
        days = max(old + 1, round(old * {2: 1.2, 3: ease, 4: ease * 1.3}[grade]))
    return min(MAX_DAYS, days), ease


def grade(card_id: Any, how: Any, now: datetime | None = None) -> dict:
    now, g = now or datetime.now(), grade_of(how)
    c, lock = _db()
    with lock, c:
        r = c.execute(f"SELECT {_C} FROM cards WHERE id = ?", (int(card_id),)).fetchone()
        if not r:
            raise ValueError("That card is gone.")
        card = _card(r)
        days, ease = schedule_next(card, g)
        # a card for another day comes back from the morning of that day, whatever the time now
        back = now + timedelta(seconds=LEARNING) if days == 0 else datetime.combine(now.date() + timedelta(days=days), datetime.min.time()).replace(hour=4)
        c.execute("UPDATE cards SET due = ?, days = ?, ease = ?, reps = reps + 1, lapses = lapses + ? WHERE id = ?",
                  (back.isoformat(timespec="seconds"), days, ease, int(g == 1 and card["days"] > 0), card["id"]))
        c.execute("INSERT INTO reviews (card, deck, day, grade, was_new) VALUES (?, ?, ?, ?, ?)",
                  (card["id"], card["deck"], now.date().isoformat(), g, int(card["due"] is None)))
    return {**get_card(card_id), "grade": GRADES[g], "back_in": "in 10 minutes" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"}


def undo(card: dict) -> None:
    """Put a card back as it was before its last answer (pressed the wrong button)."""
    c, lock = _db()
    with lock, c:
        r = c.execute("SELECT id FROM reviews WHERE card = ? ORDER BY id DESC LIMIT 1", (int(card["id"]),)).fetchone()
        if not r:
            raise ValueError("There is nothing to undo.")
        ok = (card.get("due") is None or isinstance(card["due"], str) and len(card["due"]) <= 25 and datetime.fromisoformat(card["due"])) is not False
        if not ok or not 0 <= int(card["days"]) <= MAX_DAYS or not 1.3 <= float(card["ease"]) <= 3.0:
            raise ValueError("That can't be undone.")
        c.execute("DELETE FROM reviews WHERE id = ?", r)
        c.execute("UPDATE cards SET due = ?, days = ?, ease = ?, reps = max(0, reps - 1) WHERE id = ?", (card["due"], int(card["days"]), float(card["ease"]), int(card["id"])))


# ---------------- how it goes ----------------
def stats(today: date | None = None, days: int = 30) -> dict:
    today = today or date.today()
    first = (today - timedelta(days=days - 1)).isoformat()
    c, lock = _db()
    with lock:
        by = {d: (n, ok) for d, n, ok in c.execute("SELECT day, count(*), sum(grade > 1) FROM reviews WHERE day >= ? GROUP BY day", (first,)).fetchall()}
        every = {d for d, in c.execute("SELECT DISTINCT day FROM reviews").fetchall()}
        ahead = dict(c.execute("SELECT substr(due, 1, 10), count(*) FROM cards WHERE due >= ? GROUP BY 1", ((today + timedelta(days=1)).isoformat(),)).fetchall())
    n, ok = sum(x[0] for x in by.values()), sum(x[1] for x in by.values())
    run, d = 0, today if today.isoformat() in every else today - timedelta(days=1)
    while d.isoformat() in every:
        run, d = run + 1, d - timedelta(days=1)
    return {"days": [{"day": x, "n": by.get(x, (0, 0))[0]} for x in ((today - timedelta(days=days - 1 - i)).isoformat() for i in range(days))],
            "today": by.get(today.isoformat(), (0, 0))[0], "right": round(100 * ok / n) if n else None, "streak": run,
            "ahead": [{"day": x, "n": ahead.get(x, 0)} for x in ((today + timedelta(days=i)).isoformat() for i in range(1, 8))]}


def describe_deck(d: dict) -> str:
    return f"{d['name']}: {d['cards']} card{'' if d['cards'] == 1 else 's'}, {d['today']} to look at today, {d['known']} known well"


# ---------------- in and out ----------------
def read_cards(text: Any) -> list[tuple[str, str]]:
    """Cards from pasted text: one a line, front and back split by a tab, ; | = or a comma (CSV with quotes works too). Anki's text export too."""
    t = str(text or "").lstrip("﻿").replace("\r\n", "\n")
    if len(t) > MAX_IMPORT:
        raise ValueError("That's too much text at once.")
    lines = [x for x in t.split("\n") if x.strip() and not re.match(r"#(separator|html|tags|columns|deck|notetype)", x)]
    if not lines:
        raise ValueError("There are no cards in that.")
    sep = max(("\t", ";", "|", " = ", ","), key=lambda s: (sum(s in x for x in lines), s == "\t"))
    if not any(sep in x for x in lines):
        raise ValueError("Put the front and the back on one line, split by a tab or a semicolon, e.g.  apple ; سیب")
    if sep == " = ":
        rows = [x.split(sep, 1) for x in lines]
    else:
        rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=sep))
    plain = lambda s: re.sub(r"</?[a-zA-Z][^<>]{0,200}>", "", re.sub(r"(?i)<br\s*/?>", "\n", s)).strip()           # noqa: E731
    out = [(plain(r[0]), plain(r[1])) for r in rows if len(r) >= 2 and plain(r[0]) and plain(r[1])]
    if not out:
        raise ValueError("There are no cards in that.")
    return out


def export(deck_id: int, folder: Path | None = None) -> Path:
    """The deck as CSV in your Documents folder. Never over an existing file."""
    d = next((x for x in decks() if x["id"] == int(deck_id)), None)
    if not d:
        raise ValueError("That deck is gone.")
    folder = folder or Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    folder.mkdir(parents=True, exist_ok=True)
    from .life import _safe_cell
    stem = "Cards " + (re.sub(r'[<>:"/\\|?*\x00-\x1f.]+', " ", d["name"]).strip() or "deck")
    stem = " ".join(stem.split())
    for n in range(1, 100):
        p = folder / f"{stem}{f' ({n})' if n > 1 else ''}.csv"
        try:
            with open(p, "x", encoding="utf-8-sig", newline="") as f:
                csv.writer(f).writerows([_safe_cell(c["front"]), _safe_cell(c["back"])] for c in reversed(cards(d["id"], limit=MAX_CARDS)))
            return p
        except FileExistsError:
            continue
    raise ValueError("There are too many exports of this deck in Documents.")


# ---------------- reminder ----------------
def tick(now: datetime, notify: Callable[[str, str], None]) -> int:
    from . import schedule
    t = settings()["remind"]
    if not t or schedule.get_setting("learn_reminded") == now.date().isoformat():
        return 0
    if not timedelta(0) <= now - datetime.combine(now.date(), datetime.strptime(t, "%H:%M").time()) <= CATCH_UP:
        return 0
    schedule.set_setting("learn_reminded", now.date().isoformat())
    n = sum(d["today"] for d in decks(now))
    if not n:
        return 0
    notify(f"Reminder: {n} card{'' if n == 1 else 's'} to look at today.", "reminder")
    return 1


def load(deck_id: int | None = None, query: str = "") -> dict:
    return {"decks": decks(), "stats": stats(), "settings": settings(), "cards": cards(deck_id, query, 200) if deck_id is not None else []}

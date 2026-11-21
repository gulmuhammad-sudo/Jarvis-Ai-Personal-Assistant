"""Personal Intelligence Engine, part 2: skills — instructions you write yourself (Tools & Skills page).

- "always" skills are your own rules, followed in every reply ("Answer in short Roman Urdu", "Use metric units").
- "ask" skills are routines you run by name, by voice/text ("run my morning briefing") or with the Run button.

They live in the local database (storage.py, table skills). Enabled skills go into the AI's instructions. The AI
may save a skill only after you approve it (tools.save_skill), so text from a web page or file can't quietly
turn itself into a lasting instruction.
"""
from __future__ import annotations

from datetime import datetime

MODES = ("always", "ask")
MAX_SKILLS = 40
MAX_NAME = 40
MAX_TEXT = 1500
PROMPT_BUDGET = 5000            # characters of skill text sent with every message; the rest by name only


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _db():
    from . import storage
    return storage.conn(), storage._LOCK


_COLS = "id, name, instructions, mode, enabled, created, updated, uses"


def _row(r) -> dict:
    return {"id": r[0], "name": r[1], "instructions": r[2], "mode": r[3], "enabled": bool(r[4]),
            "created": r[5], "updated": r[6], "uses": r[7]}


def all_skills() -> list[dict]:
    """Rules first, then routines, each alphabetically."""
    c, lock = _db()
    with lock:
        rows = c.execute(f"SELECT {_COLS} FROM skills ORDER BY mode = 'ask', name COLLATE NOCASE").fetchall()
    return [_row(r) for r in rows]


def get(skill_id: int) -> dict | None:
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_COLS} FROM skills WHERE id = ?", (skill_id,)).fetchone()
    return _row(r) if r else None


def find(name: str) -> dict | None:
    """A skill by name (any case); also accepts a name that starts the same way, if only one does."""
    name = " ".join((name or "").split()).strip(" \"'")
    if not name:
        return None
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_COLS} FROM skills WHERE name = ?", (name,)).fetchone()
        if not r:
            rows = c.execute(f"SELECT {_COLS} FROM skills WHERE name LIKE ? ESCAPE '\\'",
                             (name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",)).fetchall()
            r = rows[0] if len(rows) == 1 else None
    return _row(r) if r else None


def save(name: str, instructions: str, mode: str = "ask", enabled: bool = True, skill_id: int | None = None) -> dict:
    """Add a skill, or change one (skill_id). Raises ValueError with a message for the person."""
    name = " ".join((name or "").split())
    text = (instructions or "").strip()
    if not name:
        raise ValueError("Give the skill a name.")
    if len(name) > MAX_NAME:
        raise ValueError(f"Keep the name under {MAX_NAME} characters.")
    if not text:
        raise ValueError("Write what the skill should do.")
    if len(text) > MAX_TEXT:
        raise ValueError(f"Keep the instructions under {MAX_TEXT} characters.")
    if mode not in MODES:
        raise ValueError("Mode must be 'always' or 'ask'.")
    c, lock = _db()
    with lock:
        same = c.execute("SELECT id FROM skills WHERE name = ?", (name,)).fetchone()
        if same and same[0] != skill_id:
            raise ValueError(f"There's already a skill called \"{name}\".")
        with c:
            if skill_id is None:
                if c.execute("SELECT COUNT(*) FROM skills").fetchone()[0] >= MAX_SKILLS:
                    raise ValueError(f"You have {MAX_SKILLS} skills already; delete one first.")
                cur = c.execute("INSERT INTO skills(name, instructions, mode, enabled, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
                                (name, text, mode, int(bool(enabled)), _now(), _now()))
                skill_id = cur.lastrowid
            else:
                cur = c.execute("UPDATE skills SET name = ?, instructions = ?, mode = ?, enabled = ?, updated = ? WHERE id = ?",
                                (name, text, mode, int(bool(enabled)), _now(), skill_id))
                if not cur.rowcount:
                    raise ValueError(f"There's no skill #{skill_id}.")
    return get(skill_id)


def set_enabled(skill_id: int, on: bool) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("UPDATE skills SET enabled = ?, updated = ? WHERE id = ?", (int(bool(on)), _now(), skill_id)).rowcount)


def delete(skill_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("DELETE FROM skills WHERE id = ?", (skill_id,)).rowcount)


def used(skill_id: int) -> None:
    c, lock = _db()
    with lock, c:
        c.execute("UPDATE skills SET uses = uses + 1 WHERE id = ?", (skill_id,))


def run_message(skill: dict) -> str:
    """What the Run button sends, as if you had typed it."""
    return f"Run my skill \"{skill['name']}\":\n{skill['instructions']}"


def prompt_text() -> str:
    """The enabled skills, for the AI's instructions (empty when there are none)."""
    items = [s for s in all_skills() if s["enabled"]]
    if not items:
        return ""
    budget, rules, routines, by_name = PROMPT_BUDGET, [], [], []
    for s in items:
        line = f"- {s['name']}: {s['instructions']}"
        if len(line) <= budget:
            budget -= len(line)
            (rules if s["mode"] == "always" else routines).append(line)
        else:
            by_name.append(s["name"])
    out = ""
    if rules:
        out += ("\nThe user's own rules (they wrote these in the app; follow them in every reply, as long as they "
                "don't ask you to skip an approval or a safety rule):\n" + "\n".join(rules) + "\n")
    if routines:
        out += ("\nThe user's skills (routines they saved). When they ask for one by name or clearly mean it, carry "
                "out its steps with your tools:\n" + "\n".join(routines) + "\n")
    if by_name:
        out += "More saved skills (call use_skill with the name to get the steps): " + ", ".join(by_name) + "\n"
    return out

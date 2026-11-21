"""Personal Intelligence Engine, part 1: what the assistant knows about you.

- Profile: what you wrote about yourself (profile.json, edited on the Profile page).
- Memories: facts kept across sessions, in the local database (storage.py) with a category, an importance
  (1 normal, 2 important, 3 key) and where they came from. The old memory.json is imported once and kept as
  memory.json.imported.
- Suggestions: when you say something about yourself ("mera naam…", "I work at…"), suggest_from() proposes a
  memory; nothing is saved unless you press Save.
Everything stays on this PC; the profile and the most important memories go to the AI with your messages.
"""
from __future__ import annotations

import re
from datetime import datetime

from .config import DATA_DIR, DATA_LOCK, MEMORY_FILE, USER_NAME, read_json, write_json

PROFILE_FILE = DATA_DIR / "profile.json"
# (key, label shown to the AI) - the Profile page in the Command Center edits these
PROFILE_FIELDS = [
    ("name", "Full name"), ("call", "What Jarvis calls you"), ("birthday", "Birthday"), ("city", "City"),
    ("languages", "Languages"),
    ("about", "About me (family, study or work, interests, routine, goals)"),
    ("style", "How I like replies"),
]
# fields from the older, longer profile: folded into "About me"
_OLD_FIELDS = [("family", "Family"), ("work", "Study/work"), ("interests", "Interests"), ("favourites", "Favourites"),
               ("routine", "Routine"), ("goals", "Goals"), ("health", "Health")]

CATEGORIES = ("personal", "family", "people", "work", "study", "health", "preferences", "routine", "other")
PROMPT_LIMIT = 60                 # memories sent with every message (most important and newest first)


def profile() -> dict:
    data = read_json(PROFILE_FILE, {})
    if not isinstance(data, dict):
        return {k: "" for k, _ in PROFILE_FIELDS}
    out = {k: str(data.get(k, "") or "") for k, _ in PROFILE_FIELDS}
    old = [f"{label}: {data[k]}" for k, label in _OLD_FIELDS if str(data.get(k) or "").strip()]
    if old:
        out["about"] = "\n".join(old + ([out["about"]] if out["about"] else []))
    return out


def save_profile(data: dict) -> dict:
    clean = {k: str(data.get(k, "") or "").strip()[:1500] for k, _ in PROFILE_FIELDS}
    with DATA_LOCK:
        write_json(PROFILE_FILE, clean)
    return clean


def call_name() -> str:
    """What Jarvis calls the user: the profile's "Call me" field, else JARVIS_USER_NAME."""
    return profile().get("call") or USER_NAME


# ---------------- categories and importance (a first guess you can change) ----------------
_RULES = [
    ("family", r"\b(wife|husband|son|daughter|mother|mom|mum|father|dad|brother|sister|family|kids?|children|"
               r"biwi|bivi|shohar|beta|beti|ammi|abbu|ami|abu|bhai|behen|bahen|walid|walida|ghar wal)"),
    ("health", r"\b(allerg|diabet|blood pressure|medicine|medication|doctor|sugar|asthma|diet|gym|workout|"
               r"dawai|dawa|bimar|sehat)"),
    ("work", r"\b(work|job|office|company|boss|colleague|manager|client|salary|meeting|project|naukri|kaam|daftar)"),
    ("study", r"\b(study|studies|student|university|college|school|class|exam|semester|degree|course|"
              r"parh|parhai|imtihan)"),
    ("routine", r"\b(every (day|morning|night|week)|wake up|sleep at|routine|usually|daily|roz|har din|subah|raat ko)"),
    ("preferences", r"\b(like|love|prefer|favou?rite|enjoy|hate|dislike|don'?t like|pasand|napasand|shauq)"),
    ("people", r"\b(friend|neighbou?r|cousin|uncle|aunt|teacher|dost|chacha|mamu|khala|phupho)"),
    ("personal", r"\b(my name|i am|i'?m|born|birthday|age|years old|live in|from|mera naam|meri umar|"
                 r"paida|rehta|rehti|sālgirah|salgirah)"),
]
_RULES = [(c, re.compile(p, re.I)) for c, p in _RULES]


def guess_category(fact: str) -> str:
    for cat, rx in _RULES:
        if rx.search(fact or ""):
            return cat
    return "other"


def guess_importance(fact: str) -> int:
    f = (fact or "").lower()
    if re.search(r"\b(allerg|never|must|important|always|name is|naam|birthday|salgirah)", f):
        return 2
    return 1


# ---------------- the database ----------------
def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _lock():
    """One lock for the shared database connection (the history uses the same one)."""
    from . import storage
    return storage._LOCK


def _db():
    from . import storage
    c = storage.conn()
    _import_json_once(c)
    return c


def _import_json_once(c) -> None:
    """memory.json (older versions) -> the database, keeping ids and dates; the file is kept, renamed."""
    if not MEMORY_FILE.exists():
        return
    items = read_json(MEMORY_FILE, [])
    items = [i for i in items if isinstance(i, dict) and str(i.get("fact") or "").strip()] if isinstance(items, list) else []
    with _lock():
        if not MEMORY_FILE.exists():
            return
        have = {r[0] for r in c.execute("SELECT id FROM memories")}
        with c:
            for i in items:
                mid = int(i["id"]) if str(i.get("id", "")).isdigit() else None
                if mid in have:
                    continue
                when = str(i.get("saved") or _now())
                fact = str(i["fact"]).strip()
                c.execute("INSERT INTO memories(id, fact, category, importance, source, created, updated) "
                          "VALUES (?, ?, ?, ?, 'imported', ?, ?)",
                          (mid, fact, guess_category(fact), guess_importance(fact), when, when))
        n = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        if n >= len(items):                       # everything is in: keep the old file as a backup only
            target = MEMORY_FILE.with_name("memory.json.imported")
            if target.exists():
                target = MEMORY_FILE.with_name(f"memory.json.imported-{datetime.now():%Y%m%d%H%M%S}")
            MEMORY_FILE.replace(target)
            print(f"[memory] moved {len(items)} memories into the database ({target.name} kept as a backup)")


def _row(r) -> dict:
    return {"id": r[0], "fact": r[1], "category": r[2], "importance": r[3], "source": r[4],
            "created": r[5], "saved": r[6], "uses": r[7]}


_COLS = "id, fact, category, importance, source, created, updated, uses"


def _norm(text: str) -> str:
    return re.sub(r"[^\w]+", " ", (text or "").lower()).strip()


def all_facts(category: str | None = None) -> list[dict]:
    """Every memory, most important and most recently changed first."""
    q = f"SELECT {_COLS} FROM memories"
    args: tuple = ()
    if category in CATEGORIES:
        q += " WHERE category = ?"
        args = (category,)
    with _lock():
        rows = _db().execute(q + " ORDER BY importance DESC, updated DESC, id DESC", args).fetchall()
    return [_row(r) for r in rows]


def get(memory_id: int) -> dict | None:
    with _lock():
        r = _db().execute(f"SELECT {_COLS} FROM memories WHERE id = ?", (memory_id,)).fetchone()
    return _row(r) if r else None


def find_same(fact: str) -> dict | None:
    """An existing memory that says the same thing (ignoring case and punctuation)."""
    n = _norm(fact)
    return next((m for m in all_facts() if _norm(m["fact"]) == n), None) if n else None


def remember(fact: str, category: str | None = None, importance: int | None = None, source: str = "assistant") -> str:
    fact = (fact or "").strip()
    if not fact:
        return "Nothing to remember."
    same = find_same(fact)
    if same:
        return f"Already remembered as memory #{same['id']}."
    cat = category if category in CATEGORIES else guess_category(fact)
    imp = max(1, min(3, int(importance))) if importance else guess_importance(fact)
    when = _now()
    with _lock():
        c = _db()
        with c:
            cur = c.execute("INSERT INTO memories(fact, category, importance, source, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
                            (fact[:1000], cat, imp, source if source in ("you", "assistant", "suggested") else "assistant", when, when))
    return f"Saved memory #{cur.lastrowid} ({cat})."


def forget(memory_id: int) -> str:
    with _lock():
        c = _db()
        with c:
            n = c.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount
    return f"Forgot memory #{memory_id}." if n else f"No memory with id {memory_id}."


def update(memory_id: int, fact: str | None = None, category: str | None = None, importance: int | None = None) -> str:
    sets, args = [], []
    if fact is not None:
        fact = fact.strip()
        if not fact:
            return "A memory can't be empty (use forget_memory to delete it)."
        sets.append("fact = ?")
        args.append(fact[:1000])
    if category is not None:
        if category not in CATEGORIES:
            return f"Unknown category {category!r}. Use one of: {', '.join(CATEGORIES)}."
        sets.append("category = ?")
        args.append(category)
    if importance is not None:
        sets.append("importance = ?")
        args.append(max(1, min(3, int(importance))))
    if not sets:
        return "Nothing to change."
    sets.append("updated = ?")
    args += [_now(), memory_id]
    with _lock():
        c = _db()
        with c:
            n = c.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id = ?", args).rowcount
    return f"Updated memory #{memory_id}." if n else f"No memory with id {memory_id}."


def edit(memory_id: int, fact: str) -> str:
    return update(memory_id, fact=fact)


def merge(ids: list[int] | None = None, fact: str | None = None) -> str:
    """Combine several memories (all of them if ids is empty) into one."""
    items = all_facts()
    pick = [i for i in items if not ids or i["id"] in ids]
    if len(pick) < 2:
        return "There's nothing to combine (need at least two memories)."
    text = (fact or "").strip() or "; ".join(i["fact"].rstrip(". ") for i in pick) + "."
    cats = {i["category"] for i in pick}
    with _lock():
        c = _db()
        with c:
            c.executemany("DELETE FROM memories WHERE id = ?", [(i["id"],) for i in pick])
            cur = c.execute("INSERT INTO memories(fact, category, importance, source, created, updated) VALUES (?, ?, ?, 'you', ?, ?)",
                            (text[:4000], cats.pop() if len(cats) == 1 else "other", max(i["importance"] for i in pick), _now(), _now()))
    return f"Combined {len(pick)} memories into memory #{cur.lastrowid}."


def search(query: str = "", category: str | None = None, limit: int = 30) -> list[dict]:
    """Memories matching the words in query (best matches first); all of a category if no query."""
    items = all_facts(category)
    words = [w for w in _norm(query).split() if len(w) > 1]
    if not words:
        return items[:limit]
    scored = []
    for m in items:
        text = _norm(m["fact"]) + " " + m["category"]
        score = sum(2 if re.search(rf"\b{re.escape(w)}\b", text) else 1 if w in text else 0 for w in words)
        if score:
            scored.append((score, m["importance"], m))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    found = [m for _, _, m in scored[:limit]]
    if found:
        with _lock():
            c = _db()
            with c:
                c.executemany("UPDATE memories SET uses = uses + 1 WHERE id = ?", [(m["id"],) for m in found])
    return found


def counts() -> dict:
    with _lock():
        rows = _db().execute("SELECT category, COUNT(*) FROM memories GROUP BY category").fetchall()
    return {c: n for c, n in rows}


def as_text(limit: int = PROMPT_LIMIT) -> str:
    """Profile + the most important / newest memories, for the AI's instructions."""
    prof = profile()
    lines = [f"- {label}: {prof[k]}" for k, label in PROFILE_FIELDS if prof.get(k)]
    out = ("Profile the user wrote about themselves (always true; use it naturally, don't recite it):\n"
           + "\n".join(lines) + "\n\n") if lines else ""
    items = all_facts()
    if not items:
        return out + "(no saved memories yet)"
    shown = items[:limit]
    more = f"\n(+{len(items) - limit} more: use recall_memories with a search to find them)" if len(items) > limit else ""
    return out + "\n".join(f"#{i['id']} [{i['category']}{', important' if i['importance'] > 1 else ''}]: {i['fact']}"
                           for i in shown) + more


# ---------------- knowledge graph (Memory page › Graph) ----------------
# capitalised words that are not names or places
_NOT_NAMES = set("""
i i'm im my me mine we our you your he she his her they their it its the a an and or but if so to of in on at by for
with from as is are was were be been am has have had do does did not no yes this that these those there here when
what who where why how which user users likes like loves love prefers prefer wants want works work lives live
studies study goes go plays play uses use usually always never often sometimes every daily monday tuesday wednesday
thursday friday saturday sunday january february march april may june july august september october november
december mr mrs ms dr sir madam also very much more most some any all
mera meri mere main mujhe mujh hum ham hamara aap ap ka ki ke ko se mein hai hain tha thi the aur bhi
""".split())
_NAME = re.compile(r"\b[A-Z][a-zA-Z'-]{2,}")


def _names(fact: str) -> set[str]:
    """Capitalised words that look like names or places ("Hina's" counts as "Hina")."""
    out = set()
    for w in _NAME.findall(fact or ""):
        w = re.sub(r"'s$", "", w).strip("'-")
        if len(w) > 2 and w.lower() not in _NOT_NAMES:
            out.add(w)
    return out


def graph(limit: int = 120) -> dict:
    """You in the middle, your memory categories around you, each memory on its category, and the names/places
    that appear in two or more memories linking those memories together."""
    items = all_facts()[:limit]
    nodes = [{"id": "you", "kind": "you", "label": call_name()}]
    links: list[dict] = []
    for cat in CATEGORIES:
        if any(m["category"] == cat for m in items):
            nodes.append({"id": f"c:{cat}", "kind": "category", "label": cat, "category": cat})
            links.append({"source": "you", "target": f"c:{cat}"})
    seen: dict[str, list[int]] = {}
    for m in items:
        nodes.append({"id": f"m:{m['id']}", "kind": "memory", "label": m["fact"], "memory": m["id"],
                      "category": m["category"], "importance": m["importance"]})
        links.append({"source": f"c:{m['category']}", "target": f"m:{m['id']}"})
        for name in _names(m["fact"]):
            seen.setdefault(name, []).append(m["id"])
    for name, ids in sorted(seen.items()):
        if len(ids) < 2:
            continue
        nodes.append({"id": f"e:{name}", "kind": "name", "label": name})
        links.extend({"source": f"e:{name}", "target": f"m:{i}"} for i in ids)
    return {"nodes": nodes, "links": links}


# ---------------- "Shall I remember that?" ----------------
_SELF = re.compile(
    r"\b(my name is|call me|i am a|i'?m a|i work|i study|i live|i'?m from|i was born|my birthday|i (really )?(like|love|"
    r"prefer|hate|enjoy)|i'?m allergic|i don'?t (eat|like|drink)|my (wife|husband|son|daughter|mother|father|brother|"
    r"sister|friend|boss|teacher|favou?rite)|"
    r"mera naam|meri (umar|biwi|ammi|behen|beti|salgirah)|mera (beta|bhai|dost|shohar|pasandida)|mujhe .{1,40} "
    r"pasand|main .{1,30} (mein )?(kaam|parh(ta|ti)|reh(ta|ti)) (hoon|hun|hu))", re.I)
_QUESTION = re.compile(r"\?\s*$|^\s*(what|who|when|where|why|how|do|does|did|can|could|kya|kab|kahan|kaun|kaise|kyun)\b", re.I)


def suggest_from(text: str) -> dict | None:
    """If text is you telling something lasting about yourself, a memory to propose (else None)."""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not 8 <= len(t) <= 300 or _QUESTION.search(t) or not _SELF.search(t):
        return None
    fact = t[0].upper() + t[1:]
    if find_same(fact):
        return None
    return {"fact": fact, "category": guess_category(fact)}

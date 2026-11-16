"""Long-term memory: facts Jarvis keeps across sessions, plus the profile you fill in yourself."""
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


def _load() -> list[dict]:
    data = read_json(MEMORY_FILE, [])
    return data if isinstance(data, list) else []


def remember(fact: str) -> str:
    with DATA_LOCK:
        items = _load()
        item = {"id": max((i["id"] for i in items), default=0) + 1,
                "fact": fact.strip(),
                "saved": datetime.now().isoformat(timespec="minutes")}
        items.append(item)
        write_json(MEMORY_FILE, items)
    return f"Saved memory #{item['id']}."


def forget(memory_id: int) -> str:
    with DATA_LOCK:
        items = _load()
        kept = [i for i in items if i["id"] != memory_id]
        if len(kept) == len(items):
            return f"No memory with id {memory_id}."
        write_json(MEMORY_FILE, kept)
    return f"Forgot memory #{memory_id}."


def edit(memory_id: int, fact: str) -> str:
    fact = (fact or "").strip()
    if not fact:
        return "A memory can't be empty (use forget_memory to delete it)."
    with DATA_LOCK:
        items = _load()
        for i in items:
            if i["id"] == memory_id:
                i["fact"], i["saved"] = fact, datetime.now().isoformat(timespec="minutes")
                write_json(MEMORY_FILE, items)
                return f"Updated memory #{memory_id}."
    return f"No memory with id {memory_id}."


def merge(ids: list[int] | None = None, fact: str | None = None) -> str:
    """Combine several memories (all of them if ids is empty) into one."""
    with DATA_LOCK:
        items = _load()
        pick = [i for i in items if not ids or i["id"] in ids]
        if len(pick) < 2:
            return "There's nothing to combine (need at least two memories)."
        text = (fact or "").strip() or "; ".join(i["fact"].rstrip(". ") for i in pick) + "."
        keep = [i for i in items if i not in pick]
        new = {"id": max((i["id"] for i in items), default=0) + 1, "fact": text,
               "saved": datetime.now().isoformat(timespec="minutes")}
        write_json(MEMORY_FILE, keep + [new])
    return f"Combined {len(pick)} memories into memory #{new['id']}."


def all_facts() -> list[dict]:
    return _load()


def as_text() -> str:
    """Profile + memories, for the AI's instructions."""
    prof = profile()
    lines = [f"- {label}: {prof[k]}" for k, label in PROFILE_FIELDS if prof.get(k)]
    out = ("Profile the user wrote about themselves (always true; use it naturally, don't recite it):\n"
           + "\n".join(lines) + "\n\n") if lines else ""
    items = _load()
    return out + ("\n".join(f"#{i['id']}: {i['fact']}" for i in items) if items else "(no saved memories yet)")

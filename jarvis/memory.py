"""Long-term memory: facts Jarvis keeps across sessions, plus the profile you fill in yourself."""
from datetime import datetime

from .config import DATA_DIR, DATA_LOCK, MEMORY_FILE, USER_NAME, read_json, write_json

PROFILE_FILE = DATA_DIR / "profile.json"
# (key, label shown to the AI) - the Profile page in the Command Center edits these
PROFILE_FIELDS = [
    ("name", "Full name"), ("call", "What Jarvis calls you"), ("birthday", "Birthday"), ("city", "City"),
    ("work", "Study / work"), ("languages", "Languages"), ("family", "Family and important people"),
    ("interests", "Interests and hobbies"), ("favourites", "Favourite things"), ("routine", "Daily routine"),
    ("goals", "Goals and current projects"), ("health", "Health notes"), ("style", "Reply style Jarvis should use"),
    ("about", "Anything else"),
]


def profile() -> dict:
    data = read_json(PROFILE_FILE, {})
    return {k: str(data.get(k, "")) for k, _ in PROFILE_FIELDS} if isinstance(data, dict) else {}


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

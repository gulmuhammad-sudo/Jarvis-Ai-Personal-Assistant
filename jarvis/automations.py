"""Automations (Phase 6): several steps under one name, run by hand, at a time of day, or when the app opens.

A step is one of:
  {"tool": "get_weather", "args": {...}}   one of STEP_TOOLS below, nothing else
  {"say": "text"}                          a notification
  {"wait": seconds}                        1-300
  {"ask": "prompt"}                        hand a prompt to the AI (only as the last step)

Safety: only STEP_TOOLS can be steps, checked when saving AND again when running (a row edited or imported some other
way can't smuggle in another tool). No PowerShell, power actions, deleting, uninstalling, turning Wi-Fi off; nothing
that runs a script or program file. Steps go through tools.execute, so approvals, the audit log and Emergency Stop all
apply. Imported automations arrive switched off. One automation runs at a time.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from . import guard

MAX_AUTOMATIONS = 40
MAX_STEPS = 12
MAX_NAME = 40
MAX_TEXT = 500
CATCH_UP = timedelta(minutes=10)          # a timed run missed by a little (PC asleep) still runs; later it's skipped
EXPORT_FORMAT = "personal-assistant-automation"

# tool -> what its arguments may be in an automation, on top of the tool's own schema
STEP_TOOLS: dict[str, dict[str, Any]] = {
    "open_application": {}, "open_website": {}, "open_path": {}, "play_youtube": {}, "media_control": {},
    "set_brightness": {}, "set_theme": {}, "set_timer": {}, "save_note": {}, "get_weather": {}, "daily_briefing": {},
    "prayer_times": {}, "get_datetime": {}, "system_status": {}, "arrange_windows": {}, "lock_computer": {},
    "manage_windows": {"action": ("focus", "minimize", "maximize", "restore", "snap", "minimize_all")},
    "workspace": {"action": ("open",)}, "network": {"action": ("check",)}, "software": {"action": ("updates",)},
    "close_app": {"force": (False,)},
    "calendar": {"action": ("agenda",)}, "tasks": {"action": ("list",)},
}
ONLY = {"calendar": ("action", "day", "days"), "tasks": ("action", "project")}       # of these tools, only these settings
LABELS = {
    "open_application": "Open an app", "open_website": "Open a website", "open_path": "Open a folder or document",
    "play_youtube": "Play on YouTube", "media_control": "Media and volume", "set_brightness": "Screen brightness",
    "set_theme": "Light / dark look", "set_timer": "Start a timer", "save_note": "Write a note", "get_weather": "Weather",
    "daily_briefing": "Daily briefing", "prayer_times": "Prayer times", "get_datetime": "Date and time",
    "system_status": "PC health", "arrange_windows": "Windows side by side", "lock_computer": "Lock the PC (asks first)",
    "manage_windows": "Move a window", "workspace": "Open a workspace", "network": "Check the internet",
    "software": "Look for app updates", "close_app": "Close an app", "calendar": "What's planned", "tasks": "Open tasks",
}
# steps whose answer is the point: told to you when the automation ends
TELLS = {"get_weather": "Weather", "daily_briefing": "Briefing", "prayer_times": "Prayer times", "get_datetime": "Time", "system_status": "PC",
         "network": "Internet", "software": "App updates", "calendar": "Planned", "tasks": "Tasks"}

TEMPLATES = [
    {"name": "Morning start", "steps": [{"tool": "get_weather", "args": {}}, {"tool": "prayer_times", "args": {}}, {"tool": "calendar", "args": {"action": "agenda"}},
                                        {"ask": "Give me my daily briefing in a few short lines."}],
     "trigger": {"type": "time", "at": "08:00", "days": [0, 1, 2, 3, 4, 5, 6]}},
    {"name": "Focus time", "steps": [{"tool": "manage_windows", "args": {"action": "minimize_all"}},
                                     {"tool": "set_timer", "args": {"seconds": 1500, "message": "Focus time is over: take a break"}},
                                     {"say": "Focus time started: 25 minutes."}], "trigger": {"type": "manual"}},
    {"name": "Evening wind-down", "steps": [{"tool": "set_brightness", "args": {"level": 35}},
                                            {"tool": "set_theme", "args": {"theme": "dark"}},
                                            {"say": "Screen dimmed for the evening."}],
     "trigger": {"type": "time", "at": "22:00", "days": [0, 1, 2, 3, 4, 5, 6]}},
    {"name": "PC check-up", "steps": [{"tool": "system_status", "args": {}}, {"tool": "network", "args": {"action": "check"}},
                                      {"tool": "software", "args": {"action": "updates"}}], "trigger": {"type": "manual"}},
]


# ---------------- checking ----------------
def _schemas() -> dict[str, dict]:
    from . import tools
    return {d["name"]: d["input_schema"] for d in tools.TOOL_DEFINITIONS}


_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list}


def check_step(step: Any, last: bool = True) -> dict:
    """A clean copy of a step, or ValueError saying what's wrong with it."""
    if not isinstance(step, dict):
        raise ValueError("Each step must be an object.")
    kinds = [k for k in ("tool", "say", "wait", "ask") if k in step]
    if len(kinds) != 1:
        raise ValueError("Each step needs exactly one of: tool, say, wait, ask.")
    kind = kinds[0]
    if kind in ("say", "ask"):
        text = str(step[kind] or "").strip()
        if not text or len(text) > MAX_TEXT:
            raise ValueError(f"Write something to {kind} (up to {MAX_TEXT} characters).")
        if kind == "ask" and not last:
            raise ValueError("Asking the AI must be the last step (it answers in its own time).")
        return {kind: text}
    if kind == "wait":
        try:
            secs = int(step["wait"])
        except (TypeError, ValueError):
            secs = 0
        if not 1 <= secs <= 300 or isinstance(step["wait"], bool):
            raise ValueError("Wait between 1 and 300 seconds.")
        return {"wait": secs}
    name = str(step["tool"])
    if name not in STEP_TOOLS:
        raise ValueError(f"{name!r} can't be used in an automation.")
    schema = _schemas()[name]
    args = step.get("args") or {}
    if not isinstance(args, dict):
        raise ValueError(f"{LABELS[name]}: the settings must be an object.")
    clean = {}
    for key, val in args.items():
        spec = schema["properties"].get(key)
        if spec is None or (name in ONLY and key not in ONLY[name]):
            raise ValueError(f"{LABELS[name]}: unknown setting {key!r}.")
        if val is None or val == "":
            continue
        want = _TYPES.get(spec.get("type", ""), object)
        if not isinstance(val, want) or (isinstance(val, bool) and spec.get("type") != "boolean"):
            raise ValueError(f"{LABELS[name]}: {key} must be a {spec['type']}.")
        if "enum" in spec and val not in spec["enum"]:
            raise ValueError(f"{LABELS[name]}: {key} must be one of {', '.join(map(str, spec['enum']))}.")
        if isinstance(val, str) and len(val) > MAX_TEXT:
            raise ValueError(f"{LABELS[name]}: {key} is too long.")
        if isinstance(val, list) and (len(val) > 10 or not all(isinstance(x, str) and len(x) <= 100 for x in val)):
            raise ValueError(f"{LABELS[name]}: {key} must be a short list of names.")
        clean[key] = val
    for key in schema.get("required", []):
        if key not in clean:
            raise ValueError(f"{LABELS[name]}: {key} is missing.")
    for key, allowed in STEP_TOOLS[name].items():
        if key in clean and clean[key] not in allowed:
            raise ValueError(f"{LABELS[name]}: {key} can't be {clean[key]!r} in an automation.")
    if name == "workspace" and "name" not in clean:
        raise ValueError("Open a workspace: say which one.")
    if name == "open_website" and not re.match(r"^(https?://)?[\w-]+(\.[\w-]+)+([/?#:].*)?$", clean["url"], re.I):
        raise ValueError("Open a website: use a web address (http or https).")
    if name == "open_application" and (re.search(r"[\\/:*?\"<>|&;%^]", clean["name"]) or guard.runs_code(clean["name"])):
        raise ValueError("Open an app: use the app's name, not a file or path.")
    if name == "open_path":
        path = clean["path"].strip().rstrip(". ").strip("\"'")
        # no %COMSPEC%-style names (open_path expands them after this check), no second colon (hidden streams, shell:, http:)
        if (guard.runs_code(clean["path"]) or re.search(r"[%$<>|*?\"]", path) or ":" in path[2:]
                or re.match(r"^[a-z][a-z0-9+.-]+:", path, re.I) or path.startswith(("\\\\", "//"))):
            raise ValueError("Open a folder or document: programs, scripts, links, %names% and network paths aren't allowed.")
    return {"tool": name, "args": clean}


def check_steps(steps: Any) -> list[dict]:
    if not isinstance(steps, list) or not steps:
        raise ValueError("Add at least one step.")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"Up to {MAX_STEPS} steps.")
    return [check_step(s, i == len(steps) - 1) for i, s in enumerate(steps)]


def check_trigger(trigger: Any) -> dict:
    t = trigger if isinstance(trigger, dict) else {}
    kind = t.get("type", "manual")
    if kind in ("manual", "startup"):
        return {"type": kind}
    if kind != "time":
        raise ValueError("Run it by hand, at a time, or when the app opens.")
    at = str(t.get("at", ""))
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", at):
        raise ValueError("Pick a time like 08:00.")
    days = t.get("days", list(range(7)))
    if not isinstance(days, list) or not days or not all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days):
        raise ValueError("Pick at least one day.")
    return {"type": "time", "at": at, "days": sorted(set(days))}


def describe_step(step: dict) -> str:
    if "say" in step:
        return f"Show: {step['say']}"
    if "wait" in step:
        return f"Wait {step['wait']} s"
    if "ask" in step:
        return f"Ask the AI: {step['ask']}"
    args = ", ".join(f"{k} {v if not isinstance(v, list) else ' + '.join(v)}" for k, v in (step.get("args") or {}).items())
    return LABELS.get(step.get("tool"), str(step.get("tool"))) + (f" ({args})" if args else "")


DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def describe_trigger(t: dict) -> str:
    if t.get("type") == "startup":
        return "when the app opens"
    if t.get("type") == "time":
        days = t.get("days", [])
        return f"at {t['at']} " + ("every day" if len(days) == 7 else "on " + ", ".join(DAY_NAMES[d] for d in days))
    return "by hand"


def step_choices() -> list[dict]:
    """What the step editor offers: each allowed tool with its settings (already narrowed to what's allowed here)."""
    out = []
    for name, limits in STEP_TOOLS.items():
        schema = _schemas()[name]
        props = []
        for key, spec in schema["properties"].items():
            if limits.get(key) == (False,) or (name in ONLY and key not in ONLY[name]):
                continue                                   # fixed off (e.g. force-closing)
            choices = limits.get(key) or spec.get("enum")
            props.append({"key": key, "type": spec.get("type", "string"), "choices": list(choices) if choices else None,
                          "required": key in schema.get("required", []) or (name == "workspace" and key == "name")})
        out.append({"tool": name, "label": LABELS[name], "props": props})
    return sorted(out, key=lambda t: t["label"])


# ---------------- storage ----------------
_COLS = "id, name, steps, trigger, enabled, created, updated, last_run, last_ok, last_result, last_day, runs"


def _db():
    from . import storage
    return storage.conn(), storage._LOCK


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _row(r) -> dict:
    steps, trigger = json.loads(r[2]), json.loads(r[3])
    return {"id": r[0], "name": r[1], "steps": steps, "trigger": trigger, "enabled": bool(r[4]), "created": r[5],
            "updated": r[6], "last_run": r[7], "last_ok": None if r[8] is None else bool(r[8]), "last_result": r[9],
            "last_day": r[10], "runs": r[11], "steps_text": [describe_step(s) for s in steps],
            "trigger_text": describe_trigger(trigger)}


def all_automations() -> list[dict]:
    c, lock = _db()
    with lock:
        rows = c.execute(f"SELECT {_COLS} FROM automations ORDER BY name COLLATE NOCASE").fetchall()
    return [_row(r) for r in rows]


def get(auto_id: int) -> dict | None:
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_COLS} FROM automations WHERE id = ?", (auto_id,)).fetchone()
    return _row(r) if r else None


def find(name: str) -> dict | None:
    name = " ".join(str(name or "").split()).strip(" \"'").lower()
    items = all_automations()
    exact = [a for a in items if a["name"].lower() == name]
    start = [a for a in items if name and a["name"].lower().startswith(name)]
    return exact[0] if exact else start[0] if len(start) == 1 else None


def save(name: str, steps: Any, trigger: Any = None, enabled: bool = False, auto_id: int | None = None) -> dict:
    """Add or change an automation; ValueError with a message for the person when something isn't allowed."""
    name = " ".join(str(name or "").split())
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"Give it a name (up to {MAX_NAME} characters).")
    steps, trigger = check_steps(steps), check_trigger(trigger)
    c, lock = _db()
    with lock:
        same = c.execute("SELECT id FROM automations WHERE name = ?", (name,)).fetchone()
        if same and same[0] != auto_id:
            raise ValueError(f"There's already an automation called \"{name}\".")
        data = (name, json.dumps(steps, ensure_ascii=False), json.dumps(trigger), int(bool(enabled)), _now())
        with c:
            if auto_id is None:
                if c.execute("SELECT COUNT(*) FROM automations").fetchone()[0] >= MAX_AUTOMATIONS:
                    raise ValueError(f"You have {MAX_AUTOMATIONS} automations already; delete one first.")
                auto_id = c.execute("INSERT INTO automations(name, steps, trigger, enabled, updated, created) "
                                    "VALUES (?, ?, ?, ?, ?, ?)", (*data, _now())).lastrowid
            elif not c.execute("UPDATE automations SET name = ?, steps = ?, trigger = ?, enabled = ?, updated = ?, "
                               "last_day = NULL WHERE id = ?", (*data, auto_id)).rowcount:
                raise ValueError("That automation is gone.")
    return get(auto_id)


def set_enabled(auto_id: int, on: bool) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("UPDATE automations SET enabled = ?, updated = ? WHERE id = ?", (int(bool(on)), _now(), auto_id)).rowcount)


def delete(auto_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        return bool(c.execute("DELETE FROM automations WHERE id = ?", (auto_id,)).rowcount)


def export(auto_id: int) -> str:
    a = get(auto_id)
    if not a:
        raise ValueError("That automation is gone.")
    return json.dumps({"format": EXPORT_FORMAT, "version": 1, "name": a["name"], "steps": a["steps"], "trigger": a["trigger"]},
                      ensure_ascii=False, indent=2)


def import_text(text: str) -> dict:
    """A shared automation (JSON): checked like any other, never replaces one you have, and arrives switched off."""
    try:
        data = json.loads(str(text or "")[:50_000])
    except ValueError:
        raise ValueError("That isn't a shared automation (it must be the exported JSON text).") from None
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
        raise ValueError("That isn't a shared automation from this app.")
    if any(isinstance(s, dict) and "ask" in s for s in (data.get("steps") if isinstance(data.get("steps"), list) else [])):
        # its text would reach the AI as if you had typed it
        raise ValueError("Shared automations can't contain a prompt for the AI. Remove that step, or write it yourself.")
    base = name = " ".join(str(data.get("name") or "Imported").split())[:MAX_NAME] or "Imported"
    have, n = {a["name"].lower() for a in all_automations()}, 2
    while name.lower() in have:
        name, n = f"{base[:MAX_NAME - 4]} {n}", n + 1
    return save(name, data.get("steps"), data.get("trigger"), enabled=False)


# ---------------- running ----------------
_RUN_LOCK = threading.Lock()


class Runner:
    """Runs automations one at a time in the background. The HUD gives it the tool context and how to tell the page."""

    def __init__(self, ctx, emit: Callable[..., None], ask: Callable[[str], None], sleep: Callable[[float], bool] | None = None):
        self.ctx, self.emit, self.ask = ctx, emit, ask
        self._sleep = sleep or self._stoppable_sleep
        self._startup: tuple[set[int], datetime] | None = None    # "when the app opens" runs still to start, and until when

    @staticmethod
    def _stoppable_sleep(seconds: float) -> bool:
        """False when Emergency Stop was pressed while waiting."""
        from . import tools
        return not tools.STOP.wait(seconds)

    def start(self, auto: dict, why: str) -> bool:
        """Run in the background. False when another automation is still running."""
        if not _RUN_LOCK.acquire(blocking=False):
            return False

        def work():
            try:
                self._run(auto, why)
            finally:
                _RUN_LOCK.release()
        threading.Thread(target=work, daemon=True, name="automation").start()
        return True

    def _run(self, auto: dict, why: str) -> tuple[bool, str]:
        from . import audit, tools
        audit.record("automation_start", name=auto["name"], why=why)
        lines, tell, ok = [], [], True
        try:
            steps = check_steps(auto["steps"])              # again, at run time: never trust the stored row
        except ValueError as e:
            steps, ok, lines = [], False, [f"Not run: {e}"]
        total = len(steps)
        self.emit("auto_run", id=auto["id"], name=auto["name"], state="running", step=0, total=total, text="")
        for i, step in enumerate(steps, 1):
            if tools.STOP.is_set():
                ok = False
                lines.append("Stopped.")
                break
            self.emit("auto_run", id=auto["id"], name=auto["name"], state="running", step=i, total=total, text=describe_step(step))
            if "say" in step:
                self.ctx.notify(step["say"], "info")
                out, err = step["say"], False
            elif "wait" in step:
                err = not self._sleep(step["wait"])
                out = "Stopped while waiting." if err else f"waited {step['wait']} s"
            elif "ask" in step:
                self.ask(step["ask"])
                out, err = "sent to the AI", False
            else:
                out, err = tools.execute(step["tool"], step["args"], self.ctx)
                out = re.sub(r"</?untrusted[^>]*>", "", out if isinstance(out, str) else "done").strip()
                if step["tool"] in TELLS and not err:
                    tell.append(f"{TELLS[step['tool']]}: " + " ".join(ln.strip() for ln in out.splitlines()[:4] if ln.strip())[:320])
            lines.append(f"{i}. {describe_step(step)}: {out[:300]}")
            if err:
                ok = False
                break
        result = "\n".join(lines)[:4000]
        if tell:
            self.ctx.notify(f"{auto['name']}. " + " ".join(tell)[:900], "info")
        elif not ok and why.startswith("trigger"):
            self.ctx.notify(f"The automation {auto['name']} stopped early: {lines[-1][:200] if lines else ''}", "info")
        c, lock = _db()
        with lock, c:
            c.execute("UPDATE automations SET last_run = ?, last_ok = ?, last_result = ?, runs = runs + 1 WHERE id = ?",
                      (_now(), int(ok), result, auto["id"]))
        audit.record("automation_end", name=auto["name"], ok=ok, steps=len(lines))
        self.emit("auto_run", id=auto["id"], name=auto["name"], state="ok" if ok else "failed", step=len(lines), total=total, text=result)
        return ok, result

    def tick(self, now: datetime) -> list[str]:
        """Called by the scheduler every few seconds: start what's due. Returns the names started."""
        from . import tools
        started: list[str] = []
        today = now.date().isoformat()
        items = all_automations()
        if self._startup is None:                           # first tick after the app opened
            self._startup = ({a["id"] for a in items if a["enabled"] and a["trigger"]["type"] == "startup"}, now + CATCH_UP)
        for a in items:
            t = a["trigger"]
            if not a["enabled"]:
                continue
            due = t["type"] == "startup" and a["id"] in self._startup[0] and now <= self._startup[1]
            if t["type"] == "time" and now.weekday() in t["days"] and a["last_day"] != today:
                at = datetime.combine(now.date(), datetime.strptime(t["at"], "%H:%M").time())
                due = timedelta(0) <= now - at <= CATCH_UP
            if not due or tools.STOP.is_set():              # after Emergency Stop nothing starts by itself
                continue
            if self.start(a, f"trigger: {t['type']}"):      # busy: a timed one is tried again on the next tick
                started.append(a["name"])
                self._startup[0].discard(a["id"])
                if t["type"] == "time":
                    c, lock = _db()
                    with lock, c:
                        c.execute("UPDATE automations SET last_day = ? WHERE id = ?", (today, a["id"]))
        return started

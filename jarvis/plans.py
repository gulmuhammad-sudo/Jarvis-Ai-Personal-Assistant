"""Visible plans (Phase 6): before a longer task the AI shows its steps; you see each one tick off.

Setting "plan_mode": ask (default) = approve the plan first; each = approve the plan, then every step; show = only show it.
A plan is a promise you can see, not a permission: every risky tool still asks on its own, whatever the plan said.
One plan at a time, kept in memory. Emergency Stop ends it.

Your "no" holds in code, not only in the AI's instructions (a real AI went on with a step it had been refused, in the same
breath): after a refused plan or step, and in "each" mode outside an approved step, tools that change something don't run
(blocked(), checked in tools.execute for calls made by the AI) until you say something new.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

MODES = ("ask", "each", "show")
MAX_STEPS = 12
STATUSES = ("doing", "done", "failed", "skipped")

# tools that only look, or belong to the plan itself; "tool:action" allows just that action of it
LOOKING = {"get_datetime", "system_status", "find_files", "read_text_file", "list_notes", "recall_memories", "list_timers", "list_alarms",
           "web_search", "fetch_webpage", "get_weather", "daily_briefing", "prayer_times", "read_screen_text", "look_at_screen", "use_skill",
           "find_old_files", "dev_tools", "make_plan", "plan_step", "manage_windows:list", "workspace:list", "automation:list",
           "software:search", "software:installed", "software:updates", "network:check", "network:speed", "clipboard:read",
           "wireless:status", "end_conversation", "tasks:list", "calendar:agenda", "calendar:find", "notes:search",
           "notes:read", "documents:read", "documents:search", "goals:list", "journal:read", "email:list", "email:search", "email:read",
           "money:summary", "money:list", "money:bills", "media:now", "media:search", "media:radio", "images:info", "travel:list", "travel:show", "travel:weather", "meetings:list", "meetings:show", "meetings:transcript", "people:list", "people:coming", "learn:decks", "learn:quiz", "learn:search", "fitness:summary", "fitness:history", "clock:stopwatch_read", "clock:time_in", "clock:focus_minutes", "clock:ring_stop", "clock:snooze",
           "self_check:check", "history:search", "history:day", "news:top", "news:topic", "news:search", "news:following", "news:saved", "news:story"}

_LOCK = threading.RLock()
_PLAN: dict | None = None
_N = 0
_OPEN: int | None = None          # the step being carried out with your OK ("each" mode)
_HOLD = ""                        # why changes are on hold ("" = they aren't)
_HOLD_AT = 0.0
CHANGED: Callable[[dict | None], None] | None = None      # the HUD draws the plan card


def mode() -> str:
    from . import schedule
    m = schedule.get_setting("plan_mode", "ask")
    return m if m in MODES else "ask"


def current() -> dict | None:
    with _LOCK:
        return None if _PLAN is None else {**_PLAN, "steps": [dict(s) for s in _PLAN["steps"]]}


def _tell() -> None:
    if CHANGED:
        CHANGED(current())


def blocked(tool: str, args: dict | None = None) -> str:
    """Why the AI may not use this tool now ("" = it may)."""
    action = str((args or {}).get("action") or "").lower()
    if tool in LOOKING or (action and f"{tool}:{action}" in LOOKING):
        return ""
    with _LOCK:
        if _HOLD:
            return _HOLD
        if _PLAN is not None and _PLAN["state"] == "running" and _PLAN.get("mode") == "each" and _PLAN.get("armed") and _OPEN is None:
            return ("Not done: the user approves every step of this plan. Call plan_step with the step's number and status 'doing' first "
                    "(alone, and wait for the answer), do that step, then report it done.")
    return ""


def new_message(spoken: str = "") -> None:
    """The user said something new: a "no" is settled, and an unrelated wish isn't held back by an old plan.
    spoken: what was heard (leave it out for typed text). The spoken "no" that put things on hold isn't something new; a
    call hears it as speech too. So a bare "no", or a short refusal right after the hold began, changes nothing."""
    from . import approvals
    global _HOLD, _OPEN
    if spoken and approvals.parse(spoken) is False:
        words = len(spoken.split())
        if words <= 2 or (words <= 6 and time.time() - _HOLD_AT < 8):
            return
    with _LOCK:
        _HOLD, _OPEN = "", None
        if _PLAN is not None:
            _PLAN["armed"] = False                # plan_step('doing') arms it again


def start(title: str, steps: list[str], approve: Callable[[str], bool]) -> str:
    global _PLAN, _N, _OPEN, _HOLD, _HOLD_AT
    title = " ".join(str(title or "").split())[:80] or "Plan"
    texts = [" ".join(str(s or "").split())[:160] for s in (steps if isinstance(steps, list) else [])]
    texts = [t for t in texts if t]
    if not 2 <= len(texts) <= MAX_STEPS:
        return f"A plan needs 2 to {MAX_STEPS} short steps."
    how = mode()
    with _LOCK:
        _N += 1
        mine = _N
        _PLAN = {"id": mine, "title": title, "state": "running" if how == "show" else "waiting", "started": time.time(),
                 "mode": how, "armed": True,
                 "steps": [{"text": t, "status": "todo", "note": ""} for t in texts]}
        _OPEN = None
        if how != "show":
            _HOLD = "Not done: the user hasn't answered the plan yet."
    _tell()
    if how != "show":
        ok = approve(f"Plan: {title}\n\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)))
        with _LOCK:
            if _PLAN is None or _PLAN["id"] != mine or _PLAN["state"] != "waiting":
                return "That plan was stopped. Don't carry it out."
            _PLAN["state"] = "running" if ok else "refused"
            _HOLD = "" if ok else "Not done: the user said no to the plan. Ask what they want instead."
            _HOLD_AT = time.time()
        _tell()
        if not ok:
            return "The user said no to this plan. Don't do any of it; ask what they'd like changed."
    each = (" Before each step call plan_step with status 'doing', alone, and wait for the answer: the user approves every step, and tools that "
            "change something are refused outside an approved step. Report a step done only after everything in it is done.") if how == "each" else ""
    return (f"Plan #{mine} is shown. " if how == "show" else f"Plan #{mine} approved. ") + \
        "Report each step with plan_step (doing, then done / failed / skipped). Risky actions still ask on their own." + each


def step(number: int, status: str, note: str, approve: Callable[[str], bool]) -> str:
    global _OPEN, _HOLD, _HOLD_AT
    with _LOCK:
        if _PLAN is None or _PLAN["state"] != "running":
            state = _PLAN["state"] if _PLAN else "none"
            return f"There's no running plan ({state}). Don't continue it."
        if not 1 <= number <= len(_PLAN["steps"]):
            return f"This plan has steps 1 to {len(_PLAN['steps'])}."
        if status not in STATUSES:
            return f"status must be one of: {', '.join(STATUSES)}."
        s, mine, title, each = _PLAN["steps"][number - 1], _PLAN["id"], _PLAN["title"], _PLAN.get("mode") == "each"
        if s.get("refused"):
            return f"The user said no to step {number}. It stays skipped; don't do it."
        if each and status == "done" and _OPEN != number:
            return f"Step {number} wasn't started with the user's OK (plan_step 'doing' first), so it isn't done."
        if each and status == "doing":
            if _HOLD:
                return _HOLD
            _OPEN = None                          # nothing else runs while the question is open
            _PLAN["armed"] = True
    ok = True
    if status == "doing" and each:
        ok = approve(f"Step {number} of \"{title}\":\n\n{s['text']}")
    with _LOCK:
        if _PLAN is None or _PLAN["id"] != mine or _PLAN["state"] != "running":
            return "That plan was stopped. Don't carry it out."
        s["status"], s["note"] = (status, " ".join(str(note or "").split())[:200]) if ok else ("skipped", "you said no")
        if each:
            if not ok:
                s["refused"], _OPEN, _HOLD_AT = True, None, time.time()
                _HOLD = f"Not done: the user said no to step {number}. Stop here and ask whether to go on with the other steps."
            elif status == "doing":
                _OPEN = number
            elif _OPEN == number:
                _OPEN = None
        left = [x for x in _PLAN["steps"] if x["status"] in ("todo", "doing")]
        if not left:
            _PLAN["state"] = "failed" if any(x["status"] == "failed" for x in _PLAN["steps"]) else "finished"
    _tell()
    if not ok:
        return f"The user said no to step {number}: it is skipped. Nothing more runs until they answer: ask whether to go on with the rest."
    return f"Step {number}: {status}." + ("" if left else " That was the last step.")


def stop(why: str = "stopped") -> None:
    """Emergency Stop: a plan that isn't finished ends here."""
    global _OPEN
    with _LOCK:
        _OPEN = None
        if _PLAN is None or _PLAN["state"] not in ("waiting", "running"):
            return
        _PLAN["state"] = why
    _tell()


def dismiss() -> None:
    global _PLAN
    with _LOCK:
        if _PLAN is not None and _PLAN["state"] in ("waiting", "running"):
            return
        _PLAN = None
    _tell()

"""Visible plans (Phase 6): before a longer task the AI shows its steps; you see each one tick off.

Setting "plan_mode": ask (default) = approve the plan first; each = approve the plan, then every step; show = only show it.
A plan is a promise you can see, not a permission: every risky tool still asks on its own, whatever the plan said.
One plan at a time, kept in memory. Emergency Stop ends it.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

MODES = ("ask", "each", "show")
MAX_STEPS = 12
STATUSES = ("doing", "done", "failed", "skipped")

_LOCK = threading.RLock()
_PLAN: dict | None = None
_N = 0
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


def start(title: str, steps: list[str], approve: Callable[[str], bool]) -> str:
    global _PLAN, _N
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
                 "steps": [{"text": t, "status": "todo", "note": ""} for t in texts]}
    _tell()
    if how != "show":
        ok = approve(f"Plan: {title}\n\n" + "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1)))
        with _LOCK:
            if _PLAN is None or _PLAN["id"] != mine or _PLAN["state"] != "waiting":
                return "That plan was stopped. Don't carry it out."
            _PLAN["state"] = "running" if ok else "refused"
        _tell()
        if not ok:
            return "The user said no to this plan. Don't do any of it; ask what they'd like changed."
    each = " Before each step call plan_step with status 'doing' and wait: the user approves every step." if how == "each" else ""
    return (f"Plan #{mine} is shown. " if how == "show" else f"Plan #{mine} approved. ") + \
        "Report each step with plan_step (doing, then done / failed / skipped). Risky actions still ask on their own." + each


def step(number: int, status: str, note: str, approve: Callable[[str], bool]) -> str:
    with _LOCK:
        if _PLAN is None or _PLAN["state"] != "running":
            state = _PLAN["state"] if _PLAN else "none"
            return f"There's no running plan ({state}). Don't continue it."
        if not 1 <= number <= len(_PLAN["steps"]):
            return f"This plan has steps 1 to {len(_PLAN['steps'])}."
        if status not in STATUSES:
            return f"status must be one of: {', '.join(STATUSES)}."
        s, mine, title = _PLAN["steps"][number - 1], _PLAN["id"], _PLAN["title"]
    ok = True
    if status == "doing" and mode() == "each":
        ok = approve(f"Step {number} of \"{title}\":\n\n{s['text']}")
    with _LOCK:
        if _PLAN is None or _PLAN["id"] != mine or _PLAN["state"] != "running":
            return "That plan was stopped. Don't carry it out."
        s["status"], s["note"] = (status, " ".join(str(note or "").split())[:200]) if ok else ("skipped", "you said no")
        left = [x for x in _PLAN["steps"] if x["status"] in ("todo", "doing")]
        if not left:
            _PLAN["state"] = "failed" if any(x["status"] == "failed" for x in _PLAN["steps"]) else "finished"
    _tell()
    if not ok:
        return f"The user said no to step {number}: skip it and ask whether to go on with the rest."
    return f"Step {number}: {status}." + ("" if left else " That was the last step.")


def stop(why: str = "stopped") -> None:
    """Emergency Stop: a plan that isn't finished ends here."""
    with _LOCK:
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

"""Agents (Phase 6): helpers with their own role and their own short list of tools, sharing one board of results.

The main assistant hands an agent a task (tool "delegate"), or you do on the Agents page. The agent works in a fresh
conversation with the AI you already use (one agent at a time: free AI services limit how much can run at once).

Safety, enforced in code (tools.execute checks AgentContext.allowed_tools, whatever the AI asks for):
- an agent can only use the tools it was given, all from AGENT_TOOLS; no PowerShell, power, deleting, installing, making
  skills or automations, changing settings, and no calling other agents;
- an agent has EITHER tools that send something out (web) OR your private things (memories, notes, files, screen), never
  both, so a web page it reads can't get it to carry your data out. The shared board keeps that: results of agents that
  saw private things are only shown to agents that may see private things;
- approvals, the audit log and Emergency Stop apply as always.
What the main assistant (or you) writes in the task itself is of course seen by the agent.
"""
from __future__ import annotations

import copy
import json
import threading
from datetime import datetime
from typing import Any, Callable

MAX_AGENTS = 20
MAX_NAME = 30
MAX_ROLE = 1500
MAX_TASK = 4000
MAX_STEPS = 10                     # rounds of tool use per task
BOARD_SIZE = 10
BOARD_CHARS = 1200                 # of each result, in an agent's instructions

# sends something out of this PC (words you typed, an address)
# (daily_briefing is neither: it goes out AND holds alarms, timers and plans, so no agent has it)
OUTBOUND = {"web_search", "fetch_webpage", "open_website", "search_web_in_browser", "play_youtube", "get_weather", "prayer_times"}
# shows the agent something private
PRIVATE = {"recall_memories", "list_notes", "read_text_file", "find_files", "read_screen_text", "manage_windows", "workspace",
           "list_alarms", "list_timers", "dev_tools", "find_old_files", "remember_fact", "edit_memory", "system_status", "network",
           "write_file", "make_folder", "save_note", "tasks", "calendar", "notes", "documents", "arrange_windows", "cancel_timer"}
# neither
PLAIN = {"get_datetime", "set_timer", "set_alarm", "media_control", "set_brightness", "set_theme", "open_application"}
AGENT_TOOLS = OUTBOUND | PRIVATE | PLAIN
# tools with a wider reach than an agent should have: only these actions
LIMITS: dict[str, tuple[str, ...]] = {"workspace": ("open", "list"), "network": ("check",), "dev_tools": ("versions", "ports"),
                                     "tasks": ("list", "add", "update", "done", "undone"), "calendar": ("agenda", "find", "add", "update"),
                                     "notes": ("search", "read")}

BUILT_IN = [
    {"key": "researcher", "name": "Researcher", "memory": False, "tools": ["web_search", "fetch_webpage", "get_datetime"],
     "role": "Find current, reliable information on the web. Check more than one source, say when they disagree, and give a short "
             "answer with the addresses you used."},
    {"key": "organiser", "name": "Organiser", "memory": True,
     "tools": ["recall_memories", "tasks", "calendar", "notes", "save_note", "set_timer", "list_timers", "set_alarm", "list_alarms", "get_datetime"],
     "role": "Keep the user's day in order: notes, timers, alarms and what they told you before. Be brief and exact about times."},
    {"key": "pc_helper", "name": "PC Helper", "memory": False,
     "tools": ["system_status", "network", "manage_windows", "arrange_windows", "workspace", "open_application", "media_control",
               "set_brightness", "set_theme", "get_datetime"],
     "role": "Look after the PC: health, internet, windows and workspaces. Say plainly what you found and what you did."},
    {"key": "writer", "name": "Writer", "memory": True, "tools": ["documents", "read_text_file", "find_files", "list_notes", "save_note", "write_file"],
     "role": "Write and improve texts for the user from what they give you and their files. Save to a file only when asked."},
]


# ---------------- checking ----------------
def check(name: Any, role: Any, tools_: Any, memory: Any) -> tuple[str, str, list[str], bool]:
    name = " ".join(str(name or "").split())
    role = str(role or "").strip()
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"Give the agent a name (up to {MAX_NAME} characters).")
    if not role or len(role) > MAX_ROLE:
        raise ValueError(f"Write what the agent does (up to {MAX_ROLE} characters).")
    if not isinstance(tools_, list) or not all(isinstance(t, str) for t in tools_):
        raise ValueError("Choose its tools.")
    picked = list(dict.fromkeys(tools_))
    bad = [t for t in picked if t not in AGENT_TOOLS]
    if bad:
        raise ValueError(f"An agent can't have: {', '.join(bad)}.")
    out, private = [t for t in picked if t in OUTBOUND], [t for t in picked if t in PRIVATE]
    if out and (private or memory):
        why = ["your memories"] if memory else []
        raise ValueError(f"Web or private, not both: {', '.join(out)} can't go together with {', '.join(why + private)}. "
                         "Make two agents instead.")
    return name, role, picked, bool(memory)


def sees_private(agent: dict) -> bool:
    return bool(agent["memory"]) or any(t in PRIVATE for t in agent["tools"])


def goes_out(agent: dict) -> bool:
    return any(t in OUTBOUND for t in agent["tools"])


# ---------------- storage ----------------
def _db():
    from . import storage
    return storage.conn(), storage._LOCK


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _row(r) -> dict:
    return {"id": r[0], "name": r[1], "role": r[2], "tools": json.loads(r[3]), "memory": bool(r[4]), "runs": r[5], "built_in": False}


def all_agents() -> list[dict]:
    c, lock = _db()
    with lock:
        rows = c.execute("SELECT id, name, role, tools, memory, runs FROM agents ORDER BY name COLLATE NOCASE").fetchall()
    own = [_row(r) for r in rows]
    fixed = [{"id": a["key"], "name": a["name"], "role": a["role"], "tools": a["tools"], "memory": a["memory"], "runs": 0, "built_in": True}
             for a in BUILT_IN]
    out = fixed + own
    for a in out:
        a["web"], a["private"] = goes_out(a), sees_private(a)
    return out


def get(agent_id: Any) -> dict | None:
    return next((a for a in all_agents() if str(a["id"]) == str(agent_id)), None)


def find(name: str) -> dict | None:
    n = " ".join(str(name or "").split()).strip(" \"'").lower()
    items = all_agents()
    exact = [a for a in items if a["name"].lower() == n]
    start = [a for a in items if n and a["name"].lower().startswith(n)]
    return exact[0] if exact else start[0] if len(start) == 1 else None


def save(name: Any, role: Any, tools_: Any, memory: Any = False, agent_id: Any = None) -> dict:
    name, role, picked, memory = check(name, role, tools_, memory)
    other = next((a for a in all_agents() if a["name"].lower() == name.lower()), None)
    if other and str(other["id"]) != str(agent_id):
        raise ValueError(f"There's already an agent called \"{name}\".")
    if agent_id is not None and not str(agent_id).isdigit():
        raise ValueError("The ready-made agents can't be changed. Make your own instead.")
    c, lock = _db()
    with lock, c:
        data = (name, role, json.dumps(picked), int(memory), _now())
        if agent_id is None:
            if c.execute("SELECT COUNT(*) FROM agents").fetchone()[0] >= MAX_AGENTS:
                raise ValueError(f"You have {MAX_AGENTS} agents already; delete one first.")
            agent_id = c.execute("INSERT INTO agents(name, role, tools, memory, updated, created) VALUES (?, ?, ?, ?, ?, ?)",
                                 (*data, _now())).lastrowid
        elif not c.execute("UPDATE agents SET name = ?, role = ?, tools = ?, memory = ?, updated = ? WHERE id = ?",
                           (*data, int(agent_id))).rowcount:
            raise ValueError("That agent is gone.")
    return get(agent_id)


def delete(agent_id: Any) -> bool:
    if not str(agent_id).isdigit():
        return False
    c, lock = _db()
    with lock, c:
        return bool(c.execute("DELETE FROM agents WHERE id = ?", (int(agent_id),)).rowcount)


def tool_choices() -> list[dict]:
    """For the agent editor: the tools an agent may have, and which side they're on."""
    from . import tools
    defs = {d["name"]: d["description"].split(". ")[0] for d in tools.TOOL_DEFINITIONS + tools.WEB_TOOL_DEFINITIONS}
    return [{"tool": t, "label": t.replace("_", " "), "what": defs.get(t, "")[:120],
             "kind": "web" if t in OUTBOUND else "private" if t in PRIVATE else "plain"} for t in sorted(AGENT_TOOLS)]


# ---------------- the shared board ----------------
_BOARD: list[dict] = []
_BOARD_LOCK = threading.Lock()


def board() -> list[dict]:
    with _BOARD_LOCK:
        return [dict(b) for b in _BOARD]


def post(agent: dict, task: str, result: str) -> None:
    with _BOARD_LOCK:
        _BOARD.append({"agent": agent["name"], "task": task[:300], "result": result[:4000], "at": _now(), "private": sees_private(agent)})
        del _BOARD[:-BOARD_SIZE]


def clear_board() -> None:
    with _BOARD_LOCK:
        _BOARD.clear()


def board_for(agent: dict) -> list[dict]:
    """What this agent may read of the others: never private results for one that isn't allowed private things."""
    return [b for b in board() if sees_private(agent) or not b["private"]]


# ---------------- running ----------------
class AgentContext:
    """The normal tool context with a hard list of allowed tools (checked in tools.execute) and the agent's name on approvals.
    Everything else (timers, settings hooks) is the real context's."""

    def __init__(self, parent, agent: dict):
        object.__setattr__(self, "_parent", parent)
        object.__setattr__(self, "allowed_tools", frozenset(agent["tools"]) & AGENT_TOOLS)
        object.__setattr__(self, "limits", LIMITS)
        object.__setattr__(self, "agent_name", agent["name"])

    def __getattr__(self, key):
        return getattr(object.__getattribute__(self, "_parent"), key)

    def __setattr__(self, key, value):
        setattr(object.__getattribute__(self, "_parent"), key, value)

    def approve(self, question: str, kind: str | None = None) -> bool:
        # no "always allow" for agents: the kind is only passed on so that a "Never" rule still refuses
        return self._parent.approve(f"[{self.agent_name}] {question}", kind=kind)


def instructions(agent: dict) -> str:
    from . import guard, memory, schedule
    text = (f"You are {agent['name']}, a specialist agent working for {schedule.agent_name()}, a personal assistant on a Windows PC.\n"
            f"Your job: {agent['role']}\n\nDo only the task you are given, with your tools, then answer with the result: short, plain and "
            "honest. Say what you could not do or could not check. Never claim an action a tool didn't confirm. You can't ask other "
            "agents; don't ask the user questions unless you can't go on.\n")
    if agent["memory"]:
        text += f"\nWhat is known about the user ({memory.call_name()}):\n{memory.as_text()}\n"
    shared = board_for(agent)
    if shared:
        listing = "\n\n".join(f"{b['agent']} was asked: {b['task']}\nand answered: {b['result'][:BOARD_CHARS]}" for b in shared)
        text += "\nEarlier results from the team:\n" + guard.wrap("team board", listing) + "\n"
    return text + guard.SYSTEM_RULE


_RUN_LOCK = threading.Lock()


class Runner:
    """Runs one agent task at a time with the AIs the app already uses, in the same order."""

    def __init__(self, brain: Callable[[], Any], ctx, emit: Callable[..., None], on_tool: Callable[[str, dict], None]):
        self.brain, self.ctx, self.emit, self.on_tool = brain, ctx, emit, on_tool

    def _clone(self, backend, agent: dict, steps: list[str]):
        """The same AI, with a fresh conversation and only the agent's tools."""
        b = copy.copy(backend)                       # shares the connection, nothing of the conversation
        b.messages, b._note, b.max_steps = [], None, MAX_STEPS
        b.system = instructions(agent)
        b.tool_defs = [d for d in backend.tool_defs if d["function"]["name"] in agent["tools"] and d["function"]["name"] in AGENT_TOOLS]
        b.ctx = AgentContext(self.ctx, agent)
        b.on_text = lambda text: None

        def on_tool(name, args):
            steps.append(name)
            self.emit("agent_run", id=agent["id"], name=agent["name"], state="running", text=name.replace("_", " "))
            self.on_tool(name, args)
        b.on_tool = on_tool
        return b

    def run(self, agent: dict, task: str) -> tuple[bool, str]:
        """Do the task now and return (ok, answer). One at a time."""
        from . import audit, tools
        from .brain import ProviderError
        from .providers import route
        task = str(task or "").strip()[:MAX_TASK]
        if not task:
            return False, "There's no task."
        try:
            check(agent["name"], agent["role"], agent["tools"], agent["memory"])      # again: never trust the stored row
        except ValueError as e:
            return False, f"{agent['name']} can't run: {e}"
        if not _RUN_LOCK.acquire(blocking=False):
            return False, "Another agent is still working; try again when it's done."
        ok, answer, steps = False, "", []
        try:
            audit.record("agent_start", agent=agent["name"], task=task[:200])
            self.emit("agent_run", id=agent["id"], name=agent["name"], state="running", text="thinking", task=task[:300])
            if tools.STOP.is_set():
                return False, "Stopped."
            brain = self.brain()
            backends = [(label, b) for label, b in getattr(brain, "backends", []) if hasattr(b, "tool_defs") and hasattr(b, "messages")]
            order, _ = route(backends, task) if backends else ([], "")
            problems = []
            for label, backend in order:
                clone = self._clone(backend, agent, steps)
                try:
                    answer = (clone.ask(task) or "").strip() or "(no answer)"
                    ok = not tools.STOP.is_set()
                    break
                except ProviderError as e:
                    problems.append(f"{label}: {e}")
                    if getattr(e, "acted", False) or steps:
                        answer = f"It stopped partway ({label}). Tools already used: {', '.join(steps)}. Check before asking again."
                        break
            else:
                answer = "No AI could answer right now. " + "; ".join(problems) if problems else "No AI is set up (or there's no internet)."
            if ok:
                post(agent, task, answer)
                if str(agent["id"]).isdigit():
                    c, lock = _db()
                    with lock, c:
                        c.execute("UPDATE agents SET runs = runs + 1 WHERE id = ?", (int(agent["id"]),))
            return ok, answer
        except Exception as e:                       # an agent must never take the assistant down
            answer = f"{type(e).__name__}: {e}"
            return False, answer
        finally:
            _RUN_LOCK.release()
            audit.record("agent_end", agent=agent["name"], ok=ok, tools=steps[:20])
            self.emit("agent_run", id=agent["id"], name=agent["name"], state="done" if ok else "failed", text=answer[:6000], tools=steps[:20],
                      task=task[:300])

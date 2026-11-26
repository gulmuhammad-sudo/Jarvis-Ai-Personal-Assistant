"""The API for your own programs on this PC: http://127.0.0.1:<port>/v1/…, with a key from Settings › API.

Only from this PC (the window's own server listens nowhere else), never from a web page (no browser may use it), only what
the key's scopes allow, 60 requests a minute, not while the app is locked. A program can't undo Stop, and what it asks of the
assistant counts as a program's words: the assistant doesn't go online or leave orders behind for it without asking you.
"""
from __future__ import annotations

import json
import re
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote

from . import access

PER_MINUTE, MAX_BODY, MAX_WAIT = 60, 64_000, 120
_RATE: dict[str, list[float]] = {}
_LOCK = threading.Lock()

# method, path, scope, what it does, body
ROUTES: list[tuple[str, str, str, str, dict]] = [
    ("GET", "/v1/status", "status", "What the assistant is doing", {}),
    ("POST", "/v1/ask", "ask", "Ask the assistant and wait for its answer", {"text": "what you ask", "wait": "seconds, up to 120 (60)"}),
    ("POST", "/v1/notify", "notify", "Show a notice in the app", {"text": "up to 300 letters"}),
    ("GET", "/v1/tasks", "tasks", "Open tasks (?q=words)", {}),
    ("POST", "/v1/tasks", "tasks", "Add a task", {"title": "what", "due": "a day, also with a time (not needed)", "project": "(not needed)"}),
    ("POST", "/v1/tasks/{id}/done", "tasks", "Tick a task off", {"done": "true or false"}),
    ("GET", "/v1/agenda", "agenda", "Events and tasks (?days=1 to 14)", {}),
    ("GET", "/v1/notes", "notes", "Notes (?q=words)", {}),
    ("GET", "/v1/notes/{name}", "notes", "One note", {}),
    ("POST", "/v1/notes", "notes", "A new note", {"name": "its name", "text": "its text"}),
    ("GET", "/v1/memories", "memories", "What it remembers (?q=words)", {}),
]


class ApiError(Exception):
    def __init__(self, status: int, text: str) -> None:
        super().__init__(text)
        self.status = status


def openapi(port: int) -> dict:
    from . import __version__
    paths: dict[str, dict] = {}
    for method, path, scope, about, body in ROUTES:
        op: dict[str, Any] = {"summary": about, "security": [{"key": []}], "x-scope": scope, "responses": {"200": {"description": "OK"}, "401": {"description": "No key, or not a good one"}, "403": {"description": "The key may not do that"}}}
        names = re.findall(r"\{(\w+)\}", path)
        if names:
            op["parameters"] = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}} for n in names]
        if body:
            op["requestBody"] = {"content": {"application/json": {"schema": {"type": "object", "properties": {k: {"description": v} for k, v in body.items()}}}}}
        paths.setdefault(path, {})[method.lower()] = op
    return {"openapi": "3.0.3", "info": {"title": "Personal Assistant", "version": __version__}, "servers": [{"url": f"http://127.0.0.1:{port}"}], "paths": paths,
            "components": {"securitySchemes": {"key": {"type": "http", "scheme": "bearer"}}}}


def _limited(key: str) -> bool:
    now = time.monotonic()
    with _LOCK:
        t = [x for x in _RATE.get(key, []) if now - x < 60]
        t.append(now)
        _RATE[key] = t
        return len(t) > PER_MINUTE


def handle(hub: Any, port: int, method: str, target: str, headers: Any, body: bytes) -> tuple[int, dict]:
    """One request. Returns (status, answer)."""
    from . import lock
    path, _, query = target.partition("?")
    if headers.get("Origin") or headers.get("Sec-Fetch-Site") not in (None, "none"):
        return 403, {"error": "Not from a web page."}
    if path == "/v1/openapi.json" and method == "GET":
        return 200, openapi(port)
    from . import parts
    if not parts.is_on("devices"):
        return 403, {"error": "The API is turned off (Settings > Updates & parts)."}
    if access.held("127.0.0.1 api"):
        return 429, {"error": "Too many wrong keys. Wait ten minutes."}
    m = re.fullmatch(r"Bearer\s+(\S+)", headers.get("Authorization") or "")
    key = access.check_key(m[1]) if m else None
    if key is None:
        access.failed("127.0.0.1 api")
        return 401, {"error": "Send your key: Authorization: Bearer pa_…"}
    if _limited(key["id"]):
        return 429, {"error": f"At most {PER_MINUTE} requests a minute."}
    if lock.is_locked():
        return 423, {"error": "The app is locked."}
    try:
        for want, pattern, scope, _about, _b in ROUTES:
            hit = re.fullmatch(re.sub(r"\{\w+\}", "([^/]+)", pattern), path)
            if hit and want == method:
                if scope not in key["scopes"]:
                    raise ApiError(403, f"This key may not do that (it needs: {scope}).")
                data: dict = {}
                if method == "POST":
                    try:
                        data = json.loads(body or b"{}")
                    except ValueError:
                        raise ApiError(400, "Send JSON.") from None
                    if not isinstance(data, dict):
                        raise ApiError(400, "Send a JSON object.")
                return 200, _do(hub, key, method, pattern, [unquote(x) for x in hit.groups()], {k: v[0] for k, v in parse_qs(query).items()}, data)
        known = any(re.fullmatch(re.sub(r"\{\w+\}", "[^/]+", p), path) for _, p, *_x in ROUTES)
        return (405, {"error": "Not with this method."}) if known else (404, {"error": "There is nothing at that address. See /v1/openapi.json."})
    except ApiError as e:
        return e.status, {"error": str(e)}
    except (ValueError, TypeError, KeyError) as e:
        return 400, {"error": str(e) if isinstance(e, ValueError) and str(e)[:1].isupper() and len(str(e)) < 200 else "Something is missing or wrong."}


def _do(hub: Any, key: dict, method: str, route: str, parts: list[str], q: dict, data: dict) -> dict:
    from . import audit, memory, notes, planner, schedule, tools
    from . import __version__
    if route == "/v1/status":
        return {"name": schedule.agent_name(), "version": __version__, "state": hub.state, "busy": bool(hub.busy), "waiting_for_you": len(hub.pending)}
    if route == "/v1/ask":
        text = str(data.get("text") or "").strip()
        if not text or len(text) > 8000:
            raise ApiError(400, "Send a text (up to 8000 letters).")
        try:
            wait = max(1.0, min(float(data.get("wait") or 60), MAX_WAIT))
        except (TypeError, ValueError):
            raise ApiError(400, "wait is a number of seconds.") from None
        audit.record("api_asked", program=key["name"])
        got = hub.ask_and_wait(text, "api", wait)
        if got is None:
            raise ApiError(409, "Stop was pressed on the PC. It answers again after the owner's next message.")
        return got
    if route == "/v1/notify":
        text = str(data.get("text") or "").strip()[:300]
        if not text:
            raise ApiError(400, "Send a text.")
        hub.notify(f"{key['name']}: {text}", "info")
        return {"ok": True}
    if route.startswith("/v1/tasks"):
        if method == "GET":
            return {"tasks": planner.list_tasks(query=str(q.get("q") or ""), limit=200)}
        if route == "/v1/tasks":
            t = planner.save_task(title=data.get("title"), due=data.get("due") or None, project=data.get("project") or None, notes=data.get("notes") or None)
        else:
            if not planner.set_done(int(parts[0]), data.get("done", True) is True):
                raise ApiError(404, "There is no such task.")
            t = planner.get_task(int(parts[0])) or {}
        tools._planner_changed()
        return {"task": t}
    if route == "/v1/agenda":
        return {"days": planner.agenda(days=max(1, min(int(q.get("days") or 1), 14)))}
    if route.startswith("/v1/notes"):
        if method == "POST":
            n = notes.save(str(data.get("name") or ""), str(data.get("text") or ""), new=True)
            tools._planner_changed()
            return {"note": n}
        if parts:
            return {"name": parts[0], "text": notes.read(parts[0])}
        return {"notes": notes.all_notes(str(q.get("q") or ""))[:200]}
    if route == "/v1/memories":
        return {"memories": [{k: m[k] for k in ("id", "fact", "category") if k in m} for m in memory.search(str(q.get("q") or ""), limit=100)]}
    raise ApiError(404, "There is nothing at that address.")

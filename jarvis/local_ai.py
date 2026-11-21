"""Local AI through Ollama (free, runs on this PC, works offline, nothing leaves the computer).

Ollama is a separate free program (https://ollama.com). This module only talks to it on 127.0.0.1:
- is it installed / running, which models are downloaded and what they can do (tools, images);
- download a model when you ask (with progress);
- one chat request (Ollama's own /api/chat, so the context size can be set: small models default to a
  context too short for the assistant's instructions and tools).

Nothing here downloads or installs Ollama itself: the app sends you to ollama.com for that.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not HOST.startswith("http"):
    HOST = "http://" + HOST
DOWNLOAD_PAGE = "https://ollama.com/download/windows"
CONTEXT = int(os.environ.get("JARVIS_LOCAL_CONTEXT", "8192"))
# Good small models that can use tools, smallest first: (name, size, what it's like)
RECOMMENDED = [
    ("qwen2.5:3b", "1.9 GB", "fast on most laptops, follows tool instructions well"),
    ("llama3.2:3b", "2.0 GB", "fast, good English"),
    ("qwen2.5:7b", "4.7 GB", "smarter, needs 8 GB+ free memory"),
]
_PREFER = ("qwen3", "qwen2.5", "llama3.2", "llama3.1", "mistral", "gemma3", "phi4", "granite")
_cache: dict = {"at": 0.0, "models": None}


def _req(path: str, body: dict | None = None, timeout: float = 3.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(HOST + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


def exe() -> Path | None:
    """Where ollama.exe is, if installed."""
    found = shutil.which("ollama")
    if found:
        return Path(found)
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return p if p.exists() else None


def installed() -> bool:
    return exe() is not None or running()


def running() -> bool:
    try:
        return "version" in _req("/api/version", timeout=1.5)
    except (OSError, ValueError, urllib.error.URLError):
        return False


def start() -> bool:
    """Start Ollama in the background if it's installed but not running. True once it answers."""
    if running():
        return True
    path = exe()
    if not path:
        return False
    try:
        subprocess.Popen([str(path), "serve"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except OSError:
        return False
    for _ in range(20):
        time.sleep(0.5)
        if running():
            return True
    return False


def models(refresh: bool = False) -> list[dict]:
    """Downloaded models: [{name, size_gb, tools, vision}] ([] if Ollama isn't running). Cached 30 s."""
    if not refresh and _cache["models"] is not None and time.time() - _cache["at"] < 30:
        return _cache["models"]
    out = []
    try:
        for m in _req("/api/tags").get("models", []):
            name = m.get("name") or m.get("model")
            caps: list = []
            try:
                caps = _req("/api/show", {"model": name}).get("capabilities") or []
            except (OSError, ValueError, urllib.error.URLError):
                pass
            out.append({"name": name, "size_gb": round((m.get("size") or 0) / 1e9, 1),
                        "tools": "tools" in caps, "vision": "vision" in caps})
    except (OSError, ValueError, urllib.error.URLError):
        out = []
    _cache.update(at=time.time(), models=out)
    return out


def pick_model() -> str | None:
    """The model to use: JARVIS_LOCAL_MODEL / the saved choice, else the best downloaded model that can use tools."""
    from . import schedule
    have = models()
    names = [m["name"] for m in have]
    chosen = os.environ.get("JARVIS_LOCAL_MODEL") or schedule.get_setting("local_model")
    if chosen and chosen in names:
        return chosen
    usable = [m["name"] for m in have if m["tools"]]
    for family in _PREFER:
        for n in usable:
            if n.startswith(family):
                return n
    return usable[0] if usable else None


def status() -> dict:
    """For the AI Models page."""
    if not running():
        return {"installed": installed(), "running": False, "models": [], "model": None,
                "recommended": [dict(zip(("name", "size", "about"), r)) for r in RECOMMENDED]}
    return {"installed": True, "running": True, "models": models(), "model": pick_model(),
            "recommended": [dict(zip(("name", "size", "about"), r)) for r in RECOMMENDED]}


def pull(name: str, on_progress=None) -> None:
    """Download a model (streams progress: on_progress(status_text, fraction or None)). Raises on failure."""
    req = urllib.request.Request(HOST + "/api/pull", data=json.dumps({"model": name, "stream": True}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    last = 0.0
    with urllib.request.urlopen(req, timeout=60) as r:
        for line in r:
            if not line.strip():
                continue
            msg = json.loads(line)
            if msg.get("error"):
                raise RuntimeError(msg["error"])
            total, done = msg.get("total"), msg.get("completed")
            frac = (done / total) if total and done is not None else None
            if on_progress and (time.time() - last > 0.5 or msg.get("status") == "success"):
                last = time.time()
                on_progress(msg.get("status", ""), frac)
    _cache["models"] = None


def chat(model: str, messages: list[dict], tools: list[dict] | None = None, timeout: float = 300) -> dict:
    """One /api/chat request (not streamed). Returns Ollama's 'message' dict (content, tool_calls)."""
    body = {"model": model, "messages": messages, "stream": False, "options": {"num_ctx": CONTEXT}}
    if tools:
        body["tools"] = tools
    return _req("/api/chat", body, timeout=timeout).get("message") or {}

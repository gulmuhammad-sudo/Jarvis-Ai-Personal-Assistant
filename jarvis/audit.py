"""Audit log: a permanent record of what the assistant did on this PC.

One JSON line per event in audit.log (data folder): every tool call and every approval question with your
answer. It never stores secrets or file contents: argument values are shortened, anything that looks like a key
or password is replaced by "[hidden]", and long text fields only record their length.
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_MAX_BYTES = 5_000_000                      # then audit.log becomes audit.old.log and a new one starts
_SECRET_NAME = re.compile(r"(key|token|password|passwd|secret|pin|otp|cookie)", re.I)
_SECRET_VALUE = re.compile(r"(AIza[0-9A-Za-z_-]{20,}|gsk_[0-9A-Za-z]{20,}|sk-[A-Za-z0-9-]{20,}|ghp_[0-9A-Za-z]{20,}"
                           r"|xox[abp]-[0-9A-Za-z-]{10,}|eyJ[0-9A-Za-z_-]{20,}\.[0-9A-Za-z_-]+)")
_BULKY = {"content", "text", "body", "data", "html"}       # record only their size


def file() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "audit.log"


def redact(value, name: str = ""):
    """A loggable version of a value: secrets hidden, bulky text replaced by its length, long strings cut."""
    if name and _SECRET_NAME.search(name):
        return "[hidden]"
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in list(value.items())[:20]}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in list(value)[:10]]
    if isinstance(value, str):
        if name.lower() in _BULKY and len(value) > 40:
            return f"<{len(value)} characters>"
        value = _SECRET_VALUE.sub("[hidden]", value)
        return value if len(value) <= 160 else value[:157] + "..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(str(value), name)


def record(event: str, **fields) -> None:
    """Append one event. Never raises: a full disk mustn't stop the assistant."""
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event,
             **{k: redact(v, k) for k, v in fields.items()}}
    try:
        f = file()
        with _LOCK:
            if f.exists() and f.stat().st_size > _MAX_BYTES:
                f.replace(f.with_name("audit.old.log"))
            with open(f, "a", encoding="utf-8") as out:
                out.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent(n: int = 100) -> list[dict]:
    """The last n events, newest last."""
    try:
        lines = file().read_text(encoding="utf-8").splitlines()[-n:]
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out

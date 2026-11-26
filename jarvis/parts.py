"""Parts of the app you can turn off, the parts you downloaded, and the versions of what the app is made of.

A part that is off: its page or tabs are hidden, the AI is not given its tools (and they refuse if asked anyway), and whatever it
does by itself stops. Nothing of yours is deleted; turning it on again brings everything back.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# name: (title, what it is, its AI tools)
FEATURES: dict[str, tuple[str, str, frozenset[str]]] = {
    "studio": ("Studio", "Music, radio, screen recording and pictures", frozenset({"media", "images"})),
    "daily": ("Daily extras", "News, flashcards, fitness, travel, meetings and people (the clock stays)", frozenset({"news", "learn", "fitness", "travel", "meetings", "people"})),
    "email": ("Email", "Gmail on the Planner page", frozenset({"email"})),
    "documents": ("Documents", "Making, reading and searching Word, Excel, PowerPoint and PDF files", frozenset({"documents"})),
    "automations": ("Automations", "Several steps under one name, also at set times", frozenset({"automation"})),
    "agents": ("Agents", "Helpers the assistant hands a job to", frozenset({"delegate"})),
    "vault": ("Vault", "Passwords, cards and papers, encrypted", frozenset()),
    "devices": ("Phones, other PCs and the API", "Coming in from other devices and programs, and connections", frozenset({"connection", "other_pc"})),
}
CHANGED = None                                            # hud: tell the page, rebuild the AI


class PartsError(ValueError):
    """Something to tell the owner, in plain words."""


def off() -> list[str]:
    from . import schedule
    s = schedule.get_setting("parts_off")
    return [x for x in FEATURES if isinstance(s, list) and x in s]


def is_on(name: str) -> bool:
    return name not in off()


def tool_on(tool: str) -> bool:
    return not any(tool in FEATURES[x][2] for x in off())


def offered(defs: list[dict]) -> list[dict]:
    """The tools the AI is given."""
    gone = set().union(*(FEATURES[x][2] for x in off())) if off() else set()
    return [d for d in defs if d.get("name") not in gone]


def owner(tool: str) -> str:
    return next((FEATURES[x][0] for x in off() if tool in FEATURES[x][2]), "")


def set_on(name: Any, on: bool) -> list[str]:
    """Your switch."""
    from . import audit, schedule
    if not isinstance(name, str) or name not in FEATURES:
        raise PartsError("That isn't one of the parts.")
    now = [x for x in off() if x != name] + ([] if on else [name])
    schedule.set_setting("parts_off", now)
    audit.record("part_on" if on else "part_off", part=name)
    if name == "devices" and not on:
        from . import access, remote
        remote.stop()
        access.stop_pairing()
    if name == "devices" and on:
        from . import remote
        remote.start()
    if name == "email" and not on:
        from . import mail
        mail.close()
    if CHANGED:
        CHANGED()
    return off()


# ---------------- what you downloaded ----------------
def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else 0


def downloaded() -> list[dict]:
    from . import local_stt, local_tts, updates
    out = [{"id": f"stt:{n}", "name": f"Speech model {n.split('-')[0]}", "about": "Understanding speech on this PC", "size": _size(local_stt.model_file(n))} for n in local_stt.installed()]
    out += [{"id": f"voice:{v}", "name": f"Voice {v}", "about": "Speaking on this PC", "size": _size(local_tts._folder(v))} for v in local_tts.installed()]
    up = updates.folder()
    if up.is_dir() and any(up.iterdir()):
        out.append({"id": "updates", "name": "Downloaded Setup", "about": "For installing or going back", "size": _size(up)})
    return out


def remove(i: Any) -> None:
    """Your click: a downloaded part goes (it can be downloaded again)."""
    from . import audit, local_stt, local_tts, schedule, updates
    i = str(i)
    if i.startswith("stt:") and i[4:] in local_stt.installed():
        local_stt.model_file(i[4:]).unlink(missing_ok=True)
        if schedule.get_setting("local_stt_model") == i[4:]:
            schedule.set_setting("local_stt_model", None)
    elif i.startswith("voice:") and i[6:] in local_tts.installed():
        shutil.rmtree(local_tts._folder(i[6:]), ignore_errors=True)
    elif i == "updates":
        shutil.rmtree(updates.folder(), ignore_errors=True)
    else:
        raise PartsError("That isn't there any more.")
    audit.record("part_removed", part=i)


# ---------------- versions ----------------
def versions() -> list[dict]:
    """What the app is made of, and whether the pieces fit together."""
    import sys
    from importlib.metadata import PackageNotFoundError, version
    from . import __version__, install, local_ai, storage
    rows = [{"name": "Personal Assistant", "version": __version__, "ok": True}]
    with storage._LOCK:
        db = storage.conn().execute("PRAGMA user_version").fetchone()[0]
    rows.append({"name": "Database", "version": f"{db} of {len(storage.MIGRATIONS)}", "ok": db == len(storage.MIGRATIONS)})
    w = install.webview2()
    rows.append({"name": "Window (Edge WebView2)", "version": w or "missing", "ok": bool(w)})
    rows.append({"name": "Python", "version": sys.version.split()[0], "ok": True})
    import importlib
    for pkg, mod, name in (("pywhispercpp", "pywhispercpp", "Speech on this PC"), ("sherpa-onnx", "sherpa_onnx", "Voices on this PC"), ("cryptography", "cryptography", "Encryption"), ("google-genai", "google.genai", "Live calls")):
        try:
            v = version(pkg)
        except PackageNotFoundError:                      # (the installed app carries the code, not always its papers)
            try:
                v = str(getattr(importlib.import_module(mod), "__version__", "") or "included")
            except Exception:
                v = ""
        rows.append({"name": name, "version": v or "missing", "ok": bool(v)})
    known, running = local_ai.known()
    rows.append({"name": "Ollama (AI on this PC)", "version": "running" if running else "installed, not running" if known else "not installed", "ok": True})
    return rows


def page() -> dict:
    return {"features": [{"id": k, "name": t, "about": a, "on": is_on(k)} for k, (t, a, _) in FEATURES.items()], "downloaded": downloaded(), "versions": versions()}

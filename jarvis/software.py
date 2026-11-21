"""Windows software manager (Phase 5) through winget, which is free and built into Windows 10/11.

Looking is free: search, what's installed, which updates are waiting. Changing needs the user's OK every time
(tools.py asks): install, update, uninstall. Changes run in the background and report back when they finish, so
the assistant isn't stuck for minutes. Only the community "winget" source is used for installs (no Store account).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from typing import Callable

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{1,120}$")       # e.g. VideoLAN.VLC, Microsoft.VisualStudioCode
TIMEOUT_LOOK = 120
TIMEOUT_CHANGE = 1800
_BUSY = threading.Lock()                 # one install/update/uninstall at a time (winget doesn't like more)


def available() -> bool:
    return shutil.which("winget") is not None


def _run(args: list[str], timeout: int = TIMEOUT_LOOK) -> tuple[int, str]:
    if not available():
        raise RuntimeError("winget isn't on this PC. Get \"App Installer\" from the Microsoft Store to use it.")
    r = subprocess.run(["winget", *args, "--disable-interactivity"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def parse_table(text: str) -> list[dict]:
    """winget's text tables -> rows {name, id, version, available, match, source} (missing columns are '')."""
    lines = [ln.rstrip("\r") for ln in text.splitlines()]
    rows: list[dict] = []
    for i in range(1, len(lines)):
        if not re.fullmatch(r"-{10,}", lines[i].strip()):
            continue
        head = lines[i - 1].rstrip()
        cols = [(m.start(), m.group(0).lower()) for m in re.finditer(r"\S+", head)]
        if not cols or cols[0][1] != "name":
            continue
        for ln in lines[i + 1:]:
            if not ln.strip() or re.fullmatch(r"-{10,}", ln.strip()):
                break
            if ln.lstrip().startswith("<") or re.match(r"\d+ (upgrades?|packages?) ", ln.strip()):
                continue                       # "<additional entries truncated…>", "17 upgrades available."
            cells = {}
            for n, (start, key) in enumerate(cols):
                end = cols[n + 1][0] if n + 1 < len(cols) else None
                cells[key] = ln[start:end].strip() if len(ln) > start else ""
            if not cells.get("id") or cells["id"].startswith("<"):
                continue
            rows.append({"name": cells.get("name", ""), "id": cells["id"], "version": cells.get("version", ""),
                         "available": cells.get("available", ""), "match": cells.get("match", ""),
                         "source": cells.get("source", "")})
        break
    return rows


def search(query: str, count: int = 10) -> list[dict]:
    query = " ".join(str(query or "").split())[:80]
    if not query:
        raise ValueError("What should I look for?")
    _, out = _run(["search", "--query", query, "--source", "winget", "--count", str(max(1, min(count, 25)))])
    return parse_table(out)


def installed(query: str = "") -> list[dict]:
    args = ["list"] + (["--query", " ".join(query.split())[:80]] if query.strip() else [])
    _, out = _run(args)
    return parse_table(out)


def upgrades() -> list[dict]:
    _, out = _run(["upgrade", "--source", "winget"])
    return [r for r in parse_table(out) if r["available"]]


def describe(rows: list[dict], kind: str = "search") -> str:
    if not rows:
        return {"search": "Nothing found.", "installed": "No matching apps installed.",
                "upgrades": "Everything is up to date."}.get(kind, "Nothing.")
    if kind == "upgrades":
        return f"{len(rows)} update(s) available:\n" + "\n".join(
            f"- {r['name']} ({r['id']}): {r['version']} → {r['available']}" for r in rows)
    return "\n".join(f"- {r['name']} ({r['id']}) {r['version']}" + (f" [{r['match']}]" if r.get("match") else "") for r in rows)


def check_id(pkg_id: str) -> str:
    pkg_id = str(pkg_id or "").strip()
    if not ID_RE.fullmatch(pkg_id):
        raise ValueError(f"{pkg_id!r} doesn't look like a winget package id (e.g. VideoLAN.VLC). Search first.")
    return pkg_id


def _summary(code: int, out: str, verb: str, name: str) -> str:
    tail = [ln.strip() for ln in out.splitlines() if ln.strip() and not re.fullmatch(r"[\s\-\\|/█▒]+", ln.strip())]
    if code == 0:
        return f"{verb} {name}: done."
    last = tail[-1][:200] if tail else f"winget exit code {code}"
    if "No available upgrade" in out or "No applicable update" in out or "No newer package" in out:
        return f"{name} is already up to date."
    if "No package found" in out or "No installed package" in out:
        return f"{verb} {name}: winget couldn't find it ({last})."
    return f"{verb} {name} failed: {last}"


def change(action: str, pkg_id: str = "", on_done: Callable[[str], None] | None = None, name: str = "") -> str:
    """install / upgrade / uninstall one package, or upgrade_all, in the background. The caller has the OK already."""
    if action == "upgrade_all":
        args, label, verb = ["upgrade", "--all", "--source", "winget", "--silent", "--accept-package-agreements",
                             "--accept-source-agreements"], "all apps", "Updating"
    else:
        pkg_id = pkg_id if action == "uninstall" else check_id(pkg_id)
        label = name or pkg_id
        base = ["--id", pkg_id, "--exact", "--silent"]
        if action == "install":
            args, verb = ["install", *base, "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"], "Installing"
        elif action == "upgrade":
            args, verb = ["upgrade", *base, "--source", "winget", "--accept-package-agreements", "--accept-source-agreements"], "Updating"
        elif action == "uninstall":
            args, verb = ["uninstall", *base], "Removing"
        else:
            raise ValueError(f"Unknown action {action!r}.")
    if not _BUSY.acquire(blocking=False):
        return "Another install or update is still running; I'll do this one after it finishes. Ask me again in a minute."

    def work():
        try:
            code, out = _run(args, TIMEOUT_CHANGE)
            msg = _summary(code, out, verb, label)
        except subprocess.TimeoutExpired:
            msg = f"{verb} {label} is taking over 30 minutes; I stopped waiting (it may still finish)."
        except Exception as e:
            msg = f"{verb} {label} failed: {e}"
        finally:
            _BUSY.release()
        if on_done:
            on_done(msg)

    threading.Thread(target=work, daemon=True, name=f"winget-{action}").start()
    return f"{verb} {label} in the background (winget). I'll tell you when it's done."

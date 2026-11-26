"""New versions from GitHub Releases: looked for only when you press the button, or once a day if you turned that on.

What goes out: one request to GitHub's list of releases (nothing about you). A Setup is downloaded only on your click, only from
this app's own releases, and is used only when its SHA-256 equals both the one GitHub keeps for the file and the one in the
release's SHA256.txt, and its version is the one it says. Before it runs, a restore point is made. Setup itself then asks and
shows what it does; your settings, memories and keys stay.

Going back to an earlier version (1.31.5 or newer, which can put a backup back): the restore point made when you moved past it
is made ready, and that version's Setup runs; the older app puts its data back when it starts.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import ssl
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = "gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant"
SETUP = "Personal-Assistant-Setup.exe"
MAX_SETUP = 600 * 2**20
OLDEST_BACK = (1, 31, 5)                                 # the first version that puts a restore point back at its start
HOSTS = {"api.github.com", "github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"}
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"busy": "", "done": 0.0, "error": ""}


class UpdateError(ValueError):
    """Something to tell the owner, in plain words."""


def num(v: Any) -> tuple[int, ...]:
    m = re.fullmatch(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})", str(v or "").strip())
    if not m:
        raise UpdateError("That isn't a version number.")
    return tuple(int(x) for x in m.groups())


def _settings() -> dict:
    from . import schedule
    s = schedule.get_setting("updates")
    return s if isinstance(s, dict) else {}


def _set(**k: Any) -> None:
    from . import schedule
    schedule.set_setting("updates", {**_settings(), **k})


def folder() -> Path:
    from .local_stt import models_dir
    return models_dir().parent / "updates"


# ---------------- speaking with GitHub ----------------
def _get(url: str, most: int, accept: str = "application/vnd.github+json", hops: int = 4, sink=None) -> bytes:
    """HTTPS, certificate checked, only GitHub's own addresses (also where it hands a download on to)."""
    from . import __version__, netlog
    for _ in range(hops + 1):
        p = urlsplit(url)
        if p.scheme != "https" or p.hostname not in HOSTS or p.username or p.port not in (None, 443):
            raise UpdateError("That isn't one of GitHub's addresses.")
        if netlog.local_only():
            raise UpdateError("Local only is on (Privacy): nothing goes out.")
        c = http.client.HTTPSConnection(p.hostname, 443, timeout=30, context=ssl.create_default_context())
        try:
            c.request("GET", (p.path or "/") + (f"?{p.query}" if p.query else ""), headers={"User-Agent": f"PersonalAssistant/{__version__}", "Accept": accept})
            r = c.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                url = r.getheader("Location") or ""
                r.read(1000)
                continue
            if r.status != 200:
                raise UpdateError("GitHub is busy just now; try again in a while." if r.status in (403, 429) else f"GitHub answered {r.status}.")
            size = int(r.getheader("Content-Length") or 0)
            if size > most:
                raise UpdateError("That download is far bigger than it should be.")
            if sink is None:
                data = r.read(most + 1)
                if len(data) > most:
                    raise UpdateError("That answer is far bigger than it should be.")
                return data
            got = 0
            while block := r.read(2**20):
                got += len(block)
                if got > most:
                    raise UpdateError("That download is far bigger than it should be.")
                sink(block, got, size)
            return b""
        except (OSError, http.client.HTTPException) as e:
            raise UpdateError(f"GitHub couldn't be reached ({type(e).__name__}).") from None
        finally:
            c.close()
    raise UpdateError("GitHub sent it on too often.")


def releases() -> list[dict]:
    """This app's published versions, newest first (only those with a Setup)."""
    raw = _get(f"https://api.github.com/repos/{REPO}/releases?per_page=30", 4 * 2**20)
    try:
        items = json.loads(raw)
    except ValueError:
        raise UpdateError("GitHub's answer wasn't understood.") from None
    out = []
    for r in items if isinstance(items, list) else []:
        try:
            v = num(r.get("tag_name"))
        except UpdateError:
            continue
        if r.get("draft") or r.get("prerelease"):
            continue
        a = {x.get("name"): x for x in r.get("assets") or [] if isinstance(x, dict)}
        s = a.get(SETUP)
        if not s or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(s.get("digest"))) or "SHA256.txt" not in a:
            continue
        out.append({"version": ".".join(map(str, v)), "notes": str(r.get("body") or "")[:4000], "date": str(r.get("published_at") or "")[:10], "size": int(s.get("size") or 0),
                    "sha": s["digest"][7:], "url": f"https://github.com/{REPO}/releases/download/v{'.'.join(map(str, v))}/{SETUP}",
                    "sums": f"https://github.com/{REPO}/releases/download/v{'.'.join(map(str, v))}/SHA256.txt"})
    return sorted(out, key=lambda x: num(x["version"]), reverse=True)


def check() -> dict:
    """Your button, or once a day: is there a newer one?"""
    from . import __version__, audit
    with _LOCK:
        if _STATE["busy"]:
            raise UpdateError("It is busy already.")
        _STATE["busy"] = "Looking"
    try:
        rel = releases()
    finally:
        _STATE["busy"] = ""
    newer = [r for r in rel if num(r["version"]) > num(__version__)]
    back = [r for r in rel if OLDEST_BACK <= num(r["version"]) < num(__version__)][:6]
    _set(checked=datetime.now().isoformat(timespec="seconds"), latest=newer[0] if newer else None, back=back)
    audit.record("updates_checked", newest=newer[0]["version"] if newer else __version__)
    return status()


# ---------------- getting one ----------------
def _file(version: str) -> Path:
    return folder() / f"Personal-Assistant-Setup-{version}.exe"


def _known(version: str) -> dict:
    s = _settings()
    for r in [s.get("latest"), *(s.get("back") or [])]:
        if isinstance(r, dict) and r.get("version") == version:
            return r
    raise UpdateError("Look for versions first.")


def _file_version(p: Path) -> str:
    try:
        import win32api
        i = win32api.GetFileVersionInfo(str(p), "\\")
        ms, ls = i["FileVersionMS"], i["FileVersionLS"]
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}"
    except Exception:
        return ""


def verified(version: str) -> Path | None:
    """The downloaded Setup, if it is still exactly the one GitHub has for that version."""
    p = _file(version)
    if not p.is_file():
        return None
    r = _known(version)
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(2**20):
            h.update(b)
    return p if h.hexdigest() == r["sha"] and _file_version(p) == version else None


def download(version: Any) -> Path:
    """Your click. In the background with progress; checked twice before it counts."""
    from . import audit
    r = _known(str(version))
    if not 0 < r["size"] <= MAX_SETUP:
        raise UpdateError("That Setup has an odd size.")
    sums = _get(r["sums"], 10_000, accept="application/octet-stream").decode("utf-8", "replace")
    if not re.search(rf"(?m)^{r['sha']}\s+\*?{re.escape(SETUP)}\s*$", sums):
        raise UpdateError("The release's own list of checksums doesn't name this file. It isn't used.")
    folder().mkdir(parents=True, exist_ok=True)
    part = folder() / f"{SETUP}.{os.getpid()}.part"
    h = hashlib.sha256()
    try:
        with open(part, "wb") as f:
            def sink(block: bytes, got: int, size: int) -> None:
                f.write(block)
                h.update(block)
                _STATE["done"] = got / (size or r["size"])
            _get(r["url"], MAX_SETUP, accept="application/octet-stream", sink=sink)
        if h.hexdigest() != r["sha"]:
            raise UpdateError("The download isn't the file GitHub lists. It was thrown away.")
        if part.read_bytes()[:2] != b"MZ" or _file_version(part) != r["version"]:
            raise UpdateError("That Setup isn't the version it says. It was thrown away.")
        os.replace(part, _file(r["version"]))
    finally:
        part.unlink(missing_ok=True)
    for old in folder().glob("Personal-Assistant-Setup-*.exe"):           # only the newest download is kept
        if old != _file(r["version"]):
            old.unlink(missing_ok=True)
    audit.record("update_downloaded", version=r["version"])
    return _file(r["version"])


def start_download(version: Any) -> None:
    with _LOCK:
        if _STATE["busy"]:
            raise UpdateError("It is busy already.")
        _known(str(version))
        _STATE.update(busy=f"Downloading {version}", done=0.0, error="")

    def go() -> None:
        try:
            download(version)
        except UpdateError as e:
            _STATE["error"] = str(e)
        except OSError as e:
            _STATE["error"] = f"Windows said: {e.strerror or e}"
        finally:
            _STATE["busy"] = ""
    threading.Thread(target=go, name="update", daemon=True).start()


# ---------------- using it ----------------
def install(version: Any, run=None) -> str:
    """Your click: a restore point, then that version's Setup (it closes this app, asks, and keeps your things)."""
    from . import __version__, audit, backup
    from .config import FROZEN
    v = str(version)
    if not FROZEN:
        raise UpdateError("This copy runs from the source code: update it with git.")
    p = verified(v)
    if p is None:
        raise UpdateError("Download it first.")
    going_back = num(v) < num(__version__)
    if going_back:
        if num(v) < OLDEST_BACK:
            raise UpdateError("Versions before 1.31.5 can't take your data back.")
        point = next((b for b in backup.listing() if b["point"] and f"(from {v})" in b["why"]), None)
        if point:
            backup.prepare(point["path"], ["app", "settings"])                   # the older app puts it back at its start
    else:
        try:
            backup.make(point=True, why=f"before installing {v}")
        except backup.BackupError as e:
            raise UpdateError(f"No restore point could be made, so nothing was started: {e}") from None
    audit.record("update_started", version=v, back=going_back)
    (run or _run)(p)
    return f"Setup {v} is opening." + (" Your data from when you used it comes back at its first start." if going_back and point else " Your data stays as it is now." if going_back else "")


def _run(p: Path) -> None:
    import subprocess
    subprocess.Popen([str(p)], close_fds=True, env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})


# ---------------- by itself, and for the page ----------------
_NEXT = {"at": 0.0}


def auto() -> bool:
    return _settings().get("auto") is True


def set_auto(on: bool) -> None:
    from . import audit
    _set(auto=on is True)
    audit.record("updates_auto", on=on is True)


def tick(now: datetime, notify) -> int:
    from . import netlog
    if not auto() or netlog.local_only() or time.monotonic() < _NEXT["at"] or _STATE["busy"]:
        return 0
    _NEXT["at"] = time.monotonic() + 3600
    try:
        last = datetime.fromisoformat(str(_settings().get("checked")))
    except ValueError:
        last = datetime.min
    if now - last < timedelta(hours=23):
        return 0

    def go() -> None:
        try:
            s = check()
        except UpdateError as e:
            print(f"[updates] {e}")
            return
        new = s["latest"]
        if new and _settings().get("told") != new["version"]:
            _set(told=new["version"])
            notify(f"Version {new['version']} is ready: Settings › Updates.", "info")
    threading.Thread(target=go, name="updates", daemon=True).start()
    return 1


def status() -> dict:
    from . import __version__, backup
    from .config import FROZEN
    s = _settings()
    have = {b["why"] for b in backup.listing() if b["point"]}
    back = [{**{k: r[k] for k in ("version", "date", "size")}, "data": any(f"(from {r['version']})" in w for w in have)} for r in s.get("back") or [] if isinstance(r, dict)]
    latest = s.get("latest") if isinstance(s.get("latest"), dict) and num(s["latest"]["version"]) > num(__version__) else None
    ready = []
    for v in [latest["version"]] if latest else []:
        try:
            ready += [v] if verified(v) else []
        except (UpdateError, OSError):
            pass
    for b in back:
        try:
            if verified(b["version"]):
                ready.append(b["version"])
        except (UpdateError, OSError):
            pass
    return {"version": __version__, "auto": auto(), "checked": str(s.get("checked") or ""), "latest": latest, "back": back, "ready": ready, "busy": _STATE["busy"], "done": round(_STATE["done"], 3),
            "error": _STATE["error"], "installed": FROZEN}

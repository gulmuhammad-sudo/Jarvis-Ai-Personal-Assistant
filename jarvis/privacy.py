"""Privacy: when the app used the microphone or looked at the screen, what Windows itself noted about every
program, what is kept on this PC, and how long.

Everything here is for the owner's own page. The AI has no tool for it.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

KEEP_CHOICES = {"conversations": (0, 7, 30, 90, 365), "screenshots": (0, 7, 30, 90), "record": (0, 30, 90, 365), "logs": (7, 30, 90)}
MERGE = 120                                            # the same use again within two minutes is one use
SENSORS = ("mic", "screen", "clipboard")
CHANGED: Callable[[], None] | None = None              # the page's small microphone sign
_LOCK = threading.RLock()
_ACTIVE: dict[int, dict] = {}                          # going on now
_LAST: dict[tuple[str, str], tuple[int, float]] = {}   # (what, why) -> (its row, when it ended)
_NEXT = 0
_STARTED = False


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _write(sql: str, args: tuple) -> int | None:
    """Never in the way of what it writes down."""
    from . import storage
    try:
        with storage._LOCK:
            c = storage.conn()
            with c:
                return c.execute(sql, args).lastrowid
    except sqlite3.Error as e:
        print(f"[privacy] couldn't note the use: {e}")
        return None


def _tell() -> None:
    if CHANGED:
        try:
            CHANGED()
        except Exception:
            pass


def logging() -> bool:
    from . import schedule
    return schedule.get_setting("sensor_log", True) is not False


# ---------------- microphone and screen ----------------
def begin(what: str, why: str, show: bool = True) -> int:
    """Something starts to listen or look. Returns a number for end()."""
    global _NEXT
    row = None
    if logging():
        with _LOCK:
            old = _LAST.get((what, why))
        if old and time.time() - old[1] < MERGE:
            row = old[0]
        else:
            row = _write("INSERT INTO sensor_log(what, why, start, end) VALUES (?, ?, ?, ?)", (what, why, _now(), _now()))
    with _LOCK:
        _NEXT += 1
        n = _NEXT
        _ACTIVE[n] = {"what": what, "why": why, "since": time.time(), "row": row, "show": show}
    _tell()
    return n


def end(n: int | None) -> None:
    with _LOCK:
        a = _ACTIVE.pop(n or 0, None)
    if not a:
        return
    if a["row"]:
        _write("UPDATE sensor_log SET end = ? WHERE id = ?", (_now(), a["row"]))
        with _LOCK:
            _LAST[(a["what"], a["why"])] = (a["row"], time.time())
    _tell()


@contextmanager
def using(what: str, why: str, show: bool = True):
    n = begin(what, why, show)
    try:
        yield
    finally:
        end(n)


def look(what: str, why: str) -> None:
    """One look (a screenshot, the clipboard)."""
    if logging():
        _write("INSERT INTO sensor_log(what, why, start, end) VALUES (?, ?, ?, ?)", (what, why, _now(), _now()))


def active() -> list[dict]:
    with _LOCK:
        return [{"what": a["what"], "why": a["why"], "seconds": int(time.time() - a["since"])} for a in _ACTIVE.values() if a["show"]]


def _beat() -> None:
    """Uses that go on are written with the time so far (a crash loses half a minute at most)."""
    with _LOCK:
        rows = [a["row"] for a in _ACTIVE.values() if a["row"]]
    for r in rows:
        _write("UPDATE sensor_log SET end = ? WHERE id = ?", (_now(), r))


def seconds(start: str, stop: str) -> int:
    try:
        return max(0, int((datetime.fromisoformat(stop) - datetime.fromisoformat(start)).total_seconds()))
    except ValueError:
        return 0


def uses(days: int = 7, what: str = "") -> list[dict]:
    """What the app used, newest first."""
    from . import storage
    since = (date.today() - timedelta(days=max(0, min(90, int(days)) - 1))).isoformat()
    with storage._LOCK:
        rows = storage.conn().execute("SELECT id, what, why, start, end FROM sensor_log WHERE start >= ?" + (" AND what = ?" if what in SENSORS else "") + " ORDER BY start DESC, id DESC LIMIT 400",
                                      (since, what) if what in SENSORS else (since,)).fetchall()
    with _LOCK:
        now = {a["row"] for a in _ACTIVE.values()}
    return [{"id": i, "what": w, "why": why, "start": start, "end": stop, "seconds": seconds(start, stop), "now": i in now} for i, w, why, start, stop in rows]


def clear_uses() -> int:
    from . import storage
    with storage._LOCK:
        c = storage.conn()
        with c:
            n = c.execute("DELETE FROM sensor_log").rowcount
    with _LOCK:
        _LAST.clear()
        for a in _ACTIVE.values():
            a["row"] = None
    return n


# ---------------- what Windows noted ----------------
_STORE = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore"
WINDOWS = {"mic": ("microphone",), "camera": ("webcam",), "location": ("location",), "screen": ("graphicsCaptureProgrammatic", "graphicsCaptureWithoutBorder")}
PAGES = {"mic": "ms-settings:privacy-microphone", "camera": "ms-settings:privacy-webcam", "location": "ms-settings:privacy-location", "screen": "ms-settings:privacy-graphicscaptureprogrammatic"}


def _when(filetime: Any) -> str:
    """Windows' time (100 ns since 1601, UTC) as local time; "" for none."""
    try:
        n = int(filetime)
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(n // 10_000_000 - 11_644_473_600)) if n > 0 else ""
    except (ValueError, TypeError, OverflowError, OSError):
        return ""


def _app(key: str, packaged: bool) -> tuple[str, str]:
    """(name to show, program path) of one entry."""
    if packaged:
        name = key.split("_", 1)[0]
        return name.split(".", 1)[-1].replace(".", " ") or key, ""            # (the part before the first dot is the maker)
    path = key.replace("#", "\\")
    return os.path.splitext(os.path.basename(path))[0] or path, path


def _entries(store: str):
    """(key, packaged, values) of Windows' list, and whether it is allowed at all (first item)."""
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for sub, packaged in (("", True), ("\\NonPackaged", False)):
            try:
                k = winreg.OpenKey(hive, f"{_STORE}\\{store}{sub}")
            except OSError:
                continue
            with k:
                for i in range(min(400, winreg.QueryInfoKey(k)[0])):
                    try:
                        key = winreg.EnumKey(k, i)
                        if key == "NonPackaged":
                            continue
                        with winreg.OpenKey(k, key) as e:
                            vals = {}
                            for v in ("LastUsedTimeStart", "LastUsedTimeStop", "Value"):
                                try:
                                    vals[v] = winreg.QueryValueEx(e, v)[0]
                                except OSError:
                                    pass
                    except OSError:
                        continue
                    yield key, packaged, vals


def _allowed(store: str) -> bool | None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{_STORE}\\{store}") as k:
            return str(winreg.QueryValueEx(k, "Value")[0]) == "Allow"
    except OSError:
        return None


def windows_uses(what: str, running: set[str] | None = None) -> dict:
    """Which programs used it, going by Windows' own list (read only)."""
    if what not in WINDOWS:
        raise ValueError("That isn't one of the lists.")
    if running is None:
        try:
            import psutil
            running = {(p.info["name"] or "").lower() for p in psutil.process_iter(["name"])}
        except Exception:
            running = set()
    apps: dict[str, dict] = {}
    for store in WINDOWS[what]:
        for key, packaged, vals in _entries(store):
            name, path = _app(key, packaged)
            start, stop = _when(vals.get("LastUsedTimeStart")), _when(vals.get("LastUsedTimeStop"))
            now = bool(start and not stop and (packaged or os.path.basename(path).lower() in running))     # (a program that crashed never says it stopped)
            row = {"name": name, "path": path, "start": start, "end": stop, "now": now, "allowed": vals.get("Value") != "Deny"}
            have = apps.get((path or key).lower())
            if not have or row["start"] > have["start"]:
                apps[(path or key).lower()] = row
    used = sorted((r for r in apps.values() if r["start"]), key=lambda r: r["start"], reverse=True)
    used.sort(key=lambda r: not r["now"])
    return {"what": what, "allowed": _allowed(WINDOWS[what][0]), "apps": used[:40], "never": len(apps) - len(used)}


# ---------------- what is kept on this PC ----------------
def _size(p: Path, depth: int = 6) -> tuple[int, int]:
    """(files, bytes) in a folder or of one file."""
    try:
        if p.is_file():
            return 1, p.stat().st_size
        n = b = 0
        with os.scandir(p) as it:
            for e in it:
                try:
                    if e.is_symlink() or e.is_junction():
                        continue
                    if e.is_dir():
                        if depth:
                            k, s = _size(Path(e.path), depth - 1)
                            n, b = n + k, b + s
                    else:
                        n, b = n + 1, b + e.stat().st_size
                except OSError:
                    continue
        return n, b
    except OSError:
        return 0, 0


def _home(name: str) -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / name / "Personal Assistant"


def _voice_dir() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "voice_debug"


def _bytes(files) -> int:
    return sum(_size(f)[1] for f in files)


_COUNTED = ("memories", "skills", "automations", "agents", "tasks", "calendar", "goals", "habits", "journal", "money", "cards", "fit_log", "workouts", "trips", "meetings",
            "people", "docs", "media_files", "news_saved", "net_log", "sensor_log")


def kept() -> dict:
    """Every kind of thing the app keeps: how many, how big, where to see it, and whether it can be cleared here."""
    from . import audit, keystore, local_stt, mail, netlog, schedule, storage
    from .config import DATA_DIR, NOTES_DIR, SCREENSHOT_DIR
    with storage._LOCK:
        c = storage.conn()
        events, text = c.execute("SELECT COUNT(*), COALESCE(SUM(LENGTH(data)), 0) FROM events").fetchone()
        n = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _COUNTED}
    record = [audit.file(), audit.file().with_name("audit.old.log")]
    logs = [f for f in (DATA_DIR / "jarvis.log", DATA_DIR / "jarvis.old.log") if f.exists()]
    db = _bytes(storage.path().parent.glob("assistant.db*"))
    items: list[dict] = []

    def add(i: str, name: str, count: int, size: int = 0, go: str = "", clear: bool = False, note: str = "") -> None:
        items.append({"id": i, "name": name, "n": count, "bytes": size, "go": go, "clear": clear, "note": note})
    add("conversations", "Conversations and activity", events, text, "conv", True, "What you said, the answers, the Activity list.")
    add("record", "Record of actions and approvals", sum(len(audit._lines(f)) for f in record), _bytes(record), "", True,
        "Every action and every question. Keys, passwords and file contents are never in it. Clearing it leaves one line that says so.")
    add("net", "List of what goes out", n["net_log"], 0, "", True, "Days and addresses, never what was said.")
    add("uses", "List of microphone and screen uses", n["sensor_log"], 0, "", True)
    add("voice", "Recordings of your voice", sum(1 for _ in _voice_dir().glob("*.wav")), _size(_voice_dir())[1], "", True, "The last five, for finding microphone problems. Off unless you turn it on.")
    add("screenshots", "Pictures of the screen it looked at", *_size(SCREENSHOT_DIR), "", True, "Each time the assistant looked at your screen. Clearing moves them to the Recycle Bin.")
    add("log", "Log of the program", sum(_bytes([f]) > 0 for f in logs), _bytes(logs), "", True, "For finding faults. Short pieces of what was heard can be in it.")
    add("memories", "Memories about you", n["memories"], 0, "memory")
    add("notes", "Notes", *_size(NOTES_DIR), "planner")
    add("planner", "Tasks, calendar, goals, habits", n["tasks"] + n["calendar"] + n["goals"] + n["habits"], 0, "planner")
    add("journal", "Journal", n["journal"], 0, "planner")
    add("money", "Money", n["money"], 0, "planner")
    add("health", "Fitness", n["fit_log"] + n["workouts"], 0, "daily")
    add("cards", "Flashcards", n["cards"], 0, "daily")
    add("meetings", "Meetings", n["meetings"], 0, "daily")
    add("people", "People", n["people"], 0, "daily")
    add("trips", "Trips and saved news", n["trips"] + n["news_saved"], 0, "daily")
    add("own", "Your skills, automations and agents", n["skills"] + n["automations"] + n["agents"], 0, "tools")
    add("docs", "Word index of your documents", n["docs"], 0, "tools", note="Made from the folders you chose; your files stay where they are.")
    add("media", "List of your music and videos", n["media_files"], 0, "studio", note="Only names; your files stay where they are.")
    add("recordings", "Screen recordings", *_size(_home("Videos")), "studio", note="In Videos › Personal Assistant.")
    add("pictures", "Pictures you made or edited", *_size(_home("Pictures")), "studio", note="In Pictures › Personal Assistant.")
    add("keys", "AI keys", len(keystore.load()), 0, "models", note="Locked with your Windows account. Only how many is known here.")
    add("mail", "Gmail sign-in", 1 if mail._file().exists() else 0, 0, "planner", note="Locked with your Windows account.")
    add("models", "Voices and speech models", *_size(local_stt.models_dir()), "settings")
    web = _size(DATA_DIR / "webview", 12)[1]
    add("web", "The window's own storage", 1 if web else 0, web, note="Its cache.")
    return {"items": items, "folder": str(DATA_DIR), "database": db, "total": sum(i["bytes"] for i in items if i["id"] != "conversations") + db, "keep": keeping(), "choices": KEEP_CHOICES,
            "voice_debug": schedule.get_setting("voice_debug") is True, "history": schedule.get_setting("keep_history", True) is not False, "net_on": netlog.on(), "uses_on": logging()}


def clear(what: str) -> int:
    """Clear one kind (the owner's button). Returns how many things went."""
    from . import audit, netlog, storage
    from .config import DATA_DIR, SCREENSHOT_DIR
    if what == "conversations":
        n = storage.clear_events()
    elif what == "record":
        return audit.clear()                             # (leaves its own line)
    elif what == "net":
        n = netlog.clear()
    elif what == "uses":
        n = clear_uses()
    elif what == "voice":
        files = [f for f in _voice_dir().glob("*") if f.suffix.lower() in (".wav", ".json")] if _voice_dir().is_dir() else []
        for f in files:
            f.unlink(missing_ok=True)
        n = sum(f.suffix.lower() == ".wav" for f in files)
    elif what == "screenshots":
        n = _recycle_all([f for f in SCREENSHOT_DIR.glob("*") if f.is_file()])
    elif what == "log":
        n = 0
        for f in (DATA_DIR / "jarvis.old.log", DATA_DIR / "jarvis.log"):
            if f.exists():
                n += 1
                if f.name == "jarvis.old.log":
                    f.unlink(missing_ok=True)
                else:
                    with open(f, "r+b") as h:            # (the app has it open for adding: it just goes on at the start)
                        h.truncate(0)
    else:
        raise ValueError("That can't be cleared here.")
    audit.record("cleared", what=what, things=n)
    return n


def _recycle_all(files: list[Path]) -> int:
    """To the Recycle Bin, sixty at a time."""
    from .tools import _ps, _ps_quote
    files = files[:3000]
    for i in range(0, len(files), 60):
        _ps("Add-Type -AssemblyName Microsoft.VisualBasic; foreach ($f in @(" + ",".join(f"'{_ps_quote(f)}'" for f in files[i:i + 60]) + ")) { try { "
            "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($f, 'OnlyErrorDialogs', 'SendToRecycleBin') } catch {} }", timeout=120)
    return sum(not f.exists() for f in files)


# ---------------- how long ----------------
def _key(k: str) -> str:
    return "net_log_days" if k == "logs" else f"keep_days_{k}"


def keeping() -> dict:
    from . import schedule
    out = {}
    for k, choices in KEEP_CHOICES.items():
        v = schedule.get_setting(_key(k))
        out[k] = v if v in choices and not isinstance(v, bool) else (30 if k == "logs" else 0)
    return out


def set_keeping(d: dict) -> dict:
    from . import audit, schedule
    new = {k: d[k] for k in KEEP_CHOICES if k in d}
    for k, v in new.items():
        if isinstance(v, bool) or not isinstance(v, int) or v not in KEEP_CHOICES[k]:
            raise ValueError("Choose one of the times in the list.")
    for k, v in new.items():
        schedule.set_setting(_key(k), v)
        audit.record("keeping_changed", what=k, days=v)
    return keeping()


def tidy(today: date | None = None) -> dict:
    """Once a day: what is older than you chose goes. Nothing is cleared unless you chose a time (the two small lists: 30 days)."""
    from . import audit, netlog, storage
    from .config import SCREENSHOT_DIR
    today, keep = today or date.today(), keeping()
    out: dict[str, int] = {}

    def since(days: int) -> str:
        return (today - timedelta(days=days)).isoformat()
    with storage._LOCK:
        c = storage.conn()
        with c:
            out["uses"] = c.execute("DELETE FROM sensor_log WHERE start < ?", (since(keep["logs"]),)).rowcount
            if keep["conversations"]:
                out["conversations"] = c.execute("DELETE FROM events WHERE at < ?", (since(keep["conversations"]),)).rowcount
    out["net"] = netlog.tidy(today)
    if keep["record"]:
        out["record"] = audit.drop_before(since(keep["record"]))
    if keep["screenshots"]:
        limit = time.mktime((today - timedelta(days=keep["screenshots"])).timetuple())
        out["screenshots"] = _recycle_all([f for f in SCREENSHOT_DIR.glob("*") if f.is_file() and f.stat().st_mtime < limit])
    if any(out.get(k) for k in ("conversations", "record", "screenshots")):
        audit.record("old_things_cleared", **{k: v for k, v in out.items() if v and k not in ("net", "uses")})
    return out


# ---------------- in the background ----------------
def start() -> None:
    """Writes the counts every few seconds and tidies once a day."""
    global _STARTED
    if _STARTED:
        return
    _STARTED = True

    def loop() -> None:
        from . import netlog, schedule
        n = 0
        while True:
            time.sleep(10)
            n += 1
            try:
                netlog.flush()
                if n % 3 == 0:
                    _beat()
                if n % 6 == 0 and schedule.get_setting("tidied") != date.today().isoformat():
                    tidy()
                    schedule.set_setting("tidied", date.today().isoformat())
            except Exception as e:
                print(f"[privacy] {type(e).__name__}: {e}")
    threading.Thread(target=loop, name="privacy", daemon=True).start()

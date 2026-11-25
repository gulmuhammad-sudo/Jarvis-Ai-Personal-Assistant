"""Health: the app looks at itself, and repairs what can be repaired.

check() looks (nothing is changed, nothing goes online); each finding says in plain words what it is and, where something
can be done, which repair() helps. Repairs are only done by the owner's click; those that touch your data make a restore
point first. The report holds no names, keys or texts.

started()/ended() notice a run that didn't end by itself (a crash), leaving out Windows shutting down.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

OK, INFO, WARN, BAD = "ok", "info", "warn", "bad"
_BEAT = {"on": False}


class CareError(ValueError):
    """Something to tell the owner, in plain words."""


def _data() -> Path:
    from .config import DATA_DIR
    return DATA_DIR


# ---------------- a run that didn't end by itself ----------------
def _running() -> Path:
    return _data() / "running.json"


def started() -> str:
    """At the start. Returns "crash", "off" (the PC was shut down meanwhile) or "" (it ended properly)."""
    from . import __version__, audit, schedule
    was = ""
    try:
        r = json.loads(_running().read_text(encoding="utf-8"))
        beat = float(r["beat"])
        import psutil
        since = max([psutil.boot_time(), *(float(u.started or 0) for u in psutil.users())])      # (with Windows' fast startup only the sign-in is new)
        was = "off" if beat < since else "" if r.get("app") != __version__ else "crash"             # (Setup closes the app that runs)
        if was == "crash":
            old = schedule.get_setting("crashes")
            schedule.set_setting("crashes", [*(old if isinstance(old, list) else []), datetime.fromtimestamp(beat).isoformat(timespec="seconds")][-20:])
            audit.record("ended_unexpectedly", last_seen=datetime.fromtimestamp(beat).isoformat(timespec="seconds"))
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        was = was if was else ""
    _write_beat()
    if not _BEAT["on"]:
        _BEAT["on"] = True

        def loop() -> None:
            while _BEAT["on"]:
                time.sleep(60)
                if _BEAT["on"]:
                    _write_beat()
        threading.Thread(target=loop, name="beat", daemon=True).start()
    return was


def _write_beat() -> None:
    from . import __version__
    try:
        tmp = _running().with_name("running.json.tmp")
        tmp.write_text(json.dumps({"pid": os.getpid(), "beat": time.time(), "app": __version__}), encoding="utf-8")
        os.replace(tmp, _running())
    except OSError:
        pass


def ended() -> None:
    """The app ends by itself (quit, restart)."""
    _BEAT["on"] = False
    try:
        _running().unlink(missing_ok=True)
    except OSError:
        pass


def crashes(days: int = 7) -> list[str]:
    from . import schedule
    since = (datetime.now() - timedelta(days=days)).isoformat()
    c = schedule.get_setting("crashes")
    return [x for x in c if isinstance(x, str) and x[:2] == "20" and x >= since] if isinstance(c, list) else []


# ---------------- looking ----------------
def _row(i: str, name: str, state: str, detail: str, fix: str = "", go: str = "") -> dict:
    return {"id": i, "name": name, "state": state, "detail": detail, "fix": fix, "go": go}


def _size(n: float) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB" if n >= 2**20 else f"{n / 1024:.0f} KB"


def _app(hub: Any) -> dict:
    from . import __version__
    from .config import FROZEN
    import psutil
    p = psutil.Process()
    mem = p.memory_info().rss
    return _row("app", "The app", OK, f"Version {__version__}{'' if FROZEN else ' (from the source code)'}, running {_since(p.create_time())}, {_size(mem)} of memory, {p.num_threads()} threads")


def _since(t: float) -> str:
    s = int(time.time() - t)
    return f"for {s // 86400} d {s % 86400 // 3600} h" if s >= 86400 else f"for {s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"for {s // 60} min"


def _windows(hub: Any) -> dict:
    from . import install
    v = sys.getwindowsversion()
    w = install.webview2()
    name = f"Windows {'11' if v.build >= 22000 else '10'} (build {v.build})"
    if v.build < install.MIN_WINDOWS:
        return _row("windows", "Windows", WARN, f"{name}: the app needs Windows 10 version 1809 or newer")
    return _row("windows", "Windows", OK if w else BAD, f"{name}, WebView2 {w}" if w else f"{name}; Microsoft Edge WebView2 is missing (it draws the window)", go="" if w else "ms-settings:windowsupdate")


def _crashed(hub: Any) -> dict:
    c = crashes()
    return _row("crashes", "Ended unexpectedly", OK if not c else WARN, "Not once in the last 7 days" if not c else f"{len(c)} time{'' if len(c) == 1 else 's'} in the last 7 days, last {c[-1].replace('T', ' ')[:16]}")


def _disk(hub: Any) -> dict:
    t = shutil.disk_usage(_data())
    free = t.free
    return _row("disk", "Free space", BAD if free < 2**30 else WARN if free < 5 * 2**30 else OK, f"{_size(free)} free of {_size(t.total)} on {_data().anchor}" + (": very little. Empty the Recycle Bin or remove big files" if free < 2**30 else ": getting little" if free < 5 * 2**30 else ""),
                go="ms-settings:storagesense" if free < 5 * 2**30 else "")


def _memory(hub: Any) -> dict:
    import psutil
    m = psutil.virtual_memory()
    return _row("memory", "The PC's memory", WARN if m.percent >= 92 else OK, f"{m.percent:.0f}% of {_size(m.total)} in use" + (": close a few programs or browser tabs" if m.percent >= 92 else ""))


def _database(hub: Any) -> dict:
    from . import storage
    p = storage.path()
    try:
        with storage._LOCK:
            c = storage.conn()
            quick = c.execute("PRAGMA quick_check").fetchone()[0]
            version = c.execute("PRAGMA user_version").fetchone()[0]
            n = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    except sqlite3.Error as e:
        return _row("database", "Database", BAD, f"It can't be read ({type(e).__name__}): everything the app keeps is in it. Repair it, or put a backup back", "database")
    if quick != "ok":
        return _row("database", "Database", BAD, "It is damaged. Repair it, or put a backup back (Backup)", "database")
    if version != len(storage.MIGRATIONS):
        return _row("database", "Database", BAD, f"It is of version {version}, the app needs {len(storage.MIGRATIONS)}", "database")
    size = p.stat().st_size if p.exists() else 0
    return _row("database", "Database", OK, f"Whole, {_size(size)}, {n} things in the history")


JSONS = ("settings.json", "profile.json", "alarms.json", "location.json")


def _files(hub: Any) -> dict:
    bad, left = broken_files(), leftovers()
    try:
        t = _data() / f".w{os.getpid()}"
        t.write_bytes(b"")
        t.unlink()
    except OSError:
        return _row("files", "The app's folder", BAD, f"The app can't write into {_data()}")
    if bad:
        return _row("files", "The app's files", BAD, f"{', '.join(p.name for p in bad)} can't be read (begun again, or put back from a backup)", "files")
    return _row("files", "The app's files", INFO if left else OK, f"{len(left)} leftover file{'' if len(left) == 1 else 's'} of interrupted work" if left else "All readable", "files" if left else "")


def broken_files() -> list[Path]:
    out = []
    for n in JSONS:
        p = _data() / n
        if p.is_file():
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                out.append(p)
    return out


def leftovers() -> list[Path]:
    """Files of work that was cut short, older than a day."""
    old = time.time() - 86400
    out = []
    for p in [*_data().glob("*.tmp"), *_data().glob("*.part"), *(_data() / "notes").glob("*.tmp"), _data() / "restore.tmp", _data() / "restore.before", _data() / "backup.tmp"]:
        try:
            if p.exists() and p.stat().st_mtime < old:
                out.append(p)
        except OSError:
            pass
    return out


def _ais(hub: Any) -> list[dict]:
    from .providers import provider_status
    rows = provider_status(getattr(hub, "brain", None))
    good = [r for r in rows if r["status"] in ("active", "connected", "limited")]
    limited = [r for r in rows if r["status"] == "limited"]
    down = [r for r in rows if r["status"] == "offline" and r["detail"] not in ("not available", "Ollama isn't running")]
    if not good:
        return [_row("ai", "AI", BAD, "No AI can answer. Add a free key (Settings › Run setup › AI keys), or install Ollama", "ai", "models")]
    text = ", ".join(r["label"] for r in good) + " ready"
    if limited:
        text += "; at its limit for now: " + ", ".join(r["label"] for r in limited)
    if down:
        text += "; out: " + ", ".join(f"{r['label']} ({_short(r['detail'])})" for r in down)
    return [_row("ai", "AI", WARN if down or len(limited) == len(good) else OK, text, "ai" if down else "", "models")]


def _short(t: Any) -> str:
    from . import audit
    return re.sub(r"https?://\S+", "…", str(audit.redact(str(t))))[:90]


def _net(hub: Any) -> dict:
    from . import netlog
    if netlog.local_only():
        return _row("net", "Internet", INFO, "Local only is on (Privacy): nothing goes online", go="privacy")
    import socket
    up = False
    for host in ("1.1.1.1", "8.8.8.8"):
        try:
            socket.create_connection((host, 53), timeout=1.5).close()
            up = True
            break
        except OSError:
            pass
    return _row("net", "Internet", OK if up else WARN, "Connected" if up else "No connection: only what works on this PC is available", "" if up else "dns")


def _mic(hub: Any) -> dict:
    from . import hud
    r = hud.recorder
    if r is None:
        return _row("mic", "Microphone", INFO, "Not used here" if os.environ.get("JARVIS_NO_MIC") == "1" else "The app can't reach the sound system; the page's own microphone is used", "" if os.environ.get("JARVIS_NO_MIC") == "1" else "mic")
    try:
        from . import privacy
        if privacy._allowed("microphone") is False:
            return _row("mic", "Microphone", BAD, "Windows doesn't let programs use it", go="ms-settings:privacy-microphone")
    except Exception:
        pass
    dev = r._chosen
    if not dev:
        return _row("mic", "Microphone", BAD, "None was found. Plug one in, then look again", "mic")
    s = hub.mic_status() if hub else {}
    if s.get("mic_muted"):
        return _row("mic", "Microphone", WARN, f"{dev['name']} is muted in Windows", go="unmute")
    lv = s.get("mic_level")
    return _row("mic", "Microphone", WARN if lv is not None and lv < 40 else OK, f"{dev['name']}" + (f", level {lv}%" if lv is not None else "") + (": low, press Boost in Settings › Voice & Mic" if lv is not None and lv < 40 else ""), "", "settings")


def _speaker(hub: Any) -> dict:
    try:
        import sounddevice as sd
        out = sd.query_devices(kind="output")["name"]
        return _row("speaker", "Speakers", OK, str(out)[:60])
    except Exception:
        return _row("speaker", "Speakers", WARN, "No sound output was found", go="ms-settings:sound")


def _hearing(hub: Any) -> dict:
    from . import local_stt, stt
    e = stt.engines()
    names = {"whisper": "Whisper (Groq)", "gemini": "Gemini", "local": "this PC (offline)"}
    off = local_stt.ready()
    if not e:
        return _row("stt", "Understanding speech", WARN, "Only Windows' own recogniser (less exact). Add a free Groq key, or download the offline model", go="settings")
    return _row("stt", "Understanding speech", OK, ", then ".join(names.get(x, x) for x in e) + ("" if off else "; nothing offline yet"))


def _voice(hub: Any) -> dict:
    from . import local_tts, tts
    have = local_tts.installed()
    if not tts.available() and not have:
        return _row("tts", "Voice", WARN, "Only Windows' own voice", go="settings")
    return _row("tts", "Voice", OK, ("Online voices" if tts.available() else "") + (f"{', ' if tts.available() else ''}{len(have)} on this PC" if have else "; none on this PC (offline it uses Windows' voice)"))


def _live(hub: Any) -> dict:
    from . import live
    if live.genai is None:
        return _row("live", "Live calls", BAD, "A part of the app for them is missing: install the app again")
    if not os.environ.get("GEMINI_API_KEY"):
        return _row("live", "Live calls", INFO, "Need a free Gemini key", go="models")
    errs = [t for t in getattr(hub, "_live_errors", []) if time.time() - t < 3600]
    return _row("live", "Live calls", WARN if len(errs) >= 2 else OK, f"{len(errs)} ended with a fault in the last hour" if errs else "Ready")


def _vault(hub: Any) -> dict:
    from . import vault
    try:
        key = b"k" * 32
        if vault._unseal(key, vault._seal(key, b"test", "x"), "x") != b"test":
            raise ValueError
    except Exception as e:
        return _row("vault", "Vault", BAD, f"Encryption doesn't work here ({type(e).__name__}): install the app again")
    if not vault.exists():
        return _row("vault", "Vault", INFO, "None yet", go="vault")
    s = vault.status()
    return _row("vault", "Vault", BAD if s["damaged"] else OK, s["damaged"] or ("Whole, " + ("open" if s["open"] else "locked")), go="vault")


def _hello(hub: Any) -> dict:
    from . import hello
    return _row("hello", "Windows Hello", OK if hello.ready() else INFO, "Set up" if hello.ready() else "Not set up on this PC (or not asked yet)")


def _start(hub: Any) -> dict:
    from . import install, schedule
    from .config import FROZEN
    want = schedule.get_setting("start_with_windows", True) is not False
    if not FROZEN:
        return _row("start", "Start with Windows", INFO, "Only the installed app")
    there = install.startup_shortcut().exists()
    return _row("start", "Start with Windows", OK if want == there else WARN, ("On" if want else "Off") if want == there else "The setting says on, but the shortcut is gone" if want else "The setting says off, but the shortcut is there", "" if want == there else "startup")


def _remote(hub: Any) -> dict:
    from . import access, remote
    s, n = remote.status(), len(access.devices())
    if not s["on"]:
        return _row("remote", "Phones and other PCs", INFO, "Off: nothing can come in", go="devices")
    if s["local_only"]:
        return _row("remote", "Phones and other PCs", INFO, "Held back by Local only", go="devices")
    if not s["running"]:
        return _row("remote", "Phones and other PCs", WARN, s["error"] or "It isn't running", go="devices")
    return _row("remote", "Phones and other PCs", OK if s["addresses"] else WARN, f"Open in your home network, {n} device{'' if n == 1 else 's'}" if s["addresses"] else "On, but this PC isn't in a network", go="devices")


def _parts(hub: Any) -> dict:
    names = {t.name for t in threading.enumerate()}
    need = {"scheduler": "reminders", "clock": "timers", "privacy": "lists", "lock-watch": "lock"}
    gone = [v for k, v in need.items() if k not in names]
    return _row("parts", "Parts at work", OK if not gone else WARN, "Reminders, timers, lists and lock are running" if not gone else f"Not running: {', '.join(gone)}. Start the app again", "" if not gone else "restart")


def _errors(hub: Any) -> dict:
    e = log_errors()
    n = sum(x["n"] for x in e)
    return _row("errors", "Faults in the log", OK if not n else INFO if n < 20 else WARN, "None since the last start" if not n else f"{n} since the last start: " + ", ".join(f"{x['what']} ({x['n']})" for x in e[:4]))


def log_errors() -> list[dict]:
    """Kinds of faults since the last start (kinds only: what was said or done isn't in it)."""
    p = _data() / "jarvis.log"
    try:
        with open(p, "rb") as f:
            f.seek(max(0, p.stat().st_size - 400_000))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return []
    text = text.rsplit("===== Jarvis started", 1)[-1]
    got: dict[str, int] = {}
    for m in re.finditer(r"^(?:\[([a-z -]{2,20})\][^\n]{0,200}?)?\b([A-Z]\w{2,40}(?:Error|Exception|Timeout|Refused))\b", text, re.M):
        k = (f"{m[1]}: " if m[1] else "") + m[2]
        got[k] = got.get(k, 0) + 1
    return [{"what": k, "n": n} for k, n in sorted(got.items(), key=lambda x: -x[1])[:12]]


def _backup(hub: Any) -> dict:
    from . import backup
    s = backup.settings()
    if s["last_error"]:
        return _row("backup", "Backup", WARN, f"The last automatic one didn't work: {_short(s['last_error'])}", go="backup")
    if not s["last"]:
        return _row("backup", "Backup", WARN, "None yet. One button makes one", go="backup")
    days = (datetime.now() - datetime.fromisoformat(s["last"])).days
    gone = not Path(s["last_path"]).exists()
    return _row("backup", "Backup", WARN if days > 30 or gone else OK, ("The last one isn't in its place any more" if gone else f"The last one was {'today' if not days else f'{days} day' + ('' if days == 1 else 's') + ' ago'}") + ("; automatic: " + s["every"]), go="backup")


def _documents(hub: Any) -> dict:
    from . import docindex, storage
    if not docindex.folders():
        return _row("docs", "Document search", INFO, "No folders chosen", go="tools")
    with storage._LOCK:
        n, bad = storage.conn().execute("SELECT COUNT(*), SUM(error != '') FROM docs").fetchone()
    return _row("docs", "Document search", OK, f"{n} documents" + (f", {bad} couldn't be read" if bad else ""), "index" if bad else "", "tools")


CHECKS = [_app, _windows, _crashed, _disk, _memory, _database, _files, _backup, _ais, _net, _mic, _speaker, _hearing, _voice, _live, _vault, _hello, _start, _remote, _parts, _documents, _errors]


def check(hub: Any) -> dict:
    """All of it. A check that itself fails is a finding, not the end."""
    rows: list[dict] = []
    t0 = time.perf_counter()
    for f in CHECKS:
        try:
            r = f(hub)
            rows += r if isinstance(r, list) else [r]
        except Exception as e:
            rows.append(_row(f.__name__.strip("_"), f.__name__.strip("_").capitalize(), INFO, f"Couldn't be checked ({type(e).__name__})"))
    order = {BAD: 0, WARN: 1, INFO: 3, OK: 2}
    return {"rows": sorted(rows, key=lambda r: order[r["state"]]), "bad": sum(r["state"] == BAD for r in rows), "warn": sum(r["state"] == WARN for r in rows), "ms": round((time.perf_counter() - t0) * 1000), "at": datetime.now().isoformat(timespec="seconds"),
            "repairs": [{"id": k, "name": n, "about": a, "restart": s} for k, (n, a, s) in REPAIRS.items()], "windows": [{"id": k, "name": v[0]} for k, v in WINDOWS.items()]}


def for_ai(hub: Any) -> str:
    c = check(hub)
    head = "Everything looks fine." if not c["bad"] and not c["warn"] else f"{c['bad']} problem(s), {c['warn']} to look at."
    return _plain(head + "\n" + "\n".join(f"- {r['name']}: {'OK' if r['state'] == OK else 'PROBLEM' if r['state'] == BAD else 'LOOK AT' if r['state'] == WARN else 'note'}. {r['detail']}" for r in c["rows"] if r["state"] != OK or c["bad"] + c["warn"] == 0)) \
        + "\n(Repairs are only done by the user's click: Settings › Health.)"


# ---------------- repairing ----------------
REPAIRS: dict[str, tuple[str, str, bool]] = {
    "database": ("Check and repair the database", "Makes a restore point, checks every page, rebuilds the indexes and gives unused space back.", False),
    "files": ("Tidy the app's files", "Leftovers of interrupted work go; a settings file that can't be read is put aside and begun again.", False),
    "ai": ("Connect to the AIs again", "Reads the keys again and looks which AIs can answer.", False),
    "mic": ("Look for microphones again", "Listens for a moment to each one to find one that works.", False),
    "dns": ("Clear the address cache (DNS)", "The usual first help when websites don't open.", False),
    "index": ("Read the documents again", "The word index of your document folders is made anew.", False),
    "startup": ("Start with Windows: put it right", "Makes or removes the shortcut, as your setting says.", False),
    "shortcuts": ("Make the shortcuts again", "Start Menu, and the Desktop one if you had it.", False),
    "window": ("Clear the window's cache", "For a window that stays black or draws wrongly. The app starts again.", True),
    "settings": ("Settings back to how they came", "Look, voice, microphone, AI, alerts and permissions. A restore point is made first; everything of yours, privacy and the lock stay. The app starts again.", True),
    "restart": ("Start the app again", "Closes and opens it.", True),
}
WINDOWS: dict[str, tuple[str, list[str] | str]] = {
    "troubleshoot": ("Troubleshooters", "ms-settings:troubleshoot"), "update": ("Windows Update", "ms-settings:windowsupdate"), "sound": ("Sound", "ms-settings:sound"), "storage": ("Storage", "ms-settings:storagesense"),
    "reliability": ("Reliability history", ["perfmon.exe", "/rel"]), "restore": ("System Restore", ["rstrui.exe"]), "memory": ("Memory test", ["mdsched.exe"]),
}


_PLACES = ("ms-settings:windowsupdate", "ms-settings:storagesense", "ms-settings:privacy-microphone", "ms-settings:sound")      # (what a finding may lead to)


def _point(why: str) -> None:
    from . import backup
    try:
        backup.make(point=True, why=why)
    except backup.BackupError as e:
        if "isn't whole" not in str(e):                  # (a damaged database is what is to be repaired)
            raise CareError(f"No restore point could be made, so nothing was changed: {e}") from None


def repair(what: Any, hub: Any) -> str:
    from . import audit
    if what not in REPAIRS:
        raise CareError("That isn't one of the repairs.")
    out = {"database": _fix_database, "files": _fix_files, "ai": _fix_ai, "mic": _fix_mic, "dns": _fix_dns, "index": _fix_index, "startup": _fix_startup, "shortcuts": _fix_shortcuts, "window": _fix_window,
           "settings": _fix_settings, "restart": lambda h: "The app starts again."}[what](hub)
    audit.record("repaired", what=what)
    return out


def _fix_database(hub: Any) -> str:
    from . import storage
    _point("before the database is repaired")
    with storage._LOCK:
        try:
            c = storage.conn()
            before = storage.path().stat().st_size
            bad = [r[0] for r in c.execute("PRAGMA integrity_check(20)").fetchall() if r[0] != "ok"]
            c.execute("REINDEX")
            c.commit()
            c.execute("VACUUM")
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            still = [r[0] for r in c.execute("PRAGMA integrity_check(20)").fetchall() if r[0] != "ok"]
            if not still:
                after = storage.path().stat().st_size
                return "The database is whole" + (f" again ({len(bad)} fault{'' if len(bad) == 1 else 's'} repaired)" if bad else "") + (f"; {_size(before - after)} given back." if before - after > 100_000 else ".")
        except sqlite3.Error:
            pass
        saved, lost = _rescue()
        return f"The database was made anew from what can still be read: {saved} rows saved, {lost} tables not complete. The damaged one is kept as assistant.db.damaged."


def _rescue() -> tuple[int, int]:
    """Row by row into a new database; the damaged one is kept."""
    from . import storage
    p = storage.path()
    storage.close()
    new = p.with_name("assistant.db.new")
    new.unlink(missing_ok=True)
    dst = sqlite3.connect(new)
    storage.migrate(dst)
    saved = lost = 0
    src = sqlite3.connect(p)
    for (t,) in dst.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'doc_text%' AND name != 'docs'").fetchall():            # (the word index is made anew)
        try:
            cols = [r[1] for r in dst.execute(f"PRAGMA table_info({t})")]
            have = {r[1] for r in src.execute(f"PRAGMA table_info({t})")}
            use = [c for c in cols if c in have]
            if not use:
                continue
            cur = src.execute(f"SELECT {', '.join(use)} FROM {t}")
            while True:
                try:
                    row = cur.fetchone()
                except sqlite3.Error:
                    lost += 1
                    break
                if row is None:
                    break
                try:
                    dst.execute(f"INSERT INTO {t} ({', '.join(use)}) VALUES ({', '.join('?' * len(use))})", row)
                    saved += 1
                except sqlite3.Error:
                    pass
        except sqlite3.Error:
            lost += 1
    dst.commit()
    dst.close()
    src.close()
    os.replace(p, p.with_name("assistant.db.damaged"))
    for n in ("-wal", "-shm"):
        Path(str(p) + n).unlink(missing_ok=True)
    os.replace(new, p)
    storage.conn()
    return saved, lost


def _fix_files(hub: Any) -> str:
    n = 0
    for p in leftovers():
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            n += 1
        except OSError:
            pass
    bad = broken_files()
    for p in bad:
        os.replace(p, p.with_name(p.name + ".broken"))
    return f"{n} leftover{'' if n == 1 else 's'} removed" + (f"; put aside: {', '.join(p.name for p in bad)} (kept as .broken)." if bad else ".")


def _fix_ai(hub: Any) -> str:
    from . import keystore, local_ai
    keystore.load_into_env()
    local_ai._ask()
    hub.rebuild_brain()
    names = getattr(hub.brain, "names", [])
    return f"Ready: {', '.join(names)}." if names else "No AI is available yet. Add a free key, or install Ollama."


def _fix_mic(hub: Any) -> str:
    from . import hud
    if hud.recorder is None:
        raise CareError("The microphone isn't available here.")
    if hub.live and hub.live.active or hub.meeting_on() or hub.recording:
        raise CareError("The microphone is in use. End the call or the meeting first.")
    hub.standby_halt()
    hud.recorder.refresh()
    dev = hud.recorder.choose_mic(force=True)
    hub._mic_cache = (0.0, {})
    if hub.standby_wanted():
        hub.standby_start(1)
    return f"Using {dev['name']}." if dev else "No microphone that works was found."


def _fix_dns(hub: Any) -> str:
    from . import netcheck
    return str(netcheck.flush_dns())


def _fix_index(hub: Any) -> str:
    from . import docindex, storage
    if not docindex.folders():
        raise CareError("No document folders are chosen.")
    with storage._LOCK:
        c = storage.conn()
        with c:
            c.execute("DELETE FROM doc_text")
            c.execute("DELETE FROM docs")
    docindex.start()
    return "The documents are read again; this goes on in the background."


def _fix_startup(hub: Any) -> str:
    from . import install, schedule
    from .config import FROZEN
    if not FROZEN:
        raise CareError("Only the installed app starts with Windows.")
    on = schedule.get_setting("start_with_windows", True) is not False
    install.set_startup(on)
    return "It starts with Windows." if on else "It doesn't start with Windows."


def _fix_shortcuts(hub: Any) -> str:
    from . import install
    from .config import APP_NAME, FROZEN
    if not FROZEN:
        raise CareError("Only the installed app has shortcuts.")
    made = install.create_shortcuts(desktop=(install.folder("desktop") / f"{APP_NAME}.lnk").exists())
    return f"Made: {', '.join(p.parent.name for p in made)}."


def _fix_window(hub: Any) -> str:
    (_data() / "clear_window").write_text("1", encoding="utf-8")
    return "The window's cache is cleared when the app starts again."


# what goes back: look, voice, microphone, AI and alerts. Privacy, lock, vault, reminders' texts and lists of yours stay.
RESET = ("theme", "face", "speak", "hands_free", "wake_word", "live_voice", "live_on_open", "live_pause", "live_resting", "voice_engine", "tts_engine", "stt_engine", "local_stt_model", "noise_reduction", "mic", "loud_alerts",
         "alert_tone", "brain", "plan_mode", "prefer_local", "local_model", "chat_script", "reading_voice", "ring_minutes", "suggest_memories")


def _fix_settings(hub: Any) -> str:
    from . import schedule
    from .config import DATA_LOCK, read_json, write_json
    _point("before the settings are set back")
    with DATA_LOCK:
        old = read_json(schedule.SETTINGS_FILE, {})
        old = old if isinstance(old, dict) else {}
        new = {k: v for k, v in old.items() if k not in RESET and not k.startswith("local_voice_")}
        perms = {k: v for k, v in old["permissions"].items() if v == "never"} if isinstance(old.get("permissions"), dict) else {}
        write_json(schedule.SETTINGS_FILE, {**{k: v for k, v in new.items() if k != "permissions"}, **({"permissions": perms} if perms else {})})      # (what is always allowed asks again)
    return "The settings are as they came."


def open_windows(what: Any) -> None:
    """One of Windows' own tools (a fixed list)."""
    import subprocess
    if what not in WINDOWS and what not in _PLACES:
        raise CareError("That isn't one of the tools.")
    t = WINDOWS[what][1] if what in WINDOWS else what
    if isinstance(t, str):
        os.startfile(t)
    else:
        exe = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / t[0]
        try:
            os.startfile(str(exe), arguments=" ".join(t[1:]))
        except (OSError, TypeError):
            subprocess.Popen([str(exe), *t[1:]], close_fds=True)


# ---------------- at the start ----------------
_CACHES = ("Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache", "DawnCache")


def clear_window_cache() -> bool:
    """Asked for on the Health page: before the window is opened."""
    flag = _data() / "clear_window"
    if not flag.is_file():
        return False
    places = [base / n for base in (_data() / "webview").glob("**/Default") for n in _CACHES] + list((_data() / "webview").glob("**/*ShaderCache"))
    for attempt in range(8):                             # the old window's processes need a moment to end
        for p in places:
            shutil.rmtree(p, ignore_errors=True)
        if not any(p.exists() for p in places):
            break
        time.sleep(0.5)
    flag.unlink(missing_ok=True)
    return True


def wait_for(pid: int, seconds: float = 25) -> None:
    """The app that asked for a restart has to be gone first."""
    import psutil
    end = time.monotonic() + seconds
    while time.monotonic() < end and psutil.pid_exists(pid):
        time.sleep(0.2)


def at_start() -> str:
    """Before anything is opened (and only when no other copy of the app is running). Returns what to tell."""
    from . import backup, keystore
    note = ""
    for f in (backup.apply_pending, backup.before_update, clear_window_cache):
        try:
            r = f()
            if isinstance(r, str) and r:
                note = r
                os.environ.update(keystore.load())       # (the keys in a backup, if they were put back)
        except Exception as e:
            print(f"[start] {f.__name__}: {type(e).__name__}: {e}")
    return note


# ---------------- a report ----------------
def _plain(text: str) -> str:
    """Without the name of the Windows account."""
    home = os.environ.get("USERPROFILE", str(Path.home()))
    user = os.path.basename(home)
    text = text.replace(home, "%USERPROFILE%")
    return re.sub(re.escape(user), "(user)", text, flags=re.I) if len(user) > 2 else text


def report(hub: Any, save: bool = True) -> dict:
    """What check() found, as text without names, keys or texts; saved in Documents."""
    from . import __version__
    c = check(hub)
    lines = [f"Personal Assistant {__version__}, health report of {c['at'].replace('T', ' ')}", ""]
    lines += [f"[{r['state'].upper():4}] {r['name']}: {r['detail']}" for r in c["rows"]]
    e = log_errors()
    if e:
        lines += ["", "Faults since the last start:"] + [f"  {x['n']}x {x['what']}" for x in e]
    text = _plain("\n".join(lines))
    out = {"text": text, "path": ""}
    if save:
        folder = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        folder.mkdir(parents=True, exist_ok=True)
        for n in range(1, 100):
            p = folder / f"Personal Assistant health {c['at'][:10]}{f' ({n})' if n > 1 else ''}.txt"
            try:
                with open(p, "x", encoding="utf-8") as f:
                    f.write(text + "\n")
                out["path"] = str(p)
                break
            except FileExistsError:
                continue
    return out

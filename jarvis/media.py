"""Media (Phase 8): what is playing on this PC, the volume, your own music and videos, playlists, and free internet radio.

Your files are only read, in the folders you chose; nothing is uploaded. Going online: a radio search (its words go to
radio-browser.info) and the station you play (your player connects to it).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from .planner import _db, _now, _text

AUDIO = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac"}
VIDEO = {".mp4": "video/mp4", ".webm": "video/webm", ".m4v": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska"}
TYPES = {**AUDIO, **VIDEO}
MAX_FILES, MAX_FOLDERS, MAX_LISTS, MAX_IN_LIST, MAX_STATIONS = 20_000, 20, 100, 500, 200


# ---------------- what is playing (Windows' own media control) ----------------
_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
$null = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties, Windows.Media.Control, ContentType = WindowsRuntime]
$as = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Wait-Op($op, $type) { $t = $as.MakeGenericMethod($type).Invoke($null, @($op)); if (-not $t.Wait(3000)) { throw 'slow' }; $t.Result }
$man = Wait-Op ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
while ($null -ne ($line = [Console]::In.ReadLine())) {
  try {
    $s = $man.GetCurrentSession()
    if ($null -eq $s) { [Console]::Out.WriteLine('{"none":true}'); continue }
    $did = $null
    switch ($line) {
      'play'  { $did = Wait-Op ($s.TryPlayAsync()) ([bool]) }
      'pause' { $did = Wait-Op ($s.TryPauseAsync()) ([bool]) }
      'play_pause' { $did = Wait-Op ($s.TryTogglePlayPauseAsync()) ([bool]) }
      'next'  { $did = Wait-Op ($s.TrySkipNextAsync()) ([bool]) }
      'previous' { $did = Wait-Op ($s.TrySkipPreviousAsync()) ([bool]) }
      'stop'  { $did = Wait-Op ($s.TryStopAsync()) ([bool]) }
    }
    $p = Wait-Op ($s.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
    $t = $s.GetTimelineProperties()
    [Console]::Out.WriteLine((@{ did = $did; title = $p.Title; artist = $p.Artist; album = $p.AlbumTitle; app = $s.SourceAppUserModelId; status = "$($s.GetPlaybackInfo().PlaybackStatus)";
      position = [math]::Round($t.Position.TotalSeconds, 1); length = [math]::Round($t.EndTime.TotalSeconds, 1) } | ConvertTo-Json -Compress))
  } catch { [Console]::Out.WriteLine('{"none":true}') }
}
"""
CONTROLS = ("play", "pause", "play_pause", "next", "previous", "stop")


class NowPlaying:
    """One quiet helper process that asks Windows; it ends by itself when nobody asked for a minute."""
    IDLE = 60

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._p: subprocess.Popen | None = None
        self._used = 0.0

    def _start(self) -> subprocess.Popen:
        p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        threading.Thread(target=self._end_idle, args=(p,), daemon=True).start()
        return p

    def _end_idle(self, p: subprocess.Popen) -> None:
        while p.poll() is None:
            time.sleep(5)
            if time.monotonic() - self._used > self.IDLE:
                try:
                    p.stdin.close()                         # its loop ends
                    p.wait(5)
                except Exception:
                    p.kill()
                return

    def ask(self, line: str, wait: float = 6.0) -> dict:
        with self._lock:
            self._used = time.monotonic()
            for _ in (0, 1):
                try:
                    if self._p is None or self._p.poll() is not None or self._p.stdin.closed:
                        self._p = self._start()
                    p = self._p
                    p.stdin.write(line + "\n")
                    p.stdin.flush()
                    got: list[str] = []
                    t = threading.Thread(target=lambda: got.append(p.stdout.readline()), daemon=True)
                    t.start()
                    t.join(wait)
                    if got and got[0].strip():
                        return json.loads(got[0])
                    raise OSError("no answer")
                except (OSError, ValueError):
                    try:
                        self._p.kill()
                    except Exception:
                        pass
                    self._p = None
            return {"none": True}


_NOW = NowPlaying()
_APPS = {"chrome": "Chrome", "msedge": "Edge", "microsoftedge": "Edge", "firefox": "Firefox", "spotify": "Spotify", "vlc": "VLC", "zunemusic": "Media Player", "zunevideo": "Films & TV",
         "itunes": "iTunes", "applemusic": "Apple Music", "brave": "Brave", "opera": "Opera", "whatsapp": "WhatsApp", "personal assistant": "Personal Assistant"}


def app_name(source: str) -> str:
    low = str(source or "").lower()
    hit = next((name for key, name in _APPS.items() if key in low), "")
    return hit or re.sub(r"\.exe$", "", re.split(r"[!_\\/]", str(source or ""))[0], flags=re.I).split(".")[-1][:40]


def now(action: str = "get") -> dict:
    """What is playing, after an optional action. {'none': True}: nothing."""
    if action != "get" and action not in CONTROLS:
        raise ValueError(f"I can {', '.join(CONTROLS)}.")
    r = _NOW.ask(action)
    if r.get("none"):
        return {"none": True}
    clean = lambda v, n: " ".join(re.sub(r"[\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]", " ", str(v or "")).split())[:n]           # noqa: E731
    return {"title": clean(r.get("title"), 200), "artist": clean(r.get("artist"), 120), "album": clean(r.get("album"), 120), "app": app_name(r.get("app")),
            "playing": r.get("status") == "Playing", "position": max(0, float(r.get("position") or 0)), "length": max(0, float(r.get("length") or 0)), "did": r.get("did")}


def volume(value: Any = None, mute: bool | None = None) -> dict:
    from .alerts import _speakers
    ep = _speakers()
    if ep is None:
        raise ValueError("The speakers' volume can't be reached.")
    if value is not None:
        try:
            n = int(float(str(value).strip().rstrip("%")))
        except ValueError:
            raise ValueError("The volume is a number from 0 to 100.") from None
        if not 0 <= n <= 100:
            raise ValueError("The volume is a number from 0 to 100.")
        ep.SetMasterVolumeLevelScalar(n / 100, None)
        if n and mute is None:
            ep.SetMute(0, None)
    if mute is not None:
        ep.SetMute(int(bool(mute)), None)
    return {"volume": round(ep.GetMasterVolumeLevelScalar() * 100), "muted": bool(ep.GetMute())}


# ---------------- your files ----------------
def _id3(raw: bytes) -> dict[str, str]:
    """Title, artist and album from an MP3's ID3v2 tag (best effort)."""
    if raw[:3] != b"ID3" or len(raw) < 20:
        return {}
    ver, out, i = raw[3], {}, 10
    size = (raw[6] & 127) << 21 | (raw[7] & 127) << 14 | (raw[8] & 127) << 7 | raw[9] & 127
    names = {b"TIT2": "title", b"TPE1": "artist", b"TALB": "album", b"TT2": "title", b"TP1": "artist", b"TAL": "album"}
    end = min(len(raw), 10 + size)
    while i + 10 < end and len(out) < 3:
        if ver == 2:
            key, n, head = raw[i:i + 3], int.from_bytes(raw[i + 3:i + 6], "big"), 6
        else:
            b = raw[i + 4:i + 8]
            n = ((b[0] & 127) << 21 | (b[1] & 127) << 14 | (b[2] & 127) << 7 | b[3] & 127) if ver == 4 else int.from_bytes(b, "big")
            key, head = raw[i:i + 4], 10
        if not key.strip(b"\0") or n <= 0 or i + head + n > end:
            break
        if key in names and n < 2000:
            data = raw[i + head:i + head + n]
            enc = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}.get(data[0], "latin-1")
            text = " ".join(data[1:].decode(enc, "ignore").replace("\0", " ").split())[:160]
            if text:
                out[names[key]] = text
        i += head + n
    return out


def _tags(p: Path) -> dict[str, str]:
    tags: dict[str, str] = {}
    if p.suffix.lower() == ".mp3":
        try:
            with open(p, "rb") as f:
                tags = _id3(f.read(200_000))
        except OSError:
            pass
    if not tags.get("title"):
        stem = re.sub(r"^\d{1,3}[\s._-]+(?=\D)", "", p.stem.replace("_", " ")).strip() or p.stem
        a, sep, b = stem.partition(" - ")
        tags = {**({"artist": a.strip()} if sep and b.strip() else {}), **tags, "title": (b.strip() if sep and b.strip() else stem)[:160]}
    return tags


def folders() -> list[dict]:
    c, lock = _db()
    with lock:
        counts = dict(c.execute("SELECT folder, count(*) FROM media_files GROUP BY folder").fetchall())
        return [{"id": r[0], "path": r[1], "files": counts.get(r[0], 0)} for r in c.execute("SELECT id, path FROM media_folders ORDER BY id").fetchall()]


def suggestions() -> list[str]:
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    have = {f["path"].casefold() for f in folders()}
    return [str(p) for n in ("Music", "Videos") if (p := (home / n).resolve()).is_dir() and str(p).casefold() not in have]


def add_folder(path: Any) -> dict:
    from . import guard
    raw = str(path or "").strip().strip('"')
    if not raw:
        raise ValueError("Which folder?")
    if guard.elsewhere(raw):
        raise ValueError("Folders on other computers aren't read.")
    p = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not p.is_absolute() or not p.is_dir():
        raise ValueError("That folder isn't there.")
    p = p.resolve()
    bad = [Path(os.environ.get(k, "C:/nope")).resolve() for k in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA", "LOCALAPPDATA")]
    if p == Path(p.anchor) or any(p == b or b in p.parents for b in bad):
        raise ValueError("Choose a folder of your own music or videos.")
    rows = folders()
    if any(f["path"].casefold() == str(p).casefold() for f in rows):
        raise ValueError("That folder is already there.")
    if len(rows) >= MAX_FOLDERS:
        raise ValueError(f"That's {MAX_FOLDERS} folders.")
    c, lock = _db()
    with lock, c:
        i = c.execute("INSERT INTO media_folders (path) VALUES (?)", (str(p),)).lastrowid
    scan(i)
    return next(f for f in folders() if f["id"] == i)


def remove_folder(folder_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        c.execute("DELETE FROM media_files WHERE folder = ?", (int(folder_id),))
        return c.execute("DELETE FROM media_folders WHERE id = ?", (int(folder_id),)).rowcount > 0


def scan(folder_id: int | None = None) -> int:
    """Look again for files: new, changed and gone ones. Their numbers stay."""
    c, lock = _db()
    total = 0
    for f in folders():
        if folder_id is not None and f["id"] != folder_id:
            continue
        root = Path(f["path"])
        with lock:
            have = {p: (i, m) for i, p, m in c.execute("SELECT id, path, mtime FROM media_files WHERE folder = ?", (f["id"],)).fetchall()}
            room = MAX_FILES - c.execute("SELECT count(*) FROM media_files").fetchone()[0]
        seen, new = set(), []
        if root.is_dir():
            for dirpath, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if not d.startswith((".", "$"))]
                for n in names:
                    ext = os.path.splitext(n)[1].lower()
                    if ext not in TYPES:
                        continue
                    p = os.path.join(dirpath, n)
                    try:
                        m = os.stat(p).st_mtime
                    except OSError:
                        continue
                    seen.add(p)
                    if p not in have or abs(have[p][1] - m) > 1:
                        new.append((p, ext, m))
        elif have:
            continue                                        # the drive isn't plugged in: keep what is known
        with lock, c:
            for p, ext, m in new:
                t = _tags(Path(p))
                row = ("video" if ext in VIDEO else "audio", t.get("title", ""), t.get("artist", ""), t.get("album", ""), m)
                if p in have:
                    c.execute("UPDATE media_files SET kind = ?, title = ?, artist = ?, album = ?, mtime = ? WHERE id = ?", (*row, have[p][0]))
                elif room > 0:
                    room -= 1
                    c.execute("INSERT INTO media_files (folder, path, kind, title, artist, album, mtime) VALUES (?, ?, ?, ?, ?, ?, ?)", (f["id"], p, *row))
            gone = [have[p][0] for p in have if p not in seen]
            c.executemany("DELETE FROM media_files WHERE id = ?", [(i,) for i in gone])
        total += len(seen)
    return total


_F = "id, path, kind, title, artist, album"


def _file(r) -> dict:
    return {"id": r[0], "kind": r[2], "title": r[3], "artist": r[4], "album": r[5], "name": os.path.basename(r[1])}


def files(query: str = "", kind: str = "", limit: int = 300) -> list[dict]:
    q, args = [], []
    for w in str(query or "").split()[:8]:
        q.append("(title || ' ' || artist || ' ' || album || ' ' || path) LIKE ? ESCAPE '\\'")
        args.append("%" + re.sub(r"([\\%_])", r"\\\1", w) + "%")
    if kind in ("audio", "video"):
        q.append("kind = ?")
        args.append(kind)
    c, lock = _db()
    with lock:
        return [_file(r) for r in c.execute(f"SELECT {_F} FROM media_files" + (" WHERE " + " AND ".join(q) if q else "") +
                                            " ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, title COLLATE NOCASE LIMIT ?", (*args, limit)).fetchall()]


def path_of(file_id: Any) -> tuple[Path, str] | None:
    """A file's path and type: only what is in the library, and still inside its folder."""
    c, lock = _db()
    with lock:
        r = c.execute("SELECT m.path, f.path FROM media_files m JOIN media_folders f ON f.id = m.folder WHERE m.id = ?", (int(file_id),)).fetchone()
    if not r:
        return None
    p, root = Path(r[0]), Path(r[1]).resolve()
    try:
        real = p.resolve(strict=True)
    except OSError:
        return None
    t = TYPES.get(real.suffix.lower())
    return (real, t) if t and root in real.parents and real.is_file() else None


def by_ids(ids: list[int]) -> list[dict]:
    c, lock = _db()
    with lock:
        got = {r[0]: _file(r) for r in c.execute(f"SELECT {_F} FROM media_files WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()} if ids else {}
    return [got[i] for i in ids if i in got]


# ---------------- playlists ----------------
def playlists() -> list[dict]:
    c, lock = _db()
    with lock:
        rows = c.execute("SELECT id, name, items FROM playlists ORDER BY name COLLATE NOCASE").fetchall()
    return [{"id": r[0], "name": r[1], "items": by_ids(json.loads(r[2]))} for r in rows]


def save_playlist(name: Any, playlist_id: int | None = None) -> int:
    n = _text(name, 60, "The playlist's name", True)
    rows = playlists()
    if any(p["name"].casefold() == n.casefold() and p["id"] != playlist_id for p in rows):
        raise ValueError(f"There is already a playlist called {n}.")
    c, lock = _db()
    with lock, c:
        if playlist_id is None:
            if len(rows) >= MAX_LISTS:
                raise ValueError(f"That's {MAX_LISTS} playlists.")
            return c.execute("INSERT INTO playlists (name, items, created) VALUES (?, '[]', ?)", (n, _now())).lastrowid
        if not c.execute("UPDATE playlists SET name = ? WHERE id = ?", (n, playlist_id)).rowcount:
            raise ValueError("That playlist is gone.")
        return playlist_id


def delete_playlist(playlist_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM playlists WHERE id = ?", (int(playlist_id),)).rowcount > 0


def change_playlist(playlist_id: Any, file_id: Any, add: bool = True) -> int:
    c, lock = _db()
    with lock, c:
        r = c.execute("SELECT items FROM playlists WHERE id = ?", (int(playlist_id),)).fetchone()
        if not r:
            raise ValueError("That playlist is gone.")
        ids = [i for i in json.loads(r[0]) if i != int(file_id)]
        if add:
            if not c.execute("SELECT 1 FROM media_files WHERE id = ?", (int(file_id),)).fetchone():
                raise ValueError("That file isn't in the library any more.")
            if len(ids) >= MAX_IN_LIST:
                raise ValueError(f"That's {MAX_IN_LIST} in one playlist.")
            ids.append(int(file_id))
        c.execute("UPDATE playlists SET items = ? WHERE id = ?", (json.dumps(ids), int(playlist_id)))
    return len(ids)


# ---------------- radio ----------------
RADIO = ("https://de1.api.radio-browser.info", "https://de2.api.radio-browser.info", "https://fi1.api.radio-browser.info")
_found: dict[str, dict] = {}                # stations shown since the start, by their number


def _station_url(url: Any) -> str:
    """A station's address: ordinary web address, out on the internet (stations often use odd ports)."""
    from .news import _public
    u = str(url or "").strip()
    if len(u) > 500 or re.search(r"[\s\x00-\x1f\"'<>]", u):
        raise ValueError("That station's address can't be used.")
    _public(u, any_port=True)
    return u


def radio_search(words: Any) -> list[dict]:
    from . import news, schedule
    q = news.clean(words, 80)
    if len(q) < 2:
        raise ValueError("Which station, kind of music or country?")
    rows = None
    for host in RADIO:
        try:
            rows = schedule._get_json(f"{host}/json/stations/search?" + urllib.parse.urlencode({"name": q, "limit": 40, "hidebroken": "true", "order": "clickcount", "reverse": "true"}), timeout=10,
                                      ua={"User-Agent": "PersonalAssistant"})
            if not rows:
                rows = schedule._get_json(f"{host}/json/stations/search?" + urllib.parse.urlencode({"tag": q.lower(), "limit": 40, "hidebroken": "true", "order": "clickcount", "reverse": "true"}),
                                          timeout=10, ua={"User-Agent": "PersonalAssistant"})
            break
        except (OSError, ValueError):
            continue
    if not isinstance(rows, list):
        raise ValueError("The radio list can't be reached. Is the internet on?")
    out, have = [], {s["uid"] for s in stations()}
    for r in rows:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url_resolved") or r.get("url") or "")
        uid, name = re.sub(r"[^\w-]", "", str(r.get("stationuuid") or ""))[:40], news.clean(r.get("name"), 80)
        if not uid or not name or not url.startswith(("http://", "https://")) or len(url) > 500 or url.lower().split("?")[0].endswith((".m3u8", ".pls", ".m3u", ".asx")):
            continue                                        # (lists a web player can't play)
        s = {"uid": uid, "name": name, "url": url, "country": news.clean(r.get("country"), 40), "tags": news.clean(r.get("tags"), 60), "codec": news.clean(r.get("codec"), 8), "saved": uid in have}
        _found[uid] = s
        out.append(s)
    while len(_found) > 1000:
        _found.pop(next(iter(_found)))
    return out[:30]


def stations() -> list[dict]:
    c, lock = _db()
    with lock:
        return [{"uid": r[0], "name": r[1], "url": r[2], "country": r[3], "tags": "", "codec": "", "saved": True} for r in
                c.execute("SELECT uid, name, url, country FROM stations ORDER BY name COLLATE NOCASE").fetchall()]


def station(uid: Any) -> dict | None:
    u = str(uid or "")
    return next((s for s in stations() if s["uid"] == u), None) or _found.get(u)


def station_play(uid: Any) -> dict:
    s = station(uid)
    if not s:
        raise ValueError("That station isn't in the list any more.")
    return {**s, "url": _station_url(s["url"])}


def station_save(uid: Any, on: bool = True) -> None:
    c, lock = _db()
    if not on:
        with lock, c:
            c.execute("DELETE FROM stations WHERE uid = ?", (str(uid),))
        return
    s = station(uid)
    if not s:
        raise ValueError("That station isn't in the list any more.")
    if len(stations()) >= MAX_STATIONS:
        raise ValueError(f"That's {MAX_STATIONS} stations.")
    with lock, c:
        c.execute("INSERT OR IGNORE INTO stations (uid, name, url, country) VALUES (?, ?, ?, ?)", (s["uid"], s["name"], s["url"], s["country"]))


# ---------------- what to play, by name ----------------
def find(words: Any) -> dict | None:
    """{'what': 'playlist' | 'files' | 'station', ...} for what was asked for, or None."""
    q = " ".join(str(words or "").split())
    low = q.casefold()
    if not low:
        return None
    for p in playlists():
        if p["name"].casefold() == low and p["items"]:
            return {"what": "playlist", "name": p["name"], "items": p["items"]}
    for s in stations():
        if s["name"].casefold() == low:
            return {"what": "station", "name": s["name"], "uid": s["uid"]}
    got = files(q, limit=50)
    if got:
        return {"what": "files", "name": got[0]["title"] if len(got) == 1 else f"{q} ({len(got)})", "items": got}
    p = next((p for p in playlists() if low in p["name"].casefold() and p["items"]), None)
    if p:
        return {"what": "playlist", "name": p["name"], "items": p["items"]}
    s = next((s for s in stations() if all(w in s["name"].casefold() for w in low.split())), None)
    return {"what": "station", "name": s["name"], "uid": s["uid"]} if s else None


def load(query: str = "", kind: str = "") -> dict:
    return {"folders": folders(), "suggestions": suggestions(), "files": files(query, kind), "playlists": playlists(), "stations": stations()}

"""Backups: one encrypted file (.pabackup) with everything that is yours in the app, and putting it back.

What is in it: the database (conversations, memories, planner, …), settings, profile, alarms, notes, the record of actions,
the vault (as it is: still encrypted with its own password), and, if ticked, the AI keys and the pictures of the screen.
Not in it: voices and speech models, the window's cache, logs, the Gmail sign-in, the lock's PIN.

The file is encrypted (AES-256-GCM in pieces, each bound to its place) with a random key; that key is in it twice at most:
locked for this Windows account (so it opens here without asking) and, if you chose a backup password, locked with that
(scrypt), so it opens on another PC too. Every backup is read back and checked before it counts.

Putting one back: everything is unpacked and checked first, a restore point of now is made, and the app starts again; only
then are the files exchanged, all of them or none.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import struct
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

MAGIC = b"PABACKUP1\n"
CHUNK = 2**20
N = 2 ** 16                                              # scrypt: 64 MB
EVERY = ("off", "daily", "weekly")
KEEP = (3, 7, 14, 30)
FILES = ("settings.json", "profile.json", "alarms.json", "location.json", "memory.json", "audit.log", "audit.old.log")
MAX_ENTRY = 2 * 2**30                                    # of one file in it (a made-up file must not fill the drive)
_ENTROPY = b"Personal Assistant backup v1"
_LOCK = threading.Lock()
_BUSY = {"what": ""}


class BackupError(ValueError):
    """Something to tell the owner, in plain words."""


def _data() -> Path:
    from .config import DATA_DIR
    return DATA_DIR


def points_dir() -> Path:
    """Restore points: kept with the app's data, only for this Windows account."""
    return _data() / "backups"


def _settings() -> dict:
    from . import schedule
    s = schedule.get_setting("backup")
    return s if isinstance(s, dict) else {}


def _set(**k: Any) -> None:
    from . import schedule
    schedule.set_setting("backup", {**_settings(), **k})


def default_folder() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "Personal Assistant Backups"


def folder() -> Path:
    f = _settings().get("folder")
    return Path(f) if isinstance(f, str) and f else default_folder()


# ---------------- locking ----------------
def _b(x: bytes) -> str:
    return base64.b64encode(x).decode("ascii")


def _u(x: Any) -> bytes:
    return base64.b64decode(str(x).encode("ascii"), validate=True)


def _gcm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def _protect(data: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptProtectData(data, "Personal Assistant backup", _ENTROPY, None, None, 0)


def _unprotect(blob: bytes) -> bytes | None:
    import win32crypt
    try:
        return win32crypt.CryptUnprotectData(blob, _ENTROPY, None, None, 0)[1]
    except Exception:
        return None


def _stretch(password: Any, salt: bytes) -> bytes:
    import unicodedata
    return hashlib.scrypt(unicodedata.normalize("NFC", str(password or "")).encode(), salt=salt, n=N, r=8, p=1, maxmem=128 * 2**20, dklen=32)


def _wrap(kek: bytes, key: bytes, bid: str) -> str:
    nonce = secrets.token_bytes(12)
    return _b(nonce + _gcm(kek).encrypt(nonce, key, f"pa-backup key {bid}".encode()))


def _unwrap(kek: bytes, text: Any, bid: str) -> bytes | None:
    from cryptography.exceptions import InvalidTag
    try:
        raw = _u(text)
        return _gcm(kek).decrypt(raw[:12], raw[12:], f"pa-backup key {bid}".encode())
    except (InvalidTag, ValueError, TypeError):
        return None


def _pw_file() -> Path:
    return _data() / "backup.dat"


def has_password() -> bool:
    return _pw_file().is_file()


def set_password(password: Any, again: Any) -> None:
    """Kept only as the key made from it, locked for this Windows account (so automatic backups need no typing)."""
    from . import audit, vault
    if str(password or "") != str(again or ""):
        raise BackupError("The two passwords aren't the same.")
    if len(str(password or "")) < 8 or vault.strength(password) < 1:
        raise BackupError("The backup password needs at least 8 letters or signs, and not an easy one.")
    salt = secrets.token_bytes(16)
    blob = _protect(json.dumps({"salt": _b(salt), "key": _b(_stretch(password, salt))}).encode())
    tmp = _pw_file().with_name("backup.dat.tmp")
    tmp.write_bytes(blob)
    tmp.replace(_pw_file())
    audit.record("backup_password_set")


def remove_password() -> None:
    from . import audit
    _pw_file().unlink(missing_ok=True)
    audit.record("backup_password_removed")


def _pw_key() -> tuple[bytes, bytes] | None:
    """(salt, key) of the backup password."""
    if not has_password():
        return None
    raw = _unprotect(_pw_file().read_bytes())
    if raw is None:
        return None
    d = json.loads(raw)
    return _u(d["salt"]), _u(d["key"])


# ---------------- the file ----------------
class _Seal(io.RawIOBase):
    """Writes pieces, each encrypted and bound to its place; the last one says that it is."""

    def __init__(self, f: BinaryIO, key: bytes, about: bytes) -> None:
        super().__init__()
        self.f, self.g, self.about, self.buf, self.n = f, _gcm(key), about, bytearray(), 0

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:                                 # type: ignore[override]
        self.buf += data
        while len(self.buf) > CHUNK:
            self._piece(bytes(self.buf[:CHUNK]), False)
            del self.buf[:CHUNK]
        return len(data)

    def _piece(self, data: bytes, last: bool) -> None:
        self.f.write(self.g.encrypt(struct.pack(">QI", 0, self.n), data, self.about + struct.pack(">QB", self.n, last)))
        self.n += 1

    def finish(self) -> None:
        self._piece(bytes(self.buf), True)
        self.buf.clear()


class _Open(io.RawIOBase):
    """Reads them back, anywhere in the file (zip needs to jump about)."""

    def __init__(self, f: BinaryIO, start: int, size: int, key: bytes, about: bytes) -> None:
        super().__init__()
        self.f, self.start, self.g, self.about, self.at = f, start, _gcm(key), about, 0
        sealed = size - start
        self.pieces = max(1, (sealed + CHUNK + 15) // (CHUNK + 16))
        self.len = sealed - 16 * self.pieces
        self.have = (-1, b"")
        if self.len < 0:
            raise BackupError("That backup is cut short.")

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, pos: int, how: int = 0) -> int:
        self.at = pos if how == 0 else self.at + pos if how == 1 else self.len + pos
        return self.at

    def tell(self) -> int:
        return self.at

    def _piece(self, i: int) -> bytes:
        if self.have[0] != i:
            from cryptography.exceptions import InvalidTag
            self.f.seek(self.start + i * (CHUNK + 16))
            try:
                self.have = (i, self.g.decrypt(struct.pack(">QI", 0, i), self.f.read(CHUNK + 16), self.about + struct.pack(">QB", i, i == self.pieces - 1)))
            except (InvalidTag, ValueError):
                raise BackupError("That backup was changed or is damaged.") from None
        return self.have[1]

    def readinto(self, b) -> int:                                 # type: ignore[override]
        if self.at >= self.len:
            return 0
        i, o = divmod(self.at, CHUNK)
        part = self._piece(i)[o:o + len(b)]
        b[:len(part)] = part
        self.at += len(part)
        return len(part)


def _header(f: BinaryIO) -> tuple[dict, int, bytes]:
    """(the readable part at the front, where the rest starts, what binds the two)."""
    if f.read(len(MAGIC)) != MAGIC:
        raise BackupError("That isn't a backup of this app.")
    raw = f.read(4)
    n = struct.unpack(">I", raw)[0] if len(raw) == 4 else 0
    if not 0 < n < 100_000:
        raise BackupError("That backup is damaged.")
    text = f.read(n)
    try:
        h = json.loads(text)
        if h.get("v") != 1 or not isinstance(h.get("slots"), dict) or not re.fullmatch(r"[0-9a-f]{16}", str(h.get("id"))):
            raise ValueError
    except (ValueError, AttributeError):
        raise BackupError("That backup is damaged, or made by a newer version of the app.") from None
    return h, len(MAGIC) + 4 + n, hashlib.sha256(MAGIC + raw + text).digest()


def _key_of(h: dict, password: Any = None) -> bytes | None:
    s = h["slots"]
    if s.get("windows"):
        try:
            k = _unprotect(_u(s["windows"]))
        except ValueError:
            k = None
        if k and len(k) == 32:
            return k
    p = s.get("password")
    if isinstance(p, dict) and password:
        try:
            return _unwrap(_stretch(password, _u(p["salt"])), p["key"], h["id"])
        except (ValueError, KeyError):
            return None
    return None


# ---------------- making one ----------------
def _snapshot(to: Path) -> int:
    """A whole copy of the database while it is in use, checked. Returns its version."""
    from . import storage
    if not storage.path().is_file():
        return 0
    src = sqlite3.connect(f"file:{storage.path().as_posix()}?mode=ro", uri=True, timeout=20)
    dst = sqlite3.connect(to)
    try:
        src.backup(dst)
        if dst.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise BackupError("The database isn't whole, so it wasn't backed up. Health › Database can repair it.")
        return dst.execute("PRAGMA user_version").fetchone()[0]
    finally:
        src.close()
        dst.close()


def _contents(keys: bool, shots: bool) -> list[tuple[str, Path]]:
    from .config import NOTES_DIR, SCREENSHOT_DIR
    out = [(f"data/{n}", _data() / n) for n in FILES if (_data() / n).is_file()]
    out += [(f"notes/{p.relative_to(NOTES_DIR).as_posix()}", p) for p in sorted(NOTES_DIR.rglob("*")) if p.is_file() and p.suffix != ".tmp"]
    v = _data() / "vault"
    out += [(f"vault/{p.relative_to(v).as_posix()}", p) for p in sorted(v.rglob("*")) if p.is_file() and not p.name.endswith((".tmp", ".bak"))] if v.is_dir() else []
    if shots:
        out += [(f"screenshots/{p.name}", p) for p in sorted(SCREENSHOT_DIR.glob("*")) if p.is_file()]
    return out


def _free(p: Path) -> int:
    while not p.exists():
        p = p.parent
    return shutil.disk_usage(p).free


def make(to: Path | None = None, why: str = "you", password: Any = None, keys: bool | None = None, shots: bool | None = None, point: bool = False) -> dict:
    """A backup (or, point=True, a restore point with the app's data). Returns {"path", "size", "files"}."""
    from . import __version__, audit, keystore
    if not _LOCK.acquire(blocking=False):
        raise BackupError("A backup is being made already.")
    _BUSY["what"] = "Making a backup"
    work = _data() / "backup.tmp"
    try:
        s = _settings()
        keys = (s.get("keys") is True if keys is None else keys) or point
        shots = (s.get("shots") is True if shots is None else shots) and not point
        where = points_dir() if point else to or folder()
        where.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir()
        version = _snapshot(work / "assistant.db")
        items = _contents(keys, shots)
        if (work / "assistant.db").is_file():
            items.insert(0, ("data/assistant.db", work / "assistant.db"))
        if keys and (k := keystore.load()):
            (work / "keys.json").write_text(json.dumps(k), encoding="utf-8")
            items.append(("secret/keys.json", work / "keys.json"))
        need = sum(p.stat().st_size for _, p in items)
        if _free(where) < need + 200 * 2**20:
            raise BackupError(f"There isn't enough room in {where}.")
        bid, key = secrets.token_hex(8), secrets.token_bytes(32)
        slots: dict[str, Any] = {"windows": _b(_protect(key))}
        if password:
            salt = secrets.token_bytes(16)
            slots["password"] = {"salt": _b(salt), "key": _wrap(_stretch(password, salt), key, bid)}
        elif not point and (pk := _pw_key()):
            slots["password"] = {"salt": _b(pk[0]), "key": _wrap(pk[1], key, bid)}
        head = json.dumps({"v": 1, "id": bid, "made": datetime.now().isoformat(timespec="seconds"), "app": __version__, "why": why[:80], "db": version, "slots": slots, "n": N}).encode()
        front = MAGIC + struct.pack(">I", len(head)) + head
        stamp = datetime.now().strftime("%Y-%m-%d %H.%M.%S")
        name = f"Restore point {stamp}" if point else f"Personal Assistant {stamp}"
        out = where / f"{name}.pabackup"
        for n in range(2, 50):
            if not out.exists():
                break
            out = where / f"{name} ({n}).pabackup"
        part = out.with_name(out.name + ".part")
        manifest: dict[str, Any] = {"app": __version__, "made": datetime.now().isoformat(timespec="seconds"), "db": version, "files": {}}
        try:
            with open(part, "xb") as f:
                f.write(front)
                seal = _Seal(f, key, hashlib.sha256(front).digest())
                with zipfile.ZipFile(seal, "w", zipfile.ZIP_DEFLATED, compresslevel=5) as z:            # type: ignore[arg-type]
                    for arc, p in items:
                        h, size = hashlib.sha256(), 0
                        try:
                            src = open(p, "rb")
                        except FileNotFoundError:                                                    # gone since the list was made
                            continue
                        with src, z.open(zipfile.ZipInfo(arc, time.localtime()[:6]), "w", force_zip64=True) as d:
                            while block := src.read(CHUNK):
                                h.update(block)
                                size += len(block)
                                d.write(block)
                        manifest["files"][arc] = [size, h.hexdigest()]
                    z.writestr("manifest.json", json.dumps(manifest))
                seal.finish()
                f.flush()
                os.fsync(f.fileno())
            _verify(part, key)
            part.replace(out)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        size = out.stat().st_size
        audit.record("backup_made", why=why, point=point, files=len(manifest["files"]), size=size)
        if not point:
            _set(last=datetime.now().isoformat(timespec="seconds"), last_path=str(out), last_error="")
        _prune(where, point)
        return {"path": str(out), "size": size, "files": len(manifest["files"]), "password": "password" in slots}
    except OSError as e:
        raise BackupError(f"Windows said: {e.strerror or e}") from None
    finally:
        shutil.rmtree(work, ignore_errors=True)
        _BUSY["what"] = ""
        _LOCK.release()


def _verify(path: Path, key: bytes) -> dict:
    """Every piece opens, every file is what the list in it says."""
    with open(path, "rb") as f:
        h, start, about = _header(f)
        try:
            with zipfile.ZipFile(io.BufferedReader(_Open(f, start, path.stat().st_size, key, about), CHUNK)) as z:
                m = json.loads(z.read("manifest.json"))
                names = set(z.namelist()) - {"manifest.json"}
                if names != set(m["files"]):
                    raise BackupError("That backup was changed or is damaged.")
                for arc, (size, want) in m["files"].items():
                    d, n = hashlib.sha256(), 0
                    with z.open(arc) as e:
                        while block := e.read(CHUNK):
                            d.update(block)
                            n += len(block)
                    if n != size or d.hexdigest() != want:
                        raise BackupError("That backup was changed or is damaged.")
        except (zipfile.BadZipFile, KeyError, ValueError, TypeError) as e:
            raise e if isinstance(e, BackupError) else BackupError("That backup was changed or is damaged.") from None
    return {"head": h, "manifest": m}


def _prune(where: Path, point: bool) -> None:
    """Old ones go: only files this made, by their name, and never the newest."""
    keep = 5 if point else _settings().get("keep") if _settings().get("keep") in KEEP else 7
    rx = re.compile(r"(Restore point|Personal Assistant) \d{4}-\d\d-\d\d \d\d\.\d\d\.\d\d( \(\d+\))?\.pabackup")
    mine = sorted((p for p in where.glob("*.pabackup") if (m := rx.fullmatch(p.name)) and (m[1] == "Restore point") == point), key=lambda p: p.name, reverse=True)
    for p in mine[keep:]:
        try:
            p.unlink()
        except OSError:
            pass


def listing() -> list[dict]:
    """The backups in your folder and the restore points, newest first (only their readable front is looked at)."""
    out = []
    for where, point in ((folder(), False), (points_dir(), True)):
        for p in list(where.glob("*.pabackup"))[:300] if where.is_dir() else []:
            try:
                with open(p, "rb") as f:
                    h = _header(f)[0]
                out.append({"path": str(p), "name": p.name, "made": str(h.get("made") or "")[:19], "app": str(h.get("app") or "")[:20], "why": str(h.get("why") or "")[:80], "size": p.stat().st_size, "point": point,
                            "password": isinstance(h["slots"].get("password"), dict), "here": bool(h["slots"].get("windows"))})
            except (OSError, BackupError):
                out.append({"path": str(p), "name": p.name, "made": "", "app": "", "why": "can't be read", "size": 0, "point": point, "password": False, "here": False})
    return sorted(out, key=lambda x: x["made"], reverse=True)


def _file(path: Any) -> Path:
    p = Path(str(path or "").strip().strip('"'))
    from . import guard
    if guard.elsewhere(str(p)) or not p.is_absolute():
        raise BackupError("Choose a file on this PC (a drive or a USB stick).")
    if p.suffix.lower() != ".pabackup" or not p.is_file():
        raise BackupError("That isn't a backup (.pabackup).")
    return p


def delete(path: Any) -> None:
    """To the Recycle Bin."""
    from . import audit
    from .tools import recycle
    p = _file(path)
    if not recycle(p):
        raise BackupError("Windows couldn't move it to the Recycle Bin.")
    audit.record("backup_deleted", name=p.name)


# ---------------- looking into one, and putting it back ----------------
PARTS = {"app": "Conversations, memories, planner and everything else in the database", "settings": "Settings, profile and alarms", "notes": "Notes", "vault": "The vault (with the password it had then)", "keys": "AI keys",
         "screenshots": "Pictures of the screen", "record": "Record of actions"}


def _part(arc: str) -> str:
    if arc == "data/assistant.db":
        return "app"
    if arc.startswith("data/audit"):
        return "record"
    return {"data": "settings", "notes": "notes", "vault": "vault", "secret": "keys", "screenshots": "screenshots"}.get(arc.split("/", 1)[0], "")


def look(path: Any, password: Any = None) -> dict:
    """What is in a backup. {"locked": True} when it needs its password."""
    from . import __version__, storage
    p = _file(path)
    with open(p, "rb") as f:
        h, _, _ = _header(f)
    key = _key_of(h, password)
    if key is None:
        if isinstance(h["slots"].get("password"), dict):
            if password:
                time.sleep(1)
                raise BackupError("That isn't the password of this backup.")
            return {"locked": True, "name": p.name, "made": h.get("made"), "app": h.get("app")}
        raise BackupError("This backup opens only with the Windows account it was made in (it has no password).")
    v = _verify(p, key)
    m = v["manifest"]
    if int(m.get("db") or 0) > len(storage.MIGRATIONS):
        raise BackupError(f"This backup is from a newer version of the app ({m.get('app')}); this is {__version__}. Update first.")
    parts: dict[str, list] = {}
    for arc, (size, _) in m["files"].items():
        if k := _part(arc):
            q = parts.setdefault(k, [0, 0])
            q[0] += 1
            q[1] += size
    return {"locked": False, "path": str(p), "name": p.name, "made": m["made"], "app": m["app"], "size": p.stat().st_size,
            "parts": [{"id": k, "name": PARTS[k], "files": n, "bytes": b} for k, (n, b) in sorted(parts.items(), key=lambda x: list(PARTS).index(x[0]))]}


def _safe(arc: str) -> bool:
    """A place inside the unpacking folder, and one we know."""
    return bool(re.fullmatch(r"(data/(assistant\.db|" + "|".join(re.escape(f) for f in FILES) + r")|secret/keys\.json|vault/(vault\.json|files/[0-9a-f]{24}\.bin)|(notes|screenshots)/[^\\:*?\"<>|\x00-\x1f]{1,200})", arc)) \
        and ".." not in arc.split("/") and not any(s.endswith((".", " ")) or not s for s in arc.split("/"))


def pending_dir() -> Path:
    return _data() / "restore.pending"


def prepare(path: Any, parts: Any, password: Any = None) -> dict:
    """Unpack the chosen parts, check them, and make a restore point of now. The exchange happens at the next start."""
    from . import audit
    want = {str(x) for x in parts} & set(PARTS) if isinstance(parts, list) else set()
    if not want:
        raise BackupError("Choose what to put back.")
    info = look(path, password)
    if info["locked"]:
        raise BackupError("This backup needs its password.")
    p = _file(path)
    with open(p, "rb") as f:
        h, start, about = _header(f)
        key = _key_of(h, password)
        point = make(point=True, why="before putting a backup back")
        pend, tmp = pending_dir(), _data() / "restore.tmp"
        shutil.rmtree(pend, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            with zipfile.ZipFile(io.BufferedReader(_Open(f, start, p.stat().st_size, key, about), CHUNK)) as z:
                m = json.loads(z.read("manifest.json"))
                picked = [a for a in m["files"] if _part(a) in want]
                if any(not _safe(a) for a in picked):
                    raise BackupError("There is something in that backup that doesn't belong there.")
                if sum(m["files"][a][0] for a in picked) > min(_free(_data()) - 300 * 2**20, 20 * 2**30) or any(m["files"][a][0] > MAX_ENTRY for a in picked):
                    raise BackupError("There isn't enough room on the drive to put that back.")
                for a in picked:
                    to = tmp / a
                    to.parent.mkdir(parents=True, exist_ok=True)
                    d, n = hashlib.sha256(), 0
                    with z.open(a) as e, open(to, "xb") as o:
                        while block := e.read(CHUNK):
                            d.update(block)
                            n += len(block)
                            if n > m["files"][a][0]:
                                break
                            o.write(block)
                    if [n, d.hexdigest()] != m["files"][a]:
                        raise BackupError("That backup was changed or is damaged.")
            for j in tmp.glob("data/*.json"):
                json.loads(j.read_text(encoding="utf-8"))
            db = tmp / "data" / "assistant.db"
            if db.is_file():
                c = sqlite3.connect(db)
                try:
                    if c.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise BackupError("The database in that backup isn't whole.")
                finally:
                    c.close()
            (tmp / "todo.json").write_text(json.dumps({"parts": sorted(want), "files": picked, "from": p.name, "point": point["path"]}), encoding="utf-8")
            tmp.replace(pend)
        except BackupError:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, sqlite3.Error) as e:
            shutil.rmtree(tmp, ignore_errors=True)
            raise BackupError(f"It couldn't be unpacked ({type(e).__name__}). Nothing was changed.") from None
    audit.record("restore_prepared", parts=sorted(want), name=p.name)
    return {"parts": sorted(want), "point": point["path"]}


def cancel_pending() -> None:
    shutil.rmtree(pending_dir(), ignore_errors=True)


def apply_pending() -> str:
    """At the start, before anything is opened: all of it, or everything as it was. Returns what to tell ("" for nothing)."""
    pend = pending_dir()
    todo = pend / "todo.json"
    if not todo.is_file():
        shutil.rmtree(pend, ignore_errors=True)
        return ""
    from . import audit
    from .config import NOTES_DIR, SCREENSHOT_DIR
    data, old = _data(), _data() / "restore.before"
    shutil.rmtree(old, ignore_errors=True)
    moved: list[tuple[Path, Path]] = []                  # (now there, where the one before is)
    put: list[Path] = []
    try:
        t = json.loads(todo.read_text(encoding="utf-8"))
        want = set(t["parts"])

        def away(p: Path) -> None:
            if p.exists():
                b = old / f"{len(moved)}-{p.name}"
                b.parent.mkdir(parents=True, exist_ok=True)
                _move(p, b)
                moved.append((p, b))

        def into(src: Path, to: Path) -> None:
            to.parent.mkdir(parents=True, exist_ok=True)
            _move(src, to)
            put.append(to)
        if "app" in want and (pend / "data" / "assistant.db").is_file():
            for n in ("assistant.db", "assistant.db-wal", "assistant.db-shm"):
                away(data / n)
            into(pend / "data" / "assistant.db", data / "assistant.db")
        for n in FILES:
            if (pend / "data" / n).is_file() and ("record" if n.startswith("audit") else "settings") in want:
                away(data / n)
                into(pend / "data" / n, data / n)
        for part, live in (("notes", NOTES_DIR), ("screenshots", SCREENSHOT_DIR), ("vault", data / "vault")):
            if part in want and (pend / part).is_dir():
                away(live)
                into(pend / part, live)
        k = pend / "secret" / "keys.json"
        if "keys" in want and k.is_file():
            from . import keystore
            away(data / "keys.dat")
            keystore.save({str(a): str(b) for a, b in json.loads(k.read_text(encoding="utf-8")).items() if keystore.is_secret(str(a))})
            put.append(data / "keys.dat")
    except Exception as e:
        for p in reversed(put):
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
            except OSError:
                pass
        for p, b in reversed(moved):
            try:
                _move(b, p)
            except OSError:
                pass
        shutil.rmtree(pend, ignore_errors=True)
        audit.record("restore_failed", why=type(e).__name__)
        return f"The backup couldn't be put back ({type(e).__name__}); everything is as it was."
    for d in (NOTES_DIR, SCREENSHOT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(pend, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    audit.record("restored", parts=t["parts"], name=str(t.get("from") or ""))
    return f"The backup is back in place: {str(t.get('from') or '')}. How it was before is in the restore points (Settings › Backup)."


def _move(a: Path, b: Path) -> None:
    for attempt in range(20):
        try:
            os.replace(a, b)
            return
        except PermissionError:                          # antivirus or the search index for a moment
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


# ---------------- by itself ----------------
def before_update() -> bool:
    """The first start of another version: a restore point, before the database is changed for it."""
    from . import __version__, schedule
    was = schedule.get_setting("app_version")
    if was == __version__:
        return False
    made = False
    if (_data() / "assistant.db").is_file():
        try:
            make(point=True, why=f"before {__version__}" + (f" (from {was})" if isinstance(was, str) else ""))
            made = True
        except BackupError as e:
            print(f"[backup] no restore point before the update: {e}")
    schedule.set_setting("app_version", __version__)
    return made


def due(now: datetime | None = None) -> bool:
    s = _settings()
    every = s.get("every") if s.get("every") in EVERY else "off"
    if every == "off":
        return False
    try:
        last = datetime.fromisoformat(str(s.get("last")))
    except ValueError:
        return True
    return (now or datetime.now()) - last >= (timedelta(hours=23) if every == "daily" else timedelta(days=6, hours=23))


_TRIED = {"at": 0.0}


def tick(now: datetime, notify) -> int:
    """Every few seconds; a backup that is due is made in the background (after a failure again in an hour)."""
    if not due(now) or _BUSY["what"] or time.monotonic() < _TRIED["at"]:
        return 0
    _TRIED["at"] = time.monotonic() + 3600

    def go() -> None:
        try:
            make(why="by itself")
        except BackupError as e:
            before = _settings().get("last_error")
            _set(last_error=str(e))
            if str(e) != before:
                notify(f"The automatic backup didn't work: {e}", "info")
    threading.Thread(target=go, name="backup", daemon=True).start()
    return 1


def settings() -> dict:
    s = _settings()
    return {"every": s.get("every") if s.get("every") in EVERY else "off", "keep": s.get("keep") if s.get("keep") in KEEP else 7, "folder": str(folder()), "keys": s.get("keys") is True, "shots": s.get("shots") is True,
            "last": str(s.get("last") or ""), "last_path": str(s.get("last_path") or ""), "last_error": str(s.get("last_error") or ""), "password": has_password(), "busy": _BUSY["what"], "pending": (pending_dir() / "todo.json").is_file()}


def set_settings(d: dict) -> None:
    from . import audit, guard
    new: dict[str, Any] = {}
    if "every" in d:
        if d["every"] not in EVERY:
            raise BackupError("Choose daily, weekly or off.")
        new["every"] = d["every"]
    if "keep" in d:
        if isinstance(d["keep"], bool) or d["keep"] not in KEEP:
            raise BackupError("Choose one of the numbers in the list.")
        new["keep"] = d["keep"]
    for k in ("keys", "shots"):
        if k in d:
            new[k] = d[k] is True
    if "folder" in d:
        raw = str(d["folder"] or "").strip().strip('"')
        if not raw:
            new["folder"] = ""
        else:
            p = Path(os.path.expandvars(raw))
            if guard.elsewhere(str(p)) or not p.is_absolute():
                raise BackupError("Choose a folder on this PC (a drive or a USB stick).")
            try:
                if _data().resolve() in (p.resolve(), *p.resolve().parents):
                    raise BackupError("Not inside the app's own data: choose another folder.")
                p.mkdir(parents=True, exist_ok=True)
                t = p / f".pa-{secrets.token_hex(4)}"
                t.write_bytes(b"")
                t.unlink()
            except OSError as e:
                raise BackupError(f"That folder can't be used: {e.strerror or e}") from None
            new["folder"] = str(p)
    _set(**new)
    audit.record("backup_settings", **{k: v for k, v in new.items() if k != "folder"})


def page() -> dict:
    return {"settings": settings(), "list": listing(), "every": EVERY, "keep": KEEP}

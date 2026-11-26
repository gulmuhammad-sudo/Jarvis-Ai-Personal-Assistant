"""Finding things in your documents (Phase 7): a word index of the folders you choose, kept in the local database (SQLite
FTS5). Nothing leaves the PC. Only text is kept; password and key files are never read. Updating runs in the background,
reads only new or changed files, and Emergency Stop ends it.
"""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import documents, guard

KINDS = documents.OFFICE | {".pdf", ".txt", ".md", ".csv", ".rtf", ".html", ".htm"}
MAX_FOLDERS = 20
MAX_FILES = 5000
MAX_SIZE = 30 * 2**20
CHUNK = 1200
PER_FILE = 300_000
SKIP_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", "appdata", "$recycle.bin", "system volume information", "windows"}
_STATE: dict = {"running": False, "done": 0, "total": 0, "file": "", "message": ""}
_RUN = threading.Lock()
CHANGED: Callable[[], None] | None = None


def _db():
    from . import storage
    return storage.conn(), storage._LOCK


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def check_folder(path: str) -> Path:
    """A folder that may be indexed: on this PC, not a whole drive, not Windows' or programs' own folders."""
    raw = str(path or "").strip().strip("\"'")
    if not raw or guard.elsewhere(raw):
        raise ValueError("Choose a folder on this PC.")
    p = Path(os.path.expandvars(os.path.expanduser(raw))).resolve()
    if not p.is_dir() or guard.elsewhere(str(p)):
        raise ValueError(f"There's no folder at {p}.")
    if p == Path(p.anchor) or p == Path(os.environ.get("USERPROFILE", str(Path.home()))).resolve() or p == Path(os.environ.get("USERPROFILE", "")).resolve().parent:
        raise ValueError("That's too much at once. Choose a folder inside it, like Documents.")
    low = [x.lower() for x in p.parts]
    own = [Path(os.environ[k]).resolve() for k in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData") if os.environ.get(k)]
    if os.environ.get("APPDATA"):
        own.append(Path(os.environ["APPDATA"]).resolve().parent)
    if any(p == q or q in p.parents for q in own) or any(x in SKIP_DIRS - {"appdata"} or x.startswith((".ssh", ".aws", ".gnupg")) for x in low):
        raise ValueError("That folder belongs to Windows or a program.")
    return p


def folders() -> list[dict]:
    c, lock = _db()
    with lock:
        rows = c.execute("SELECT f.id, f.path, f.added, COUNT(d.id) FROM doc_folders f LEFT JOIN docs d ON d.folder = f.id GROUP BY f.id ORDER BY f.path").fetchall()
    return [{"id": r[0], "path": r[1], "added": r[2], "files": r[3]} for r in rows]


def add_folder(path: str) -> dict:
    p = check_folder(path)
    have = folders()
    for f in have:
        q = Path(f["path"])
        if q == p or q in p.parents:
            raise ValueError("That folder is already covered.")
    if len(have) >= MAX_FOLDERS:
        raise ValueError(f"Up to {MAX_FOLDERS} folders.")
    for f in have:                                # a folder around one you had: it takes its place
        if p in Path(f["path"]).parents:
            remove_folder(f["id"])
    c, lock = _db()
    with lock, c:
        i = c.execute("INSERT INTO doc_folders(path, added) VALUES (?, ?)", (str(p), _now())).lastrowid
    return next(f for f in folders() if f["id"] == i)


def _forget(c, doc_id: int) -> None:
    c.execute("DELETE FROM doc_text WHERE doc = ?", (doc_id,))
    c.execute("DELETE FROM docs WHERE id = ?", (doc_id,))


def remove_folder(folder_id: int) -> bool:
    c, lock = _db()
    with lock, c:
        for (i,) in c.execute("SELECT id FROM docs WHERE folder = ?", (int(folder_id),)).fetchall():
            _forget(c, i)
        return bool(c.execute("DELETE FROM doc_folders WHERE id = ?", (int(folder_id),)).rowcount)


def status() -> dict:
    c, lock = _db()
    with lock:
        n, bad, last = c.execute("SELECT COUNT(*), COALESCE(SUM(error != ''), 0), MAX(read_at) FROM docs").fetchone()
    return {**_STATE, "files": n, "unread": bad, "last": last, "folders": folders()}


def chunks(text: str) -> list[str]:
    """Pieces of about 1200 characters, cut at line ends or sentences where possible."""
    out, text = [], text.strip()
    while text:
        if len(text) <= CHUNK:
            out.append(text)
            break
        cut = max(text.rfind("\n", CHUNK // 2, CHUNK), text.rfind(". ", CHUNK // 2, CHUNK) + 1, text.rfind("۔", CHUNK // 2, CHUNK) + 1)
        cut = cut if cut > 0 else (text.rfind(" ", CHUNK // 2, CHUNK) if text.rfind(" ", CHUNK // 2, CHUNK) > 0 else CHUNK)
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    return [x for x in out if x]


def _walk(root: Path, stop: Callable[[], bool]):
    base = root.resolve()
    for d, subs, names in os.walk(root):
        if stop():
            return
        subs[:] = [s for s in subs if s.lower() not in SKIP_DIRS and not s.startswith(".") and not os.path.islink(os.path.join(d, s))
                   and not os.path.isjunction(os.path.join(d, s))]
        for n in names:
            p = Path(d, n)
            if p.suffix.lower() not in KINDS or n.startswith(("~$", "~pa-", ".")) or guard.secret_file(str(p)):
                continue
            try:
                if p.is_symlink() and base not in p.resolve().parents:
                    continue                      # a link out of the folder isn't in the folder
                st = p.stat()
            except OSError:
                continue
            if 0 < st.st_size <= MAX_SIZE:
                yield p, st


def update(stop: Callable[[], bool] = lambda: False) -> str:
    """Read what's new or changed in the chosen folders, and forget what's gone. One at a time."""
    if not _RUN.acquire(blocking=False):
        return "It's already being updated."
    _STATE.update(running=True, done=0, total=0, file="", message="")
    new = bad = gone = 0
    try:
        c, lock = _db()
        found: list[tuple[int, Path, os.stat_result]] = []
        missing_roots = set()
        for f in folders():
            root = Path(f["path"])
            if not root.is_dir():                 # an unplugged drive: keep what we know
                missing_roots.add(f["id"])
                continue
            for p, st in _walk(root, stop):
                found.append((f["id"], p, st))
                if len(found) >= MAX_FILES:
                    break
        full = len(found) >= MAX_FILES
        with lock:
            have = {r[1]: r for r in c.execute("SELECT id, path, mtime, size, folder FROM docs").fetchall()}
        todo = [(fid, p, st) for fid, p, st in found if (r := have.get(str(p))) is None or r[2] != int(st.st_mtime) or r[3] != st.st_size]
        _STATE["total"] = len(todo)
        here = {str(p) for _, p, _ in found}
        if not stop() and not full:
            with lock, c:
                for path, r in have.items():
                    if path not in here and r[4] not in missing_roots:
                        _forget(c, r[0])
                        gone += 1
        for n, (fid, p, st) in enumerate(todo, 1):
            if stop():
                break
            _STATE.update(done=n - 1, file=p.name)
            if CHANGED and n % 5 == 1:
                CHANGED()
            error, pieces = "", []
            try:
                total = 0
                for label, text in documents.parts(p, seconds=30):
                    for piece in chunks(text[:PER_FILE - total]):
                        pieces.append((label, piece))
                    total += len(text)
                    if total >= PER_FILE:
                        break
                if not pieces:
                    error = "no text in it"
            except (ValueError, OSError) as e:
                error = str(e)[:200]
            with lock, c:
                old = c.execute("SELECT id FROM docs WHERE path = ?", (str(p),)).fetchone()
                if old:
                    _forget(c, old[0])
                i = c.execute("INSERT INTO docs(path, folder, mtime, size, read_at, error) VALUES (?, ?, ?, ?, ?, ?)",
                              (str(p), fid, int(st.st_mtime), st.st_size, _now(), error)).lastrowid
                c.executemany("INSERT INTO doc_text(text, doc, part) VALUES (?, ?, ?)", [(t, i, label) for label, t in pieces])
            new, bad = new + (not error), bad + bool(error)
            _STATE["done"] = n
        msg = f"Read {new} new or changed file(s)" + (f", {bad} had no readable text" if bad else "") + (f", forgot {gone}" if gone else "") + (
            " (stopped early)" if stop() else "") + (f". There are more than {MAX_FILES} files; choose smaller folders" if full else "") + "."
        _STATE["message"] = msg
        return msg
    finally:
        _STATE.update(running=False, file="")
        _RUN.release()
        if CHANGED:
            CHANGED()


def start() -> bool:
    """Update in the background. False when it's already running."""
    if _STATE["running"]:
        return False
    from . import tools
    threading.Thread(target=lambda: update(tools.STOP.is_set), daemon=True, name="doc-index").start()
    return True


def match(query: str) -> str:
    """Any words -> an FTS5 question: the words themselves, never FTS5's own language; the last one may be unfinished."""
    words = re.findall(r"[\w\u0600-\u06FF]+", str(query or ""), re.U)[:12]
    if not words:
        return ""
    return " OR ".join(f'"{w}"' + ("*" if len(w) > 2 else "") for w in words)


def search(query: str, limit: int = 8, per_file: int = 2) -> list[dict]:
    q = match(query)
    if not q:
        return []
    c, lock = _db()
    with lock:
        rows = c.execute("SELECT t.doc, t.part, snippet(doc_text, 0, '', '', ' … ', 48), bm25(doc_text), d.path, t.text FROM doc_text t "
                         "JOIN docs d ON d.id = t.doc WHERE doc_text MATCH ? ORDER BY bm25(doc_text) LIMIT 80", (q,)).fetchall()
    words = [w.lower() for w in re.findall(r"[\w\u0600-\u06FF]+", query, re.U)]
    # pieces with more of the words first, then FTS5's own order
    ranked = sorted(rows, key=lambda r: (-sum(w in r[5].lower() for w in words), r[3]))
    out, count = [], {}
    for doc, part, snip, _, path, _ in ranked:
        if count.get(doc, 0) >= per_file:
            continue
        count[doc] = count.get(doc, 0) + 1
        out.append({"id": doc, "path": path, "name": Path(path).name, "part": part, "text": " ".join(snip.split())})
        if len(out) >= limit:
            break
    return out


def path_of(doc_id: int) -> Path | None:
    c, lock = _db()
    with lock:
        r = c.execute("SELECT path FROM docs WHERE id = ?", (int(doc_id),)).fetchone()
    return Path(r[0]) if r else None

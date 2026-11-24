"""Screen recording (Phase 8): never silent, never the assistant's idea.

The page records: Windows' / Edge's own box asks each time what to share (getDisplayMedia can't start without a click and that
box). This file only keeps the pieces as one file in Videos\\Personal Assistant, and what the red bar shows. No tool, agent,
automation or plan gets here.
"""
from __future__ import annotations

import os
import re
import secrets
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

MAX_SECONDS = 4 * 3600
MAX_BYTES = 8 * 1024 ** 3
MAX_PIECE = 64 * 1024 ** 2
LEAVE_FREE = 1024 ** 3                       # always left on the drive
SILENT_FOR = 30                              # no piece for this long: the page is gone, the file is closed
KINDS = {"video/webm": ".webm", "video/mp4": ".mp4"}


def folder() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Videos" / "Personal Assistant"


class Recording:
    """The one recording that may run."""

    def __init__(self, changed: Callable[[dict | None], None] = lambda s: None, ended: Callable[[str, str], None] = lambda path, why: None):
        self.changed, self.ended = changed, ended
        self._lock = threading.RLock()
        self._r: dict | None = None

    def state(self) -> dict | None:
        with self._lock:
            r = self._r
            return None if r is None else {"id": r["id"], "seconds": int(time.time() - r["started"]), "paused": r["paused"], "bytes": r["bytes"], "mic": r["mic"], "sound": r["sound"], "name": r["final"].name}

    def start(self, kind: Any, mic: Any, sound: Any, agree: Any) -> dict:
        if agree is not True:
            raise ValueError("Start it with the button.")
        base = str(kind or "").split(";")[0].strip().lower()
        if base not in KINDS:
            raise ValueError("That kind of video can't be kept.")
        with self._lock:
            if self._r is not None:
                raise ValueError("A recording is already running.")
            d = folder()
            d.mkdir(parents=True, exist_ok=True)
            recover(d)
            if shutil.disk_usage(d).free < LEAVE_FREE * 2:
                raise ValueError("There is too little free space for a recording (2 GB are needed).")
            stem, n = f"Recording {datetime.now():%Y-%m-%d %H.%M.%S}", 1
            while (final := d / f"{stem}{f' ({n})' if n > 1 else ''}{KINDS[base]}").exists() or final.with_suffix(final.suffix + ".part").exists():
                n += 1
            part = final.with_suffix(final.suffix + ".part")
            self._r = {"id": secrets.token_urlsafe(12), "started": time.time(), "last": time.time(), "next": 0, "bytes": 0, "paused": False, "mic": bool(mic), "sound": bool(sound), "final": final, "part": part,
                       "f": open(part, "xb")}
            threading.Thread(target=self._watch, args=(self._r["id"],), name="screenrec", daemon=True).start()
            st = self.state()
        self.changed(st)
        return st

    def _mine(self, rid: Any) -> dict:
        r = self._r
        if r is None or not secrets.compare_digest(str(rid or ""), r["id"]):
            raise ValueError("That recording isn't running.")
        return r

    def piece(self, rid: Any, n: Any, data: bytes) -> None:
        why = ""
        with self._lock:
            r = self._mine(rid)
            if int(n) != r["next"]:
                raise ValueError("A piece of the recording is missing.")
            if len(data) > MAX_PIECE:
                raise ValueError("That piece is too large.")
            r["f"].write(data)
            r["next"], r["bytes"], r["last"] = r["next"] + 1, r["bytes"] + len(data), time.time()
            if r["bytes"] > MAX_BYTES:
                why = "it reached 8 GB"
            elif time.time() - r["started"] > MAX_SECONDS:
                why = "it reached four hours"
            elif shutil.disk_usage(r["part"].parent).free < LEAVE_FREE:
                why = "the drive is nearly full"
        if why:
            self.stop(why)

    def pause(self, rid: Any, on: bool) -> None:
        with self._lock:
            self._mine(rid)["paused"] = bool(on)
            st = self.state()
        self.changed(st)

    def stop(self, why: str = "you stopped it", rid: Any = None) -> str:
        """Close the file. The page is told through changed(None) and stops its recorder."""
        with self._lock:
            r = self._r
            if r is None:
                return ""
            if rid is not None:
                self._mine(rid)
            self._r = None
            r["f"].close()
            path = ""
            if r["bytes"]:
                os.replace(r["part"], r["final"])
                path = str(r["final"])
            else:
                r["part"].unlink(missing_ok=True)
        self.changed(None)
        self.ended(path, why)
        return path

    def _watch(self, rid: str) -> None:
        while True:
            time.sleep(2)
            with self._lock:
                r = self._r
                if r is None or r["id"] != rid:
                    return
                gone = time.time() - r["last"] > SILENT_FOR and not r["paused"]
                long = time.time() - r["last"] > 1800
            if gone or long:
                self.stop("the window was closed" if gone else "it was paused for half an hour")
                return


def recover(d: Path | None = None) -> int:
    """Recordings that were cut short (a crash, the power) keep what there is."""
    d, n = d or folder(), 0
    if not d.is_dir():
        return 0
    for p in d.glob("Recording *.part"):
        try:
            if p.stat().st_size == 0:
                p.unlink()
                continue
            final = p.with_suffix("")
            stem, k = final.stem + " (cut short)", 1
            while (final := p.parent / f"{stem}{f' {k}' if k > 1 else ''}{Path(p.stem).suffix}").exists():
                k += 1
            os.replace(p, final)
            n += 1
        except OSError:                          # still being written
            pass
    return n


_NAME = re.compile(r"Recording [\w .()-]{10,60}\.(webm|mp4)")


def listing(limit: int = 60) -> list[dict]:
    d = folder()
    rows = []
    if d.is_dir():
        for p in d.iterdir():
            if _NAME.fullmatch(p.name):
                s = p.stat()
                rows.append({"name": p.name, "size": s.st_size, "at": datetime.fromtimestamp(s.st_mtime).strftime("%Y-%m-%dT%H:%M")})
    return sorted(rows, key=lambda r: r["at"], reverse=True)[:limit]


def path_of(name: Any) -> Path | None:
    n = str(name or "")
    p = folder() / n
    return p if _NAME.fullmatch(n) and p.is_file() and not p.is_symlink() else None


def recycle(name: Any) -> None:
    p = path_of(name)
    if not p:
        raise ValueError("That recording is gone.")
    from .tools import _ps, _ps_quote
    r = _ps("Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile("
            f"'{_ps_quote(p)}', 'OnlyErrorDialogs', 'SendToRecycleBin')")
    if p.exists():
        raise ValueError(f"It couldn't be moved to the Recycle Bin. {(r.stderr or '').strip()[:120]}")

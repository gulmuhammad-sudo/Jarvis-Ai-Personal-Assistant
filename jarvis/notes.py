"""Notes manager (Phase 7): the .md notes in the notes folder, with search, reading, changing and deleting.

A note is named by its file name, never by a path: names with folders, drives or streams are refused, and the file must
really lie in the notes folder. Deleting moves to the Recycle Bin.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import config

MAX_CHARS = 200_000


def _dir() -> Path:
    return config.NOTES_DIR


def path_of(name: str) -> Path:
    """The file of a note. ValueError for anything but a plain note name."""
    n = str(name or "").strip()
    if not n or len(n) > 120 or re.search(r'[\\/:*?"<>|\x00-\x1f]', n) or n.startswith(".") or n.endswith((".", " ")):
        raise ValueError("That isn't the name of a note.")
    p = _dir() / (n if n.lower().endswith(".md") else n + ".md")
    if p.parent.resolve() != _dir().resolve() or (p.exists() and p.resolve().parent != _dir().resolve()):
        raise ValueError("That isn't the name of a note.")
    if re.match(r"(con|prn|aux|nul|com\d|lpt\d)(\.|$)", n, re.I):
        raise ValueError("Windows doesn't allow that name.")
    return p


def _row(p: Path, text: str | None = None) -> dict:
    text = p.read_text(encoding="utf-8", errors="replace") if text is None else text
    return {"name": p.stem, "modified": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes"), "chars": len(text),
            "preview": " ".join(text[:400].split())[:160]}


def all_notes(query: str = "") -> list[dict]:
    """Newest change first; with a query, only notes with all its words in the name or text."""
    words = [w for w in str(query or "").lower().split() if w]
    out = []
    for p in _dir().glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            hay = f"{p.stem}\n{text}".lower()
            if not all(w in hay for w in words):
                continue
            row = _row(p, text)
            if words:
                at = min((i for i in (text.lower().find(w) for w in words) if i >= 0), default=0)
                row["preview"] = ("… " if at > 60 else "") + " ".join(text[max(0, at - 60):at + 120].split())
            out.append(row)
        except OSError:
            continue
    return sorted(out, key=lambda r: r["modified"], reverse=True)


def find(name: str) -> str | None:
    """The note's exact name from a name or its beginning / words, when only one fits."""
    n = " ".join(str(name or "").lower().removesuffix(".md").split())
    names = [p.stem for p in _dir().glob("*.md")]
    exact = [x for x in names if x.lower() == n]
    part = [x for x in names if n and all(w in x.lower() for w in n.split())]
    return exact[0] if exact else part[0] if len(part) == 1 else None


def read(name: str) -> str:
    p = path_of(name)
    if not p.is_file():
        raise ValueError("There's no note with that name.")
    return p.read_text(encoding="utf-8", errors="replace")[:MAX_CHARS]


def save(name: str, text: str, new: bool = False) -> dict:
    p = path_of(name)
    if len(str(text)) > MAX_CHARS:
        raise ValueError("That note is too long.")
    if new and p.exists():
        raise ValueError("There's already a note with that name.")
    if not new and not p.is_file():
        raise ValueError("There's no note with that name.")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(str(text), encoding="utf-8")        # never half a note if the PC stops in between
    tmp.replace(p)
    return _row(p)


def rename(name: str, to: str) -> dict:
    p, q = path_of(name), path_of(to)
    if not p.is_file():
        raise ValueError("There's no note with that name.")
    if q.exists() and q.resolve() != p.resolve():
        raise ValueError("There's already a note with that name.")
    p.rename(q)
    return _row(q)


def delete(name: str) -> bool:
    """To the Recycle Bin. False when it could not be moved there (then it stays)."""
    from .tools import recycle
    p = path_of(name)
    if not p.is_file():
        raise ValueError("There's no note with that name.")
    return recycle(p)

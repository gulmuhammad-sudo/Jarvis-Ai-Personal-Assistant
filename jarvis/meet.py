"""Meetings (Phase 8): agenda, notes, decisions, actions, and (only if you start it) writing down what is said.

Writing down is never silent and never the assistant's idea: only the owner's button starts it, each time with a tick that
everyone knows and agrees; a red bar shows on every page; Emergency Stop ends it. Sound is never saved: it goes piece by piece
to the chosen speech-to-text (this PC, or Groq if the owner picks it) and only the text is kept, in the local database.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
from datetime import date, datetime
from typing import Any, Callable

from .planner import _db, _now, _text, parse_clock, parse_day

MAX_MEETINGS = 2000
MAX_NOTES = 20_000
MAX_TRANSCRIPT = 400_000                    # characters: many hours
MAX_ACTIONS = 100
MAX_SECONDS = 4 * 3600                      # one recording
PART = 6000                                 # characters of a transcript the AI gets at once
PIECE_MIN, PIECE_MAX = 6.0, 26.0            # seconds of sound written down at a time
ENGINES = ("local", "groq")

_M = "id, title, at, people, agenda, notes, decisions, summary, actions, length(transcript), created"


def _row(r) -> dict:
    m = dict(zip(("id", "title", "at", "people", "agenda", "notes", "decisions", "summary", "actions", "said", "created"), r))
    m["actions"] = json.loads(m["actions"] or "[]")
    return m


def meetings(query: str = "", limit: int = 200) -> list[dict]:
    words = str(query or "").split()[:8]
    where = " AND ".join("(title || ' ' || people || ' ' || agenda || ' ' || notes || ' ' || decisions || ' ' || summary || ' ' || transcript) LIKE ? ESCAPE '\\'" for _ in words)
    args = ["%" + re.sub(r"([\\%_])", r"\\\1", w) + "%" for w in words]
    c, lock = _db()
    with lock:
        return [_row(r) for r in c.execute(f"SELECT {_M} FROM meetings" + (f" WHERE {where}" if words else "") + " ORDER BY at DESC, id DESC LIMIT ?", (*args, limit)).fetchall()]


def get(meeting_id: Any) -> dict | None:
    c, lock = _db()
    with lock:
        r = c.execute(f"SELECT {_M} FROM meetings WHERE id = ?", (int(meeting_id),)).fetchone()
    return _row(r) if r else None


def find(ref: Any) -> dict | None:
    """By number, whole title, or words that fit only one. Nothing said: the latest."""
    s = str(ref if ref is not None else "").strip()
    rows = meetings(limit=MAX_MEETINGS)
    if not s:
        return rows[0] if rows else None
    if s.lstrip("#").isdigit():
        return next((m for m in rows if m["id"] == int(s.lstrip("#"))), None)
    low = s.casefold()
    for hits in ([m for m in rows if m["title"].casefold() == low], [m for m in rows if all(w in f"{m['title']} {m['people']}".casefold() for w in low.split())]):
        if len(hits) == 1:
            return hits[0]
    return None


def transcript(meeting_id: Any) -> str:
    c, lock = _db()
    with lock:
        r = c.execute("SELECT transcript FROM meetings WHERE id = ?", (int(meeting_id),)).fetchone()
    return r[0] if r else ""


def save(title: Any = None, day: Any = None, at: Any = None, people: Any = None, agenda: Any = None, notes: Any = None, decisions: Any = None,
         summary: Any = None, meeting_id: int | None = None) -> dict:
    old = get(meeting_id) if meeting_id is not None else None
    if meeting_id is not None and not old:
        raise ValueError("That meeting is gone.")
    o = old or {"title": "", "at": datetime.now().isoformat(timespec="minutes"), "people": "", "agenda": "", "notes": "", "decisions": "", "summary": ""}
    d = parse_day(day).isoformat() if day else o["at"][:10]
    hour = parse_clock(str(at)) if at else o["at"][11:16]
    row = (_text(o["title"] if title is None else title, 120, "The meeting's name") or f"Meeting {d}", f"{d}T{hour}",
           _text(o["people"] if people is None else people, 500, "The people"), _text(o["agenda"] if agenda is None else agenda, MAX_NOTES, "The agenda"),
           _text(o["notes"] if notes is None else notes, MAX_NOTES, "The notes"), _text(o["decisions"] if decisions is None else decisions, MAX_NOTES, "The decisions"),
           _text(o["summary"] if summary is None else summary, MAX_NOTES, "The summary"))
    c, lock = _db()
    with lock, c:
        if meeting_id is None:
            if c.execute("SELECT count(*) FROM meetings").fetchone()[0] >= MAX_MEETINGS:
                raise ValueError(f"That's {MAX_MEETINGS} meetings. Remove some first.")
            meeting_id = c.execute("INSERT INTO meetings (title, at, people, agenda, notes, decisions, summary, created) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (*row, _now())).lastrowid
        else:
            c.execute("UPDATE meetings SET title = ?, at = ?, people = ?, agenda = ?, notes = ?, decisions = ?, summary = ? WHERE id = ?", (*row, meeting_id))
    return get(meeting_id)


def delete(meeting_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM meetings WHERE id = ?", (int(meeting_id),)).rowcount > 0


def clear_transcript(meeting_id: Any) -> None:
    c, lock = _db()
    with lock, c:
        c.execute("UPDATE meetings SET transcript = '' WHERE id = ?", (int(meeting_id),))


# ---------------- actions ----------------
def add_action(meeting_id: Any, text: Any, who: Any = "", due: Any = "") -> dict:
    m = get(meeting_id)
    if not m:
        raise ValueError("That meeting is gone.")
    if len(m["actions"]) >= MAX_ACTIONS:
        raise ValueError(f"That's {MAX_ACTIONS} actions.")
    a = {"text": _text(text, 160, "The action", True), "who": _text(who, 60, "Who"), "due": parse_day(due).isoformat() if str(due or "").strip() else "", "task": None}
    if any(x["text"].casefold() == a["text"].casefold() and x["who"].casefold() == a["who"].casefold() for x in m["actions"]):
        return m
    return _actions(m["id"], [*m["actions"], a])


def _actions(meeting_id: int, rows: list[dict]) -> dict:
    c, lock = _db()
    with lock, c:
        c.execute("UPDATE meetings SET actions = ? WHERE id = ?", (json.dumps(rows, ensure_ascii=False), meeting_id))
    return get(meeting_id)


def remove_action(meeting_id: Any, n: Any) -> dict:
    m = get(meeting_id)
    if not m or not 0 <= int(n) < len(m["actions"]):
        raise ValueError("That action is gone.")
    return _actions(m["id"], [a for i, a in enumerate(m["actions"]) if i != int(n)])


def action_task(meeting_id: Any, n: Any) -> dict:
    """The action as a task in the Planner; once."""
    from . import planner
    m = get(meeting_id)
    if not m or not 0 <= int(n) < len(m["actions"]):
        raise ValueError("That action is gone.")
    a = m["actions"][int(n)]
    if a.get("task") and planner.get_task(a["task"]):
        raise ValueError("That is already a task.")
    t = planner.save_task(title=(a["text"] + (f" ({a['who']})" if a["who"] else ""))[:planner.MAX_TITLE], notes=f"From the meeting: {m['title']}", due=a["due"] or None)
    a["task"] = t["id"]
    return _actions(m["id"], m["actions"])


# ---------------- what the AI reads ----------------
def describe(m: dict) -> str:
    extra = [f"with {m['people']}" if m["people"] else "", f"{len(m['actions'])} action{'' if len(m['actions']) == 1 else 's'}" if m["actions"] else "",
             f"{m['said'] // 1000 + 1}k characters written down" if m["said"] else ""]
    return f"#{m['id']} {m['title']}, {m['at'].replace('T', ' ')}" + "".join(f", {x}" for x in extra if x)


def describe_full(m: dict) -> str:
    out = [describe(m)] + [f"{k.title()}: {m[k]}" for k in ("agenda", "notes", "decisions", "summary") if m[k]]
    if m["actions"]:
        out.append("Actions: " + "; ".join(a["text"] + (f" ({a['who']})" if a["who"] else "") + (f", due {a['due']}" if a["due"] else "") + (" [a task]" if a.get("task") else "") for a in m["actions"]))
    return "\n".join(out)


def part(meeting_id: Any, n: Any = 1) -> tuple[str, int, int]:
    """(text, which part, how many): cut between lines."""
    text, parts = transcript(meeting_id), []
    while text:
        cut = len(text) if len(text) <= PART else (text.rfind("\n", PART // 2, PART) + 1 or PART)
        parts.append(text[:cut])
        text = text[cut:]
    i = min(max(1, int(n or 1)), len(parts) or 1)
    return (parts[i - 1] if parts else ""), i, len(parts)


_YES: dict[int, float] = {}                 # transcripts the owner let the AI read in this conversation (for half an hour)


def allow(meeting_id: int) -> None:
    _YES[int(meeting_id)] = time.monotonic()


def allowed(meeting_id: int) -> bool:
    return int(meeting_id) in _YES and time.monotonic() - _YES[int(meeting_id)] < 1800


def forget_yes() -> None:
    _YES.clear()


# ---------------- writing down ----------------
def engines() -> dict[str, bool]:
    import os
    from . import local_stt
    return {"local": local_stt.ready(), "groq": bool(os.environ.get("GROQ_API_KEY"))}


def _write_down(wav: bytes, engine: str, language: str) -> str:
    """One piece, with the chosen engine only (never another one: the owner chose where the sound goes)."""
    from . import stt
    if engine == "local":
        return stt._clean(stt._local(wav, language))
    return stt._clean(stt._whisper(wav, language))


def append(meeting_id: int, text: str) -> bool:
    """Add to the transcript; False when it is full or the meeting was deleted."""
    c, lock = _db()
    with lock, c:
        return c.execute("UPDATE meetings SET transcript = transcript || ? WHERE id = ? AND length(transcript) + ? <= ?", (text, meeting_id, len(text), MAX_TRANSCRIPT)).rowcount > 0


class Scribe:
    """Listens and writes down, until stopped. source() gives blocks of sound (numpy, 1 channel) at .rate, or None at the end."""

    def __init__(self, meeting_id: int, engine: str, language: str, source, changed: Callable[[dict], None], ended: Callable[[str], None],
                 write: Callable[[bytes, str, str], str] = _write_down):
        self.meeting_id, self.engine, self.language = meeting_id, engine, language
        self.source, self.changed, self.ended, self.write = source, changed, ended, write
        self.started, self.paused, self.off = time.time(), False, threading.Event()
        self.pieces: queue.Queue = queue.Queue(maxsize=200)
        self.waiting, self.words, self.failed, self.reason = 0, 0, 0, ""
        self.active = True
        m = get(meeting_id)
        self.title = m["title"] if m else ""

    def start(self) -> "Scribe":
        append(self.meeting_id, f"\n[{datetime.now():%d %b %Y %H:%M}, writing started]\n")
        threading.Thread(target=self._listen, name="meeting-listen", daemon=True).start()
        threading.Thread(target=self._writer, name="meeting-write", daemon=True).start()
        self.changed(self.state())
        return self

    def state(self) -> dict:
        return {"active": self.active, "meeting": self.meeting_id, "title": self.title, "engine": self.engine, "paused": self.paused, "seconds": int(time.time() - self.started),
                "waiting": self.waiting, "words": self.words, "failed": self.failed}

    def pause(self, on: bool) -> None:
        self.paused = bool(on)
        self.changed(self.state())

    def stop(self, reason: str = "stopped") -> None:
        self.reason = self.reason or reason
        self.off.set()

    # -- sound in: cut where someone breathes
    def _listen(self) -> None:
        import numpy as np
        from . import recorder
        buf, seconds, quiet, voiced, floor = [], 0.0, 0.0, False, float("inf")
        try:
            rate = self.source.rate
            while not self.off.is_set():
                x = self.source.read()
                if x is None:
                    self.stop("the microphone stopped")
                    break
                if time.time() - self.started > MAX_SECONDS:
                    self.stop("it reached four hours")
                    break
                if self.paused:
                    buf, seconds, quiet, voiced = [], 0.0, 0.0, False
                    continue
                buf.append(x)
                dt = x.size / rate
                rms = recorder._voice_rms(x, rate)
                floor = rms if rms < floor else floor * 0.998 + rms * 0.002
                loud = rms > max(0.004, min(floor * 2.2, 0.03))         # (a meeting that starts in the middle of a sentence has no quiet to compare with)
                voiced, quiet, seconds = voiced or loud, 0.0 if loud else quiet + dt, seconds + dt
                if (seconds >= PIECE_MIN and quiet >= 0.5) or seconds >= PIECE_MAX:
                    if voiced:
                        self._put(np.concatenate(buf), rate)
                    buf, seconds, quiet, voiced = [], 0.0, 0.0, False
            if buf and voiced and not self.paused and seconds > 0.6:
                self._put(np.concatenate(buf), rate)
        except Exception as e:
            print(f"[meeting] {type(e).__name__}: {e}")
            self.stop("the microphone stopped")
        finally:
            try:
                self.source.close()
            except Exception:
                pass
            self.pieces.put(None)

    def _put(self, x, rate) -> None:
        from . import recorder
        try:
            self.pieces.put_nowait((datetime.now(), recorder._to_wav(x, rate)))
            self.waiting += 1
        except queue.Full:
            self.failed += 1

    # -- text out
    def _writer(self) -> None:
        while (got := self.pieces.get()) is not None:
            at, wav = got
            try:
                text = self.write(wav, self.engine, self.language)
            except Exception as e:
                print(f"[meeting] a piece couldn't be written down: {type(e).__name__}: {str(e)[:120]}")
                text, self.failed = f"({len(wav) // 32000} seconds couldn't be written down)", self.failed + 1
            self.waiting -= 1
            text = " ".join(str(text or "").split())
            if text:
                self.words += len(text.split())
                if not append(self.meeting_id, f"[{at:%H:%M}] {text}\n"):
                    self.stop("there is no room for more" if get(self.meeting_id) else "the meeting was deleted")
            self.changed(self.state())
        append(self.meeting_id, f"[{datetime.now():%H:%M}, writing ended]\n")
        self.active = False
        self.changed(self.state())
        self.ended(self.reason or "stopped")


class Mic:
    """The chosen microphone as a source for Scribe."""

    def __init__(self) -> None:
        import sounddevice as sd
        from . import recorder
        dev = recorder.choose_mic()
        if not dev:
            raise RuntimeError("No microphone was found.")
        if recorder.is_muted(dev["name"]):
            raise RuntimeError("The microphone is muted in Windows. Unmute it first.")
        self.rate, self.name = dev["rate"], dev["name"]
        self._block = int(self.rate * 0.1)
        self._stream = sd.InputStream(device=dev["index"], channels=1, samplerate=self.rate, dtype="float32", blocksize=self._block)
        self._stream.start()
        from . import privacy
        self._noted = privacy.begin("mic", "Writing down a meeting")

    def read(self):
        data, _ = self._stream.read(self._block)
        return data[:, 0].copy()

    def close(self) -> None:
        from . import privacy
        privacy.end(self._noted)
        self._stream.stop()
        self._stream.close()


def load(meeting_id: Any = None, query: str = "") -> dict:
    m = get(meeting_id) if meeting_id not in (None, "") else None
    if m:
        m["transcript"] = transcript(m["id"])
    return {"meetings": meetings(query), "meeting": m, "engines": engines(), "today": date.today().isoformat()}

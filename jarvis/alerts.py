"""Loud alert beeps: warnings, alarms and reminders beep at full volume so you can't miss them.

With "Loud alerts" on (Settings), the Windows speaker volume is raised to 100% (and unmuted) just for the
beep, then put back exactly as it was. With it off, the beep plays at your normal volume.
"""
from __future__ import annotations

import threading
import time

import numpy as np

from . import schedule

RATE = 48000
_lock = threading.Lock()
_last: dict[str, float] = {}          # text -> when it last beeped (same warning: no repeat beep for a minute)
_last_any = 0.0


def loud() -> bool:
    return schedule.get_setting("loud_alerts", True) is not False


def _speakers():
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        from pycaw.pycaw import AudioUtilities
        return AudioUtilities.GetSpeakers().EndpointVolume
    except Exception:
        return None


def _tone(freq: float, dur: float, shape: str = "beep") -> np.ndarray:
    t = np.arange(int(RATE * dur)) / RATE
    if shape == "bell":
        env = np.exp(-t * 3.2)
        wave = np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 2 * t)
    else:
        env = np.minimum(1, np.minimum(t, dur - t) / 0.008)              # 8 ms fade: no clicks
        wave = np.sin(2 * np.pi * freq * t) + 0.25 * np.sin(2 * np.pi * freq * 3 * t)   # bright, cuts through
    return (wave * env).astype(np.float32)


TONES = {"chime": "Chime (bright bells)", "beep": "Classic beeps", "siren": "Siren", "pulse": "Digital pulse"}


def tone() -> str:
    t = schedule.get_setting("alert_tone") or "chime"
    return t if t in TONES else "chime"


def _sweep(f0: float, f1: float, dur: float) -> np.ndarray:
    t = np.arange(int(RATE * dur)) / RATE
    f = f0 + (f1 - f0) * (0.5 - 0.5 * np.cos(np.pi * t / dur))       # smooth up-and-over
    env = np.minimum(1, np.minimum(t, dur - t) / 0.01)
    return (np.sin(2 * np.pi * np.cumsum(f) / RATE) * env).astype(np.float32)


def _once(name: str) -> list:
    gap = lambda s: np.zeros(int(RATE * s), np.float32)
    if name == "beep":
        return [_tone(1250, .14), gap(.09), _tone(1250, .14), gap(.09), _tone(1250, .2)]
    if name == "siren":
        return [_sweep(650, 1350, .45), _sweep(1350, 650, .45)]
    if name == "pulse":
        return sum(([_tone(1800, .06), gap(.06)] for _ in range(6)), [])
    bell = lambda f, d: _tone(f, d, "bell")                             # chime: a rising C-E-G arpeggio
    notes = [bell(1047, .5), bell(1319, .5), bell(1568, .8)]
    out = np.zeros(int(RATE * 1.1), np.float32)
    for i, n in enumerate(notes):
        start = int(RATE * .15 * i)
        out[start:start + n.size] += n[: out.size - start]
    return [out]


def pattern(kind: str, name: str | None = None) -> np.ndarray:
    gap = lambda s: np.zeros(int(RATE * s), np.float32)
    name = name or tone()
    if kind == "prayer":         # a calm two-note bell
        parts = [_tone(660, 1.0, "bell"), _tone(880, 1.4, "bell")]
    elif kind == "alarm":        # alarms and timers: the tone twice
        parts = _once(name) + [gap(.3)] + _once(name)
    else:                        # warnings: once
        parts = _once(name)
    x = np.concatenate(parts)
    return (x / np.abs(x).max() * 0.85).astype(np.float32)


def duration(kind: str) -> float:
    return pattern(kind).size / RATE


def beep(kind: str = "warn", text: str = "", on_start=None, force: bool = False, name: str | None = None) -> bool:
    """Play the alert beep (blocking). Returns False if it was skipped as a repeat (force: the Test button)."""
    global _last_any
    now = time.time()
    key = (text or kind)[:120]
    if not force and (now - _last.get(key, 0) < 60 or now - _last_any < 3):
        return False
    _last[key] = _last_any = now
    with _lock:
        ep = _speakers() if loud() else None
        old = None
        try:
            if ep:
                old = (ep.GetMasterVolumeLevelScalar(), ep.GetMute())
                ep.SetMute(0, None)
                ep.SetMasterVolumeLevelScalar(1.0, None)
        except Exception as e:
            print(f"[alert] couldn't raise the volume: {e}")
            old = None
        try:
            if on_start:
                on_start()
            import sounddevice as sd
            sd.play(pattern(kind, name), RATE, blocking=True)
        except Exception as e:
            print(f"[alert] beep failed: {e}")
        finally:
            if ep and old:
                try:
                    if abs(ep.GetMasterVolumeLevelScalar() - 1.0) < 0.01:   # you didn't change it meanwhile
                        ep.SetMasterVolumeLevelScalar(old[0], None)
                    ep.SetMute(old[1], None)
                except Exception:
                    pass
    return True

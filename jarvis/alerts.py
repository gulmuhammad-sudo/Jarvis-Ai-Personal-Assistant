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


def pattern(kind: str) -> np.ndarray:
    gap = lambda s: np.zeros(int(RATE * s), np.float32)
    if kind == "alarm":          # alarms and timers: two triple-beeps
        tri = [_tone(1000, .16), gap(.08), _tone(1000, .16), gap(.08), _tone(1320, .22)]
        parts = tri + [gap(.35)] + tri
    elif kind == "prayer":       # a calm two-note bell
        parts = [_tone(660, 1.0, "bell"), _tone(880, 1.4, "bell")]
    else:                        # warnings: three sharp beeps
        parts = [_tone(1250, .14), gap(.09), _tone(1250, .14), gap(.09), _tone(1250, .2)]
    x = np.concatenate(parts)
    return (x / np.abs(x).max() * 0.85).astype(np.float32)


def duration(kind: str) -> float:
    return pattern(kind).size / RATE


def beep(kind: str = "warn", text: str = "", on_start=None) -> bool:
    """Play the alert beep (blocking). Returns False if it was skipped as a repeat."""
    global _last_any
    now = time.time()
    key = (text or kind)[:120]
    if now - _last.get(key, 0) < 60 or now - _last_any < 3:
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
            sd.play(pattern(kind), RATE, blocking=True)
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

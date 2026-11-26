"""Records your voice straight from a microphone (no browser involved).

- Picks a microphone that actually hears something. Some laptop mics go completely
  silent (all zeros) while a Bluetooth headset is connected, so every recording
  re-checks the device list, and if the mic in use turns out to be dead mid-recording
  Jarvis switches to another live mic straight away and keeps listening.
- Notices when Windows has the mic muted, and can unmute it / raise its level on request.
- Stops by itself after you finish talking (0.9 s of quiet by default; "end_silence" in data/settings.json).
- Returns cleaned-up 16 kHz mono WAV bytes, ready for Whisper.
"""
from __future__ import annotations

import io
import json
import threading
import time
import wave
from typing import Callable

import numpy as np
import sounddevice as sd

from . import privacy, schedule
from .config import DATA_DIR


# --- Windows mute state of a microphone (pycaw / Core Audio) ---
def _endpoint(name: str):
    try:
        import comtypes
        try:
            comtypes.CoInitialize()          # every thread that talks to Windows audio must do this
        except OSError:
            pass                             # already initialised on this thread
        from pycaw.pycaw import AudioUtilities
        from pycaw.utils import AudioDeviceState
        key = name[:28].lower()
        for d in AudioUtilities.GetAllDevices():
            if d.state == AudioDeviceState.Active and (d.FriendlyName or "").lower().startswith(key):
                return d.EndpointVolume
    except Exception:
        pass
    return None


def is_muted(name: str) -> bool | None:
    """True if Windows has this microphone muted (None if unknown)."""
    ep = _endpoint(name)
    try:
        return bool(ep.GetMute()) if ep else None
    except Exception:
        return None


def level(name: str) -> int | None:
    """Windows input level of a microphone in percent."""
    ep = _endpoint(name)
    try:
        return round(ep.GetMasterVolumeLevelScalar() * 100) if ep else None
    except Exception:
        return None


def boost(name: str, percent: int = 100) -> int | None:
    """Raise a microphone's Windows input level. Only called when the user clicks Boost in Jarvis."""
    ep = _endpoint(name)
    try:
        ep.SetMasterVolumeLevelScalar(max(0.0, min(1.0, percent / 100)), None)
        return level(name)
    except Exception:
        return None


def unmute(name: str) -> bool:
    """Unmute a microphone in Windows. Only called when the user clicks Unmute in Jarvis."""
    ep = _endpoint(name)
    try:
        ep.SetMute(0, None)
        return not bool(ep.GetMute())
    except Exception:
        return False


_lock = threading.Lock()
_recording = threading.Event()         # set while a stream is open: rescanning devices then would kill it
_chosen: dict | None = None            # {"index", "name", "api", "rate"}
_dead: dict[str, float] = {}           # mic name -> time it was found silent
DEAD_FOR = 120                         # seconds a silent mic is skipped before trying it again


def _refresh_devices() -> None:
    """PortAudio only scans devices at start-up; rescan so headsets that (dis)connected show up."""
    if _recording.is_set():
        return
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


def _inputs() -> list[dict]:
    """Usable input devices: WASAPI first (best quality), then MME; skip loopback/stereo-mix style devices."""
    apis = {i: a["name"] for i, a in enumerate(sd.query_hostapis())}
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] < 1:
            continue
        api = apis.get(d["hostapi"], "")
        if api not in ("Windows WASAPI", "MME"):
            continue
        name = d["name"]
        if any(x in name.lower() for x in ("stereo mix", "sound mapper", "loopback", "what u hear")):
            continue
        out.append({"index": i, "name": name, "api": api, "rate": int(d["default_samplerate"])})
    out.sort(key=lambda d: 0 if d["api"] == "Windows WASAPI" else 1)
    seen, uniq = set(), []               # one entry per physical mic (MME cuts names at 31 chars)
    for d in out:
        key = d["name"][:28].lower()
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    return uniq


def active_mic_names() -> list[str] | None:
    """Microphones Windows has active right now (cheap, ~40 ms; safe while a stream is open)."""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except OSError:
            pass
        from pycaw.constants import DEVICE_STATE, EDataFlow
        from pycaw.pycaw import AudioUtilities
        return [d.FriendlyName for d in AudioUtilities.GetAllDevices(
            data_flow=EDataFlow.eCapture.value, device_state=DEVICE_STATE.ACTIVE.value) if d.FriendlyName]
    except Exception:
        return None


def refresh() -> None:
    """Rescan devices now (only when no stream is open)."""
    with _lock:
        _refresh_devices()


def list_mics() -> list[dict]:
    return [{"name": d["name"], "index": d["index"]} for d in _inputs()]


def _probe(dev: dict, seconds: float = 0.8) -> float:
    """RMS level a device hears, ignoring the first 0.15 s (start-up click/zeros). 0.0 = dead/muted."""
    try:
        with privacy.using("mic", "Looking for a microphone that works", show=False):
            x = sd.rec(int(seconds * dev["rate"]), samplerate=dev["rate"], channels=1, dtype="float32", device=dev["index"])
            sd.wait()
        tail = x[int(0.15 * dev["rate"]):, 0]
        return float(np.sqrt(np.mean(tail * tail))) if tail.size else 0.0
    except Exception:
        return -1.0


def _is_dead(name: str) -> bool:
    t = _dead.get(name)
    return t is not None and time.time() - t < DEAD_FOR


def choose_mic(force: bool = False) -> dict | None:
    """Saved choice if it works, else the Windows default if it isn't dead, else any mic that hears something."""
    global _chosen
    with _lock:
        if _chosen and not force:
            # PortAudio numbers its devices anew after every rescan (a headset plugged in): the number kept from before may now
            # be another device, even one that can't be opened this way (WDM-KS). The same microphone, by name, as it is now:
            now = next((d for d in _inputs() if d["name"] == _chosen["name"] and d["api"] == _chosen["api"]), None)
            if now:
                _chosen = now
                return _chosen
        _refresh_devices()
        devices = _inputs()
        if not devices:
            _chosen = None
            print("[voice] no microphone found")
            return None
        wanted = schedule.get_setting("mic")
        try:
            default_name = sd.query_devices(kind="input")["name"]
        except Exception:
            default_name = ""
        ordered = sorted(devices, key=lambda d: (0 if wanted and d["name"] == wanted else
                                                 1 if d["name"].startswith(default_name[:28]) else 2))
        report = []
        for d in ordered:
            if _is_dead(d["name"]):
                report.append(f"{d['name']}=skipped(silent)")
                continue
            level = _probe(d)
            report.append(f"{d['name']}={level:.5f}")
            if level > 0.00005:          # live: hears at least the room
                _chosen = d
                print(f"[voice] using mic: {d['name']}  (probe: {', '.join(report)})")
                return d
        _chosen = next((d for d in ordered if not _is_dead(d["name"])), ordered[0])
        print(f"[voice] no mic hears anything; trying {_chosen['name']}  (probe: {', '.join(report)})")
        return _chosen


def set_mic(name: str | None) -> dict | None:
    schedule.set_setting("mic", name or None)
    if name:
        _dead.pop(name, None)
    return choose_mic(force=True)


def _clean_audio(samples: np.ndarray, rate: int, out_rate: int = 16000) -> np.ndarray:
    """Make speech easier for Whisper: keep only the voice band (cuts fan/AC rumble and hiss),
    resample to 16 kHz, then even out the volume.

    Laptop mics pick up a lot of fan rumble below 150 Hz. If that stays in, the volume boost
    below boosts the rumble instead of your voice, and Whisper starts inventing sentences."""
    x = samples.astype(np.float64)
    if x.size < 64:
        return x.astype(np.float32)
    x -= x.mean()
    n_out = int(x.size * out_rate / rate)
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(x.size, 1 / rate)
    # soft band-pass: fades in from 90 to 150 Hz, out from 4.0 to 4.6 kHz (also the anti-alias filter)
    spec *= np.clip((f - 90) / 60, 0, 1) * np.clip((4600 - f) / 600, 0, 1)
    x = np.fft.irfft(spec[: n_out // 2 + 1], n=n_out) * (n_out / x.size)   # resample in the same step
    from . import denoise
    lvl = denoise.level()
    if lvl != "off":                                # background noise (fans, a busy room) turned down
        x = denoise.denoise(x.astype(np.float32), out_rate, lvl).astype(np.float64)
    peak = float(np.percentile(np.abs(x), 99.9))   # ignore single clicks when judging loudness
    if peak > 0:
        x *= min(0.7 / peak, 20.0)     # quiet speech gets louder (max 20x so noise isn't blown up)
    return np.clip(x, -1, 1).astype(np.float32)


def _voice_rms(x: np.ndarray, rate: int) -> float:
    """Loudness of the speech band only (250-3500 Hz), so fan rumble doesn't count as talking."""
    if x.size < 32:
        return 0.0
    spec = np.abs(np.fft.rfft(x * np.hanning(x.size))) ** 2
    f = np.fft.rfftfreq(x.size, 1 / rate)
    band = spec[(f >= 250) & (f <= 3500)].sum()
    return float(np.sqrt(2 * band / (x.size * (np.hanning(x.size) ** 2).sum())))


DEBUG_DIR = DATA_DIR / "voice_debug"


def _save_debug(wav: bytes, meta: dict) -> None:
    """Keep the last 5 recordings (data/voice_debug) so voice problems can be diagnosed: only if you turned it on (Privacy)."""
    if schedule.get_setting("voice_debug") is not True:
        return
    try:
        DEBUG_DIR.mkdir(exist_ok=True)
        stamp = time.strftime("%H%M%S")
        (DEBUG_DIR / f"{stamp}.wav").write_bytes(wav)
        (DEBUG_DIR / f"{stamp}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        files = sorted(DEBUG_DIR.glob("*.wav"))
        for old in files[:-5]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
    except OSError:
        pass


def _to_wav(samples: np.ndarray, rate: int, out_rate: int = 16000) -> bytes:
    samples = _clean_audio(samples, rate, out_rate)
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(out_rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Recording:
    """One utterance. Call stop() to end early (e.g. the user clicks the mic again)."""

    def __init__(self) -> None:
        self.stop_now = False
        self.peak = 0.0
        self.started = False
        self.mic = ""
        self.switched_from: list[str] = []   # mics that turned out to be silent during this recording
        self.all_dead = False
        self.muted = False                   # Windows has the microphone muted

    def stop(self) -> None:
        self.stop_now = True

    def run(self, on_level: Callable[[float], None] | None = None, hands_free: bool = False,
            max_seconds: float = 25.0) -> bytes | None:
        global _chosen
        # Rescan every time: a headset may have been connected or removed since the last recording.
        with _lock:
            _refresh_devices()
            current = {d["name"]: d for d in _inputs()}
            try:
                default_name = sd.query_devices(kind="input")["name"]
            except Exception:
                default_name = ""
        keep = (_chosen and _chosen["name"] in current and not _is_dead(_chosen["name"])
                and (schedule.get_setting("mic") or _chosen["name"].startswith(default_name[:28])
                     or _is_dead(next((n for n in current if n.startswith(default_name[:28])), ""))))
        if keep:
            dev = current[_chosen["name"]]       # same mic, fresh device index
            _chosen = dev
        else:
            dev = choose_mic(force=True)
        if not dev:
            raise RuntimeError("No microphone found.")
        if is_muted(dev["name"]):
            # Muted in Windows (often the keyboard's mic key): every sample would be zero.
            others = [d for d in _inputs() if d["name"] != dev["name"] and not is_muted(d["name"]) and not _is_dead(d["name"])]
            if not others:
                self.mic, self.muted = dev["name"], True
                print(f"[voice] mic '{dev['name']}' is MUTED in Windows")
                return None
            dev = others[0]
        for _attempt in range(3):
            self.mic = dev["name"]
            result = self._record(dev, on_level, hands_free, max_seconds)
            if result != "dead":
                return result
            # this mic gives pure digital silence: remember that and switch to another one
            _dead[dev["name"]] = time.time()
            self.switched_from.append(dev["name"])
            print(f"[voice] mic '{dev['name']}' is silent (all zeros); switching")
            with _lock:
                _chosen = None
            nxt = choose_mic(force=True)
            if not nxt or nxt["name"] in self.switched_from:
                self.all_dead = True
                return None
            dev = nxt
        return None

    def _record(self, dev: dict, on_level, hands_free: bool, max_seconds: float):
        rate = dev["rate"]
        block = int(rate * 0.05)                # 50 ms
        chunks: list[np.ndarray] = []
        floor, last_voice, heard, raw_peak = float("inf"), 0.0, 0, 0.0
        end_silence = float(schedule.get_setting("end_silence", 0.9))   # seconds of quiet that end your turn
        _recording.set()
        try:
            with privacy.using("mic", "You talked to it"), sd.InputStream(device=dev["index"], channels=1, samplerate=rate,
                                                                          dtype="float32", blocksize=block) as stream:
                while True:
                    data, _ = stream.read(block)
                    x = data[:, 0].copy()
                    chunks.append(x)
                    heard += x.size
                    now = heard / rate              # time measured in audio, not wall clock
                    raw_peak = max(raw_peak, float(np.max(np.abs(x))) if x.size else 0.0)
                    if now > 1.2 and raw_peak == 0.0 and not self.stop_now:
                        return "dead"               # 1.2 s of exact zeros: muted/disabled mic
                    rms = _voice_rms(x, rate)       # speech band only: a fan isn't "talking"
                    self.peak = max(self.peak, rms)
                    floor = rms if rms < floor else floor * 0.997 + rms * 0.003
                    if rms > max(0.004, floor * 2.4):
                        self.started, last_voice = True, now
                    if on_level:
                        on_level(min(1.0, rms * 12))
                    silent = now - last_voice
                    if self.stop_now or (self.started and now > 0.9 and silent > end_silence) \
                            or (not self.started and now > (8 if hands_free else 7)) or now > max_seconds:
                        break
        finally:
            _recording.clear()
        if not self.started and not self.stop_now and self.peak < 0.01:
            return None                          # nobody spoke
        raw = np.concatenate(chunks)
        wav = _to_wav(raw, rate)
        _save_debug(wav, {"mic": dev["name"], "rate": rate, "seconds": round(raw.size / rate, 2),
                          "raw_peak": round(float(np.max(np.abs(raw))), 4),
                          "raw_rms": round(float(np.sqrt(np.mean(raw * raw))), 5),
                          "noise_floor": round(floor, 5), "speech_detected": self.started})
        return wav

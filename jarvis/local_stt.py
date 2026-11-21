"""Speech-to-text on this PC: Whisper running locally (whisper.cpp through the free pywhispercpp package).

Works without internet and nothing you say leaves the computer. A model file is downloaded once, when you ask
(Settings › Microphone): "base" (60 MB, fast) or "small" (190 MB, better for Urdu). Models are kept in
%LOCALAPPDATA%\\Personal Assistant\\models for the installed app (data\\models in a source checkout).
"""
from __future__ import annotations

import io
import os
import threading
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

MODELS = {   # name: (what it's like, size in MB)
    "base-q5_1": ("fast, good for English and short commands", 60),
    "small-q5_1": ("slower, better for Urdu and noisy rooms", 190),
}
URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-{name}.bin"
_lock = threading.Lock()
_loaded: dict = {"name": None, "model": None}


def models_dir() -> Path:
    from .config import APP_NAME, DATA_DIR, FROZEN, ISOLATED
    if FROZEN and not ISOLATED:          # big files: local (not roaming) app data
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME / "models"
    return DATA_DIR / "models"


def model_file(name: str) -> Path:
    return models_dir() / f"ggml-{name}.bin"


def available() -> bool:
    """Is the speech engine itself (pywhispercpp) part of this app?"""
    try:
        import pywhispercpp  # noqa: F401
        return True
    except ImportError:
        return False


def installed() -> list[str]:
    return [n for n in MODELS if model_file(n).exists()]


def chosen() -> str | None:
    """The model to use: the one picked in Settings if it's there, else the best one downloaded."""
    from . import schedule
    have = installed()
    pick = schedule.get_setting("local_stt_model")
    if pick in have:
        return pick
    for n in ("small-q5_1", "base-q5_1"):
        if n in have:
            return n
    return None


def ready() -> bool:
    return available() and chosen() is not None


def status() -> dict:
    return {"available": available(), "installed": installed(), "model": chosen(),
            "models": [{"name": n, "about": a, "size_mb": s} for n, (a, s) in MODELS.items()]}


def download(name: str, on_progress=None) -> Path:
    """Download a model (only ones from MODELS). Written to a .part file first, so a broken download never
    leaves a half model behind. on_progress(fraction)."""
    if name not in MODELS:
        raise ValueError(f"unknown model {name}")
    dest = model_file(name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(".part")
    req = urllib.request.Request(URL.format(name=name), headers={"User-Agent": "PersonalAssistant"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if on_progress and total and time.time() - last > 0.4:
                last = time.time()
                on_progress(done / total)
    if total and part.stat().st_size != total:
        part.unlink(missing_ok=True)
        raise OSError("the download was cut off; try again")
    os.replace(part, dest)
    if on_progress:
        on_progress(1.0)
    return dest


def _consoles() -> None:
    """The installed app has no console (sys.stdout/stderr are None) and pywhispercpp flushes them: give it a
    harmless sink instead of crashing ("'NoneType' object has no attribute 'flush'")."""
    import sys
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _model(name: str):
    if _loaded["name"] != name:
        _consoles()
        from pywhispercpp.model import Model
        threads = max(2, min(8, (os.cpu_count() or 4) // 2))
        _loaded["model"] = Model(str(model_file(name)), n_threads=threads, print_progress=False,
                                 print_realtime=False, redirect_whispercpp_logs_to=False)
        _loaded["name"] = name
    return _loaded["model"]


def wav_to_pcm(wav: bytes) -> np.ndarray:
    """16-bit / 32-bit WAV bytes -> mono float32 at 16 kHz."""
    with wave.open(io.BytesIO(wav)) as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    dtype = {2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"unsupported WAV sample width {width}")
    x = np.frombuffer(raw, dtype).astype(np.float32) / float(np.iinfo(dtype).max)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    if rate != 16000:
        from scipy import signal
        g = np.gcd(rate, 16000)
        x = signal.resample_poly(x, 16000 // g, rate // g).astype(np.float32)
    return x


def transcribe(pcm: np.ndarray, language: str | None = None) -> str:
    """Text for 16 kHz mono float32 audio. language: a Whisper code ('ur', 'en', ...) or None = detect."""
    name = chosen()
    if not name:
        raise RuntimeError("no local speech model downloaded")
    with _lock:                      # one at a time: the model isn't thread-safe and uses several CPU cores
        _consoles()
        segs = _model(name).transcribe(np.ascontiguousarray(pcm, dtype=np.float32),
                                       language=language or "auto", translate=False, no_context=True,
                                       single_segment=False, print_progress=False)
    return " ".join((s.text or "").strip() for s in segs).strip()

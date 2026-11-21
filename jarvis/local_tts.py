"""Voices that speak on this PC (Piper voices run by the free sherpa-onnx package): offline and private.

Each voice is a one-time download (about 20 MB) kept next to the speech-to-text models
(%LOCALAPPDATA%\\Personal Assistant\\models\\voices for the installed app). Used when Settings › Voices says
"This PC", or with "Auto" when there's no internet or the online voices fail.
"""
from __future__ import annotations

import io
import os
import shutil
import tarfile
import threading
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{file}.tar.bz2"
VOICES = {   # id: (label, language, file name in the release, size MB)
    "alan": ("Alan · British (male)", "en", "vits-piper-en_GB-alan-medium-int8", 21),
    "jenny": ("Jenny · British (female)", "en", "vits-piper-en_GB-jenny_dioco-medium-int8", 20),
    "fasih": ("Fasih · Urdu (male)", "ur", "vits-piper-ur_PK-fasih-medium-int8", 21),
    "rohan": ("Rohan · Hindi (male)", "hi", "vits-piper-hi_IN-rohan-medium-int8", 21),
    "priyamvada": ("Priyamvada · Hindi (female)", "hi", "vits-piper-hi_IN-priyamvada-medium-int8", 21),
}
_lock = threading.Lock()
_engines: dict = {}


def voices_dir() -> Path:
    from .local_stt import models_dir
    return models_dir() / "voices"


def available() -> bool:
    try:
        import sherpa_onnx  # noqa: F401
        return True
    except ImportError:
        return False


def _folder(voice: str) -> Path:
    return voices_dir() / VOICES[voice][2]


def installed() -> list[str]:
    return [v for v in VOICES if any(_folder(v).glob("*.onnx"))] if voices_dir().exists() else []


def status() -> dict:
    return {"available": available(), "installed": installed(),
            "voices": [{"id": v, "label": l, "lang": g, "size_mb": s} for v, (l, g, _, s) in VOICES.items()]}


def download(voice: str, on_progress=None) -> Path:
    """Download and unpack a voice (only the ones listed above). Nothing half-done is left behind."""
    if voice not in VOICES:
        raise ValueError(f"unknown voice {voice}")
    folder = _folder(voice)
    folder.parent.mkdir(parents=True, exist_ok=True)
    part = folder.parent / (folder.name + ".tar.bz2.part")
    req = urllib.request.Request(URL.format(file=VOICES[voice][2]), headers={"User-Agent": "PersonalAssistant"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if on_progress and total and time.time() - last > 0.4:
                last = time.time()
                on_progress(min(done / total, 0.99))
    try:
        if total and part.stat().st_size != total:
            raise OSError("the download was cut off; try again")
        tmp = folder.parent / (folder.name + ".unpacking")
        shutil.rmtree(tmp, ignore_errors=True)
        with tarfile.open(part, "r:bz2") as t:
            t.extractall(tmp, filter="data")            # refuses paths outside the folder, links, devices
        inner = next((p for p in tmp.iterdir() if p.is_dir()), tmp)
        if not any(inner.glob("*.onnx")):
            raise OSError("the voice file didn't contain a voice model")
        shutil.rmtree(folder, ignore_errors=True)
        shutil.move(str(inner), str(folder))
        shutil.rmtree(tmp, ignore_errors=True)
    finally:
        part.unlink(missing_ok=True)
    if on_progress:
        on_progress(1.0)
    return folder


def pick(text: str, language: str | None = None) -> str | None:
    """The downloaded voice for this text: Urdu script → an Urdu voice, Hindi → Hindi, else English
    (the one chosen in Settings if it's downloaded)."""
    from . import schedule
    have = installed()
    if any("؀" <= c <= "ۿ" for c in text) or language == "ur":
        want = "ur"
    elif any("ऀ" <= c <= "ॿ" for c in text) or language == "hi":
        want = "hi"
    else:
        want = "en"
    chosen = schedule.get_setting(f"local_voice_{want}")
    if chosen in have and VOICES[chosen][1] == want:
        return chosen
    return next((v for v in have if VOICES[v][1] == want), None)


_ESPEAK: dict = {}


def _espeak():
    """espeak-ng (from the espeakng-loader package) turns text into the IPA sounds Piper voices are trained on.
    (sherpa-onnx 2.x no longer does this itself.)"""
    if not _ESPEAK:
        import ctypes
        import espeakng_loader
        lib = ctypes.cdll.LoadLibrary(espeakng_loader.get_library_path())
        lib.espeak_Initialize.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
        lib.espeak_SetVoiceByName.argtypes = [ctypes.c_char_p]
        lib.espeak_TextToPhonemes.restype = ctypes.c_char_p
        lib.espeak_TextToPhonemes.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.c_int, ctypes.c_int]
        if lib.espeak_Initialize(0x02, 0, espeakng_loader.get_data_path().encode(), 0) <= 0:   # (synchronous)
            raise RuntimeError("couldn't start espeak-ng")
        _ESPEAK.update(lib=lib, ctypes=ctypes)
    return _ESPEAK


def phonemes(text: str, espeak_voice: str) -> str:
    """IPA for the text, keeping . , ? ! as pauses (Piper voices know these symbols)."""
    import re
    e = _espeak()
    lib, ct = e["lib"], e["ctypes"]
    lib.espeak_SetVoiceByName(espeak_voice.encode())
    out = []
    for piece, mark in re.findall(r"([^.,!?;:،۔؟]+)([.,!?;:،۔؟]*)", text):
        if not piece.strip():
            continue
        buf = ct.c_char_p(piece.encode("utf-8"))
        ptr = ct.pointer(buf)
        words = []
        while buf.value:
            p = lib.espeak_TextToPhonemes(ptr, 1, 0x02)          # UTF-8 text in, IPA out
            if p:
                words.append(p.decode("utf-8"))
        mark = {"،": ",", "۔": ".", "؟": "?", ";": ",", ":": ","}.get(mark[:1], mark[:1])
        out.append(" ".join(words) + mark)
    return " ".join(out).strip()


def _engine(voice: str):
    if voice not in _engines:
        import json
        import sherpa_onnx
        folder = _folder(voice)
        model = next(folder.glob("*.onnx"))
        meta = json.loads(next(folder.glob("*.onnx.json")).read_text(encoding="utf-8"))
        vits = sherpa_onnx.OfflineTtsVitsModelConfig(model=str(model), tokens=str(folder / "tokens.txt"))
        cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=vits, num_threads=max(1, min(4, (os.cpu_count() or 2) // 2))))
        _engines[voice] = (sherpa_onnx.OfflineTts(cfg), (meta.get("espeak") or {}).get("voice") or "en-us",
                           sherpa_onnx.GenerationConfig)
    return _engines[voice]


def synthesize(text: str, voice: str, speed: float = 1.0) -> bytes:
    """Spoken text as a 16-bit mono WAV. speed: 1.0 normal, 1.2 faster, 0.8 slower."""
    with _lock:
        tts, espeak_voice, Gen = _engine(voice)
        g = Gen()
        g.speed = max(0.5, min(2.0, float(speed)))
        g.phoneme_codepoints = [[ord(c) for c in phonemes(text, espeak_voice)]]
        audio = tts.generate(text, g)
    samples = np.clip(np.asarray(audio.samples, dtype=np.float32), -1, 1)
    if not samples.size:
        raise RuntimeError("the voice produced no sound for this text")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(audio.sample_rate))
        w.writeframes((samples * 32767).astype("<i2").tobytes())
    return buf.getvalue()

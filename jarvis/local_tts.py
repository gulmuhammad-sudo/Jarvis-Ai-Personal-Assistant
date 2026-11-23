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
    "fasih": ("Fasih · Pakistani Urdu (male)", "ur", "vits-piper-ur_PK-fasih-medium-int8", 21),
    "aegis": ("Aegis · Pakistani Urdu (female)", "ur", "vits-piper-ur_PK-aegis_female-medium", 64),
    "rohan": ("Rohan · Hindi (male)", "hi", "vits-piper-hi_IN-rohan-medium-int8", 21),
    "priyamvada": ("Priyamvada · Hindi (female)", "hi", "vits-piper-hi_IN-priyamvada-medium-int8", 21),
}
# voices that aren't in sherpa-onnx's release: taken from Piper's own (a fixed version, checked by its SHA-256)
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/e9c8a39444359388adaa94255becb37a5a2b8e51/{path}"
PIPER = {   # id: ((path of the model, SHA-256), (path of its description, SHA-256))
    "aegis": (("ur/ur_PK/aegis_female/medium/ur_PK-aegis_female-medium.onnx", "3ec306035cfd0bbc22342fee5890450708a16dd231809522731678aa583c961f"),
              ("ur/ur_PK/aegis_female/medium/ur_PK-aegis_female-medium.onnx.json", "a8385c217a7e276acf5234bf01dbd0adb007a57c32ffbcc57d2db7eac3979bb6")),
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
    if voice in PIPER:
        return _download_piper(voice, folder, on_progress)
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


def _download_piper(voice: str, folder: Path, on_progress=None) -> Path:
    """A Piper voice in its original form: download, check, and add what sherpa-onnx needs next to the model."""
    import hashlib
    import json
    tmp = folder.parent / (folder.name + ".unpacking")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    try:
        for path, want in PIPER[voice]:
            req = urllib.request.Request(PIPER_URL.format(path=path), headers={"User-Agent": "PersonalAssistant"})
            h, out = hashlib.sha256(), tmp / path.rsplit("/", 1)[1]
            with urllib.request.urlopen(req, timeout=60) as r, open(out, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done, last = 0, 0.0
                while chunk := r.read(1 << 20):
                    h.update(chunk)
                    f.write(chunk)
                    done += len(chunk)
                    if done > 200 << 20:
                        raise OSError("that's not the voice file")
                    if on_progress and total and out.suffix == ".onnx" and time.time() - last > 0.4:
                        last = time.time()
                        on_progress(min(done / total, 0.99))
            if h.hexdigest() != want:
                raise OSError("the download was cut off or isn't the right file; try again")
        model = next(tmp.glob("*.onnx"))
        meta = json.loads(next(tmp.glob("*.onnx.json")).read_text(encoding="utf-8"))
        # one character each (sherpa-onnx ends the whole program at longer ones, like this voice's "aɪ")
        (tmp / "tokens.txt").write_text("".join(f"{s} {ids[0]}\n" for s, ids in meta["phoneme_id_map"].items() if len(s) == 1), encoding="utf-8", newline="\n")
        with open(model, "ab") as f:
            f.write(onnx_notes({"model_type": "vits", "comment": "piper", "language": "Urdu", "voice": meta["espeak"]["voice"], "version": "1",
                                "has_espeak": "1", "has_g2pw": "0", "n_speakers": str(meta["num_speakers"]), "sample_rate": str(meta["audio"]["sample_rate"])}))
        shutil.rmtree(folder, ignore_errors=True)
        shutil.move(str(tmp), str(folder))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if on_progress:
        on_progress(1.0)
    return folder


def onnx_notes(notes: dict[str, str]) -> bytes:
    """Notes (metadata_props) to put at the end of an .onnx file: it's a protobuf message, so adding fields at its end adds them to it."""
    def field(n: int, data: bytes) -> bytes:
        size, out = len(data), bytearray([n << 3 | 2])
        while size > 127:
            out.append(size & 127 | 128)
            size >>= 7
        return bytes(out) + bytes([size]) + data
    return b"".join(field(14, field(1, k.encode()) + field(2, v.encode())) for k, v in notes.items())


def female(voice: str) -> bool:
    return "(female)" in VOICES[voice][0]


def pick(text: str, language: str | None = None) -> str | None:
    """The downloaded voice for this text: Urdu script → an Urdu voice, Hindi → Hindi, else English
    (the one chosen in Settings if it's downloaded, else one like the online voice you chose: male or female)."""
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
    from .tts import reading_female
    fits = [v for v in have if VOICES[v][1] == want]
    return next((v for v in fits if female(v) == reading_female()), fits[0] if fits else None)


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

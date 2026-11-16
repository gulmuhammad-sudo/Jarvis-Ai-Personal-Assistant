"""Natural neural text-to-speech (Microsoft's online voices via the free edge-tts package).

Default voice: en-GB-RyanNeural, a smooth British male voice in the spirit of the films.
Urdu text is automatically read by the Urdu voice (Asad).
If this fails (offline), the HUD falls back to the Windows voices built into the browser.
"""
from __future__ import annotations

import asyncio
import os
import queue
import threading

VOICES = [
    ("en-GB-RyanNeural", "Ryan · British (Jarvis)"),
    ("en-GB-ThomasNeural", "Thomas · British"),
    ("en-US-BrianNeural", "Brian · American, calm"),
    ("en-US-AndrewNeural", "Andrew · American, warm"),
    ("en-US-ChristopherNeural", "Christopher · American, deep"),
    ("en-US-GuyNeural", "Guy · American"),
    ("en-US-AndrewMultilingualNeural", "Andrew · multilingual"),
    ("en-GB-SoniaNeural", "Sonia · British (female)"),
    ("en-GB-LibbyNeural", "Libby · British (female)"),
    ("en-US-AvaMultilingualNeural", "Ava · multilingual (female)"),
    ("ur-PK-AsadNeural", "Asad · Urdu (Pakistan)"),
    ("ur-PK-UzmaNeural", "Uzma · Urdu (Pakistan)"),
]
DEFAULT_VOICE = os.environ.get("JARVIS_VOICE", "en-GB-RyanNeural")
URDU_VOICE = os.environ.get("JARVIS_URDU_VOICE", "ur-PK-AsadNeural")
RATE = os.environ.get("JARVIS_VOICE_SPEED", "+5%")    # e.g. -10%, +0%, +15%
PITCH = os.environ.get("JARVIS_VOICE_PITCH", "-2Hz")  # slightly lower = calmer
from . import languages as _languages
_ALLOWED = {v for v, _ in VOICES} | {DEFAULT_VOICE, URDU_VOICE} | _languages.all_voices()
_FEMALE = ("Sonia", "Libby", "Ava", "Uzma", "Jenny", "Aria", "Swara", "Zariyah", "Latifa", "Dilara", "Nabanita",
           "Emel", "Denise", "Elvira", "Tanja", "Francisca", "Elsa", "Svetlana", "Xiaoxiao", "Nanami", "Gadis", "Yasmin")


def available() -> bool:
    try:
        import edge_tts  # noqa: F401  (only checking it is installed)
        return True
    except ImportError:
        return False


def _resolve(text: str, voice: str | None, lang: str | None = None) -> tuple[str, str, str]:
    """(voice, rate, pitch) for this text: unknown voices become the default; Urdu script gets the Urdu voice;
    another chosen language gets that language's voice (same gender as the voice you picked)."""
    voice = voice if voice in _ALLOWED else DEFAULT_VOICE
    lang = _languages.clean(lang) if lang else "en"
    if lang not in ("en", "ur") and voice.startswith("en-") and "Multilingual" not in voice:
        voice = _languages.voice(lang, female=any(f in voice for f in _FEMALE))
    elif voice.startswith("en-") and any("؀" <= ch <= "ۿ" for ch in text) and lang in ("en", "ur"):
        voice = _languages.voice("ur", female=any(f in voice for f in _FEMALE))
    return (voice, "+0%", "+0Hz") if voice.startswith("ur-") else (voice, RATE, PITCH)


def _communicate(text: str, voice: str | None, lang: str | None = None):
    import edge_tts
    v, rate, pitch = _resolve(text, voice, lang)
    return edge_tts.Communicate(text, v, rate=rate, pitch=pitch, connect_timeout=8)


def synthesize(text: str, voice: str | None = None, lang: str | None = None) -> bytes:
    """Return the whole sentence as MP3. Raises on network/service errors."""
    async def run() -> bytes:
        audio = bytearray()
        async for chunk in _communicate(text, voice, lang).stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        return bytes(audio)

    data = asyncio.run_coroutine_threadsafe(run(), _loop()).result(timeout=30)
    if not data:
        raise RuntimeError("no audio returned")
    return data


def stream(text: str, voice: str | None = None, lang: str | None = None):
    """Yield MP3 bytes as they arrive, so playback can start after ~1 s instead of after the whole sentence."""
    q: queue.Queue = queue.Queue()

    async def run() -> None:
        try:
            async for chunk in _communicate(text, voice, lang).stream():
                if chunk["type"] == "audio":
                    q.put(chunk["data"])
        except Exception as e:
            q.put(e)
        finally:
            q.put(None)

    asyncio.run_coroutine_threadsafe(run(), _loop())
    while True:
        try:
            item = q.get(timeout=30)
        except queue.Empty:
            raise TimeoutError("the voice service stopped responding") from None
        if item is None:
            return
        if isinstance(item, Exception):
            raise item
        yield item


# One long-lived event loop is ~2x faster than a fresh asyncio.run() per sentence.
_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_LOCK = threading.Lock()


def _loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.new_event_loop()
            threading.Thread(target=_LOOP.run_forever, name="tts-loop", daemon=True).start()
        return _LOOP


def warm_up() -> None:
    """Synthesize a tiny phrase in the background so the first real reply isn't the slow one."""
    def go() -> None:
        try:
            synthesize("Ready.")
        except Exception:
            pass
    threading.Thread(target=go, name="tts-warmup", daemon=True).start()

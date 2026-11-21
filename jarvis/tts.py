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
    speed = f"{speed_pct():+d}%"
    return (voice, speed, "+0Hz") if voice.startswith("ur-") else (voice, speed, f"{pitch_hz():+d}Hz")


# ---------------- Settings › Voices: speed, pitch, and online voices vs voices on this PC ----------------
def _setting_int(key: str, default: int, low: int, high: int) -> int:
    from . import schedule
    try:
        return max(low, min(high, int(schedule.get_setting(key, default))))
    except (TypeError, ValueError):
        return default


def _num(text: str) -> int:
    """'+5%' -> 5, '-2Hz' -> -2."""
    try:
        return int(str(text).lower().replace("%", "").replace("hz", "").strip() or 0)
    except ValueError:
        return 0


def speed_pct() -> int:
    """Speaking speed in % (0 = normal). Both online voices and voices on this PC."""
    return _setting_int("voice_speed", _num(RATE), -50, 50)


def pitch_hz() -> int:
    """Pitch change in Hz (online voices only: the voices on this PC can't change pitch)."""
    return _setting_int("voice_pitch", _num(PITCH), -20, 20)


def mode() -> str:
    """'auto' (online voices when there's internet, this PC when not or if they fail), 'online' or 'local'."""
    from . import schedule
    m = schedule.get_setting("tts_engine") or "auto"
    return m if m in ("auto", "online", "local") else "auto"


def local_voice(text: str, lang: str | None = None, after_failure: bool = False) -> str | None:
    """The voice on this PC to use for this text right now, or None to use the online voices."""
    from . import local_tts
    if not local_tts.available():
        return None
    v = local_tts.pick(text, lang)
    if not v:
        return None
    m = mode()
    if m == "local" or after_failure:
        return v
    if m == "auto":
        from .providers import online
        if not online():
            return v
    return None


def speak_local(text: str, voice: str) -> bytes:
    """WAV from a voice on this PC, at the chosen speed."""
    from . import local_tts
    return local_tts.synthesize(text, voice, 1 + speed_pct() / 100)


def _communicate(text: str, voice: str | None, lang: str | None = None):
    import edge_tts
    v, rate, pitch = _resolve(text, voice, lang)
    return edge_tts.Communicate(text, v, rate=rate, pitch=pitch, connect_timeout=8)


async def _audio(text: str, voice: str | None, lang: str | None):
    """MP3 chunks. If the chosen voice can't read the text at all (another script or language: the service
    answers "NoAudioReceived"), a multilingual voice of the same gender reads it instead."""
    got = False
    try:
        async for chunk in _communicate(text, voice, lang).stream():
            if chunk["type"] == "audio":
                got = True
                yield chunk["data"]
    except Exception as e:
        if got or type(e).__name__ != "NoAudioReceived":
            raise
        import edge_tts
        female = any(f in (voice or DEFAULT_VOICE) for f in _FEMALE)
        alt = "en-US-AvaMultilingualNeural" if female else "en-US-AndrewMultilingualNeural"
        print(f"[speech] {voice or DEFAULT_VOICE} couldn't read {text[:40]!r}; {alt} reads it instead")
        async for chunk in edge_tts.Communicate(text, alt, connect_timeout=8).stream():
            if chunk["type"] == "audio":
                yield chunk["data"]


def synthesize(text: str, voice: str | None = None, lang: str | None = None) -> bytes:
    """Return the whole sentence as MP3. Raises on network/service errors."""
    async def run() -> bytes:
        audio = bytearray()
        async for chunk in _audio(text, voice, lang):
            audio += chunk
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
            async for chunk in _audio(text, voice, lang):
                q.put(chunk)
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

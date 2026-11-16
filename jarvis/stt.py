"""Speech-to-text: turns recorded audio (WAV) into text.

1st choice: Whisper large-v3 on Groq (free key). It first works out which language you spoke:
            English stays English; Urdu/Hindi/Punjabi is written in Urdu script.
            Whisper "guesses" whole sentences when the audio is unclear (e.g. fan noise),
            so low-confidence results are rejected instead of being sent to Jarvis.
2nd choice: Gemini (free key) listening to the audio.
If neither key is set, the HUD falls back to the built-in Windows recognizer.
"""
from __future__ import annotations

import base64
import os
import re

from . import config  # noqa: F401  (importing config loads the API keys from .env)

# Whisper sometimes "hears" these on near-silent clips.
_HALLUCINATIONS = {
    "thank you", "thank you.", "thanks for watching", "thanks for watching!", "you", "bye", "bye.",
    "thank you for watching", "thank you for watching.", ".", "the the", "the", "so", "okay.", "hmm",
    "please subscribe", "subscribe", "shukriya", "شکریہ", "سبسکرائب",
    "music", "[music]", "(music)", "♪", "♪♪", "موسیقی", "[موسیقی]", "संगीत", "धन्यवाद", "subtitles by",
}
_SOUTH_ASIAN = {"urdu", "hindi", "punjabi", "ur", "hi", "pa", "sindhi", "sd"}
_PLAUSIBLE = _SOUTH_ASIAN | {"english", "en"}
LAST: dict = {}                      # details of the last transcription, for the log


def engines() -> list[str]:
    out = []
    if os.environ.get("GROQ_API_KEY"):
        out.append("whisper")
    if os.environ.get("GEMINI_API_KEY"):
        out.append("gemini")
    return out


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return "" if text.lower().strip(" .!?,") in {h.strip(" .!?,") for h in _HALLUCINATIONS} else text


def _client():
    import openai
    return openai.OpenAI(api_key=os.environ["GROQ_API_KEY"], base_url="https://api.groq.com/openai/v1",
                         timeout=40, max_retries=1)


FAST_MODEL = os.environ.get("JARVIS_STT_MODEL", "whisper-large-v3-turbo")   # ~0.5 s
URDU_MODEL = os.environ.get("JARVIS_STT_URDU_MODEL", "whisper-large-v3")    # slower, better Urdu


def _whisper_once(wav: bytes, language: str | None, model: str | None = None) -> dict:
    # No prompt on purpose: on noisy audio Whisper tends to "hear" the prompt text itself.
    kwargs = {"language": language} if language else {}
    r = _client().audio.transcriptions.create(
        model=model or FAST_MODEL,
        file=("speech.wav", wav, "audio/wav"), temperature=0,
        response_format="verbose_json", **kwargs)
    d = r.model_dump() if hasattr(r, "model_dump") else dict(r)
    segs = d.get("segments") or []
    n = max(1, len(segs))
    return {"text": (d.get("text") or "").strip(),
            "language": (d.get("language") or language or "").lower(),
            "logprob": sum(s.get("avg_logprob", 0) for s in segs) / n if segs else 0.0,
            "no_speech": sum(s.get("no_speech_prob", 0) for s in segs) / n if segs else 0.0}


def _repetitive(text: str) -> bool:
    """'You're a little bit better. You're a little bit better. ...' = Whisper looping on noise."""
    parts = [p.strip(" .!?,").lower() for p in re.split(r"[.!?،۔]+", text) if p.strip(" .!?,")]
    return len(parts) >= 3 and len(set(parts)) <= len(parts) / 2


def _confident(r: dict) -> bool:
    if not r["text"] or _repetitive(r["text"]):
        return False
    if r["no_speech"] > 0.6 and r["logprob"] < -0.6:
        return False                      # mostly noise
    return r["logprob"] > -1.05           # very low = Whisper is guessing


def _whisper(wav: bytes, mode: str) -> str:
    """mode 'ur' = Urdu; 'auto'/'en' = automatic English/Urdu; another language code = that language."""
    from . import languages
    other = mode not in ("ur", "en", "auto") and not mode.startswith("custom:")
    if mode == "ur":
        r = _whisper_once(wav, "ur", URDU_MODEL)
    elif other:                                            # e.g. Arabic, Hindi, French: tell Whisper
        r = _whisper_once(wav, languages.stt_code(mode), URDU_MODEL)
    elif mode.startswith("custom:"):
        r = _whisper_once(wav, None, URDU_MODEL)           # any language: let large-v3 detect it
    else:
        r = _whisper_once(wav, None)                       # let Whisper detect the language
        lang = r["language"]
        if lang in _SOUTH_ASIAN and lang not in ("ur", "urdu"):
            r = _whisper_once(wav, "ur", URDU_MODEL)       # Hindi/Punjabi -> write it in Urdu script
        elif lang not in _PLAUSIBLE:                       # an odd language = probably a bad guess
            r = _whisper_once(wav, "en")                   # one quick English retry
        elif r["logprob"] < -0.35 and _confident(r):
            # The fast model never says how likely "no speech" is, and on fan noise it can be
            # sure of itself and still make a sentence up. Double-check doubtful ones with large-v3.
            check = _whisper_once(wav, None, URDU_MODEL)
            if check["no_speech"] > 0.35 or check["logprob"] < -0.8:
                r = {**r, "rejected_by": f"large-v3 no_speech={check['no_speech']:.2f} logprob={check['logprob']:.2f}",
                     "text": ""}
    LAST.clear()
    LAST.update(r)
    if not _confident(r):
        LAST["rejected"] = True
        return ""
    return r["text"]


def _gemini(wav: bytes, mode: str) -> str:
    import openai
    client = openai.OpenAI(api_key=os.environ["GEMINI_API_KEY"],
                           base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
                           timeout=30, max_retries=1)
    how = ("The speaker uses Urdu: write it in Urdu script." if mode == "ur" else
           "Write English as English; if the speaker uses Urdu or Hindi, write it in Urdu script.")
    resp = client.chat.completions.create(
        model=os.environ.get("JARVIS_STT_GEMINI_MODEL", "gemini-3.5-flash-lite"),
        messages=[{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}},
            {"type": "text", "text": "Transcribe exactly what the speaker says. " + how +
             " Output only the words. If there is no clear speech, output nothing."},
        ]}])
    LAST.clear()
    LAST.update({"engine": "gemini"})
    return resp.choices[0].message.content or ""


def transcribe(wav: bytes, language: str | None = None) -> tuple[str, str]:
    """Returns (text, engine used). language: 'ur' = Urdu mode, else automatic English/Urdu.
    Empty text means nothing clear was said. Raises RuntimeError if every engine failed."""
    mode = (language or os.environ.get("JARVIS_STT_LANGUAGE", "auto")).lower()
    errors = []
    for name, fn in (("whisper", _whisper), ("gemini", _gemini)):
        if name not in engines():
            continue
        try:
            return _clean(fn(wav, mode)), name
        except Exception as e:  # try the next engine
            errors.append(f"{name}: {type(e).__name__}: {str(e)[:150]}")
    raise RuntimeError("; ".join(errors) or "no speech-to-text engine configured")

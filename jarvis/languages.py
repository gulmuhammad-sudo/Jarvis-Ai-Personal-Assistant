"""Languages the assistant can talk in: name, native name, speech-recognition code and voices.

Any other language works too ("custom:Swahili"): the AI replies in it, speech recognition detects it
automatically, and a multilingual voice reads it aloud.
"""
from __future__ import annotations

# code: (English name, native name, Whisper/Gemini code, male voice, female voice, right-to-left)
LANGUAGES: dict[str, tuple] = {
    "en": ("English", "English", "en", "en-GB-RyanNeural", "en-GB-SoniaNeural", False),
    "ur": ("Urdu", "اردو", "ur", "ur-PK-AsadNeural", "ur-PK-UzmaNeural", True),
    "hi": ("Hindi", "हिन्दी", "hi", "hi-IN-MadhurNeural", "hi-IN-SwaraNeural", False),
    "ar": ("Arabic", "العربية", "ar", "ar-SA-HamedNeural", "ar-SA-ZariyahNeural", True),
    "ps": ("Pashto", "پښتو", "ps", "ps-AF-GulNawazNeural", "ps-AF-LatifaNeural", True),
    "fa": ("Persian", "فارسی", "fa", "fa-IR-FaridNeural", "fa-IR-DilaraNeural", True),
    "bn": ("Bengali", "বাংলা", "bn", "bn-BD-PradeepNeural", "bn-BD-NabanitaNeural", False),
    "pa": ("Punjabi", "پنجابی", "pa", "", "", True),
    "tr": ("Turkish", "Türkçe", "tr", "tr-TR-AhmetNeural", "tr-TR-EmelNeural", False),
    "fr": ("French", "Français", "fr", "fr-FR-HenriNeural", "fr-FR-DeniseNeural", False),
    "es": ("Spanish", "Español", "es", "es-ES-AlvaroNeural", "es-ES-ElviraNeural", False),
    "de": ("German", "Deutsch", "de", "de-DE-ChristophNeural", "de-DE-TanjaNeural", False),
    "pt": ("Portuguese", "Português", "pt", "pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", False),
    "it": ("Italian", "Italiano", "it", "it-IT-DiegoNeural", "it-IT-ElsaNeural", False),
    "ru": ("Russian", "Русский", "ru", "ru-RU-DmitryNeural", "ru-RU-SvetlanaNeural", False),
    "zh": ("Chinese", "中文", "zh", "zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural", False),
    "ja": ("Japanese", "日本語", "ja", "ja-JP-KeitaNeural", "ja-JP-NanamiNeural", False),
    "id": ("Indonesian", "Bahasa Indonesia", "id", "id-ID-ArdiNeural", "id-ID-GadisNeural", False),
    "ms": ("Malay", "Bahasa Melayu", "ms", "ms-MY-OsmanNeural", "ms-MY-YasminNeural", False),
}
MULTILINGUAL = ("en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural")
# other languages Whisper knows (typed under "Other language"): name -> Whisper code
WHISPER_CODES = {
    "sindhi": "sd", "swahili": "sw", "korean": "ko", "nepali": "ne", "tamil": "ta", "telugu": "te", "marathi": "mr",
    "gujarati": "gu", "kannada": "kn", "malayalam": "ml", "thai": "th", "vietnamese": "vi", "dutch": "nl", "polish": "pl",
    "ukrainian": "uk", "greek": "el", "hebrew": "he", "kazakh": "kk", "uzbek": "uz", "tagalog": "tl", "filipino": "tl",
    "somali": "so", "hausa": "ha", "yoruba": "yo", "amharic": "am", "sinhala": "si", "burmese": "my", "khmer": "km",
    "lao": "lo", "mongolian": "mn", "azerbaijani": "az", "georgian": "ka", "armenian": "hy", "czech": "cs",
    "romanian": "ro", "hungarian": "hu", "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi",
    "serbian": "sr", "croatian": "hr", "bosnian": "bs", "slovak": "sk", "slovenian": "sl", "bulgarian": "bg",
    "lithuanian": "lt", "latvian": "lv", "estonian": "et", "catalan": "ca", "afrikaans": "af", "welsh": "cy",
    "tajik": "tg", "turkmen": "tk", "tatar": "tt", "maltese": "mt", "icelandic": "is", "irish": "ga", "basque": "eu",
    "galician": "gl", "belarusian": "be", "macedonian": "mk", "albanian": "sq", "assamese": "as", "odia": "or",
}


def clean(code: str | None) -> str:
    """A known code, or 'custom:<Name>' for any other language."""
    code = (code or "en").strip()
    low = code.lower()
    if low in LANGUAGES:
        return low
    for k, v in LANGUAGES.items():                 # "Urdu", "urdu", "اردو" -> "ur"
        if low in (v[0].lower(), v[1].lower()):
            return k
    if low.startswith("custom:"):
        code = code[7:]
    name = " ".join(code.split())[:30]
    return f"custom:{name.title()}" if name and name.replace(" ", "").isalpha() else "en"


def name(code: str) -> str:
    code = clean(code)
    return code[7:] if code.startswith("custom:") else LANGUAGES[code][0]


def native(code: str) -> str:
    code = clean(code)
    return code[7:] if code.startswith("custom:") else LANGUAGES[code][1]


def stt_code(code: str) -> str | None:
    """What to tell speech recognition (None = detect it)."""
    code = clean(code)
    if code.startswith("custom:"):
        return WHISPER_CODES.get(code[7:].lower())        # e.g. Sindhi -> "sd"; unknown -> detect it
    return LANGUAGES[code][2]


def voice(code: str, female: bool = False) -> str:
    code = clean(code)
    if code in LANGUAGES:
        v = LANGUAGES[code][4 if female else 3]
        if v:
            return v
    return MULTILINGUAL[1 if female else 0]


def all_voices() -> set[str]:
    return {v for row in LANGUAGES.values() for v in row[3:5] if v} | set(MULTILINGUAL)


def reply_note(code: str) -> str:
    """Extra instructions for the AI (English and Urdu have their own, older notes)."""
    code = clean(code)
    if code in ("en", "ur"):
        return ""
    return (f"\nLANGUAGE: the user chose {name(code)} ({native(code)}). Always reply in natural, simple {name(code)}, "
            f"written in its usual script, short and conversational because it may be read aloud. Keep app names, "
            "numbers and technical terms as they are when that is clearer.\n")


def choices() -> list[dict]:
    return [{"code": k, "name": v[0], "native": v[1], "rtl": v[5]} for k, v in LANGUAGES.items()]


LIVE_VOICES = {   # Gemini Live's voices (male-sounding ones first; Charon is the closest to the films' Jarvis)
    "Charon": "deep, informative", "Iapetus": "clear", "Orus": "firm", "Sadaltager": "knowledgeable",
    "Rasalgethi": "informative", "Algenib": "gravelly", "Fenrir": "lively", "Puck": "upbeat",
    "Umbriel": "easy-going", "Schedar": "even", "Kore": "firm (female)", "Aoede": "breezy (female)",
}

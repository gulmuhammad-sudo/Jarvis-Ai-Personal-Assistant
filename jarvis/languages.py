"""Languages the assistant can talk in: name, native name, speech-recognition code and voices.

Any other language works too ("custom:Swahili"): the AI replies in it, speech recognition detects it
automatically, and a multilingual voice reads it aloud.
"""
from __future__ import annotations

import re
import unicodedata

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
            "numbers and technical terms as they are when that is clearer. If the user asks for something in another language, give that in that language and its own script.\n")


def choices() -> list[dict]:
    return [{"code": k, "name": v[0], "native": v[1], "rtl": v[5]} for k, v in LANGUAGES.items()]


LIVE_VOICES = {   # Gemini Live's voices (male-sounding ones first; Charon is the closest to the films' Jarvis)
    "Charon": "deep, informative", "Iapetus": "clear", "Orus": "firm", "Sadaltager": "knowledgeable",
    "Rasalgethi": "informative", "Algenib": "gravelly", "Fenrir": "lively", "Puck": "upbeat",
    "Umbriel": "easy-going", "Schedar": "even", "Kore": "firm (female)", "Aoede": "breezy (female)",
    # the same kind of voice, told to speak like someone from Pakistan (Google has no voice from there)
    "Aoede (Pakistani)": "breezy (female)", "Leda (Pakistani)": "youthful (female)", "Zephyr (Pakistani)": "bright (female)",
    "Kore (Pakistani)": "firm (female)", "Sulafat (Pakistani)": "warm (female)", "Achernar (Pakistani)": "soft (female)",
}


def live_name(voice: str) -> str:
    """Google's own name of a Live voice: "Leda (Pakistani)" -> "Leda"."""
    return voice.split(" (")[0]


def live_female(voice: str) -> bool:
    return "(female)" in LIVE_VOICES.get(voice, "")


def accent(voice: str) -> str:
    """How a Live voice should speak."""
    if "(Pakistani)" in voice:
        return ("You are a Pakistani woman. Speak with a natural, educated Pakistani accent, warm and polite, in Urdu and in English alike "
                "(never a British or Indian one). In Urdu use the everyday words of Pakistan (shukriya, ji, theek hai, meherbani), not Hindi ones "
                "(dhanyavaad, kripya, namaste). " + WOMAN)
    return "Speak with a calm, refined British accent, like a loyal butler-engineer." + (" " + WOMAN if live_female(voice) else "")


WOMAN = "Your voice is a woman's: in Urdu and Hindi speak of yourself in the feminine (main kar rahi hun, میں کر سکتی ہوں)."


# ---------------- "tell me in Urdu": the language you asked an answer for ----------------
_CALLED = {
    "ur": "urdu ordu اردو اُردو उर्दू उर्दु उरदू", "hi": "hindi ہندی हिंदी हिन्दी हिंदि", "en": "english angrezi angreezi inglish انگریزی انگلش अंग्रेजी अंग्रेज़ी इंग्लिश इंगलिश",
    "ar": "arabic arabi عربی العربية अरबी अरेबिक", "fa": "persian farsi فارسی फारसी फ़ारसी", "ps": "pashto pushto پشتو پښتو पश्तो", "pa": "punjabi panjabi پنجابی पंजाबी", "custom:Sindhi": "sindhi سندھی सिंधी",
    "bn": "bengali bangla بنگالی बंगाली बांग्ला", "tr": "turkish turki ترکی तुर्की", "fr": "french فرانسیسی فرنچ फ्रेंच", "es": "spanish ہسپانوی سپینش स्पेनिश", "de": "german جرمن जर्मन", "it": "italian اطالوی इटालियन",
    "pt": "portuguese पुर्तगाली", "ru": "russian روسی रूसी रशियन", "zh": "chinese چینی چائنیز चाइनीज", "ja": "japanese جاپانی जापानी", "custom:Korean": "korean کورین कोरियन", "id": "indonesian", "ms": "malay",
}
LATIN = {"en", "tr", "fr", "es", "de", "it", "pt", "id", "ms", "roman"}        # written in English letters anyway


def _plain(word: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", word).replace("\u093c", "")).lower()


_NAMES = {_plain(w): code for code, words in _CALLED.items() for w in words.split()}
_NAMES.update({n: f"custom:{n.title()}" for n in WHISPER_CODES if n not in _NAMES})
_NAMES.update({_plain(w): "roman" for w in "roman رومن रोमन रोमन्".split()})
_NAMES.pop("irish", None), _NAMES.pop("thai", None)                           # (food and people, more often than a language)
_IN = {_plain(w) for w in "mein main me mai m men mn میں مے में मे मैं".split()}
_FILL = {_plain(w) for w in "zaban zubaan zuban language bhasha script writing likhai lipi letters huroof haroof alphabet زبان لکھائی رسم الخط حروف भाषा ज़बान जबान जुबान लिपि लैंग्वेज राइटिंग स्क्रिप्ट लेटर्स".split()}
_LETTERS = {_plain(w) for w in "letters huroof haroof alphabet حروف लेटर्स writing राइटिंग".split()}
_TRANSLATION = {_plain(w) for w in "translation translate tarjuma tarjama tarjma ترجمہ अनुवाद ट्रांसलेशन ट्रांसलेट तर्जुमा".split()}
_SAY = {_plain(w) for w in "bolo boliye bolna likho likhna likhiye بولو لکھو بولیں لکھیں बोलो लिखो बोलिए लिखिए".split()}
_SPEAK = {"speak", "write", "talk", "reply", "answer", "use"}
_NO = {_plain(w) for w in "mat nahi nahin nai nhi not don't dont kyun kyon kyu why مت نہیں کیوں मत नहीं क्यों क्यूं".split()}
_NA = {_plain(w) for w in "na naa نہ نا ना न".split()}
_DO = {_plain(w) for w in "karo karna kare karen kro krna likho likhna bolo bolna convert change badlo کرو کرنا لکھو بولو کنورٹ करो करना करे करें लिखो बोलो कन्वर्ट".split()}
_WORDS = re.compile(r"[^\s,.;:!?؟،۔।\"“”()\[\]{}<>/|…—–]+")


def asked_for(text: str) -> str:
    """The language somebody asks an answer in ("Urdu mein batao", "translate it to Hindi", "उर्दू में बताओ"): its code, "roman" for English letters, or ""."""
    t = [_plain(w) for w in _WORDS.findall(str(text or "")[:2000])]
    found = ""
    for i, w in enumerate(t):
        code = _NAMES.get(w)
        if not code:
            continue
        if w == "urdu" and i and _NAMES.get(t[i - 1]) == "roman":
            continue                                     # "Roman Urdu" was taken with "Roman"
        j = i + 1
        if code == "roman" and j < len(t) and _NAMES.get(t[j]) in ("ur", "en"):
            j += 1
        if code == "en" and j < len(t) and t[j] in _LETTERS:
            code = "roman"                               # "English letters"
        while j < len(t) and t[j] in _FILL:
            j += 1
        after, before = t[j] if j < len(t) else "", t[i - 1] if i else ""
        hit = after in _IN or before in ("in", "into") or before == "to" and any(x in _TRANSLATION or x in ("convert", "translated") for x in t) or after in _TRANSLATION or after in _SAY or before in _SPEAK
        if not hit:
            continue
        rest = t[j + 1:j + 4] if after in _IN else t[j:j + 3]
        for k, x in enumerate(rest):                     # up to the next language
            if x in _NAMES:
                rest = rest[:k]
                break
        no = any(x in _NO for x in rest) or any(x in _NA and (k == 0 or k + 1 < len(rest) and rest[k + 1] in _DO) for k, x in enumerate(rest)) or any(x in ("not", "don't", "dont", "never") for x in t[max(0, i - 3):i])
        if not no:
            found = code
    return found

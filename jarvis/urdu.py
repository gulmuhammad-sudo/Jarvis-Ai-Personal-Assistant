"""Devanagari -> Urdu script.

Gemini Live writes spoken Urdu in Hindi letters ("आज मौसम कैसा है"). Spoken Hindi and Urdu are the same
language, so a letter-by-letter mapping gives readable Urdu ("آج موسم کیسا ہے"). Used for what you say and
what the assistant says on Live calls, unless you chose Hindi as your language.
"""
from __future__ import annotations

import re

NUKTA, VIRAMA = "़", "्"
CONS = {
    "क": "ک", "ख": "کھ", "ग": "گ", "घ": "گھ", "ङ": "ن", "च": "چ", "छ": "چھ", "ज": "ج", "झ": "جھ", "ञ": "ن",
    "ट": "ٹ", "ठ": "ٹھ", "ड": "ڈ", "ढ": "ڈھ", "ण": "ن", "त": "ت", "थ": "تھ", "द": "د", "ध": "دھ", "न": "ن",
    "प": "پ", "फ": "پھ", "ब": "ب", "भ": "بھ", "म": "م", "य": "ی", "र": "ر", "ल": "ل", "व": "و", "श": "ش",
    "ष": "ش", "स": "س", "ह": "ہ", "क़": "ق", "ख़": "خ", "ग़": "غ", "ज़": "ز", "ड़": "ڑ", "ढ़": "ڑھ", "फ़": "ف",
    "य़": "ی", "ऱ": "ر", "ऩ": "ن", "ळ": "ل", "ॹ": "ژ",
}
PRECOMPOSED = {"क़": "क़", "ख़": "ख़", "ग़": "ग़", "ज़": "ज़", "ड़": "ड़", "ढ़": "ढ़", "फ़": "फ़", "य़": "य़"}
VOWELS = {"अ": "ا", "आ": "آ", "इ": "ا", "ई": "ای", "उ": "ا", "ऊ": "او", "ए": "ای", "ऐ": "اے", "ओ": "او", "औ": "او",
          "ऋ": "رِ", "ऑ": "آ", "ॲ": "ا"}
SIGNS = {"ा": "ا", "ि": "", "ी": "ی", "ु": "", "ू": "و", "ृ": "ر", "ॉ": "ا", "ो": "و", "ौ": "و"}
WORDS = {"कि": "کہ", "है": "ہے", "हैं": "ہیں", "में": "میں", "मैं": "میں", "यह": "یہ", "वह": "وہ", "ये": "یہ", "वो": "وہ",
         "क्या": "کیا", "नहीं": "نہیں", "तो": "تو", "और": "اور", "कहा": "کہا", "कहाँ": "کہاں", "हाँ": "ہاں", "जी": "جی",
         "मैंने": "میں نے", "हमने": "ہم نے", "तुमने": "تم نے", "आपने": "آپ نے", "उसने": "اس نے", "इसने": "اس نے",
         "ज़रूर": "ضرور", "जरूर": "ضرور", "ज़रा": "ذرا", "शुक्रिया": "شکریہ", "अल्लाह": "اللہ", "इंशाअल्लाह": "ان شاء اللہ",
         "माशाअल्लाह": "ماشاء اللہ", "सलाम": "سلام", "ख़ुदा": "خدا", "दुआ": "دعا", "वक़्त": "وقت", "वक्त": "وقت",
         "मौसम": "موسم", "ख़बर": "خبر", "ख़बरें": "خبریں", "ज़्यादा": "زیادہ", "ज्यादा": "زیادہ", "दफ़ा": "دفعہ"}
PUNCT = {"।": "۔", "॥": "۔", "?": "؟", ",": "،", ";": "؛"}
DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_WORD = re.compile(r"[ऀ-ॣ०-ॿ]+")     # (not the danda "।", that's punctuation)


def mostly_latin(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) > 3 and sum("a" <= c.lower() <= "z" for c in letters) / len(letters) > 0.7


def has_other_script(text: str) -> bool:
    """Any Urdu/Arabic or Hindi letters in it?"""
    return any("\u0600" <= c <= "\u06ff" or "\u0900" <= c <= "\u097f" for c in text or "")


_URDU_ONLY = set("ٹڈڑںےھہۂۓ")
_NOT_URDU = set("ښېځڅډړږڼۍئۀ" "ڳڻٻڄڃٿٽڍڌڏڊڦڪڱ") - set("ئ")


def looks_urdu(text: str) -> bool:
    """Urdu (or Hindi) letters that may be rewritten in English letters: not Arabic, Persian, Pashto or Sindhi, which stay as they are."""
    return has_devanagari(text) or any(c in _URDU_ONLY for c in text or "") and not any(c in _NOT_URDU for c in text or "")


def from_hindi(text: str) -> str:
    """What a Live call wrote down in Hindi letters, in correct Urdu. "" if it couldn't be done."""
    prompt = ("These words were spoken in Urdu but written down in Hindi letters. Write them in correct Urdu script. Keep exactly the same words, do not translate, add or drop anything; "
              "words in English letters or other languages stay as they are. Reply with the rewritten text only.\n\n" + text)
    return _rewrite(prompt, lambda out: not has_devanagari(out) and sum("\u0600" <= c <= "\u06ff" for c in out) > len(out) * 0.3)


def to_urdu_script(text: str) -> str:
    """Roman Urdu ("Main theek hoon, Gul!") -> Urdu script ("میں ٹھیک ہوں، Gul!"); English is translated into Urdu.
    Only names, app names and numbers stay in English letters. "" if it couldn't be done."""
    prompt = ("Write this chat message in Urdu script. If it is Urdu written in English or Hindi letters, keep exactly "
              "the same words and meaning, and write the English words an Urdu speaker uses in Urdu letters too "
              "(volume -> والیوم, problem -> پرابلم, check -> چیک). If it is English, translate it into natural, simple Urdu. "
              "Only people's names, app or website names and numbers stay in English letters. "
              "Reply with the rewritten text only.\n\n" + text)
    out = _rewrite(prompt, lambda out: sum("\u0600" <= c <= "\u06ff" for c in out) > len(out) * 0.3)
    return from_devanagari(out)                # (the AI now and then slips a Hindi-letter word in)


def to_roman(text: str) -> str:
    """Urdu or Hindi letters ("میں ٹھیک ہوں") -> English letters ("Main theek hoon"). "" if it couldn't be done."""
    prompt = ("Rewrite this chat message in English letters. Urdu or Hindi words become Roman Urdu, written the usual "
              "way Pakistanis type it (e.g. \"میں ٹھیک ہوں، آپ کیسے ہیں؟\" -> \"Main theek hoon, aap kaise hain?\"). "
              "Keep exactly the same words and meaning: do not translate, add or drop anything; English stays as it is. "
              "Reply with the rewritten text only.\n\n" + text)
    return _rewrite(prompt, lambda out: not has_other_script(out))


def _rewrite(prompt: str, good) -> str:
    """One quick free AI call (Gemini, then Groq); the answer only if good(answer)."""
    import os
    tries = []
    if os.environ.get("GEMINI_API_KEY"):
        tries.append(("https://generativelanguage.googleapis.com/v1beta/openai/", os.environ["GEMINI_API_KEY"], "gemini-3.5-flash-lite"))
    if os.environ.get("GROQ_API_KEY"):
        tries.append(("https://api.groq.com/openai/v1", os.environ["GROQ_API_KEY"], "openai/gpt-oss-20b"))
    for base, key, model in tries:
        try:
            import openai
            r = openai.OpenAI(api_key=key, base_url=base, timeout=15, max_retries=0).chat.completions.create(
                model=model, messages=[{"role": "user", "content": prompt}], temperature=0)
            out = (r.choices[0].message.content or "").strip()
            if out and good(out):
                return out
        except Exception as e:
            print(f"[urdu] couldn't rewrite the chat text with {model}: {str(e)[:80]}")
    return ""


def has_devanagari(text: str) -> bool:
    return bool(text) and any("ऀ" <= ch <= "ॿ" for ch in text)


def _word(w: str) -> str:
    if w in WORDS:
        return WORDS[w]
    for k, v in PRECOMPOSED.items():
        w = w.replace(k, v)
    out, i, n = [], 0, len(w)
    while i < n:
        ch = w[i]
        last = i == n - 1
        if ch + (w[i + 1] if i + 1 < n else "") in CONS and i + 1 < n and w[i + 1] == NUKTA:
            out.append(CONS[ch + NUKTA]); i += 2; continue
        if ch in CONS:
            out.append(CONS[ch])
        elif ch in VOWELS and i and ch in "इईएऐउऊओऔ":   # a vowel inside a word: फ़ाइल فائل, जाओ جاؤ, आइए آئیے
            if ch in "एऐ" and out and out[-1] == "ئ":
                out.append("یے" if last else "ی")
            else:
                out.append("ئ" if ch == "इ" else "ئی" if ch == "ई" else ("ئے" if last else "ئی") if ch in "एऐ" else "ؤ")
        elif ch in VOWELS:
            out.append(VOWELS[ch])
        elif ch in ("े", "ै"):                 # word-final -> ے ("मुझे" مجھے), inside a word -> ی ("कैसा" کیسا)
            out.append("ے" if last else "ی")
        elif ch in SIGNS:
            out.append(SIGNS[ch])
        elif ch in ("ं", "ँ"):
            out.append("ں" if last else "ن")
        elif ch == "ः":
            out.append("ہ")
        elif ch in (VIRAMA, NUKTA):
            pass
        elif ch in DIGITS:
            out.append(DIGITS[ch])
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def from_devanagari(text: str) -> str:
    """Rewrite any Devanagari words in text in Urdu script (other text is left as it is)."""
    if not has_devanagari(text):
        return text
    out = _WORD.sub(lambda m: _word(m.group(0)), text)
    if any("؀" <= ch <= "ۿ" for ch in out):
        out = "".join(PUNCT.get(ch, ch) for ch in out)
    return out

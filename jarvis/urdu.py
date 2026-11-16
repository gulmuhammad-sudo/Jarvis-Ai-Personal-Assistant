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

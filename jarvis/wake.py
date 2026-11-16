"""Wake word: the assistant only responds when you call its name ("Maya", "مایا", "Friday...").

match("Maya, aaj mausam kaisa hai?", "Maya") -> (True, "aaj mausam kaisa hai?")
Speech recognition may write the name in English letters, Urdu script or Hindi letters, so all of them are
turned into simple Latin sounds and compared. Short names must match exactly (so "maa" or "main" never
wake "Maya"); longer ones may differ by a letter or in their vowels.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from . import urdu

_U2L = {"ا": "a", "آ": "a", "أ": "a", "إ": "i", "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s", "ج": "j", "چ": "ch",
        "ح": "h", "خ": "kh", "د": "d", "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh", "س": "s", "ش": "sh",
        "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q", "ک": "k", "ك": "k", "گ": "g",
        "ل": "l", "م": "m", "ن": "n", "ں": "n", "و": "v", "ؤ": "v", "ہ": "h", "ۃ": "h", "ھ": "h", "ء": "", "ی": "y",
        "ي": "y", "ے": "e", "ئ": "y", "ى": "y", "ة": "h", "َ": "", "ِ": "", "ُ": "", "ّ": "", "ْ": ""}
FILLERS = {"hey", "hi", "hello", "ok", "okay", "oye", "oy", "suno", "sunno", "suniye", "listen", "please", "ji", "jee",
           "haan", "han", "acha", "achha", "yaar", "bhai", "ae", "ay", "o", "اے", "او", "سنو", "سنیں", "سنیے", "جی", "ہاں",
           "یار", "بھائی", "ہیلو", "ہائے"}


def _latin(word: str) -> str:
    """A word in any script -> simple, normalised Latin sounds."""
    w = word.lower()
    if any("؀" <= c <= "ۿ" for c in w):
        w = "".join(_U2L.get(c, "") for c in w)
    w = re.sub(r"[^a-z]", "", w)
    w = w.replace("ph", "f").replace("x", "ks").replace("w", "v").replace("i", "y").replace("ee", "y").replace("oo", "u")
    w = re.sub(r"(.)\1+", r"\1", w)                     # aa -> a, yy -> y
    if len(w) > 3 and w.endswith("h"):
        w = w[:-1]
    return w


def _skeleton(w: str) -> str:
    return w[:1] + re.sub(r"[aeouyh]", "", w[1:])


def _same(word: str, name: str, urdu_script: bool = False) -> bool:
    if not word or not name:
        return False
    if word == name:
        return True
    if len(name) <= 4:                                  # short names: exact only...
        # ...except in Urdu script, where "Max" comes back as میکس / ماکس: the same 3+ consonants are enough
        return urdu_script and len(_skeleton(name)) >= 3 and _skeleton(word) == _skeleton(name)
    close = SequenceMatcher(None, word, name).ratio() >= 0.8 and abs(len(word) - len(name)) <= 1 and word[0] == name[0]
    # Urdu script often leaves vowels out or spells them differently: matching consonants are enough there
    skel = urdu_script and _skeleton(word) == _skeleton(name) and len(_skeleton(name)) >= 3
    return close or skel


def match(text: str, name: str) -> tuple[bool, str]:
    """(was the name said?, what was said after it, without greetings)."""
    text = urdu.from_devanagari(text or "")
    target = _latin(name.replace(".", ""))
    if not target:
        return False, ""
    tokens = re.findall(r"[\w؀-ۿ']+", text)
    lat = [_latin(t) for t in tokens]
    ur = [any("؀" <= c <= "ۿ" for c in t) for t in tokens]
    hit = -1
    for i in range(len(tokens)):
        if _same(lat[i], target, ur[i]) or (i + 1 < len(tokens) and _same(lat[i] + lat[i + 1], target, ur[i]) and len(target) > 4):
            hit = i
            break
    if hit < 0:
        return False, ""
    span = 2 if not _same(lat[hit], target, ur[hit]) else 1
    rest = [t for t in tokens[:hit] + tokens[hit + span:]]
    while rest and (rest[0].lower() in FILLERS):
        rest.pop(0)
    while rest and rest[-1].lower() in FILLERS:
        rest.pop()
    # keep the original wording/punctuation after the name if the name came first
    after = text.split(tokens[hit + span - 1], 1)[1] if hit == 0 or all(t.lower() in FILLERS for t in tokens[:hit]) else " ".join(rest)
    after = re.sub(r"^[\s,،.!?۔:;-]+", "", after).strip()
    words = re.findall(r"[\w؀-ۿ']+", after)
    if not [w for w in words if w.lower() not in FILLERS]:
        after = ""
    return True, after

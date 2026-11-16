"""Answering an approval by voice: "yes / haan / allow / theek hai" or "no / nahi / deny / cancel".

Only short replies count (up to 10 words), and "no" words win over "yes" words, so
"mat karo" (don't) or "no, don't do it" is never taken as a yes.
"""
from __future__ import annotations

import re

_NO = re.compile(
    r"\b(no|nope|nah|deny|denied|reject|cancel|stop|abort|don'?t|do not|never|not now|"
    r"nahi|nahin|nahee|nai|nhi|na|mat|matt|ruko|ruk jao|rehne do|rehnay do|band karo|chhoro|chhodo)\b"
    r"|نہیں|نہ\b|مت|رکو|رہنے دو|منسوخ|بند کرو")
_YES = re.compile(
    r"\b(yes|yeah|yea|yep|yup|ok|okay|sure|allow|allowed|approve|approved|authori[sz]e|authori[sz]ed|confirm|"
    r"confirmed|go ahead|do it|proceed|of course|please do|"
    r"haan|haa|han|hanji|ha ji|haan ji|ji|jee|ji haan|theek hai|thik hai|theek|thik|kar do|kardo|karo|kar lo|"
    r"chalao|chala do|bilkul|zaroor|zarur)\b"
    r"|ہاں|ہا|جی|ٹھیک|کر دو|کرو|بالکل|ضرور|اجازت")


def parse(text: str) -> bool | None:
    """True = allow, False = deny, None = not a clear answer."""
    t = re.sub(r"[^\w\s'؀-ۿ]", " ", (text or "").lower()).strip()
    if not t or len(t.split()) > 10:
        return None
    if _NO.search(t):
        return False
    if _YES.search(t):
        return True
    return None

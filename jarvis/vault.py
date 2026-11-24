"""The vault: passwords, cards, papers, notes and files, encrypted on this PC (AES-256-GCM).

The key is random and is itself locked up three ways: with a key made from your master password (scrypt, 128 MB), with
one from the recovery code you wrote down, and, if you want, with a signature only Windows Hello can make (see hello.py).
None of them is kept. Nobody can open a vault whose password and recovery code are both lost.

The AI has no way in: there is no tool, agent, automation or plan for it; what is here is never in the conversation, the
Activity list, the record of actions, the database or the log; while it is open the assistant doesn't look at the screen,
and it can't read the clipboard while something from here is on it. Every request needs a secret given out at unlocking.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import string
import struct
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

N, R, P = 2 ** 17, 8, 1                          # scrypt: 128 MB and about half a second per try
MAX_ENTRIES, MAX_FIELD, MAX_TEXT = 5000, 500, 20_000
MAX_FILE, MAX_FILES, MAX_ALL = 20 * 2**20, 20, 500 * 2**20
CHUNK = 2**20
IDLE = (1, 5, 15, 30)
COPY_FOR = 30                                    # seconds something stays on the clipboard
TRASH_DAYS = 30
KINDS = {"login": "Password", "card": "Card", "paper": "Document", "note": "Secure note"}
FIELDS = {"login": ("title", "username", "password", "url", "totp", "notes"),
          "card": ("title", "holder", "number", "expires", "cvv", "pin", "notes"),
          "paper": ("title", "paper", "name", "number", "issued", "expires", "notes"),
          "note": ("title", "notes")}
SECRET = {"password", "totp", "cvv", "pin", "number"}      # never in a list; shown or copied one by one
PAPERS = ("CNIC / ID card", "Passport", "Driving licence", "Birth certificate", "Visa", "Insurance", "Degree / certificate", "Vehicle", "Property", "Bank", "Other")
CHANGED: Callable[[], None] | None = None
_LOCK = threading.RLock()
_OPEN: dict | None = None                        # {"key", "data", "session", "used", "head"} while it is open
_TRIES = {"n": 0, "until": 0.0}
_CLIP = {"seq": None, "timer": None}


class VaultError(ValueError):
    """Something to tell the owner, in plain words."""


# ---------------- files and keys ----------------
def folder() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "vault"


def _file() -> Path:
    return folder() / "vault.json"


def exists() -> bool:
    return _file().is_file() or _file().with_name("vault.json.bak").is_file()


def _b(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _u(text: Any) -> bytes:
    return base64.b64decode(str(text).encode("ascii"), validate=True)


def _gcm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key)


def _seal(key: bytes, data: bytes, about: str) -> str:
    nonce = secrets.token_bytes(12)
    return _b(nonce + _gcm(key).encrypt(nonce, data, about.encode()))


def _unseal(key: bytes, text: Any, about: str) -> bytes | None:
    """None when the key is wrong or anything was changed."""
    from cryptography.exceptions import InvalidTag
    try:
        raw = _u(text)
        return _gcm(key).decrypt(raw[:12], raw[12:], about.encode())
    except (InvalidTag, ValueError, TypeError):
        return None


def _password(value: Any) -> bytes:
    return unicodedata.normalize("NFC", str(value or "")).encode("utf-8")


def _stretch(secret: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(secret, salt=salt, n=N, r=R, p=P, maxmem=256 * 2**20, dklen=32)


def _code(value: Any) -> bytes:
    """A recovery code as typed (small letters, spaces, 0 for O, 1 for I are fine)."""
    return re.sub(r"[^A-Z2-7]", "", str(value or "").upper().replace("0", "O").replace("1", "I").replace("8", "B")).encode()


def _new_code() -> str:
    raw = base64.b32encode(secrets.token_bytes(20)).decode("ascii")          # 160 bits
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def _about(head: dict, what: str) -> str:
    """What is locked up belongs to this vault, with these numbers, and to this use only."""
    return f"pa-vault 1|{head['id']}|{head['n']}|{head['salt']}|{what}"


def strength(pw: Any) -> int:
    """0 (very weak) to 4 (strong), going by length, kinds of signs and repetition. An estimate."""
    s = str(pw or "")
    if not s:
        return 0
    pool = sum(n for n, rx in ((26, "[a-z]"), (26, "[A-Z]"), (10, "[0-9]"), (33, r"[^\w\s]|_"), (100, r"[^\x00-\x7f]")) if re.search(rx, s)) or 1
    import math
    runs = sum(1 for a, b in zip(s, s[1:]) if ord(b) - ord(a) in (0, 1, -1))
    size = max(1, len(set(s)) + (len(s) - len(set(s))) * 0.5 - runs * 0.7)
    if any(w in s.lower() for w in _COMMON):
        size = max(1, size - 6)
    bits = size * math.log2(pool)
    return 0 if bits < 28 else 1 if bits < 40 else 2 if bits < 55 else 3 if bits < 75 else 4


_COMMON = ("password", "qwerty", "123456", "iloveyou", "admin", "welcome", "letmein", "abc123", "pakistan", "111111", "asdfgh", "football", "cricket", "monkey", "dragon", "allah", "786786")


def _check_password(pw: Any) -> bytes:
    p = _password(pw)
    if len(str(pw or "")) < 10:
        raise VaultError("The master password needs at least 10 letters or signs. A few words in a row are fine.")
    if len(p) > 500:
        raise VaultError("The master password is too long.")
    if strength(pw) < 2:
        raise VaultError("That master password is too easy to guess. Use a few unrelated words, or add numbers and signs.")
    return p


def _read() -> dict:
    """The file (the one before it, if it is damaged)."""
    for f in (_file(), _file().with_name("vault.json.bak")):
        try:
            head = json.loads(f.read_text(encoding="utf-8"))
            if head.get("v") == 1 and isinstance(head.get("wrapped"), dict) and head.get("id") and head.get("data"):
                return head
        except (OSError, ValueError, AttributeError):
            continue
    if exists():
        raise VaultError("The vault file is damaged and can't be read. A backup of it may still open.")
    raise VaultError("There is no vault yet.")


def _write(head: dict) -> None:
    """All or nothing, and the version before stays as vault.json.bak."""
    folder().mkdir(parents=True, exist_ok=True)
    f = _file()
    tmp = f.with_name("vault.json.tmp")
    with open(tmp, "w", encoding="utf-8") as h:
        json.dump(head, h)
        h.flush()
        os.fsync(h.fileno())
    for attempt in range(20):
        try:
            if f.is_file():
                os.replace(f, f.with_name("vault.json.bak"))
            os.replace(tmp, f)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


def _tell() -> None:
    if CHANGED:
        try:
            CHANGED()
        except Exception:
            pass


# ---------------- making, opening, locking ----------------
def create(password: Any, again: Any) -> dict:
    """A new vault. Returns {"session", "recovery"}: the recovery code is shown this once."""
    with _LOCK:
        if exists():
            raise VaultError("There is a vault already.")
        if _password(password) != _password(again):
            raise VaultError("The two passwords aren't the same.")
        pw = _check_password(password)
        head = {"v": 1, "id": secrets.token_hex(8), "n": N, "salt": _b(secrets.token_bytes(16)), "wrapped": {}}
        key, code = secrets.token_bytes(32), _new_code()
        head["wrapped"]["password"] = _seal(_stretch(pw, _u(head["salt"])), key, _about(head, "password"))
        head["wrapped"]["recovery"] = _seal(_stretch(_code(code), _u(head["salt"])), key, _about(head, "recovery"))
        data = {"entries": {}, "trash": {}}
        head["data"] = _seal(key, json.dumps(data).encode(), _about(head, "data"))
        _write(head)
        return {"session": _opened(head, key, data), "recovery": code}


def _opened(head: dict, key: bytes, data: dict) -> str:
    global _OPEN
    _OPEN = {"key": key, "data": data, "head": head, "session": secrets.token_urlsafe(24), "used": time.monotonic()}
    _TRIES.update(n=0, until=0.0)
    _drop_old_trash()
    _due_days()
    _tell()
    return _OPEN["session"]


def _wait() -> int:
    return max(0, int(_TRIES["until"] - time.time() + 0.99))


def _wrong(what: str) -> VaultError:
    """After five wrong tries: 30 seconds, then twice as long each time, up to an hour."""
    from . import audit, schedule
    _TRIES["n"] += 1
    if _TRIES["n"] >= 5:
        _TRIES["until"] = time.time() + min(3600, 30 * 2 ** (_TRIES["n"] - 5))
    schedule.set_setting("vault_tries", [_TRIES["n"], int(_TRIES["until"])])
    audit.record("vault_wrong", tries=_TRIES["n"])
    w = _wait()
    return VaultError(f"That isn't the {what}." + (f" Wait {w} seconds before the next try." if w else ""))


def _may_try() -> None:
    from . import schedule
    saved = schedule.get_setting("vault_tries")
    if isinstance(saved, list) and len(saved) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in saved) and saved[0] > _TRIES["n"]:
        _TRIES.update(n=saved[0], until=min(float(saved[1]), time.time() + 3600))        # (a restart doesn't start the count again)
    if w := _wait():
        raise VaultError(f"Too many wrong tries. Wait {w} seconds.")


def _done_trying() -> None:
    from . import schedule
    schedule.set_setting("vault_tries", None)


def _load(head: dict, key: bytes) -> dict:
    raw = _unseal(key, head["data"], _about(head, "data"))
    if raw is None:
        raise VaultError("The vault opened, but what is in it is damaged. A backup of it may still be good.")
    return json.loads(raw.decode("utf-8"))


def unlock(password: Any) -> str:
    with _LOCK:
        _may_try()
        head = _read()
        key = _unseal(_stretch(_password(password), _u(head["salt"])), head["wrapped"].get("password"), _about(head, "password"))
        if key is None:
            raise _wrong("master password")
        s = _opened(head, key, _load(head, key))
        _done_trying()
        return s


def unlock_recovery(code: Any, password: Any, again: Any) -> dict:
    """With the recovery code: a new master password, and a new recovery code (the old one is used up)."""
    with _LOCK:
        _may_try()
        head = _read()
        if _password(password) != _password(again):
            raise VaultError("The two passwords aren't the same.")
        pw = _check_password(password)
        key = _unseal(_stretch(_code(code), _u(head["salt"])), head["wrapped"].get("recovery"), _about(head, "recovery"))
        if key is None:
            raise _wrong("recovery code")
        data, new = _load(head, key), _new_code()
        head["wrapped"] = {"password": _seal(_stretch(pw, _u(head["salt"])), key, _about(head, "password")),
                           "recovery": _seal(_stretch(_code(new), _u(head["salt"])), key, _about(head, "recovery"))}       # (Windows Hello is off again)
        _write(head)
        s = _opened(head, key, data)
        _done_trying()
        return {"session": s, "recovery": new}


def unlock_hello() -> str:
    from . import hello
    head = _read()
    w = head["wrapped"].get("hello")
    if not isinstance(w, dict):
        raise VaultError("Windows Hello isn't turned on for the vault.")
    sig = hello.sign(_hello_name(head), _u(w["ask"]))                # (its own window: outside the lock)
    with _LOCK:
        key = _unseal(hashlib.sha256(sig).digest(), w["key"], _about(head, "hello"))
        if key is None:
            raise VaultError("Windows Hello gave a different answer than before. Use the master password, then turn Windows Hello on again.")
        return _opened(head, key, _load(head, key))


def _hello_name(head: dict) -> str:
    return "PersonalAssistantVault-" + re.sub(r"[^0-9a-f]", "", str(head["id"]))[:16]


def lock(why: str = "") -> bool:
    global _OPEN
    with _LOCK:
        was, _OPEN = _OPEN is not None, None
    if was:
        from . import audit
        audit.record("vault_locked", why=why)
        _tell()
    return was


def is_open() -> bool:
    return _OPEN is not None


def need(session: Any) -> dict:
    """The open vault, for whoever opened it."""
    with _LOCK:
        if _OPEN is None or not hmac.compare_digest(str(session or "").encode(), _OPEN["session"].encode()):
            raise VaultError("The vault is locked.")
        _OPEN["used"] = time.monotonic()
        return _OPEN


def idle_minutes() -> int:
    from . import schedule
    n = schedule.get_setting("vault_idle")
    return n if n in IDLE and not isinstance(n, bool) else 5


def check_idle() -> bool:
    """Called every few seconds: locks after the time you chose."""
    with _LOCK:
        if _OPEN is None or time.monotonic() - _OPEN["used"] < idle_minutes() * 60:
            return False
    return lock("not used for a while")


def status() -> dict:
    from . import hello
    try:
        head = _read() if exists() else None
    except VaultError as e:
        return {"exists": True, "open": False, "damaged": str(e), "hello": False, "hello_ready": False, "wait": _wait(), "idle": idle_minutes(), "remind": remind()}
    return {"exists": bool(head), "open": is_open(), "hello": bool(head and isinstance(head["wrapped"].get("hello"), dict)), "hello_ready": hello.ready(), "wait": _wait(), "idle": idle_minutes(), "remind": remind(), "damaged": ""}


def _save(o: dict) -> None:
    raw = json.dumps(o["data"], ensure_ascii=False).encode("utf-8")
    if len(raw) > 20 * 2**20:
        raise VaultError("The vault is full.")
    head = dict(o["head"], data=_seal(o["key"], raw, _about(o["head"], "data")))
    _write(head)
    o["head"] = head
    _due_days()


# ---------------- entries ----------------
def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(kind: str, d: dict) -> dict:
    if kind not in KINDS:
        raise VaultError("Choose what it is.")
    out: dict[str, Any] = {}
    for f in FIELDS[kind]:
        if f not in d:
            continue
        v = "" if d[f] is None else str(d[f])
        v = "".join(ch for ch in v if ch in "\n\t" or unicodedata.category(ch) != "Cc")
        if f != "notes":
            v = v.replace("\n", " ").replace("\t", " ")
        if f not in ("password", "notes"):
            v = v.strip()
        if len(v) > (MAX_TEXT if f == "notes" else MAX_FIELD):
            raise VaultError(f"The {f} is too long.")
        out[f] = v
    if "title" in out and not out["title"]:
        raise VaultError("Give it a name.")
    if out.get("url"):
        u = out["url"] if re.match(r"^[a-z][a-z0-9+.-]*:", out["url"], re.I) and not re.match(r"^[\w.-]+:\d+(/|$)", out["url"]) else "https://" + out["url"]
        if not re.match(r"^https?://[^\s/]+", u, re.I):
            raise VaultError("The address should be a website (https://…).")
        out["url"] = u
    if out.get("totp"):
        out["totp"] = _totp_secret(out["totp"])
    if kind == "card" and out.get("number"):
        out["number"] = re.sub(r"[ -]", "", out["number"])
        if not re.fullmatch(r"\d{8,19}", out["number"]):
            raise VaultError("The card number has 8 to 19 digits.")
    if kind == "paper":
        for f in ("issued", "expires"):
            if out.get(f):
                try:
                    out[f] = date.fromisoformat(out[f]).isoformat()
                except ValueError:
                    raise VaultError("The dates are days (YYYY-MM-DD).") from None
        if out.get("paper") and out["paper"] not in PAPERS:
            out["paper"] = "Other"
    return out


def save(session: Any, kind: Any, fields: Any, entry_id: Any = None, favourite: Any = None, tags: Any = None) -> dict:
    with _LOCK:
        o = need(session)
        entries = o["data"]["entries"]
        old = entries.get(str(entry_id)) if entry_id else None
        if entry_id and old is None:
            raise VaultError("That entry is gone.")
        kind = old["kind"] if old else str(kind)
        if not isinstance(fields, dict):
            raise VaultError("Something is missing.")
        new = _clean(kind, fields)
        if old is None:
            if len(entries) >= MAX_ENTRIES:
                raise VaultError(f"That's {MAX_ENTRIES} entries. Remove some first.")
            if not new.get("title"):
                raise VaultError("Give it a name.")
            entry_id = secrets.token_hex(6)
            e = {"kind": kind, "made": _now(), "fav": False, "tags": [], "files": [], "was": []}
        else:
            e = json.loads(json.dumps(old))
            for f in ("password", "totp", "pin", "number", "cvv"):
                if f in new and new[f] != old.get(f, "") and old.get(f) and f == "password":
                    e["was"] = ([{"password": old[f], "until": _now()}] + e.get("was", []))[:5]
        if "password" in new and new["password"] != (old or {}).get("password", ""):
            e["set"] = _now()
        e.update(new)
        e["changed"] = _now()
        if favourite is not None:
            e["fav"] = favourite is True
        if tags is not None:
            e["tags"] = sorted({" ".join(str(t).split())[:30] for t in (tags if isinstance(tags, list) else str(tags).split(",")) if str(t).strip()})[:10]
        before = entries.get(str(entry_id))
        entries[str(entry_id)] = e
        try:
            _save(o)
        except Exception:
            entries.pop(str(entry_id), None) if before is None else entries.__setitem__(str(entry_id), before)
            raise
        return {"id": str(entry_id), **_card(str(entry_id), e)}


def _card(i: str, e: dict) -> dict:
    """What a list shows: no secrets."""
    sub = {"login": e.get("username") or "", "card": ("•••• " + e["number"][-4:] if e.get("number") else e.get("holder") or ""), "paper": " · ".join(x for x in (e.get("paper"), e.get("name")) if x), "note": ""}[e["kind"]]
    return {"id": i, "kind": e["kind"], "title": e["title"], "sub": sub, "url": e.get("url") or "", "fav": bool(e.get("fav")), "tags": e.get("tags") or [], "files": len(e.get("files") or []),
            "expires": e.get("expires") or "", "totp": bool(e.get("totp")), "changed": e.get("changed") or ""}


def listing(session: Any, query: Any = "", kind: Any = "", fav: Any = False) -> list[dict]:
    with _LOCK:
        o = need(session)
        words = str(query or "").casefold().split()
        out = []
        for i, e in o["data"]["entries"].items():
            hay = " ".join(str(e.get(f) or "") for f in ("title", "username", "url", "holder", "name", "paper", "notes") if not (f == "notes" and e["kind"] == "note")) + " " + " ".join(e.get("tags") or [])
            if (not kind or e["kind"] == kind) and (fav is not True or e.get("fav")) and all(w in hay.casefold() for w in words):
                out.append(_card(i, e))
        return sorted(out, key=lambda x: (not x["fav"], x["title"].casefold()))


def _entry(o: dict, entry_id: Any) -> dict:
    e = o["data"]["entries"].get(str(entry_id))
    if e is None:
        raise VaultError("That entry is gone.")
    return e


def get(session: Any, entry_id: Any) -> dict:
    """One entry, without its secrets (only whether they are there)."""
    with _LOCK:
        e = _entry(need(session), entry_id)
        out = {"id": str(entry_id), "kind": e["kind"], "fav": bool(e.get("fav")), "tags": e.get("tags") or [], "made": e.get("made"), "changed": e.get("changed"), "set": e.get("set"),
               "files": [{"id": f["id"], "name": f["name"], "size": f["size"]} for f in e.get("files") or []], "was": [{"until": w["until"]} for w in e.get("was") or []], "has": {}}
        for f in FIELDS[e["kind"]]:
            if f in SECRET:
                out["has"][f] = bool(e.get(f))
            else:
                out[f] = e.get(f) or ""
        if e["kind"] == "login" and e.get("password"):
            out["strength"] = strength(e["password"])
        return out


def _secret(session: Any, entry_id: Any, field: Any) -> str:
    e = _entry(need(session), entry_id)
    if field == "code":
        if not e.get("totp"):
            raise VaultError("There is no code for this.")
        return totp(e["totp"])[0]
    m = re.fullmatch(r"was(\d)", str(field))
    if m:
        was = e.get("was") or []
        if int(m[1]) >= len(was):
            raise VaultError("There is nothing there.")
        return was[int(m[1])]["password"]
    if field not in FIELDS[e["kind"]] or field == "totp" and not e.get("totp"):
        raise VaultError("There is nothing there.")
    return str(e.get(field) or "")


def reveal(session: Any, entry_id: Any, field: Any) -> dict:
    with _LOCK:
        v = _secret(session, entry_id, field)
        out = {"value": v}
        if field == "code":
            out["left"] = 30 - int(time.time()) % 30
        return out


def delete(session: Any, entry_id: Any) -> None:
    """Into the vault's own bin, for 30 days."""
    with _LOCK:
        o = need(session)
        e = _entry(o, entry_id)
        o["data"]["trash"][str(entry_id)] = {**e, "gone": _now()}
        del o["data"]["entries"][str(entry_id)]
        _save(o)


def trash(session: Any) -> list[dict]:
    with _LOCK:
        return [{**_card(i, e), "gone": e["gone"]} for i, e in need(session)["data"]["trash"].items()]


def restore(session: Any, entry_id: Any) -> None:
    with _LOCK:
        o = need(session)
        e = o["data"]["trash"].pop(str(entry_id), None)
        if e is None:
            raise VaultError("That isn't in the bin.")
        e.pop("gone", None)
        o["data"]["entries"][str(entry_id)] = e
        _save(o)


def empty_trash(session: Any) -> int:
    with _LOCK:
        o = need(session)
        gone = o["data"]["trash"]
        o["data"]["trash"] = {}
        _save(o)
        for e in gone.values():
            _wipe_files(e)
        return len(gone)


def _drop_old_trash() -> None:
    o = _OPEN
    limit = (datetime.now() - timedelta(days=TRASH_DAYS)).isoformat()
    old = [i for i, e in o["data"]["trash"].items() if str(e.get("gone") or "") < limit]
    if old:
        dropped = [o["data"]["trash"].pop(i) for i in old]
        try:
            _save(o)
        except OSError:
            return
        for e in dropped:
            _wipe_files(e)


# ---------------- codes (2-step sign-in, RFC 6238) ----------------
def _totp_secret(value: str) -> str:
    v = value.strip()
    if v.lower().startswith("otpauth://"):
        from urllib.parse import parse_qs, urlsplit
        v = (parse_qs(urlsplit(v).query).get("secret") or [""])[0]
    v = re.sub(r"[\s=-]", "", v).upper()
    try:
        if len(base64.b32decode(v + "=" * (-len(v) % 8))) < 5:
            raise ValueError
    except ValueError:
        raise VaultError("The 2-step secret is letters A to Z and digits 2 to 7 (what the website shows as the setup key).") from None
    return v


def totp(secret: str, at: float | None = None) -> tuple[str, int]:
    """(six digits, seconds they are still good)."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    t = int(at if at is not None else time.time())
    h = hmac.new(key, struct.pack(">Q", t // 30), hashlib.sha1).digest()
    o = h[-1] & 15
    return f"{(struct.unpack('>I', h[o:o + 4])[0] & 0x7fffffff) % 1_000_000:06d}", 30 - t % 30


# ---------------- making passwords, and how good they are ----------------
def generate(length: Any = 20, upper: Any = True, digits: Any = True, signs: Any = True, clear: Any = True) -> str:
    try:
        n = int(length)
    except (TypeError, ValueError):
        n = 20
    n = max(8, min(64, n))
    sets = [string.ascii_lowercase] + ([string.ascii_uppercase] if upper is not False else []) + ([string.digits] if digits is not False else []) + (["!@#$%&*+-=?_."] if signs is not False else [])
    if clear is not False:
        sets = ["".join(c for c in s if c not in "Il1O0o") for s in sets]
    chars = [secrets.choice(s) for s in sets] + [secrets.choice("".join(sets)) for _ in range(n - len(sets))]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def health(session: Any) -> dict:
    """Weak, used twice, or old passwords: all looked at here, nothing is sent."""
    with _LOCK:
        logins = [(i, e) for i, e in need(session)["data"]["entries"].items() if e["kind"] == "login" and e.get("password")]
    by: dict[str, list[str]] = {}
    for i, e in logins:
        by.setdefault(e["password"], []).append(i)
    year = (datetime.now() - timedelta(days=365)).isoformat()
    weak = [i for i, e in logins if strength(e["password"]) < 2]
    again = [i for ids in by.values() if len(ids) > 1 for i in ids]
    old = [i for i, e in logins if str(e.get("set") or e.get("made") or "") < year]
    cards = {i: _card(i, e) for i, e in logins}
    bad = set(weak) | set(again)
    return {"logins": len(logins), "weak": [cards[i] for i in weak], "again": [cards[i] for i in again], "old": [cards[i] for i in old],
            "score": round(100 * (1 - len(bad) / len(logins))) if logins else None}


# ---------------- the clipboard ----------------
def copy(session: Any, entry_id: Any, field: Any) -> int:
    """Onto the clipboard, kept out of Windows' clipboard history and cloud, and gone again after 30 seconds."""
    with _LOCK:
        v = _secret(session, entry_id, field)
    if not v:
        raise VaultError("There is nothing there.")
    _put(v)
    return COPY_FOR


def _put(text: str) -> None:
    import win32clipboard as wc
    for attempt in range(10):
        try:
            wc.OpenClipboard()
            break
        except Exception:
            if attempt == 9:
                raise VaultError("The clipboard is in use by another program. Try again.") from None
            time.sleep(0.05)
    try:
        wc.EmptyClipboard()
        wc.SetClipboardData(wc.CF_UNICODETEXT, text)
        for name in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"):
            wc.SetClipboardData(wc.RegisterClipboardFormat(name), b"\0\0\0\0")
    finally:
        wc.CloseClipboard()
    _CLIP["seq"] = _sequence()
    if _CLIP["timer"]:
        _CLIP["timer"].cancel()
    _CLIP["timer"] = threading.Timer(COPY_FOR, clear_clipboard)
    _CLIP["timer"].daemon = True
    _CLIP["timer"].start()


def _sequence() -> int:
    import ctypes
    return int(ctypes.windll.user32.GetClipboardSequenceNumber())


def on_clipboard() -> bool:
    """Is something from the vault on the clipboard now?"""
    return _CLIP["seq"] is not None and _CLIP["seq"] == _sequence()


def clear_clipboard() -> bool:
    """Only if it is still what was put there."""
    if not on_clipboard():
        _CLIP["seq"] = None
        return False
    import win32clipboard as wc
    try:
        wc.OpenClipboard()
        try:
            wc.EmptyClipboard()
        finally:
            wc.CloseClipboard()
    except Exception:
        return False
    _CLIP["seq"] = None
    return True


# ---------------- files ----------------
def _path(file_id: Any) -> Path:
    if not re.fullmatch(r"[0-9a-f]{24}", str(file_id or "")):
        raise VaultError("That file is gone.")
    return folder() / "files" / f"{file_id}.bin"


def _name(name: Any) -> str:
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or "")).strip(" .")[-120:]
    if not n:
        raise VaultError("The file needs a name.")
    return n


def file_add(session: Any, entry_id: Any, name: Any, data: bytes) -> dict:
    with _LOCK:
        o = need(session)
        e, n = _entry(o, entry_id), _name(name)
        if not data:
            raise VaultError("That file is empty.")
        if len(data) > MAX_FILE:
            raise VaultError("A file can be up to 20 MB.")
        files = e.setdefault("files", [])
        if len(files) >= MAX_FILES:
            raise VaultError(f"An entry can have up to {MAX_FILES} files.")
        if sum(f["size"] for x in (*o["data"]["entries"].values(), *o["data"]["trash"].values()) for f in x.get("files") or []) + len(data) > MAX_ALL:
            raise VaultError("The vault's files together can be up to 500 MB.")
        fid, key = secrets.token_hex(12), secrets.token_bytes(32)             # each file its own key
        p = _path(fid)
        p.parent.mkdir(parents=True, exist_ok=True)
        total = (len(data) + CHUNK - 1) // CHUNK
        with open(p, "xb") as h:
            for i in range(total):
                h.write(_gcm(key).encrypt(struct.pack(">QI", 0, i), data[i * CHUNK:(i + 1) * CHUNK], f"{fid}|{i}|{total}".encode()))
        files.append({"id": fid, "name": n, "size": len(data), "key": _b(key), "n": total, "added": _now()})
        try:
            _save(o)
        except Exception:
            files.pop()
            p.unlink(missing_ok=True)
            raise
        return {"id": fid, "name": n, "size": len(data)}


def _find_file(o: dict, file_id: Any) -> tuple[dict, dict]:
    for e in o["data"]["entries"].values():
        for f in e.get("files") or []:
            if f["id"] == file_id:
                return e, f
    raise VaultError("That file is gone.")


def file_get(session: Any, file_id: Any) -> tuple[str, bytes]:
    with _LOCK:
        _, f = _find_file(need(session), file_id)
        f = dict(f)
    from cryptography.exceptions import InvalidTag
    out, key = [], _u(f["key"])
    try:
        with open(_path(f["id"]), "rb") as h:
            for i in range(f["n"]):
                out.append(_gcm(key).decrypt(struct.pack(">QI", 0, i), h.read(CHUNK + 16), f"{f['id']}|{i}|{f['n']}".encode()))
            if h.read(1):
                raise InvalidTag
    except FileNotFoundError:
        raise VaultError("That file isn't there any more.") from None
    except InvalidTag:
        raise VaultError("That file was changed or is damaged.") from None
    return f["name"], b"".join(out)


def file_delete(session: Any, file_id: Any) -> None:
    with _LOCK:
        o = need(session)
        e, f = _find_file(o, file_id)
        e["files"].remove(f)
        _save(o)
        _path(f["id"]).unlink(missing_ok=True)


def file_save(session: Any, file_id: Any, to: Path | None = None) -> Path:
    """A copy outside the vault (not encrypted any more), never over a file."""
    name, data = file_get(session, file_id)
    to = to or Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    to.mkdir(parents=True, exist_ok=True)
    stem, ext = os.path.splitext(name)
    for n in range(1, 100):
        p = to / f"{stem}{f' ({n})' if n > 1 else ''}{ext}"
        try:
            with open(p, "xb") as h:
                h.write(data)
            return p
        except FileExistsError:
            continue
    raise VaultError("There are too many files with this name in Documents.")


def _wipe_files(e: dict) -> None:
    for f in e.get("files") or []:
        try:
            _path(f["id"]).unlink(missing_ok=True)
        except (OSError, VaultError):
            pass


# ---------------- bringing in and taking out ----------------
_COLS = {"title": ("name", "title", "account"), "url": ("url", "login_uri", "website", "web site", "hostname", "uri"), "username": ("username", "login_username", "user", "login", "email", "login name"),
         "password": ("password", "login_password"), "notes": ("note", "notes", "comment", "comments", "extra"), "totp": ("totp", "login_totp", "otpauth", "otp")}


def import_csv(session: Any, text: Any) -> dict:
    """Passwords exported from Chrome, Edge, Firefox, Bitwarden, LastPass, KeePass… Those you have already are left alone."""
    raw = str(text or "").lstrip("﻿")
    if len(raw) > 4 * 2**20:
        raise VaultError("That file is too big (4 MB at most).")
    rows = list(csv.reader(io.StringIO(raw)))
    if len(rows) < 2:
        raise VaultError("There is nothing in that file.")
    head = [h.strip().lower() for h in rows[0]]
    at = {f: next((head.index(n) for n in names if n in head), None) for f, names in _COLS.items()}
    if at["password"] is None:
        raise VaultError("That isn't a list of passwords: there is no password column.")
    with _LOCK:
        o = need(session)
        entries = o["data"]["entries"]
        have = {(e.get("url") or "", e.get("username") or "", e.get("password") or "") for e in entries.values() if e["kind"] == "login"}
        new, same, bad = {}, 0, 0
        for row in rows[1:MAX_ENTRIES + 1]:
            g = {f: (row[i] if i is not None and i < len(row) else "") for f, i in at.items()}
            if not any(g.values()):
                continue
            if not (g["password"] or g["notes"] or g["totp"] or g["username"]):
                bad += 1
                continue
            host = re.sub(r"^https?://(www\.)?", "", g["url"]).split("/")[0]
            g["title"] = (g["title"] or host or g["username"] or "Without a name")[:MAX_FIELD]
            if not re.match(r"^https?://", g["url"], re.I):
                g["url"] = g["url"] if re.fullmatch(r"[\w.-]+\.\w{2,}(/\S*)?", g["url"]) else ""
            try:
                try:
                    c = _clean("login", g)
                except VaultError:
                    c = _clean("login", {**g, "totp": "", "url": ""})
            except VaultError:
                bad += 1
                continue
            k = (c["url"], c["username"], c["password"])
            if k in have:
                same += 1
                continue
            have.add(k)
            new[secrets.token_hex(6)] = {"kind": "login", "made": _now(), "changed": _now(), "fav": False, "tags": [], "files": [], "was": [], **c}
        if len(entries) + len(new) > MAX_ENTRIES:
            raise VaultError(f"The vault can hold {MAX_ENTRIES} entries.")
        entries.update(new)
        try:
            _save(o)
        except Exception:
            for i in new:
                entries.pop(i, None)
            raise
        return {"added": len(new), "same": same, "bad": bad}


def _check(password: Any) -> None:
    """The master password once more, for what can't be taken back."""
    _may_try()
    head = _read()
    if _unseal(_stretch(_password(password), _u(head["salt"])), head["wrapped"].get("password"), _about(head, "password")) is None:
        raise _wrong("master password")
    _TRIES.update(n=0, until=0.0)
    _done_trying()


def export_csv(session: Any, password: Any, to: Path | None = None) -> Path:
    """Passwords as a plain CSV in Documents: readable by anyone who has the file."""
    with _LOCK:
        o = need(session)
        _check(password)
        rows = [(e["title"], e.get("url") or "", e.get("username") or "", e.get("password") or "", e.get("notes") or "") for e in o["data"]["entries"].values() if e["kind"] == "login"]
    to = to or Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
    to.mkdir(parents=True, exist_ok=True)
    for n in range(1, 100):
        p = to / f"Vault passwords NOT ENCRYPTED {date.today().isoformat()}{f' ({n})' if n > 1 else ''}.csv"
        try:
            with open(p, "x", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["name", "url", "username", "password", "note"])
                w.writerows(rows)
            return p
        except FileExistsError:
            continue
    raise VaultError("There are too many exports of today in Documents.")


# ---------------- settings of the vault ----------------
def change_password(session: Any, old: Any, new: Any, again: Any) -> None:
    with _LOCK:
        o = need(session)
        _check(old)
        if _password(new) != _password(again):
            raise VaultError("The two passwords aren't the same.")
        pw = _check_password(new)
        head = json.loads(json.dumps(o["head"]))
        head["wrapped"]["password"] = _seal(_stretch(pw, _u(head["salt"])), o["key"], _about(head, "password"))
        _write(head)
        o["head"] = head


def new_recovery(session: Any, password: Any) -> str:
    with _LOCK:
        o = need(session)
        _check(password)
        code, head = _new_code(), json.loads(json.dumps(o["head"]))
        head["wrapped"]["recovery"] = _seal(_stretch(_code(code), _u(head["salt"])), o["key"], _about(head, "recovery"))
        _write(head)
        o["head"] = head
        return code


def hello_on(session: Any, password: Any) -> None:
    """Windows Hello too: a key only this PC's security chip can use, and only after your finger, face or PIN."""
    from . import hello
    with _LOCK:
        head = need(session)["head"]
        _check(password)
    ask = secrets.token_bytes(32)
    hello.make_key(_hello_name(head))
    sig = hello.sign(_hello_name(head), ask)
    with _LOCK:
        o = need(session)
        head = json.loads(json.dumps(o["head"]))
        head["wrapped"]["hello"] = {"ask": _b(ask), "key": _seal(hashlib.sha256(sig).digest(), o["key"], _about(head, "hello"))}
        _write(head)
        o["head"] = head


def hello_off(session: Any) -> None:
    from . import hello
    with _LOCK:
        o = need(session)
        head = json.loads(json.dumps(o["head"]))
        if head["wrapped"].pop("hello", None) is not None:
            _write(head)
            o["head"] = head
    hello.drop_key(_hello_name(head))


def settings(d: dict) -> None:
    from . import schedule
    if "idle" in d:
        if isinstance(d["idle"], bool) or d["idle"] not in IDLE:
            raise VaultError("Choose one of the times in the list.")
        schedule.set_setting("vault_idle", d["idle"])
    if "remind" in d:
        schedule.set_setting("vault_remind", d["remind"] is True)
        if is_open():
            _due_days()
        elif d["remind"] is not True:
            schedule.set_setting("vault_due", None)


def remove(word: Any) -> None:
    """The whole vault to the Recycle Bin (still encrypted), after typing DELETE."""
    if str(word or "").strip() != "DELETE":
        raise VaultError("Type DELETE in capitals to remove the vault.")
    if not folder().is_dir():
        raise VaultError("There is no vault yet.")
    lock("removed")
    from . import schedule
    from .tools import _ps, _ps_quote
    _ps("Add-Type -AssemblyName Microsoft.VisualBasic; [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory('" + _ps_quote(folder()) + "', 'OnlyErrorDialogs', 'SendToRecycleBin')", timeout=120)
    if folder().is_dir():
        raise VaultError("Windows couldn't move it to the Recycle Bin.")
    for k in ("vault_due", "vault_tries", "vault_said"):
        schedule.set_setting(k, None)
    _TRIES.update(n=0, until=0.0)


# ---------------- papers that run out ----------------
def remind() -> bool:
    from . import schedule
    return schedule.get_setting("vault_remind", True) is not False


def _due_days() -> None:
    """The days something runs out, without saying what: the only thing known outside, for the reminder."""
    from . import schedule
    o = _OPEN
    days = sorted({e["expires"] for e in o["data"]["entries"].values() if e["kind"] == "paper" and re.fullmatch(r"\d{4}-\d\d-\d\d", str(e.get("expires") or ""))})[:200] if o and remind() else []
    try:
        schedule.set_setting("vault_due", days or None)
    except OSError:
        pass


def tick(now: datetime, notify: Callable[[str, str], None]) -> int:
    """30 days and 7 days before, and on the day (from 9 o'clock), each once."""
    from . import schedule
    days = schedule.get_setting("vault_due")
    if not isinstance(days, list) or not remind() or now.hour < 9:
        return 0
    said = schedule.get_setting("vault_said")
    said, n = (said if isinstance(said, list) else []), 0
    for d in days:
        try:
            left = (date.fromisoformat(str(d)) - now.date()).days
        except ValueError:
            continue
        mark = next((m for m in (0, 7, 30) if 0 <= left <= m), None)
        if mark is None or f"{d}:{mark}" in said:
            continue
        said = [*said, f"{d}:{mark}"][-300:]
        notify("Something in your vault runs out " + ("today" if left == 0 else "tomorrow" if left == 1 else f"in {left} days") + ". Open the vault to see what.", "reminder")
        n += 1
    if n:
        schedule.set_setting("vault_said", said)
    return n

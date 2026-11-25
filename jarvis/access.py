"""Who may come in from outside this window: paired phones and PCs, API keys, and what goes out to your own connections.

Everything lies in access.dat, locked for this Windows account (DPAPI) and never part of a backup: putting an old backup
back must not let a device in again that you removed. Of a device's or program's secret only its SHA-256 is kept (the
secrets are 256 random bits).

Pairing: a code of eight letters, shown only in the app, good once and for three minutes; five wrong tries end it. Then
the app asks you with the device's name; only your click lets it in. Two PCs prove to each other that both know the code
and that they speak with each other's own key (so nobody can stand in between).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ENTROPY = b"Personal Assistant access v1"
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"            # (nothing that looks like something else)
CODE_FOR, ASK_FOR, TRIES = 180, 180, 5
IDLE_DAYS = 90                                           # a device that wasn't seen for so long has to be paired again
N = 2 ** 15                                              # scrypt for the code between two PCs: 32 MB a try
MAX_DEVICES, MAX_KEYS, MAX_CONNECTIONS = 20, 20, 30
PHONE_RIGHTS = {"chat": "Chat: write to the assistant and see the conversation", "lists": "Tasks and agenda: see them, add, tick off", "approve": "Answer its questions (Allow / Deny)"}
PC_RIGHTS = {"ask": "Ask this PC's assistant to do something", "files": "Send files to this PC", "sync": "Sync memories, notes, tasks and calendar"}
SCOPES = {"status": "See what the assistant is doing", "ask": "Ask the assistant (risky steps still ask you)", "notify": "Show a notice", "tasks": "Tasks: list, add, tick off", "agenda": "See the agenda",
          "notes": "Notes: list, read, write new ones", "memories": "Read what it remembers about you"}
_LOCK = threading.RLock()
_S: dict[str, Any] = {"data": None, "file": None, "saved": 0.0, "dirty": False}
_PAIR: dict[str, Any] = {}
_ASKS: dict[str, dict] = {}
_FAILS: dict[str, list[float]] = {}


class AccessError(ValueError):
    """Something to tell the owner or the device, in plain words."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def hash_of(secret: Any) -> str:
    return hashlib.sha256(str(secret or "").encode("utf-8", "surrogatepass")).hexdigest()


# ---------------- the store ----------------
def _file() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "access.dat"


def _protect(data: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptProtectData(data, "Personal Assistant access", _ENTROPY, None, None, 0)


def _unprotect(blob: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptUnprotectData(blob, _ENTROPY, None, None, 0)[1]


def _empty() -> dict:
    return {"v": 1, "devices": {}, "peers": {}, "keys": {}, "connections": {}, "server": {}}


def _data() -> dict:
    with _LOCK:
        f = _file()
        if _S["data"] is None or _S["file"] != f:
            d = _empty()
            if f.is_file():
                try:
                    got = json.loads(_unprotect(f.read_bytes()))
                    d.update({k: v for k, v in got.items() if isinstance(v, type(d.get(k)))})
                except Exception as e:                  # another Windows account, or damaged: nobody comes in; the file is kept
                    print(f"[access] access.dat can't be read ({type(e).__name__}): put aside")
                    try:
                        os.replace(f, f.with_name("access.dat.broken"))
                    except OSError:
                        pass
            _S.update(data=d, file=f, dirty=False)
        return _S["data"]


def _save() -> None:
    with _LOCK:
        f = _file()
        tmp = f.with_name("access.dat.tmp")
        tmp.write_bytes(_protect(json.dumps(_data()).encode("utf-8")))
        os.replace(tmp, f)
        _S.update(saved=time.monotonic(), dirty=False)


def flush(now: bool = False) -> None:
    """(when a device was last seen changes all the time: written at most once a minute)"""
    with _LOCK:
        if _S["dirty"] and (now or time.monotonic() - _S["saved"] > 60):
            _save()


def name_of(text: Any, fallback: str = "Device") -> str:
    t = re.sub(r"[\x00-\x1f\x7f<>‎‏‪-‮⁦-⁩]", " ", str(text or ""))
    return re.sub(r"\s+", " ", t).strip()[:40] or fallback


# ---------------- wrong tries ----------------
def failed(ip: str) -> None:
    with _LOCK:
        if len(_FAILS) > 500:
            _FAILS.clear()
        _FAILS.setdefault(ip, []).append(time.monotonic())


def held(ip: str) -> bool:
    """Too many wrong tries from there: ten minutes of nothing."""
    with _LOCK:
        t = [x for x in _FAILS.get(ip, []) if time.monotonic() - x < 600]
        if t:
            _FAILS[ip] = t
        else:
            _FAILS.pop(ip, None)
        return len(t) >= 20


# ---------------- pairing ----------------
def start_pairing(kind: Any) -> dict:
    """Your button: a new code (the one before ends)."""
    if kind not in ("phone", "pc"):
        raise AccessError("Choose a phone or a PC.")
    with _LOCK:
        if len(_data()["devices"]) >= MAX_DEVICES:
            raise AccessError("That is enough devices. Remove one first.")
        _PAIR.clear()
        _PAIR.update(kind=kind, code="".join(secrets.choice(ALPHABET) for _ in range(8)), until=time.monotonic() + CODE_FOR, tries=0, salt=secrets.token_bytes(16), nonce=secrets.token_bytes(16))
        _ASKS.clear()
    return pairing()


def stop_pairing() -> None:
    with _LOCK:
        _PAIR.clear()
        _ASKS.clear()


def pairing() -> dict | None:
    """For the app's own page: the code and who is asking."""
    with _LOCK:
        for k in [k for k, a in _ASKS.items() if time.monotonic() > a["until"]]:
            del _ASKS[k]
        if _PAIR and time.monotonic() > _PAIR["until"]:
            _PAIR.clear()
        asks = [{"id": a["id"], "name": a["name"], "kind": a["kind"], "ip": a["ip"]} for a in _ASKS.values() if a["state"] == "waiting"]
        if not _PAIR and not asks:
            return None
        out: dict[str, Any] = {"asks": asks, "kind": _PAIR.get("kind") or asks[0]["kind"], "code": "", "left": 0}
        if _PAIR:
            out.update(code=f"{_PAIR['code'][:4]}-{_PAIR['code'][4:]}", left=max(0, int(_PAIR["until"] - time.monotonic())))
        return out


def clean_code(code: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(code or "").upper())[:16]


def _open(kind: str) -> dict:
    if not _PAIR or time.monotonic() > _PAIR["until"] or _PAIR["kind"] != kind:
        raise AccessError("No code is open on the PC. Make one there: Settings, Devices.")
    return _PAIR


def _wrong(ip: str) -> None:
    failed(ip)
    _PAIR["tries"] += 1
    if _PAIR["tries"] >= TRIES:
        _PAIR.clear()
        raise AccessError("Too many wrong tries: that code ended. Make a new one on the PC.")
    raise AccessError("That isn't the code.")


def _ask(kind: str, name: Any, ip: str, more: dict | None = None) -> str:
    secret = secrets.token_urlsafe(24)
    _ASKS[hash_of(secret)] = {"id": secrets.token_hex(6), "name": name_of(name, "Phone" if kind == "phone" else "PC"), "kind": kind, "ip": ip, "until": time.monotonic() + ASK_FOR, "state": "waiting", "more": more or {}}
    _PAIR.clear()                                        # good once
    return secret


def phone_code(code: Any, name: Any, ip: str) -> str:
    """The phone's page sent the code. Returns the secret it asks again with until you clicked."""
    with _LOCK:
        p = _open("phone")
        if not hmac.compare_digest(clean_code(code).encode(), p["code"].encode()):
            _wrong(ip)
        return _ask("phone", name, ip)


def stretch(code: Any, salt: bytes) -> bytes:
    return hashlib.scrypt(clean_code(code).encode(), salt=salt, n=N, r=8, p=1, maxmem=64 * 2**20, dklen=32)


def proof(key: bytes, who: str, pin: str, nonce_c: bytes, nonce_s: bytes, hello: str) -> str:
    """What only somebody who knows the code can make, for exactly this connection."""
    return hmac.new(key, json.dumps(["pa-pair 1", who, pin, nonce_c.hex(), nonce_s.hex(), hello]).encode(), hashlib.sha256).hexdigest()


def pc_begin() -> dict:
    with _LOCK:
        p = _open("pc")
        return {"salt": p["salt"].hex(), "nonce": p["nonce"].hex()}


def pc_code(pin: str, nonce_c: Any, shown: Any, hello: Any, ip: str) -> dict:
    """The other PC's proof. Answers with ours, so that it knows that it isn't speaking with somebody in between."""
    with _LOCK:
        p = _open("pc")
        try:
            nc = bytes.fromhex(str(nonce_c))
            h = json.loads(str(hello))
        except ValueError:
            nc, h = b"", None
        if len(nc) != 16 or not isinstance(h, dict) or len(str(hello)) > 4000:
            raise AccessError("That wasn't understood. Are both PCs on the same version?")
        key = stretch(p["code"], p["salt"])
        if not hmac.compare_digest(proof(key, "client", pin, nc, p["nonce"], str(hello)).encode(), str(shown or "").encode("utf-8", "replace")):
            _wrong(ip)
        ours = proof(key, "server", pin, nc, p["nonce"], str(hello))
        return {"ask": _ask("pc", h.get("name"), ip, {k: h.get(k) for k in ("pin", "urls", "token", "id")}), "proof": ours}


def ask_state(secret: Any) -> dict:
    """The device asks whether you clicked. The secret that lets it in is handed out once."""
    with _LOCK:
        a = _ASKS.get(hash_of(secret))
        if not a or time.monotonic() > a["until"]:
            return {"state": "ended"}
        if a["state"] != "allowed":
            if a["state"] == "denied":
                del _ASKS[hash_of(secret)]
            return {"state": a["state"]}
        del _ASKS[hash_of(secret)]
        return {"state": "allowed", "id": a["device"], "token": a["token"], "kind": a["kind"], "rights": a["rights"]}


def answer(ask_id: Any, allow: bool, rights: Any = None) -> dict | None:
    """Your click."""
    from . import audit
    with _LOCK:
        a = next((x for x in _ASKS.values() if x["id"] == ask_id and x["state"] == "waiting" and time.monotonic() < x["until"]), None)
        if not a:
            raise AccessError("It isn't asking any more.")
        if not allow:
            a["state"] = "denied"
            audit.record("device_denied", name=a["name"], kind=a["kind"])
            return None
        known = PHONE_RIGHTS if a["kind"] == "phone" else PC_RIGHTS
        want = [r for r in known if r in rights] if isinstance(rights, list) else [r for r in known if r != "approve"]
        did, token = secrets.token_hex(8), secrets.token_urlsafe(32)
        _data()["devices"][did] = {"name": a["name"], "kind": a["kind"], "hash": hash_of(token), "rights": want, "added": _now(), "seen": _now(), "ip": a["ip"]}
        a.update(state="allowed", device=did, token=token, rights=want)
        if a["kind"] == "pc":
            m = a["more"]
            if isinstance(m.get("token"), str) and re.fullmatch(r"[0-9a-f]{64}", str(m.get("pin"))) and isinstance(m.get("urls"), list):
                save_peer(did, a["name"], [str(u) for u in m["urls"]][:8], str(m["pin"]), str(m.get("id") or ""), str(m["token"]), other=str(m.get("id") or ""))
        _save()
        audit.record("device_added", name=a["name"], kind=a["kind"], rights=want)
        return device(did)


# ---------------- devices ----------------
def _shown(i: str, d: dict) -> dict:
    return {"id": i, "name": d["name"], "kind": d["kind"], "rights": list(d["rights"]), "added": d["added"], "seen": d["seen"], "ip": d.get("ip", ""), "old": _old(d)}


def _old(d: dict) -> bool:
    try:
        return datetime.now() - datetime.fromisoformat(d["seen"]) > timedelta(days=IDLE_DAYS)
    except ValueError:
        return True


def devices() -> list[dict]:
    with _LOCK:
        return sorted((_shown(i, d) for i, d in _data()["devices"].items()), key=lambda d: d["added"], reverse=True)


def device(i: Any) -> dict | None:
    with _LOCK:
        d = _data()["devices"].get(str(i))
        return _shown(str(i), d) if d else None


def check(i: Any, token: Any, ip: str, kind: str | None = None) -> dict | None:
    """Is it one of your devices? (its rights are looked up every time)"""
    with _LOCK:
        d = _data()["devices"].get(str(i))
        if not d or not hmac.compare_digest(d["hash"], hash_of(token)) or _old(d) or kind and d["kind"] != kind:
            return None
        d.update(seen=_now(), ip=ip)
        _S["dirty"] = True
    flush()
    return device(i)


def set_rights(i: Any, rights: Any) -> None:
    from . import audit
    with _LOCK:
        d = _data()["devices"].get(str(i))
        if not d or not isinstance(rights, list):
            raise AccessError("That device isn't there any more.")
        known = PHONE_RIGHTS if d["kind"] == "phone" else PC_RIGHTS
        d["rights"] = [r for r in known if r in rights]
        _save()
        audit.record("device_rights", name=d["name"], rights=d["rights"])


def rename(i: Any, name: Any) -> None:
    with _LOCK:
        d = _data()["devices"].get(str(i))
        if not d:
            raise AccessError("That device isn't there any more.")
        d["name"] = name_of(name, d["name"])
        _save()


def remove(i: Any) -> None:
    """It can't come in any more, at once."""
    from . import audit
    with _LOCK:
        d = _data()["devices"].pop(str(i), None)
        _data()["peers"].pop(str(i), None)
        if d:
            _save()
            audit.record("device_removed", name=d["name"], kind=d["kind"])


# ---------------- other PCs we can call ----------------
def save_peer(i: str, name: str, urls: list[str], pin: str, device_id: str, token: str, other: str = "") -> None:
    with _LOCK:
        _data()["peers"][i] = {"name": name_of(name, "PC"), "urls": [u for u in urls if re.fullmatch(r"[A-Za-z0-9.\-]{1,100}:\d{2,5}", u)], "pin": pin, "as": device_id, "token": token, "added": _now(), "other": other}


def peers() -> dict[str, dict]:
    with _LOCK:
        return {k: dict(v) for k, v in _data()["peers"].items()}


def set_peer(i: str, **k: Any) -> None:
    with _LOCK:
        if i in _data()["peers"]:
            _data()["peers"][i].update(k)
            _save()


def add_pair(i: str, name: str, token_hash: str, rights: list[str], urls: list[str], pin: str, device_id: str, token: str) -> None:
    """The PC that typed the code keeps both: how to call the other, and that the other may come in."""
    with _LOCK:
        _data()["devices"][i] = {"name": name_of(name, "PC"), "kind": "pc", "hash": token_hash, "rights": [r for r in PC_RIGHTS if r in rights], "added": _now(), "seen": _now(), "ip": ""}
        save_peer(i, name, urls, pin, device_id, token)
        _save()


# ---------------- the server's own key ----------------
def server_key() -> dict:
    with _LOCK:
        return dict(_data()["server"])


def set_server_key(d: dict) -> None:
    with _LOCK:
        _data()["server"] = d
        _save()


# ---------------- API keys ----------------
def make_key(name: Any, scopes: Any, days: Any = 0) -> dict:
    """A key for one of your own programs. Shown once."""
    from . import audit
    want = [s for s in SCOPES if isinstance(scopes, list) and s in scopes]
    if not want:
        raise AccessError("Choose what the program may do.")
    if isinstance(days, bool) or days not in (0, 30, 90, 365):
        raise AccessError("Choose how long it is good.")
    with _LOCK:
        if len(_data()["keys"]) >= MAX_KEYS:
            raise AccessError("That is enough keys. Remove one first.")
        i, secret = secrets.token_hex(6), secrets.token_urlsafe(32)
        _data()["keys"][i] = {"name": name_of(name, "Program"), "hash": hash_of(secret), "scopes": want, "added": _now(), "until": (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds") if days else "", "used": "", "n": 0}
        _save()
    audit.record("api_key_made", name=name_of(name, "Program"), scopes=want)
    return {"id": i, "key": f"pa_{i}_{secret}"}


def keys() -> list[dict]:
    with _LOCK:
        return [{"id": i, **{x: k[x] for x in ("name", "scopes", "added", "until", "used", "n")}, "ended": bool(k["until"]) and k["until"] < _now()} for i, k in sorted(_data()["keys"].items(), key=lambda x: x[1]["added"], reverse=True)]


def remove_key(i: Any) -> None:
    from . import audit
    with _LOCK:
        k = _data()["keys"].pop(str(i), None)
        if k:
            _save()
            audit.record("api_key_removed", name=k["name"])


def check_key(text: Any) -> dict | None:
    m = re.fullmatch(r"pa_([0-9a-f]{12})_([A-Za-z0-9_\-]{40,50})", str(text or ""))
    if not m:
        return None
    with _LOCK:
        k = _data()["keys"].get(m[1])
        if not k or not hmac.compare_digest(k["hash"], hash_of(m[2])) or k["until"] and k["until"] < _now():
            return None
        k["used"], k["n"] = _now(), int(k["n"]) + 1
        _S["dirty"] = True
        out = {"id": m[1], "name": k["name"], "scopes": list(k["scopes"])}
    flush()
    return out


# ---------------- connections (connections.py knows what they mean) ----------------
def connections() -> dict[str, dict]:
    with _LOCK:
        return {k: dict(v) for k, v in _data()["connections"].items()}


def save_connection(i: str, d: dict | None) -> None:
    with _LOCK:
        if d is None:
            _data()["connections"].pop(i, None)
        else:
            _data()["connections"][i] = d
        _save()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")

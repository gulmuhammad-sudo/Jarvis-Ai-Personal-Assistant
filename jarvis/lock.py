"""The privacy lock: covers the whole app. While it is locked the app itself refuses everything but unlocking, stopping and
silencing an alarm (not only a cover on the page), the microphone is closed and nothing is said or shown.

It opens with Windows Hello, with the app's own PIN, or with either: your choice. Never by voice. It keeps people at your
keyboard out of the app; it doesn't encrypt the app's files (that is what the vault is for).

Without Windows Hello's sensor working: press Windows+L and sign in to Windows again; that counts too.
"""
from __future__ import annotations

import ctypes
import hmac
import json
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable

IDLE = (0, 1, 5, 15, 30, 60)
WAYS = ("hello", "pin")
_ENTROPY = b"Personal Assistant lock v1"
CHANGED: Callable[[bool, str], None] | None = None
_LOCK = threading.RLock()
_STATE = {"locked": False, "why": "", "since": 0.0, "signed_in": 0.0}
_TRIES = {"n": 0, "until": 0.0}
_STARTED = False


class LockError(ValueError):
    """Something to tell the owner, in plain words."""


# ---------------- settings ----------------
def _file() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "lock.dat"


def settings() -> dict:
    from . import hello, schedule
    s = schedule.get_setting("lock")
    s = s if isinstance(s, dict) else {}
    ways = [w for w in WAYS if w in (s.get("ways") or []) and (w != "pin" or _file().is_file())]
    return {"ways": ways, "on": bool(ways), "idle": s.get("idle") if s.get("idle") in IDLE and not isinstance(s.get("idle"), bool) else 0, "windows": s.get("windows") is True, "start": s.get("start") is True,
            "has_pin": _file().is_file(), "hello_ready": hello.ready(), "locked": is_locked()}


def set_settings(d: dict) -> dict:
    from . import audit, schedule
    s = settings()
    new = {k: s[k] for k in ("ways", "idle", "windows", "start")}
    if "ways" in d:
        w = d["ways"]
        if not isinstance(w, list) or any(x not in WAYS for x in w):
            raise LockError("Choose Windows Hello, the app's PIN, or both.")
        if "pin" in w and not _file().is_file():
            raise LockError("Choose a PIN first.")
        if "hello" in w and "hello" not in s["ways"] and not s["hello_ready"]:
            raise LockError("Windows Hello isn't set up on this PC (Windows Settings › Accounts › Sign-in options).")
        new["ways"] = [x for x in WAYS if x in w]
    if "idle" in d:
        if d["idle"] not in IDLE or isinstance(d["idle"], bool):
            raise LockError("Choose one of the times in the list.")
        new["idle"] = d["idle"]
    for k in ("windows", "start"):
        if k in d:
            new[k] = d[k] is True
    schedule.set_setting("lock", new)
    audit.record("lock_settings", ways="+".join(new["ways"]) or "off", idle=new["idle"], windows=new["windows"], start=new["start"])
    return settings()


def _hash(pin: str, salt: bytes) -> bytes:
    import hashlib
    return hashlib.scrypt(pin.encode("utf-8"), salt=salt, n=2 ** 15, r=8, p=1, maxmem=64 * 2**20, dklen=32)


def set_pin(pin: Any, again: Any, old: Any = None) -> None:
    """Kept as a hash, and that locked with your Windows account."""
    import win32crypt
    from . import audit
    p = str(pin or "")
    if _file().is_file():
        _check_pin(old)
    if p != str(again or ""):
        raise LockError("The two PINs aren't the same.")
    if not 4 <= len(p) <= 32:
        raise LockError("The PIN has 4 to 32 digits or letters.")
    if len(set(p)) == 1 or p in "01234567890123456789" or p in "98765432109876543210":
        raise LockError("That PIN is too easy to guess.")
    salt = secrets.token_bytes(16)
    blob = win32crypt.CryptProtectData(json.dumps({"salt": salt.hex(), "pin": _hash(p, salt).hex()}).encode(), "Personal Assistant lock", _ENTROPY, None, None, 0)
    tmp = _file().with_name("lock.dat.tmp")
    tmp.write_bytes(blob)
    tmp.replace(_file())
    audit.record("lock_pin_set")


def remove_pin(old: Any) -> None:
    from . import schedule
    _check_pin(old)
    s = schedule.get_setting("lock") or {}
    schedule.set_setting("lock", {**s, "ways": [w for w in s.get("ways") or [] if w != "pin"]})
    _file().unlink(missing_ok=True)


def _wait() -> int:
    return max(0, int(_TRIES["until"] - time.time() + 0.99))


def _check_pin(pin: Any) -> None:
    import win32crypt
    from . import audit, schedule
    saved = schedule.get_setting("lock_tries")
    if isinstance(saved, list) and len(saved) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in saved) and saved[0] > _TRIES["n"]:
        _TRIES.update(n=saved[0], until=min(float(saved[1]), time.time() + 3600))      # (a restart doesn't start the count again)
    if w := _wait():
        raise LockError(f"Too many wrong tries. Wait {w} seconds.")
    try:
        d = json.loads(win32crypt.CryptUnprotectData(_file().read_bytes(), _ENTROPY, None, None, 0)[1])
        good = hmac.compare_digest(_hash(str(pin or ""), bytes.fromhex(d["salt"])), bytes.fromhex(d["pin"]))
    except Exception:
        raise LockError("The PIN can't be read on this PC.") from None
    if good:
        _TRIES.update(n=0, until=0.0)
        schedule.set_setting("lock_tries", None)
        return
    _TRIES["n"] += 1
    if _TRIES["n"] >= 5:
        _TRIES["until"] = time.time() + min(3600, 30 * 2 ** (_TRIES["n"] - 5))
    schedule.set_setting("lock_tries", [_TRIES["n"], int(_TRIES["until"])])
    audit.record("lock_wrong", tries=_TRIES["n"])
    w = _wait()
    raise LockError("That isn't the PIN." + (f" Wait {w} seconds before the next try." if w else ""))


# ---------------- locked or not ----------------
def is_locked() -> bool:
    return bool(_STATE["locked"])


def lock(why: str = "you locked it") -> bool:
    """Nothing happens when no way to open it again is set up."""
    if not settings()["on"]:
        return False
    with _LOCK:
        if _STATE["locked"]:
            return True
        _STATE.update(locked=True, why=why, since=time.time(), signed_in=0.0)
    _tell(True, why)
    return True


def _open(how: str) -> None:
    with _LOCK:
        if not _STATE["locked"]:
            return
        _STATE.update(locked=False, why="", since=0.0, signed_in=0.0)
    _tell(False, how)


def _tell(locked: bool, why: str) -> None:
    from . import audit
    audit.record("app_locked" if locked else "app_unlocked", how=why)
    if CHANGED:
        try:
            CHANGED(locked, why)
        except Exception as e:
            print(f"[lock] {type(e).__name__}: {e}")


def unlock_pin(pin: Any) -> None:
    if "pin" not in settings()["ways"]:
        raise LockError("The app's PIN isn't in use.")
    _check_pin(pin)
    _open("PIN")


def unlock_hello() -> None:
    if "hello" not in settings()["ways"]:
        raise LockError("Windows Hello isn't in use.")
    if 0 < time.time() - _STATE["signed_in"] < 120:          # you just signed in to Windows itself
        return _open("Windows sign-in")
    from . import hello
    try:
        if not hello.verify("Open Personal Assistant"):
            raise LockError("Not opened.")
    except hello.HelloError as e:
        raise LockError(f"{e} You can also press Windows+L, sign in to Windows, and press this button again.") from None
    _open("Windows Hello")


def state() -> dict:
    s = settings()
    return {"locked": is_locked(), "ways": s["ways"], "why": _STATE["why"], "since": int(_STATE["since"]), "wait": _wait(), "on": s["on"]}


# ---------------- by itself ----------------
def windows_locked() -> bool | None:
    """Is Windows' own lock screen up? None when Windows doesn't say."""
    w = ctypes.windll.wtsapi32
    buf, n = ctypes.c_void_p(), ctypes.c_ulong()
    if not w.WTSQuerySessionInformationW(None, ctypes.c_ulong(-1 & 0xFFFFFFFF), 25, ctypes.byref(buf), ctypes.byref(n)):
        return None
    try:
        if n.value < 20:
            return None
        flags = ctypes.c_long.from_address(buf.value + 16).value
        return True if flags == 0 else False if flags == 1 else None
    finally:
        w.WTSFreeMemory(buf)


class _Last(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def untouched() -> float:
    """Seconds since the keyboard or mouse was last touched."""
    i = _Last(ctypes.sizeof(_Last), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(i)):
        return 0.0
    return ((ctypes.windll.kernel32.GetTickCount() - i.dwTime) & 0xFFFFFFFF) / 1000


def look(was: dict) -> None:
    """Every two seconds: Windows locked, back from sleep, not touched for the time you chose."""
    from . import vault
    now, locked = time.time(), windows_locked()
    asleep, was_locked = now - was.get("at", now) > 30, was.get("windows")
    was.update(at=now, windows=locked)
    s = settings()
    if locked and not was_locked or asleep:
        vault.lock("Windows was locked" if locked else "the PC slept")
        if s["windows"]:
            lock("Windows was locked" if locked else "the PC slept")
    if was_locked and locked is False and is_locked():
        _STATE["signed_in"] = now
    if s["idle"] and not is_locked() and untouched() > s["idle"] * 60:
        lock("not used for a while")
    vault.check_idle()


def start() -> None:
    global _STARTED
    if settings()["start"]:
        lock("the app was started")
    if _STARTED:
        return
    _STARTED = True

    def loop() -> None:
        was: dict = {}
        while True:
            time.sleep(2)
            try:
                look(was)
            except Exception as e:
                print(f"[lock] {type(e).__name__}: {e}")
                time.sleep(30)
    threading.Thread(target=loop, name="lock-watch", daemon=True).start()

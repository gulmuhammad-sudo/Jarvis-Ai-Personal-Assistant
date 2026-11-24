"""Windows Hello: the finger, face or PIN you open this PC with.

verify() only asks "is it you?" (for the privacy lock). make_key() and sign() use a key inside the PC's security chip that
signs only after your gesture; the same question always gets the same signature, so a key can be made from it (for the
vault) without keeping that key anywhere.

Windows shows its own box; nothing here ever sees your finger or PIN. Test copies never show it (JARVIS_HELLO_TEST).
"""
from __future__ import annotations

import base64
import ctypes
import hashlib
import os
import re
import subprocess
import threading
import time

_NAME = re.compile(r"[A-Za-z0-9-]{1,64}")
_READY = {"at": 0.0, "up": None, "asking": False}
_LOCK = threading.Lock()
_ONE = threading.Lock()                          # one box at a time


class HelloError(ValueError):
    """Something to tell the owner, in plain words."""


_PRE = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Security.Credentials.UI.UserConsentVerifier, Windows.Security.Credentials.UI, ContentType = WindowsRuntime]
$null = [Windows.Security.Credentials.KeyCredentialManager, Windows.Security.Credentials, ContentType = WindowsRuntime]
$null = [Windows.Security.Cryptography.CryptographicBuffer, Windows.Security.Cryptography, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
"""
_AVAILABLE = _PRE + r"""
$a = Await ([Windows.Security.Credentials.UI.UserConsentVerifier]::CheckAvailabilityAsync()) ([Windows.Security.Credentials.UI.UserConsentVerifierAvailability])
$k = Await ([Windows.Security.Credentials.KeyCredentialManager]::IsSupportedAsync()) ([bool])
Write-Output "$a $k"
"""
_VERIFY = _PRE + r"""
$r = Await ([Windows.Security.Credentials.UI.UserConsentVerifier]::RequestVerificationAsync('__TEXT__')) ([Windows.Security.Credentials.UI.UserConsentVerificationResult])
Write-Output "$r"
"""
_MAKE = _PRE + r"""
$r = Await ([Windows.Security.Credentials.KeyCredentialManager]::RequestCreateAsync('__NAME__', [Windows.Security.Credentials.KeyCredentialCreationOption]::ReplaceExisting)) ([Windows.Security.Credentials.KeyCredentialRetrievalResult])
Write-Output "$($r.Status)"
"""
_SIGN = _PRE + r"""
$r = Await ([Windows.Security.Credentials.KeyCredentialManager]::OpenAsync('__NAME__')) ([Windows.Security.Credentials.KeyCredentialRetrievalResult])
if ("$($r.Status)" -ne 'Success') { Write-Output "$($r.Status)"; exit }
$b = [Windows.Security.Cryptography.CryptographicBuffer]::DecodeFromBase64String('__ASK__')
$s = Await ($r.Credential.RequestSignAsync($b)) ([Windows.Security.Credentials.KeyCredentialOperationResult])
if ("$($s.Status)" -ne 'Success') { Write-Output "$($s.Status)"; exit }
Write-Output ("Signed " + [Windows.Security.Cryptography.CryptographicBuffer]::EncodeToBase64String($s.Result))
"""
_DROP = _PRE + r"""
$m = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
$m.Invoke($null, @([Windows.Security.Credentials.KeyCredentialManager]::DeleteAsync('__NAME__'))).Wait(15000) | Out-Null
"""


def _pretend() -> str | None:
    """Test copies (isolated data only): "yes", "no" or "off" instead of Windows' box."""
    from .config import ISOLATED
    return os.environ.get("JARVIS_HELLO_TEST", "off") if ISOLATED else None


def _run(script: str, timeout: int) -> str:
    """Windows PowerShell 5.1 knows these Windows parts by itself. Nothing in the script is a secret (the answer comes back by a pipe)."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise HelloError("Windows Hello took too long.") from None
    except OSError:
        raise HelloError("Windows Hello couldn't be asked.") from None
    lines = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


# ---------------- is it there? ----------------
def ready() -> bool:
    """Set up on this PC, as far as known (asked in the background, kept for five minutes)."""
    p = _pretend()
    if p is not None:
        return p in ("yes", "no")
    with _LOCK:
        ask = not _READY["asking"] and time.time() - _READY["at"] > 300
        if ask:
            _READY["asking"] = True
    if ask:
        threading.Thread(target=_ask, name="hello-ready", daemon=True).start()
    return bool(_READY["up"])


def _ask() -> None:
    try:
        _READY["up"] = _run(_AVAILABLE, 30) == "Available True"
    except HelloError:
        _READY["up"] = False
    finally:
        _READY.update(at=time.time(), asking=False)


# ---------------- Windows' box to the front ----------------
def _to_front(stop: threading.Event) -> None:
    """Its box may open behind other windows: bring it to the front once it is there."""
    u = ctypes.windll.user32
    for _ in range(60):
        if stop.wait(0.15):
            return
        h = u.FindWindowW("Credential Dialog Xaml Host", None)
        if h:
            u.SetForegroundWindow(h)
            return


def _with_box(script: str, timeout: int = 120) -> str:
    if not _ONE.acquire(blocking=False):
        raise HelloError("Windows Hello is already asking.")
    stop = threading.Event()
    try:
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(0xFFFFFFFF)
        except (AttributeError, OSError):
            pass
        threading.Thread(target=_to_front, args=(stop,), daemon=True).start()
        return _run(script, timeout)
    finally:
        stop.set()
        _ONE.release()


_WHY = {"Canceled": "cancelled", "UserCanceled": "cancelled", "UserPrefersPassword": "cancelled", "RetriesExhausted": "there were too many tries", "DeviceBusy": "the sensor is busy", "DeviceNotPresent": "there is no sensor",
        "NotConfiguredForUser": "it isn't set up on this PC", "DisabledByPolicy": "it is turned off on this PC", "NotFound": "its key is gone", "SecurityDeviceLocked": "the security chip is locked"}


def _no(result: str) -> HelloError:
    return HelloError(f"Windows Hello: {_WHY.get(result, 'it did not work')}.")


def verify(text: str = "Open Personal Assistant") -> bool:
    """Is it you? True, False (cancelled), or HelloError when it can't be asked."""
    p = _pretend()
    if p is not None:
        if p == "off":
            raise HelloError("Windows Hello: it isn't set up on this PC.")
        return p == "yes"
    r = _with_box(_VERIFY.replace("__TEXT__", re.sub(r"[^A-Za-z0-9 .,]", "", text)[:100]))
    if r == "Verified":
        return True
    if r in ("Canceled", ""):
        return False
    raise _no(r)


def make_key(name: str) -> None:
    if not _NAME.fullmatch(name):
        raise HelloError("That isn't a name for a key.")
    p = _pretend()
    r = {"yes": "Success", "no": "UserCanceled"}.get(p, "NotConfiguredForUser") if p is not None else _with_box(_MAKE.replace("__NAME__", name))
    if r != "Success":
        raise _no(r)


def sign(name: str, ask: bytes) -> bytes:
    """The signature of these bytes: the same each time, and only after your gesture."""
    if not _NAME.fullmatch(name):
        raise HelloError("That isn't a name for a key.")
    p = _pretend()
    if p is not None:
        if p != "yes":
            raise _no("UserCanceled" if p == "no" else "NotConfiguredForUser")
        return hashlib.sha512(b"pretend" + name.encode() + ask).digest()
    r = _with_box(_SIGN.replace("__NAME__", name).replace("__ASK__", base64.b64encode(ask).decode()))
    if r.startswith("Signed "):
        try:
            sig = base64.b64decode(r[7:], validate=True)
        except ValueError:
            sig = b""
        if len(sig) >= 64:
            return sig
    raise _no(r)


def drop_key(name: str) -> None:
    if _pretend() is None and _NAME.fullmatch(name):
        try:
            _run(_DROP.replace("__NAME__", name), 30)
        except HelloError:
            pass

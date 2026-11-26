"""Your other PCs: joining one, asking its assistant, sending it a file, syncing (sync.py). Straight from PC to PC.

A PC is known by its own key (its pin), not by its address: before a single word is sent, the key at the other end has to be
the one from the pairing. Each PC keeps its own rights for the other, and its own list of what it syncs.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from . import access, remote, sync

MAX_FILE = 200 * 2**20
_JOIN: dict[str, Any] = {"state": "", "text": ""}
_STATUS: dict[str, dict] = {}
_LAST: dict[str, dict] = {}
_NEXT = {"at": 0.0}
_LOCK = threading.RLock()


class PeerError(ValueError):
    """Something to tell the owner, in plain words."""


class Elsewhere(PeerError):
    """Another machine than the one that was paired answers there."""


# ---------------- speaking ----------------
def _connect(where: str, timeout: float, pin: str | None = None) -> tuple[ssl.SSLSocket, str]:
    host, _, port = where.rpartition(":")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname, ctx.verify_mode, ctx.minimum_version = False, ssl.CERT_NONE, ssl.TLSVersion.TLSv1_2      # (its key is compared instead)
    raw = socket.create_connection((host, int(port)), timeout=timeout)
    try:
        tls = ctx.wrap_socket(raw, server_hostname=host)
    except BaseException:
        raw.close()
        raise
    got = remote.pin_of(tls.getpeercert(True) or b"")
    if pin is not None and got != pin:
        tls.close()
        raise Elsewhere("Another computer answers at that address. Nothing was sent to it.")
    return tls, got


def _speak(tls: ssl.SSLSocket, where: str, path: str, body: Any, headers: dict | None = None, timeout: float = 20, most: int = 30 * 2**20) -> dict:
    tls.settimeout(timeout)
    c = http.client.HTTPConnection(where.rpartition(":")[0], int(where.rpartition(":")[2]), timeout=timeout)
    c.sock = tls
    try:
        c.request("POST", path, body if headers and "X-Name" in headers else json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
        r = c.getresponse()
        raw = r.read(most)
    finally:
        c.close()
    try:
        j = json.loads(raw)
    except ValueError:
        raise PeerError("The other PC's answer wasn't understood.") from None
    if r.status != 200 or not isinstance(j, dict):
        t = str(j.get("error") if isinstance(j, dict) else "")[:200]
        raise PeerError({401: "The other PC doesn't know this one any more. Pair them again.", 403: t or "The other PC doesn't allow that.", 423: "The app on the other PC is locked.", 429: "The other PC says: too many requests."}.get(r.status, t or f"The other PC answered {r.status}."))
    return j


def call(i: str, path: str, body: Any, timeout: float = 20, headers: dict | None = None) -> dict:
    from . import netlog
    p = access.peers().get(i)
    if not p:
        raise PeerError("That PC isn't paired.")
    if netlog.local_only():
        raise PeerError("Local only is on (Privacy): nothing goes out.")
    fault: Exception | None = None
    for where in p["urls"]:
        try:
            tls, _ = _connect(where, 4, p["pin"])
        except Elsewhere as e:
            fault = e
            continue
        except (OSError, ValueError) as e:
            fault = fault or e
            continue
        try:
            out = _speak(tls, where, path, body, {"Authorization": f"Bearer {p['as']}.{p['token']}", **(headers or {})}, timeout)
        except (OSError, http.client.HTTPException) as e:
            raise PeerError(f"The connection broke ({type(e).__name__}).") from None
        if where != p["urls"][0]:
            access.set_peer(i, urls=[where, *[u for u in p["urls"] if u != where]])
        return out
    if isinstance(fault, Elsewhere):
        raise fault
    raise PeerError("It couldn't be reached. Is it on, is the app open, and is Devices turned on there?")


# ---------------- joining ----------------
def own_urls() -> list[str]:
    port = remote.settings()["port"]
    bind = os.environ.get("JARVIS_REMOTE_BIND", "0.0.0.0")
    if bind != "0.0.0.0":
        return [f"{bind}:{port}"]
    host = re.sub(r"[^A-Za-z0-9\-]", "-", socket.gethostname())
    return [f"{a}:{port}" for a in remote.addresses()[:5]] + [f"{host}:{port}", f"{host}.local:{port}"]


def address(text: Any) -> str:
    t = re.sub(r"^https?://", "", str(text or "").strip().rstrip("/"))
    m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9.\-]{0,90})(?::(\d{2,5}))?", t)
    if not m:
        raise PeerError("Type the address the other PC shows, like 192.168.1.5:8766.")
    if not re.fullmatch(r"[0-9.]+", m[1]) and "." in m[1] and not m[1].lower().endswith((".local", ".lan", ".home.arpa", ".ts.net")):
        raise PeerError("Only an address in your own network.")
    if re.fullmatch(r"[0-9.]+", m[1]) and not remote.allowed_ip(m[1]):
        raise PeerError("Only an address in your own network.")
    return f"{m[1]}:{m[2] or remote.PORT}"


def join(where: Any, code: Any, rights: Any) -> None:
    """Your button on the PC that typed the code. Goes on in the background; joining() says how far."""
    from . import netlog
    w = address(where)
    if len(access.clean_code(code)) != 8:
        raise PeerError("The code has eight letters.")
    if netlog.local_only():
        raise PeerError("Local only is on (Privacy): nothing goes out.")
    if len(access.devices()) >= access.MAX_DEVICES:
        raise PeerError("That is enough devices. Remove one first.")
    want = [r for r in access.PC_RIGHTS if isinstance(rights, list) and r in rights]
    with _LOCK:
        if _JOIN["state"] == "busy":
            raise PeerError("It is joining already.")
        _JOIN.update(state="busy", text="Looking for it…")
    threading.Thread(target=_join, args=(w, access.clean_code(code), want), name="join", daemon=True).start()


def joining() -> dict:
    return dict(_JOIN)


def _join(where: str, code: str, rights: list[str]) -> None:
    try:
        _JOIN["text"] = _do_join(where, code, rights)
        _JOIN["state"] = "done"
    except PeerError as e:
        _JOIN.update(state="failed", text=str(e))
    except (OSError, http.client.HTTPException, KeyError, ValueError, TypeError) as e:
        _JOIN.update(state="failed", text=f"It couldn't be reached ({type(e).__name__}). Is the address right, and Devices turned on there?")


def _do_join(where: str, code: str, rights: list[str]) -> str:
    from . import audit
    tls, pin = _connect(where, 6)
    b = _speak(tls, where, "/pair/pc/begin", {})
    salt, ns, nc = bytes.fromhex(b["salt"]), bytes.fromhex(b["nonce"]), secrets.token_bytes(16)
    if len(salt) != 16 or len(ns) != 16:
        raise PeerError("The other PC's answer wasn't understood.")
    if pin == remote.own_pin():
        raise PeerError("That is this PC.")
    mine, token = secrets.token_hex(8), secrets.token_urlsafe(32)
    hello = json.dumps({"name": socket.gethostname(), "pin": remote.own_pin(), "urls": own_urls(), "token": token, "id": mine})
    key = access.stretch(code, salt)
    tls, _ = _connect(where, 6, pin)
    r = _speak(tls, where, "/pair/pc/code", {"nonce": nc.hex(), "proof": access.proof(key, "client", pin, nc, ns, hello), "hello": hello})
    import hmac
    if not hmac.compare_digest(access.proof(key, "server", pin, nc, ns, hello).encode(), str(r.get("proof")).encode()):
        raise PeerError("The other PC couldn't prove that it knows the code. Nothing was paired.")
    _JOIN["text"] = "Found. Press Allow on the other PC."
    end = time.monotonic() + access.ASK_FOR
    while time.monotonic() < end:
        time.sleep(1.2 if not os.environ.get("JARVIS_REMOTE_BIND") else 0.1)
        tls, _ = _connect(where, 6, pin)
        s = _speak(tls, where, "/pair/state", {"ask": r["ask"]})
        if s["state"] == "waiting":
            continue
        if s["state"] != "allowed":
            raise PeerError("It was denied on the other PC." if s["state"] == "denied" else "That took too long. Make a new code.")
        name = access.name_of(s.get("pc"), "PC")
        urls = list(dict.fromkeys([where, f"{re.sub(r'[^A-Za-z0-9-]', '-', name)}:{where.rpartition(':')[2]}"]))
        access.add_pair(mine, name, access.hash_of(token), rights, urls, pin, str(s["id"]), str(s["token"]))
        audit.record("device_added", name=name, kind="pc", rights=rights)
        return f"Paired with {name}."
    raise PeerError("That took too long. Make a new code.")


# ---------------- what you do with it ----------------
def options(i: str) -> dict:
    p = access.peers().get(i) or {}
    k = p.get("kinds")
    return {"auto": p.get("auto") is True, "kinds": [x for x in sync.KINDS if x in k] if isinstance(k, list) else list(sync.KINDS)}


def set_options(i: Any, d: dict) -> None:
    i = str(i)
    if i not in access.peers():
        raise PeerError("That PC isn't paired.")
    new: dict[str, Any] = {}
    if "auto" in d:
        new["auto"] = d["auto"] is True
    if "kinds" in d:
        if not isinstance(d["kinds"], list):
            raise PeerError("Choose what to sync.")
        new["kinds"] = [x for x in sync.KINDS if x in d["kinds"]]
    access.set_peer(i, **new)


def listing() -> list[dict]:
    return [{"id": i, "name": p["name"], **options(i), "status": _STATUS.get(i), "last": _LAST.get(i) or p.get("last")} for i, p in access.peers().items()]


def check(i: str) -> dict:
    try:
        s = {"on": True, **{k: v for k, v in call(i, "/pc/hello", {}, 8).items() if k in ("name", "version", "state", "battery", "locked")}}
    except PeerError as e:
        s = {"on": False, "text": str(e)}
    _STATUS[i] = {**s, "at": datetime.now().isoformat(timespec="seconds")}
    return _STATUS[i]


def ask(i: str, text: Any, seconds: float = 90) -> str:
    t = str(text or "").strip()
    if not t or len(t) > 4000:
        raise PeerError("Say what it should do (up to 4000 letters).")
    r = call(i, "/pc/ask", {"text": t, "wait": seconds}, seconds + 15)
    a = str(r.get("answer") or "").strip()[:8000]
    return a if r.get("done") else (a + "\n" if a else "") + ("It waits for an answer on that PC." if r.get("waiting_for_owner") else "It is still working on it.")


def find(name: Any) -> str | None:
    n = str(name or "").strip().lower()
    have = {i: p["name"].lower() for i, p in access.peers().items()}
    if not n and len(have) == 1:
        return next(iter(have))
    exact = [i for i, x in have.items() if x == n]
    part = [i for i, x in have.items() if n and n in x]
    return exact[0] if exact else part[0] if len(part) == 1 else None


def send_file(i: str, path: Any) -> str:
    from . import audit, guard
    p = Path(str(path or "").strip().strip('"'))
    if guard.elsewhere(str(p)) or not p.is_absolute() or not p.is_file():
        raise PeerError("Choose a file on this PC.")
    if guard.secret_file(str(p)):
        raise PeerError("That looks like a file with passwords or keys: it isn't sent.")
    size = p.stat().st_size
    if size > MAX_FILE:
        raise PeerError("At most 200 MB.")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while b := f.read(2**20):
            h.update(b)
    with open(p, "rb") as f:
        r = call(i, "/pc/file", f, 600, {"Content-Type": "application/octet-stream", "Content-Length": str(size), "X-Name": quote(p.name), "X-Sha256": h.hexdigest()})
    audit.record("file_sent_to_pc", name=p.name, size=size)
    return f"{p.name} is there ({r.get('name')}, in Downloads › Personal Assistant)."


def run_sync(i: str, deletions: str = "ask") -> dict:
    o = options(i)
    if deletions not in ("ask", "yes", "no"):
        raise PeerError("Choose what is right.")
    out: dict[str, Any] = {"at": datetime.now().isoformat(timespec="seconds"), "ok": False, "text": ""}
    try:
        r = sync.run(i, lambda path, body: call(i, path, body, 60), remote.own_id(), o["kinds"], deletions)
        held = sum(x["here"] + x["there"] for x in r["held"].values())
        out.update(ok=True, held=r["held"], text=(f"{r['in']} in, {r['out']} out" if r["in"] or r["out"] else "Nothing new") + (f", {r['aside']} set aside" if r["aside"] else "") + (f"; {held} deletions are held: say what is right" if held else ""))
        if r["in"]:
            _refresh()
    except (PeerError, sync.SyncError) as e:
        out["text"] = str(e)
        raise PeerError(str(e)) from None
    except (KeyError, TypeError, ValueError) as e:
        out["text"] = "The other PC's answer wasn't understood. Are both on the same version?"
        raise PeerError(out["text"]) from e
    finally:
        _LAST[i] = out
        access.set_peer(i, last=out)
    return out


def _refresh() -> None:
    from . import hud
    h = hud.HUB
    if h is not None and hasattr(h.brain, "refresh_system"):
        h.brain.refresh_system()


def tick(now: datetime, notify) -> int:
    """Every ten minutes, with the PCs where it is turned on (a PC that is off is no fault)."""
    from . import netlog
    if time.monotonic() < _NEXT["at"] or netlog.local_only():
        return 0
    _NEXT["at"] = time.monotonic() + sync.EVERY
    todo = [i for i in access.peers() if options(i)["auto"]]
    if not todo:
        return 0

    def go() -> None:
        for i in todo:
            try:
                r = run_sync(i)
                if r.get("held") and (_LAST.get(i, {}).get("told") is not True):
                    notify("Syncing with another PC would delete a lot: say what is right in Settings › Devices.", "info")
            except PeerError:
                pass
    threading.Thread(target=go, name="sync", daemon=True).start()
    return len(todo)


# ---------------- what the other PC may do here ----------------
def downloads() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads" / "Personal Assistant"


def safe_name(text: Any) -> str:
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f‪-‮⁦-⁩‎‏]', "_", str(text or "")).strip(" .")[:120]
    if not n or re.match(r"(con|prn|aux|nul|com\d|lpt\d)(\.|$)", n, re.I):
        n = "file"
    return n


def _take_file(h: Any, d: dict) -> dict:
    from . import audit, hud
    try:
        size = int(h.headers.get("Content-Length") or -1)
    except ValueError:
        size = -1
    want = str(h.headers.get("X-Sha256") or "")
    if not 0 <= size <= MAX_FILE or not re.fullmatch(r"[0-9a-f]{64}", want) or h.headers.get("Transfer-Encoding"):
        raise PeerError("At most 200 MB.")
    to = downloads()
    to.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(to).free < size + 500 * 2**20:
        raise PeerError("There isn't enough room on that PC.")
    name = safe_name(unquote(str(h.headers.get("X-Name") or "")))
    part = to / f".{secrets.token_hex(6)}.part"
    digest, left = hashlib.sha256(), size
    h._got = True
    try:
        with open(part, "xb") as f:
            while left > 0:
                b = h.rfile.read(min(left, 2**18))
                if not b:
                    raise PeerError("The connection broke.")
                digest.update(b)
                f.write(b)
                left -= len(b)
        if digest.hexdigest() != want:
            raise PeerError("The file didn't arrive whole.")
        stem, suffix = os.path.splitext(name)
        for n in range(1, 1000):
            out = to / (name if n == 1 else f"{stem} ({n}){suffix}")
            try:
                os.rename(part, out)                     # (on Windows this never writes over a file)
                break
            except FileExistsError:
                continue
        else:
            raise PeerError("There are too many files with that name.")
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    try:
        with open(f"{out}:Zone.Identifier", "w", encoding="ascii") as z:   # Windows warns before it runs something that came from elsewhere
            z.write("[ZoneTransfer]\nZoneId=3\n")
    except OSError:
        pass
    audit.record("file_from_pc", name=out.name, size=size, pc=d["name"])
    if hud.HUB:
        hud.HUB.notify(f"{d['name']} sent a file: {out.name} (Downloads › Personal Assistant)", "info")
    return {"ok": True, "name": out.name}


def serve(h: Any, path: str, d: dict, locked: bool) -> None:
    from . import __version__, audit, hud
    if path == "/pc/file" and not locked:
        if "files" not in d["rights"]:
            return h._json({"error": "That PC doesn't take files from this one."}, 403)
        return h._json(_take_file(h, d))
    data = h._data(30 * 2**20 if path.startswith("/pc/sync/") and "sync" in d["rights"] and not locked else None) if path != "/pc/file" else {}
    if path == "/pc/hello":
        import psutil
        b = psutil.sensors_battery()
        return h._json({"name": socket.gethostname(), "version": __version__, "locked": locked, "state": "" if locked else hud.HUB.state, "battery": None if b is None or locked else round(b.percent), "time": time.time()})
    if locked:
        return h._json({"error": "The app on that PC is locked."}, 423)
    if path == "/pc/ask":
        if "ask" not in d["rights"]:
            return h._json({"error": "That PC doesn't take orders from this one."}, 403)
        text = str(data.get("text") or "").strip()[:4000]
        if not text:
            raise PeerError("Say what it should do.")
        audit.record("pc_asked", pc=d["name"])
        got = hud.HUB.ask_and_wait(text, "pc", max(1.0, min(float(data.get("wait") or 60), 120)))
        return h._json(got) if got is not None else h._json({"error": "Stop was pressed on that PC."}, 409)
    if path.startswith("/pc/sync/"):
        if "sync" not in d["rights"]:
            return h._json({"error": "That PC doesn't sync with this one."}, 403)
        return h._json(sync.serve(path.rpartition("/")[2], data, d["id"], remote.own_id(), options(d["id"])["kinds"]))
    return h._json({"error": "not there"}, 404)

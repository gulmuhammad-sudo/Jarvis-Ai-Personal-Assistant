"""The door for your phone and your other PCs: a second server, apart from the window's own, off until you turn it on.

- HTTPS only, with a key this PC made for itself (locked for your Windows account); only from addresses of a home network
  (and, if you allow it, of a private VPN such as Tailscale). Nothing is opened in your router, no service in between.
- A phone gets one small page (remote.html); the window's own page and its requests are not reachable here. Not the vault,
  settings, files, permissions or the lock: there is no way to them.
- Every request: a paired device, its rights, a limit of requests, and not while the app is locked (only Stop).
- Local only turns it off.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import socket
import ssl
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import access

PORT = 8766
PAGE = Path(__file__).with_name("remote.html")
MAX_AT_ONCE, PER_MINUTE = 40, 240
CHAT = {"user", "jarvis", "notify", "error"}
_LOCK = threading.RLock()
_STATE: dict[str, Any] = {"server": None, "error": "", "pin": ""}
_RATE: dict[str, list[float]] = {}


class RemoteError(ValueError):
    """Something to tell the owner, in plain words."""


# ---------------- settings and addresses ----------------
def settings() -> dict:
    from . import schedule
    s = schedule.get_setting("remote")
    s = s if isinstance(s, dict) else {}
    p = s.get("port")
    return {"on": s.get("on") is True, "port": p if isinstance(p, int) and not isinstance(p, bool) and 1024 <= p <= 65535 else PORT, "vpn": s.get("vpn") is True}


def set_settings(d: dict) -> None:
    from . import audit, netlog, schedule
    new = settings()
    if "port" in d:
        if isinstance(d["port"], bool) or not isinstance(d["port"], int) or not 1024 <= d["port"] <= 65535:
            raise RemoteError("The port is a number from 1024 to 65535.")
        new["port"] = d["port"]
    for k in ("on", "vpn"):
        if k in d:
            new[k] = d[k] is True
    if d.get("on") is True and netlog.local_only():
        raise RemoteError("Local only is on (Privacy), so nothing comes in or goes out.")
    was = settings()
    schedule.set_setting("remote", new)
    audit.record("remote_settings", **new)
    if new != was:
        stop()
        if new["on"]:
            start()
            if _STATE["error"]:
                schedule.set_setting("remote", {**new, "on": False})
                raise RemoteError(_STATE["error"])
    if not new["on"]:
        access.stop_pairing()


_HOME = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
_VPN = [ipaddress.ip_network("100.64.0.0/10")]
_CARDS: dict[str, Any] = {"at": 0.0, "list": []}


def _cards() -> list[tuple[str, str, Any]]:
    """(name, address, network) of this PC's network cards that are connected."""
    import psutil
    if time.monotonic() - _CARDS["at"] > 10 or not _CARDS["at"]:
        up = {n for n, s in psutil.net_if_stats().items() if s.isup}
        out = []
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and name in up and not a.address.startswith(("127.", "169.254.")):
                    try:
                        out.append((name, a.address, ipaddress.ip_network(f"{a.address}/{a.netmask or '255.255.255.255'}", strict=False)))
                    except ValueError:
                        pass
        _CARDS.update(at=time.monotonic(), list=out)
    return _CARDS["list"]


def home_ip(ip: Any) -> bool:
    """In a home network: the usual ranges, or the very network this PC is in (some routers hand out other numbers)."""
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    a = getattr(a, "ipv4_mapped", None) or a
    if a.version != 4 or a.is_multicast or a.is_unspecified:
        return False
    return any(a in n for n in _HOME) or any(a in net and net.prefixlen >= 20 for _, _, net in _cards())


def allowed_ip(ip: Any, vpn: bool | None = None) -> bool:
    """May something at that address knock at all? (never from the internet)"""
    if home_ip(ip):
        return True
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return False
    a = getattr(a, "ipv4_mapped", None) or a
    return a.version == 4 and (settings()["vpn"] if vpn is None else vpn) and any(a in n for n in _VPN)


def _gateway() -> str:
    """The router's address, from Windows' own table (nothing is sent)."""
    import ctypes
    import struct

    class Row(ctypes.Structure):
        _fields_ = [("dest", ctypes.c_uint32), ("mask", ctypes.c_uint32), ("policy", ctypes.c_uint32), ("next", ctypes.c_uint32), *[(f"x{i}", ctypes.c_uint32) for i in range(10)]]
    r = Row()
    try:
        if ctypes.windll.iphlpapi.GetBestRoute(struct.unpack("<I", socket.inet_aton("8.8.8.8"))[0], 0, ctypes.byref(r)) == 0:
            return socket.inet_ntoa(struct.pack("<I", r.next))
    except (AttributeError, OSError):
        pass
    return ""


def addresses() -> list[str]:
    """This PC's own addresses, the one in the router's network first."""
    gate, found = _gateway(), []
    for name, a, net in _cards():
        odd = bool(re.search(r"virtual|vmware|hyper-v|vethernet|wsl|bluetooth|loopback", name, re.I))
        vpn = any(ipaddress.ip_address(a) in n for n in _VPN)
        found.append((not (gate and ipaddress.ip_address(gate) in net), odd, vpn, a))
    return [a for *_, a in sorted(set(found))]


# ---------------- its key and certificate ----------------
def _make_key() -> bytes:
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.generate_private_key(ec.SECP256R1()).private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption())


def pin_of(cert_der: bytes) -> str:
    """What identifies a PC: the SHA-256 of its public key (stays when the certificate is renewed)."""
    import hashlib
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization as ser
    k = x509.load_der_x509_certificate(cert_der).public_key()
    return hashlib.sha256(k.public_bytes(ser.Encoding.DER, ser.PublicFormat.SubjectPublicKeyInfo)).hexdigest()


def _certificate() -> tuple[bytes, bytes]:
    """(certificate, key) as PEM; made for today's addresses, the key stays the same."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization as ser
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    s = access.server_key()
    if not s.get("key"):
        s = {"key": _make_key().decode("ascii"), "id": secrets.token_hex(8)}
        access.set_server_key(s)
    key = ser.load_pem_private_key(s["key"].encode("ascii"), None)
    host = re.sub(r"[^A-Za-z0-9\-]", "-", socket.gethostname())[:60] or "pc"
    names: list[Any] = [x509.DNSName(n) for n in (host, f"{host}.local", "localhost")]
    names += [x509.IPAddress(ipaddress.ip_address(a)) for a in ["127.0.0.1", *addresses()]]
    who = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Personal Assistant on {host}"[:60])])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(who).issuer_name(who).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=390))
            .add_extension(x509.SubjectAlternativeName(names), False).add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False).sign(key, hashes.SHA256()))
    return cert.public_bytes(ser.Encoding.PEM), key.private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.NoEncryption())


def own_pin() -> str:
    return pin_of(ssl.PEM_cert_to_DER_cert(_certificate()[0].decode("ascii")))


def own_id() -> str:
    _certificate()
    return str(access.server_key().get("id") or "")


def shown_pin(pin: str) -> str:
    return " ".join(pin[i:i + 4] for i in range(0, 32, 4)).upper()


def _context() -> ssl.SSLContext:
    from cryptography.hazmat.primitives import serialization as ser
    cert, key = _certificate()
    word = secrets.token_hex(24)                         # Python reads a key from files only: on the disk it is encrypted, for a moment
    locked = ser.load_pem_private_key(key, None).private_bytes(ser.Encoding.PEM, ser.PrivateFormat.PKCS8, ser.BestAvailableEncryption(word.encode()))
    fd, path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(cert + locked)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(path, password=word)
    finally:
        os.unlink(path)
    _STATE["pin"] = pin_of(ssl.PEM_cert_to_DER_cert(cert.decode("ascii")))
    return ctx


# ---------------- the server ----------------
class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 32
    allow_reuse_address = False

    def __init__(self, bind: str, port: int) -> None:
        self.ctx = _context()
        self.room = threading.BoundedSemaphore(MAX_AT_ONCE)
        self.here: dict[str, int] = {}
        self.here_lock = threading.Lock()
        super().__init__((bind, port), RemoteHandler)

    def verify_request(self, request, client_address) -> bool:
        ip = client_address[0]
        if not allowed_ip(ip) or access.held(ip):
            return False
        with self.here_lock:
            if self.here.get(ip, 0) >= 12 or not self.room.acquire(blocking=False):
                return False
            self.here[ip] = self.here.get(ip, 0) + 1
        return True

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            ip = client_address[0]
            with self.here_lock:
                self.here[ip] -= 1
                if self.here[ip] <= 0:
                    del self.here[ip]
            self.room.release()

    def finish_request(self, request, client_address) -> None:
        request.settimeout(10)                           # the greeting has ten seconds, in its own thread
        try:
            tls = self.ctx.wrap_socket(request, server_side=True)
        except (OSError, ValueError):
            return
        try:
            tls.settimeout(25)
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def handle_error(self, request, client_address) -> None:
        pass


def start() -> bool:
    """Open the door (if it is on). What went wrong is in status()."""
    from . import netlog
    with _LOCK:
        s = settings()
        from . import parts
        if _STATE["server"] or not s["on"] or netlog.local_only() or not parts.is_on("devices"):
            return bool(_STATE["server"])
        _STATE["error"] = ""
        try:
            srv = Server(os.environ.get("JARVIS_REMOTE_BIND", "0.0.0.0"), s["port"])
        except OSError as e:
            _STATE["error"] = f"Port {s['port']} is in use by another program; choose another." if getattr(e, "winerror", 0) in (10048, 10013) else f"Windows said: {e.strerror or e}"
            return False
        _STATE["server"] = srv
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.3}, name="remote", daemon=True).start()
        return True


def stop() -> None:
    with _LOCK:
        srv, _STATE["server"] = _STATE["server"], None
        if srv:                                          # (held until the port is free: off and on again quickly)
            srv.shutdown()
            srv.server_close()
    access.flush(True)


def status() -> dict:
    s = settings()
    from . import netlog
    run = bool(_STATE["server"])
    return {**s, "running": run, "error": _STATE["error"], "local_only": netlog.local_only(), "addresses": addresses(), "host": socket.gethostname(), "pin": shown_pin(_STATE["pin"]) if run else ""}


def _limited(who: str) -> bool:
    now = time.monotonic()
    with _LOCK:
        if len(_RATE) > 500:
            _RATE.clear()
        t = [x for x in _RATE.get(who, []) if now - x < 60]
        t.append(now)
        _RATE[who] = t
        return len(t) > PER_MINUTE


class RemoteHandler(BaseHTTPRequestHandler):
    server_version = "PA"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    MAX_BODY = 64_000
    _got = True

    def log_message(self, *args) -> None:
        pass

    def version_string(self) -> str:
        return "PA"

    # ---- answers ----
    def _headers(self, kind: str, n: int, extra: dict | None = None) -> None:
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(n))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def _json(self, data: Any, status: int = 200, extra: dict | None = None) -> None:
        body = json.dumps(data).encode()
        if status >= 400:
            self.close_connection = True
            if not self._got:                            # an unread body would break the connection before the answer is read
                try:
                    self.rfile.read(max(0, min(int(self.headers.get("Content-Length", "0")), 2**20)))
                except (ValueError, OSError):
                    pass
        self.send_response(status)
        self._headers("application/json", len(body), extra)
        self.wfile.write(body)

    # ---- who ----
    def _host_ok(self) -> bool:
        h = self.headers.get("Host", "").rpartition(":")[0] or self.headers.get("Host", "")
        name = socket.gethostname().lower()
        if h.lower() in (name, f"{name}.local", "localhost") or settings()["vpn"] and h.lower().startswith(f"{name}.") and h.lower().endswith(".ts.net"):
            return True
        return allowed_ip(h, vpn=True)

    def _origin_ok(self) -> bool:
        """A request that changes something comes from our own page (or from no page at all: another PC)."""
        o = self.headers.get("Origin")
        return o is None or o == f"https://{self.headers.get('Host', '')}"

    def _device(self) -> dict | None:
        ip = self.client_address[0]
        auth = self.headers.get("Authorization", "")
        m = re.fullmatch(r"Bearer ([0-9a-f]{16})\.([A-Za-z0-9_\-]{30,60})", auth)
        kind = "pc"
        if not m:
            m = re.search(r"(?:^|;\s*)__Host-pa=([0-9a-f]{16})\.([A-Za-z0-9_\-]{30,60})(?:;|$)", self.headers.get("Cookie", ""))
            kind = "phone"
        if not m:
            return None
        d = access.check(m[1], m[2], ip, kind)
        if d is None:
            access.failed(ip)
        return d

    def _body(self, most: int | None = None) -> bytes:
        most = self.MAX_BODY if most is None else most
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if n < 0 or n > most or self.headers.get("Transfer-Encoding"):
            raise RemoteError("That is too big.")
        self._got = True
        return self.rfile.read(n)

    def _data(self, most: int | None = None) -> dict:
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise RemoteError("That wasn't understood.")
        try:
            d = json.loads(self._body(most) or b"{}")
        except ValueError:
            raise RemoteError("That wasn't understood.") from None
        if not isinstance(d, dict):
            raise RemoteError("That wasn't understood.")
        return d

    # ---- requests ----
    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json({"error": "bad host"}, 403)
        if _limited(self.client_address[0]):
            return self._json({"error": "Too many requests."}, 429)
        path = self.path.partition("?")[0]
        if path == "/":
            return self._page()
        if path == "/favicon.ico":
            self.send_response(204)
            self._headers("image/x-icon", 0)
            return
        self._json({"error": "not there"}, 404)

    do_HEAD = do_GET

    def _page(self) -> None:
        nonce = secrets.token_urlsafe(16)
        from . import schedule
        import html
        body = PAGE.read_text(encoding="utf-8").replace("__NONCE__", nonce).replace("__NAME__", html.escape(schedule.agent_name())).encode("utf-8")
        csp = f"default-src 'none'; script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        self.send_response(200)
        self._headers("text/html; charset=utf-8", len(body), {"Content-Security-Policy": csp, "Permissions-Policy": "camera=(), microphone=(), geolocation=()"})
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_POST(self) -> None:
        from . import hud, lock
        ip = self.client_address[0]
        self._got = False
        if not self._host_ok() or not self._origin_ok():
            return self._json({"error": "forbidden"}, 403)
        if access.held(ip) or _limited(ip):
            return self._json({"error": "Too many requests. Wait a little."}, 429)
        path = self.path.partition("?")[0]
        try:
            if path.startswith("/pair/"):
                return self._pair(path, ip, lock.is_locked())
            d = self._device()
            if d is None:
                return self._json({"error": "not paired"}, 401)
            if path.startswith("/pc/"):
                if d["kind"] != "pc":
                    return self._json({"error": "forbidden"}, 403)
                from . import peers, sync
                try:
                    return peers.serve(self, path, d, lock.is_locked())
                except (peers.PeerError, sync.SyncError) as e:
                    return self._json({"error": str(e)}, 400)
            if d["kind"] != "phone" or not self.headers.get("X-PA"):      # (a header another page can't send)
                return self._json({"error": "forbidden"}, 403)
            return self._phone(path, d, hud.HUB, lock.is_locked())
        except (RemoteError, access.AccessError) as e:
            return self._json({"error": str(e)}, 400)
        except (ValueError, TypeError, KeyError, AttributeError) as e:
            return self._json({"error": str(e) if isinstance(e, ValueError) and str(e)[:1].isupper() and len(str(e)) < 200 else "Something is missing or wrong."}, 400)

    do_PUT = do_POST

    def _pair(self, path: str, ip: str, locked: bool) -> None:
        if locked:
            return self._json({"error": "The app on the PC is locked."}, 423)
        if path == "/pair/pc/code":
            pc_hello = self._data()
            return self._json(access.pc_code(_STATE["pin"], pc_hello.get("nonce"), pc_hello.get("proof"), pc_hello.get("hello"), ip))
        if path == "/pair/pc/begin":
            self._data()
            return self._json(access.pc_begin())
        data = self._data()
        if path == "/pair/code":
            if not self.headers.get("X-PA"):
                return self._json({"error": "forbidden"}, 403)
            time.sleep(0.3)
            return self._json({"ask": access.phone_code(data.get("code"), data.get("name"), ip)})
        if path == "/pair/state":
            s = access.ask_state(data.get("ask"))
            if s["state"] == "allowed" and s["kind"] == "phone":       # the page never sees the secret: only the browser keeps it
                return self._json({"state": "allowed"}, 200, {"Set-Cookie": f"__Host-pa={s['id']}.{s['token']}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={access.IDLE_DAYS * 86400}"})
            if s["state"] == "allowed":
                return self._json({**s, "pc": socket.gethostname(), "id": s["id"], "port": settings()["port"], "own": own_id()})
            return self._json(s)
        self._json({"error": "not there"}, 404)

    def _phone(self, path: str, d: dict, hub: Any, locked: bool) -> None:
        data = self._data()
        may = set(d["rights"])
        if path == "/api/stop":
            threading.Thread(target=hub.emergency_stop, args=(f"{d['name']} (phone)",), daemon=True).start()
            return self._json({"ok": True})
        if path == "/api/leave":
            access.remove(d["id"])
            return self._json({"ok": True}, 200, {"Set-Cookie": "__Host-pa=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0"})
        if path == "/api/state":
            return self._json(phone_state(hub, d, locked, str(data.get("have") or "")))
        if locked:
            return self._json({"error": "The app on the PC is locked."}, 423)
        if path == "/api/send":
            if "chat" not in may:
                return self._json({"error": "This device may not chat."}, 403)
            text = str(data.get("text") or "").strip()[:4000]
            if not text:
                raise RemoteError("Write something first.")
            hub.submit(text, "phone")
            return self._json({"ok": True})
        if path == "/api/confirm":
            if "approve" not in may:
                return self._json({"error": "Answer that on the PC."}, 403)
            return self._json({"ok": hub.answer_confirm(str(data.get("id")), data.get("allow") is True, how=f"{d['name']} (phone)", once=True)})
        if path.startswith("/api/lists"):
            if "lists" not in may:
                return self._json({"error": "This device may not see the lists."}, 403)
            return self._json(lists(path.rpartition("/")[2], data))
        self._json({"error": "not there"}, 404)


def phone_state(hub: Any, d: dict, locked: bool, have: str) -> dict:
    import hashlib
    from . import schedule
    base = {"name": schedule.agent_name(), "device": d["name"], "rights": d["rights"], "locked": locked}
    if locked:
        return {**base, "chat": [], "asks": [], "state": "locked", "mark": ""}
    chat = []
    if "chat" in d["rights"]:
        chat = [{"id": e.get("id", ""), "type": e["type"], "text": str(e.get("text") or "")[:6000], "time": str(e.get("time") or "")[:5], "src": e.get("source", "")} for e in list(hub.history) if e.get("type") in CHAT and e.get("text")][-60:]
    asks = [{"id": k, "question": s["question"][:1500]} for k, s in list(hub.pending.items()) if not s["event"].is_set()]
    out = {**base, "asks": asks if "approve" in d["rights"] else [], "waiting": len(asks), "state": hub.state, "busy": bool(hub.busy)}
    mark = hashlib.sha256(json.dumps([chat, out]).encode()).hexdigest()[:16]
    return {"same": True, "mark": mark} if mark == have else {**out, "chat": chat, "mark": mark}


def lists(action: str, data: dict) -> dict:
    from . import planner, tools
    if action == "add":
        planner.save_task(title=data.get("title"), due=data.get("due") or None)
    elif action == "done":
        planner.set_done(int(data.get("id")), data.get("done") is True)
    elif action != "lists":
        raise RemoteError("That isn't there.")
    if action != "lists":
        tools._planner_changed()
    days = [{"day": r["day"], "items": [{"at": "" if e["all_day"] else e["start"][11:16], "text": e["title"][:200]} for e in r["events"]] + [{"at": p["time"], "text": p["label"]} for p in r["prayers"]]} for r in planner.agenda(days=3)]
    return {"tasks": [{"id": t["id"], "title": t["title"], "due": t.get("due") or "", "done": False} for t in planner.list_tasks(limit=100)], "agenda": days}

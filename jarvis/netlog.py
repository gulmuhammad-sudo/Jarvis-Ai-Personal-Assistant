"""What goes out: which services this app talks to, how often, and "Local only".

Python says by itself when a program looks up an address or opens a connection (audit events); this listens to
those, so nothing in the app can forget to be counted. Kept on this PC only: the day, the service's name and how
often, never what was said. Local only refuses every one of them except this PC itself.

Not seen: what other programs do (your browser, Windows, Ollama while it downloads a model) and the app's window
itself (its letters come from Google Fonts; radio). The window is held back in Local only by the page's own rules.
"""
from __future__ import annotations

import ipaddress
import platform
import queue
import socket
import sqlite3
import sys
import threading
import time
from datetime import date, timedelta
from typing import Any

KEEP = (7, 30, 90)
_ON = False                                  # listening (only after install())
_HOOKED = False
_LOCAL = False                               # Local only
_QUEUE: "queue.SimpleQueue[tuple]" = queue.SimpleQueue()      # (its put may be used inside an audit hook)
_FLUSH = threading.Lock()

# (words at the end of the address, name, kind, what goes there, how to stop it)
SERVICES: list[tuple[tuple[str, ...], str, str, str, str]] = [
    (("generativelanguage.googleapis.com",), "Gemini (Google)", "ai",
     "What you say or type, the conversation, and what it needs for an answer (your profile and memories too); pictures when you ask it to look. In a Live call: the sound of your microphone.", "AI Models; Settings › Voice & Mic"),
    (("api.groq.com",), "Groq", "ai", "The sound of what you say, to write it down; your messages when Groq answers; a meeting if you choose Groq for it.", "AI Models; Settings › Voice & Mic"),
    (("openrouter.ai",), "OpenRouter", "ai", "Your messages when it answers.", "AI Models"),
    (("api.deepseek.com",), "DeepSeek", "ai", "Your messages when it answers.", "AI Models"),
    (("api.anthropic.com",), "Claude (Anthropic)", "ai", "Your messages when it answers.", "AI Models"),
    (("speech.platform.bing.com",), "Microsoft voices", "ai", "The text of spoken answers, to read it out loud.", "Settings › Voice & Mic: voices on this PC"),
    (("image.pollinations.ai",), "Pollinations.ai", "you", "Your words for a picture.", "Permissions: making a picture online"),
    (("imap.gmail.com",), "Gmail", "you", "Your sign-in, and searches in your own mail.", "Planner › Email: disconnect"),
    (("duckduckgo.com",), "DuckDuckGo", "you", "The words of a web search.", ""),
    (("wikipedia.org",), "Wikipedia", "you", "The words you looked up.", ""),
    (("youtube.com", "youtu.be"), "YouTube", "you", "The words you looked up.", ""),
    (("radio-browser.info",), "Radio list (radio-browser.info)", "you", "The words of a station search.", ""),
    (("ntfy.sh", "api.telegram.org", "discord.com", "discordapp.com", "hooks.slack.com"), "Your connections (ntfy, Telegram, Discord, Slack)", "you", "The text you allowed, to the place you set up.", "Settings › API"),
    (("wttr.in",), "Weather (wttr.in)", "info", "The name of your place.", "Settings › General: location"),
    (("api.aladhan.com",), "Prayer times (aladhan.com)", "info", "The name of your place.", "Settings › General: location"),
    (("nominatim.openstreetmap.org",), "Place search (OpenStreetMap)", "info", "The name of a place you typed.", ""),
    (("news.google.com",), "Google News", "info", "Topics you follow and news searches.", "Daily › News"),
    (("feeds.bbci.co.uk", "dawn.com", "geo.tv", "espncricinfo.com", "tribune.com.pk", "feeds.arstechnica.com"), "News sources", "info", "Nothing but the request.", "Daily › News"),
    (("msftconnecttest.com", "www.gstatic.com", "speed.cloudflare.com", "1.1.1.1", "8.8.8.8", "www.microsoft.com"), "Is there internet?", "check", "Nothing but the request.", ""),
    (("huggingface.co", "hf.co", "ollama.com"), "Downloads of voices and models", "load", "Nothing but the request, when you press Download.", ""),
    (("github.com", "githubusercontent.com"), "GitHub", "load", "Nothing but the request.", ""),
]
KINDS = {"ai": "AI and voice", "you": "Because you asked", "info": "Weather, prayer times, news", "check": "Checking the internet", "load": "Downloads", "web": "Web pages and the rest"}


class LocalOnly(socket.gaierror):
    """Refused because Local only is on (looks like "no internet" to everything that asks)."""

    def __init__(self, host: str = "") -> None:
        super().__init__(socket.EAI_NONAME, f"Local only is on: nothing may leave this PC ({host})" if host else "Local only is on: nothing may leave this PC")


def service(host: str) -> tuple[str, str, str, str]:
    """(name, kind, what goes there, how to stop it) for an address."""
    for ends, name, kind, what, off in SERVICES:
        if any(host == e or host.endswith("." + e) for e in ends):
            return name, kind, what, off
    return "Other web addresses", "web", "Pages you asked for, and whatever else was opened.", ""


def clean(host: Any) -> str:
    if isinstance(host, (bytes, bytearray)):
        host = bytes(host).decode("ascii", "replace")
    return str(host or "").strip().rstrip(".").lower().split("%", 1)[0][:200]


def is_here(host: Any) -> bool:
    """This PC itself (not the home network: that is another computer)."""
    if host is None:
        return True
    h = clean(host).strip("[]")
    if h in ("", "localhost", platform.node().lower()):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_loopback or ip.is_unspecified or bool(getattr(ip, "ipv4_mapped", None) and ip.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def _hook(event: str, args: tuple) -> None:
    if event == "socket.getaddrinfo":
        host = args[0] if args else None
    elif event == "socket.connect":
        addr = args[1] if len(args) > 1 else None
        if not isinstance(addr, tuple) or not addr:
            return
        host = addr[0]
    else:
        return
    if not _ON or is_here(host):
        return
    h = clean(host)
    if _LOCAL:
        _QUEUE.put(("no", h, 0, time.time()))
        raise LocalOnly(h)
    if event == "socket.getaddrinfo":                    # (a connect comes after its lookup: counted once)
        _QUEUE.put(("yes", h, 0, time.time()))


def _note(host: Any, size: Any, refused: type[Exception] | None = None, **k: Any) -> None:
    """A message over a connection that may be open already."""
    h = clean(host)
    if not _ON or is_here(h):
        return
    if _LOCAL:
        _QUEUE.put(("no", h, 0, time.time()))
        raise (refused or LocalOnly)(str(LocalOnly(h)), **k)
    try:
        n = int(size or 0)
    except (TypeError, ValueError):
        n = 0
    _QUEUE.put(("sent", h, n, time.time()))


def _watch_httpx(m: Any) -> None:
    """The AI services keep one connection open for many messages: those are counted where they are sent."""
    if getattr(m.Client.send, "_netlog", False):
        return
    plain, async_plain = m.Client.send, m.AsyncClient.send

    def send(self, request, *a, **k):
        _note(request.url.host, request.headers.get("Content-Length"), m.ConnectError, request=request)
        return plain(self, request, *a, **k)

    async def asend(self, request, *a, **k):
        _note(request.url.host, request.headers.get("Content-Length"), m.ConnectError, request=request)
        return await async_plain(self, request, *a, **k)
    send._netlog = True
    m.Client.send, m.AsyncClient.send = send, asend


def _watch_requests(m: Any) -> None:
    if getattr(m.Session.send, "_netlog", False):
        return
    plain = m.Session.send

    def send(self, request, **k):
        from urllib.parse import urlsplit
        _note(urlsplit(request.url or "").hostname, request.headers.get("Content-Length"), m.ConnectionError, request=request)
        return plain(self, request, **k)
    send._netlog = True
    m.Session.send = send


def _watch() -> None:
    import importlib
    for name, how in (("httpx2", _watch_httpx), ("httpx", _watch_httpx), ("requests", _watch_requests)):
        try:
            how(importlib.import_module(name))
        except ImportError:
            pass
        except AttributeError as e:                      # (a new version of it: lookups are still counted and held back)
            print(f"[privacy] {name}: {e}")


def install() -> None:
    """Start listening (once per run; before anything goes online)."""
    global _ON, _HOOKED, _LOCAL
    from . import schedule
    _LOCAL = schedule.get_setting("local_only") is True
    if not _HOOKED:
        sys.addaudithook(_hook)
        _HOOKED = True
    _watch()
    _ON = True


def local_only() -> bool:
    return _LOCAL and _ON


def set_local_only(on: bool) -> None:
    global _LOCAL
    from . import providers, schedule
    _LOCAL = on is True
    schedule.set_setting("local_only", _LOCAL)
    providers._net.update(at=0.0)                        # "is there internet?" is asked again


# ---------------- keeping it ----------------
def kept_days() -> int:
    from . import schedule
    n = schedule.get_setting("net_log_days")
    return n if n in KEEP else 30


def on() -> bool:
    from . import schedule
    return schedule.get_setting("net_log", True) is not False


def flush() -> int:
    """Write what was counted since last time. Never raises."""
    from . import storage
    with _FLUSH:
        rows: dict[tuple[str, str], list] = {}
        n = 0
        while n < 20000:
            try:
                what, host, size, at = _QUEUE.get_nowait()
            except queue.Empty:
                break
            n += 1
            r = rows.setdefault((time.strftime("%Y-%m-%d", time.localtime(at)), host), [0, 0, 0, 0, ""])
            r[{"yes": 0, "sent": 1, "no": 3}[what]] += 1
            r[2] += size
            r[4] = time.strftime("%H:%M:%S", time.localtime(at))
        if not rows or not on():
            return 0
        try:
            with storage._LOCK:
                c = storage.conn()
                with c:
                    c.executemany("INSERT INTO net_log(day, host, opened, sent, bytes, refused, last) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(day, host) DO UPDATE SET "
                                  "opened = opened + excluded.opened, sent = sent + excluded.sent, bytes = bytes + excluded.bytes, refused = refused + excluded.refused, last = excluded.last",
                                  [(day, host, *r) for (day, host), r in rows.items()])
        except sqlite3.Error as e:
            print(f"[privacy] couldn't keep the list of what goes out: {e}")
        return len(rows)


def clear() -> int:
    from . import storage
    flush()
    with storage._LOCK:
        c = storage.conn()
        with c:
            return c.execute("DELETE FROM net_log").rowcount


def tidy(today: date | None = None) -> int:
    from . import storage
    before = ((today or date.today()) - timedelta(days=kept_days())).isoformat()
    with storage._LOCK:
        c = storage.conn()
        with c:
            return c.execute("DELETE FROM net_log WHERE day < ?", (before,)).rowcount


def report(days: int = 1, today: date | None = None) -> dict:
    """What went out in the last days (1 = today), by service, and how much per day for the last 14."""
    from . import storage
    flush()
    today = today or date.today()
    days = days if days in (1, 7, 30) else 1
    since = (today - timedelta(days=days - 1)).isoformat()
    with storage._LOCK:
        c = storage.conn()
        rows = c.execute("SELECT host, SUM(opened), SUM(sent), SUM(bytes), SUM(refused), MAX(day || ' ' || last) FROM net_log WHERE day >= ? GROUP BY host", (since,)).fetchall()
        per = dict((d, (n, no)) for d, n, no in c.execute("SELECT day, SUM(MAX(opened, sent)), SUM(refused) FROM net_log WHERE day >= ? GROUP BY day", ((today - timedelta(days=13)).isoformat(),)))
    got: dict[str, dict] = {}
    for host, opened, sent, size, refused, last in rows:
        name, kind, what, off = service(host)
        s = got.setdefault(name, {"name": name, "kind": kind, "what": what, "off": off, "n": 0, "bytes": 0, "refused": 0, "last": "", "hosts": []})
        n = max(opened, sent)                                    # several messages over one connection, or one connection each
        s["n"] += n
        s["bytes"] += size
        s["refused"] += refused
        s["last"] = max(s["last"], last or "")
        s["hosts"].append({"host": host, "n": n, "refused": refused})
    for s in got.values():
        s["hosts"] = sorted(s["hosts"], key=lambda h: (-h["n"], -h["refused"], h["host"]))[:40]
    order = list(KINDS)
    services = sorted(got.values(), key=lambda s: (order.index(s["kind"]), -s["n"], s["name"]))
    line = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    return {"days": days, "services": services, "kinds": KINDS, "total": sum(s["n"] for s in services), "refused": sum(s["refused"] for s in services),
            "line": [{"day": d, "n": per.get(d, (0, 0))[0], "refused": per.get(d, (0, 0))[1]} for d in line],
            "local_only": local_only(), "on": on(), "keep": kept_days()}

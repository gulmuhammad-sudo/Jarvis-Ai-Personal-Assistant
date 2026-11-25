"""Your own connections to other services and devices: the assistant can send a text there (and only a text, only where you said).

You make a connection once, with its address and its secrets (locked for this Windows account in access.dat, never shown again,
never given to the AI). The AI knows its name and what it is for; it can't see or change the address. Every sending asks you
with the whole text. Only HTTPS, except for devices in your home network; the answer isn't followed anywhere else.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
import time
from typing import Any
from urllib.parse import quote, urlsplit

from . import access

MAX_TEXT, TIMEOUT, MAX_ANSWER = 2000, 15, 20_000

# kind: name, what to fill in [(field, label, secret)], help
KINDS: dict[str, dict[str, Any]] = {
    "ntfy": {"name": "ntfy (a notice on your phone)", "fields": [("topic", "Topic (a long name nobody guesses)", True), ("server", "Server (not needed: ntfy.sh)", False)],
             "help": "Free, no account: install the ntfy app on the phone and subscribe to the same topic. Anyone who knows the topic can read it."},
    "homeassistant": {"name": "Home Assistant", "fields": [("server", "Address, like http://192.168.1.20:8123", False), ("token", "Long-lived access token", True), ("service", "Service, like light.turn_on", False), ("entity", "Entity, like light.room (not needed)", False)],
                      "help": "Calls one service of your own Home Assistant. The text is sent as 'message' only for notify services."},
    "telegram": {"name": "Telegram (your own bot)", "fields": [("token", "Bot token from @BotFather", True), ("chat", "Chat id", False)], "help": "Free: make a bot with @BotFather, write to it once, then use your chat id."},
    "discord": {"name": "Discord (webhook)", "fields": [("url", "Webhook address", True)], "help": "Channel settings, Integrations, Webhooks."},
    "slack": {"name": "Slack (webhook)", "fields": [("url", "Webhook address", True)], "help": "An incoming webhook of your workspace."},
    "web": {"name": "Any address", "fields": [("url", "Address (https://…, or http:// in your home network)", True), ("method", "POST, PUT or GET", False), ("header", "One header, like Authorization: Bearer … (not needed)", True), ("body", "Body; {text} becomes the text (not needed)", False)],
            "help": "For IFTTT, Make, Zapier, a device, your own server."},
}


class ConnError(ValueError):
    """Something to tell the owner, in plain words."""


def _text(v: Any, most: int = 1000) -> str:
    t = str(v or "").strip()
    if len(t) > most or re.search(r"[\x00-\x1f\x7f]", t):
        raise ConnError("That is too long, or has signs that don't belong there.")
    return t


def private_host(host: str) -> bool:
    h = host.strip("[]").lower()
    try:
        ipaddress.ip_address(h)
        from . import remote
        return remote.home_ip(h)
    except ValueError:
        return h == "localhost" or h.endswith((".local", ".lan", ".home.arpa")) or "." not in h


def check_url(url: Any) -> str:
    u = _text(url, 2000)
    p = urlsplit(u)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password or not u.isascii() or " " in u or "\\" in u:
        raise ConnError("That isn't a web address (https://…).")
    if p.scheme == "http" and not private_host(p.hostname):
        raise ConnError("Only https:// (http:// only for devices in your own network).")
    try:
        _ = p.port
    except ValueError:
        raise ConnError("That isn't a web address (https://…).") from None
    from . import hud, remote
    if private_host(p.hostname) and (p.port in (hud.PORT, remote.settings()["port"])) and (p.hostname in ("localhost", "127.0.0.1") or p.hostname in remote.addresses()):
        raise ConnError("Not to the app itself.")
    return u


def _clean(kind: str, values: dict) -> dict:
    v = {f: _text(values.get(f), 2000 if f == "body" else 1000) for f, _, _ in KINDS[kind]["fields"]}
    if kind == "ntfy":
        if not re.fullmatch(r"[A-Za-z0-9_\-]{6,64}", v["topic"]):
            raise ConnError("The topic: 6 to 64 letters, numbers, - or _.")
        v["server"] = check_url(v["server"] if "://" in v["server"] else f"https://{v['server'] or 'ntfy.sh'}").rstrip("/")
    elif kind == "homeassistant":
        v["server"] = check_url(v["server"]).rstrip("/")
        if not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", v["service"]) or v["entity"] and not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", v["entity"]) or not v["token"]:
            raise ConnError("It needs the token and a service like light.turn_on.")
    elif kind == "telegram":
        if not re.fullmatch(r"\d{6,12}:[A-Za-z0-9_\-]{30,50}", v["token"]) or not re.fullmatch(r"-?\d{1,20}|@\w{3,40}", v["chat"]):
            raise ConnError("It needs the bot token and a chat id (a number).")
    elif kind in ("discord", "slack"):
        u = check_url(v["url"])
        host = urlsplit(u).hostname
        if urlsplit(u).scheme != "https" or host not in (("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com") if kind == "discord" else ("hooks.slack.com",)):
            raise ConnError("That isn't a webhook address of " + ("Discord." if kind == "discord" else "Slack."))
    else:
        check_url(v["url"].replace("{text}", "x"))
        if "{text}" in v["url"].split("?", 1)[0]:
            raise ConnError("{text} may only stand after the ? of the address.")
        v["method"] = (v["method"] or "POST").upper()
        if v["method"] not in ("POST", "PUT", "GET"):
            raise ConnError("POST, PUT or GET.")
        if v["header"] and not re.fullmatch(r"[A-Za-z0-9\-]{1,60}:\s?\S.*", v["header"]):
            raise ConnError("A header looks like this: Authorization: Bearer …")
        if v["header"] and v["header"].split(":", 1)[0].lower() in ("host", "content-length", "transfer-encoding", "connection"):
            raise ConnError("That header isn't allowed.")
        if v["body"].lstrip().startswith(("{", "[")):
            try:
                json.loads(v["body"].replace("{text}", "x"))
            except ValueError:
                raise ConnError("The body looks like JSON but isn't.") from None
    return v


def save(kind: Any, name: Any, about: Any, values: Any, i: Any = None) -> str:
    from . import audit
    if kind not in KINDS or not isinstance(values, dict):
        raise ConnError("Choose one of the kinds.")
    n = access.name_of(name, "")
    if not n:
        raise ConnError("Give it a name.")
    have = access.connections()
    if i and i not in have:
        raise ConnError("That connection isn't there any more.")
    if any(c["name"].lower() == n.lower() and k != i for k, c in have.items()):
        raise ConnError("There is already a connection with that name.")
    if not i and len(have) >= access.MAX_CONNECTIONS:
        raise ConnError("That is enough connections. Remove one first.")
    old = have.get(i, {}).get("values", {}) if i and have[i]["kind"] == kind else {}
    secret = {f for f, _, s in KINDS[kind]["fields"] if s}
    v = _clean(kind, {f: (values.get(f) or old.get(f, "")) if f in secret else values.get(f) for f, _, _ in KINDS[kind]["fields"]})
    if old and any(old.get(f) and v.get(f) == old[f] for f in secret) and _where(kind, v) != _where(kind, old):
        raise ConnError("The address changed, so type the secret again.")      # (a kept secret never goes to another address)
    i = str(i or secrets.token_hex(6))
    access.save_connection(i, {"kind": kind, "name": n, "about": access.name_of(about, "")[:120], "values": v, "on": have.get(i, {}).get("on", True), "used": have.get(i, {}).get("used", ""), "last": have.get(i, {}).get("last", "")})
    audit.record("connection_saved", name=n, kind=kind, host=_where(kind, v))
    return i


def _where(kind: str, v: dict) -> str:
    u = {"ntfy": v.get("server"), "homeassistant": v.get("server"), "telegram": "https://api.telegram.org"}.get(kind) or v.get("url") or ""
    p = urlsplit(u)
    return (p.hostname or "") + (f":{p.port}" if p.port else "")


def listing() -> list[dict]:
    """For the page: never a secret."""
    out = []
    for i, c in access.connections().items():
        out.append({"id": i, "kind": c["kind"], "name": c["name"], "about": c["about"], "on": c["on"], "used": c["used"], "last": c["last"], "host": _where(c["kind"], c["values"]),
                    "values": {f: ("" if s else c["values"].get(f, "")) for f, _, s in KINDS[c["kind"]]["fields"]}})
    return sorted(out, key=lambda c: c["name"].lower())


def kinds() -> list[dict]:
    return [{"id": k, "name": v["name"], "help": v["help"], "fields": [{"id": f, "label": lab, "secret": s} for f, lab, s in v["fields"]]} for k, v in KINDS.items()]


def set_on(i: Any, on: bool) -> None:
    c = access.connections().get(str(i))
    if not c:
        raise ConnError("That connection isn't there any more.")
    access.save_connection(str(i), {**c, "on": on is True})


def delete(i: Any) -> None:
    from . import audit
    c = access.connections().get(str(i))
    if c:
        access.save_connection(str(i), None)
        audit.record("connection_removed", name=c["name"])


def find(name: Any) -> tuple[str, dict] | None:
    n = str(name or "").strip().lower()
    have = {k: c for k, c in access.connections().items() if c["on"]}
    exact = [(k, c) for k, c in have.items() if c["name"].lower() == n]
    part = [(k, c) for k, c in have.items() if n and n in c["name"].lower()]
    return exact[0] if exact else part[0] if len(part) == 1 else None


def _request(c: dict, text: str) -> tuple[str, str, dict[str, str], bytes]:
    """(method, address, headers, body)"""
    k, v = c["kind"], c["values"]
    js = {"Content-Type": "application/json; charset=utf-8"}
    if k == "ntfy":
        return "POST", f"{v['server']}/{v['topic']}", {"Content-Type": "text/plain; charset=utf-8"}, text.encode("utf-8")
    if k == "telegram":
        return "POST", f"https://api.telegram.org/bot{v['token']}/sendMessage", js, json.dumps({"chat_id": v["chat"], "text": text}).encode()
    if k == "discord":
        return "POST", v["url"], js, json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    if k == "slack":
        return "POST", v["url"], js, json.dumps({"text": text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")}).encode()
    if k == "homeassistant":
        d, s = v["service"].split(".", 1)
        body: dict[str, Any] = {"entity_id": v["entity"]} if v["entity"] else {}
        if d == "notify":
            body["message"] = text
        return "POST", f"{v['server']}/api/services/{d}/{s}", {**js, "Authorization": f"Bearer {v['token']}"}, json.dumps(body).encode()
    url = v["url"].replace("{text}", quote(text, safe=""))
    head: dict[str, str] = {}
    if v["header"]:
        n, _, val = v["header"].partition(":")
        head[n.strip()] = val.strip()
    raw = v["body"]
    if v["method"] == "GET":
        return "GET", url, head, b""
    if raw.lstrip().startswith(("{", "[")):
        return v["method"], url, {**js, **head}, raw.replace("{text}", json.dumps(text)[1:-1]).encode("utf-8")
    return v["method"], url, {"Content-Type": "text/plain; charset=utf-8", **head}, (raw.replace("{text}", text) if raw else text).encode("utf-8")


def send(i: Any, text: Any) -> str:
    """Send it. The answer's number only (what it says isn't given on)."""
    from . import audit, netlog
    c = access.connections().get(str(i))
    if not c:
        raise ConnError("That connection isn't there any more.")
    t = str(text or "").strip()
    if not t and c["kind"] != "homeassistant" or len(t) > MAX_TEXT:
        raise ConnError(f"The text has to be 1 to {MAX_TEXT} letters.")
    method, url, head, body = _request(c, t)
    p = urlsplit(url)
    if netlog.local_only() and not netlog.is_here(p.hostname):
        raise ConnError("Local only is on (Privacy): nothing goes out.")
    status = 0
    try:
        cls = http.client.HTTPSConnection if p.scheme == "https" else http.client.HTTPConnection
        kw = {"context": ssl.create_default_context()} if p.scheme == "https" else {}
        con = cls(p.hostname, p.port, timeout=TIMEOUT, **kw)
        try:
            con.request(method, (p.path or "/") + (f"?{p.query}" if p.query else ""), body=body, headers={"User-Agent": "PersonalAssistant", "Accept": "*/*", **head})
            r = con.getresponse()                        # (http.client follows nothing)
            status = r.status
            r.read(MAX_ANSWER)
        finally:
            con.close()
        said = f"Sent ({status})." if 200 <= status < 300 else f"It answered with {status}" + (": a wrong secret or no permission." if status in (401, 403) else ": it has moved; use its new address." if 300 <= status < 400 else ": the address isn't there." if status == 404 else ": too many, wait a little." if status == 429 else ".")
    except (OSError, http.client.HTTPException, ssl.SSLError, socket.timeout) as e:
        said = f"It couldn't be reached ({type(e).__name__})."
    c = access.connections().get(str(i))
    if c:
        access.save_connection(str(i), {**c, "used": time.strftime("%Y-%m-%dT%H:%M:%S"), "last": said})
    audit.record("connection_used", name=c["name"] if c else "", host=_where(c["kind"], c["values"]) if c else "", answer=status)
    if not 200 <= status < 300:
        raise ConnError(said)
    return said

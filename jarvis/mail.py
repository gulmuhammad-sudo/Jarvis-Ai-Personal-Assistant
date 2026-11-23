"""Your Gmail: read it and keep drafts (Phase 7, part 4). Nothing is ever sent, deleted, moved or marked as read.

That is held in code, not in instructions: the connection below (_ReadOnly) refuses every mail command except looking, and adding a
message to the Drafts folder; mailboxes are only opened read-only; there is no sending (SMTP) in the app at all.

You sign in with an app password (16 letters Google makes for one app; needs 2-Step Verification). It is kept encrypted for your Windows
account in mail.dat (DPAPI, like the AI keys), is never put in the environment, logged or shown, and goes nowhere but imap.gmail.com.

What an email says is someone else's text: it is shown as plain text (no pictures, so senders can't see that you opened it), hidden text
is left out, and the AI gets it marked as data. After the AI has seen an email it asks before it goes online (tools.execute, after_email).
"""
from __future__ import annotations

import imaplib
import json
import os
import re
import ssl
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from . import guard

HOST, PORT = "imap.gmail.com", 993
TIMEOUT = 20
IDLE = 60                                   # seconds a connection is kept for the next click
MAX_BYTES = 3 * 2**20                       # of one email
MAX_TEXT = 100_000
MAX_LIST = 50
MAX_TO = 10
MAX_BODY = 50_000
TAINT_FOR = 30 * 60                         # after the AI saw an email, going online asks for this long (or until a new conversation)
_ENTROPY = b"Personal Assistant mail v1"
_LOCK = threading.RLock()
_CONN: dict = {"c": None, "at": 0.0, "special": None}
_TIMER: threading.Timer | None = None
_SEEN_AT = 0.0


class MailError(ValueError):
    """Something to tell the user, in plain words."""


# ---------------- the account ----------------
def _file() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "mail.dat"


def _load() -> dict:
    try:
        import win32crypt
        d = json.loads(win32crypt.CryptUnprotectData(_file().read_bytes(), _ENTROPY, None, None, 0)[1].decode("utf-8"))
        return d if isinstance(d, dict) and d.get("address") and d.get("password") else {}
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"[mail] couldn't read the saved sign-in ({type(e).__name__}); was it made by another Windows account?")
        return {}


def _save(address: str, password: str) -> None:
    import win32crypt
    blob = win32crypt.CryptProtectData(json.dumps({"address": address, "password": password}).encode("utf-8"), "Personal Assistant mail", _ENTROPY, None, None, 0)
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(blob)
    os.replace(tmp, p)
    if _load() != {"address": address, "password": password}:
        raise MailError("The sign-in couldn't be saved on this PC.")


def account() -> dict:
    d = _load()
    return {"connected": bool(d), "address": d.get("address", "")}


_ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")


def connect(address: Any, password: Any) -> dict:
    """Try the sign-in and, if Google accepts it, keep it (encrypted)."""
    address = str(address or "").strip().lower()
    secret = re.sub(r"\s+", "", str(password or ""))
    if not _ADDRESS.fullmatch(address):
        raise MailError("That isn't an email address.")
    if not re.fullmatch(r"[A-Za-z]{16}", secret):
        raise MailError("That isn't an app password: it has 16 letters, like abcd efgh ijkl mnop. Never type your normal Google password here.")
    secret = secret.lower()
    with _LOCK:
        close()
        c = _login(address, secret)
        try:
            c.select("INBOX", readonly=True)
        finally:
            _bye(c)
        _save(address, secret)
    return account()


def disconnect() -> None:
    """Forget the sign-in. (The app password itself is taken back at myaccount.google.com/apppasswords.)"""
    with _LOCK:
        close()
        clear_seen()
        try:
            _file().unlink()
        except FileNotFoundError:
            pass


# ---------------- a connection that can only look ----------------
class _Guarded:
    """Mixed into imaplib's classes: whatever calls it, only these commands leave the PC."""
    ALLOWED = {"CAPABILITY", "LOGIN", "EXAMINE", "LIST", "NOOP", "LOGOUT", "UID", "APPEND", "CLOSE", "UNSELECT"}
    drafts: str | None = None

    def _command(self, name, *args):
        up = str(name).upper()
        if up not in self.ALLOWED:
            raise MailError(f"The app never does that with your email ({up}).")
        first = args[0].decode("ascii", "replace") if args and isinstance(args[0], bytes) else str(args[0]) if args else ""
        if up == "UID" and first.upper() not in ("FETCH", "SEARCH"):
            raise MailError(f"The app never does that with your email (UID {first.upper()}).")
        if up == "APPEND" and (self.drafts is None or first != self.drafts):
            raise MailError("The app only adds to the Drafts folder.")
        return super()._command(name, *args)


class _ReadOnly(_Guarded, imaplib.IMAP4_SSL):
    pass


class _ReadOnlyPlain(_Guarded, imaplib.IMAP4):      # only for tests against a server on this PC
    pass


def _test_server() -> tuple[str, int] | None:
    """Tests only: a pretend server on this PC, and only with a throw-away data folder."""
    m = re.fullmatch(r"127\.0\.0\.1:(\d{2,5})", os.environ.get("JARVIS_MAIL_TEST", ""))
    return ("127.0.0.1", int(m.group(1))) if m and os.environ.get("JARVIS_DATA_DIR") else None


def _login(address: str, secret: str):
    try:
        t = _test_server()
        c = _ReadOnlyPlain(*t, timeout=TIMEOUT) if t else _ReadOnly(HOST, PORT, ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    except (OSError, imaplib.IMAP4.error) as e:
        raise MailError(f"Gmail can't be reached ({_why(e)}).") from None
    try:
        c.login(address, secret)
    except (imaplib.IMAP4.error, OSError) as e:
        _bye(c)
        if isinstance(e, OSError):
            raise MailError(f"Gmail can't be reached ({_why(e)}).") from None
        raise MailError("Google didn't accept that address and app password. Make a new app password at myaccount.google.com/apppasswords "
                        "(2-Step Verification must be on) and try again.") from None
    return c


def _why(e: BaseException) -> str:
    return "no internet connection" if "getaddrinfo" in str(e) or "11001" in str(e) else "it took too long" if isinstance(e, TimeoutError) else type(e).__name__


def _bye(c) -> None:
    try:
        c.logout()
    except Exception:
        pass


def close() -> None:
    """End the kept connection."""
    global _TIMER
    with _LOCK:
        if _TIMER:
            _TIMER.cancel()
            _TIMER = None
        c, _CONN["c"], _CONN["special"] = _CONN["c"], None, None
    if c:
        _bye(c)


@contextmanager
def _open():
    """The signed-in connection: one at a time, kept for a minute."""
    global _TIMER
    with _LOCK:
        d = _load()
        if not d:
            raise MailError("Gmail isn't connected yet: Planner page, Email.")
        c = _CONN["c"]
        if c is not None:
            try:
                if time.time() - _CONN["at"] > IDLE or c.noop()[0] != "OK":
                    raise OSError
            except Exception:
                close()
                c = None
        if c is None:
            c = _CONN["c"] = _login(d["address"], d["password"])
        try:
            yield c, d["address"]
        except MailError:
            raise
        except (imaplib.IMAP4.error, OSError, EOFError) as e:
            close()
            raise MailError(f"Gmail didn't answer properly ({_why(e)}). Try again.") from None
        finally:
            _CONN["at"] = time.time()
            if _TIMER:
                _TIMER.cancel()
            if _CONN["c"] is not None:
                _TIMER = threading.Timer(IDLE, close)
                _TIMER.daemon = True
                _TIMER.start()


def _special(c) -> dict[str, str]:
    """The names of All Mail and Drafts (they depend on your Gmail's language)."""
    if _CONN["special"] is None:
        found = {}
        for line in c.list()[1] or []:
            m = re.match(rb'\(([^)]*)\) (?:"[^"]*"|NIL) ("(?:[^"\\]|\\.)*"|[^ ]+)$', line if isinstance(line, bytes) else b"")
            if m:
                for flag in (b"\\All", b"\\Drafts"):
                    if flag.lower() in m.group(1).lower().split():
                        found[flag[1:].decode()] = m.group(2).decode("ascii", "replace")
        _CONN["special"] = found
    return _CONN["special"]


def _look(c, box: str) -> None:
    name = "INBOX" if box == "I" else _special(c).get("All", "INBOX")
    ok, data = c.select(name, readonly=True)
    if ok != "OK":
        raise MailError("That mail folder can't be opened.")


# ---------------- making text safe to show ----------------
_INVISIBLE = re.compile("[­͏؜ᅟᅠ឴឵᠎​‎‏⁠-⁤⁪-⁯﻿‪-‮⁦-⁩\U000e0000-\U000e007f]")


def clean(text: Any, one_line: bool = False) -> str:
    """Without invisible characters (used to hide words from you, or to turn file names around) and control codes."""
    s = _INVISIBLE.sub("", str(text or ""))
    s = "".join(ch for ch in s if ch in "\n\t" or ord(ch) >= 32 and not 127 <= ord(ch) < 160)
    return " ".join(s.split()) if one_line else s


class _Text(HTMLParser):
    """HTML email -> the text a person sees, and its links. Nothing is loaded."""
    BLOCK = {"p", "div", "tr", "table", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote", "pre", "hr"}
    VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
    DROP = {"script", "style", "head", "title", "template", "noscript", "svg", "object", "iframe", "select", "textarea"}
    HIDDEN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d]*[1-9])|opacity\s*:\s*0(?![.\d]*[1-9])|max-height\s*:\s*0(?![.\d]*[1-9])|mso-hide\s*:\s*all", re.I)

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.stack: list[tuple[str, bool]] = []       # open tags; True = hidden from here on
        self.href: str | None = None
        self.words: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.BLOCK or tag == "br":
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")
        if tag in ("td", "th"):
            self.out.append(" ")
        if tag in self.VOID:
            return
        hidden = bool(self.stack and self.stack[-1][1]) or tag in self.DROP or "hidden" in a or bool(self.HIDDEN.search(a.get("style") or ""))
        if len(self.stack) < 500:
            self.stack.append((tag, hidden))
        if tag == "a" and not hidden and re.match(r"https?://", (a.get("href") or "").strip(), re.I):
            self.href, self.words = a["href"].strip(), []

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join("".join(self.words).split())))
            self.href = None
        if any(t == tag for t, _ in self.stack):
            while self.stack:
                if self.stack.pop()[0] == tag:
                    break
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not (self.stack and self.stack[-1][1]):
            self.out.append(re.sub(r"\s+", " ", data))
            if self.href:
                self.words.append(data)


def html_text(html: str) -> tuple[str, list[tuple[str, str]]]:
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception as e:
        print(f"[mail] odd HTML: {type(e).__name__}")
    text = re.sub(r" *\n *", "\n", "".join(p.out))
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", text)).strip(), p.links


def _host(url: str) -> str:
    m = re.match(r"https?://(?:[^/?#@]*@)?([^/?#:]+)", url, re.I)
    return m.group(1).lower().strip(".") if m else ""


def _base(host: str) -> str:
    """example.co.uk and mail.example.co.uk belong together (near enough for a warning)."""
    parts = host.lower().split(".")
    n = 3 if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "net", "org", "gov", "edu", "ac") else 2
    return ".".join(parts[-n:])


# ---------------- reading ----------------
def _header(msg, name: str) -> str:
    try:
        return clean(msg[name], True)[:500] if msg[name] is not None else ""
    except Exception:                               # a broken header mustn't hide the email
        return ""


def _people(value: str) -> list[tuple[str, str]]:
    return [(clean(n, True), clean(a, True).lower()) for n, a in getaddresses([value]) if a]


def _when(msg, internal: bytes) -> str:
    try:
        d = parsedate_to_datetime(str(msg["Date"])).astimezone()
        return d.strftime("%Y-%m-%dT%H:%M")
    except Exception:
        m = re.search(rb'INTERNALDATE "([^"]+)"', internal)
        try:
            return datetime.strptime(m.group(1).decode().strip(), "%d-%b-%Y %H:%M:%S %z").astimezone().strftime("%Y-%m-%dT%H:%M")
        except Exception:
            return ""


def _card(msg, meta: bytes, box: str) -> dict:
    uid = re.search(rb"\bUID (\d+)", meta)
    who = _people(_header(msg, "From")) or [("", "")]
    size = re.search(rb"RFC822\.SIZE (\d+)", meta)
    return {"id": f"{box}{uid.group(1).decode()}" if uid else "", "name": who[0][0] or who[0][1], "address": who[0][1], "to": ", ".join(a for _, a in _people(_header(msg, "To")))[:300],
            "subject": _header(msg, "Subject") or "(no subject)", "at": _when(msg, meta), "unread": b"\\seen" not in meta.lower(), "size": int(size.group(1)) if size else 0}


def _responses(data) -> list[tuple[bytes, bytes]]:
    """(everything about it, its text) of each message in a FETCH answer."""
    out, extra = [], b""
    for item in data or []:
        if isinstance(item, tuple):
            out.append([item[0], item[1]])
        elif isinstance(item, bytes) and out:
            out[-1][0] += b" " + item
        elif isinstance(item, bytes):
            extra += item
    return [(a, b) for a, b in out]


def listing(query: str = "", unread: bool = False, limit: int = 20) -> list[dict]:
    """The newest emails of the inbox; with a query (Gmail's own search words), of all mail."""
    query = clean(query, True)[:300]
    limit = max(1, min(int(limit), MAX_LIST))
    with _open() as (c, _):
        box = "A" if query else "I"
        _look(c, box)
        if query:
            c.literal = (query + (" is:unread" if unread else "")).encode("utf-8")      # sent as a counted block: nothing in it can become a command
            ok, data = c.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
        else:
            ok, data = c.uid("SEARCH", None, "UNSEEN" if unread else "ALL")
        if ok != "OK":
            raise MailError("Gmail couldn't search for that.")
        uids = sorted({int(u) for u in (data[0] or b"").split() if u.isdigit()}, reverse=True)[:limit]
        if not uids:
            return []
        ok, data = c.uid("FETCH", ",".join(map(str, uids)), "(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])")
        if ok != "OK":
            raise MailError("Gmail didn't give the list.")
        rows = [_card(message_from_bytes(raw, policy=policy.default), meta, box) for meta, raw in _responses(data)]
    return sorted((r for r in rows if r["id"]), key=lambda r: int(r["id"][1:]), reverse=True)


def _split(mail_id: Any) -> tuple[str, int]:
    m = re.fullmatch(r"([IA])(\d{1,10})", str(mail_id or "").strip().lstrip("#").upper())
    if not m:
        raise MailError("I don't know that email; list them first.")
    return m.group(1), int(m.group(2))


def read(mail_id: Any) -> dict:
    """One email as text, with warnings. It stays unread."""
    box, uid = _split(mail_id)
    with _open() as (c, me):
        _look(c, box)
        ok, data = c.uid("FETCH", str(uid), f"(UID FLAGS INTERNALDATE RFC822.SIZE BODY.PEEK[]<0.{MAX_BYTES}>)")
        found = _responses(data) if ok == "OK" else []
        if not found:
            raise MailError("That email isn't there any more.")
    meta, raw = found[0]
    msg = message_from_bytes(raw, policy=policy.default)
    card = _card(msg, meta, box)
    plain, html, files = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        kind = part.get_content_type()
        try:
            name = part.get_filename()
        except Exception:
            name = "attachment"
        if name or part.get_content_disposition() == "attachment" or kind not in ("text/plain", "text/html"):
            if name or part.get_content_disposition() == "attachment":
                body = part.get_payload(decode=True) or b""
                files.append({"name": clean(name or "attachment", True)[:120], "kind": kind, "size": len(body)})
            continue
        try:
            text = part.get_content()
        except Exception:                           # an unknown or wrong character set
            text = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        (html if kind == "text/html" else plain).append(str(text))
    links: list[tuple[str, str]] = []
    if html:
        seen = [html_text(h) for h in html]
        links = [x for _, ls in seen for x in ls]
    text = "\n\n".join(plain).strip() if "".join(plain).strip() else "\n\n".join(t for t, _ in seen) if html else ""
    text = clean(text.replace("\r\n", "\n").replace("\r", "\n")).strip()
    cut = len(text) > MAX_TEXT or card["size"] > MAX_BYTES
    hosts = list(dict.fromkeys(h for h in [*(_host(u) for u, _ in links), *(_host(u) for u in re.findall(r"https?://[^\s<>\"')\]]+", text))] if h))
    return {**card, "cc": ", ".join(a for _, a in _people(_header(msg, "Cc")))[:300], "text": text[:MAX_TEXT], "cut": cut, "files": files[:30], "hosts": hosts[:15],
            "warnings": warnings(msg, card, links, files, me), "reply_to": ((_people(_header(msg, "Reply-To")) or _people(_header(msg, "From")) or [("", "")])[0][1]),
            "message_id": _header(msg, "Message-ID"), "references": _header(msg, "References")}


def warnings(msg, card: dict, links: list[tuple[str, str]], files: list[dict], me: str = "") -> list[str]:
    """Signs of a trick, in plain words."""
    out = []
    domain = card["address"].rpartition("@")[2]
    results = msg.get_all("Authentication-Results") or []
    top = clean(results[0], True).lower() if results else ""      # only the first one is Google's; a sender can write more below it
    if top.startswith("mx.google.com"):
        got = {k: (re.search(rf"\b{k}=(\w+)", top) or [None, ""])[1] for k in ("dmarc", "dkim", "spf")}
        if got["dmarc"] == "fail" or (got["dmarc"] != "pass" and "pass" not in (got["dkim"], got["spf"])):
            out.append(f"Google couldn't confirm that this really comes from {domain or 'its sender'}.")
    inner = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", card["name"])
    if inner and inner.group(0).lower() != card["address"]:
        out.append(f"It shows the name {inner.group(0)}, but it comes from {card['address']}.")
    back = _people(_header(msg, "Reply-To"))
    if back and card["address"] and _base(back[0][1].rpartition("@")[2]) != _base(domain):
        out.append(f"Answers would go to another address: {back[0][1]}.")
    for url, words in links:
        shown = re.search(r"\b((?:[a-z0-9-]+\.)+(?:com|net|org|pk|co|io|gov|edu|info|uk|bank|app))\b", words.lower())
        if shown and _host(url) and _base(shown.group(1)) != _base(_host(url)):
            out.append(f"A link shows {shown.group(1)} but goes to {_host(url)}.")
            break
    bad = [f["name"] for f in files if guard.runs_code(f["name"])]
    if bad:
        out.append(f"It carries a program: {', '.join(bad[:3])}.")
    return out


def for_ai(m: dict, limit: int = 20_000) -> str:
    lines = [f"Id {m['id']}, from {m['name']} <{m['address']}>, to {m['to']}, {m['at'].replace('T', ' ')}", f"Subject: {m['subject']}"]
    if m["warnings"]:
        lines.append("Warnings (tell the user): " + " ".join(m["warnings"]))
    if m["files"]:
        lines.append("Attachments (not opened): " + ", ".join(f["name"] for f in m["files"]))
    return "\n".join(lines) + "\n\n" + m["text"][:limit] + (" [...]" if len(m["text"]) > limit or m["cut"] else "")


# ---------------- drafts ----------------
def recipients(value: Any) -> list[tuple[str, str]]:
    raw = str(value or "")
    if "\n" in raw or "\r" in raw:
        raise MailError("An address can't have a line break.")
    got = [(clean(n, True), a.strip()) for n, a in getaddresses([raw.replace(";", ",")]) if n or a]
    bad = [a or n for n, a in got if not _ADDRESS.fullmatch(a)]
    if bad:
        raise MailError(f"That isn't an email address: {bad[0][:80]}")
    if len(got) > MAX_TO:
        raise MailError(f"Up to {MAX_TO} addresses.")
    return got


def compose(me: str, to: Any, subject: Any, body: Any, cc: Any = "", reply: dict | None = None) -> EmailMessage:
    people, copies = recipients(to), recipients(cc)
    if reply and not people:
        people = recipients(reply["reply_to"])
    subject = clean(subject, True)[:300]
    if reply and not subject:
        subject = reply["subject"] if re.match(r"re:", reply["subject"], re.I) else f"Re: {reply['subject']}"
    text = clean(str(body or "").replace("\r\n", "\n")).strip()
    if not text:
        raise MailError("The draft is empty.")
    if len(text) > MAX_BODY:
        raise MailError("That's too long for one email.")
    m = EmailMessage(policy=policy.SMTP)
    m["From"], m["Subject"], m["Date"] = me, subject, formatdate(localtime=True)
    if people:
        m["To"] = ", ".join(formataddr(p) for p in people)
    if copies:
        m["Cc"] = ", ".join(formataddr(p) for p in copies)
    m["Message-ID"] = make_msgid(domain=me.rpartition("@")[2])        # (the default would carry this PC's name)
    if reply and re.fullmatch(r"<[^<>\s]{3,250}>", reply["message_id"]):
        m["In-Reply-To"] = reply["message_id"]
        refs = re.findall(r"<[^<>\s]{3,250}>", reply["references"])[-10:]
        m["References"] = " ".join([*refs, reply["message_id"]])
    m.set_content(text)
    return m


def save_draft(to: Any, subject: Any, body: Any, cc: Any = "", reply_id: Any = "") -> dict:
    """Put a draft in Gmail's Drafts. You read it there and send it yourself."""
    reply = read(reply_id) if str(reply_id or "").strip() else None
    with _open() as (c, me):
        m = compose(me, to, subject, body, cc, reply)
        box = _special(c).get("Drafts")
        if not box:
            raise MailError("Gmail's Drafts folder isn't shown to other programs (Gmail settings › Labels › Drafts › Show in IMAP).")
        c.drafts = box
        try:
            ok, _ = c.append(box, r"(\Draft)", None, m.as_bytes())
        finally:
            c.drafts = None
        if ok != "OK":
            raise MailError("Gmail didn't take the draft.")
    return {"to": str(m["To"] or ""), "subject": str(m["Subject"])}


# ---------------- after the AI has seen an email ----------------
def seen_by_ai() -> None:
    global _SEEN_AT
    _SEEN_AT = time.monotonic()


def clear_seen() -> None:
    global _SEEN_AT
    _SEEN_AT = 0.0


def recently_seen() -> bool:
    return bool(_SEEN_AT) and time.monotonic() - _SEEN_AT < TAINT_FOR

"""News (Phase 8): topics, the owner's own sources (RSS / Atom), search, words to follow, and stories kept for later.

Free and without a key. Nothing is fetched until the News tab is opened, the assistant is asked, or the briefing runs.
Only feeds are read (never whole pages, no pictures); what they say is untrusted text. An address must be public: feeds
(and where they redirect to) on this PC or the home network are refused. Kept stories are in the local database.
"""
from __future__ import annotations

import calendar
import hashlib
import html
import ipaddress
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit

from . import schedule
from .planner import _db

MAX_BYTES = 3_000_000
MAX_STORIES = 60
MAX_FEEDS = 30
MAX_SAVED = 500
MAX_FOLLOW = 20
KEEP_SECONDS = 10 * 60
TIMEOUT = 10
TRIES = 2                           # a weak connection often works the second time

# Google News (its feeds are for personal reading); names the owner sees
TOPICS = {"top": "Top stories", "pakistan": "Pakistan", "world": "World", "business": "Business", "technology": "Technology", "science": "Science",
          "health": "Health", "sports": "Sports", "entertainment": "Entertainment"}
_SECTION = {"pakistan": "NATION"}
SOURCES = {"dawn": ("Dawn", "https://www.dawn.com/feeds/home"), "tribune": ("Express Tribune", "https://tribune.com.pk/feed/home"),
           "geo": ("Geo News", "https://www.geo.tv/rss/1/1"), "bbc_urdu": ("BBC اردو", "https://feeds.bbci.co.uk/urdu/rss.xml"),
           "bbc_world": ("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"), "ars": ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index"),
           "cricket": ("ESPNcricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml")}


def _google(path: str, **params: str) -> str:
    region = re.sub(r"[^A-Z]", "", (os.environ.get("JARVIS_NEWS_REGION") or "PK").upper())[:2] or "PK"
    return f"https://news.google.com/rss{path}?" + urlencode({**params, "hl": f"en-{region}", "gl": region, "ceid": f"{region}:en"})


# ---------------- fetching ----------------
def _public(url: str, any_port: bool = False) -> None:
    """Only ordinary web addresses out on the internet (not this PC, the router, or other machines at home)."""
    u = urlsplit(url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ValueError("That isn't a web address (https://…).")
    try:
        port = u.port
    except ValueError:
        port = 0
    if port not in (None, 80, 443) and not (any_port and port and port > 1023):
        raise ValueError("That address uses an unusual port.")
    try:
        found = {i[4][0] for i in socket.getaddrinfo(u.hostname, port or 443, type=socket.SOCK_STREAM)}
    except (OSError, UnicodeError):
        raise ConnectionError(f"{u.hostname} can't be reached. Is the internet on?") from None
    for a in found:
        ip = ipaddress.ip_address(a.split("%")[0])
        ip = (ip.ipv4_mapped or ip) if ip.version == 6 else ip
        if not ip.is_global or ip.is_multicast or ip.is_reserved:
            raise ValueError("That address is on this PC or your own network, not on the internet.")


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str) -> bytes:
    for left in range(TRIES - 1, -1, -1):
        try:
            return _once(url)
        except ConnectionError as e:
            if not left or "answered" in str(e):
                raise
    raise AssertionError


def _once(url: str) -> bytes:
    _public(url)
    req = urllib.request.Request(url, headers={**schedule.UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.5"})
    try:
        with urllib.request.build_opener(_Redirect).open(req, timeout=TIMEOUT) as r:
            raw = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise ConnectionError(f"The site answered with an error ({e.code}).") from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, ValueError):
            raise e.reason from None
        raise ConnectionError("The site can't be reached. Is the internet on?") from None
    except (OSError, TimeoutError):
        raise ConnectionError("The site took too long to answer.") from None
    if len(raw) > MAX_BYTES:
        raise ValueError("That feed is too large.")
    return raw


# ---------------- reading feeds ----------------
def clean(text: Any, limit: int) -> str:
    t = html.unescape(re.sub(r"(?s)<[^>]*>", " ", html.unescape(re.sub(r"(?is)<(script|style).*?</\1>", " ", str(text or "")))))
    t = re.sub(r"(?s)<[^>]*>", " ", t)
    t = re.sub(r"[\x00-\x1f\x7f​‎‏‪-‮⁠⁦-⁩﻿]+", " ", t)
    t = " ".join(t.split())
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def _when(text: str) -> str:
    """Its time here, as 2026-11-24T09:30 ('' if it doesn't say)."""
    t = (text or "").strip()
    d = None
    for read in (parsedate_to_datetime, lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))):
        try:
            d = read(t)
            break
        except (ValueError, TypeError, IndexError):
            pass
    if d is None:
        return ""
    try:
        d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
        return datetime.fromtimestamp(calendar.timegm(d.utctimetuple())).strftime("%Y-%m-%dT%H:%M")
    except (ValueError, OverflowError, OSError):
        return ""


def _link(value: Any, base: str) -> str:
    if not str(value or "").strip():
        return ""
    u = urljoin(base, str(value).strip())
    p = urlsplit(u)
    return u if p.scheme in ("http", "https") and p.hostname and not p.username and len(u) <= 2000 and not re.search(r"[\s\x00-\x1f\"<>]", u) else ""


def story_id(link: str) -> str:
    return hashlib.sha256(link.encode()).hexdigest()[:8]


def parse(raw: bytes, base: str, source: str = "") -> list[dict]:
    """The stories of an RSS or Atom feed, newest first."""
    if re.search(rb"(?i)<\0?!\0?E\0?N\0?T\0?I\0?T\0?Y", raw):          # (also as UTF-16)
        raise ValueError("That feed isn't in a form this app reads.")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, LookupError):
        raise ValueError("That address isn't a news feed (RSS or Atom).") from None
    name = lambda el: el.tag.rsplit("}", 1)[-1].lower() if isinstance(el.tag, str) else ""          # noqa: E731
    if name(root) not in ("rss", "feed", "rdf"):
        raise ValueError("That address isn't a news feed (RSS or Atom).")
    channel = next((clean(x.text, 60) for x in root.iter() if name(x) == "title" and x.text), "")
    out, seen = [], set()
    for el in root.iter():
        if name(el) not in ("item", "entry"):
            continue
        got: dict[str, str] = {}
        for c in el:
            n = name(c)
            if n == "link" and c.get("href"):
                if c.get("rel") in (None, "alternate") and "link" not in got:
                    got["link"] = c.get("href") or ""
            elif n in ("title", "link", "description", "summary", "content", "pubdate", "published", "updated", "date", "source", "guid") and n not in got:
                got[n] = "".join(c.itertext())
        link = _link(got.get("link") or (got.get("guid") if str(got.get("guid")).startswith("http") else ""), base)
        title, src = clean(got.get("title"), 220), clean(got.get("source"), 60)
        if src and title.endswith(f" - {src}"):                         # Google News adds the paper's name to the title
            title = title[:-len(src) - 3].rstrip()
        key = title.casefold()
        if not link or not title or key in seen:
            continue
        seen.add(key)
        about = clean(got.get("description") or got.get("summary") or got.get("content"), 320)
        if "news.google.com" in base or about.casefold().startswith(key):        # (Google's are only other papers' titles)
            about = ""
        out.append({"id": story_id(link), "title": title, "link": link, "source": src or source or channel, "about": about,
                    "at": _when(got.get("pubdate") or got.get("published") or got.get("updated") or got.get("date") or "")})
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    for s in out:
        if s["at"] > now:                                                # a clock that is wrong there
            s["at"] = now
    return sorted(out, key=lambda s: s["at"], reverse=True)[:MAX_STORIES]


_lock = threading.Lock()
_cache: dict[str, tuple[float, list[dict]]] = {}
_known: dict[str, dict] = {}                         # stories shown since the app started, by number


def _get(url: str, source: str = "", fresh: bool = False) -> dict:
    """The feed's stories: kept for ten minutes; if the site can't be reached, the last ones it gave."""
    with _lock:
        hit = _cache.get(url)
    if hit and not fresh and time.time() - hit[0] < KEEP_SECONDS:
        return {"stories": hit[1], "at": hit[0], "note": ""}
    try:
        rows = parse(_download(url), url, source)
    except ConnectionError as e:
        if not hit:
            raise ValueError(str(e)) from None
        return {"stories": hit[1], "at": hit[0], "note": f"{e} These are from {datetime.fromtimestamp(hit[0]):%H:%M}."}
    now = time.time()
    with _lock:
        if len(_cache) > 40:
            _cache.pop(min(_cache, key=lambda k: _cache[k][0]))
        _cache[url] = (now, rows)
        _known.update({s["id"]: s for s in rows})
        while len(_known) > 3000:
            _known.pop(next(iter(_known)))
    return {"stories": rows, "at": now, "note": ""}


# ---------------- what can be read ----------------
def feeds() -> list[dict]:
    c, lock = _db()
    with lock:
        return [{"id": r[0], "name": r[1], "url": r[2]} for r in c.execute("SELECT id, name, url FROM news_feeds ORDER BY id").fetchall()]


def add_feed(url: Any, name: Any = "") -> dict:
    u = str(url or "").strip()
    if not u:
        raise ValueError("Give the feed's address.")
    u = u if "://" in u else "https://" + u
    if len(u) > 500 or re.search(r"[\s\x00-\x1f\"<>]", u):
        raise ValueError("That isn't a web address (https://…).")
    if any(f["url"].casefold() == u.casefold() for f in feeds()) or any(u.casefold() == s[1].casefold() for s in SOURCES.values()):
        raise ValueError("That source is already there.")
    if len(feeds()) >= MAX_FEEDS:
        raise ValueError(f"That's {MAX_FEEDS} sources. Remove one first.")
    got = _get(u, fresh=True)["stories"]                                  # it must work
    if not got:
        raise ValueError("That feed has no stories.")
    name = clean(name, 40) or clean(got[0]["source"], 40) or urlsplit(u).hostname or u
    c, lock = _db()
    with lock, c:
        fid = c.execute("INSERT INTO news_feeds (name, url) VALUES (?, ?)", (name, u)).lastrowid
    return {"id": fid, "name": name, "url": u}


def remove_feed(feed_id: Any) -> bool:
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM news_feeds WHERE id = ?", (int(feed_id),)).rowcount > 0


def stories(where: Any = "top", fresh: bool = False) -> dict:
    """where: a topic, a built-in source, 'feed:3', 'q:words' or 'saved'."""
    w = str(where or "top").strip()
    key = w.casefold()
    if key == "saved":
        return {"stories": saved(), "at": time.time(), "note": ""}
    if key.startswith("q:"):
        return search(w[2:], fresh)
    if key.startswith("feed:"):
        f = next((f for f in feeds() if f"feed:{f['id']}" == key), None)
        if not f:
            raise ValueError("That source is gone.")
        return _mark(_get(f["url"], f["name"], fresh))
    if key in SOURCES:
        return _mark(_get(SOURCES[key][1], SOURCES[key][0], fresh))
    key = next((k for k, v in TOPICS.items() if key in (k, v.casefold())), None) or next((k for k in TOPICS if k.rstrip("s") == key.rstrip("s")), "")
    if not key:
        raise ValueError(f"I don't know that topic. There are: {', '.join(TOPICS)}.")
    return _mark(_get(_google("" if key == "top" else f"/headlines/section/topic/{_SECTION.get(key, key.upper())}"), fresh=fresh))


def search(words: Any, fresh: bool = False) -> dict:
    q = clean(words, 120)
    if len(q) < 2:
        raise ValueError("What should I look for?")
    return _mark(_get(_google("/search", q=q), fresh=fresh))


def _mark(got: dict) -> dict:
    have = {s["id"] for s in saved()}
    return {**got, "stories": [{**s, "saved": s["id"] in have} for s in got["stories"]]}


def story(sid: Any) -> dict | None:
    s = str(sid or "").strip().lower().lstrip("#")
    with _lock:
        hit = _known.get(s)
    return hit or next((x for x in saved() if x["id"] == s), None)


# ---------------- kept for later ----------------
_S = "link, title, source, about, at, read"


def saved() -> list[dict]:
    c, lock = _db()
    with lock:
        rows = c.execute(f"SELECT {_S} FROM news_saved ORDER BY saved DESC, rowid DESC").fetchall()
    return [{"id": story_id(r[0]), "link": r[0], "title": r[1], "source": r[2], "about": r[3], "at": r[4], "read": bool(r[5]), "saved": True} for r in rows]


def save(sid: Any) -> dict:
    s = story(sid)
    if not s:
        raise ValueError("That story isn't in the list any more.")
    c, lock = _db()
    with lock, c:
        if c.execute("SELECT count(*) FROM news_saved").fetchone()[0] >= MAX_SAVED:
            raise ValueError(f"That's {MAX_SAVED} stories. Remove some first.")
        c.execute("INSERT OR IGNORE INTO news_saved (link, title, source, about, at, saved) VALUES (?, ?, ?, ?, ?, ?)",
                  (s["link"], s["title"], s["source"], s["about"], s["at"], datetime.now().isoformat(timespec="seconds")))
    return s


def unsave(sid: Any) -> bool:
    s = next((x for x in saved() if x["id"] == str(sid)), None)
    if not s:
        return False
    c, lock = _db()
    with lock, c:
        return c.execute("DELETE FROM news_saved WHERE link = ?", (s["link"],)).rowcount > 0


def mark_read(sid: Any) -> None:
    s = next((x for x in saved() if x["id"] == str(sid)), None)
    if s:
        c, lock = _db()
        with lock, c:
            c.execute("UPDATE news_saved SET read = 1 WHERE link = ?", (s["link"],))


# ---------------- words to follow ----------------
def follows() -> list[str]:
    got = schedule.get_setting("news_follow")
    return [str(w) for w in got][:MAX_FOLLOW] if isinstance(got, list) else []


def follow(words: Any) -> str:
    w, now = clean(words, 60), follows()
    if len(w) < 2:
        raise ValueError("What should I follow?")
    if w.casefold() in (x.casefold() for x in now):
        raise ValueError(f"You already follow {w}.")
    if len(now) >= MAX_FOLLOW:
        raise ValueError(f"That's {MAX_FOLLOW}. Remove one first.")
    schedule.set_setting("news_follow", [*now, w])
    return w


def unfollow(words: Any) -> bool:
    w, now = str(words or "").casefold(), follows()
    schedule.set_setting("news_follow", [x for x in now if x.casefold() != w])
    return len(follows()) < len(now)


def page() -> dict:
    return {"topics": TOPICS, "sources": {k: v[0] for k, v in SOURCES.items()}, "feeds": feeds(), "follow": follows(), "saved": len(saved()),
            "briefing": in_briefing()}


# ---------------- the briefing ----------------
def in_briefing() -> bool:
    return schedule.get_setting("news_follow_briefing", True) is not False


def followed_lines(each: int = 2, most: int = 5) -> list[str]:
    """The newest of what the owner follows, for the daily briefing (from the last two days)."""
    if not in_briefing():
        return []
    cut = datetime.fromtimestamp(time.time() - 2 * 86400).strftime("%Y-%m-%dT%H:%M")
    out = []
    for w in follows()[:most]:
        try:
            got = [s for s in search(w)["stories"] if s["at"] >= cut][:each]
        except ValueError:
            continue
        if got:
            out.append(f"{w}: " + " | ".join(f"{s['title']} ({s['source']})" for s in got))
    return out


def line(s: dict, about: bool = False) -> str:
    at = s["at"].replace("T", " ")
    return f"[{s['id']}] {s['title']} ({', '.join(x for x in (s['source'], at) if x)})" + (f"\n   {s['about']}" if about and s["about"] else "")

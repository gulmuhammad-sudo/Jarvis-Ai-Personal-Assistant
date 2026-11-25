"""The same memories, notes, tasks and calendar on two of your PCs, straight from one to the other (no service in between).

Each thing has a lasting number (uid), made from its content when it is first seen, so that what is already the same on both
PCs fits together. One PC compares both lists and decides:
- changed on one side only since the last time: that one is taken over;
- changed on both: the newer one wins and the other is kept under "Set aside" (an edit always wins over a deletion);
- a lot deleted at once (a new or damaged database, an old backup): held, until you say what is right.
Clocks that don't agree are reckoned with. What comes in is checked like anything you type.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Any

KINDS = {"memories": "Memories", "notes": "Notes", "tasks": "Tasks", "calendar": "Calendar"}
MAX_ITEMS, EVERY = 6000, 600
MAX_PUSH, MAX_BYTES = 200, 4 * 2**20
_LOCK = threading.RLock()
_RUN: dict[str, Any] = {"busy": ""}


class SyncError(ValueError):
    """Something to tell the owner, in plain words."""


def _db():
    from . import storage
    return storage.conn(), storage._LOCK


def _hash(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:32]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------- what is here ----------------
_TASK = ("title", "notes", "project", "due", "priority", "done", "done_at")
_EVENT = ("title", "place", "notes", "start", "end", "all_day", "repeat", "until", "remind")


def _rows(kind: str) -> dict[str, dict]:
    """local id -> the content that counts"""
    from . import memory, notes
    if kind == "memories":
        return {str(m["id"]): {"fact": m["fact"], "category": m["category"], "importance": m["importance"]} for m in memory.all_facts()}
    if kind == "notes":
        out = {}
        for p in notes._dir().glob("*.md"):
            try:
                out[p.stem] = {"name": p.stem, "text": p.read_text(encoding="utf-8", errors="replace")[:notes.MAX_CHARS]}
            except OSError:
                continue
        return out
    c, lock = _db()
    table, cols = ("tasks", _TASK) if kind == "tasks" else ("calendar", _EVENT)
    with lock:
        return {str(r[0]): dict(zip(cols, r[1:])) for r in c.execute(f"SELECT id, {', '.join(cols)} FROM {table}").fetchall()}


def _key(kind: str, d: dict) -> str:
    from . import memory
    if kind == "memories":
        return memory._norm(d["fact"])
    if kind == "notes":
        return d["name"].lower()
    if kind == "tasks":
        return f"{d['title'].lower()}|{d['due'] or ''}"
    return f"{d['title'].lower()}|{d['start']}|{d['repeat']}"


def _uid(kind: str, d: dict) -> str:
    return hashlib.sha256(f"{kind}|{_key(kind, d)}".encode("utf-8", "replace")).hexdigest()[:24]


def scan(kind: str, me: str) -> dict[str, dict]:
    """Look what changed here since the last look. Returns uid -> {"hash", "changed", "by", "deleted", "local"}."""
    rows = _rows(kind)
    if len(rows) > MAX_ITEMS:
        raise SyncError(f"There are too many {KINDS[kind].lower()} to sync.")
    c, lock = _db()
    now = time.time()
    with lock, c:
        have = {r[0]: {"local": r[1], "hash": r[2], "changed": r[3], "by": r[4], "deleted": bool(r[5])} for r in c.execute("SELECT uid, local, hash, changed, by, deleted FROM sync_items WHERE kind = ?", (kind,)).fetchall()}
        by_local = {v["local"]: u for u, v in have.items() if not v["deleted"]}
        for uid, v in have.items():
            if not v["deleted"] and v["local"] not in rows:
                v.update(deleted=True, hash="", changed=now, by=me)
                c.execute("UPDATE sync_items SET deleted = 1, hash = '', changed = ?, by = ? WHERE kind = ? AND uid = ?", (now, me, kind, uid))
        for local, d in rows.items():
            h = _hash(d)
            uid = by_local.get(local)
            if uid is None:
                uid = _uid(kind, d)
                old = have.get(uid)
                if old and not old["deleted"]:
                    uid = secrets.token_hex(12)            # the same twice on this PC
                have[uid] = {"local": local, "hash": h, "changed": now, "by": me, "deleted": False}
                c.execute("INSERT OR REPLACE INTO sync_items(kind, uid, local, hash, changed, by, deleted, seen) VALUES (?, ?, ?, ?, ?, ?, 0, COALESCE((SELECT seen FROM sync_items WHERE kind = ? AND uid = ?), '{}'))", (kind, uid, local, h, now, me, kind, uid))
            elif have[uid]["hash"] != h:
                have[uid].update(hash=h, changed=now, by=me)
                c.execute("UPDATE sync_items SET hash = ?, changed = ?, by = ? WHERE kind = ? AND uid = ?", (h, now, me, kind, uid))
    return have


def index(kinds: list[str], me: str) -> dict[str, dict]:
    with _LOCK:
        return {k: {u: {x: v[x] for x in ("hash", "changed", "by", "deleted")} for u, v in scan(k, me).items()} for k in kinds}


def data_of(kind: str, uids: list[str]) -> dict[str, dict]:
    c, lock = _db()
    rows = _rows(kind)
    out, size = {}, 0
    with lock:
        for u in uids[:MAX_PUSH]:
            r = c.execute("SELECT local, deleted FROM sync_items WHERE kind = ? AND uid = ?", (kind, str(u))).fetchone()
            if r and not r[1] and r[0] in rows:
                size += len(json.dumps(rows[r[0]]))
                if out and size > MAX_BYTES:
                    break
                out[str(u)] = rows[r[0]]
    return out


# ---------------- checking what comes in ----------------
_DAY = r"\d{4}-\d\d-\d\d"


def _s(v: Any, most: int, need: bool = False) -> str:
    t = v if isinstance(v, str) else ""
    t = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", t)[:most]
    if need and not t.strip():
        raise SyncError("Something in it is empty.")
    return t


def _when(v: Any, need: bool = False) -> str | None:
    if v in (None, "") and not need:
        return None
    if not isinstance(v, str) or not re.fullmatch(_DAY + r"(T\d\d:\d\d)?", v):
        raise SyncError("A time in it isn't one.")
    datetime.fromisoformat(v)
    return v


def clean(kind: str, d: Any) -> dict:
    from . import memory, notes, planner
    if not isinstance(d, dict):
        raise SyncError("That wasn't understood.")
    if kind == "memories":
        return {"fact": _s(d.get("fact"), 1000, True), "category": d["category"] if d.get("category") in memory.CATEGORIES else "other", "importance": d["importance"] if d.get("importance") in (1, 2, 3) else 1}
    if kind == "notes":
        notes.path_of(d.get("name"))
        return {"name": str(d["name"]), "text": str(d.get("text") or "")[:notes.MAX_CHARS]}
    if kind == "tasks":
        done = 1 if d.get("done") else 0
        at = d.get("done_at")
        return {"title": _s(d.get("title"), planner.MAX_TITLE, True), "notes": _s(d.get("notes"), planner.MAX_NOTES), "project": _s(d.get("project"), 40), "due": _when(d.get("due")),
                "priority": d["priority"] if d.get("priority") in (1, 2, 3) and not isinstance(d.get("priority"), bool) else 1, "done": done, "done_at": at if done and isinstance(at, str) and re.fullmatch(_DAY + r"T[\d:]{5,8}", at) else None}
    start, end = _when(d.get("start"), True), _when(d.get("end"), True)
    if datetime.fromisoformat(end) < datetime.fromisoformat(start):
        raise SyncError("An event in it ends before it begins.")
    rem = d.get("remind")
    return {"title": _s(d.get("title"), planner.MAX_TITLE, True), "place": _s(d.get("place"), planner.MAX_TITLE), "notes": _s(d.get("notes"), planner.MAX_NOTES), "start": start, "end": end, "all_day": 1 if d.get("all_day") else 0,
            "repeat": d["repeat"] if d.get("repeat") in planner.REPEATS else "none", "until": (_when(d.get("until")) or "")[:10] or None, "remind": rem if isinstance(rem, int) and not isinstance(rem, bool) and 0 <= rem <= 10080 else None}


# ---------------- putting in ----------------
def _set_aside(kind: str, d: dict | None, why: str) -> None:
    if not d:
        return
    c, lock = _db()
    title = str(d.get("fact") or d.get("title") or d.get("name") or "")[:120]
    with lock, c:
        c.execute("INSERT INTO sync_lost(at, kind, title, data, why) VALUES (?, ?, ?, ?, ?)", (_now_iso(), kind, title, json.dumps(d, ensure_ascii=False), why[:120]))
        c.execute("DELETE FROM sync_lost WHERE at < ?", ((datetime.now() - timedelta(days=90)).isoformat(),))


def _write(kind: str, local: str | None, d: dict | None) -> str:
    """Add, change or delete one thing here. Returns its local id ("" when deleted)."""
    from . import memory, notes
    if kind == "notes":
        if d is None:
            if local:                                    # (its text is set aside: it can be brought back for 90 days)
                _set_aside("notes", _rows("notes").get(local), "deleted on the other PC")
                notes.path_of(local).unlink(missing_ok=True)
            return ""
        p = notes.path_of(d["name"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(d["text"], encoding="utf-8")
        tmp.replace(p)
        return p.stem
    c, lock = _db()
    if kind == "memories":
        memory._db()
        with lock, c:
            if d is None:
                c.execute("DELETE FROM memories WHERE id = ?", (int(local or 0),))
                return ""
            if local and c.execute("UPDATE memories SET fact = ?, category = ?, importance = ?, updated = ? WHERE id = ?", (d["fact"], d["category"], d["importance"], memory._now(), int(local))).rowcount:
                return local
            return str(c.execute("INSERT INTO memories(fact, category, importance, source, created, updated) VALUES (?, ?, ?, 'imported', ?, ?)", (d["fact"], d["category"], d["importance"], memory._now(), memory._now())).lastrowid)
    table, cols = ("tasks", _TASK) if kind == "tasks" else ("calendar", _EVENT)
    with lock, c:
        if d is None:
            c.execute(f"DELETE FROM {table} WHERE id = ?", (int(local or 0),))
            return ""
        vals = [d[k] for k in cols]
        if local and c.execute(f"UPDATE {table} SET {', '.join(k + ' = ?' for k in cols)}, updated = ?, reminded = NULL WHERE id = ?", (*vals, _now_iso(), int(local))).rowcount:
            return local
        return str(c.execute(f"INSERT INTO {table}({', '.join(cols)}, created, updated) VALUES ({', '.join('?' * len(cols))}, ?, ?)", (*vals, _now_iso(), _now_iso())).lastrowid)


def put(kind: str, uid: str, d: dict | None, changed: float, by: str, expect: str | None, aside: str = "") -> bool:
    """One thing from the other PC. expect: what it must still be here ("" = not here or deleted); False when it changed meanwhile."""
    if not re.fullmatch(r"[0-9a-f]{24}", str(uid)):
        raise SyncError("That wasn't understood.")
    d = None if d is None else clean(kind, d)
    with _LOCK:
        c, lock = _db()
        with lock:
            r = c.execute("SELECT local, deleted FROM sync_items WHERE kind = ? AND uid = ?", (kind, uid)).fetchone()
        rows = _rows(kind)
        local = r[0] if r and not r[1] and r[0] in rows else None
        now_hash = _hash(rows[local]) if local else ""
        if expect is not None and now_hash != expect:
            return False
        if kind == "notes" and d is not None and local is None and any(n.lower() == d["name"].lower() for n in rows):
            local = next(n for n in rows if n.lower() == d["name"].lower())      # the same name under another number
            _set_aside("notes", rows[local], "replaced by the other PC's")
        if aside and local:
            _set_aside(kind, rows[local], aside)
        if d is None and kind != "notes" and local:
            _set_aside(kind, rows[local], "deleted on the other PC")
        new = _write(kind, local, d)
        with lock, c:
            c.execute("INSERT INTO sync_items(kind, uid, local, hash, changed, by, deleted, seen) VALUES (?, ?, ?, ?, ?, ?, ?, '{}') "
                      "ON CONFLICT(kind, uid) DO UPDATE SET local = excluded.local, hash = excluded.hash, changed = excluded.changed, by = excluded.by, deleted = excluded.deleted",
                      (kind, uid, new, _hash(_rows(kind)[new]) if d is not None and new in _rows(kind) else "", float(changed), str(by)[:16], int(d is None)))
    return True


def bases(kind: str, peer: str) -> dict[str, str]:
    c, lock = _db()
    out = {}
    with lock:
        for u, s in c.execute("SELECT uid, seen FROM sync_items WHERE kind = ?", (kind,)).fetchall():
            try:
                b = json.loads(s).get(peer)
            except ValueError:
                b = None
            if isinstance(b, str):
                out[u] = b
    return out


def mark(kind: str, peer: str, same: dict[str, str]) -> None:
    """Both PCs have this now (uid -> hash, "" for deleted)."""
    c, lock = _db()
    with lock, c:
        for u, h in list(same.items())[:MAX_ITEMS]:
            r = c.execute("SELECT seen FROM sync_items WHERE kind = ? AND uid = ?", (kind, str(u))).fetchone()
            if not r:
                continue
            try:
                s = json.loads(r[0])
            except ValueError:
                s = {}
            s[peer] = str(h)[:32]
            c.execute("UPDATE sync_items SET seen = ? WHERE kind = ? AND uid = ?", (json.dumps(s), kind, str(u)))


def decide(mine: dict[str, dict], theirs: dict[str, dict], base: dict[str, str], skew: float = 0.0) -> dict[str, list]:
    """What has to move. mine/theirs: uid -> {"hash", "changed", "deleted"}; a deleted one has the hash ""."""
    out: dict[str, list] = {"pull": [], "push": [], "same": [], "pull_aside": [], "push_aside": []}
    for u in {*mine, *theirs}:
        a, b = mine.get(u), theirs.get(u)
        ha, hb = (a["hash"] if a and not a["deleted"] else ""), (b["hash"] if b and not b["deleted"] else "")
        if ha == hb:
            out["same"].append(u)
        elif a is None:
            out["pull"].append(u)
        elif b is None:
            out["push"].append(u)
        elif u in base and base[u] == ha:
            out["pull"].append(u)
        elif u in base and base[u] == hb:
            out["push"].append(u)
        elif not ha or not hb:                           # one deleted it, the other changed it: the change stays
            (out["push"] if ha else out["pull"]).append(u)
        elif b["changed"] - skew > a["changed"]:
            out["pull_aside"].append(u)
        else:
            out["push_aside"].append(u)
    return out


# ---------------- the whole round (the PC that starts it) ----------------
def too_many(deletes: int, live: int) -> bool:
    return deletes > max(10, live // 4)


def run(peer: str, call, me: str, kinds: list[str], deletions: str = "ask") -> dict:
    """call(path, body) speaks with the other PC. deletions: "ask" holds many at once, "yes" carries them out, "no" sends mine back."""
    kinds = [k for k in KINDS if k in kinds]
    if not kinds:
        raise SyncError("Choose what to sync.")
    with _LOCK:
        if _RUN["busy"]:
            raise SyncError("A sync is running already.")
        _RUN["busy"] = peer
    total = {"in": 0, "out": 0, "gone": 0, "aside": 0, "held": {}, "kinds": kinds}
    try:
        t0 = time.time()
        there = call("/pc/sync/index", {"kinds": kinds})
        skew = float(there["time"]) - (t0 + time.time()) / 2
        if abs(skew) < 2:
            skew = 0.0
        for k in [k for k in kinds if k in there["items"]]:
            _one(k, peer, call, me, there["items"][k], skew, deletions, total)
        return total
    finally:
        _RUN["busy"] = ""


def _one(k: str, peer: str, call, me: str, theirs: dict, skew: float, deletions: str, total: dict) -> None:
    if not isinstance(theirs, dict) or len(theirs) > 4 * MAX_ITEMS:
        raise SyncError("The other PC's list wasn't understood.")
    mine = index([k], me)[k]
    base = bases(k, peer)
    d = decide(mine, theirs, base, skew)
    gone = lambda t, u: u not in t or t[u]["deleted"]                                                     # noqa: E731
    del_here = [u for u in d["pull"] if gone(theirs, u) and not gone(mine, u)]
    del_there = [u for u in d["push"] if gone(mine, u) and not gone(theirs, u)]
    live_here, live_there = sum(not v["deleted"] for v in mine.values()), sum(not v["deleted"] for v in theirs.values())
    if too_many(len(del_here), live_here) and deletions != "yes":
        d["pull"] = [u for u in d["pull"] if u not in set(del_here)]
        if deletions == "no":
            d["push"] += del_here
        else:
            total["held"][k] = {"here": len(del_here), "there": 0}
    if too_many(len(del_there), live_there) and deletions != "yes":
        d["push"] = [u for u in d["push"] if u not in set(del_there)]
        if deletions == "no":
            d["pull"] += del_there
        else:
            total["held"].setdefault(k, {"here": 0, "there": 0})["there"] = len(del_there)
    same = {u: "" if gone(mine, u) else mine[u]["hash"] for u in d["same"]}
    aside = set(d["pull_aside"])
    want = d["pull"] + d["pull_aside"]
    while want:
        part, want = want[:MAX_PUSH], want[MAX_PUSH:]
        need = [u for u in part if not gone(theirs, u)]
        got = call("/pc/sync/get", {"kind": k, "uids": need})["items"] if need else {}
        if got:                                          # (it sends what fits: the rest with the next question)
            want = [u for u in need if u not in got] + want
        for u in part:
            t = theirs.get(u)
            dead = t is None or t["deleted"]
            if not dead and u not in got:
                continue                                 # gone or changed over there meanwhile: next time
            expect = "" if gone(mine, u) else mine[u]["hash"]
            try:
                ok = put(k, u, None if dead else got[u], (float(t["changed"]) - skew) if t else time.time(), str(t["by"]) if t else me, expect, "both PCs changed it; the other PC's was newer" if u in aside else "")
            except (SyncError, ValueError, KeyError, TypeError, OSError) as e:
                print(f"[sync] {k} {u[:6]}: {type(e).__name__}")
                continue
            if ok:
                total["in"] += 1
                total["gone"] += dead
                total["aside"] += u in aside
                same[u] = "" if dead else t["hash"]
    give = d["push"] + d["push_aside"]
    aside = set(d["push_aside"])
    while give:
        part, give = give[:MAX_PUSH], give[MAX_PUSH:]
        need = [u for u in part if not gone(mine, u)]
        data = data_of(k, need)
        if data:
            give = [u for u in need if u not in data] + give
        items = [{"uid": u, "data": data.get(u), "deleted": gone(mine, u), "changed": (mine[u]["changed"] if u in mine else time.time()) + skew, "by": mine[u]["by"] if u in mine else me, "expect": "" if gone(theirs, u) else theirs[u]["hash"],
                  "aside": u in aside} for u in part if gone(mine, u) or u in data]
        r = call("/pc/sync/put", {"kind": k, "items": items})
        for u in r["done"]:
            if u in set(part):
                total["out"] += 1
                total["aside"] += u in aside
                same[u] = "" if gone(mine, u) else mine[u]["hash"]
    mark(k, peer, same)
    call("/pc/sync/done", {"kind": k, "same": same})
    from . import tools
    tools._planner_changed()


# ---------------- the other side ----------------
def serve(action: str, data: dict, peer: str, me: str, kinds: list[str]) -> dict:
    if action == "index":
        ask = data.get("kinds")
        use = [k for k in kinds if isinstance(ask, list) and k in ask]
        return {"time": time.time(), "items": index(use, me)}
    k = data.get("kind")
    if k not in kinds:
        raise SyncError("That isn't synced with this PC.")
    if action == "get":
        u = data.get("uids")
        return {"items": data_of(k, [str(x) for x in u]) if isinstance(u, list) else {}}
    if action == "put":
        done = []
        items = data.get("items")
        for x in items[:MAX_PUSH] if isinstance(items, list) else []:
            try:
                if put(k, str(x["uid"]), None if x.get("deleted") is True else x["data"], float(x["changed"]), str(x["by"]), str(x["expect"]), "both PCs changed it; the other PC's was newer" if x.get("aside") is True else ""):
                    done.append(str(x["uid"]))
            except (SyncError, ValueError, KeyError, TypeError, OSError) as e:
                print(f"[sync] {k}: {type(e).__name__}")
        from . import tools
        tools._planner_changed()
        return {"done": done}
    if action == "done":
        s = data.get("same")
        if isinstance(s, dict):
            mark(k, peer, {str(u): str(h) for u, h in s.items()})
        return {"ok": True}
    raise SyncError("That wasn't understood.")


# ---------------- what was set aside ----------------
def set_aside() -> list[dict]:
    c, lock = _db()
    with lock:
        return [{"id": r[0], "at": r[1], "kind": r[2], "title": r[3], "why": r[4]} for r in c.execute("SELECT id, at, kind, title, why FROM sync_lost ORDER BY id DESC LIMIT 100").fetchall()]


def bring_back(i: Any) -> None:
    """As a new thing beside the one that won."""
    c, lock = _db()
    with lock:
        r = c.execute("SELECT kind, data FROM sync_lost WHERE id = ?", (int(i),)).fetchone()
    if not r:
        raise SyncError("That isn't there any more.")
    d = json.loads(r[1])
    if r[0] == "notes":
        from . import notes
        base, n = d["name"][:100], 1
        have = {x.lower() for x in _rows("notes")}
        while d["name"].lower() in have:
            n += 1
            d["name"] = f"{base} ({n})"
        notes.path_of(d["name"])
    _write(r[0], None, clean(r[0], d))
    with lock, c:
        c.execute("DELETE FROM sync_lost WHERE id = ?", (int(i),))


def forget(peer: str) -> None:
    """A PC was removed: what was agreed with it doesn't count any more."""
    c, lock = _db()
    with lock, c:
        for k, u, s in c.execute("SELECT kind, uid, seen FROM sync_items WHERE seen LIKE ?", (f"%{peer}%",)).fetchall():
            try:
                d = json.loads(s)
            except ValueError:
                continue
            d.pop(peer, None)
            c.execute("UPDATE sync_items SET seen = ? WHERE kind = ? AND uid = ?", (json.dumps(d), k, u))

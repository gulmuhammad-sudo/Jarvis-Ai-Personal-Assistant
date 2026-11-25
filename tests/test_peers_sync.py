"""Phase 9, part 4: other PCs and sync. Two made-up PCs: for the sync inside this process (two data folders), for pairing, asking and files
a second real process. Only 127.0.0.1; Windows' clipboard, Recycle Bin and real folders are never touched."""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jarvis import access, agents, audit, automations, config, guard, hud, lock, mail, memory, netlog, notes, peers, planner, plans, providers, remote, schedule, storage, sync, timeline, tools

ROOT = Path(__file__).parent.parent
HTML = hud.HTML_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------- sync: two PCs in one process ----------------
class Two:
    def __init__(self, tmp, monkeypatch):
        self.m, self.tmp, self.now = monkeypatch, tmp, ""
        self.skew = 0.0                                   # PC B's clock
        self.calls = []
        monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp / "settings.json")
        monkeypatch.setattr(audit, "file", lambda: tmp / "audit.log")
        monkeypatch.setattr(memory, "MEMORY_FILE", tmp / "none.json")
        for x in "AB":
            (tmp / x / "notes").mkdir(parents=True)
        self.use("A")

    def use(self, x):
        if self.now != x:
            storage.close()
            self.now = x
            self.m.setattr(storage, "path", lambda: self.tmp / x / "assistant.db")
            self.m.setattr(config, "NOTES_DIR", self.tmp / x / "notes")

    def call(self, to, back, peer):
        def f(path, body):
            body = json.loads(json.dumps(body))
            self.calls.append(path)
            self.use(to)
            real = time.time
            try:
                if self.skew and to == "B":
                    sync.time = types.SimpleNamespace(time=lambda: real() + self.skew)
                return json.loads(json.dumps(sync.serve(path.rpartition("/")[2], body, peer, f"me{to}", list(sync.KINDS))))
            finally:
                sync.time = time
                self.use(back)
        return f

    def sync(self, start="A", kinds=None, deletions="ask"):
        other = "B" if start == "A" else "A"
        self.use(start)
        r = sync.run(f"peer{other}", self.call(other, start, f"peer{start}"), f"me{start}", kinds or list(sync.KINDS), deletions)
        self.use(start)
        return r

    def on(self, x, f):
        self.use(x)
        if x == "B" and self.skew:
            real = time.time
            sync.time = types.SimpleNamespace(time=lambda: real() + self.skew)
        try:
            return f()
        finally:
            sync.time = time

    def facts(self, x):
        self.use(x)
        return sorted(m["fact"] for m in memory.all_facts())


@pytest.fixture
def two(tmp_path, monkeypatch):
    storage.close()
    t = Two(tmp_path, monkeypatch)
    yield t
    sync.time = time
    sync._RUN["busy"] = ""
    storage.close()


def note(t, x, name, text=None):
    t.use(x)
    p = config.NOTES_DIR / f"{name}.md"
    if text is None:
        return p.read_text(encoding="utf-8") if p.exists() else None
    p.write_text(text, encoding="utf-8")


def test_everything_goes_both_ways(two):
    two.on("A", lambda: (memory.remember("likes tea", "preferences", 2), planner.save_task(title="Buy milk", due="2026-12-01", project="Home", priority=2), planner.save_event(title="Doctor", day="2026-12-02", time="17:00", place="City", repeat="weekly")))
    note(two, "A", "Ideas", "one\nدو")
    two.on("B", lambda: (memory.remember("works at X"), planner.save_task(title="Call Ali")))
    note(two, "B", "Work", "text")
    r = two.sync()
    assert (r["in"], r["out"], r["aside"], r["held"]) == (3, 4, 0, {})
    for x in "AB":
        assert two.facts(x) == ["likes tea", "works at X"] and note(two, x, "Ideas") == "one\nدو" and note(two, x, "Work") == "text"
        assert sorted(t["title"] for t in planner.list_tasks()) == ["Buy milk", "Call Ali"]
        e = planner.all_events()[0]
        assert (e["title"], e["place"], e["repeat"], e["start"]) == ("Doctor", "City", "weekly", "2026-12-02T17:00")
    two.use("B")
    t = next(t for t in planner.list_tasks() if t["title"] == "Buy milk")
    assert (t["due"], t["project"], t["priority"]) == ("2026-12-01", "Home", 2)
    assert next(m for m in memory.all_facts() if m["fact"] == "likes tea")["category"] == "preferences"
    for start in "ABA":
        r = two.sync(start)
        assert (r["in"], r["out"], r["gone"], r["aside"]) == (0, 0, 0, 0)


def test_the_same_thing_on_both_stays_one(two):
    for x in "AB":
        two.on(x, lambda: (memory.remember("likes tea"), planner.save_task(title="Buy milk"), planner.save_event(title="Doctor", day="2026-12-02", time="17:00")))
        note(two, x, "Ideas", "same")
    assert (lambda r: (r["in"], r["out"]))(two.sync()) == (0, 0) and two.facts("B") == ["likes tea"] and len(planner.list_tasks()) == 1


def test_changes_and_deletions(two):
    two.on("A", lambda: [memory.remember(f"fact {i}") for i in range(3)])
    note(two, "A", "N", "old")
    two.sync()
    two.on("B", lambda: memory.update(next(m["id"] for m in memory.all_facts() if m["fact"] == "fact 1"), "fact one"))
    two.on("A", lambda: memory.forget(next(m["id"] for m in memory.all_facts() if m["fact"] == "fact 2")))
    note(two, "B", "N", "new")
    r = two.sync()
    assert (r["in"], r["out"], r["aside"]) == (2, 1, 0)
    for x in "AB":
        assert two.facts(x) == ["fact 0", "fact one"] and note(two, x, "N") == "new"
    two.use("B")
    (config.NOTES_DIR / "N.md").unlink()
    two.sync("B")
    assert note(two, "A", "N") is None
    two.use("A")
    assert [(a["kind"], a["title"]) for a in sync.set_aside()] == [("notes", "N")]                  # what was deleted there can be brought back here
    sync.bring_back(sync.set_aside()[0]["id"])
    assert note(two, "A", "N") == "new" and sync.set_aside() == []
    two.sync()
    assert note(two, "B", "N") == "new"                                                              # made again: lives again on both


def test_both_changed_the_newer_wins_the_other_is_kept(two):
    two.on("A", lambda: memory.remember("the wifi password is in the drawer"))
    two.sync()
    mid = lambda: memory.all_facts()[0]["id"]                                                         # noqa: E731
    two.on("A", lambda: memory.update(mid(), "older change"))
    two.on("A", lambda: sync.scan("memories", "meA"))
    time.sleep(0.05)
    two.on("B", lambda: memory.update(mid(), "newer change"))
    r = two.sync()
    assert r["aside"] == 1 and two.facts("A") == two.facts("B") == ["newer change"]
    two.use("A")
    assert sync.set_aside()[0]["title"] == "older change" and "newer" in sync.set_aside()[0]["why"]
    two.on("B", lambda: (memory.update(mid(), "B older"), sync.scan("memories", "meB")))
    time.sleep(0.05)
    two.on("A", lambda: memory.update(mid(), "A newer"))
    assert two.sync()["aside"] == 1 and two.facts("B") == ["A newer"] and [a["title"] for a in two.on("B", sync.set_aside)] == ["B older"]


def test_a_change_wins_over_a_deletion(two):
    two.on("A", lambda: memory.remember("keep me"))
    two.sync()
    two.on("A", lambda: memory.update(memory.all_facts()[0]["id"], "kept and changed"))
    two.on("B", lambda: memory.forget(memory.all_facts()[0]["id"]))
    two.sync("B")
    assert two.facts("A") == two.facts("B") == ["kept and changed"]


def test_clocks_that_do_not_agree(two):
    two.skew = 86400.0
    two.on("A", lambda: memory.remember("x fact"))
    two.sync()
    mid = lambda: memory.all_facts()[0]["id"]                                                         # noqa: E731
    two.on("B", lambda: (memory.update(mid(), "B first"), sync.scan("memories", "meB")))             # (its clock: tomorrow)
    time.sleep(0.05)
    two.on("A", lambda: memory.update(mid(), "A later"))
    two.sync()
    assert two.facts("A") == two.facts("B") == ["A later"]


def test_a_lot_deleted_is_held(two):
    two.on("A", lambda: [memory.remember(f"fact number {i}") for i in range(30)])
    two.sync()
    two.use("B")
    storage.conn().execute("DELETE FROM memories")
    storage.conn().commit()
    r = two.sync()
    assert r["held"] == {"memories": {"here": 30, "there": 0}} and len(two.facts("A")) == 30
    r = two.sync("B")
    assert r["held"] == {"memories": {"here": 0, "there": 30}} and len(two.facts("A")) == 30
    two.sync("A", deletions="no")
    assert len(two.facts("A")) == len(two.facts("B")) == 30
    two.use("B")
    storage.conn().execute("DELETE FROM memories")
    storage.conn().commit()
    two.sync("A", deletions="yes")
    assert two.facts("A") == [] and len(two.on("A", sync.set_aside)) == 30


def test_only_the_chosen_kinds(two):
    two.on("A", lambda: (memory.remember("a fact"), planner.save_task(title="T")))
    two.sync(kinds=["tasks"])
    assert two.facts("B") == [] and two.on("B", lambda: len(planner.list_tasks())) == 1
    with pytest.raises(sync.SyncError):
        two.sync(kinds=["vault"])
    two.use("B")
    with pytest.raises(sync.SyncError):
        sync.serve("get", {"kind": "vault", "uids": []}, "p", "me", list(sync.KINDS))
    with pytest.raises(sync.SyncError):
        sync.serve("put", {"kind": "tasks", "items": []}, "p", "me", ["notes"])
    assert list(sync.serve("index", {"kinds": ["tasks", "notes", "vault"]}, "p", "me", ["notes"])["items"]) == ["notes"]


def test_what_comes_in_is_checked(two):
    ok = "a" * 24
    for kind, d in (("notes", {"name": "../x", "text": ""}), ("notes", {"name": "a\\b", "text": ""}), ("notes", {"name": "con", "text": ""}), ("memories", {"fact": " "}), ("memories", {"fact": ["x"]}), ("tasks", {"title": ""}),
                    ("tasks", {"title": "x", "due": "2026-99-99"}), ("tasks", {"title": "x", "due": "'; DROP TABLE tasks"}), ("calendar", {"title": "x", "start": "2026-01-02T10:00", "end": "2026-01-01T10:00"}), ("calendar", {"title": "x"}), ("tasks", None), ("tasks", [1])):
        with pytest.raises(ValueError):
            sync.clean(kind, d)
    d = sync.clean("calendar", {"title": "x\x00", "start": "2026-01-01T10:00", "end": "2026-01-01T11:00", "repeat": "hourly", "remind": -5, "all_day": "yes", "until": "2026-02-01T00:00"})
    assert d["title"] == "x" and d["repeat"] == "none" and d["remind"] is None and d["all_day"] == 1 and d["until"] == "2026-02-01"
    assert sync.clean("memories", {"fact": "x" * 5000, "category": "evil", "importance": 9}) == {"fact": "x" * 1000, "category": "other", "importance": 1}
    for bad in ("x", "A" * 24, "", "../" + "a" * 21, "a" * 25):
        with pytest.raises(sync.SyncError):
            sync.put("memories", bad, {"fact": "x"}, 1.0, "me", "")
    assert sync.put("memories", ok, {"fact": "x"}, 1.0, "me", "") and not sync.put("memories", ok, {"fact": "y"}, 2.0, "me", "wrong")      # changed meanwhile: not written over
    assert two.facts("A") == ["x"]
    r = sync.serve("put", {"kind": "notes", "items": [{"uid": ok, "data": {"name": "../../evil", "text": "x"}, "changed": 1, "by": "x", "expect": ""}, {"bad": 1}, {"uid": "b" * 24, "data": {"name": "fine", "text": "x"}, "changed": 1, "by": "x", "expect": ""}]}, "p", "me", ["notes"])
    assert r == {"done": ["b" * 24]} and [p.name for p in config.NOTES_DIR.iterdir()] == ["fine.md"] and not list(two.tmp.rglob("evil*"))


def test_a_change_while_it_runs_is_not_lost(two):
    two.on("A", lambda: memory.remember("start"))
    two.sync()
    two.on("B", lambda: memory.update(memory.all_facts()[0]["id"], "from B"))
    real = two.call("B", "A", "peerA")

    def call(path, body):
        out = real(path, body)
        if path.endswith("get"):                                                                      # you type on this PC in exactly that moment
            memory.update(memory.all_facts()[0]["id"], "typed here")
        return out
    two.use("A")
    sync.run("peerB", call, "meA", ["memories"])
    assert two.facts("A") == ["typed here"]
    two.sync()
    assert two.facts("A") == two.facts("B") and two.facts("A")[0] in ("typed here", "from B")
    two.use("A")
    assert {a["title"] for a in sync.set_aside()} | {a["title"] for a in two.on("B", sync.set_aside)} >= {"from B"} or two.facts("A") == ["from B"]


def test_many_and_big_go_in_parts(two, monkeypatch):
    monkeypatch.setattr(sync, "MAX_PUSH", 7)
    monkeypatch.setattr(sync, "MAX_BYTES", 900)
    two.use("A")
    for i in range(20):
        note(two, "A", f"note {i}", f"{i} " * 80)
    for i in range(20):
        note(two, "B", f"other {i}", f"{i} " * 80)
    r = two.sync()
    assert (r["in"], r["out"]) == (20, 20)
    for x in "AB":
        two.use(x)
        assert len(list(config.NOTES_DIR.glob("*.md"))) == 40 and note(two, x, "note 19") == "19 " * 80


def test_one_at_a_time(two):
    sync._RUN["busy"] = "x"
    with pytest.raises(sync.SyncError, match="already"):
        two.sync()
    sync._RUN["busy"] = ""
    with pytest.raises(RuntimeError):
        sync.run("p", lambda p, b: (_ for _ in ()).throw(RuntimeError()), "me", ["tasks"])
    assert sync._RUN["busy"] == ""


def test_done_tasks_and_notes_by_name(two):
    two.on("A", lambda: planner.save_task(title="T"))
    note(two, "A", "List", "a")
    two.sync()
    two.on("B", lambda: planner.set_done(planner.list_tasks()[0]["id"], True))
    two.sync("B")
    assert two.on("A", lambda: planner.list_tasks(done=True)[0]["done"]) is True
    note(two, "A", "Two", "from A")
    note(two, "B", "Two", "from B")
    r = two.sync()
    assert r["aside"] == 1 and note(two, "A", "Two") == note(two, "B", "Two")
    lost = two.on("A", sync.set_aside) + two.on("B", sync.set_aside)
    assert [x["title"] for x in lost] == ["Two"]


def test_forgetting_a_pc(two):
    two.on("A", lambda: memory.remember("x fact"))
    two.sync()
    two.use("A")
    assert sync.bases("memories", "peerB")
    sync.forget("peerB")
    assert sync.bases("memories", "peerB") == {}
    assert (lambda r: (r["in"], r["out"], r["aside"]))(two.sync()) == (0, 0, 0)


def test_three_pcs_worth_of_marks(two):
    two.on("A", lambda: memory.remember("x fact"))
    sync.scan("memories", "me")
    u = next(iter(sync.scan("memories", "me")))
    sync.mark("memories", "p1", {u: "h1", "f" * 24: "h"})
    sync.mark("memories", "p2", {u: "h2"})
    assert sync.bases("memories", "p1") == {u: "h1"} and sync.bases("memories", "p2") == {u: "h2"}


# ---------------- two real programs ----------------
B = r'''
import json, sys, threading, types, os
sys.path.insert(0, %r)
from jarvis import access, hud, remote, schedule, lock, memory, peers, tools, storage, sync
schedule.Scheduler._loop = lambda self: None
access.N = 2 ** 10
h = hud.HUB = hud.Hub()
h.brain = types.SimpleNamespace(names=["F"], current="F", ask=lambda t: h.on_text("B did: " + t))
threading.Thread(target=h.brain_worker, daemon=True).start()
print(json.dumps("ready"), flush=True)
for line in sys.stdin:
    try:
        out = eval(line)
    except Exception as e:
        out = f"!{type(e).__name__}: {e}"
    print(json.dumps(out, default=str), flush=True)
os._exit(0)
'''


class Other:
    def __init__(self, tmp):
        self.port = free_port()
        self.dir = tmp / "pcb"
        env = {**os.environ, "JARVIS_DATA_DIR": str(self.dir), "JARVIS_REMOTE_BIND": "127.0.0.1", "JARVIS_NO_MIC": "1", "JARVIS_NO_SPEAK": "1", "USERPROFILE": str(tmp / "homeb"), "PYTHONIOENCODING": "utf-8"}
        self.p = subprocess.Popen([sys.executable, "-c", B % str(ROOT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True, encoding="utf-8", bufsize=1)
        self.read()

    def read(self):
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("PC B ended")
            try:
                return json.loads(line)
            except ValueError:
                continue                                                                              # (something it printed)

    def __call__(self, code):
        self.p.stdin.write(code.replace("\n", " ") + "\n")
        self.p.stdin.flush()
        out = self.read()
        assert not (isinstance(out, str) and out.startswith("!")), out
        return out


@pytest.fixture(scope="module")
def far(tmp_path_factory):
    b = Other(tmp_path_factory.mktemp("far"))
    b(f"remote.set_settings({{'on': True, 'port': {b.port}}})")
    yield b
    b.p.stdin.close()
    try:
        b.p.wait(10)
    except subprocess.TimeoutExpired:
        b.p.kill()


@pytest.fixture
def home(tmp_path, monkeypatch):
    d = tmp_path / "data"
    (d / "notes").mkdir(parents=True)
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: d / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", d / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: d / "audit.log")
    monkeypatch.setattr(config, "DATA_DIR", d)
    monkeypatch.setattr(config, "NOTES_DIR", d / "notes")
    monkeypatch.setattr(memory, "MEMORY_FILE", d / "none.json")
    monkeypatch.setenv("JARVIS_REMOTE_BIND", "127.0.0.1")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "homea"))
    monkeypatch.setattr(access, "N", 2 ** 10)
    access._S.update(data=None, file=None, saved=0.0, dirty=False)
    access._PAIR.clear(), access._ASKS.clear(), access._FAILS.clear(), remote._RATE.clear()
    peers._JOIN.update(state="", text=""), peers._STATUS.clear(), peers._LAST.clear()
    peers._NEXT["at"] = 0.0
    lock._STATE.update(locked=False)
    tools.STOP.clear()
    mail.clear_seen()
    yield d
    remote.stop()
    access._S.update(data=None, file=None)
    mail.clear_seen()
    storage.close()


def wait_for(f, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if f():
            return True
        time.sleep(0.05)
    return False


def pair(far, rights=("ask", "files", "sync"), allow=True, answer=True):
    for d in far("access.devices()"):
        far(f"access.remove({d['id']!r})")
    far("access._FAILS.clear()")
    code = far("access.start_pairing('pc')")["code"]
    peers.join(f"127.0.0.1:{far.port}", code, ["ask", "files", "sync"])
    if answer:
        assert wait_for(lambda: (far("access.pairing()") or {}).get("asks"))
        a = far("access.pairing()")["asks"][0]
        far(f"(access.answer({a['id']!r}, {allow}, {list(rights)!r}), 1)[1]")
    assert wait_for(lambda: peers.joining()["state"] != "busy", 15)
    return peers.joining()


def test_pairing_two_pcs(home, far):
    j = pair(far)
    assert j["state"] == "done" and "Paired with" in j["text"]
    i, p = next(iter(access.peers().items()))
    assert p["urls"][0] == f"127.0.0.1:{far.port}" and p["pin"] == far("remote.own_pin()") and access.devices()[0]["id"] == i and access.devices()[0]["rights"] == ["ask", "files", "sync"]
    raw = access._unprotect((home / "access.dat").read_bytes()).decode()
    assert access.devices()[0]["kind"] == "pc" and raw.count(p["token"]) == 1                        # theirs for calling them; of ours for them only the hash
    s = peers.check(i)
    assert s["on"] and s["version"] == hud.__version__ and s["locked"] is False


def test_both_can_call_each_other(home, far, monkeypatch):
    h = hud.Hub()
    monkeypatch.setattr(hud, "HUB", h)
    h.brain = types.SimpleNamespace(names=["F"], current="F", ask=lambda t: h.on_text("A did: " + t))
    threading.Thread(target=h.brain_worker, daemon=True).start()
    remote.set_settings({"on": True, "port": free_port()})
    pair(far)
    i = next(iter(access.peers()))
    assert peers.ask(i, "open notes") == "B did: open notes"
    pid = next(iter(far("{k: 1 for k in access.peers()}")))
    assert far(f"peers.ask({pid!r}, 'salam')") == "A did: salam"
    assert h.history[-2]["source"] == "pc" and h.history[-1]["quiet"] and mail.recently_seen() and "Another" in mail.why_seen().title() or "another" in mail.why_seen()
    h.ringer.stop()


def test_a_wrong_code_and_no(home, far):
    for d in far("access.devices()"):
        far(f"access.remove({d['id']!r})")
    far("access.start_pairing('pc')")
    peers.join(f"127.0.0.1:{far.port}", "AAAA-AAAA", [])
    assert wait_for(lambda: peers.joining()["state"] == "failed") and "isn't the code" in peers.joining()["text"]
    assert access.peers() == {} and far("access.devices()") == []
    j = pair(far, allow=False)
    assert j["state"] == "failed" and "denied" in j["text"] and access.peers() == {} and access.devices() == []
    far("access.stop_pairing()")
    peers.join(f"127.0.0.1:{far.port}", "AAAA-AAAA", [])
    assert wait_for(lambda: peers.joining()["state"] == "failed") and "No code" in peers.joining()["text"]


def test_somebody_in_between_is_noticed(home, far, monkeypatch):
    """A machine that hands everything on, with its own key: the proofs don't fit its key."""
    far("access._FAILS.clear()")
    code = far("access.start_pairing('pc')")["code"]
    real = peers._connect
    monkeypatch.setattr(peers, "_connect", lambda w, t, pin=None: (real(w, t)[0], "e" * 64))         # (what this PC would see)
    peers.join(f"127.0.0.1:{far.port}", code, ["ask"])
    assert wait_for(lambda: peers.joining()["state"] == "failed") and "isn't the code" in peers.joining()["text"] and access.peers() == {}
    far("access._FAILS.clear()")


def test_a_pc_that_cannot_prove_the_code(home, monkeypatch):
    class Fake:
        pass
    monkeypatch.setattr(peers, "_connect", lambda w, t, pin=None: (Fake(), "d" * 64))
    said = []

    def speak(tls, where, path, body, *a, **k):
        said.append(path)
        return {"salt": "00" * 16, "nonce": "11" * 16} if path.endswith("begin") else {"ask": "x", "proof": "0" * 64}
    monkeypatch.setattr(peers, "_speak", speak)
    peers.join("192.168.1.5", "AAAA-AAAA", ["ask"])
    assert wait_for(lambda: peers.joining()["state"] == "failed") and "couldn't prove" in peers.joining()["text"] and access.peers() == {} and said == ["/pair/pc/begin", "/pair/pc/code"]


def test_another_machine_at_the_address_gets_nothing(home, far, monkeypatch):
    pair(far)
    i = next(iter(access.peers()))
    access.set_peer(i, pin="f" * 64)
    spoke = []
    monkeypatch.setattr(peers, "_speak", lambda *a, **k: spoke.append(a))
    with pytest.raises(peers.Elsewhere, match="Nothing was sent"):
        peers.call(i, "/pc/hello", {})
    assert spoke == [] and peers.check(i)["on"] is False


def test_rights_on_each_side(home, far):
    pair(far, rights=[])
    i = next(iter(access.peers()))
    with pytest.raises(peers.PeerError, match="doesn't take orders"):
        peers.ask(i, "x")
    with pytest.raises(peers.PeerError, match="doesn't sync"):
        peers.run_sync(i)
    f = home / "a.txt"
    f.write_text("x")
    with pytest.raises(peers.PeerError, match="doesn't take files"):
        peers.send_file(i, str(f))
    assert peers.check(i)["on"]
    far(f"access.remove({far('access.devices()')[0]['id']!r})")
    with pytest.raises(peers.PeerError, match="doesn't know this one"):
        peers.ask(i, "x")


def test_a_phone_s_secret_opens_no_pc_requests_and_back(home, far):
    pair(far)
    i = next(iter(access.peers()))
    for path in ("/api/send", "/api/state", "/api/lists", "/api/stop"):
        with pytest.raises(peers.PeerError):
            peers.call(i, path, {"text": "x"})
    with pytest.raises(peers.PeerError):
        peers.call(i, "/pc/nothing", {})


def test_paired_again_takes_the_old_one_s_place(home, far):
    pair(far)
    old = next(iter(access.peers()))
    code = far("access.start_pairing('pc')")["code"]
    peers.join(f"127.0.0.1:{far.port}", code, ["ask"])
    assert wait_for(lambda: (far("access.pairing()") or {}).get("asks"))
    a = far("access.pairing()")["asks"][0]
    far(f"(access.answer({a['id']!r}, True, ['ask']), 1)[1]")
    assert wait_for(lambda: peers.joining()["state"] == "done")
    assert len(access.peers()) == len(access.devices()) == 1 and old not in access.peers() and len(far("access.devices()")) == 1
    assert peers.check(next(iter(access.peers())))["on"]


def test_locked_and_stopped_over_there(home, far):
    pair(far)
    i = next(iter(access.peers()))
    far("lock._STATE.update(locked=True)")
    try:
        with pytest.raises(peers.PeerError, match="locked"):
            peers.ask(i, "x")
        with pytest.raises(peers.PeerError, match="locked"):
            peers.run_sync(i)
        s = peers.check(i)
        assert s["on"] and s["locked"] and not s["state"]
    finally:
        far("lock._STATE.update(locked=False)")
    far("tools.STOP.set()")
    with pytest.raises(peers.PeerError, match="Stop was pressed"):
        peers.ask(i, "x")
    far("tools.STOP.clear()")


def test_files(home, far, tmp_path):
    pair(far)
    i = next(iter(access.peers()))
    f = tmp_path / "Report نیا.pdf"
    f.write_bytes(os.urandom(700_000))
    assert "is there" in peers.send_file(i, str(f)) and "is there" in peers.send_file(i, str(f))
    got = Path(far("str(peers.downloads())"))
    names = sorted(p.name for p in got.iterdir())
    assert names == ["Report نیا (2).pdf", "Report نیا.pdf"] and (got / names[1]).read_bytes() == f.read_bytes()
    assert "ZoneId=3" in open(f"{got / names[1]}:Zone.Identifier").read()
    for bad in ("", "relative.txt", "\\\\pc\\x.txt", str(tmp_path / "none"), str(tmp_path), None):
        with pytest.raises(peers.PeerError):
            peers.send_file(i, bad)
    for secret in (".env", "keys.dat", "id_rsa", "My Passwords.txt"):
        (tmp_path / secret).write_text("x")
        with pytest.raises(peers.PeerError, match="passwords or keys"):
            peers.send_file(i, str(tmp_path / secret))
    with pytest.raises(peers.PeerError, match="whole"):
        peers.call(i, "/pc/file", open(f, "rb"), 20, {"Content-Type": "application/octet-stream", "Content-Length": str(f.stat().st_size), "X-Name": "x.bin", "X-Sha256": "0" * 64})
    with pytest.raises(peers.PeerError, match="200 MB"):
        peers.call(i, "/pc/file", open(f, "rb"), 20, {"Content-Type": "application/octet-stream", "Content-Length": str(f.stat().st_size), "X-Name": "x.bin", "X-Sha256": "x"})
    assert len(list(got.iterdir())) == 2                                                              # nothing half


def test_names_of_files():
    for a, b in (("..\\..\\evil.exe", "_.._evil.exe"), ("a/b:c?.txt", "a_b_c_.txt"), ("con.txt", "file"), ("", "file"), ("  . ", "file"), ("x\u202egnp.exe", "x_gnp.exe"), ("C:\\x\\y.txt", "C__x_y.txt")):
        n = peers.safe_name(a)
        assert n == b or "\\" not in n and "/" not in n and ":" not in n and not n.startswith("."), (a, n)
    assert len(peers.safe_name("x" * 500)) <= 120


def test_sync_over_the_wire(home, far):
    far("[memory.forget(m['id']) for m in memory.all_facts()]")
    pair(far)
    i = next(iter(access.peers()))
    memory.remember("from A نیا")
    far("memory.remember('from B')")
    r = peers.run_sync(i)
    assert r["ok"] and sorted(m["fact"] for m in memory.all_facts()) == ["from A نیا", "from B"] == sorted(far("[m['fact'] for m in memory.all_facts()]"))
    assert peers.run_sync(i)["text"] == "Nothing new" and peers.listing()[0]["last"]["ok"]
    did = far("access.devices()")[0]["id"]
    far(f"peers.set_options({did!r}, {{'kinds': ['tasks']}})")                                        # the other PC only wants tasks
    memory.remember("only here")
    peers.run_sync(i)
    assert "only here" not in far("[m['fact'] for m in memory.all_facts()]")
    peers.set_options(i, {"auto": True, "kinds": ["tasks", "x"]})
    assert peers.options(i) == {"auto": True, "kinds": ["tasks"]}
    for bad in (("x", {}), (i, {"kinds": "all"})):
        with pytest.raises(peers.PeerError):
            peers.set_options(*bad)
    assert peers.tick(datetime.now(), lambda *a: None) == 1 and peers.tick(datetime.now(), lambda *a: None) == 0
    assert wait_for(lambda: not any(t.name == "sync" for t in threading.enumerate()))


def test_local_only_and_a_pc_that_is_off(home, far, monkeypatch):
    pair(far)
    i = next(iter(access.peers()))
    access.set_peer(i, urls=["127.0.0.1:9"])
    with pytest.raises(peers.PeerError, match="couldn't be reached"):
        peers.ask(i, "x")
    monkeypatch.setattr(netlog, "_ON", True)
    monkeypatch.setattr(netlog, "_LOCAL", True)
    with pytest.raises(peers.PeerError, match="Local only"):
        peers.ask(i, "x")
    with pytest.raises(peers.PeerError, match="Local only"):
        peers.join("192.168.1.5", "AAAABBBB", [])
    assert peers.tick(datetime.now(), lambda *a: None) == 0


def test_addresses_of_pcs(monkeypatch, home):
    monkeypatch.setattr(remote, "_cards", lambda: [])
    for a, b in (("192.168.1.5", "192.168.1.5:8766"), ("https://192.168.1.5:9000/", "192.168.1.5:9000"), ("DESKTOP-1", "DESKTOP-1:8766"), ("pc.local:8766", "pc.local:8766")):
        assert peers.address(a) == b
    for bad in ("8.8.8.8", "evil.com", "x/y", "", None, "a b", "1.2.3.4:80", "user@192.168.1.5", "192.168.1.5:99999999", "[::1]"):
        with pytest.raises(peers.PeerError):
            peers.address(bad)
    with pytest.raises(peers.PeerError, match="eight"):
        peers.join("192.168.1.5", "ABC", [])


def test_a_bad_hello_makes_no_way_back(home):
    """The joining PC's own words are checked before they are kept."""
    for more in ({"pin": "x", "urls": ["192.168.1.5:1"], "token": "a" * 43, "id": "0" * 16}, {"pin": "f" * 64, "urls": "x", "token": "a" * 43, "id": "0" * 16}, {"pin": "f" * 64, "urls": [], "token": "x\r\ny", "id": "0" * 16}, {"pin": "f" * 64, "urls": [], "token": "a" * 43, "id": "../x"}):
        access._ASKS.clear()
        s = access._ask("pc", "X", "192.168.1.9", more)
        access.answer(next(iter(access._ASKS.values()))["id"], True, ["ask"])
        assert access.peers() == {} and s
    access._ASKS.clear()
    access._ask("pc", "X", "192.168.1.9", {"pin": "f" * 64, "urls": ["192.168.1.5:8766", "evil/x:1", "http://x", "a:b"], "token": "a" * 43, "id": "0" * 16})
    access.answer(next(iter(access._ASKS.values()))["id"], True, ["ask"])
    assert next(iter(access.peers().values()))["urls"] == ["192.168.1.5:8766"]


# ---------------- the AI, the page ----------------
def test_the_ai_s_tool(home, far, tmp_path):
    asked = []
    ctx = types.SimpleNamespace(approve=lambda q, kind=None: asked.append((q, kind)) or len(asked) % 2 == 0)
    assert "No other PC" in tools.other_pc_tool({"action": "list"}, ctx)
    pair(far)
    name = next(iter(access.peers().values()))["name"]
    assert name in tools.other_pc_tool({"action": "list"}, ctx) and "127.0.0.1" not in tools.other_pc_tool({"action": "list"}, ctx)
    assert "didn't ask" in tools.other_pc_tool({"action": "ask", "pc": name, "text": "hi"}, ctx)
    assert "B did: hi" in tools.other_pc_tool({"action": "ask", "pc": name.lower(), "text": "hi"}, ctx)
    f = tmp_path / "f.txt"
    f.write_text("x")
    assert "didn't send" in tools.other_pc_tool({"action": "send_file", "pc": name, "path": str(f)}, ctx) and "is there" in tools.other_pc_tool({"action": "send_file", "pc": name, "path": str(f)}, ctx)
    assert [k for _, k in asked] == ["other_pc", "other_pc", "other_pc_file", "other_pc_file"]
    assert "Synced" in tools.other_pc_tool({"action": "sync", "pc": name}, ctx) and "can't tell" in tools.other_pc_tool({"action": "ask", "pc": "zzz"}, ctx)
    assert "other_pc" in hud.Hub.TRUSTABLE and "other_pc_file" not in hud.Hub.TRUSTABLE and {"other_pc", "other_pc_file"} <= set(hud.Hub.PERMISSION_KINDS)
    assert guard.is_untrusted("other_pc", {"action": "ask"}) and guard.held_after_email("other_pc", {"action": "ask"}) and not guard.held_after_email("other_pc", {"action": "list"})
    assert "other_pc" not in agents.AGENT_TOOLS and "other_pc" not in automations.STEP_TOOLS and "other_pc:list" in plans.LOOKING and "other_pc" in providers.LOCAL_TOOLS


def call(action, data=None):
    h = hud.Handler.__new__(hud.Handler)
    out = {}
    h._json = lambda d, code=200: out.update(body=d, code=code)
    h._daily_api("devices", action, data or {})
    return out["code"], out["body"]


def test_requests_of_the_page(home, far, monkeypatch, tmp_path):
    h = hud.Hub()
    monkeypatch.setattr(hud, "HUB", h)
    pair(far)
    i = next(iter(access.peers()))
    j = call("load")[1]
    assert j["pcs"][0]["id"] == i and j["kinds"] == sync.KINDS and j["aside"] == [] and "token" not in json.dumps(j) and "pin\": \"" + access.peers()[i]["pin"] not in json.dumps(j)
    assert call("check", {"id": i})[1]["pcs"][0]["status"]["on"] and call("sync", {"id": i})[1]["sync"]["ok"] and call("ask", {"id": i, "text": "hey"})[1]["answer"] == "B did: hey"
    assert call("pc", {"id": i, "auto": True})[1]["pcs"][0]["auto"] and call("sync", {"id": i, "deletions": "maybe"})[0] == 400 and call("ask", {"id": "x", "text": "y"})[0] == 400
    f = tmp_path / "g.txt"
    f.write_text("x")
    monkeypatch.setattr(hud, "_pick_file", lambda k, s="": str(f))
    assert "is there" in call("file", {"id": i})[1]["said"]
    monkeypatch.setattr(hud, "_pick_file", lambda k, s="": "")
    assert "said" not in call("file", {"id": i})[1]
    sync._set_aside("memories", {"fact": "old words", "category": "other", "importance": 1}, "why")
    a = call("load")[1]["aside"][0]
    assert call("back", {"aside": a["id"]})[1]["aside"] == [] and any(m["fact"] == "old words" for m in memory.all_facts()) and call("back", {"aside": 99})[0] == 400
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(p), raising=False)
    call("files")
    assert opened == [str(peers.downloads())]
    assert call("join", {"address": "evil.com", "code": "AAAABBBB"})[0] == 400
    assert call("remove", {"id": i})[1]["pcs"] == [] and access.peers() == {}
    h.ringer.stop()


def test_words_and_names(home):
    src = "".join(open(m.__file__, encoding="utf-8").read() for m in (peers, sync))
    for e in re.findall(r'audit\.record\("([a-z_]+)"', src):
        assert e in timeline._WORDS, e
    assert netlog.service("192.168.1.5")[0] == "Your own network" and netlog.service("evil.com")[0] == "Other web addresses" and netlog.service("ntfy.sh")[1] == "you"
    made = set(re.findall(r'id="(dv[A-Za-z0-9]+)"', HTML))
    for i in re.findall(r'\$\("(dv[A-Z][A-Za-z0-9]*)"\)', HTML):
        assert i in made, i


def test_old_databases_get_the_new_tables(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "x.db")
    storage.migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == len(storage.MIGRATIONS) >= 15
    assert {"sync_items", "sync_lost"} <= {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    c.close()

"""Phase 9, part 1: what goes out, Local only, microphone and screen uses, what is kept, the timeline.

Temporary database, settings and record; nothing goes online (lookups are caught before Windows gets them)."""
import json
import socket
import sqlite3
import threading
import time
from datetime import date, timedelta

import pytest

from jarvis import agents, audit, fit, guard, life, mail, netlog, people, plans, privacy, providers, schedule, storage, timeline, tools

TODAY = date.today()


def day(n):
    return (TODAY + timedelta(days=n)).isoformat()


@pytest.fixture
def db(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    monkeypatch.setattr(plans, "_HOLD", "")
    monkeypatch.setattr(plans, "_PLAN", None)
    monkeypatch.setattr(privacy, "CHANGED", None)
    for d in (privacy._ACTIVE, privacy._LAST, timeline._CACHE):
        d.clear()
    while not netlog._QUEUE.empty():
        netlog._QUEUE.get()
    mail.clear_seen()
    tools.STOP.clear()
    yield tmp_path
    netlog._ON = netlog._LOCAL = False
    privacy._ACTIVE.clear()
    mail.clear_seen()
    storage.close()


@pytest.fixture
def listening(db, monkeypatch):
    """netlog on, without its hook (tests call it themselves): nothing real is looked up."""
    monkeypatch.setattr(netlog, "_ON", True)
    monkeypatch.setattr(netlog, "_LOCAL", False)
    return db


def look(host, event="socket.getaddrinfo"):
    netlog._hook(event, (host, 443, 0, 0, 0) if event == "socket.getaddrinfo" else (None, (host, 443)))


# ---------------- the database ----------------
def test_an_upgrade_cut_short_leaves_nothing_half_made(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "MIGRATIONS", ["CREATE TABLE a (x TEXT);", "CREATE TABLE b (x TEXT); CREATE TABLE b (y TEXT);"])
    c = sqlite3.connect(tmp_path / "x.db")
    with pytest.raises(sqlite3.Error):
        storage.migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    assert [r[0] for r in c.execute("SELECT name FROM sqlite_master")] == ["a"]          # b isn't there: the next start can try again
    monkeypatch.setattr(storage, "MIGRATIONS", ["CREATE TABLE a (x TEXT);", "CREATE TABLE b (x TEXT DEFAULT 'a;b' -- note; here\n); CREATE TABLE d (y TEXT);\n-- the end\n"])
    assert storage.migrate(c) == 2 and storage.migrate(c) == 2
    assert {r[0] for r in c.execute("SELECT name FROM sqlite_master")} == {"a", "b", "d"}


def test_two_at_once_upgrade_it_once(tmp_path):
    db, errors = tmp_path / "y.db", []

    def go():
        try:
            c = sqlite3.connect(db, timeout=20)
            assert storage.migrate(c) == len(storage.MIGRATIONS)
            c.close()
        except Exception as e:
            errors.append(e)
    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors


# ---------------- what goes out ----------------
@pytest.mark.parametrize("host,here", [("127.0.0.1", True), ("localhost", True), ("LOCALHOST.", True), ("::1", True), ("[::1]", True), (b"127.0.0.1", True), (None, True), ("", True), ("127.5.5.5", True),
                                       ("::ffff:127.0.0.1", True), ("0.0.0.0", True), ("example.com", False), ("127.0.0.1.evil.com", False), ("localhost.evil.com", False), ("192.168.1.5", False),
                                       ("10.0.0.1", False), ("8.8.8.8", False), ("127.1", False), ("2130706433", False), ("::2", False), ("fe80::1%12", False)])
def test_this_pc_and_everything_else(host, here):
    assert netlog.is_here(host) is here


def test_counted_by_service_and_day(listening):
    for h in ("api.groq.com", "api.groq.com", "API.GROQ.COM.", "ur.wikipedia.org", "notgroq.com", "evilapi.groq.com.evil.org", "127.0.0.1", "localhost"):
        look(h)
    look("140.82.1.1", "socket.connect")                                                  # (its lookup was counted)
    netlog._note("api.groq.com", "2048")
    r = netlog.report(1)
    by = {s["name"]: s for s in r["services"]}
    assert by["Groq"]["n"] == 3 and by["Groq"]["bytes"] == 2048 and by["Groq"]["kind"] == "ai"
    assert by["Wikipedia"]["n"] == 1 and by["Other web addresses"]["n"] == 2
    assert {h["host"] for h in by["Other web addresses"]["hosts"]} == {"notgroq.com", "evilapi.groq.com.evil.org"}
    assert r["total"] == 6 and r["line"][-1]["n"] >= 5 and len(r["line"]) == 14 and not r["local_only"]
    assert [s["kind"] for s in r["services"]] == ["ai", "you", "web"]


def test_many_messages_over_one_connection(listening):
    look("api.groq.com")
    for _ in range(5):
        netlog._note("api.groq.com", "10")
    s = netlog.report(1)["services"][0]
    assert s["n"] == 5 and s["bytes"] == 50


def test_off_means_nothing_is_kept_and_clear(listening):
    schedule.set_setting("net_log", False)
    look("api.groq.com")
    assert netlog.report(1)["total"] == 0 and netlog.report(1)["on"] is False
    schedule.set_setting("net_log", True)
    look("api.groq.com")
    assert netlog.report(1)["total"] == 1
    assert netlog.clear() == 1 and netlog.report(1)["total"] == 0


def test_old_days_go(listening):
    look("api.groq.com")
    netlog.flush()
    with storage._LOCK, storage.conn() as c:
        c.execute("INSERT INTO net_log(day, host, opened) VALUES (?, 'old.com', 4)", (day(-31),))
        c.execute("INSERT INTO net_log(day, host, opened) VALUES (?, 'week.com', 2)", (day(-6),))
    assert netlog.report(30)["total"] == 3 and netlog.report(7)["total"] == 3 and netlog.report(1)["total"] == 1
    assert netlog.tidy() == 1
    schedule.set_setting("net_log_days", 12345)
    assert netlog.kept_days() == 30


def test_a_broken_database_is_no_reason_to_stop(listening, monkeypatch, capsys):
    look("api.groq.com")
    monkeypatch.setattr(storage, "conn", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
    assert netlog.flush() == 1
    assert "couldn't keep" in capsys.readouterr().out
    n = privacy.begin("mic", "x")
    privacy.end(n)
    privacy.look("screen", "y")


# ---------------- Local only ----------------
def test_local_only_refuses_everything_but_this_pc(listening):
    netlog.set_local_only(True)
    for h in ("example.com", "api.groq.com", "192.168.1.1", "8.8.8.8", "2001:db8::1", "127.1"):
        for event in ("socket.getaddrinfo", "socket.connect"):
            with pytest.raises(OSError, match="Local only"):
                look(h, event)
    for h in ("127.0.0.1", "localhost", "::1"):
        for event in ("socket.getaddrinfo", "socket.connect"):
            look(h, event)
    netlog._hook("socket.connect", (None, "a pipe"))
    netlog._hook("open", ("x", "r", 0))
    r = netlog.report(1)
    assert r["total"] == 0 and r["refused"] == 12 and r["local_only"]
    netlog.set_local_only(False)
    look("example.com")
    assert not netlog.local_only()


def test_only_a_real_true_turns_it_on(listening):
    for v in ("true", 1, "yes", None):
        netlog.set_local_only(v)
        assert netlog.local_only() is False and schedule.get_setting("local_only") is False


def test_the_real_hook_stops_real_lookups(db):
    """Real sockets: nothing gets as far as Windows, not even over a connection that is open already."""
    schedule.set_setting("local_only", True)
    netlog.install()
    assert netlog.local_only()
    import urllib.request
    with pytest.raises(OSError, match="Local only"):
        socket.getaddrinfo("example.com", 80)
    with pytest.raises(OSError, match="Local only"):
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    with pytest.raises(OSError, match="Local only"):
        s.connect(("192.0.2.1", 53))
    s.close()
    with pytest.raises(OSError, match="Local only"):
        urllib.request.urlopen("https://example.com", timeout=2)
    import requests
    with pytest.raises(requests.ConnectionError, match="Local only"):
        requests.get("https://example.com", timeout=2)
    import httpx2
    with pytest.raises(httpx2.ConnectError, match="Local only"):
        httpx2.Client().get("https://example.com")
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    c = socket.create_connection(("127.0.0.1", srv.getsockname()[1]), timeout=5)       # this PC is fine (Ollama)
    c.close()
    srv.close()
    assert netlog.report(1)["refused"] >= 6


def test_ai_voices_and_calls_follow_local_only(listening, monkeypatch):
    from jarvis import live, local_stt, local_tts, stt, tts
    monkeypatch.setenv("GEMINI_API_KEY", "x" * 39)
    monkeypatch.setenv("GROQ_API_KEY", "x" * 39)
    monkeypatch.setattr(live, "genai", object())
    monkeypatch.setattr(local_stt, "ready", lambda: False)
    monkeypatch.setattr(local_tts, "available", lambda: True)
    monkeypatch.setattr(local_tts, "pick", lambda text, lang=None: "amy")
    monkeypatch.setitem(providers._net, "at", time.time())
    monkeypatch.setitem(providers._net, "up", True)
    schedule.set_setting("tts_engine", "online")
    assert live.available() and providers.online() and "whisper" in stt.engines() and tts.local_voice("hi") is None
    netlog.set_local_only(True)
    assert not live.available() and not providers.online() and stt.engines() == [] and tts.local_voice("hi") == "amy"
    monkeypatch.setattr(local_stt, "ready", lambda: True)
    assert stt.engines() == ["local"]
    cloud, here = ("Gemini", object()), ("Local AI", object())
    assert providers.route([cloud, here], "hi") == ([here], "Local only: using the AI on this PC")
    assert providers.route([cloud], "hi")[0] == []
    said = []
    b = providers.MultiBrain.__new__(providers.MultiBrain)
    b.backends, b.on_text, b.on_tool = [cloud], said.append, lambda *a: None
    assert "Local only is on" in b.ask("hi") and said


def test_tools_that_go_online_in_another_program_are_refused(listening, monkeypatch):
    opened = []
    monkeypatch.setattr(tools.webbrowser, "open", lambda u: opened.append(u))
    ctx = tools.ToolContext(confirm=lambda q, kind=None: True, notify=lambda *a: None)
    netlog.set_local_only(True)
    for name, args in (("open_website", {"url": "x.com"}), ("search_web_in_browser", {"query": "x"}), ("play_youtube", {"query": "x"}), ("software", {"action": "search", "query": "x"}),
                       ("software", {"action": "INSTALL", "id": "x"}), ("software", {}), ("network", {"action": "check"}), ("network", {"action": "speed"})):
        out, err = tools.execute(name, args, ctx)
        assert err and "Local only is on" in str(out), name
    assert not opened
    asked = []
    ctx.confirm = lambda q, kind=None: asked.append(q) or False
    tools.execute("run_powershell", {"command": "echo hi", "reason": "t"}, ctx)
    assert "can't hold back" in asked[0]
    netlog.set_local_only(False)
    tools.execute("run_powershell", {"command": "echo hi", "reason": "t"}, ctx)
    assert "can't hold back" not in asked[1]
    tools.execute("open_website", {"url": "x.com"}, ctx)
    assert opened == ["https://x.com"]


# ---------------- microphone and screen ----------------
def test_uses_are_noted_and_merged(db, monkeypatch):
    told = []
    monkeypatch.setattr(privacy, "CHANGED", lambda: told.append([a["why"] for a in privacy.active()]))
    with privacy.using("mic", "Live call"):
        assert [(a["what"], a["why"]) for a in privacy.active()] == [("mic", "Live call")]
        assert privacy.uses(1)[0]["now"] is True
    with privacy.using("mic", "Live call"):                             # again within two minutes: one use
        pass
    with privacy.using("mic", "Looking", show=False):
        assert privacy.active() == []
    privacy.look("screen", "The assistant looked at the screen")
    u = privacy.uses(1)
    assert sorted(x["why"] for x in u) == ["Live call", "Looking", "The assistant looked at the screen"] and not any(x["now"] for x in u)
    assert [x["what"] for x in privacy.uses(1, "screen")] == ["screen"]
    assert told[0] == ["Live call"] and told[1] == []
    assert privacy.clear_uses() == 3 and privacy.uses(1) == []


def test_a_use_ends_also_after_a_fault(db):
    with pytest.raises(RuntimeError):
        with privacy.using("mic", "x"):
            raise RuntimeError
    assert privacy.active() == []
    privacy.end(None)
    privacy.end(999)


def test_a_test_copy_never_opens_the_microphone_not_even_with_windows_recogniser(db, monkeypatch):
    from jarvis import hud
    heard = []
    monkeypatch.setattr(hud, "windows_listen", lambda: heard.append(1) or "hello")
    h = hud.Hub.__new__(hud.Hub)
    h.busy, h.set_state, h.heard = False, lambda s: None, lambda t: heard.append(t)
    monkeypatch.setenv("JARVIS_NO_MIC", "1")
    h.listen_once()
    assert heard == []
    monkeypatch.delenv("JARVIS_NO_MIC")
    h.listen_once()
    assert heard == [1, "hello"] and privacy.uses(1)[0]["why"].startswith("You talked to it")


def test_a_long_use_is_written_while_it_goes_on(db):
    n = privacy.begin("mic", "Waiting for its name")
    with storage._LOCK, storage.conn() as c:
        c.execute("UPDATE sensor_log SET start = ?, end = ?", (f"{day(0)} 00:00:00", f"{day(0)} 00:00:01"))
    privacy._beat()
    assert privacy.uses(1)[0]["seconds"] >= 0 and privacy.uses(1)[0]["end"] != f"{day(0)} 00:00:01"
    privacy.end(n)


def test_clearing_while_in_use_and_off(db):
    n = privacy.begin("mic", "x")
    privacy.clear_uses()
    privacy.end(n)                                                      # (its row is gone)
    assert privacy.uses(1) == []
    schedule.set_setting("sensor_log", False)
    with privacy.using("mic", "y"):
        assert privacy.active()                                         # the sign on the page doesn't depend on the list
    assert privacy.uses(1) == []


def test_tools_note_their_looks(db, monkeypatch):
    ctx = tools.ToolContext(confirm=lambda q, kind=None: True, notify=lambda *a: None)
    for name in ("look_at_screen", "take_screenshot", "read_screen_text", "clipboard"):
        monkeypatch.setitem(tools._HANDLERS, name, lambda inp, c: "done")
    tools.execute("look_at_screen", {}, ctx)
    tools.execute("take_screenshot", {}, ctx)
    tools.execute("read_screen_text", {"source": "window"}, ctx)
    tools.execute("read_screen_text", {"source": "file", "path": "x"}, ctx)
    tools.execute("clipboard", {"action": "read"}, ctx)
    tools.execute("clipboard", {"action": "write", "text": "x"}, ctx)
    assert sorted(u["what"] for u in privacy.uses(1)) == ["clipboard", "screen", "screen", "screen"]


# ---------------- Windows' own list ----------------
def test_windows_list(db, monkeypatch):
    ft = lambda t: int((t + 11_644_473_600) * 10_000_000)               # noqa: E731
    now = time.time()
    rows = [("C:#Program Files#Chat#Chat.exe", False, {"LastUsedTimeStart": ft(now - 60), "LastUsedTimeStop": 0}),
            ("C:#Old#Crashed.exe", False, {"LastUsedTimeStart": ft(now - 90000), "LastUsedTimeStop": 0}),
            ("Microsoft.WindowsCamera_8wekyb3d8bbwe", True, {"LastUsedTimeStart": ft(now - 500), "LastUsedTimeStop": ft(now - 400), "Value": "Deny"}),
            ("Never.Used_x", True, {"Value": "Allow"}), ("C:#Odd.exe", False, {"LastUsedTimeStart": "junk"})]
    monkeypatch.setattr(privacy, "_entries", lambda store: iter(rows))
    monkeypatch.setattr(privacy, "_allowed", lambda store: True)
    r = privacy.windows_uses("mic", running={"chat.exe"})
    assert [(a["name"], a["now"], a["allowed"]) for a in r["apps"]] == [("Chat", True, True), ("WindowsCamera", False, False), ("Crashed", False, True)]
    assert r["apps"][0]["path"] == r"C:\Program Files\Chat\Chat.exe" and r["apps"][0]["start"] == time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(now - 60)))
    assert r["never"] == 2
    with pytest.raises(ValueError):
        privacy.windows_uses("..\\evil")


def test_windows_times_that_make_no_sense():
    assert [privacy._when(v) for v in (0, None, "x", -5, 2 ** 70)] == [""] * 5


# ---------------- what is kept ----------------
def test_everything_kept_is_listed_and_no_secret_shown(db, monkeypatch):
    from jarvis import keystore
    monkeypatch.setattr(keystore, "load", lambda *a: {"GROQ_API_KEY": "gsk_" + "s" * 24})
    k = privacy.kept()
    by = {i["id"]: i for i in k["items"]}
    assert by["keys"]["n"] == 1 and "gsk_" not in json.dumps(k) and by["keys"]["clear"] is False
    assert {i["id"] for i in k["items"] if i["clear"]} == {"conversations", "record", "net", "uses", "voice", "screenshots", "log"}
    assert k["keep"] == {"conversations": 0, "screenshots": 0, "record": 0, "logs": 30} and k["voice_debug"] is False and k["database"] > 0


@pytest.mark.parametrize("what", ["memories", "journal", "keys", "mail", "models", "", "../x", None])
def test_only_these_can_be_cleared_here(db, what):
    with pytest.raises(ValueError):
        privacy.clear(what)


def test_clearing(db, monkeypatch, tmp_path):
    from jarvis import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    storage.add_event({"type": "user", "text": "hello"})
    audit.record("tool", tool="x", ok=True)
    (tmp_path / "jarvis.log").write_text("heard things")
    (tmp_path / "voice_debug").mkdir()
    for n in ("1.wav", "1.json", "keep.txt"):
        (tmp_path / "voice_debug" / n).write_text("x")
    assert privacy.clear("conversations") == 1 and storage.count_events() == 0
    assert privacy.clear("voice") == 1 and [f.name for f in (tmp_path / "voice_debug").iterdir()] == ["keep.txt"]
    assert privacy.clear("log") == 1 and (tmp_path / "jarvis.log").read_text() == ""
    n = len(audit.recent(100))
    assert n >= 4 and privacy.clear("record") == n
    left = audit.recent(100)
    assert [e["event"] for e in left] == ["record_cleared"] and left[0]["lines"] == n


def test_the_log_can_be_cleared_while_it_is_open(db, monkeypatch, tmp_path):
    from jarvis import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    f = open(tmp_path / "jarvis.log", "a", encoding="utf-8", buffering=1)
    f.write("before\n")
    privacy.clear("log")
    f.write("after\n")
    f.close()
    assert (tmp_path / "jarvis.log").read_text() == "after\n"


def test_screen_pictures_go_to_the_recycle_bin(db, monkeypatch, tmp_path):
    from jarvis import config
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "it's.jpg").write_bytes(b"x")
    (shots / "b.jpg").write_bytes(b"x")
    monkeypatch.setattr(config, "SCREENSHOT_DIR", shots)
    ran = []

    def ps(script, timeout=60):
        ran.append(script)
        [f.unlink() for f in shots.iterdir()]
    monkeypatch.setattr(tools, "_ps", ps)
    assert privacy.clear("screenshots") == 2
    assert "SendToRecycleBin" in ran[0] and "it''s.jpg" in ran[0]


# ---------------- how long ----------------
@pytest.mark.parametrize("bad", [{"conversations": 1}, {"logs": 0}, {"record": 7}, {"screenshots": True}, {"conversations": "7"}, {"logs": None}, {"conversations": 30, "logs": 9999}])
def test_only_the_times_in_the_list(db, bad):
    with pytest.raises(ValueError):
        privacy.set_keeping(bad)
    assert privacy.keeping() == {"conversations": 0, "screenshots": 0, "record": 0, "logs": 30}       # (all or nothing)


def fill(db):
    with storage._LOCK, storage.conn() as c:
        for n in (0, -10, -100):
            c.execute("INSERT INTO events(at, type, data) VALUES (?, 'user', ?)", (f"{day(n)} 10:00:00", json.dumps({"type": "user", "text": f"said {n}", "time": "10:00:00"})))
            c.execute("INSERT INTO sensor_log(what, why, start, end) VALUES ('mic', 'x', ?, ?)", (f"{day(n)} 10:00:00", f"{day(n)} 10:01:00"))
    audit.file().write_text("".join(json.dumps({"time": f"{day(n)} 11:00:00", "event": "tool", "tool": f"t{-n}", "ok": True}) + "\n" for n in (-100, -10, 0)), encoding="utf-8")


def test_nothing_goes_by_itself_at_first(db):
    fill(db)
    out = privacy.tidy()
    assert out == {"uses": 1, "net": 0} and storage.count_events() == 3 and len(audit.recent(10)) == 3


def test_old_things_go_when_you_chose_so(db):
    fill(db)
    privacy.set_keeping({"conversations": 7, "record": 30, "logs": 7})
    out = privacy.tidy()
    assert out["conversations"] == 2 and out["uses"] == 2 and out["record"] == 1
    assert [e["text"] for e in storage.recent_events()] == ["said 0"]
    kept = audit.recent(20)
    assert [e.get("tool") for e in kept if e["event"] == "tool"] == ["t10", "t0"] and kept[-1]["event"] == "old_things_cleared"


def test_a_line_that_cant_be_read_stays(db):
    audit.file().write_text('not json\n{"time": "2020-01-01 00:00:00", "event": "x"}\n{"time": "junk"}\n', encoding="utf-8")
    assert audit.drop_before("2021-01-01") == 1
    assert audit.file().read_text(encoding="utf-8").splitlines() == ["not json", '{"time": "junk"}']


# ---------------- the timeline ----------------
def test_a_day_has_everything_newest_first(db):
    storage.add_event({"type": "user", "text": "what's the weather", "source": "voice"})
    storage.add_event({"type": "jarvis", "text": "Sunny.", "provider": "Groq"})
    storage.add_event({"type": "tool", "name": "get_weather", "args": ""})          # (the record has it)
    storage.add_event({"type": "notify", "text": "Alarm: wake up"})
    audit.record("tool", tool="get_weather", args={"city": "Karachi", "api_key": "gsk_" + "x" * 24}, ok=True, result="Sunny")
    audit.record("approval", kind="powershell", question="Run this?", granted=False)
    audit.record("blocked", tool="run_powershell", command="format c:", reason="formatting")
    audit.record("permission_changed", kind="lock", rule="never")
    audit.record("local_only", on=True)
    privacy.look("screen", "The assistant looked at the screen")
    rows = timeline.of_day(day(0))
    assert {r["kind"] for r in rows} == {"you", "answer", "reminder", "action", "approval", "change", "use"} and len(rows) == 9
    assert [r["at"] for r in rows] == sorted((r["at"] for r in rows), reverse=True)
    by = {r["title"]: r for r in rows}
    assert by["get weather"]["text"] == "city: Karachi, api_key: [hidden]" and by["Not allowed"]["ok"] is False and by["Refused"]["ok"] is False
    assert by["Groq"]["text"] == "Sunny." and by["Local only was turned on"]["kind"] == "change"
    assert "gsk_" not in json.dumps(rows)
    assert [r["kind"] for r in timeline.of_day(day(0), ["you"])] == ["you"]
    assert timeline.of_day(day(-1)) == [] and len(timeline.of_day(day(0), ["nonsense"])) == 0


@pytest.mark.parametrize("bad", ["", None, "yesterday", "2026-13-01", "2026-02-30", "x' OR 1=1", 5])
def test_only_real_days(db, bad):
    with pytest.raises(ValueError):
        timeline.of_day(bad)


def test_search(db):
    fill(db)
    storage.add_event({"type": "user", "text": "کل کا موسم کیسا تھا؟"})
    storage.add_event({"type": "user", "text": "100% of it_all"})
    assert {r["text"] for r in timeline.search("SAID 10")} == {"said -100", "said -10"}
    assert len(timeline.search("موسم")) == 1 and len(timeline.search("100% it_all")) == 1 and timeline.search("10%") == []
    assert [r["kind"] for r in timeline.search("t10")] == ["action", "action"]                       # t10 and t100
    assert timeline.search("zebra") == []
    with pytest.raises(ValueError):
        timeline.search("  ")


def test_days_strip_and_often(db):
    fill(db)
    line = timeline.days(35)
    assert len(line) == 35 and line[-1] == {"day": day(0), "n": 2} and line[-11]["n"] == 2 and line[0]["n"] == 0
    for t in ("Play Quran!", "play quran", "weather", "x" * 200, "x" * 200):
        storage.add_event({"type": "user", "text": t})
    storage.add_event({"type": "user", "text": "sched", "source": "scheduled"})
    storage.add_event({"type": "user", "text": "sched", "source": "scheduled"})
    o = timeline.often()
    assert len(o) == 1 and o[0]["n"] == 2 and "play quran" in o[0]["text"].lower()


def test_take_one_thing_or_a_day_out(db):
    fill(db)
    storage.add_event({"type": "jarvis", "text": "secret answer", "time": "12:00:00"})
    rid = next(r["id"] for r in timeline.of_day(day(0)) if r["text"] == "secret answer")
    assert timeline.remove(rid) == [{"type": "jarvis", "time": "12:00:00", "text": "secret answer"}]
    assert timeline.remove(rid) == []
    for bad in ("a0", "u1", "e1; DROP TABLE events", "", None, "e"):
        with pytest.raises(ValueError):
            timeline.remove(bad)
    assert len(timeline.remove(whole_day=day(-10))) == 1 and storage.count_events() == 2
    assert len([r for r in timeline.of_day(day(-10)) if r["kind"] == "action"]) == 1                 # the record stays
    assert [e["event"] for e in audit.recent(5)][-2:] == ["timeline_removed", "timeline_removed"]


def test_the_record_is_read_again_when_it_changed(db):
    audit.record("tool", tool="one", ok=True)
    assert len(timeline.of_day(day(0))) == 1
    audit.record("tool", tool="two", ok=True)
    assert len(timeline.of_day(day(0))) == 2
    audit.clear()
    assert [r["title"] for r in timeline.of_day(day(0))] == ["The record of actions was cleared"]


def test_csv_is_safe_and_never_over_a_file(db, tmp_path):
    storage.add_event({"type": "user", "text": "=cmd|' /C calc'!A0"})
    rows = timeline.of_day(day(0))
    a, b = timeline.export(rows, "T", tmp_path / "Documents"), timeline.export(rows, "T", tmp_path / "Documents")
    assert a.name == "T.csv" and b.name == "T (2).csv"
    assert "'=cmd" in a.read_text(encoding="utf-8-sig") and "When,Kind,Title,Text" in a.read_text(encoding="utf-8-sig")


# ---------------- the AI ----------------
def test_the_ai_reads_the_conversation_only_after_a_yes(db):
    storage.add_event({"type": "user", "text": "my flight is on Friday"})
    storage.add_event({"type": "jarvis", "text": "Noted."})
    audit.record("tool", tool="run_powershell", ok=True)
    asked, answer = [], [False]
    ctx = tools.ToolContext(confirm=lambda q, kind=None: asked.append((q, kind)) or answer[0], notify=lambda *a: None)
    out, err = tools.execute("history", {"action": "search", "query": "flight"}, ctx, from_ai=True)
    assert "didn't read" in out and asked[0][1] == "history" and "flight" in asked[0][0] and not mail.recently_seen()
    answer[0] = True
    out, err = tools.execute("history", {"action": "day", "day": "today"}, ctx, from_ai=True)
    assert "my flight is on Friday" in out and "Noted." in out and "untrusted" in out and "powershell" not in out
    assert mail.recently_seen()                                          # nothing is carried out after it without asking
    assert "flight" not in json.dumps(audit.recent(20)[-1])              # neither the words nor what was found
    assert "isn't a day" in tools.execute("history", {"action": "day", "day": "soon"}, ctx)[0]
    assert "look for" in tools.execute("history", {"action": "search"}, ctx)[0]


def test_history_is_in_every_list_it_must_be_in():
    from jarvis import automations, hud
    assert "history" in hud.Hub.PERMISSION_KINDS and "history" in hud.Hub.TRUSTABLE and "history" in guard.READ_BACK
    assert "history" not in agents.AGENT_TOOLS and "history" in providers.LOCAL_TOOLS and "history" in providers.BIG_TOOLS
    assert not any("history" in json.dumps(s) for s in automations.STEP_TOOLS)
    for name in ("privacy", "netlog", "timeline", "local_only"):
        assert name not in tools._HANDLERS


# ---------------- permissions for an hour ----------------
@pytest.fixture
def hub(db, monkeypatch):
    from jarvis import hud
    monkeypatch.setattr(hud.Hub, "CONFIRM_TIMEOUT", 0.05)
    h = hud.Hub()
    monkeypatch.setattr(hud, "HUB", h)
    yield h
    h.ringer.stop()
    h.scheduler.stop() if hasattr(h.scheduler, "stop") else None


def test_an_hour(hub, monkeypatch):
    assert hub.confirm("Run?", kind="powershell") is False               # (nobody answers)
    hub.allow_hour("powershell")
    assert hub.confirm("Run?", kind="powershell") is True and 3500 < hub.hour_left("powershell") <= 3600
    monkeypatch.setitem(hub.hour, "powershell", time.monotonic() - 1)
    assert hub.confirm("Run?", kind="powershell") is False and hub.hour == {}
    for kind in ("power", "clean", "overwrite", "software", "email_draft", "after_email", "force_close", "x", "", None):
        with pytest.raises(ValueError):
            hub.allow_hour(kind)
    hub.allow_hour("lock")
    hub.set_permissions({"lock": "never"})
    assert hub.confirm("Lock?", kind="lock") is False and hub.hour == {}
    hub.allow_hour("lock")                                               # from Never: Ask, with the hour
    assert hub.permission("lock") == "ask" and hub.confirm("Lock?", kind="lock") is True
    hub.emergency_stop()
    assert hub.hour == {} and hub.confirm("Lock?", kind="lock") is False


def test_ask_everything_again(hub):
    hub.set_permissions({"powershell": "allow", "lock": "never"})
    hub.trusted.add("email")
    hub.allow_hour("wifi_off")
    hub.ask_again()
    assert set(hub.permissions().values()) == {"ask"} and not hub.trusted and not hub.hour


def test_local_only_ends_a_call_and_refuses_a_new_one(hub, monkeypatch):
    stopped, closed, said = [], [], []
    monkeypatch.setattr(netlog, "_ON", True)
    monkeypatch.setattr(hub, "live_stop", lambda why="": stopped.append(why))
    monkeypatch.setattr(mail, "close", lambda: closed.append(1))
    monkeypatch.setattr(hub, "emit", lambda *a, **k: said.append((a, k)))
    hub.set_local_only(True)
    assert stopped == ["Local only"] and closed == [1] and audit.recent(1)[0]["event"] == "local_only"
    monkeypatch.delenv("JARVIS_NO_MIC", raising=False)
    hub.live_start()
    assert hub.live is None and "Local only" in said[-1][1]["text"]
    hub._pulling = None
    hub.local_pull("llama")
    assert "Local only" in said[-1][1]["status"]


# ---------------- the page's requests ----------------
def call(page, action, data=None):
    from jarvis import hud
    got = []
    h = hud.Handler.__new__(hud.Handler)
    h._json = lambda d, status=200: got.append((status, d))
    h._daily_api(page, action, data or {})
    return got[0]


def test_every_request_of_the_page(hub, monkeypatch):
    from jarvis import hud
    opened = []
    monkeypatch.setattr(hud.os, "startfile", opened.append, raising=False)
    st, o = call("privacy", "overview")
    assert st == 200 and {a["id"] for a in o["access"]} >= {"journal", "fitness", "names", "never"} and o["net"]["total"] == 0
    assert call("privacy", "net", {"days": 7})[1]["days"] == 7 and call("privacy", "net", {"days": 99})[1]["days"] == 1
    assert call("privacy", "uses", {"days": 1})[1]["on"] is True and call("privacy", "uses", {"on": False})[1]["on"] is False
    assert call("privacy", "kept")[1]["items"]
    assert call("privacy", "perms")[1]["perms"][0]["rule"] == "ask"
    assert call("privacy", "rule", {"kind": "power", "rule": "allow"})[1]["perms"][3]["rule"] == "ask"         # never Allow for these
    assert call("privacy", "hour", {"kind": "power"})[0] == 400 and call("privacy", "hour", {"kind": "lock"})[0] == 200
    assert call("privacy", "kept", {"keep": {"conversations": 3}})[0] == 400 and call("privacy", "kept", {"keep": {"conversations": 90}})[1]["keep"]["conversations"] == 90
    assert call("privacy", "kept", {"voice_debug": "yes"})[1]["voice_debug"] is False and call("privacy", "kept", {"voice_debug": True})[1]["voice_debug"] is True
    assert call("privacy", "clear", {"what": "keys"})[0] == 400 and call("privacy", "windows", {"what": "x"})[0] == 400
    assert call("privacy", "windows_open", {"what": "calc.exe"})[0] == 400 and not opened
    assert call("privacy", "windows_open", {"what": "camera"})[0] == 200 and opened == ["ms-settings:privacy-webcam"]
    assert call("privacy", "nope")[0] == 404 and call("time", "nope")[0] == 404
    assert call("time", "load", {"day": "x"})[0] == 400 and call("time", "load", {"kinds": "you"})[0] == 200


def test_who_may_read_what(hub):
    def on(i):
        return next(a for a in call("privacy", "overview")[1]["access"] if a["id"] == i)["on"]
    for i, get in (("journal", lambda: life.settings()["journal_ai"]), ("fitness", lambda: fit.settings()["ai"]), ("names", lambda: people.settings()["use_names"])):
        assert on(i) is False
        call("privacy", "access", {"id": i, "on": "true"})
        assert get() is False
        call("privacy", "access", {"id": i, "on": True})
        assert get() is True and on(i) is True
    assert call("privacy", "access", {"id": "email", "on": True})[0] == 400


def test_permission_counts(hub):
    for yes in (True, True, False):
        audit.record("approval", kind="lock", question="?", granted=yes)
    p = next(x for x in call("privacy", "perms")[1]["perms"] if x["kind"] == "lock")
    assert (p["yes"], p["no"]) == (2, 1) and p["last"]


def test_removed_things_leave_the_open_page_too(hub):
    hub.emit("user", keep=True, text="forget me")
    hub.emit("user", keep=True, text="keep me")
    rid = next(r["id"] for r in timeline.of_day(day(0)) if r["text"] == "forget me")
    assert call("time", "remove", {"id": rid})[1]["removed"] == 1
    assert [h["text"] for h in hub.history if h["type"] == "user"] == ["keep me"]
    call("privacy", "clear", {"what": "conversations"})
    assert hub.history == []


def test_the_voice_is_kept_only_if_you_turned_it_on(db, monkeypatch, tmp_path):
    recorder = pytest.importorskip("jarvis.recorder")
    monkeypatch.setattr(recorder, "DEBUG_DIR", tmp_path / "vd")
    recorder._save_debug(b"x", {})
    assert not (tmp_path / "vd").exists()
    schedule.set_setting("voice_debug", True)
    recorder._save_debug(b"x", {})
    assert len(list((tmp_path / "vd").glob("*.wav"))) == 1


def test_the_window_is_held_back_too():
    from jarvis import hud
    html = hud.HTML_FILE.read_text(encoding="utf-8")
    import re
    cut = re.sub(r"<link[^>]+fonts\.g[^>]+>\s*", "", html)
    assert "fonts.googleapis.com" in html and "fonts.g" not in cut
    assert "https:" not in hud.LOCAL_CSP and "http:" not in hud.LOCAL_CSP and "*" not in hud.LOCAL_CSP and "connect-src 'self'" in hud.LOCAL_CSP
    meta = re.search(r'm\.content = "([^"]+)"', html)[1]
    assert "http" not in meta and "*" not in meta and "default-src 'self'" in meta

"""Phase 8, part 1: the clock. Temporary database and settings; nothing makes a sound."""
import json
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone

import pytest

from jarvis import agents, audit, automations, clock, guard, plans, providers, schedule, storage, tools


@pytest.fixture
def db(tmp_path, monkeypatch):
    clock.stop()
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(schedule, "ALARMS_FILE", tmp_path / "alarms.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    monkeypatch.setattr(plans, "_HOLD", "")
    monkeypatch.setattr(plans, "_PLAN", None)
    monkeypatch.setattr(tools, "RINGER", None)
    tools.STOP.clear()
    yield tmp_path
    clock.stop()
    storage.close()


def ctx():
    return tools.ToolContext(confirm=lambda q, **k: True, notify=lambda *a, **k: None)


def call(tool_, **args):
    return tools.execute(tool_, args, ctx())[0]


def due(now=None):
    got = []
    clock.run_due(lambda text, label, ring: got.append((text, label, ring)), now)
    return got


# ---------------- timers ----------------
def test_a_timer_is_kept_and_ends_once(db):
    t = clock.add(60, "  eggs \n now ")
    assert t["label"] == "eggs now" and 59 < t["left"] <= 60 and t["id"] == 1
    storage.close()                                                   # the app was closed and opened again
    assert [x["label"] for x in clock.timers()] == ["eggs now"]
    now = time.time()
    assert due(now + 30) == [] and due(now + 61) == [("Reminder: eggs now", "eggs now", True)] and due(now + 62) == []
    assert clock.add(5)["id"] == 1 and due(time.time() + 6)[0][0] == "Your timer is done."


@pytest.mark.parametrize("bad", [0, -1, 7 * 86400 + 1, "x", None, float("nan"), float("inf")])
def test_bad_lengths(db, bad):
    with pytest.raises(ValueError):
        clock.add(bad)
    assert clock.timers() == []


def test_pause_resume_extend_cancel(db):
    t = clock.add(100, "a")
    p = clock.pause(t["id"])
    assert p["paused"] and 99 < p["left"] <= 100
    assert due(time.time() + 500) == []                                # paused: it doesn't end
    assert clock.pause(t["id"])["left"] == p["left"]                   # twice is the same
    assert clock.extend(t["id"], 60)["paused"] and 159 < clock.timers()[0]["left"] <= 160
    r = clock.pause(t["id"], False)
    assert not r["paused"] and 159 < r["left"] <= 160
    assert clock.extend(t["id"], -9999)["left"] <= 1.01                # never under a second
    assert clock.cancel(t["id"])["label"] == "a" and clock.cancel(t["id"]) is None
    for f in (clock.pause, lambda i: clock.extend(i, 60)):
        with pytest.raises(ValueError):
            f(99)


def test_late_ones_are_told_not_rung(db):
    clock.add(10, "soup")
    (text, _, ring), = due(time.time() + 10 + clock.LATE + 5)
    assert not ring and "soup" in text and "while the app or the PC was off" in text
    clock.add(10, "old")
    assert due(time.time() + clock.FORGET + 60) == [] and clock.timers() == []      # after a day not even that
    clock.add(10, "nap")                                                             # a short sleep of the PC: still rings
    assert due(time.time() + 70)[0][2] is True


def test_at_most_thirty(db):
    for i in range(clock.MAX_TIMERS):
        clock.add(60, str(i))
    with pytest.raises(ValueError):
        clock.add(60)


def test_finding_one(db):
    a, b = clock.add(60, "green tea"), clock.add(90, "black tea")
    assert clock.get("#1")["id"] == a["id"] and clock.get("black")["id"] == b["id"] and clock.get("tea") is None and clock.get("") is None
    clock.cancel(b["id"])
    assert clock.get("")["id"] == a["id"]


def test_the_thread_ends_them_on_time_and_restarts_dont_double(db):
    got, hit = [], threading.Event()

    def done(text, label, ring):
        got.append((text, time.time()))
        hit.set()
    clock.start(lambda *a: got.append(("old thread", 0)))
    clock.start(done)
    start = time.time()
    clock.add(0.4, "quick")
    assert hit.wait(5) and got[0][0] == "Reminder: quick" and abs(got[0][1] - start - 0.4) < 0.4
    time.sleep(0.2)
    assert len(got) == 1


def test_one_failing_end_never_blocks_the_rest(db):
    clock.add(1, "a")
    clock.add(1, "b")
    seen = []

    def done(text, label, ring):
        seen.append(label)
        raise RuntimeError("x")
    assert clock.run_due(done, time.time() + 5) == 2 and sorted(seen) == ["a", "b"] and clock.timers() == []


# ---------------- focus ----------------
def test_focus_rounds_follow_each_other(db):
    clock.focus(25, 5, 2, "book")
    with pytest.raises(ValueError):
        clock.focus()
    def end():
        c = storage.conn()
        with c:
            c.execute("UPDATE timers SET due = ?", (time.time() - 1,))
        return due()[0][0]
    assert end() == "Focus round 1 of 2 is done. Break: 5 minutes."
    assert [(t["kind"], t["total"]) for t in clock.timers()] == [("break", 300)]
    assert end() == "The break is over. Focus round 2 of 2 starts now."
    assert end() == "All 2 focus rounds are done. Well done." and clock.timers() == []
    assert clock.focus_days()[-1]["minutes"] == 50


def test_focus_stopped_or_skipped_keeps_what_was_done(db):
    clock.focus(25, 5, 4)
    c = storage.conn()
    with c:
        c.execute("UPDATE timers SET due = due - 600")                 # ten minutes in
    assert clock.focus_skip()["kind"] == "break" and clock.focus_days()[-1]["minutes"] == 10
    assert clock.focus_skip()["extra"]["round"] == 2
    with c:
        c.execute("UPDATE timers SET due = due - 120")
    clock.focus_stop()
    assert clock.timers() == [] and clock.focus_days()[-1]["minutes"] == 12 and clock.focus_stop() is None
    clock.focus(25, 5, 1)
    clock.focus_stop()                                                 # seconds in: nothing to keep
    assert clock.focus_days()[-1]["minutes"] == 12


def test_focus_that_ended_while_the_pc_was_off_counts_but_stops(db):
    clock.focus(25, 5, 4)
    (text, _, ring), = due(time.time() + 25 * 60 + clock.LATE + 5)
    assert not ring and text.startswith("Your focus round ended at") and clock.timers() == [] and sum(d["minutes"] for d in clock.focus_days()) == 25


@pytest.mark.parametrize("args", [(0, 5, 4), (181, 5, 4), (25, 0, 4), (25, 61, 4), (25, 5, 0), (25, 5, 13), ("x", 5, 4), (25, 5, 1.5)])
def test_focus_limits(db, args):
    with pytest.raises(ValueError):
        clock.focus(*args)
    assert clock.timers() == []


# ---------------- ringing ----------------
class Rings:
    def __init__(self, monkeypatch, every=0.05):
        monkeypatch.setattr(clock, "RING_EVERY", every)
        self.played, self.missed, self.states, self.call = [], [], [], False
        self.r = clock.Ringer(lambda label, first: self.played.append((label, first)), self.states.append, self.missed.append, lambda: self.call)


def test_it_rings_until_stopped(db, monkeypatch):
    x = Rings(monkeypatch)
    rid = x.r.start("wake up", "alarm")
    time.sleep(0.3)
    assert x.played[0] == ("wake up", True) and x.played[1] == ("wake up", False) and len(x.played) > 3 and x.r.list()[0]["id"] == rid
    x.r.stop(rid)
    n = len(x.played)
    time.sleep(0.2)
    assert len(x.played) <= n + 1 and x.r.list() == [] and x.states[-1] == [] and x.missed == []


def test_it_gives_up_and_says_so(db, monkeypatch):
    x = Rings(monkeypatch)
    monkeypatch.setattr(clock, "ring_minutes", lambda: 0.2 / 60)
    x.r.start("wake up", "alarm")
    x.r.start("eggs", "timer")
    time.sleep(0.8)
    assert x.r.list() == [] and x.missed == [f'Nobody stopped the alarm "wake up" ({datetime.now():%H:%M}).'] or len(x.missed) == 1
    assert 2 <= len(x.played) <= 14


def test_once_in_a_call_and_once_if_chosen(db, monkeypatch):
    x = Rings(monkeypatch)
    x.call = True
    x.r.start("a", "timer")
    time.sleep(0.2)
    assert len(x.played) == 1
    x.call = False
    clock.set_ring_minutes(0)
    x.r.start("b", "alarm")
    time.sleep(0.3)
    assert len(x.played) == 2 and x.r.list() == [] and x.missed == []
    for bad in (3, 60, "x", -1, None):
        with pytest.raises(ValueError):
            clock.set_ring_minutes(bad)


def test_snooze(db, monkeypatch):
    x = Rings(monkeypatch, 5)
    x.r.start("wake up", "alarm")
    t = x.r.snooze(10)
    assert t["kind"] == "snooze" and t["label"] == "wake up" and 598 < t["left"] <= 600 and x.r.list() == []
    with pytest.raises(ValueError):
        x.r.snooze(5)                                                  # nothing rings now
    x.r.start("tea", "timer")
    x.r.stop()
    assert x.r.snooze()["total"] == 300                                # a moment after it was stopped
    for bad in (0, 121, "x"):
        with pytest.raises(ValueError):
            x.r.snooze(bad)


def test_a_player_that_fails_still_shows(db, monkeypatch):
    monkeypatch.setattr(clock, "RING_EVERY", 0.05)
    r = clock.Ringer(lambda *a: 1 / 0, lambda rings: None, lambda t: None)
    r.start("x")
    time.sleep(0.15)
    assert r.list()
    r.stop()


# ---------------- stopwatch ----------------
def test_stopwatch(db):
    at = 1000.0
    assert clock.stopwatch(at) == {"running": False, "elapsed": 0.0, "laps": []}
    clock.stopwatch_do("start", at)
    assert clock.stopwatch(at + 5)["elapsed"] == 5
    clock.stopwatch_do("lap", at + 5)
    clock.stopwatch_do("start", at + 6)                                # started twice: it goes on
    storage.close()                                                    # the app was closed: it ran on
    assert clock.stopwatch_do("lap", at + 12.5)["laps"] == [5, 12.5]
    assert clock.stopwatch_do("stop", at + 20)["elapsed"] == 20 and clock.stopwatch(at + 99)["elapsed"] == 20
    clock.stopwatch_do("start", at + 100)
    assert clock.stopwatch(at + 101)["elapsed"] == 21
    assert clock.stopwatch(at - 999)["elapsed"] == 0                   # the PC's clock was put back
    s = clock.stopwatch_do("reset", at + 102)
    assert s == {"running": False, "elapsed": 0.0, "laps": []}
    with pytest.raises(ValueError):
        clock.stopwatch_do("lap")
    with pytest.raises(ValueError):
        clock.stopwatch_do("explode")


def test_stopwatch_text(db):
    assert clock.exact(0) == "00:00.00" and clock.exact(61.239) == "01:01.24" and clock.exact(3599.999) == "1:00:00.00"
    s = {"running": False, "elapsed": 12.5, "laps": [5.0, 12.5]}
    assert clock.describe_stopwatch(s) == "The stopwatch is stopped at 00:12.50. Laps: 1: 00:05.00, 2: 00:07.50."


# ---------------- the time elsewhere ----------------
def test_every_place_works_with_windows_own_zones(db):
    for p in clock.ZONES:
        assert -720 <= clock.place_time(p)["offset"] <= 840, p


@pytest.mark.parametrize("place,month,offset", [("London", 1, 0), ("London", 7, 60), ("New York", 1, -300), ("New York", 7, -240), ("Karachi", 7, 300), ("Makkah", 7, 180),
                                                ("Kathmandu", 1, 345), ("Tehran", 7, 210), ("Sydney", 1, 660), ("Sydney", 7, 600), ("Delhi", 1, 330), ("UTC", 7, 0)])
def test_summer_time(db, place, month, offset):
    assert clock.place_time(place, datetime(2026, month, 15, 12, tzinfo=timezone.utc))["offset"] == offset


def test_places(db):
    assert clock.places() == clock.DEFAULT_PLACES
    assert clock.add_place(" tokyo ") == "Tokyo" and clock.find_place("mecca") == "Makkah" and clock.find_place("istan") == "Istanbul"
    for bad in ("", "Atlantis", "xx", "S", None, "Tokyo' OR 1"):
        with pytest.raises(ValueError):
            clock.find_place(bad)
    with pytest.raises(ValueError):
        clock.add_place("Tokyo")
    clock.remove_place("Tokyo")
    assert "Tokyo" not in clock.places()
    for p in [p for p in clock.ZONES if p not in clock.places()][:clock.MAX_PLACES - 4]:
        clock.add_place(p)
    with pytest.raises(ValueError):
        clock.add_place("UTC")
    schedule.set_setting("world_places", ["Karachi", "Nowhere", 5])
    assert clock.places() == ["Karachi"]
    assert "ahead" in clock.describe_place({"place": "X", "time": "1", "day": "d", "ahead": 60}) and "5:30 hours behind" in clock.describe_place({"place": "X", "time": "1", "day": "d", "ahead": -330})


# ---------------- alarms ----------------
def sched():
    got = []
    return schedule.Scheduler(lambda t, k: got.append((t, k)), start=False), got


def at(h, m=0, days=0):
    return datetime.combine(date.today() + timedelta(days=days), datetime.min.time()).replace(hour=h, minute=m)


def test_alarm_edit_off_and_on(db, monkeypatch):
    monkeypatch.setattr(schedule.Scheduler, "_prayers", lambda *a: None)
    monkeypatch.setattr(schedule.Scheduler, "check_battery", lambda *a: None)
    s, got = sched()
    a = schedule.add_alarm("23:58", "late", "daily")
    off = schedule.add_alarm("23:58", "once off")
    schedule.enable_alarm(off["id"], False)
    s._alarms(at(23, 58), date.today().isoformat(), lambda w: timedelta(0) <= at(23, 58) - w <= schedule.CATCH_UP)
    assert got == [("Alarm: late (23:58)", "alarm")]
    assert [x["label"] for x in schedule.list_alarms()] == ["late", "once off"]                # a switched-off one isn't thrown away
    b = schedule.update_alarm(a["id"], "23:59", "later", "days", ["mon", "fri"])
    assert b["id"] == a["id"] and b["days"] == [0, 4] and b["last_fired"] is None
    assert schedule.enable_alarm(off["id"], True)["date"] >= date.today().isoformat()
    assert "switched off" in schedule.describe_alarm(schedule.enable_alarm(a["id"], False))
    for f in (lambda: schedule.update_alarm(99, "7:00"), lambda: schedule.enable_alarm(99, True), lambda: schedule.update_alarm(a["id"], "25:00"), lambda: schedule.update_alarm(a["id"], "7:00", "", "days", [])):
        with pytest.raises(ValueError):
            f()


def test_missed_alarms_are_told_once(db):
    s, got = sched()
    now = at(12)
    def tick(n):
        s._alarms(n, n.date().isoformat(), lambda w: timedelta(0) <= n - w <= schedule.CATCH_UP)
    schedule.write_json(schedule.ALARMS_FILE, [
        {"id": 1, "time": "07:00", "label": "daily", "repeat": "daily", "days": list(range(7)), "enabled": True, "last_fired": None, "since": "2026-01-01T00:00:00"},
        {"id": 2, "time": "08:00", "label": "once", "repeat": "once", "days": [], "enabled": True, "last_fired": None, "date": now.date().isoformat(), "since": "2026-01-01T00:00:00"},
        {"id": 3, "time": "09:00", "label": "made after", "repeat": "daily", "days": list(range(7)), "enabled": True, "last_fired": None, "since": at(10).isoformat()},
        {"id": 4, "time": "06:00", "label": "from before 1.27", "repeat": "daily", "days": list(range(7)), "enabled": True, "last_fired": None},
        {"id": 5, "time": "06:00", "label": "ancient once", "repeat": "once", "days": [], "enabled": True, "last_fired": None, "date": "2026-01-05", "since": "2026-01-01T00:00:00"},
        {"id": 6, "time": "13:00", "label": "later today", "repeat": "once", "days": [], "enabled": True, "last_fired": None, "date": now.date().isoformat(), "since": "2026-01-01T00:00:00"},
        {"id": 7, "time": "06:00", "label": "no date", "repeat": "once", "days": [], "enabled": True, "last_fired": None}])
    tick(now)
    assert [(t.split(chr(34))[1], k) for t, k in got] == [("daily", "info"), ("once", "info")]
    assert {a["id"] for a in schedule.list_alarms()} == {1, 3, 4, 6, 7}
    tick(now + timedelta(minutes=1))
    assert len(got) == 2
    tick(at(13))
    assert got[-1] == ("Alarm: later today (13:00)", "alarm") and len(got) == 3
    tick(at(7, 0, days=1))
    assert got[-1] == ("Alarm: daily (07:00)", "alarm")


# ---------------- the AI and the others ----------------
def test_tools(db):
    assert call("set_timer", seconds=600, message="pasta").startswith("Timer set: #1 pasta: 10 minutes left, ends ")
    assert "pasta" in call("list_timers") and "paused" in call("clock", action="timer_pause", name="pasta")
    assert "paused" not in call("clock", action="timer_resume", name="") and "11 minutes" in call("clock", action="timer_extend", minutes=1)
    assert call("cancel_timer", id=1) == "Cancelled timer #1 (pasta)." and call("cancel_timer", id=9) == "No timer #9." and call("list_timers") == "No active timers."
    assert "7 days" in call("set_timer", seconds=0) and "Which timer?" in call("clock", action="timer_pause", name="zz")
    assert "running at" in call("clock", action="stopwatch_start") and "Laps: 1" in call("clock", action="stopwatch_lap") and "stopped at" in call("clock", action="stopwatch_stop")
    assert "stopped at 00:00.00" in call("clock", action="stopwatch_reset") and "stopped at" in call("clock", action="stopwatch_read")
    assert call("clock", action="time_in", name="london").startswith("London: ") and "Try a big city" in call("clock", action="time_in", name="Atlantis")
    assert "Focus round 1 of 4" in call("clock", action="focus", minutes=25.0) and "already running" in call("clock", action="focus") and "stopped" in call("clock", action="focus_stop")
    assert "Nothing is ringing" in call("clock", action="ring_stop") and "Nothing is ringing" in call("clock", action="snooze")
    a = schedule.add_alarm("07:00", "x", "daily")
    assert "switched off" in call("clock", action="alarm_off", name=f"#{a['id']}") and "next" in call("clock", action="alarm_on", name=str(a["id"])) and "Give its number" in call("clock", action="alarm_on", name="zz")
    assert "Unknown action" in call("clock", action="format_disk")


def test_snoozing_by_voice(db, monkeypatch):
    x = Rings(monkeypatch, 5)
    monkeypatch.setattr(tools, "RINGER", x.r)
    x.r.start("wake up", "alarm")
    assert "wake up: 10 minutes left" in call("clock", action="snooze", minutes=10.0)
    x.r.start("tea")
    assert call("clock", action="ring_stop") == "Stopped: tea"


def test_where_it_may_be_used(db):
    names = {d["name"] for d in tools.TOOL_DEFINITIONS}
    assert {"clock", "news"} <= names and {"clock", "news"} <= set(providers.LOCAL_TOOLS) and {"clock", "news"} <= set(providers.BIG_TOOLS)
    a = agents.save("T", "r", ["clock"])
    from jarvis.agents import AgentContext
    c = AgentContext(ctx(), agents.get(a["id"]))
    assert "may only use clock" in tools.execute("clock", {"action": "ring_stop"}, c)[0] and "London" in tools.execute("clock", {"action": "time_in", "name": "London"}, c)[0]
    automations.check_step({"tool": "clock", "args": {"action": "focus", "minutes": 25}})
    for bad in ({"action": "ring_stop"}, {"action": "stopwatch_reset"}):
        with pytest.raises(ValueError):
            automations.check_step({"tool": "clock", "args": bad})
    assert plans.LOOKING >= {"clock:ring_stop", "clock:snooze", "news:top"} and "clock:focus" not in plans.LOOKING
    assert not guard.is_untrusted("clock", {"action": "focus"})


def test_emergency_stop_silences_and_test_copies_are_silent(db, monkeypatch):
    from jarvis import alerts, hud
    beeps = []
    monkeypatch.setattr(alerts, "beep", lambda *a, **k: beeps.append(a))
    monkeypatch.setenv("JARVIS_NO_SPEAK", "1")
    h = hud.Hub()
    try:
        h.notify("Alarm: up (07:00)", "alarm")
        assert h.ringer.list()[0]["label"] == "up" and h.history[-1]["ring"] == h.ringer.list()[0]["id"]
        h.clock_done("Reminder: eggs", "eggs", True)
        h.clock_done("old", "old", False)
        assert [r["label"] for r in h.ringer.list()] == ["up", "eggs"] and h.history[-1]["kind"] == "info" and "ring" not in h.history[-1]
        time.sleep(0.2)
        assert beeps == []
        h.emergency_stop()
        assert h.ringer.list() == []
        monkeypatch.setenv("JARVIS_NO_MIC", "1")
        monkeypatch.setattr(hud.live_mod, "LiveSession", lambda *a, **k: 1 / 0)
        h.live_start()                                                  # a demo copy never opens the microphone
        assert not h.live
    finally:
        clock.stop()
        tools.STOP.clear()


def test_database_upgrade_keeps_everything(db):
    storage.close()
    p = db / "old.db"
    c = sqlite3.connect(p)
    for sql in storage.MIGRATIONS[:9]:
        c.executescript(sql)
    c.execute("INSERT INTO goals (title, created) VALUES ('keep me', '2026-01-01')")
    c.execute("PRAGMA user_version = 9")
    c.commit()
    assert storage.migrate(c) == len(storage.MIGRATIONS) and c.execute("SELECT title FROM goals").fetchone() == ("keep me",)
    assert c.execute("SELECT count(*) FROM timers").fetchone() == (0,)
    c.close()


def test_page_data(db):
    clock.add(60, "<b>x</b>")
    schedule.add_alarm("07:00", "up", "daily")
    d = clock.load()
    json.dumps(d)
    assert d["timers"][0]["label"] == "<b>x</b>" and d["alarms"][0]["next"] and len(d["focus"]) == 7 and [w["place"] for w in d["world"]] == clock.DEFAULT_PLACES and d["ring_minutes"] == 2

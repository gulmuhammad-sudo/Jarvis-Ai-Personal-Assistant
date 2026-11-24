"""Phase 8, part 3: travel, meetings, people. Temporary database and settings; no microphone, no internet."""
import json
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from jarvis import agents, audit, automations, brain, clock, guard, life, mail, meet, people, planner, plans, providers, schedule, storage, tools, travel

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
    monkeypatch.setattr(travel, "_weather", {})
    meet.forget_yes()
    mail.clear_seen()
    tools.STOP.clear()
    yield tmp_path
    meet.forget_yes()
    mail.clear_seen()
    storage.close()


def call(tool_, answer=True, asked=None, from_ai=False, **args):
    def confirm(q, **k):
        if asked is not None:
            asked.append(q)
        return answer
    return tools.execute(tool_, args, tools.ToolContext(confirm=confirm, notify=lambda *a, **k: None), from_ai)[0]


# ================ travel ================
def trip(**k):
    return travel.save(**{"place": "Istanbul", "start": day(10), "end": day(14), **k})


def test_trips(db):
    t = trip()
    assert t["title"] == "Trip to Istanbul" and t["days"] == 5 and t["state"] == "coming" and t["in_days"] == 10
    travel.save(place="Lahore", start=day(-9), end=day(-7))
    travel.save(title="Now here", start=day(-1), end=day(1))
    assert [x["title"] for x in travel.trips()] == ["Now here", "Trip to Istanbul", "Trip to Lahore"] and [x["state"] for x in travel.trips()] == ["now", "coming", "past"]
    u = travel.save(start=day(20), trip_id=t["id"])
    assert (u["start"], u["end"], u["days"]) == (day(20), day(24), 5)                      # moved: as long as before
    assert travel.save(end=day(22), trip_id=t["id"])["days"] == 3 and travel.find("istanbul")["id"] == t["id"] and travel.find("")["title"] == "Now here" and travel.find("zz") is None
    for bad in ({"place": ""}, {"start": ""}, {"end": day(5)}, {"end": day(800)}, {"budget": "lots"}, {"place": "x" * 101}, {"start": "someday"}):
        with pytest.raises(ValueError):
            trip(**bad)
    assert travel.delete(t["id"]) and not travel.delete(t["id"])
    with pytest.raises(ValueError):
        travel.save(title="x", trip_id=99)


def test_plan_pack_papers(db):
    t = trip(abroad=True)
    a = travel.add_item(t["id"], "plan", "Blue Mosque", "2", "9:30", "Sultanahmet")
    assert a["day"] == day(11) and a["at"] == "09:30" and travel.add_item(t["id"], "plan", "blue mosque", day(11), "09:30") is None
    assert travel.add_item(t["id"], "plan", "Ferry")["day"] == day(10)                     # no day said: the first
    for bad in (("plan", "x", "9"), ("plan", "x", day(1)), ("plan", "", "1"), ("plan", "x", "1", "25:00"), ("booking", "x")):
        with pytest.raises(ValueError):
            travel.add_item(t["id"], *bad)
    n = travel.add_list(t["id"], "umrah")
    assert n > 10 and travel.add_list(t["id"], "umrah") == 0 and travel.add_list(t["id"], "basic") == 0 and travel.add_list(t["id"], "papers") == len(travel.PAPERS_ABROAD)
    x = travel.find_item(t["id"], "ihram belt")
    assert travel.tick_item(x["id"]) and travel.get(t["id"])["pack"] == {"n": n, "done": 1} and travel.delete_item(x["id"]) and not travel.delete_item(x["id"])
    with pytest.raises(ValueError):
        travel.add_list(t["id"], "weapons")
    with pytest.raises(ValueError):
        travel.add_item(99, "pack", "x")
    assert "Blue Mosque at Sultanahmet" in travel.describe_full(travel.get(t["id"]))
    travel.delete(t["id"])
    assert travel.items(t["id"]) == []


def test_budget_comes_from_money(db):
    t = trip(budget="50,000")
    life.save_money("1500", "out", "trip to istanbul", "taxi")
    life.save_money("999", "out", "food", "")
    d = travel.load(t["id"])
    assert d["trip"]["spent"] == 150000 and d["trip"]["budget"] == 5000000 and "1,500" in d["trip"]["spent_text"] and d["trip"]["budget_raw"] == "50000"
    assert travel.save(budget="", trip_id=t["id"])["budget"] is None
    json.dumps(travel.load())


def test_calendar_once(db):
    t = trip()
    assert travel.to_calendar(t["id"]) == {"added": 5, "there": 0} and travel.to_calendar(t["id"]) == {"added": 0, "there": 5}
    e = planner.occurrences(TODAY, TODAY + timedelta(days=30))
    assert len(e) == 5 and all(o["all_day"] for o in e)


def test_weather_asks_only_when_told(db, monkeypatch):
    asked = []
    w = {"weather": [{"date": day(i), "mintempC": "5", "maxtempC": "12", "hourly": [{"chanceofrain": "30", "weatherDesc": [{"value": "Cloudy "}]}] * 8} for i in range(3)]}
    monkeypatch.setattr(schedule, "_get_json", lambda u, **k: asked.append(u) or w)
    t = trip(place="São Paulo & co")
    travel.load(t["id"])
    travel.describe_full(t)
    assert asked == []
    assert travel.weather(t["place"])[0] == {"day": day(0), "min": 5, "max": 12, "rain": 30, "text": "Cloudy"} and travel.weather(t["place"]) and len(asked) == 1
    assert asked[0] == "https://wttr.in/S%C3%A3o%20Paulo%20%26%20co?format=j1"
    monkeypatch.setattr(schedule, "_get_json", lambda u, **k: (_ for _ in ()).throw(OSError("no net")))
    for bad in ("", "Elsewhere"):
        with pytest.raises(ValueError):
            travel.weather(bad)
    monkeypatch.setattr(schedule, "_get_json", lambda u, **k: {"weather": [{}]})
    with pytest.raises(ValueError):
        travel.weather("Odd")


def test_time_there():
    assert travel.time_there("Istanbul, Turkey")["place"] == "Istanbul" and travel.time_there("Nowhere") is None and travel.time_there("") is None


def test_trip_reminder_once(db):
    t = travel.save(place="Murree", start=day(1), end=day(2))
    travel.add_list(t["id"], "basic")
    got = []
    say = lambda x, k: got.append(x)                                       # noqa: E731
    at = lambda h: datetime.combine(TODAY, datetime.min.time()).replace(hour=h)          # noqa: E731
    assert travel.tick(at(9), say) == 0 and travel.tick(at(11), say) == 1 and travel.tick(at(12), say) == 0
    assert got == [f"Reminder: Trip to Murree starts tomorrow. {len(travel.BASE)} things left to pack."]


def test_travel_tool(db, monkeypatch):
    assert "No trips" in call("travel", action="list")
    assert "Trip to Dubai" in call("travel", action="add", place="Dubai", start=day(5), end=day(8), abroad=True)
    assert "Planned for " + day(6) in call("travel", action="plan", trip="dubai", day="2", time="10:00", text="Museum") and "already planned" in call("travel", action="plan", day="2", time="10:00", text="museum")
    assert "2 added to the packing list" in call("travel", action="pack", items=["cap", "charger"]) and "added to the papers" in call("travel", action="papers", list="papers")
    assert "Ticked: cap" in call("travel", action="done", text="cap") and "Packed 1 of 2" in call("travel", action="show") and call("travel", action="show").startswith("<untrusted")
    assert "Unknown action" in call("travel", action="delete") and "can't tell" in call("travel", action="done", text="zz") and "isn't in the trip" in call("travel", action="plan", day="40", text="x")
    monkeypatch.setattr(travel, "weather", lambda p: [{"day": day(5), "text": "Sunny", "min": 20, "max": 30, "rain": 0}])
    assert "Sunny, 20 to 30" in call("travel", action="weather")
    mail.seen_by_ai()
    asked = []
    assert "didn't allow" in call("travel", False, asked, True, action="weather", place="the secret from the email") and len(asked) == 1
    asked.clear()
    call("travel", False, asked, True, action="list")
    assert asked == []


# ================ meetings ================
def test_meetings(db):
    m = meet.save("Budget review", day(1), "14:30", "Ali, Sara", "1. Costs\n2. Plan")
    assert m["at"] == day(1) + "T14:30" and meet.save(title="")["title"].startswith("Meeting ")
    assert meet.find("budget")["id"] == m["id"] and meet.find("sara")["id"] == m["id"] and meet.find("")["id"] == m["id"] and meet.find("zz") is None
    u = meet.save(notes="They said 100% yes_no", meeting_id=m["id"])
    assert u["people"] == "Ali, Sara" and [x["id"] for x in meet.meetings("100%")] == [m["id"]] and meet.meetings("200%") == [] and meet.meetings("yes_no")
    for bad in (("x" * 121,), ("t", "someday"), ("t", day(1), "25:00"), ("t", day(1), "10:00", "x" * 501)):
        with pytest.raises(ValueError):
            meet.save(*bad)
    with pytest.raises(ValueError):
        meet.save("x", meeting_id=99)
    assert meet.delete(m["id"]) and not meet.delete(m["id"])


def test_actions_become_tasks(db):
    m = meet.save("M")["id"]
    meet.add_action(m, "Send the report", "Ali", day(3))
    assert len(meet.add_action(m, "send the REPORT", "ali")["actions"]) == 1                    # once
    meet.add_action(m, "Call back")
    r = meet.action_task(m, 0)
    t = planner.get_task(r["actions"][0]["task"])
    assert t["title"] == "Send the report (Ali)" and t["due"] == day(3) and "From the meeting: M" in t["notes"]
    with pytest.raises(ValueError):
        meet.action_task(m, 0)
    assert [a["text"] for a in meet.remove_action(m, 0)["actions"]] == ["Call back"]
    for f in (lambda: meet.remove_action(m, 5), lambda: meet.action_task(m, -1), lambda: meet.add_action(m, ""), lambda: meet.add_action(m, "x", "", "someday"), lambda: meet.add_action(99, "x")):
        with pytest.raises(ValueError):
            f()


class Source:
    """Pretend microphone: speech (noise bursts) and silence, then the end."""
    rate = 16000

    def __init__(self, plan):
        self.blocks, self.closed = [], False
        rng = np.random.default_rng(1)
        for loud, seconds in plan:
            for _ in range(int(seconds * 10)):
                t = np.arange(1600) / 16000
                x = 0.2 * np.sin(2 * np.pi * 600 * t) * (0.6 + 0.4 * rng.random(1600)) if loud else rng.normal(0, 0.0005, 1600)
                self.blocks.append(x.astype(np.float32))

    def read(self):
        return self.blocks.pop(0) if self.blocks else None

    def close(self):
        self.closed = True


def scribe(db, plan, write=None, **k):
    m = meet.save("Talk")["id"]
    over, states, pieces = threading.Event(), [], []
    src = Source(plan)

    def w(wav, engine, lang):
        pieces.append((len(wav), engine, lang))
        return f"piece {len(pieces)}"
    s = meet.Scribe(m, k.get("engine", "local"), "en", src, states.append, lambda why: over.set(), write or w)
    return m, s, src, over, states, pieces


def test_it_writes_down_and_keeps_no_sound(db):
    m, s, src, over, states, pieces = scribe(db, [(False, 1), (True, 7), (False, 2), (True, 3), (False, 1)])
    s.start()
    assert over.wait(20) and src.closed and not s.active
    text = meet.transcript(m)
    assert "piece 1" in text and "piece 2" in text and text.count("writing started") == 1 and text.count("writing ended") == 1 and len(pieces) == 2
    assert all(e == "local" for _, e, _ in pieces) and states[0]["active"] and states[-1]["active"] is False and s.reason == "the microphone stopped"
    assert not [f for f in db.rglob("*") if f.suffix in (".wav", ".mp3", ".flac")]
    assert meet.meetings("piece")[0]["id"] == m


def test_silence_is_not_sent_anywhere(db):
    m, s, src, over, states, pieces = scribe(db, [(False, 60)])
    s.start()
    assert over.wait(20) and pieces == [] and s.words == 0


def test_long_speech_is_cut(db):
    m, s, src, over, states, pieces = scribe(db, [(True, 60)])
    s.start()
    assert over.wait(30) and len(pieces) >= 2 and max(n for n, _, _ in pieces) <= (meet.PIECE_MAX + 1) * 32000


def test_a_failing_piece_is_marked_and_the_rest_goes_on(db):
    n = []

    def write(wav, engine, lang):
        n.append(1)
        if len(n) == 1:
            raise RuntimeError("rate limit")
        return "the rest"
    m, s, src, over, *_ = scribe(db, [(True, 7), (False, 1), (True, 7), (False, 1)], write)
    s.start()
    assert over.wait(20) and "couldn't be written down" in meet.transcript(m) and "the rest" in meet.transcript(m) and s.failed == 1


def test_pause_stop_and_deleting(db):
    m, s, src, over, *_ = scribe(db, [(True, 600)])
    src.read = lambda real=src.read: (time.sleep(0.002), real())[1]
    s.start()
    s.pause(True)
    time.sleep(0.2)
    s.stop("you stopped it")
    assert over.wait(10) and s.reason == "you stopped it" and "piece" not in meet.transcript(m)
    m, s, src, over, *_ = scribe(db, [(True, 60), (False, 2)], lambda *a: meet.delete(m2[0]) or "late")
    m2 = [m]
    s.start()
    assert over.wait(20) and meet.get(m) is None and "deleted" in s.reason


def test_full_transcript_stops(db, monkeypatch):
    monkeypatch.setattr(meet, "MAX_TRANSCRIPT", 60)
    m, s, src, over, *_ = scribe(db, [(True, 60), (False, 2)], lambda *a: "x" * 50)
    s.start()
    assert over.wait(20) and "no room" in s.reason and len(meet.transcript(m)) <= 60


def test_the_engine_is_the_chosen_one_only(db, monkeypatch):
    from jarvis import stt
    used = []
    monkeypatch.setattr(stt, "_local", lambda w, m: used.append("local") or "hello there")
    monkeypatch.setattr(stt, "_whisper", lambda w, m: used.append("groq") or "hello there")
    assert meet._write_down(b"x", "local", "en") == "hello there" and meet._write_down(b"x", "groq", "en") and used == ["local", "groq"]
    monkeypatch.setattr(stt, "_local", lambda w, m: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        meet._write_down(b"x", "local", "en")                              # it never goes to the cloud instead
    assert used == ["local", "groq"]


def test_only_the_button_starts_it_and_only_with_the_tick(db, monkeypatch):
    from jarvis import hud
    monkeypatch.setattr(meet, "engines", lambda: {"local": True, "groq": False})
    monkeypatch.setattr(meet, "Mic", lambda: 1 / 0)
    monkeypatch.setattr(hud, "recorder", type("R", (), {"_chosen": None}))
    h = hud.Hub()
    try:
        m = meet.save("M")["id"]
        monkeypatch.setenv("JARVIS_NO_MIC", "1")
        with pytest.raises(ValueError, match="isn't available"):
            h.meeting_start(m, "local", True)
        monkeypatch.delenv("JARVIS_NO_MIC")
        for agree in (False, None, "true", 1):
            with pytest.raises(ValueError, match="agrees"):
                h.meeting_start(m, "local", agree)
        for engine in ("groq", "gemini", ""):
            with pytest.raises(ValueError):
                h.meeting_start(m, engine, True)
        with pytest.raises(ValueError, match="gone"):
            h.meeting_start(99, "local", True)
        with pytest.raises(ValueError, match="couldn't be opened"):
            h.meeting_start(m, "local", True)
        assert not h.meeting_on()
        src = Source([(True, 2000)])
        src.read = lambda real=src.read: (time.sleep(0.01), real())[1]
        monkeypatch.setattr(meet, "Mic", lambda: src)
        monkeypatch.setattr(meet, "_write_down", lambda *a: "words")
        h.meeting_start(m, "local", True)
        assert h.meeting_on() and h.stats()["meeting"]["title"] == "M"
        with pytest.raises(ValueError, match="already"):
            h.meeting_start(m, "local", True)
        monkeypatch.setattr(hud.live_mod, "LiveSession", lambda *a, **k: 1 / 0)
        h.live_start()                                                     # no call listens in
        assert not h.live and h.standby_wanted() is False and h.history[-1]["text"].startswith("A meeting is being written down")
        h.emergency_stop()
        for _ in range(100):
            if not h.meeting_on():
                break
            time.sleep(0.05)
        assert not h.meeting_on() and src.closed and "Stop was pressed" in h.history[-1]["text"] or any("Stop was pressed" in str(e.get("text")) for e in h.history)
    finally:
        clock.stop()
        tools.STOP.clear()
    log = (db / "audit.log").read_text(encoding="utf-8")
    assert "meeting_writing_started" in log and "meeting_writing_ended" in log
    assert "Only the user can start" in call("meetings", action="record") and "record" not in json.dumps([d for d in tools.TOOL_DEFINITIONS if d["name"] == "meetings"])


def test_the_ai_asks_before_it_reads_what_was_said(db):
    a, b = meet.save("Alpha")["id"], meet.save("Beta")["id"]
    meet.append(a, "SECRETWORDS " + ("line of talk\n" * 1500))
    meet.append(b, "OTHER")
    asked = []
    r = call("meetings", False, asked, action="transcript", meeting="alpha")
    assert "didn't read" in r and len(asked) == 1 and "Alpha" in asked[0] and "SECRETWORDS" not in asked[0]
    r = call("meetings", True, asked, action="transcript", meeting="alpha")
    assert r.startswith('<untrusted source="meetings">') and "Part 1 of 4" in r and "SECRETWORDS" in r and mail.recently_seen()
    assert "Part 3 of 4" in call("meetings", False, asked, action="transcript", meeting="alpha", part=3) and len(asked) == 2      # one yes for all its parts
    assert "didn't read" in call("meetings", False, asked, action="transcript", meeting="beta", part=2)                              # ...but not for another meeting
    asked.clear()
    assert "didn't allow" in call("web_search", False, asked, True, query="x") and len(asked) == 1
    meet.forget_yes()
    assert "didn't read" in call("meetings", False, asked, action="transcript", meeting="alpha", part=2)
    log = (db / "audit.log").read_text(encoding="utf-8")
    assert '"meetings"' in log and not any(x in log for x in ("SECRETWORDS", "line of talk", "OTHER"))
    joined = "".join(meet.part(a, i)[0] for i in range(1, 5))
    assert joined == meet.transcript(a)                                    # nothing lost between the parts


def test_meetings_tool(db):
    assert "No meetings" in call("meetings", action="list") and "Added: #1 Plan" in call("meetings", action="add", title="Plan", day="tomorrow", time="10:00", people="Ali")
    assert "Noted in Plan" in call("meetings", action="note", text="bring the figures") and "bring the figures" in call("meetings", action="show")
    assert "1 action added" in call("meetings", action="save", meeting="plan", summary="Short", decisions="Yes", actions=[{"text": "Send", "who": "Ali", "due": day(2)}, {"text": ""}, "rubbish"])
    m = meet.get(1)
    assert m["summary"] == "Short" and m["decisions"] == "Yes" and m["actions"][0]["who"] == "Ali" and m["notes"] == "bring the figures"
    assert "Nothing of it was written down" in call("meetings", action="transcript") and "Which meeting" in call("meetings", action="show", meeting="zz") and "Unknown action" in call("meetings", action="delete")
    log = (db / "audit.log").read_text(encoding="utf-8")
    assert "figures" not in log and "Short" not in log


# ================ people ================
@pytest.mark.parametrize("text,want", [("", ""), ("14 May", "--05-14"), ("14 may 2001", "2001-05-14"), ("May 14, 2001", "2001-05-14"), ("2001-05-14", "2001-05-14"), ("14/5/2001", "2001-05-14"), ("14-05", "--05-14"),
                                       ("29 feb", "--02-29"), ("1st January", "--01-01"), ("--05-14", "--05-14")])
def test_birthdays_read(text, want):
    assert people.parse_birthday(text) == want


@pytest.mark.parametrize("bad", ["someday", "31 Feb", "32 May", "14 May 2999", "1 Jan 1850", "14 Ju", "14", "2001-13-01", "29 feb 2001"])
def test_bad_birthdays(bad):
    with pytest.raises(ValueError):
        people.parse_birthday(bad)


def test_next_birthday():
    n = lambda b, t: people.next_birthday(b, t)                            # noqa: E731
    assert n("2001-05-14", date(2026, 5, 14)) == (date(2026, 5, 14), 25) and n("2001-05-14", date(2026, 5, 15)) == (date(2027, 5, 14), 26) and n("--05-14", date(2026, 1, 1)) == (date(2026, 5, 14), None)
    assert n("2000-02-29", date(2026, 1, 1)) == (date(2026, 2, 28), 26) and n("2000-02-29", date(2028, 2, 1)) == (date(2028, 2, 29), 28) and n("", date.today()) is None


def test_people(db):
    p = people.save("Ali", "brother", "14 May 2001", "+92 300 1234567", "likes tea")
    assert p["birthday"] == "2001-05-14" and people.find("brother")["id"] == p["id"] and people.find("ALI") and people.find("zz") is None
    assert people.save(notes="likes coffee", person_id=p["id"])["phone"] == "+92 300 1234567" and [x["name"] for x in people.people("coffee")] == ["Ali"]
    for bad in ({"name": ""}, {"name": "ali"}, {"name": "B", "phone": "call me"}, {"name": "B", "birthday": "x"}, {"name": "B", "remind": 5}, {"name": "B", "remind": "x"}, {"name": "x" * 81}):
        with pytest.raises(ValueError):
            people.save(**bad)
    assert people.delete(p["id"]) and not people.delete(p["id"])
    with pytest.raises(ValueError):
        people.save("x", person_id=99)
    json.dumps(people.load())


def test_birthday_reminders(db):
    noon = datetime.combine(TODAY, datetime.min.time()).replace(hour=12)
    b = lambda n: "--" + (TODAY + timedelta(days=n)).strftime("%m-%d")     # noqa: E731
    people.save("Today", birthday=b(0))
    people.save("Tomorrow", birthday=b(1))
    people.save("Week", birthday=b(6), remind=7)
    people.save("Far", birthday=b(6), remind=1)
    people.save("Never", birthday=b(0), remind=-1)
    got = []
    say = lambda t, k: got.append(t)                                       # noqa: E731
    assert people.tick(noon.replace(hour=8), say) == 0 and people.tick(noon, say) == 3 and people.tick(noon, say) == 0
    assert sorted(got) == ["Reminder: Tomorrow's birthday is tomorrow.", "Reminder: Week's birthday is in 6 days.", "Today is Today's birthday."]
    assert people.tick(noon + timedelta(days=1), say) == 1 and got[-1] == "Today is Tomorrow's birthday."
    got.clear()
    for n in range(2, 7):
        people.tick(noon + timedelta(days=n), say)
    assert got == ["Reminder: Far's birthday is tomorrow.", "Today is Far's birthday.", "Today is Week's birthday."]


def test_checkin(db):
    got = []
    say = lambda t, k: got.append((t, k))                                  # noqa: E731
    six = datetime.combine(TODAY, datetime.min.time()).replace(hour=18)
    assert people.tick(six, say) == 0                                      # off unless you want it
    people.save_settings({"checkin": "18:00"})
    assert people.tick(six, say) == 1 and people.tick(six + timedelta(minutes=1), say) == 0 and got[0][1] == "info" and people.tick(six + timedelta(days=1, hours=3), say) == 0
    people.save_settings({"checkin": ""})
    assert people.settings()["checkin"] == ""


def test_the_manner(db):
    plain = people.prompt()
    assert "emergency number" in plain and "butler" not in plain
    assert people.save_settings({"tone": "warm", "humour": "none", "length": "short"}) is True and people.save_settings({"tone": "warm"}) is False
    p = people.prompt()
    assert "warm, caring" in p and "No jokes" in p and "as short as possible" in p and "emergency number" in p
    assert "warm, caring" in brain.system_prompt() and "warm, caring" in brain.system_prompt(live=True)
    for bad in ({"tone": "evil"}, {"humour": 5}, {"length": ""}, {"checkin": "99"}):
        with pytest.raises(ValueError):
            people.save_settings(bad)
    people.save("Ali", "brother", phone="+92 300 1234567", notes="SECRETNOTE")
    assert "Ali" not in people.prompt()                                    # only with your tick
    people.save_settings({"use_names": True})
    assert "Ali (brother)" in people.prompt() and "SECRETNOTE" not in people.prompt() and "300" not in people.prompt()
    schedule.set_setting("companion_tone", "rubbish")
    assert people.settings()["tone"] == "butler"


def test_people_tool(db):
    assert "Kept: Ali (brother), birthday 14 May" in call("people", action="add", name="Ali", relation="brother", birthday="14 May 2001", notes="likes tea")
    people.save(phone="+92 300 1234567", person_id=1)
    assert "likes tea" in call("people", action="update", name="ali", notes="has a cat") and people.get(1)["notes"] == "likes tea\nhas a cat" and people.get(1)["birthday"] == "2001-05-14"
    r = call("people", action="list")
    assert r.startswith('<untrusted source="people">') and "Ali" in r and "300" not in r                # never the phone number
    assert "can't tell" in call("people", action="update", name="zz") and "Unknown action" in call("people", action="delete", name="Ali") and "birthday" in call("people", action="add", name="B", birthday="x").lower()
    log = (db / "audit.log").read_text(encoding="utf-8")
    assert "likes tea" not in log and "has a cat" not in log and '"people"' in log


# ================ all three ================
def test_where_they_may_be_used(db):
    for t in ("meetings", "people"):
        with pytest.raises(ValueError):
            agents.save("X", "r", [t])
    a = agents.save("T", "r", ["travel"])
    with pytest.raises(ValueError):
        agents.save("Both", "r", ["travel", "web_search"])
    c = agents.AgentContext(tools.ToolContext(confirm=lambda q, **k: True, notify=lambda *x, **k: None), agents.get(a["id"]))
    assert "may only use travel" in tools.execute("travel", {"action": "weather"}, c)[0]
    for t in ("travel", "meetings", "people"):
        with pytest.raises(ValueError):
            automations.check_step({"tool": t, "args": {"action": "list"}})
    assert {"travel", "meetings", "people"} <= set(providers.LOCAL_TOOLS) & set(providers.BIG_TOOLS)
    assert plans.LOOKING >= {"travel:show", "meetings:transcript", "people:list"} and not {"travel:add", "meetings:save", "people:add"} & plans.LOOKING
    from jarvis import hud
    assert "meeting" in hud.Hub.PERMISSION_KINDS and "meeting" in guard.PRIVATE_KINDS


def test_database_upgrade_keeps_everything(db):
    storage.close()
    c = sqlite3.connect(db / "old.db")
    for sql in storage.MIGRATIONS[:11]:
        c.executescript(sql)
    c.execute("INSERT INTO decks (name, created) VALUES ('keep me', '2026-01-01')")
    c.execute("PRAGMA user_version = 11")
    c.commit()
    assert storage.migrate(c) == len(storage.MIGRATIONS) and c.execute("SELECT name FROM decks").fetchone() == ("keep me",)
    assert c.execute("SELECT (SELECT count(*) FROM trips), (SELECT count(*) FROM meetings), (SELECT count(*) FROM people)").fetchone() == (0, 0, 0)
    c.close()

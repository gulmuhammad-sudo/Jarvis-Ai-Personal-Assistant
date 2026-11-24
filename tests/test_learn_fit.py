"""Phase 8, part 2: learning (flashcards) and fitness. Temporary database and settings."""
import csv
import json
import sqlite3
from datetime import date, datetime, timedelta

import pytest

from jarvis import agents, audit, automations, fit, guard, learn, plans, providers, schedule, storage, tools

TODAY = date.today()
NOON = datetime.combine(TODAY, datetime.min.time()).replace(hour=12)


@pytest.fixture
def db(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    monkeypatch.setattr(plans, "_HOLD", "")
    monkeypatch.setattr(plans, "_PLAN", None)
    tools.STOP.clear()
    yield tmp_path
    storage.close()


def ctx():
    return tools.ToolContext(confirm=lambda q, **k: True, notify=lambda *a, **k: None)


def call(tool_, **args):
    return tools.execute(tool_, args, ctx())[0]


def deck(n=3, name="Words"):
    d = learn.save_deck(name)
    if n:
        learn.add_cards(d["id"], [(f"front {i}", f"back {i}") for i in range(n)])
    return d["id"]


# ---------------- decks and cards ----------------
def test_decks(db):
    d = learn.save_deck("  English   words ")
    assert d["name"] == "English words" and learn.save_deck("Maths", d["id"])["name"] == "Maths"
    for bad in ("", "x" * 61, "MATHS"):
        with pytest.raises(ValueError):
            learn.save_deck(bad)
    learn.save_deck("Urdu ادب")
    assert learn.find_deck("#1")["name"] == "Maths" and learn.find_deck("math")["name"] == "Maths" and learn.find_deck("ادب") and learn.find_deck("zz") is None and learn.find_deck("") is None
    deck(2, "Gone")
    i = learn.find_deck("Gone")["id"]
    assert learn.delete_deck(i) and not learn.delete_deck(i) and learn.cards() == []
    with pytest.raises(ValueError):
        learn.save_deck("x", 99)
    with pytest.raises(ValueError):
        learn.add_cards(99, [("a", "b")])


def test_cards(db):
    d = deck(0)
    assert learn.add_cards(d, [("apple", "سیب"), ("APPLE", "x"), ("pear\r\nfruit", "ناشپاتی")]) == (2, 1)
    rows = learn.cards(d)
    assert rows[0]["front"] == "pear\nfruit" and learn.cards(d, "سیب")[0]["front"] == "apple" and learn.cards(d, "100%") == [] and learn.cards(d, "_____") == []
    for bad in ([("", "x")], [("x", " ")], [("x" * 1001, "y")], [], [(None, None)]):
        with pytest.raises(ValueError):
            learn.add_cards(d, bad)
    assert len(learn.cards(d)) == 2
    c = learn.update_card(rows[0]["id"], "new", "neu")
    assert c["front"] == "new" and learn.delete_card(c["id"]) and not learn.delete_card(c["id"])
    with pytest.raises(ValueError):
        learn.update_card(c["id"], "a", "b")


# ---------------- when they come back ----------------
def card(days, ease=2.5):
    return {"days": days, "ease": ease}


def test_intervals():
    assert [learn.schedule_next(card(0), g)[0] for g in (1, 2, 3, 4)] == [0, 1, 1, 4]
    assert [learn.schedule_next(card(1), g)[0] for g in (1, 2, 3, 4)] == [0, 2, 3, 6]
    assert [learn.schedule_next(card(10), g)[0] for g in (1, 2, 3, 4)] == [0, 12, 25, 34]
    d, ease = 0, 2.5
    for _ in range(40):
        d, ease = learn.schedule_next(card(d, ease), 4)
    assert d == learn.MAX_DAYS and ease == 3.0
    for _ in range(40):
        _, ease = learn.schedule_next(card(5, ease), 1)
    assert ease == 1.3 and learn.schedule_next(card(3, 1.3), 2)[0] == 4          # always longer when it was known
    for days in range(1, 400):
        a, b, c = (learn.schedule_next(card(days), g)[0] for g in (2, 3, 4))
        assert days < a <= b <= c


def test_a_day_of_study(db):
    d = deck(3)
    assert [c["front"] for c in learn.due(d, NOON)] == ["front 0", "front 1", "front 2"] and learn.decks(NOON)[0]["today"] == 3
    a, b, c = (x["id"] for x in learn.due(d, NOON))
    assert learn.grade(a, "again", NOON)["back_in"] == "in 10 minutes" and learn.grade(b, 3, NOON)["back_in"] == "tomorrow" and learn.grade(c, "easy", NOON)["back_in"] == "in 4 days"
    assert learn.due(d, NOON) == [] and learn.next_soon(d, NOON) == 600
    later = NOON + timedelta(minutes=11)
    assert [x["id"] for x in learn.due(d, later)] == [a]
    learn.grade(a, "good", later)
    assert learn.due(d, later) == [] and learn.next_soon(d, later) is None
    tomorrow = NOON.replace(hour=5) + timedelta(days=1)                            # in the morning, whatever the hour was
    assert {x["id"] for x in learn.due(d, tomorrow)} == {a, b}
    assert learn.get_card(a)["lapses"] == 0                                        # a new card isn't forgotten yet
    learn.grade(b, "again", tomorrow)
    assert learn.get_card(b)["lapses"] == 1
    s = learn.stats()
    assert s["today"] == 4 and s["streak"] == 1 and s["right"] == 60 and s["ahead"][0]["n"] >= 1 and len(s["days"]) == 30


def test_only_some_new_cards_a_day(db):
    learn.save_settings({"new": 2})
    d, e = deck(5), deck(5, "Other")
    assert len(learn.due(d, NOON)) == 2 and len(learn.due(None, NOON)) == 4
    for x in learn.due(d, NOON):
        learn.grade(x["id"], "easy", NOON)
    assert learn.due(d, NOON) == [] and len(learn.due(None, NOON)) == 2 and len(learn.due(d, NOON + timedelta(days=1))) == 2
    learn.save_settings({"new": 0})
    assert learn.due(e, NOON) == []
    for bad in (-1, 201, "x", None, 1.5):
        with pytest.raises(ValueError):
            learn.save_settings({"new": bad})
    schedule.set_setting("learn_new", "many")
    assert learn.new_a_day() == 15


@pytest.mark.parametrize("how", ["", None, 0, 5, "maybe", "-1"])
def test_bad_grades(db, how):
    d = deck(1)
    with pytest.raises(ValueError):
        learn.grade(learn.cards(d)[0]["id"], how)
    with pytest.raises(ValueError):
        learn.grade(99, 3)
    assert learn.stats()["today"] == 0


def test_undo(db):
    d = deck(1)
    c = learn.cards(d)[0]
    learn.grade(c["id"], "easy", NOON)
    learn.undo(c)
    assert learn.get_card(c["id"]) == c and learn.stats()["today"] == 0 and len(learn.due(d, NOON)) == 1
    for bad in (c, {**c, "days": -1}, {}, {**c, "due": "rubbish"}):
        with pytest.raises((ValueError, KeyError, TypeError)):
            learn.undo(bad)
    learn.grade(c["id"], "good", NOON)
    for bad in ({**c, "days": 99999}, {**c, "ease": 50}, {**c, "due": "x" * 30}):
        with pytest.raises(ValueError):
            learn.undo(bad)
    assert learn.stats()["today"] == 1


def test_streak_counts_yesterday(db):
    d = deck(1)
    i = learn.cards(d)[0]["id"]
    for n in (3, 2, 1):
        learn.grade(i, "good", NOON - timedelta(days=n))
    assert learn.stats()["streak"] == 3
    learn.grade(i, "good", NOON)
    assert learn.stats()["streak"] == 4


# ---------------- in and out ----------------
@pytest.mark.parametrize("text", ["apple\tسیب\npear\tناشپاتی", "apple;سیب\r\npear;ناشپاتی\r\n", "apple , سیب\npear , ناشپاتی", "apple | سیب\n\npear | ناشپاتی", "apple = سیب\npear = ناشپاتی",
                                  '﻿"apple","سیب"\n"pear","ناشپاتی"', "#separator:tab\n#html:true\napple\t<b>سیب</b>\npear\tناشپاتی\tmytag"])
def test_import(text):
    assert learn.read_cards(text) == [("apple", "سیب"), ("pear", "ناشپاتی")]


def test_import_odd(db):
    assert learn.read_cards('"a, b",c\nd,"e ""f"""') == [("a, b", "c"), ("d", 'e "f"')]
    assert learn.read_cards("one<br>two\t2 < 3 and 4 > 1") == [("one\ntwo", "2 < 3 and 4 > 1")]
    for bad in ("", "   \n", "no separator here", ";\n;", None):
        with pytest.raises(ValueError):
            learn.read_cards(bad)
    with pytest.raises(ValueError):
        learn.read_cards("a;b\n" * 600_000)


def test_export_comes_back(db):
    d = deck(0, "My: deck/1")
    learn.add_cards(d, [("a, b", 'say "hi"'), ("=1+1", "سوال\nدو")])
    p, q = learn.export(d, db), learn.export(d, db)
    assert p != q and p.name == "Cards My deck 1.csv"
    got = learn.read_cards(p.read_text(encoding="utf-8-sig"))
    assert got[0] == ("a, b", 'say "hi"') and got[1][1] == "سوال\nدو" and not got[1][0].startswith("=")      # nothing a spreadsheet would run


def test_reminder(db):
    got = []
    say = lambda t, k: got.append(t)                                      # noqa: E731
    learn.save_settings({"remind": "12:00"})
    assert learn.tick(NOON, say) == 0                                     # nothing to look at
    deck(2)
    schedule.set_setting("learn_reminded", "")
    assert learn.tick(NOON - timedelta(minutes=1), say) == 0 and learn.tick(NOON, say) == 1 and learn.tick(NOON + timedelta(minutes=1), say) == 0
    assert got == ["Reminder: 2 cards to look at today."] and learn.tick(NOON + timedelta(days=1, hours=2), say) == 0
    with pytest.raises(ValueError):
        learn.save_settings({"remind": "25:00"})
    learn.save_settings({"remind": ""})
    assert learn.settings()["remind"] == ""


def test_learn_tool(db):
    assert "No decks yet." in call("learn", action="decks")
    assert "2 cards added to Biology" in call("learn", action="add", deck="Biology", cards=[{"front": "cell", "back": "unit of life"}, {"front": "DNA", "back": "genes"}])
    assert "(1 were already there)" in call("learn", action="add", deck="biology", cards=[{"front": "DNA", "back": "x"}])
    r = call("learn", action="quiz")
    assert r.startswith('<untrusted source="learn">') and "Front: cell" in r and "keep the back to yourself" in r
    assert "comes back tomorrow" in call("learn", action="grade", card=1, how="good") and "Front: DNA" in call("learn", action="quiz", deck="bio")
    call("learn", action="grade", card=2, how="easy")
    assert "Nothing to look at now" in call("learn", action="quiz") and "Biology: 2 cards" in call("learn", action="decks") and "cell = unit of life" in call("learn", action="search", query="cell")
    assert "no one deck" in call("learn", action="quiz", deck="zz") and "Which card" in call("learn", action="grade", card="zz", how="good") and "Unknown action" in call("learn", action="delete_deck")
    for bad in ({"cards": []}, {"cards": [{"front": "x"}]}, {"cards": ["x"]}, {"cards": "x"}):
        call("learn", action="add", deck="Half", **bad)
    assert learn.find_deck("Half") is None                                # wrong cards make no deck


# ---------------- fitness ----------------
@pytest.mark.parametrize("kind,value,unit,want", [("water", "250", "", 250), ("water", "2 glasses", "", 500), ("water", "1.5 l", "", 1500), ("water", 2, "glasses", 500), ("water", "۲۵۰", "", 250),
                                                  ("steps", "8,500", "", 8500), ("steps", "10000 steps", "", 10000), ("sleep", "7:30", "", 7.5), ("sleep", "7h 30m", "", 7.5), ("sleep", "450 min", "", 7.5),
                                                  ("sleep", "7 hours 15 minutes", "", 7.25), ("sleep", 8, "", 8), ("weight", "70,5", "", 70.5), ("weight", "154 lb", "", 69.9), ("weight", "72kg", "", 72)])
def test_amounts(kind, value, unit, want):
    assert fit.amount(kind, value, unit) == want


@pytest.mark.parametrize("kind,value,unit", [("water", "", ""), ("water", "-5", ""), ("water", "nan", ""), ("water", "20000", ""), ("water", "2 miles", ""), ("steps", "inf", ""), ("steps", "0", ""), ("sleep", "25", ""),
                                             ("sleep", "7:75", ""), ("weight", "5", ""), ("weight", "999", ""), ("heart", "70", ""), ("water", None, ""), ("water", "1e9", ""), ("weight", "70; DROP", "")])
def test_bad_amounts(kind, value, unit):
    with pytest.raises(ValueError):
        fit.amount(kind, value, unit)


def test_adding_up_and_replacing(db):
    fit.add("water", "2 glasses")
    r = fit.add("water", 250)
    assert r["total"] == 750 and fit.add("weight", 70)["total"] == 70 and fit.add("weight", 71)["total"] == 71 and fit.add("sleep", "7:30", "yesterday")["day"] == (TODAY - timedelta(days=1)).isoformat()
    assert len(fit.rows("weight")) == 1 and fit.delete(r["id"]) and not fit.delete(r["id"]) and fit.day_total("water", TODAY.isoformat()) == 500
    with pytest.raises(ValueError):
        fit.add("water", "9.9 l")                                         # two slips of the finger: more than anyone drinks
    for bad in ((TODAY + timedelta(days=1)).isoformat(), "1900-01-01", "nonsense"):
        with pytest.raises(ValueError):
            fit.add("water", 250, bad)


def test_workouts(db):
    w = fit.add_workout("Running", 30, "", 5, "by the  canal")
    assert w["what"] == "run" and w["pace"] == "6:00 min/km" and w["note"] == "by the canal" and fit.week_minutes() == 30
    fit.add_workout("gym", "45", (TODAY - timedelta(days=TODAY.weekday() + 1)).isoformat())                  # last week's
    assert fit.week_minutes() == 30 and fit.add_workout("cricket", 60, workout_id=w["id"])["what"] == "cricket"
    for bad in (("", 30), ("run", 0), ("run", 2000), ("run", "x"), ("x" * 41, 30), ("run", 30, "", -1), ("run", 30, "", 5000), ("run", 30, "", 5, "n" * 301)):
        with pytest.raises(ValueError):
            fit.add_workout(*bad)
    with pytest.raises(ValueError):
        fit.add_workout("run", 30, workout_id=99)
    assert fit.delete_workout(w["id"]) and not fit.delete_workout(w["id"])


def test_overview_and_bmi(db):
    assert fit.overview()["weight"] is None and "Weight" not in fit.describe(fit.overview())
    fit.add("weight", 74, (TODAY - timedelta(days=20)).isoformat())
    fit.add("weight", 72)
    fit.save_settings({"height": "180"})
    o = fit.overview()
    assert o["bmi"] == 22.2 and o["change"] == -2 and o["weight"] == 72 and len(fit.series("weight")) == 30
    assert "BMI 22.2" in fit.describe(o) and "-2 kg in 30 days" in fit.describe(o)
    fit.save_settings({"height": ""})
    assert fit.overview()["bmi"] is None
    json.dumps(fit.load())


def test_fit_settings(db):
    fit.save_settings({"targets": {"water": "2500", "sleep": 7.5}, "water_every": 2, "water_from": "8:00", "water_to": "22:00", "move": "18:00"})
    s = fit.settings()
    assert s["targets"]["water"] == 2500 and s["targets"]["steps"] == 8000 and (s["water_every"], s["water_from"], s["move"]) == (2, "08:00", "18:00")
    for bad in ({"targets": {"water": 5}}, {"targets": {"heart": 5}}, {"targets": {"steps": "x"}}, {"height": 20}, {"height": "tall"}, {"water_every": 9}, {"water_from": "23:00"}, {"move": "99"}):
        with pytest.raises(ValueError):
            fit.save_settings(bad)
    assert fit.settings()["water_from"] == "08:00"
    schedule.set_setting("fit_targets", {"water": "lots", "steps": True})
    schedule.set_setting("fit_height", "x")
    assert fit.targets()["water"] == 2000 and fit.targets()["steps"] == 8000 and fit.settings()["height"] is None


def test_fit_reminders(db):
    got = []
    say = lambda t, k: got.append(t)                                      # noqa: E731
    at = lambda h, m=0: NOON.replace(hour=h, minute=m)                    # noqa: E731
    assert fit.tick(NOON, say) == 0
    fit.save_settings({"water_every": 3, "water_from": "09:00", "water_to": "21:00"})
    assert [fit.tick(t, say) for t in (at(8, 59), at(9), at(9, 1), at(11, 59), at(12, 2), at(13), at(21), at(21, 20), at(23))] == [0, 1, 0, 0, 1, 0, 1, 0, 0]
    fit.add("water", 2000)
    assert fit.tick(at(15), say) == 0                                     # enough for today
    fit.save_settings({"water_every": 0, "move": "18:00"})
    assert fit.tick(at(18), say) == 1 and fit.tick(at(18, 1), say) == 0 and "move" in got[-1]
    fit.add_workout("walk", 20)
    schedule.set_setting("fit_move_said", "")
    assert fit.tick(at(18), say) == 0


def test_fit_export(db):
    fit.add("water", 250)
    fit.add_workout("=cmd()", 30, note="+1")
    p = fit.export(db)
    rows = list(csv.reader(p.read_text(encoding="utf-8-sig").splitlines()))
    assert len(rows) == 3 and not any(c[:1] in "=+-@" and not c.replace("-", "").isdigit() for r in rows for c in r if c) and fit.export(db) != p


# ---------------- private ----------------
def test_the_ai_writes_but_reads_only_if_allowed(db):
    assert call("fitness", action="log", what="water", value="2 glasses") == f"Noted: water 500 ml ({TODAY.isoformat()}). That makes 500 ml of 2 l."
    assert "weight 70.5 kg" in call("fitness", action="log", what="weight", value="70.5") and "walk, 30 minutes, 2.5 km" in call("fitness", action="workout", what="walk", value="30", km=2.5, note="SECRETNOTE")
    for a in ("summary", "history"):
        assert "closed to you" in call("fitness", action=a, what="weight")
    fit.save_settings({"ai": True})
    r = call("fitness", action="summary")
    assert "Weight: 70.5 kg" in r and "no medical advice" in r
    assert call("fitness", action="history", what="weight").startswith('<untrusted source="fitness">') and "SECRETNOTE" in call("fitness", action="history", what="workouts")
    fit.save_settings({"ai": "yes"})
    assert fit.settings()["ai"] is False                                  # only a real yes
    assert "from 20 to 400" in call("fitness", action="log", what="weight", value="4") and "Unknown action" in call("fitness", action="delete")
    log = (db / "audit.log").read_text(encoding="utf-8")
    assert '"fitness"' in log and not any(x in log for x in ("70.5", "SECRETNOTE", "glasses", "weight"))


def test_no_agent_or_automation_has_fitness(db):
    with pytest.raises(ValueError):
        agents.save("F", "r", ["fitness"])
    a = agents.save("L", "r", ["learn"])
    with pytest.raises(ValueError):
        agents.save("Both", "r", ["learn", "web_search"])                 # private things and the web, never both
    c = agents.AgentContext(ctx(), agents.get(a["id"]))
    assert "may only use learn" in tools.execute("learn", {"action": "grade", "card": 1, "how": "good"}, c)[0] and "No decks" in tools.execute("learn", {"action": "decks"}, c)[0]
    for t in ("fitness", "learn"):
        with pytest.raises(ValueError):
            automations.check_step({"tool": t, "args": {"action": "decks"}})
    assert {"learn", "fitness"} <= set(providers.LOCAL_TOOLS) & set(providers.BIG_TOOLS) and "fitness" not in agents.AGENT_TOOLS
    assert plans.LOOKING >= {"learn:quiz", "fitness:summary"} and "fitness:log" not in plans.LOOKING and "learn:add" not in plans.LOOKING
    assert guard.is_untrusted("learn", {"action": "quiz"}) and not guard.is_untrusted("learn", {"action": "add"})


def test_database_upgrade_keeps_everything(db):
    storage.close()
    c = sqlite3.connect(db / "old.db")
    for sql in storage.MIGRATIONS[:10]:
        c.executescript(sql)
    c.execute("INSERT INTO timers (kind, label, total) VALUES ('timer', 'keep me', 5)")
    c.execute("PRAGMA user_version = 10")
    c.commit()
    assert storage.migrate(c) == len(storage.MIGRATIONS) and c.execute("SELECT label FROM timers").fetchone() == ("keep me",)
    assert c.execute("SELECT (SELECT count(*) FROM cards), (SELECT count(*) FROM fit_log)").fetchone() == (0, 0)
    c.close()

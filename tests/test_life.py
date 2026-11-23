"""Phase 7, part 3: goals and habits, journal, money. Temporary database and settings."""
import csv
import json
from datetime import date, datetime, timedelta

import pytest

from jarvis import agents, audit, automations, guard, life, plans, schedule, storage, tools

TODAY = date.today()


def ago(n):
    return (TODAY - timedelta(days=n)).isoformat()


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


def ctx(answer=True, asked=None):
    def confirm(q, **k):
        if asked is not None:
            asked.append(q)
        return answer
    return tools.ToolContext(confirm=confirm, notify=lambda *a, **k: None)


def call(tool_, answer=True, asked=None, **args):
    return tools.execute(tool_, args, ctx(answer, asked))[0]


# ---------------- money: amounts ----------------
@pytest.mark.parametrize("text,want", [("1500", 150000), (1500, 150000), (1500.5, 150050), ("1,500.50", 150050), ("Rs 1,500", 150000), ("rs.500", 50000),
                                       ("1.5k", 150000), ("2 lakh", 20000000), ("1 crore", 1000000000), ("3 hazar", 300000), ("۱۵۰۰", 150000), ("٢٥٠", 25000),
                                       ("500 rupees", 50000), ("1,50,000", 15000000), ("$12.99", 1299), (0.1, 10), (0.29, 29), ("1500/-", 150000), (".5", 50), (1e3, 100000)])
def test_amounts(text, want):
    assert life.amount(text) == want


@pytest.mark.parametrize("bad", ["", None, "abc", "-5", "0", 0, -1, True, "nan", "inf", float("nan"), float("inf"), "1e99", "12 34", "1,5", "1..5", "=1+1", "1 crore crore",
                                 "99999999999999", "0.001", [], {}])
def test_bad_amounts(bad):
    with pytest.raises(ValueError):
        life.amount(bad)


def test_sums_are_exact(db):
    for _ in range(1000):
        life.save_money(0.1, "out", "Tea")
    assert life.summary()["out"] == 10000 and life.show(10000, "Rs") == "Rs 100" and life.show(-1050, "$") == "-$10.50" and life.show(123456789, "Rs") == "Rs 1,234,567.89"


@pytest.mark.parametrize("text,want", [("", "2026-11"), ("last month", "2026-10"), ("2026-3", "2026-03"), ("2026-03-15", "2026-03"), ("december", "2025-12"), ("nov", "2026-11"),
                                       ("march 2025", "2025-03")])
def test_months(text, want):
    assert life.month_of(text, date(2026, 11, 23)) == want


@pytest.mark.parametrize("bad", ["2026-13", "someday", "0000-01", "99999-01", "'; DROP", "%"])
def test_bad_months(bad):
    with pytest.raises(ValueError):
        life.month_of(bad)


def test_month_adding():
    assert life.month_add("2026-11", 2) == "2027-01" and life.month_add("2026-01", -1) == "2025-12" and life.month_add("2026-11", 0) == "2026-11"


# ---------------- money: entries ----------------
def test_money_entries_and_summary(db):
    month = TODAY.isoformat()[:7]
    first = f"{month}-01"
    a = life.save_money("1,500", "out", "Groceries", "milk", first)
    life.save_money(500, "spent", "groceries", day=first)
    life.save_money(90000, "in", "", "salary", first)
    assert a["category"] == "Groceries" and {r["category"] for r in life.list_money(month)} == {"Groceries", "Income"}      # one spelling
    s = life.summary()
    assert (s["in"], s["out"], s["left"]) == (9000000, 200000, 8800000) and s["categories"] == [{"category": "Groceries", "spent": 200000, "budget": None}]
    assert len(s["trend"]) == 6 and s["trend"][-1] == {"month": month, "in": 9000000, "out": 200000}
    life.set_budget("GROCERIES", 1800)
    life.set_budget("Fuel", "5k")
    s = life.summary()
    assert s["categories"][0]["budget"] == 180000 and {"category": "Fuel", "spent": 0, "budget": 500000} in s["categories"] and s["budget"] == 680000
    assert "over by Rs 200" in life.describe_summary(s)
    life.set_budget("fuel", 0)
    assert all(c["category"] != "Fuel" for c in life.summary()["categories"])
    b = life.save_money(note="bread", entry_id=a["id"])
    assert b["note"] == "bread" and b["amount"] == 150000 and b["day"] == first
    assert [r["note"] for r in life.list_money(month, "bread")] == ["bread"] and life.money_delete(a["id"]) and life.get_money(a["id"]) is None


@pytest.mark.parametrize("kw", [{"value": ""}, {"value": 5, "kind": "x"}, {"value": 5, "day": "tomorrow"}, {"value": 5, "day": "2026-02-30"}, {"value": 5, "category": "c" * 41},
                                {"value": 5, "note": "n" * 201}, {"value": 5, "day": "1800-01-01"}])
def test_bad_money(db, kw):
    with pytest.raises(ValueError):
        life.save_money(**kw)
    assert life.list_money() == []


def test_days_look_back():
    assert life._past_day("kal", "x") == ago(1) and life._past_day("yesterday", "x") == ago(1) and life._past_day("", "x") == ago(0)
    for d in ("monday", "friday", "sunday"):
        got = date.fromisoformat(life._past_day(d, "x"))
        assert TODAY - timedelta(days=7) <= got <= TODAY and got.strftime("%A").lower() == d
    with pytest.raises(ValueError):
        life._past_day("tomorrow", "x")
    assert life._past_day("parson", "x") == ago(2) and life._past_day("last friday", "x") == life._past_day("friday", "x")


# ---------------- bills ----------------
def at(monkeypatch, day):
    class D(date):
        @classmethod
        def today(cls):
            return cls.fromisoformat(day)
    monkeypatch.setattr(life, "date", D)


def test_bills_go_month_by_month(db, monkeypatch):
    at(monkeypatch, "2026-01-20")
    b = life.save_bill("Rent", "45,000", "Home", 31)
    assert (b["month"], b["due"], b["days"]) == ("2026-01", "2026-01-31", 11)
    r = life.bill_paid(b["id"])
    assert (r["amount"], r["category"], r["note"], r["bill_month"]) == (4500000, "Home", "Rent", "2026-01")
    assert life.bills()[0]["due"] == "2026-02-28"                                  # the 31st of a short month
    life.money_delete(r["id"])
    assert life.bills()[0]["month"] == "2026-01"                                   # not paid after all
    life.bill_skip(b["id"])
    assert life.bills()[0]["month"] == "2026-02" and life.list_money() == []
    life.bill_paid(b["id"], 46000)
    with pytest.raises(ValueError, match="already"):
        life.bill_paid(b["id"])                                                    # 31 March is more than 45 days off
    at(monkeypatch, "2026-05-02")
    assert (life.bills()[0]["month"], life.bills()[0]["days"]) == ("2026-03", -32)  # the oldest unpaid month comes first
    assert life.bill_delete(b["id"]) and [x["bill"] for x in life.list_money()] == [None]      # what was paid stays


def test_a_bill_made_after_its_day_starts_next_month(db, monkeypatch):
    at(monkeypatch, "2026-12-20")
    assert life.save_bill("Net", 2000, None, 5)["due"] == "2027-01-05" and life.save_bill("Gas", 900, "", 20)["due"] == "2026-12-20"


def test_bad_bills(db):
    life.save_bill("Rent", 10, None, 5)
    for kw in ({"name": "", "value": 5, "day": 5}, {"name": "x", "value": 0, "day": 5}, {"name": "x", "value": 5, "day": 0}, {"name": "x", "value": 5, "day": 32},
               {"name": "x", "value": 5, "day": "five"}, {"name": "RENT", "value": 5, "day": 5}, {"name": "x", "value": 5, "day": 5, "remind": 99}):
        with pytest.raises(ValueError):
            life.save_bill(**kw)
    with pytest.raises(ValueError):
        life.bill_paid(999)
    assert len(life.bills()) == 1


def test_bill_reminders_come_once(db, monkeypatch):
    at(monkeypatch, "2026-03-01")
    b = life.save_bill("Rent", 45000, "Home", 10, 2)
    said = []

    def tick(text):
        life.tick(datetime.fromisoformat(text), lambda t, k: said.append(t))
    tick("2026-03-07T12:00")
    tick("2026-03-08T08:59")
    assert said == []
    tick("2026-03-08T09:00")
    tick("2026-03-08T15:00")
    tick("2026-03-09T09:00")
    assert len(said) == 1 and "Rent (Rs 45,000)" in said[0]
    tick("2026-03-10T10:00")
    tick("2026-03-11T10:00")
    assert len(said) == 2 and "due today" in said[1]
    life.bill_paid(b["id"], day="2026-03-01")
    tick("2026-03-12T10:00")
    assert len(said) == 2
    tick("2026-05-30T10:00")                                                       # far too late to nag about April
    assert len(said) == 2


# ---------------- goals ----------------
def test_goals(db):
    g = life.save_goal("Read books", "To learn", "Mind", 20, "books", "2030-12-31")
    assert g["percent"] == 0 and life.save_goal(progress=5, goal_id=g["id"])["percent"] == 25
    assert life.save_goal(progress=99, goal_id=g["id"])["percent"] == 100 and life.save_goal(progress=-5, goal_id=g["id"])["percent"] == 0
    h = life.save_goal("Move house", steps=["Find a flat", "Sign", "", "Move"], due=ago(1))
    assert [x["text"] for x in h["steps"]] == ["Find a flat", "Sign", "Move"] and life.goal_step(h["id"], 2)["percent"] == 33
    h = life.save_goal(steps="find a flat\nSign\nPack\nMove", goal_id=h["id"])
    assert [x["done"] for x in h["steps"]] == [False, True, False, False]           # ticks stay with their step
    assert [x["id"] for x in life.goals(False)] == [h["id"], g["id"]]               # nearest day first
    assert life.save_goal(due="", target="", goal_id=g["id"])["due"] is None and life.get_goal(g["id"])["target"] is None and life.get_goal(g["id"])["title"] == "Read books"
    life.goal_done(g["id"])
    assert life.get_goal(g["id"])["percent"] == 100 and life.find_goal("read") and life.find_goal("read", False) is None
    assert life.goal_delete(h["id"]) and life.get_goal(h["id"]) is None


@pytest.mark.parametrize("kw", [{"title": ""}, {"title": "x" * 161}, {"title": "x", "target": "many"}, {"title": "x", "target": 0}, {"title": "x", "target": -1},
                                {"title": "x", "target": "nan"}, {"title": "x", "target": "1e12"}, {"title": "x", "due": "someday"}, {"title": "x", "progress": True},
                                {"title": "x", "steps": ["s" * 161]}, {"title": "x", "steps": ["s"] * 41}, {"title": "x", "why": "w" * 2001}, {"title": "x", "area": "a" * 41}])
def test_bad_goals(db, kw):
    with pytest.raises(ValueError):
        life.save_goal(**kw)
    assert life.goals() == []


def test_bad_steps(db):
    g = life.save_goal("x", steps=["a"])
    for n in (0, 2, "one", None, -1, 1.5):
        with pytest.raises(ValueError):
            life.goal_step(g["id"], n)


# ---------------- habits ----------------
def days(*back, base=date(2026, 11, 25)):                                          # a Wednesday
    return {(base - timedelta(days=n)).isoformat() for n in back}


@pytest.mark.parametrize("have,per,want", [((), 7, (0, 0)), ((0,), 7, (1, 1)), ((1, 2, 3), 7, (3, 3)), ((2, 3), 7, (0, 2)), ((0, 1, 2, 10, 11, 12, 13), 7, (3, 4)),
                                           ((0, 1, 2), 3, (1, 1)), ((0, 1), 3, (0, 0)), ((3, 4, 5, 10, 11, 12), 3, (2, 2)), ((0, 1, 2, 3, 4, 5), 3, (2, 2)),
                                           ((10, 11, 12), 3, (0, 1)), ((0, 7, 14, 21), 1, (4, 4)), ((7, 14, 28), 1, (2, 2))])
def test_streaks(have, per, want):
    assert life.streak(days(*have), per, date(2026, 11, 25)) == want


def test_streak_over_new_year():
    assert life.streak(days(*range(60), base=date(2027, 1, 20)), 7, date(2027, 1, 20)) == (60, 60)
    assert life.streak({"2026-12-30", "2027-01-02", "2027-01-05"}, 1, date(2027, 1, 6)) == (2, 2)      # one week holds both 30 Dec and 2 Jan


def test_habits(db):
    h = life.save_habit("Walk", 7, "18:30")
    for n in (0, 1, 2):
        h = life.habit_mark(h["id"], ago(n))
    life.habit_mark(h["id"], ago(0))                                               # twice is once
    h = life.find_habit("walk")
    assert (h["streak"], h["best"], h["total"], h["today"], len(h["days"])) == (3, 3, 3, True, 14) and h["days"][-1] == {"day": ago(0), "on": True}
    assert life.habit_mark(h["id"], "", False)["today"] is False and life.find_habit("walk")["streak"] == 2
    with pytest.raises(ValueError):
        life.habit_mark(h["id"], "2999-01-01")
    with pytest.raises(ValueError):
        life.habit_mark(999, "")
    with pytest.raises(ValueError):
        life.save_habit("WALK")
    for kw in ({"name": ""}, {"name": "x", "per_week": 0}, {"name": "x", "per_week": 8}, {"name": "x", "remind": "25:00"}, {"name": "n" * 61}):
        with pytest.raises(ValueError):
            life.save_habit(**kw)
    assert life.save_habit(per_week=3, remind="", habit_id=h["id"])["unit"] == "weeks"
    assert life.habit_delete(h["id"]) and life.habits() == []


def test_habit_and_journal_reminders(db):
    h = life.save_habit("Walk", 7, "18:30")
    life.save_settings({"journal_remind": "21:00"})
    said = []

    def tick(hm):
        life.tick(datetime.fromisoformat(f"{ago(0)}T{hm}"), lambda t, k: said.append(t))
    for hm in ("08:00", "18:29", "18:30", "18:31", "18:39"):
        tick(hm)
    assert said == ["Reminder: Walk."]
    tick("21:15")                                                                  # too late
    assert len(said) == 1
    tick("21:05")
    tick("21:06")
    assert len(said) == 2 and "journal" in said[1]
    schedule.set_setting("journal_reminded", None)
    life.save_entry("good day")
    life.habit_mark(h["id"])
    c, lock = life._db()
    with lock, c:
        c.execute("UPDATE habits SET reminded = NULL")
    tick("18:30")
    tick("21:00")
    assert len(said) == 2                                                          # both were done


# ---------------- journal ----------------
def test_journal(db):
    a = life.save_entry("First\n\nline", 4, "yesterday")
    b = life.save_entry("اچھا دن تھا", "great")
    assert [e["id"] for e in life.entries()] == [b["id"], a["id"]] and a["text"] == "First\n\nline" and b["mood"] == 5
    assert [e["id"] for e in life.entries("اچھا")] == [b["id"]] and [e["id"] for e in life.entries("FIRST")] == [a["id"]]
    m = life.moods()
    assert m["average"] == 4.5 and m["written"] == 2 and len(m["days"]) == 30 and m["days"][-1]["mood"] == 5
    assert life.save_entry(mood=0, entry_id=a["id"])["mood"] is None and life.save_entry(text="x", entry_id=a["id"])["day"] == ago(1)
    assert life.entry_delete(a["id"]) and len(life.entries()) == 1


@pytest.mark.parametrize("kw", [{}, {"text": " "}, {"text": "x", "mood": 6}, {"text": "x", "mood": "meh"}, {"text": "x", "mood": 2.5}, {"text": "x" * 10_001}, {"text": "x", "day": "tomorrow"}])
def test_bad_entries(db, kw):
    with pytest.raises(ValueError):
        life.save_entry(**kw)
    assert life.entries() == []


def test_the_ai_cant_read_the_journal_until_allowed(db):
    life.save_entry("SECRETWORD")
    for args in ({}, {"query": "SECRET"}, {"day": "2020-01-01"}):
        out = call("journal", action="read", **args)
        assert "SECRETWORD" not in out and "closed" in out
    life.save_settings({"journal_ai": True})
    out = call("journal", action="read")
    assert "SECRETWORD" in out and out.startswith("<untrusted")
    life.save_settings({"journal_ai": "yes"})                                      # only a real true opens it
    assert "SECRETWORD" not in call("journal", action="read")


def test_the_journal_stays_out_of_the_logs(db, monkeypatch):
    seen = []
    monkeypatch.setattr(tools, "RESULT_HOOK", lambda *a: seen.append(a))
    life.save_settings({"journal_ai": True})
    call("journal", action="add", text="SECRETWORD", mood=2)
    call("journal", action="read", query="SECRETWORD")
    log = (db / "audit.log").read_text(encoding="utf-8")
    assert len(life.entries("SECRETWORD")) == 1 and '"tool": "journal"' in log
    assert "SECRETWORD" not in log and "SECRETWORD" not in json.dumps(seen)
    assert guard.for_logs("money", {"text": "x"}) == {"text": "x"}


# ---------------- settings and files ----------------
def test_settings(db):
    assert life.settings() == {"currency": "Rs", "journal_ai": False, "journal_remind": ""}
    for c in ("PKR", "$", "Rs.", "€"):
        life.save_settings({"currency": c})
        assert life.settings()["currency"] == c
    for bad in ({"currency": ""}, {"currency": "<b>"}, {"currency": "toolong"}, {"currency": "R s"}, {"journal_remind": "99:99"}):
        with pytest.raises(ValueError):
            life.save_settings(bad)
    life.save_settings({"journal_remind": ""})
    assert life.settings()["journal_remind"] == ""


def test_export(db, tmp_path):
    out = tmp_path / "Documents"
    life.save_money(1500.5, "out", "=HYPERLINK(1)", "+cmd|x, \"q\"")
    a, b = life.export("money", out), life.export("money", out)
    assert a != b and a.suffix == ".csv" and b.name.endswith("(2).csv")
    rows = list(csv.reader(a.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[1][2:] == ["1500.50", "'=HYPERLINK(1)", "'+cmd|x, \"q\""]
    life.save_entry("دن اچھا تھا", 4)
    assert "(good)\nدن اچھا تھا" in life.export("journal", out).read_text(encoding="utf-8-sig")
    with pytest.raises(ValueError):
        life.export("../x", out)


# ---------------- the AI's tools ----------------
def test_money_by_voice(db):
    assert "Rs 1,500 Groceries" in call("money", action="spent", amount=1500, category="Groceries")
    assert "a moment ago" in call("money", action="spent", amount=1500, category="groceries") and len(life.list_money()) == 1
    call("money", action="budget", category="Groceries", amount=1600)
    assert "over the Groceries budget by Rs 100" in call("money", action="spent", amount=200, category="Groceries", note="eggs")
    out = call("money", action="summary")
    assert out.startswith("<untrusted") and "out Rs 1,700" in out
    call("money", action="add_bill", name="Electricity", amount=9000, due_day=(TODAY + timedelta(days=1)).day)
    assert "Nothing was paid by the app" in call("money", action="bill_paid", name="electricity")
    assert "already written as paid today" in call("money", action="bill_paid", name="electricity") and len(life.list_money()) == 3
    i, asked = life.list_money()[0]["id"], []
    assert call("money", answer=False, asked=asked, action="delete", name=str(i)) == "Okay, I kept it." and len(asked) == 1
    assert "Deleted" in call("money", action="delete", name=f"#{i}") and len(life.list_money()) == 2
    for args in ({"action": "spent"}, {"action": "spent", "amount": -5}, {"action": "nope"}, {"action": "delete", "name": "x"}, {"action": "bill_paid", "name": "zzz"},
                 {"action": "summary", "month": "someday"}, {"action": "add_bill", "name": "x", "amount": 5}):
        assert isinstance(call("money", **args), str)
    assert len(life.list_money()) == 2


def test_goals_by_voice(db):
    call("goals", action="add_goal", name="Read books", target=20, unit="books")
    assert "5 of 20 books, 25%" in call("goals", action="progress", name="read", value=5)
    assert "7 of 20 books" in call("goals", action="progress", name="read", add=2)
    assert "Say how far" in call("goals", action="progress", name="read")
    call("goals", action="add_habit", name="Walk", per_week=7)
    assert "done today" in call("goals", action="habit_done", name="walk") and "not yet today" in call("goals", action="habit_undo", name="walk")
    assert "can't tell which" in call("goals", action="habit_done", name="swim")
    out = call("goals", action="list")
    assert out.startswith("<untrusted") and "Read books" in out and "Walk" in out
    asked = []
    call("goals", answer=False, asked=asked, action="delete_goal", name="read")
    call("goals", answer=False, asked=asked, action="delete_habit", name="walk")
    assert len(asked) == 2 and len(life.goals()) == 1 and len(life.habits()) == 1
    assert call("goals", action="reached", name="read") == "Reached: Read books."


def test_held_plans_still_allow_looking(db, monkeypatch):
    monkeypatch.setattr(plans, "_HOLD", "The user said no.")
    run = lambda n, **a: tools.execute(n, a, ctx(), from_ai=True)[0]  # noqa: E731
    assert run("money", action="spent", amount=5) == "The user said no." and run("journal", action="add", text="x") == "The user said no."
    assert run("goals", action="habit_done", name="x") == "The user said no." and "money in" in run("money", action="summary") and "No goals" in run("goals", action="list")
    assert life.list_money() == [] and life.entries() == []


def test_agents_never_get_the_journal_and_never_with_the_web(db):
    assert "journal" not in agents.AGENT_TOOLS and {"goals", "money"} <= agents.PRIVATE
    with pytest.raises(ValueError):
        agents.check("A", "x", ["journal"], False)
    for t in ("goals", "money"):
        with pytest.raises(ValueError, match="not both"):
            agents.check("A", "x", ["web_search", t], False)
    assert "spent" not in agents.LIMITS["money"] and "delete_goal" not in agents.LIMITS["goals"]


def test_automations_only_look(db):
    assert automations.check_step({"tool": "money", "args": {"action": "summary"}})["args"] == {"action": "summary"}
    for bad in ({"tool": "money", "args": {"action": "spent", "amount": 5}}, {"tool": "money", "args": {"action": "summary", "month": "x"}}, {"tool": "journal", "args": {"action": "read"}},
                {"tool": "goals", "args": {"action": "habit_done", "name": "x"}}):
        with pytest.raises(ValueError):
            automations.check_step(bad)
    assert automations.STEP_TOOLS["money"] == {"action": ("summary", "bills")} and automations.STEP_TOOLS["goals"] == {"action": ("list",)}
    assert "journal" not in automations.STEP_TOOLS and automations.ONLY["money"] == ("action",)


def test_the_database_upgrades(tmp_path):
    import sqlite3
    c = sqlite3.connect(tmp_path / "old.db")
    for sql in storage.MIGRATIONS[:8]:
        c.executescript(sql)
    c.execute("PRAGMA user_version = 8")
    storage.migrate(c)
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"goals", "habits", "habit_log", "journal", "money", "budgets", "bills", "tasks"} <= names
    c.close()

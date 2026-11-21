"""Phase 4, part 2: skills (your own rules and routines) and the memory knowledge graph."""
import pytest

from jarvis import brain, memory, skills, storage, tools


@pytest.fixture
def db(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "memory.json")
    yield tmp_path
    storage.close()


def ctx(answer=True, asked=None):
    def confirm(q, **k):
        if asked is not None:
            asked.append(q)
        return answer
    return tools.ToolContext(confirm=confirm, notify=lambda *a, **k: None)


def test_save_edit_find_and_limits(db):
    s = skills.save("Morning briefing", "Weather, prayer times, reminders.")
    assert s["mode"] == "ask" and s["enabled"]
    assert skills.find("morning BRIEFING")["id"] == s["id"]
    assert skills.find("morning")["id"] == s["id"]                    # unique start of a name is enough
    skills.save("Short answers", "Two or three sentences.", "always")
    assert [k["name"] for k in skills.all_skills()] == ["Short answers", "Morning briefing"]   # rules first
    with pytest.raises(ValueError, match="already"):
        skills.save("morning briefing", "again")
    with pytest.raises(ValueError):
        skills.save("", "x")
    with pytest.raises(ValueError):
        skills.save("Long", "x" * (skills.MAX_TEXT + 1))
    with pytest.raises(ValueError):
        skills.save("Odd", "x", mode="sometimes")
    s2 = skills.save("Morning brief", "Only the weather.", skill_id=s["id"])
    assert s2["name"] == "Morning brief" and skills.get(s["id"])["instructions"] == "Only the weather."


def test_prompt_has_enabled_skills_only(db):
    skills.save("Short answers", "Keep it to two sentences.", "always")
    r = skills.save("Study quiz", "Ask me 5 questions.")
    p = skills.prompt_text()
    assert "own rules" in p and "Keep it to two sentences." in p and "Study quiz: Ask me 5 questions." in p
    skills.set_enabled(r["id"], False)
    assert "Study quiz" not in skills.prompt_text()
    assert "Keep it to two sentences." in brain.system_prompt()       # every conversation gets the rules


def test_prompt_budget_lists_the_rest_by_name(db, monkeypatch):
    monkeypatch.setattr(skills, "PROMPT_BUDGET", 120)
    skills.save("Alpha", "a" * 90)
    skills.save("Beta", "b" * 90)
    p = skills.prompt_text()
    assert "a" * 90 in p and "b" * 90 not in p and "use_skill" in p and "Beta" in p


def test_empty_prompt_without_skills(db):
    assert skills.prompt_text() == ""


def test_use_skill_tool(db):
    skills.save("Morning briefing", "Weather and prayer times.")
    out, err = tools.execute("use_skill", {"name": "morning briefing"}, ctx())
    assert not err and "Weather and prayer times." in out and skills.all_skills()[0]["uses"] == 1
    out, _ = tools.execute("use_skill", {"name": "nothing"}, ctx())
    assert "No skill" in out and "Morning briefing" in out


def test_ai_can_save_a_skill_only_with_your_ok(db):
    asked = []
    out, _ = tools.execute("save_skill", {"name": "Bedtime", "instructions": "Lock the PC at 1 am.", "mode": "always"}, ctx(False, asked))
    assert "not saved" in out and skills.all_skills() == [] and "Bedtime" in asked[0]
    out, _ = tools.execute("save_skill", {"name": "Bedtime", "instructions": "Remind me to sleep at 12."}, ctx(True))
    assert out.startswith("Saved") and skills.find("Bedtime")["mode"] == "ask"
    out, _ = tools.execute("save_skill", {"name": "bedtime", "instructions": "Remind me at 11."}, ctx(True))
    assert out.startswith("Updated") and len(skills.all_skills()) == 1


def test_save_skill_is_refused_while_stopped(db):
    tools.STOP.set()
    try:
        out, _ = tools.execute("save_skill", {"name": "X", "instructions": "y"}, ctx(True))
    finally:
        tools.STOP.clear()
    assert skills.all_skills() == []


def test_run_message(db):
    s = skills.save("Study quiz", "Ask me 5 questions.")
    assert skills.run_message(s) == 'Run my skill "Study quiz":\nAsk me 5 questions.'


def test_names(db):
    assert memory._names("My sister Hina's birthday is 5 March") == {"Hina"}
    assert memory._names("Mera naam Gul hai aur main Islamabad mein rehta hoon") == {"Gul", "Islamabad"}
    assert memory._names("Likes green tea every Sunday") == set()


def test_graph_links_names_in_two_memories(db):
    for f in ["My sister Hina lives in Lahore", "Hina's birthday is 5 March", "Likes green tea",
              "Goes to Lahore every Eid", "Works at a bank in Karachi"]:
        memory.remember(f)
    g = memory.graph()
    ids = {n["id"]: n for n in g["nodes"]}
    assert ids["you"]["kind"] == "you"
    assert {n["label"] for n in g["nodes"] if n["kind"] == "name"} == {"Hina", "Lahore"}     # Karachi only once
    assert "c:family" in ids and "c:preferences" in ids and "c:work" in ids
    targets = {(l["source"], l["target"]) for l in g["links"]}
    hina = [m for m in memory.all_facts() if "Hina" in m["fact"]]
    assert all(("e:Hina", f"m:{m['id']}") in targets for m in hina)
    assert all(l["source"] in ids and l["target"] in ids for l in g["links"])


def test_graph_empty(db):
    g = memory.graph()
    assert [n["kind"] for n in g["nodes"]] == ["you"] and g["links"] == []

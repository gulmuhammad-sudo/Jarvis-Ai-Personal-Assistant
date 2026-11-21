"""Personal Intelligence Engine: memories in SQLite (safe import from memory.json), categories, importance,
search, what goes to the AI, and "Shall I remember that?" suggestions."""
import json

import pytest

from jarvis import memory, storage, tools


@pytest.fixture
def mem(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(memory, "MEMORY_FILE", tmp_path / "memory.json")
    yield tmp_path
    storage.close()


def test_old_memory_json_is_imported_once_and_kept_as_backup(mem):
    old = [{"id": 3, "fact": "Likes green tea", "saved": "2026-11-01T10:00"},
           {"id": 7, "fact": "My wife's birthday is 5 March", "saved": "2026-11-02T09:00"}]
    (mem / "memory.json").write_text(json.dumps(old), encoding="utf-8")
    facts = {m["id"]: m for m in memory.all_facts()}
    assert set(facts) == {3, 7} and facts[3]["created"] == "2026-11-01T10:00"       # ids and dates kept
    assert facts[3]["category"] == "preferences" and facts[7]["category"] == "family"
    assert not (mem / "memory.json").exists() and (mem / "memory.json.imported").exists()
    assert json.loads((mem / "memory.json.imported").read_text(encoding="utf-8")) == old   # backup untouched
    memory.all_facts()
    assert len(memory.all_facts()) == 2                                              # not imported twice


def test_remember_guesses_and_skips_duplicates(mem):
    assert "Saved memory" in memory.remember("I work at a bank as an analyst")
    assert "Already remembered" in memory.remember("i work at a bank, as an analyst!")
    m = memory.all_facts()[0]
    assert m["category"] == "work" and m["importance"] == 1 and m["source"] == "assistant"
    memory.remember("Allergic to peanuts")
    assert memory.find_same("allergic to peanuts")["importance"] == 2


def test_update_category_importance_and_bad_values(mem):
    memory.remember("Plays cricket on Sundays")
    mid = memory.all_facts()[0]["id"]
    assert "Updated" in memory.update(mid, category="routine", importance=3)
    m = memory.get(mid)
    assert m["category"] == "routine" and m["importance"] == 3
    assert "Unknown category" in memory.update(mid, category="secret")
    assert "can't be empty" in memory.update(mid, fact="   ")
    assert memory.all_facts()[0]["id"] == mid                                        # important ones first


def test_search_ranks_and_filters(mem):
    memory.remember("My son Ali goes to Beaconhouse school")
    memory.remember("Loves biryani")
    memory.remember("My daughter Sara likes painting")
    hits = memory.search("son school")
    assert hits and "Ali" in hits[0]["fact"]
    assert [m["fact"] for m in memory.search("", "preferences")] == ["Loves biryani"]
    assert memory.search("quantum physics") == []
    assert memory.counts()["family"] == 2


def test_only_the_top_memories_go_to_the_ai(mem):
    for i in range(70):
        memory.remember(f"Fact number {i} about the user")
    memory.update(memory.find_same("Fact number 5 about the user")["id"], importance=3)
    text = memory.as_text(limit=60)
    lines = [ln for ln in text.splitlines() if ln.startswith("#")]
    assert len(lines) == 60 and "Fact number 5 about" in lines[0]       # the key one is first
    assert "+10 more" in text


def test_merge(mem):
    memory.remember("Likes tea")
    memory.remember("Likes coffee in the morning")
    assert "Combined 2" in memory.merge()
    assert len(memory.all_facts()) == 1


@pytest.mark.parametrize("text", ["My name is Gul and I study computer science", "I'm allergic to penicillin",
                                  "mera naam Ahmed hai", "mujhe chai bahut pasand hai", "I work at Hum TV as a developer",
                                  "My wife's birthday is on 5 March"])
def test_suggests_lasting_facts_about_you(mem, text):
    s = memory.suggest_from(text)
    assert s and s["fact"].lower().startswith(text[:6].lower()) and s["category"] in memory.CATEGORIES


@pytest.mark.parametrize("text", ["what is my name?", "Kya time hai", "open chrome", "do I like tea?", "hi",
                                  "play some music on youtube"])
def test_does_not_suggest_questions_or_commands(mem, text):
    assert memory.suggest_from(text) is None


def test_no_suggestion_for_something_already_remembered(mem):
    memory.remember("My name is Gul")
    assert memory.suggest_from("my name is Gul") is None


def test_tools_use_search_and_categories(mem):
    c = tools.ToolContext(confirm=lambda q, **k: True, notify=lambda *a, **k: None)
    tools.execute("remember_fact", {"fact": "Goes to the gym at 7 am", "category": "health", "importance": 2}, c)
    m = memory.all_facts()[0]
    assert m["category"] == "health" and m["importance"] == 2
    out, err = tools.execute("recall_memories", {"query": "gym"}, c)
    assert not err and "gym" in out
    out, err = tools.execute("edit_memory", {"id": m["id"], "category": "routine"}, c)
    assert "Updated" in out and memory.get(m["id"])["category"] == "routine"

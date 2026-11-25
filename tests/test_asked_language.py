"""1.31.8: an answer asked for in a language stays in that language's own script. No AI is called (the rewriting is watched)."""
import re
import threading
import time
from pathlib import Path

import pytest

from jarvis import audit, brain, hud, languages, live, providers, schedule, storage, tools, urdu

HTML = hud.HTML_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.mark.parametrize("text, want", [
    ("Urdu mein batao", "ur"), ("mujhe urdu me btao na", "ur"), ("मुझे उर्दू में बताओ", "ur"), ("इसको हिंदी में बोल के बताओ", "hi"), ("اردو میں بتاؤ", "ur"), ("عربی میں لکھو", "ar"),
    ("mujhe is ka Arabic mein tarjuma batao", "ar"), ("translate this to Hindi", "hi"), ("Translate from Urdu to English please", "en"), ("say it in Pashto", "ps"), ("speak Urdu", "ur"), ("convert it to Urdu", "ur"),
    ("Roman mein likho", "roman"), ("roman urdu mein likho", "roman"), ("english letters mein likho", "roman"), ("English mein batao", "en"), ("urdu translation karo iska", "ur"), ("Sindhi mein bolo", "custom:Sindhi"),
    ("Korean mein thank you kaise kehte hain", "custom:Korean"), ("फ़ारसी में बताओ", "fa"), ("Urdu zaban mein samjhao", "ur"), ("German main kya kehte hain isko", "de"),
    ("hindi mein nahi urdu mein batao", "ur"), ("roman mein convert na karo urdu mein hi likho", "ur"), ("रोमन में ना कन्वर्ट करे उर्दू में ही लिख के दो", "ur"),
    ("रोमन में क्यों कन्वर्ट कर रही है", ""), ("don't write in Roman", ""), ("urdu mein mat likho", ""), ("What is the weather?", ""), ("I like Urdu poetry", ""), ("mujhe Chinese khana pasand hai", ""), ("French fries mangwao", ""),
    ("main urdu nahi janta", ""), ("open the file in english folder", "en"), ("to Urdu", ""), ("", ""), (None, ""), (5, "")])
def test_what_was_asked_for(text, want):
    assert languages.asked_for(text) == want


def test_very_long_is_quick():
    t = time.perf_counter()
    languages.asked_for("urdu mein " * 100_000)
    assert time.perf_counter() - t < 0.5


@pytest.fixture
def hub(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    h = hud.Hub()
    monkeypatch.setattr(hud, "HUB", h)
    h.did = []
    monkeypatch.setattr(urdu, "to_roman", lambda t: h.did.append(("roman", t)) or "ROMAN")
    monkeypatch.setattr(urdu, "to_urdu_script", lambda t: h.did.append(("urdu", t)) or "اردو")
    monkeypatch.setattr(urdu, "from_hindi", lambda t: h.did.append(("fix", t)) or "ٹھیک اردو")
    real = threading.Thread

    class Now(real):                                                        # at once, in order
        def start(self):
            if self._target == h._chat_text:
                return self._target(*self._args)
            return real.start(self)
    monkeypatch.setattr(hud.threading, "Thread", Now)
    yield h
    h.ringer.stop()
    storage.close()


def last(h):
    return h.history[-1]["text"]


def test_as_always_without_asking(hub):
    hub.submit("mausam kaisa hai")
    hub.on_text("آج موسم ٹھیک ہے")
    assert last(hub) == "ROMAN" and hub.asked == ""


def test_asked_in_urdu_stays_urdu_for_the_conversation(hub):
    hub.submit("mujhe Urdu mein batao mausam kaisa hai")
    hub.on_text("آج موسم ٹھیک ہے")
    hub.submit("aur kal?")
    hub.on_text("کل بارش ہے")
    assert [e["text"] for e in hub.history if e["type"] == "jarvis"][-2:] == ["آج موسم ٹھیک ہے", "کل بارش ہے"] and hub.did == []
    hub.submit("acha ab Roman mein likho")
    hub.on_text("کل بارش ہے")
    assert last(hub) == "ROMAN"


def test_an_answer_in_english_letters_is_put_right(hub):
    hub.submit("Urdu mein batao")
    hub.on_text("Aaj mausam theek hai, sir")
    assert last(hub) == "اردو" and hub.did[0][0] == "urdu"
    hub.did.clear()
    hub.submit("shukriya bhai jaan")
    assert hub.did == []                                                     # (what you typed stays as you typed it)


def test_other_languages(hub):
    hub.submit("isko Arabic mein translate karo")
    hub.on_text("کہتے ہیں: كيف حالك")
    assert last(hub).startswith("کہتے")                                       # that answer, whole
    hub.submit("theek hai, mausam batao")
    hub.on_text("موسم ٹھیک ہے")
    assert last(hub) == "ROMAN"                                               # then Urdu is Roman again
    hub.on_text("كيف حالك يا صديقي")
    assert last(hub) == "كيف حالك يا صديقي"                                   # Arabic is never turned into Roman
    for t in ("ستاسو نوم څه دی", "توهان جو نالو ڇا آهي ڳوٺ"):                # nor Pashto, Sindhi
        hub.on_text(t)
        assert last(hub) == t
    hub.submit("Hindi mein batao")
    hub.on_text("आज मौसम अच्छा है")
    assert last(hub) == "आज मौसम अच्छा है"


def test_english_letters_languages_when_the_chat_is_always_urdu(hub):
    schedule.set_setting("chat_script", "urdu")
    hub.on_text("The weather is fine")
    assert last(hub) == "اردو"
    hub.submit("English mein batao")
    hub.on_text("The weather is fine today")
    assert last(hub) == "The weather is fine today"
    hub.submit("isko French mein batao")
    hub.on_text("Il fait beau aujourd'hui")
    assert last(hub) == "Il fait beau aujourd'hui"


def test_live_calls(hub):
    hub._live_partial("user", "मुझे उर्दू में")                                # while you are still heard
    assert hub.asked == "ur"
    hub._live_heard("मुझे उर्दू में बताओ")
    hub._live_reply("आज मौसम ठीक है", False)
    assert hub.did[-1] == ("fix", "आज मौसम ठीक है") and last(hub) == "ٹھیک اردو"    # good Urdu, not letter by letter, not Roman
    assert not any(d[0] == "roman" for d in hub.did)
    hub.did.clear()
    hub._live_heard("अब हिंदी में बताओ")
    hub._live_reply("आज मौसम ठीक है", False)
    assert last(hub) == "आज मौसम ठीक है" and hub.did == []
    told = []
    hub.subscribers.append(type("Q", (), {"put": staticmethod(told.append)}))
    hub._live_partial("jarvis", "आज मौसम")
    assert told[-1]["text"] == "आज मौसम"
    hub._live_heard("रोमन में लिखो")
    hub._live_reply("आज मौसम ठीक है", False)
    assert last(hub) == "ROMAN"


def test_live_as_always(hub):
    hub._live_heard("मौसम कैसा है")
    hub._live_reply("आज मौसम ठीक है", False)
    assert last(hub) == "ROMAN" and {d[0] for d in hub.did} == {"roman"}


def test_only_your_own_words_count(hub):
    for source in ("scheduled", "skill"):
        hub.submit("Urdu mein batao", source)
        assert hub.asked == ""
    hub.submit("Urdu mein batao", "phone")
    assert hub.asked == "ur"


def test_a_new_conversation_forgets_it(hub):
    hub.submit("Urdu mein batao")
    src = Path(hud.__file__).read_text(encoding="utf-8")
    i = src.index('elif self.path == "/api/reset":')
    assert 'HUB.asked = ""' in src[i:i + 500]
    hub._asked_now = False
    hub.set_chat_script("roman")                                              # your choice in Settings counts
    assert hub.asked == ""
    hub.submit("Urdu mein batao")
    hub.set_chat_script("urdu")                                               # (the AI's tool for that very request doesn't undo it)
    assert hub.asked == "ur"


def test_a_failed_rewriting_leaves_the_text(hub, monkeypatch):
    monkeypatch.setattr(urdu, "from_hindi", lambda t: "")
    hub._live_heard("उर्दू में बताओ")
    hub._live_reply("आज मौसम ठीक है", False)
    assert urdu.has_devanagari(last(hub)) is False and "موسم" in last(hub)


def test_which_letters_are_urdu():
    for t in ("میں ٹھیک ہوں", "ہے", "आप कैसे हैं", "ٹھیک"):
        assert urdu.looks_urdu(t), t
    for t in ("كيف حالك", "سلام", "من خوبم چطوری", "څه حال دی ښه", "hello", "", None, "こんにちは"):
        assert not urdu.looks_urdu(t), t


def test_the_ai_is_told():
    assert "own script" in brain.system_prompt() and "Devanagari" in brain.system_prompt()
    assert "own script" in providers.URDU_NOTE and "own script" in providers.ENGLISH_NOTE and "own script" in languages.reply_note("fr")
    assert "stay in it until" in Path(live.__file__).read_text(encoding="utf-8")
    d = next(x for x in tools.TOOL_DEFINITIONS if x["name"] == "set_chat_script")["description"]
    assert "ALWAYS" in d and "no tool is needed" in d

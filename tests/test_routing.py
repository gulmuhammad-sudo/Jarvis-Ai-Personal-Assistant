"""Which AI gets a message: one that can see for screen/picture questions, local only when offline."""
import pytest

from jarvis import providers, tools


class FakeAI:
    def __init__(self, label, vision=False, fail=False):
        self.label, self.vision, self.fail, self.asked = label, vision, fail, []
        self.models, self.model, self.language = [label], label, "en"

    def ask(self, text):
        self.asked.append(text)
        if self.fail:
            raise providers.ProviderError(f"{self.label} is down")
        return f"{self.label} answered"

    def reset(self):
        pass

    def set_voice_mode(self, on):
        pass


@pytest.fixture
def brain(monkeypatch):
    monkeypatch.setattr(providers, "online", lambda timeout=1.5: True)
    b = providers.MultiBrain(tools.ToolContext(confirm=lambda q, **k: True, notify=lambda *a, **k: None),
                             lambda t: None, lambda n, a: notes.append((n, a)))
    local, gemini, groq = FakeAI("Local AI"), FakeAI("Gemini", vision=True), FakeAI("Groq")
    b.backends = [("Local AI", local), ("Gemini", gemini), ("Groq", groq)]
    b.seen = {"Local AI": 0, "Gemini": 0, "Groq": 0}
    notes.clear()
    return b, local, gemini, groq


notes: list = []


@pytest.mark.parametrize("text", ["What's on my screen?", "is screenshot mein kya hai", "ye tasveer dekho",
                                  "look at this picture", "میری اسکرین پر کیا ہے", "describe the photo on my desktop"])
def test_seeing_questions_go_to_an_ai_that_can_see(brain, text):
    b, local, gemini, groq = brain
    assert b.ask(text) == "Gemini answered" and not local.asked
    assert notes and notes[0][0] == "routing" and notes[0][1]["to"] == "Gemini"


@pytest.mark.parametrize("text", ["what time is it?", "pick a song for me", "mausam kaisa hai", "open chrome"])
def test_other_questions_keep_the_normal_order(brain, text):
    b, local, gemini, groq = brain
    assert b.ask(text) == "Local AI answered" and not notes


def test_offline_uses_only_the_local_ai(brain, monkeypatch):
    b, local, gemini, groq = brain
    monkeypatch.setattr(providers, "online", lambda timeout=1.5: False)
    assert b.ask("what's on my screen?") == "Local AI answered"        # can't reach Gemini anyway
    assert not gemini.asked and not groq.asked
    assert notes[0][1]["why"].startswith("no internet")


def test_offline_without_local_ai_says_so_plainly(brain, monkeypatch):
    b, local, gemini, groq = brain
    b.backends = [("Gemini", gemini), ("Groq", groq)]
    monkeypatch.setattr(providers, "online", lambda timeout=1.5: False)
    out = b.ask("hello")
    assert "no internet" in out.lower() and "Ollama" in out and not gemini.asked


def test_fallback_still_works_inside_the_routed_order(brain):
    b, local, gemini, groq = brain
    gemini.fail = True
    assert b.ask("what's on my screen?") == "Local AI answered"        # Gemini down: the next one answers


def test_online_check_is_remembered(monkeypatch):
    calls = []

    class Sock:
        def close(self):
            pass
    monkeypatch.setattr(providers.socket, "create_connection", lambda *a, **k: calls.append(a) or Sock())
    providers._net.update(at=0.0, up=False)
    assert providers.online() and providers.online() and len(calls) == 1
    providers._net.update(at=0.0, up=True)

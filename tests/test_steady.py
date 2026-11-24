"""What you choose stays chosen: no option may jump back to its old value while older news about it is still on its way."""
import re
import threading
import time

import pytest

from jarvis import hud, local_ai, providers

HTML = hud.HTML_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")


def body_of(start, end="\n}\n"):
    i = HTML.index(start)
    return HTML[i:HTML.index(end, i)]


@pytest.fixture
def known(monkeypatch):
    monkeypatch.setattr(local_ai, "_KNOWN", {"at": 0.0, "installed": None, "running": False, "asking": False})


# ---------------- the status is answered at once ----------------
def test_ollama_is_asked_in_the_background(known, monkeypatch):
    asked, go = [], threading.Event()

    def slow():
        asked.append(1)
        go.wait(10)
        return True
    monkeypatch.setattr(local_ai, "running", slow)
    monkeypatch.setattr(local_ai, "exe", lambda: None)
    t = time.perf_counter()
    for _ in range(50):
        assert local_ai.known() == (False, False)
    assert time.perf_counter() - t < 0.5
    time.sleep(0.1)
    assert asked == [1]                                   # one question, however often the page asks
    go.set()
    for _ in range(100):
        if local_ai.known() == (True, True):
            break
        time.sleep(0.02)
    assert local_ai.known() == (True, True) and asked == [1]          # fresh for ten seconds
    local_ai._KNOWN["at"] = 0
    local_ai.known()
    time.sleep(0.2)
    assert asked == [1, 1]


def test_a_fault_while_asking_is_not_forever(known, monkeypatch):
    monkeypatch.setattr(local_ai, "running", lambda: 1 / 0)
    local_ai._ask()
    assert local_ai._KNOWN["asking"] is False and local_ai.known()[1] is False


def test_provider_status_never_waits_for_ollama(known, monkeypatch):
    monkeypatch.setattr(local_ai, "running", lambda: time.sleep(3) or False)
    t = time.perf_counter()
    rows = providers.provider_status(type("B", (), {"names": []})())
    assert time.perf_counter() - t < 1 and rows[0]["label"] == "Local AI"


class Slow:
    """A microphone Windows needs seconds to tell about."""
    def __init__(self):
        self._chosen, self.asked, self.muted = {"name": "Mic A"}, 0, True

    def is_muted(self, name):
        self.asked += 1
        time.sleep(0.6)
        return self.muted

    def level(self, name):
        return 70


@pytest.fixture
def hub(monkeypatch):
    h = hud.Hub.__new__(hud.Hub)
    h._mic_cache, h._mic_known, h._mic_busy, h._mic_asking = (0.0, {}), {}, False, threading.Lock()
    rec = Slow()
    monkeypatch.setattr(hud, "recorder", rec)
    h.rec = rec
    return h


def wait(f):
    for _ in range(200):
        if f():
            return True
        time.sleep(0.02)
    return False


def test_the_microphones_state_never_holds_the_status_up(hub):
    t = time.perf_counter()
    for _ in range(20):
        assert hub.mic_status()["mic"] == "Mic A"
    assert time.perf_counter() - t < 0.4
    assert wait(lambda: hub.mic_status()["mic_muted"]) and hub.rec.asked == 1
    assert hub.mic_status() == {"mic": "Mic A", "mic_muted": True, "mic_level": 70}


def test_what_was_known_stays_until_the_new_is_there(hub):
    wait(lambda: hub.mic_status()["mic_muted"])
    hub._mic_cache = (0.0, {})                            # "ask again": the Unmute button must not blink meanwhile
    assert hub.mic_status()["mic_muted"] is True
    assert wait(lambda: hub._mic_busy is False)
    hub.rec.muted = False
    hub._mic_cache = (0.0, {})
    assert wait(lambda: hub.mic_status()["mic_muted"] is False)
    hub.rec._chosen = {"name": "Mic B"}                   # another one: nothing known of it yet
    assert hub.mic_status() == {"mic": "Mic B", "mic_muted": False, "mic_level": None}
    assert wait(lambda: hub.mic_status()["mic_level"] == 70)


def test_a_fault_of_the_microphone_is_not_forever(hub):
    hub.rec.level = lambda name: 1 / 0
    hub.mic_status()
    assert wait(lambda: hub._mic_busy is False)
    hub.rec.level = lambda name: 55
    hub._mic_cache = (0.0, {})
    hub.mic_status()
    assert wait(lambda: hub.mic_status()["mic_level"] == 55)


# ---------------- the page ----------------
def test_one_question_at_a_time_and_old_answers_are_dropped():
    poll = body_of("async function poll()")
    assert "if (pollBusy && Date.now() - pollBusy < 4000) { pollMore = true; return; }" in poll and "finally" in poll
    once = body_of("async function pollOnce(no)", "\nconst LLM_ABBR")
    asks, reads, drops, keeps = once.index("seq = chgSeq"), once.index("await r.json()"), once.index("seq !== chgSeq"), once.index("lastStats = s;")
    assert asks < reads < drops < once.index("no < pollSeen") < keeps                   # nothing is painted or kept before the check
    assert "apply" not in once[:drops] and "paint" not in once[:drops] and "AbortSignal.timeout" in once
    assert HTML.count("/api/stats?") == 1                 # no other way in


def test_every_way_to_change_a_setting_counts_as_a_change():
    rx = re.compile(re.search(r"const CHANGES = /(.+?)/;", HTML)[1].replace("\\/", "/"))
    for p in ("/api/settings", "/api/live", "/api/mic", "/api/mic_unmute", "/api/local", "/api/setup", "/api/approvals/reset", "/api/privacy/local_only", "/api/privacy/rule", "/api/privacy/hour",
              "/api/privacy/ask_again", "/api/privacy/kept", "/api/privacy/access"):
        assert rx.match(p), p
    for p in ("/api/send", "/api/media/now", "/api/speaking", "/api/privacy/overview", "/api/settingsx", "/api/tts"):
        assert not rx.match(p), p
    f = body_of("async function post(")
    assert f.index("chgBusy++") < f.index("await fetch") < f.index("chgBusy--") and "finally" in f


def test_an_old_echo_is_not_painted():
    assert "chgSeq++; applySettings(newsOnly(ev))" in HTML


def test_options_show_at_once():
    """Painted before the server has answered, not after."""
    for start in ('document.querySelectorAll("[data-tts]")', 'document.querySelectorAll("[data-stt]")'):
        f = body_of(start, "\n});")
        assert f.index("paint") < f.index("post(")
    f = body_of('$("permList").querySelectorAll("[data-perm]")', "\n  });")
    assert f.index("paintPermissions") < f.index("post(")


def test_the_voice_test_changes_no_setting():
    f = body_of('querySelectorAll("[data-tts-try]")', "\n  });")
    assert "tts_engine" not in f and "&try=" in f


def test_the_local_ai_card_reads_the_answer():
    assert 'localInfo = action ? await (await post("/api/local", action)).json()' in HTML


def test_only_a_voice_on_this_pc_can_be_tried(monkeypatch):
    got = []
    h = hud.Handler.__new__(hud.Handler)
    h._json = lambda d, status=200: got.append((status, d))
    h._send_local_voice = lambda text, v: got.append((text, v))
    monkeypatch.setattr(hud.local_tts, "installed", lambda: ["amy"])
    h._tts_stream("text=hello&try=amy")
    h._tts_stream("text=hello&try=../x")
    assert got[0] == ("hello", "amy") and got[1][0] == 404

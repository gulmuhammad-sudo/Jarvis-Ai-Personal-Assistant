"""Saved permissions (Settings > Privacy): ask / allow / never per kind of action, kept across restarts."""
from pathlib import Path

import pytest

from jarvis import audit, hud, schedule, tools


@pytest.fixture
def hub(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    schedule.set_setting("permissions", {})
    h = hud.Hub()
    h.CONFIRM_TIMEOUT = 0.3                      # a question nobody answers ends quickly in tests
    h.voice_mode, h.last_source = False, "typed"  # asked on screen only: tests never open the microphone
    yield h
    schedule.set_setting("permissions", {})


def test_default_is_ask(hub):
    assert set(hub.permissions().values()) == {"ask"}
    assert hub.confirm("Run Get-Date?", kind="powershell") is False          # asked, nobody answered
    assert not hub.pending


def test_never_refuses_without_asking(hub):
    hub.set_permissions({"powershell": "never"})
    asked = []
    hub.emit = lambda t, keep=False, **d: asked.append(t)
    assert hub.confirm("Run Get-Date?", kind="powershell") is False
    assert "confirm" not in asked and "tool" in asked                        # no question, a note in Activity


def test_allow_only_for_the_safer_kinds(hub):
    hub.set_permissions({"lock": "allow", "power": "allow", "clean": "allow"})
    rules = hub.permissions()
    assert rules["lock"] == "allow" and rules["power"] == "ask" and rules["clean"] == "ask"
    assert hub.confirm("Lock the PC?", kind="lock") is True
    schedule.set_setting("permissions", {"power": "allow"})                   # even if written by hand
    assert hub.permission("power") == "ask"


def test_rules_survive_a_restart(hub):
    hub.set_permissions({"wifi_off": "never"})
    assert hud.Hub().permission("wifi_off") == "never"


def test_setting_ask_or_never_ends_an_earlier_yes(hub):
    hub.trusted.add("powershell")                                             # "yes, don't ask again" this session
    hub.set_permissions({"powershell": "never"})
    assert "powershell" not in hub.trusted and hub.confirm("x", kind="powershell") is False


def test_unknown_kinds_and_rules_are_ignored(hub):
    hub.set_permissions({"format_disk": "allow", "lock": "sometimes"})
    assert "format_disk" not in schedule.get_setting("permissions") and hub.permission("lock") == "ask"


def test_tools_respect_never_and_it_is_audited(hub, tmp_path):
    hub.set_permissions({"powershell": "never"})
    out, err = tools.execute("run_powershell", {"command": "Get-Date"}, hub.ctx)
    assert "declined" in out
    events = audit.recent(10)
    assert any(e["event"] == "approval" and e["granted"] is False for e in events)
    assert any(e["event"] == "permission_changed" and e["rule"] == "never" for e in events)


# ---------------- spoken replies are remembered ----------------
@pytest.fixture
def speak_setting(monkeypatch):
    monkeypatch.delenv("JARVIS_NO_SPEAK", raising=False)
    before = schedule.get_setting("speak", None)
    schedule.set_setting("speak", None)
    yield
    schedule.set_setting("speak", before)


def test_spoken_replies_stay_as_you_left_them(hub, speak_setting):
    assert hud.Hub().speak is True                    # never chosen: on
    hub.set_speak(False)
    assert hub.speak is False and hud.Hub().speak is False          # a new start
    hub.set_speak(True)
    assert hud.Hub().speak is True


def test_hands_free_off_leaves_it_and_on_turns_it_on(hub, speak_setting, monkeypatch):
    monkeypatch.setattr(hub, "standby_wanted", lambda: False)
    hub.set_speak(False)
    hub.toggle_voice_mode(False)
    assert hub.speak is False and hud.Hub().speak is False
    hub.toggle_voice_mode(True)
    assert hub.speak is True and hud.Hub().speak is True            # what you see is what is remembered
    hub.toggle_voice_mode(False)


def test_demo_copies_stay_quiet(hub, speak_setting, monkeypatch):
    monkeypatch.setenv("JARVIS_NO_SPEAK", "1")
    assert hud.Hub().speak is False
    hub.set_speak(True)
    assert hub.speak is False


def test_the_page_knows_the_setting_before_it_greets():
    """It used to greet out loud first and read the setting afterwards."""
    html = (Path(hud.__file__).parent / "hud.html").read_text(encoding="utf-8")
    block = html[html.index('case "replay":'):]
    block = block[:block.index("break;")]
    assert block.index("applySettings(ev)") < block.index("speak(last.text)")

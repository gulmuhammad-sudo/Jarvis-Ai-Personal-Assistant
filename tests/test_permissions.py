"""Saved permissions (Settings > Privacy): ask / allow / never per kind of action, kept across restarts."""
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

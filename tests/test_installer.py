"""Installer and uninstaller logic, run against temporary folders (no real shortcuts, registry entry or data)."""
import json
import os
import shutil
import time
import winreg
from pathlib import Path

import pytest

os.environ["PA_SETUP_TEST"] = "1"
import setup_app  # noqa: E402  (packaging/setup_app.py)
from jarvis import install, keystore  # noqa: E402


@pytest.fixture
def old_copy(tmp_path):
    """A fake older run.py copy with settings, a memory and plain-text keys."""
    old = tmp_path / "old"
    (old / "jarvis").mkdir(parents=True)
    (old / "data").mkdir()
    (old / "data" / "settings.json").write_text(json.dumps({"assistant_name": "Maya", "language": "ur"}), encoding="utf-8")
    (old / "data" / "memory.json").write_text(json.dumps([{"id": 1, "fact": "likes tea"}]), encoding="utf-8")
    (old / ".env").write_text("GEMINI_API_KEY=AIzaFAKEFAKEFAKEFAKE1234\nJARVIS_NEWS_REGION=PK\n", encoding="utf-8")
    return old


def test_prefill_migrate_and_apply(old_copy):
    api = setup_app.Api()
    api._old = old_copy
    for f in ("settings.json", "memory.json", "profile.json", ".env", "keys.dat"):
        (setup_app.DATA / f).unlink(missing_ok=True)
    info = api.info()
    assert info["s"]["name"] == "Maya" and info["keys"]["gemini"]
    assert "AIza" not in json.dumps(info)                     # never sends a key to the page
    api._migrate(old_copy)
    api._apply({"name": "Nova", "call": "Boss", "language": "en", "theme": "light", "face": "rings",
                "keys": {"groq": "gsk_FAKEFAKEFAKEFAKEFAKE"}, "start_with_windows": False})
    settings = json.loads((setup_app.DATA / "settings.json").read_text(encoding="utf-8"))
    assert settings["assistant_name"] == "Nova" and settings["setup_done"] and settings["start_with_windows"] is False
    assert "likes tea" in (setup_app.DATA / "memory.json").read_text(encoding="utf-8")
    if keystore.available():
        keys = keystore.load(setup_app.DATA / "keys.dat")
        assert set(keys) == {"GEMINI_API_KEY", "GROQ_API_KEY"}    # old key brought over, new one added, encrypted
        env = (setup_app.DATA / ".env").read_text(encoding="utf-8") if (setup_app.DATA / ".env").exists() else ""
        assert "AIza" not in env and "gsk_" not in env and "JARVIS_NEWS_REGION=PK" in env


def test_bad_assistant_name_is_refused():
    assert setup_app.Api().check_name("!!") and not setup_app.Api().check_name("Maya")


def test_launch_points_at_the_installed_exe(tmp_path):
    target, args, workdir = install.launch(tmp_path, tray=True)
    assert target == tmp_path / "Personal Assistant.exe" and args == "--tray" and workdir == tmp_path


def test_uninstall_removes_everything_it_made(tmp_path, monkeypatch):
    app, data, shortcuts = tmp_path / "app", tmp_path / "data", tmp_path / "links"
    (app / "_internal").mkdir(parents=True)
    (app / install.EXE_NAME).write_bytes(b"x")
    data.mkdir()
    (data / "memory.json").write_text("[]")
    for kind in ("desktop", "programs", "startup"):
        (shortcuts / kind).mkdir(parents=True)
        (shortcuts / kind / "Personal Assistant.lnk").write_text("lnk")
    monkeypatch.setattr(install, "FROZEN", True)
    monkeypatch.setattr(install, "ROOT", app)
    monkeypatch.setattr(install, "DATA_DIR", data)
    monkeypatch.setattr(install, "folder", lambda kind: shortcuts / kind)
    monkeypatch.setattr(install, "UNINSTALL_KEY", r"Software\PersonalAssistantUninstallTest")
    monkeypatch.setattr(install, "_ask", lambda *a, **k: True)
    install.register(app, "9.9.9")
    with pytest.raises(SystemExit):
        install.uninstall()
    for _ in range(40):                                        # the folder is removed a moment after exit
        if not app.exists():
            break
        time.sleep(0.25)
    assert not list(shortcuts.rglob("*.lnk")) and not data.exists() and not app.exists()
    with pytest.raises(OSError):
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, install.UNINSTALL_KEY)
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_uninstall_never_runs_from_source():
    assert install.uninstall() is None                         # not frozen: refuses, deletes nothing


@pytest.mark.parametrize("area,size", [((1536, 816), (900, 640)), ((2560, 1400), (900, 640)), ((1092, 574), (900, 566)),
                                       ((853, 440), (845, 432)), ((300, 200), (480, 380))])
def test_setup_window_is_never_bigger_than_the_screen(area, size):
    assert setup_app.window_size(area=area) == size


def test_setup_pages_scroll_and_keep_their_buttons():
    """1.19.0 and before: the row grew with a long page and pushed Back / Next out of the window (the Look page)."""
    html = (Path(setup_app.__file__).parent / "setup.html").read_text(encoding="utf-8")
    assert "grid-template-rows: minmax(0, 1fr)" in html and "nav { flex: none;" in html
    assert ".page { flex: 1 1 0; min-height: 0;" in html and "Photo face" not in html

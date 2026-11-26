"""Installer and uninstaller logic, run against temporary folders (no real shortcuts, registry entry or data)."""
import hashlib
import json
import os
import re
import shutil
import time
import winreg
import zipfile
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


# ---------------- a new user's PC ----------------
EXE = install.EXE_NAME


@pytest.fixture
def payload(tmp_path, monkeypatch):
    """A small app.zip; make(version) changes what is in it."""
    z = tmp_path / "app.zip"
    monkeypatch.setattr(setup_app, "PAYLOAD", z)

    def make(text="new", exe=True):
        with zipfile.ZipFile(z, "w") as f:
            if exe:
                f.writestr(EXE, text)
            for i in range(60):
                f.writestr(f"_internal/lib{i}.dll", text * 50)
        return z
    make()
    return make


def app(target, text="old"):
    (target / "_internal").mkdir(parents=True)
    (target / EXE).write_text(text)
    (target / "_internal" / "only-old.dll").write_text("x")
    return target


def state(target):
    return (target / EXE).read_text(), (target / "_internal").is_dir(), sorted(p.name for p in target.iterdir())


CLEAN = [EXE, "_internal"]


def test_fresh_and_update(tmp_path, payload):
    t = tmp_path / "fresh"
    seen = []
    setup_app.unpack(t, lambda pct, text: seen.append(pct))
    assert state(t) == ("new", True, CLEAN) and len(seen) > 2 and seen == sorted(seen)
    u = app(tmp_path / "update")
    setup_app.unpack(u)
    assert state(u) == ("new", True, CLEAN) and not (u / "_internal" / "only-old.dll").exists()


def test_a_damaged_setup_leaves_the_old_version(tmp_path, payload):
    u = app(tmp_path / "u")
    z = payload()
    raw = bytearray(z.read_bytes())
    at = raw.find(b"newnew")
    raw[at:at + 6] = b"brokenX"[:6]                                    # the checksum inside no longer fits
    z.write_bytes(raw)
    with pytest.raises(RuntimeError, match="damaged"):
        setup_app.unpack(u)
    assert state(u) == ("old", True, CLEAN) and (u / "_internal" / "only-old.dll").exists()
    z.write_bytes(b"not a zip")
    with pytest.raises(RuntimeError, match="damaged"):
        setup_app.unpack(u)
    payload(exe=False)
    with pytest.raises(RuntimeError, match="damaged"):
        setup_app.unpack(u)
    assert state(u) == ("old", True, CLEAN)


def test_full_drive_while_copying_leaves_the_old_version(tmp_path, payload, monkeypatch):
    u, n = app(tmp_path / "u"), []
    real = zipfile.ZipFile.extract

    def extract(self, *a, **k):
        n.append(1)
        if len(n) > 20:
            raise OSError(28, "No space left on device", None, 112)
        return real(self, *a, **k)
    monkeypatch.setattr(zipfile.ZipFile, "extract", extract)
    api = setup_app.Api()
    with pytest.raises(RuntimeError, match="drive is full"):
        api._install({"dir": str(u), "keep_settings": True})
    assert state(u) == ("old", True, CLEAN) and api.may_close()


@pytest.mark.parametrize("fails_at", [1, 2, 3, 4])
def test_a_swap_that_fails_goes_back(tmp_path, payload, monkeypatch, fails_at):
    u, n = app(tmp_path / "u"), []
    real = os.rename

    def rename(a, b):
        n.append((a, b))
        if len(n) == fails_at:
            raise PermissionError(13, "in use", None, 32)
        return real(a, b)
    monkeypatch.setattr(setup_app.time, "sleep", lambda s: None)
    force = setup_app._force
    monkeypatch.setattr(setup_app, "_force", lambda fn, *a: fn(*a) if fn is rename else force(fn, *a))
    monkeypatch.setattr(setup_app.os, "rename", rename)
    with pytest.raises(PermissionError):
        setup_app.unpack(u)
    assert state(u) == ("old", True, CLEAN) and (u / "_internal" / "only-old.dll").exists()


def test_the_pc_was_switched_off_in_the_middle(tmp_path, payload):
    u = app(tmp_path / "a")                                            # while unpacking
    (u / "_new" / "_internal").mkdir(parents=True)
    setup_app._tidy(u)
    assert state(u) == ("old", True, CLEAN)
    v = app(tmp_path / "b")                                            # while swapping: the old files are aside
    (v / "_old").mkdir()
    os.rename(v / "_internal", v / "_old" / "_internal")
    (v / "_new").mkdir()
    setup_app._tidy(v)
    assert state(v) == ("old", True, CLEAN) and (v / "_internal" / "only-old.dll").exists()
    w = app(tmp_path / "c")                                            # both aside, half of the new one in place
    (w / "_old").mkdir()
    os.rename(w / "_internal", w / "_old" / "_internal")
    os.rename(w / EXE, w / "_old" / EXE)
    (w / EXE).write_text("half new")
    setup_app._tidy(w)
    assert state(w) == ("old", True, CLEAN)
    x = app(tmp_path / "d", "new")                                     # swapped, only the tidying was missing
    app(x / "_old")
    setup_app.unpack(x)
    assert state(x) == ("new", True, CLEAN)


def test_a_file_held_for_a_moment(monkeypatch):
    n = []
    monkeypatch.setattr(setup_app.time, "sleep", lambda s: n.append(s))

    def busy():
        if len(n) < 3:
            raise PermissionError
        return "done"
    assert setup_app._force(busy) == "done" and len(n) == 3
    n.clear()
    with pytest.raises(PermissionError):
        setup_app._force(lambda: (_ for _ in ()).throw(PermissionError()))


def test_which_folders_are_allowed(tmp_path):
    api = setup_app.Api()
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "thesis.docx").write_text("x")
    (tmp_path / "file").write_text("x")
    (tmp_path / "half").mkdir()
    (tmp_path / "half" / "_new").mkdir()
    for good in (tmp_path / "does not exist yet" / "x", app(tmp_path / "app"), tmp_path / "half", setup_app.DEFAULT_DIR):
        assert api.check_dir(str(good)) == "", good
    for bad in (tmp_path / "mine", tmp_path / "file", "C:\\", "relative\\folder", "", "Q:\\nowhere\\x", "C:\\a<b>|"):
        assert api.check_dir(str(bad)) != "", bad
    assert (tmp_path / "mine" / "thesis.docx").exists()


def test_what_a_pc_can_lack(tmp_path, monkeypatch):
    assert setup_app.problems(tmp_path / "x" / "y") == []
    monkeypatch.setattr(setup_app.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 9, 100_000_000))
    assert "0.1 GB free" in setup_app.problems(tmp_path)[0]
    with pytest.raises(RuntimeError, match="free space"):
        setup_app.check_target(tmp_path / "new")
    monkeypatch.undo()
    monkeypatch.setattr(setup_app.sys, "getwindowsversion", lambda: type("V", (), {"build": 10240})())
    assert "Windows 10 (version 1809)" in setup_app.problems(tmp_path)[0]


def test_webview2_missing_is_said(monkeypatch):
    asked, opened = [], []
    monkeypatch.setattr(install, "message", lambda text, title="", yes_no=False: asked.append(text) or True)
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    monkeypatch.setattr(install, "webview2", lambda: "")
    assert install.need_webview2() is False and "WebView2" in asked[0] and opened == [install.WEBVIEW2_PAGE]
    monkeypatch.setattr(install, "webview2", lambda: "157.0")
    assert install.need_webview2() is True and len(asked) == 1


def test_older_setup_over_a_newer_version():
    assert setup_app._newer("1.27.1", "1.9.2") and not setup_app._newer("1.9.2", "1.27.1") and not setup_app._newer("1.27.1", "1.27.1")
    assert {"problems", "older"} <= set(setup_app.Api().info())


def test_silent_keeps_settings(tmp_path, payload):
    (setup_app.DATA / "settings.json").write_text('{"assistant_name": "Nova"}', encoding="utf-8")
    assert setup_app.silent(tmp_path / "s") == 0 and state(tmp_path / "s")[0] == "new"
    assert json.loads((setup_app.DATA / "settings.json").read_text(encoding="utf-8")) == {"assistant_name": "Nova"}
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "x.txt").write_text("x")
    assert setup_app.silent(tmp_path / "mine") == 1


def test_the_check_before_a_release(tmp_path, payload):
    setup_app.selfcheck(tmp_path / "r.json")
    r = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert r["damaged"] is None and r["exe"] and r["files"] == 61 and r["version"] == setup_app.__version__


def test_only_our_old_leftovers_are_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path))

    def mei(name, ours=True, old=True):
        d = tmp_path / name
        (d / "payload").mkdir(parents=True)
        if ours:
            (d / "setup.html").write_text("x")
            (d / "payload" / "app.zip").write_text("x")
        if old:
            os.utime(d, (time.time() - 2 * 86400,) * 2)
        return d
    a, b, c, d = mei("_MEI1"), mei("_MEI2", ours=False), mei("_MEI3", old=False), mei("_MEI4")
    assert setup_app.clean_leftovers(keep=d) == 1 and not a.exists() and b.exists() and c.exists() and d.exists()


def test_uninstall_also_offers_the_offline_models(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert install.models_dir() == tmp_path / "Personal Assistant" / "models"


def test_what_a_new_user_downloads(tmp_path, monkeypatch):
    import build
    monkeypatch.setattr(build, "RELEASE", tmp_path / "release")
    made = tmp_path / "Personal Assistant Setup.exe"
    made.write_bytes(b"MZ setup")
    build.release_files(made)
    names = sorted(p.name for p in build.RELEASE.iterdir())
    assert names == sorted(["Personal-Assistant-Setup.exe", f"Personal-Assistant-{build.VERSION}.zip", "SHA256.txt"])
    with zipfile.ZipFile(build.RELEASE / f"Personal-Assistant-{build.VERSION}.zip") as z:
        assert z.namelist() == ["Personal Assistant/Personal Assistant Setup.exe", "Personal Assistant/READ ME FIRST.txt"] and z.read(z.namelist()[0]) == b"MZ setup"
        assert b"Run anyway" in z.read(z.namelist()[1])
    assert hashlib.sha256(b"MZ setup").hexdigest() in (build.RELEASE / "SHA256.txt").read_text(encoding="utf-8")


def test_the_instructions_point_at_what_exists():
    import build
    readme, notes, help_ = ((build.ROOT / n).read_text(encoding="utf-8") for n in ("README.md", "docs/RELEASE_NOTES.md", "docs/INSTALL.md"))
    assert "releases/latest/download/Personal-Assistant-Setup.exe" in readme and "releases/latest/download/Personal-Assistant-Setup.exe" in help_
    assert all("Source code" in t or "source code" in t for t in (readme, notes, help_, build.README.read_text(encoding="utf-8")))
    assert re.search(r"^# Personal Assistant \d", notes) and "dist" not in readme


def test_hiding_folders_never_deletes(tmp_path, monkeypatch):
    import build
    monkeypatch.setattr(build, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x").write_text("x")
    (tmp_path / "jarvis").mkdir()
    build.tidy()
    assert (tmp_path / "data" / "x").read_text() == "x" and os.stat(tmp_path / "data").st_file_attributes & 2 and not os.stat(tmp_path / "jarvis").st_file_attributes & 2
    assert not {"jarvis", "docs", "tests", "packaging", "assets", ".env"} & set(build.HIDE)


def test_the_build_takes_every_python_library_along(tmp_path):
    """The vault couldn't be made in the exe: python3t.dll wasn't in it, and nothing said so until it was used."""
    import build
    src = open(build.__file__, encoding="utf-8").read()
    assert "--add-binary={f}{SEP}." in src and "missing_python_dlls(app_dir)" in src
    assert build.missing_python_dlls(tmp_path) == []


def test_a_note_waits_for_antivirus(tmp_path, monkeypatch):
    from pathlib import Path

    from jarvis import notes
    monkeypatch.setattr(notes, "path_of", lambda name: tmp_path / f"{name}.md")
    real, n = Path.replace, []

    def busy(self, to):
        n.append(1)
        if len(n) < 3:
            raise PermissionError(13, "in use")
        return real(self, to)
    monkeypatch.setattr(Path, "replace", busy)
    notes.save("x", "hello", new=True)
    assert (tmp_path / "x.md").read_text() == "hello" and len(n) == 3


def test_setup_wears_the_theme_you_choose():
    html = (Path(setup_app.__file__).parent / "setup.html").read_text(encoding="utf-8")
    assert 'pick("theme", S.theme); wear(S.theme, true);' in html and ':root[data-look="light"]' in html and "prefers-color-scheme: light" in html
    # the cards have data-theme, and pick() and the clicks go by it: the page itself must never have it
    assert "documentElement.dataset.theme" not in html and not re.search(r"<(html|body)[^>]*data-theme", html)
    assert html.index("wear(lookNow, false);") < html.index("<body>")                  # no dark flash before it is light
    assert html.count('<html lang="en">') == 1                                         # (setup_app puts the saved theme there)
    light = html[html.index(':root[data-look="light"] { color-scheme'):html.index("::view-transition-old")]
    for part in ("--bg", "--text", "--dim", "--card", "--line", "aside", ".check", "input[type=text]", "button.b.main", ".note.warn", ".steps li.on", "[data-face] svg"):
        assert part in light, part


@pytest.mark.parametrize("text,want", [('{"theme": "light"}', "light"), ('{"theme": "system"}', "system"), ('{"theme": "dark"}', "dark"), ('{"theme": "\\"><script>"}', "dark"), ('{"theme": 5}', "dark"), ("[]", "dark"), ("{half", "dark"), (None, "dark")])
def test_setup_opens_in_the_theme_chosen_before(tmp_path, monkeypatch, text, want):
    import setup_app
    monkeypatch.setattr(setup_app, "DATA", tmp_path)
    if text is not None:
        (tmp_path / "settings.json").write_text(text, encoding="utf-8")
    assert setup_app.saved_theme() == want and setup_app.windows_light() in (True, False)

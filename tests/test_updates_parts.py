"""Phase 10, part 1: new versions with your consent, going back, parts on and off. GitHub is pretended (nothing goes out)."""
import hashlib
import json
import os
import re
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jarvis import __version__, agents, audit, automations, backup, brain, config, devapi, doctor, hud, live, parts, providers, remote, schedule, storage, timeline, tools, updates

REAL_GET = updates._get
HTML = hud.HTML_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
SETUP = b"MZ" + b"setup bytes " * 5000
SETUP_OLD = b"MZ" + b"older setup " * 4000


def nxt(v, d=1):
    a, b, c = map(int, v.split("."))
    return f"{a}.{b}.{c + d}"


NEW, OLD = nxt(__version__), "1.31.6"


def rel(v, body=SETUP, **k):
    sha = hashlib.sha256(body).hexdigest()
    return {"tag_name": f"v{v}", "draft": False, "prerelease": False, "body": f"## {v}\n- better", "published_at": "2026-11-26T10:00:00Z",
            "assets": [{"name": "Personal-Assistant-Setup.exe", "size": len(body), "digest": f"sha256:{sha}"}, {"name": "SHA256.txt", "size": 200, "digest": "sha256:" + "0" * 64}], **k}


class GitHub:
    def __init__(self):
        self.list = [rel(NEW), rel(__version__), rel(OLD, SETUP_OLD), rel("1.31.3"), rel("9.9.9", draft=True), rel("8.8.8", prerelease=True), {"tag_name": "nonsense"}, rel("1.0.1", assets=[])]
        self.files = {NEW: SETUP, OLD: SETUP_OLD}
        self.asked = []
        self.version = None

    def get(self, url, most, accept="", hops=4, sink=None):
        self.asked.append(url)
        if url.endswith("/releases?per_page=30"):
            return json.dumps(self.list).encode()
        m = re.search(r"/download/v([\d.]+)/(.+)$", url)
        body = self.files[m[1]]
        if m[2] == "SHA256.txt":
            return f"{hashlib.sha256(body).hexdigest()}  Personal-Assistant-Setup.exe\n0000  Personal-Assistant-{m[1]}.zip\n".encode()
        sink(body, len(body), len(body))
        return b""


@pytest.fixture
def gh(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(updates, "folder", lambda: tmp_path / "updates")
    monkeypatch.setattr(backup, "N", 2 ** 10)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    g = GitHub()
    monkeypatch.setattr(updates, "_get", g.get)
    monkeypatch.setattr(updates, "_file_version", lambda p: g.version or next((v for v, b in g.files.items() if Path(p).read_bytes() == b), ""))
    updates._STATE.update(busy="", done=0.0, error="")
    updates._NEXT["at"] = 0.0
    yield g
    storage.close()


def test_versions_are_compared_as_numbers():
    assert updates.num("v1.31.10") > updates.num("1.31.9") > updates.num("1.4.99")
    for bad in ("1.31", "x", "", None, "1.31.9-beta", "1.31.9.1"):
        with pytest.raises(updates.UpdateError):
            updates.num(bad)


def test_looking(gh):
    s = updates.check()
    assert s["latest"]["version"] == NEW and s["latest"]["notes"].startswith(f"## {NEW}") and s["ready"] == []
    assert [b["version"] for b in s["back"]] == [OLD]                                           # not before 1.31.5, no drafts, no pre-releases, none without files
    assert "updates_checked" in [e["event"] for e in audit.recent(3)]
    gh.list = [rel(__version__)]
    assert updates.check()["latest"] is None


def test_nothing_about_you_goes_out(gh, monkeypatch):
    sent = []

    class C:
        def __init__(self, host, port, timeout, context):
            sent.append((host, port, context.verify_mode))

        def request(self, m, path, headers):
            sent.append((m, path, headers))

        def getresponse(self):
            return types.SimpleNamespace(status=200, getheader=lambda k, d=None: "2", read=lambda n=0: b"[]")

        def close(self):
            pass
    monkeypatch.setattr(updates, "_get", REAL_GET)
    monkeypatch.setattr(updates.http.client, "HTTPSConnection", C)
    updates.releases()
    host, port, verify = sent[0]
    m, path, headers = sent[1]
    assert host == "api.github.com" and port == 443 and verify == 2 and m == "GET" and set(headers) == {"User-Agent", "Accept"} and headers["User-Agent"] == f"PersonalAssistant/{__version__}"


def test_only_github_s_own_addresses(gh):
    for bad in ("http://github.com/x", "https://evil.com/x", "https://github.com.evil.com/x", "https://user@github.com/x", "https://github.com:8443/x", "ftp://github.com/x", "https://raw.githubusercontent.com/x"):
        with pytest.raises(updates.UpdateError, match="GitHub's addresses"):
            REAL_GET(bad, 10)


def test_download_checked_twice(gh):
    updates.check()
    p = updates.download(NEW)
    assert p.read_bytes() == SETUP and updates.verified(NEW) == p and updates.status()["ready"] == [NEW]
    assert not list(p.parent.glob("*.part")) and "update_downloaded" in [e["event"] for e in audit.recent(3)]


def test_a_changed_file_is_thrown_away(gh):
    updates.check()
    gh.files[NEW] = SETUP + b"x"                                                                  # GitHub's list says one thing, the file is another
    with pytest.raises(updates.UpdateError):
        updates.download(NEW)
    assert not list((updates.folder()).glob("*.exe")) and not list(updates.folder().glob("*.part"))


def test_the_list_of_checksums_must_agree(gh, monkeypatch):
    updates.check()
    real = gh.get

    def other(url, most, accept="", hops=4, sink=None):
        if url.endswith("SHA256.txt"):
            return b"ffff  Personal-Assistant-Setup.exe\n"
        return real(url, most, accept, hops, sink)
    gh.get = other
    monkeypatch.setattr(updates, "_get", other)
    with pytest.raises(updates.UpdateError, match="doesn't name"):
        updates.download(NEW)


def test_the_version_inside_must_agree(gh):
    updates.check()
    gh.version = "1.0.0"
    with pytest.raises(updates.UpdateError, match="isn't the version"):
        updates.download(NEW)
    gh.files[NEW] = b"XX" + SETUP[2:]
    gh.list[0] = rel(NEW, gh.files[NEW])
    gh.version = None
    updates.check()
    with pytest.raises(updates.UpdateError, match="isn't the version"):
        updates.download(NEW)


def test_odd_sizes_and_unknown_versions(gh):
    with pytest.raises(updates.UpdateError, match="Look for versions first"):
        updates.download(NEW)
    updates.check()
    for bad in ("9.9.9", "x", None):
        with pytest.raises(updates.UpdateError):
            updates.download(bad)
    s = updates._settings()
    s["latest"]["size"] = 10 ** 10
    schedule.set_setting("updates", s)
    with pytest.raises(updates.UpdateError, match="odd size"):
        updates.download(NEW)


def test_a_file_changed_after_the_download_isn_t_used(gh, monkeypatch):
    updates.check()
    p = updates.download(NEW)
    p.write_bytes(SETUP + b"!")
    assert updates.verified(NEW) is None
    monkeypatch.setattr(config, "FROZEN", True)
    with pytest.raises(updates.UpdateError, match="Download it first"):
        updates.install(NEW, run=lambda p: pytest.fail("ran"))


def test_installing(gh, monkeypatch):
    updates.check()
    updates.download(NEW)
    with pytest.raises(updates.UpdateError, match="source code"):
        updates.install(NEW, run=lambda p: pytest.fail("ran"))
    monkeypatch.setattr(config, "FROZEN", True)
    storage.add_event({"type": "user", "text": "x"})
    ran = []
    said = updates.install(NEW, run=ran.append)
    assert ran == [updates._file(NEW)] and "opening" in said
    assert any(b["why"] == f"before installing {NEW}" for b in backup.listing() if b["point"])
    assert "update_started" in [e["event"] for e in audit.recent(3)]


def test_no_restore_point_no_setup(gh, monkeypatch):
    updates.check()
    updates.download(NEW)
    monkeypatch.setattr(config, "FROZEN", True)
    monkeypatch.setattr(backup, "make", lambda **k: (_ for _ in ()).throw(backup.BackupError("There isn't enough room in X.")))
    with pytest.raises(updates.UpdateError, match="nothing was started"):
        updates.install(NEW, run=lambda p: pytest.fail("ran"))


def test_going_back_with_the_data_of_then(gh, monkeypatch):
    storage.add_event({"type": "user", "text": "in 1.31.6"})
    schedule.set_setting("app_version", OLD)
    backup.before_update()                                                                        # the point made when 1.31.6 was left
    storage.add_event({"type": "user", "text": "later"})
    updates.check()
    s = updates.status()
    assert s["back"][0]["data"] is True
    updates.download(OLD)
    monkeypatch.setattr(config, "FROZEN", True)
    ran = []
    said = updates.install(OLD, run=ran.append)
    assert ran and "comes back" in said and backup.settings()["pending"]
    storage.close()
    backup.apply_pending()                                                                        # what 1.31.6 does at its start
    assert [e["text"] for e in storage.recent_events()] == ["in 1.31.6"]


def test_by_itself_only_when_turned_on(gh):
    now = datetime.now()
    assert updates.tick(now, lambda *a: None) == 0 and gh.asked == []
    updates.set_auto(True)
    told = []
    assert updates.tick(now, lambda m, k: told.append(m)) == 1
    import threading
    for t in [t for t in threading.enumerate() if t.name == "updates"]:
        t.join(5)
    assert told == [f"Version {NEW} is ready: Settings › Updates."]
    updates._NEXT["at"] = 0.0
    assert updates.tick(now, lambda m, k: told.append(m)) == 0                                    # once a day
    updates._NEXT["at"] = 0.0
    updates.tick(now + timedelta(days=1), lambda m, k: told.append(m))
    for t in [t for t in threading.enumerate() if t.name == "updates"]:
        t.join(5)
    assert len(told) == 1                                                                          # told once per version


def test_local_only_holds_it(gh, monkeypatch):
    from jarvis import netlog
    updates.set_auto(True)
    monkeypatch.setattr(netlog, "_ON", True)
    monkeypatch.setattr(netlog, "_LOCAL", True)
    assert updates.tick(datetime.now(), lambda *a: None) == 0


def test_the_page_s_requests(gh, monkeypatch):
    h = types.SimpleNamespace(live=None, meeting_on=lambda: False, screen=types.SimpleNamespace(state=lambda: None), recording=None)
    monkeypatch.setattr(hud, "HUB", h)

    def call(page, action, data=None):
        x = hud.Handler.__new__(hud.Handler)
        out = {}
        x._json = lambda d, code=200: out.update(body=d, code=code)
        x._daily_api(page, action, data or {})
        return out["code"], out["body"]
    assert call("updates", "load")[1]["auto"] is False
    assert call("updates", "check")[1]["latest"]["version"] == NEW
    assert call("updates", "auto", {"on": True})[1]["auto"] is True
    assert call("updates", "install", {"version": NEW})[0] == 400
    assert call("updates", "download", {"version": "x"})[0] == 400 and call("updates", "x")[0] == 404
    assert len(call("parts", "load")[1]["features"]) == len(parts.FEATURES)
    assert call("parts", "set", {"id": "nope", "on": False})[0] == 400


# ---------------- parts ----------------
@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    monkeypatch.setattr(parts, "CHANGED", None)
    return tmp_path


def test_parts_off_take_their_tools_away(home):
    all_ = tools.TOOL_DEFINITIONS + tools.WEB_TOOL_DEFINITIONS
    assert parts.offered(all_) == all_
    parts.set_on("studio", False)
    parts.set_on("daily", False)
    names = {d["name"] for d in parts.offered(all_)}
    assert not names & {"media", "images", "news", "learn", "fitness", "travel", "meetings", "people"} and {"clock", "tasks", "notes"} <= names
    out, err = tools._execute("media", {"action": "now"}, types.SimpleNamespace(allowed_tools=None))
    assert err and "turned the part 'Studio'" in out
    parts.set_on("studio", True)
    assert "media" in {d["name"] for d in parts.offered(all_)} and parts.off() == ["daily"]
    assert [e["event"] for e in audit.recent(3)] == ["part_off", "part_off", "part_on"]


def test_every_tool_named_is_real():
    names = {d["name"] for d in tools.TOOL_DEFINITIONS + tools.WEB_TOOL_DEFINITIONS}
    for _, _, ts in parts.FEATURES.values():
        assert ts <= names, ts - names


def test_every_ai_gets_only_what_is_on(home, monkeypatch):
    parts.set_on("agents", False)
    srcs = {m: Path(m.__file__).read_text(encoding="utf-8") for m in (brain, providers, live)}
    assert "parts.offered(tools.TOOL_DEFINITIONS)" in srcs[brain] and srcs[providers].count("parts.offered(") == 2 and "parts.offered(" in srcs[live]


def test_devices_off_closes_the_door_and_the_api(home, monkeypatch):
    monkeypatch.setenv("JARVIS_REMOTE_BIND", "127.0.0.1")
    monkeypatch.setattr(config, "DATA_DIR", home)
    stopped = []
    monkeypatch.setattr(remote, "stop", lambda: stopped.append(1))
    parts.set_on("devices", False)
    assert stopped and remote.start() is False
    assert devapi.handle(None, 8765, "GET", "/v1/status", {}, b"")[0] == 403


def test_bad_names(home):
    for bad in ("x", None, "", ["studio"]):
        with pytest.raises(parts.PartsError):
            parts.set_on(bad, False)
    schedule.set_setting("parts_off", ["studio", "nonsense", 5])
    assert parts.off() == ["studio"]
    schedule.set_setting("parts_off", "studio")
    assert parts.off() == []


def test_downloaded_parts(home, monkeypatch):
    from jarvis import local_stt, local_tts
    monkeypatch.setattr(local_stt, "models_dir", lambda: home / "models")
    monkeypatch.setattr(updates, "folder", lambda: home / "updates")
    (home / "models").mkdir()
    local_stt.model_file("base-q5_1").write_bytes(b"x" * 1000)
    v = next(iter(local_tts.VOICES))
    local_tts._folder(v).mkdir(parents=True)
    (local_tts._folder(v) / "a.onnx").write_bytes(b"y" * 500)
    (home / "updates").mkdir()
    (home / "updates" / "s.exe").write_bytes(b"z")
    schedule.set_setting("local_stt_model", "base-q5_1")
    d = {x["id"]: x for x in parts.downloaded()}
    assert d["stt:base-q5_1"]["size"] == 1000 and d[f"voice:{v}"]["size"] == 500 and d["updates"]["size"] == 1
    for i in list(d):
        parts.remove(i)
    assert parts.downloaded() == [] and schedule.get_setting("local_stt_model") is None
    for bad in ("stt:../../x", "voice:none", "x", None):
        with pytest.raises(parts.PartsError):
            parts.remove(bad)


def test_versions(home, monkeypatch, tmp_path):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "a.db")
    v = {r["name"]: r for r in parts.versions()}
    assert v["Personal Assistant"]["version"] == __version__ and v["Database"]["ok"] and v["Encryption"]["ok"] and v["Live calls"]["ok"]
    storage.close()


def test_health_and_timeline_know_it(gh):
    assert doctor._updates(None)["state"] == "info"
    updates.check()
    assert doctor._updates(None)["state"] == "warn" and NEW in doctor._updates(None)["detail"]
    src = Path(updates.__file__).read_text(encoding="utf-8") + Path(parts.__file__).read_text(encoding="utf-8")
    for e in re.findall(r'audit\.record\(\s*"([a-z_]+)"', src) + ["part_on", "part_off"]:
        assert e in timeline._WORDS, e


def test_the_ai_may_look_not_install(gh):
    out = tools.self_check_tool({"action": "updates"}, types.SimpleNamespace())
    assert NEW in out and "you can't" in out
    assert "install" not in json.dumps(next(d for d in tools.TOOL_DEFINITIONS if d["name"] == "self_check")["input_schema"])
    assert "update" not in agents.AGENT_TOOLS and "self_check" not in automations.STEP_TOOLS


def test_the_page():
    assert 'data-settab="updates"' in HTML and 'data-setgroup="updates"' in HTML
    made = set(re.findall(r'id="((?:up|pt)[A-Za-z0-9]+)"', HTML))
    for i in re.findall(r'\$\("((?:up|pt)[A-Z][A-Za-z0-9]*)"\)', HTML):
        assert i in made, i
    for p in ("studio", "automations", "agents", "vault", "daily", "email", "devices"):
        assert f'body[data-off~="{p}"]' in HTML, p
    assert 'if ("parts_off" in s) applyParts(s.parts_off);' in HTML

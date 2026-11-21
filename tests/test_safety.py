"""PC-control safety: files only in your folders, approvals respected, system folders refused, server locked down."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from jarvis import tools


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / "Documents").mkdir()
    return tmp_path


def ctx(answer: bool):
    asked = []
    c = tools.ToolContext(confirm=lambda q, **k: asked.append(q) or answer, notify=lambda *a, **k: None)
    return c, asked


def test_write_file_inside_documents(home):
    c, _ = ctx(True)
    out, err = tools.execute("write_file", {"path": "Documents/note.txt", "content": "hi"}, c)
    assert not err and (home / "Documents" / "note.txt").read_text() == "hi"


def test_write_file_outside_user_folders_is_refused(home):
    c, asked = ctx(True)
    out, err = tools.execute("write_file", {"path": r"C:\Windows\evil.txt", "content": "x"}, c)
    assert err and "only create files inside" in out and not asked


def test_overwrite_needs_approval(home):
    f = home / "Documents" / "keep.txt"
    f.write_text("original")
    c, asked = ctx(False)
    tools.execute("write_file", {"path": "Documents/keep.txt", "content": "new"}, c)
    assert asked and f.read_text() == "original"


def test_system_folders_are_never_cleaned():
    assert tools._folder_problem(tools.Path(r"C:\Windows"), "*") is not None
    assert tools._folder_problem(tools.ROOT, "*") is not None
    assert tools._folder_problem(tools.Path(r"C:\Users\x\Downloads"), "../*") is not None


def test_unknown_tool_and_bad_input_are_errors():
    c, _ = ctx(True)
    assert tools.execute("format_disk", {}, c)[1]
    assert tools.execute("write_file", "not a dict", c)[1]


def test_local_server_needs_token_and_local_host():
    from jarvis import hud
    server = hud.QuietServer(("127.0.0.1", 0), hud.Handler)
    port = server.server_address[1]
    old_port, hud.PORT = hud.PORT, port
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def status(req):
        try:
            return urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        assert status(f"{base}/api/stats?token=wrong") == 403
        post = urllib.request.Request(f"{base}/api/send", data=json.dumps({"text": "hi"}).encode(), method="POST",
                                      headers={"Content-Type": "application/json"})
        assert status(post) == 403                                   # no token
        spoofed = urllib.request.Request(f"{base}/api/stats?token={hud.TOKEN}", headers={"Host": "evil.example"})
        assert status(spoofed) == 403                                # DNS-rebinding style Host
    finally:
        server.shutdown()
        hud.PORT = old_port

"""1.31.3: taking things out of the Activity list, panels that open large, pages in the middle, waves, the memory graph."""
import io
import json
import re

import pytest

from jarvis import audit, hud, schedule, storage

HTML = hud.HTML_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.fixture
def hub(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    h = hud.Hub()
    monkeypatch.setattr(hud, "HUB", h)
    yield h
    h.ringer.stop()
    storage.close()


def fill(h):
    h.emit("user", keep=True, text="play music")
    h.on_tool("get_weather", {"city": "Karachi"})
    h._tool_result("get_weather", {}, "Sunny", False)
    h.notify("Reminder: tea", "reminder")
    h.emit("error", keep=True, text="oops")
    h.emit("jarvis", keep=True, text="Done.")


def test_everything_kept_has_its_own_number(hub):
    fill(hub)
    ids = [e.get("id") for e in hub.history if e["type"] != "tool_result"]
    assert all(ids) and len(set(ids)) == len(ids)
    tool = next(e for e in hub.history if e["type"] == "tool")
    assert next(e for e in hub.history if e["type"] == "tool_result")["id"] == tool["id"]          # a result belongs to its action


def test_one_goes_for_good(hub):
    fill(hub)
    tool = next(e for e in hub.history if e["type"] == "tool")
    told = []
    hub.subscribers.append(type("Q", (), {"put": staticmethod(told.append)}))
    assert hub.remove_activity([tool["id"]]) == 2                                                  # the action and its result
    assert [e["type"] for e in hub.history] == ["user", "notify", "error", "jarvis"]
    assert [e["type"] for e in storage.recent_events()] == ["user", "notify", "error", "jarvis"]
    assert told[-1]["type"] == "activity_removed" and told[-1]["ids"] == [tool["id"]]
    assert hub.remove_activity([tool["id"], "nothing", "' OR 1=1 --"]) == 0 and len(hub.history) == 4


def test_all_go_but_the_conversation_stays(hub):
    fill(hub)
    assert hub.remove_activity(None) == 4
    assert [e["type"] for e in hub.history] == ["user", "jarvis"] == [e["type"] for e in storage.recent_events()]
    assert audit.recent(5)[-1]["event"] == "activity_removed"                                      # and the record says so


def test_a_message_can_not_be_taken_out_this_way(hub):
    fill(hub)
    mine = next(e for e in hub.history if e["type"] == "user")
    assert hub.remove_activity([mine["id"]]) == 0 and any(e["type"] == "user" for e in hub.history) and storage.recent_events()[0]["text"] == "play music"


def test_old_things_without_a_number_can_go_too(hub):
    with storage._LOCK, storage.conn() as c:
        c.execute("INSERT INTO events(type, data) VALUES ('notify', ?)", (json.dumps({"type": "notify", "text": "old one"}),))
    old = storage.recent_events()[-1]
    assert re.fullmatch(r"r\d+", old["id"])
    assert storage.remove_activity([old["id"]]) == 1 and storage.recent_events() == []


def post(path, body, token=True):
    got = []
    h = hud.Handler.__new__(hud.Handler)
    h._json = lambda d, status=200: got.append((status, d))
    h._host_ok, h._token_ok = lambda: True, lambda v: token
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    h.headers, h.rfile, h.path = {"X-Jarvis-Token": "t", "Content-Length": str(len(raw))}, io.BytesIO(raw), path
    h.do_POST()
    return got[0]


def test_the_request(hub):
    fill(hub)
    tool = next(e for e in hub.history if e["type"] == "tool")
    assert post("/api/activity/remove", {"ids": [tool["id"]]}, token=False)[0] == 403
    for bad in (b"", b"x", {}, [], {"ids": 5}, {"all": "true"}, {"all": 1}):
        assert post("/api/activity/remove", bad)[0] == 400, bad
    assert len(hub.history) == 6
    assert post("/api/activity/remove", {"ids": [tool["id"]]}) == (200, {"ok": True, "removed": 2})
    assert post("/api/activity/remove", {"all": True})[1]["removed"] == 2 and "/api/activity/remove" not in hud.WHILE_LOCKED


# ---------------- the page ----------------
def test_the_load_line_stays_and_the_rest_has_a_cross():
    f = HTML[HTML.index("function addFeed("):]
    f = f[:f.index("\n}\n")]
    assert 'fid === "load" ? ""' in f and 'class="fx"' in f
    assert 'case "activity_removed": feedGone(ev.ids)' in HTML and "/api/activity/remove" in HTML


def test_every_dashboard_panel_opens_large():
    dash = HTML[HTML.index('<section class="view dash active"'):HTML.index("<!-- Conversations -->") if "<!-- Conversations -->" in HTML else HTML.index('<section class="view" data-view="conv">')]
    assert dash.count("<h3>") == 8 and '.dash .card:not(.hero) > h3' in HTML
    for part in ("async function xpOpen", "async function xpClose", 'id="xpBack"', 'id="xpHost"', "el.animate(", "if (xpEl) xpClose(true);"):
        assert part in HTML, part
    z = {k: int(v) for k, v in re.findall(r"(#xpBack|\.xp) \{[^}]*z-index: (\d+)", HTML)}
    modal = int(re.search(r"\.modal \{[^}]*z-index: (\d+)", HTML)[1])
    assert z["#xpBack"] < z[".xp"] < modal                                        # a question for you is always above


def test_what_the_panels_use_is_there_before_the_page_runs():
    """Used by the timeline while the page is still loading: declared later it would stop the whole page."""
    assert HTML.index("let xpEl = null") < HTML.index("\nrenderTimeline();")


def test_the_waves_have_no_movement_of_their_own():
    assert not re.search(r"\.wv i[^{]*\{[^}]*animation", HTML)
    f = HTML[HTML.index("const wvMine"):HTML.index("setInterval(wvKick")]
    assert 'live.phase === "listening"' in f and "rec.level" in f and "speaking" not in f


def test_the_menu_shares_its_room_and_the_voice_box_has_one_layout():
    assert ".side > nav > .navi { flex: 1 1 31px; min-height: 31px;" in HTML and "@container voice" not in HTML


def test_pages_are_in_the_middle():
    assert ".view:not(.dash) > .page > .body { padding-inline: max(2px, calc((100% - var(--col)) / 2)); }" in HTML
    assert "const P = { tools: {}, models: {}, auto:" in HTML and '.plbar > .seg[role="tablist"]' in HTML


def test_the_graph_can_be_handled():
    for part in ("cv.onpointerdown", 'addEventListener("wheel"', "cv.onkeydown", "function mgFold", "function mgFit", "data-mgc=", 'data-mgf="1"', 'tabindex="0" role="img"', "prefers-reduced-motion"):
        assert part in HTML, part
    assert "memSvg" not in HTML and "mgTip" not in HTML

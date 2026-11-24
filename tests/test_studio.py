"""Phase 8, part 4: media, screen recording, pictures. Temporary database, settings and home folder; nothing is recorded, nothing goes online."""
import io
import json
import os
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

from jarvis import agents, audit, automations, clock, guard, images, mail, media, news, plans, providers, schedule, screenrec, storage, tools


@pytest.fixture
def db(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    monkeypatch.setattr(plans, "_HOLD", "")
    monkeypatch.setattr(plans, "_PLAN", None)
    monkeypatch.setattr(media, "_found", {})
    monkeypatch.setattr(tools, "MEDIA_PLAY", None)
    monkeypatch.setattr(tools, "STUDIO_CHANGED", None)
    home = tmp_path / "home"
    for d in ("Music", "Videos", "Pictures", "Desktop", "Documents", "Downloads", "AppData"):
        (home / d).mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(home / "AppData"))            # (the temporary home itself is in the real one)
    monkeypatch.setenv("APPDATA", str(home / "AppData"))
    mail.clear_seen()
    tools.STOP.clear()
    yield home
    mail.clear_seen()
    storage.close()


def call(tool_, answer=True, asked=None, from_ai=False, **args):
    def confirm(q, **k):
        if asked is not None:
            asked.append(q)
        return answer
    return tools.execute(tool_, args, tools.ToolContext(confirm=confirm, notify=lambda *a, **k: None), from_ai)[0]


# ================ media ================
def tag(key, text, enc=3, ver=3):
    data = bytes([enc]) + (text.encode("utf-8") if enc == 3 else text.encode("utf-16"))
    return key.encode() + len(data).to_bytes(4, "big") + b"\0\0" + data


def mp3(title="", artist="", enc=3):
    body = (tag("TIT2", title, enc) if title else b"") + (tag("TPE1", artist, enc) if artist else b"")
    n = len(body)
    return b"ID3\x03\0\0" + bytes([(n >> 21) & 127, (n >> 14) & 127, (n >> 7) & 127, n & 127]) + body + b"\xff\xfb" + b"\0" * 400


def fill(home):
    m = home / "Music"
    (m / "01 - Some Band - A Song.mp3").write_bytes(b"\xff\xfb" + b"\0" * 100)
    (m / "tagged.mp3").write_bytes(mp3("نعت شریف", "قاری صاحب", 1))
    (m / "sub").mkdir()
    (m / "sub" / "05 Plain_name.flac").write_bytes(b"fLaC")
    (m / "clip.mp4").write_bytes(b"\0" * 5000)
    (m / "notes.txt").write_text("x")
    (m / "bad.exe").write_bytes(b"MZ")
    (m / ".hidden").mkdir()
    (m / ".hidden" / "x.mp3").write_bytes(b"x")
    return m


def test_library(db):
    m = fill(db)
    f = media.add_folder(str(m))
    assert f["files"] == 4
    rows = {r["name"]: r for r in media.files()}
    assert rows["01 - Some Band - A Song.mp3"]["title"] == "A Song" and rows["01 - Some Band - A Song.mp3"]["artist"] == "Some Band" and rows["tagged.mp3"]["title"] == "نعت شریف" and rows["tagged.mp3"]["artist"] == "قاری صاحب"
    assert rows["05 Plain_name.flac"]["title"] == "Plain name" and rows["clip.mp4"]["kind"] == "video" and len(media.files(kind="video")) == 1 and len(media.files("نعت")) == 1 and media.files("100%") == []
    song = rows["tagged.mp3"]["id"]
    (m / "clip.mp4").unlink()
    (m / "new.ogg").write_bytes(b"OggS")
    media.scan()
    assert {r["name"] for r in media.files()} == {"01 - Some Band - A Song.mp3", "tagged.mp3", "05 Plain_name.flac", "new.ogg"} and [r["id"] for r in media.files("نعت")] == [song]
    shutil.move(str(m), str(db / "Away"))                              # the drive isn't plugged in: what is known stays
    media.scan()
    assert len(media.files()) == 4
    assert media.remove_folder(f["id"]) and media.files() == [] and not media.remove_folder(f["id"])


def test_which_folders(db):
    for bad in ("", "nope", str(db / "nope"), "C:\\", os.environ["WINDIR"], r"\\server\share", "Music", str(db / "AppData" / "..")[:0]):
        with pytest.raises(ValueError):
            media.add_folder(bad)
    media.add_folder(str(db / "Videos"))
    with pytest.raises(ValueError):
        media.add_folder(str(db / "Videos").upper())
    assert media.suggestions() == [str((db / "Music").resolve())]


def test_only_library_files_are_served(db, tmp_path):
    m = fill(db)
    f = media.add_folder(str(m))
    i = media.files("A Song")[0]["id"]
    p, kind = media.path_of(i)
    assert p.name.endswith("A Song.mp3") and kind == "audio/mpeg" and media.path_of(9999) is None
    for bad in ("x", "", "1 OR 1", None):
        with pytest.raises((ValueError, TypeError)):
            media.path_of(bad)
    (tmp_path / "secret.mp3").write_bytes(b"secret")                   # a row pointing out of its folder, a kind that isn't media
    c = storage.conn()
    with c:
        c.execute("INSERT INTO media_files (folder, path, kind) VALUES (?, ?, 'audio')", (f["id"], str(m / ".." / ".." / "secret.mp3")))
        c.execute("INSERT INTO media_files (folder, path, kind) VALUES (?, ?, 'audio')", (f["id"], str(m / "notes.txt")))
    assert all(media.path_of(r[0]) is None for r in c.execute("SELECT id FROM media_files WHERE path LIKE '%secret%' OR path LIKE '%notes.txt'").fetchall())


@pytest.mark.parametrize("raw", [b"", b"ID3", b"ID3\x03\0\0\x7f\x7f\x7f\x7f" + b"TIT2\xff\xff\xff\xff\0\0x", b"ID3\x02\0\0\0\0\0\x20TT2\0\0\x05\0Hello", b"ID3\x04\0\0\0\0\x01\0" + b"\0" * 300, b"\xff" * 500])
def test_broken_tags(raw):
    assert isinstance(media._id3(raw), dict)


def test_playlists(db):
    media.add_folder(str(fill(db)))
    ids = [f["id"] for f in media.files(kind="audio")]
    p = media.save_playlist("Morning")
    for i in (ids[0], ids[1], ids[0]):
        media.change_playlist(p, i)
    assert [x["id"] for x in media.playlists()[0]["items"]] == [ids[1], ids[0]] and media.change_playlist(p, ids[1], False) == 1
    for bad in (lambda: media.save_playlist("MORNING"), lambda: media.save_playlist(""), lambda: media.save_playlist("x", 99), lambda: media.change_playlist(99, ids[0]), lambda: media.change_playlist(p, 999)):
        with pytest.raises(ValueError):
            bad()
    assert media.save_playlist("Evening", p) == p and media.delete_playlist(p) and not media.delete_playlist(p)


def stationsjson(*names, **more):
    return [{"stationuuid": f"u{i}", "name": n, "url_resolved": f"https://radio.example.com:8443/{i}", "country": "PK", "tags": "x", "codec": "MP3", **more} for i, n in enumerate(names)]


def test_radio(db, monkeypatch):
    asked = []
    monkeypatch.setattr(schedule, "_get_json", lambda u, **k: asked.append(u) or (stationsjson("Quran <b>Radio</b>", "News") + [{"stationuuid": "bad", "name": "List", "url_resolved": "https://x.example/a.m3u8"}, {"name": "no number", "url": "https://x"},
                                                                                                        {"stationuuid": "f", "name": "File", "url": "file:///C:/x"}, "rubbish"]))
    got = media.radio_search("quran & more")
    assert [s["name"] for s in got] == ["Quran Radio", "News"] and "name=quran+%26+more" in asked[0] and not got[0]["saved"]
    media.station_save("u0")
    media.station_save("u0")
    assert [s["name"] for s in media.stations()] == ["Quran Radio"] and media.radio_search("quran")[0]["saved"]
    monkeypatch.setattr(news, "_public", lambda u, any_port=False: (_ for _ in ()).throw(ValueError("That address is on this PC or your own network, not on the internet.")))
    with pytest.raises(ValueError, match="own network"):
        media.station_play("u0")
    monkeypatch.setattr(news, "_public", lambda u, any_port=False: None)
    assert media.station_play("u0")["url"].endswith(":8443/0")
    media.station_save("u0", False)
    assert media.stations() == []
    for bad in ("", "x", None):
        with pytest.raises(ValueError):
            media.radio_search(bad)
    with pytest.raises(ValueError):
        media.station_save("nope")
    monkeypatch.setattr(schedule, "_get_json", lambda u, **k: (_ for _ in ()).throw(OSError()))
    with pytest.raises(ValueError, match="can't be reached"):
        media.radio_search("quran")


def test_station_addresses():
    for bad in ("http://127.0.0.1:8000/x", "http://192.168.1.1:8000/", "http://localhost:9000/", "file:///x", "https://u:p@example.com/", "https://example.com:22/", "javascript:x", "https://a b/"):
        with pytest.raises((ValueError, ConnectionError)):
            media._station_url(bad)
    with pytest.raises(ValueError):
        news._public("https://example.com:8000/")                          # a news feed still may not


def test_volume_numbers(monkeypatch):
    class Ep:
        v, m = 0.5, 0

        def GetMasterVolumeLevelScalar(self):
            return self.v

        def SetMasterVolumeLevelScalar(self, v, _):
            self.v = v

        def GetMute(self):
            return self.m

        def SetMute(self, m, _):
            self.m = m
    from jarvis import alerts
    e = Ep()
    monkeypatch.setattr(alerts, "_speakers", lambda: e)
    assert media.volume() == {"volume": 50, "muted": False} and media.volume("30%")["volume"] == 30 and media.volume(mute=True)["muted"] and media.volume(40) == {"volume": 40, "muted": False}
    for bad in (-1, 101, "loud", "", [1]):
        with pytest.raises(ValueError):
            media.volume(bad)
    assert e.v == 0.4
    monkeypatch.setattr(alerts, "_speakers", lambda: None)
    with pytest.raises(ValueError):
        media.volume()


def test_now_playing(monkeypatch):
    said = []
    monkeypatch.setattr(media._NOW, "ask", lambda line, wait=6: said.append(line) or {"title": "A\u202eSong\n", "artist": "B", "app": "Spotify.exe", "status": "Playing", "position": 3.2, "length": 100})
    n = media.now("next")
    assert n["title"] == "A Song" and n["app"] == "Spotify" and n["playing"] and said == ["next"]
    for bad in ("format", "; Remove-Item", "get\nplay", ""):
        with pytest.raises(ValueError):
            media.now(bad)
    assert said == ["next"]                                                # nothing else ever reaches the helper
    assert [media.app_name(x) for x in ("Chrome", "MSEdge", "Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "foobar2000.exe")] == ["Chrome", "Edge", "Media Player", "foobar2000"]


def test_the_real_helper_answers_and_ends(monkeypatch):
    n = media.NowPlaying()
    monkeypatch.setattr(media.NowPlaying, "IDLE", 0.5)
    r = n.ask("get", 15)
    assert isinstance(r, dict) and (r.get("none") or "status" in r)
    p = n._p
    for _ in range(200):
        if p.poll() is not None:
            break
        time.sleep(0.1)
    assert p.poll() is not None                                            # nobody asked any more: it ended by itself


def test_media_tool(db, monkeypatch):
    played = []
    monkeypatch.setattr(media, "now", lambda a="get": {"title": "Song", "artist": "X", "album": "", "app": "Spotify", "playing": a != "pause", "position": 0, "length": 0} if a != "stop" else {"none": True})
    assert "Playing in Spotify: Song by X" in call("media", action="now") and "Paused" in call("media", action="control", name="pause") and "Nothing is playing" in call("media", action="control", name="stop")
    assert call("media", action="now").startswith('<untrusted source="media">')
    assert "Nothing found" in call("media", action="search", query="x") and "nothing called" in call("media", action="play", query="x")
    media.add_folder(str(fill(db)))
    assert "player isn't open" in call("media", action="play", query="A Song")
    monkeypatch.setattr(tools, "MEDIA_PLAY", played.append)
    assert call("media", action="play", query="a song") == "Playing: A Song." and played[-1]["what"] == "files"
    p = media.save_playlist("Morning")
    media.change_playlist(p, media.files("نعت")[0]["id"])
    assert "Playing: Morning" in call("media", action="play", query="morning") and played[-1]["what"] == "playlist" and "Playlists: Morning" in call("media", action="search")
    monkeypatch.setattr(media, "volume", lambda v=None, mute=None: {"volume": int(v or 70), "muted": False})
    assert "40%" in call("media", action="volume", value=40) and "70%" in call("media", action="volume") and "Unknown action" in call("media", action="delete")


# ================ screen recording ================
class Rec:
    def __init__(self):
        self.states, self.ends = [], []
        self.r = screenrec.Recording(self.states.append, lambda p, w: self.ends.append((p, w)))

    def start(self, **k):
        return self.r.start(**{"kind": "video/webm;codecs=vp9", "mic": False, "sound": False, "agree": True, **k})


def test_recording_is_one_file_in_order(db):
    x = Rec()
    st = x.start(mic=True)
    assert st["mic"] and not st["sound"] and x.r.state()["bytes"] == 0 and x.states[-1]["id"] == st["id"]
    x.r.piece(st["id"], 0, b"one")
    x.r.piece(st["id"], "1", b"two")
    for bad in ((st["id"], 1, b"again"), (st["id"], 5, b"later"), ("other", 2, b"x"), ("", 2, b"x"), (st["id"], "x", b"x")):
        with pytest.raises(ValueError):
            x.r.piece(*bad)
    with pytest.raises(ValueError, match="already running"):
        x.start()
    x.r.pause(st["id"], True)
    assert x.states[-1]["paused"]
    path = x.r.stop("you stopped it", st["id"])
    assert Path(path).read_bytes() == b"onetwo" and Path(path).parent == db / "Videos" / "Personal Assistant" and x.states[-1] is None and x.ends == [(path, "you stopped it")]
    assert x.r.stop() == "" and len(x.ends) == 1 and not list(Path(path).parent.glob("*.part"))
    assert [r["name"] for r in screenrec.listing()] == [Path(path).name] and screenrec.path_of(Path(path).name)
    with pytest.raises(ValueError):
        x.r.piece(st["id"], 2, b"too late")


@pytest.mark.parametrize("k", [{"agree": False}, {"agree": None}, {"agree": "true"}, {"agree": 1}, {"kind": "text/html"}, {"kind": ""}, {"kind": "video/x-matroska"}])
def test_what_doesnt_start(db, k):
    x = Rec()
    with pytest.raises(ValueError):
        x.start(**k)
    assert x.r.state() is None and not (db / "Videos" / "Personal Assistant").exists() or not list((db / "Videos" / "Personal Assistant").iterdir())


def test_full_drive_and_limits(db, monkeypatch):
    real = shutil.disk_usage
    x = Rec()
    monkeypatch.setattr(screenrec.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 9, 1000))
    with pytest.raises(ValueError, match="free space"):
        x.start()
    monkeypatch.setattr(screenrec.shutil, "disk_usage", real)
    st = x.start()
    monkeypatch.setattr(screenrec.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(10, 9, 1000))
    x.r.piece(st["id"], 0, b"data")
    assert x.ends[-1][1] == "the drive is nearly full" and Path(x.ends[-1][0]).read_bytes() == b"data"
    monkeypatch.setattr(screenrec.shutil, "disk_usage", real)
    monkeypatch.setattr(screenrec, "MAX_BYTES", 5)
    st = x.start()
    x.r.piece(st["id"], 0, b"123456")
    assert x.ends[-1][1] == "it reached 8 GB"
    st = x.start()
    with pytest.raises(ValueError, match="too large"):
        monkeypatch.setattr(screenrec, "MAX_PIECE", 3)
        x.r.piece(st["id"], 0, b"1234")
    assert x.r.stop() == "" and x.ends[-1] == ("", "you stopped it")             # nothing came: no empty file
    assert len(screenrec.listing()) == 2


def test_the_page_went_away(db, monkeypatch):
    monkeypatch.setattr(screenrec, "SILENT_FOR", 0.1)
    x = Rec()
    st = x.start()
    x.r.piece(st["id"], 0, b"data")
    for _ in range(80):
        if x.ends:
            break
        time.sleep(0.1)
    assert x.ends and x.ends[0][1] == "the window was closed" and Path(x.ends[0][0]).read_bytes() == b"data"


def test_cut_short_recordings_are_kept(db):
    d = db / "Videos" / "Personal Assistant"
    d.mkdir()
    (d / "Recording 2026-11-24 10.00.00.webm.part").write_bytes(b"half")
    (d / "Recording 2026-11-24 11.00.00.webm.part").write_bytes(b"")
    (d / "other.part").write_bytes(b"x")
    assert screenrec.recover() == 1 and sorted(p.name for p in d.iterdir()) == ["Recording 2026-11-24 10.00.00 (cut short).webm", "other.part"]
    assert [r["name"] for r in screenrec.listing()] == ["Recording 2026-11-24 10.00.00 (cut short).webm"]


@pytest.mark.parametrize("name", ["", "..\\..\\secret.webm", "Recording ../../x.webm", "C:\\Windows\\win.ini", "Recording 2026.exe", "Recording 2026-11-24 10.00.00.webm.part", None, "Recording x\\y 0000000000.webm"])
def test_only_recordings_are_opened(db, name):
    assert screenrec.path_of(name) is None
    with pytest.raises(ValueError):
        screenrec.recycle(name)


# ================ pictures ================
def png(w=40, h=20, color=(200, 30, 30), mode="RGB", fmt="PNG", **k):
    b = io.BytesIO()
    Image.new(mode, (w, h), color).save(b, fmt, **k)
    return b.getvalue()


def test_keeping_a_picture(db):
    p = images.keep(png(mode="RGBA", color=(1, 2, 3, 0)), "My: picture/1..", "png")
    assert p == db / "Pictures" / "Personal Assistant" / "My picture 1.png" and Image.open(p).mode == "RGBA" and images.keep(png(), "My picture 1", "png").name == "My picture 1 (2).png"
    j = images.keep(png(mode="RGBA", color=(0, 0, 0, 0)), "", "jpeg", 50)
    assert j.name == "Picture.jpg" and Image.open(j).getpixel((1, 1))[0] > 240                # see-through becomes white
    assert images.keep(png(), "con", "webp").name == "Picture.webp"
    assert {x["name"] for x in images.listing()} >= {"Picture.jpg", "Picture.webp"} and images.path_of("Picture.jpg")


def test_what_else_is_in_a_photo_isnt_kept(db):
    ex = Image.Exif()
    ex[0x010F] = "SECRETCAMERA"
    ex[0x0112] = 6
    raw = png(40, 20, fmt="JPEG", exif=ex)
    assert b"SECRETCAMERA" in raw
    p = images.keep(raw, "photo", "jpg")
    assert b"SECRETCAMERA" not in p.read_bytes() and Image.open(p).size == (20, 40)           # turned the right way, then forgotten


@pytest.mark.parametrize("raw", [b"", b"not a picture", b"<svg onload=alert(1)>", b"MZ\x90", b"\x89PNG\r\n\x1a\n" + b"\0" * 50, png()[:40], b"%PDF-1.4", b"GIF89a"])
def test_not_a_picture(db, raw):
    with pytest.raises(ValueError):
        images.keep(raw)
    assert not images.folder().exists()


def test_too_large(db, monkeypatch):
    monkeypatch.setattr(images, "MAX_PIXELS", 500)
    with pytest.raises(ValueError, match="pixels"):
        images.keep(png())
    monkeypatch.setattr(images, "MAX_IN", 10)
    with pytest.raises(ValueError, match="too large"):
        images.keep(png())
    for bad in ("exe", "svg", "gif"):
        with pytest.raises(ValueError):
            images._encode(Image.new("RGB", (2, 2)), bad)


@pytest.mark.parametrize("name", ["", "../x.png", "..\\x.png", "a/b.png", "x.exe", "C:\\x.png", None, "con:.png"])
def test_only_saved_pictures_are_served(db, name):
    images.keep(png(), "x")
    assert images.path_of(name) is None


def test_changing_a_file(db):
    a = db / "Pictures" / "holiday.jpg"
    a.write_bytes(png(400, 200, fmt="JPEG"))
    before = a.read_bytes()
    p = images.convert("holiday.jpg", "png", 100, rotate=90)
    assert p == db / "Pictures" / "holiday edited.png" and Image.open(p).size == (50, 100) and a.read_bytes() == before
    g = images.convert(str(a), grey=True)
    r, gr, b = Image.open(g).getpixel((5, 5))
    assert abs(r - gr) < 3 and abs(gr - b) < 3 and g.suffix == ".jpg" and images.info("Pictures/holiday.jpg")["width"] == 400
    (db / "AppData" / "x.png").write_bytes(png())
    for bad in ("", "nope.png", str(db / "AppData" / "x.png"), os.environ["WINDIR"] + "\\win.ini", r"\\server\x.png"):
        with pytest.raises(ValueError):
            images.convert(bad)
    for k in ({"rotate": 45}, {"max_side": 5}, {"max_side": 99999}, {"fmt": "exe"}, {"max_side": "big"}):
        with pytest.raises(ValueError):
            images.convert(str(a), **k)
    (db / "Desktop" / "notes.txt").write_text("x")
    with pytest.raises(ValueError):
        images.convert("notes.txt")


class Answer:
    def __init__(self, raw):
        self.raw = raw

    def read(self, n):
        return self.raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_making_one(db, monkeypatch):
    asked = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=0: asked.append(r) or Answer(png(64, 64)))
    p = images.make("a red apple / on a table? & more\n#", "wide")
    u = urllib.parse.urlsplit(asked[0].full_url)
    q = urllib.parse.parse_qs(u.query)
    assert u.netloc == "image.pollinations.ai" and u.path == "/prompt/a%20red%20apple%20%2F%20on%20a%20table%3F%20%26%20more%20%23" and q["safe"] == ["true"] and q["private"] == ["true"] and q["width"] == ["1344"]
    assert p.suffix == ".jpg" and Image.open(p).size == (64, 64) and p.name.startswith("a red apple on a table") and len(asked[0].headers) == 1
    for bad in (("", "square"), ("x", "square"), ("y" * 601, "square"), ("an apple", "huge")):
        with pytest.raises(ValueError):
            images.generate(*bad)
    n = len(images.listing())
    for fail, words in ((urllib.error.HTTPError("u", 429, "", {}, None), "busy"), (urllib.error.HTTPError("u", 403, "", {}, None), "refused"), (urllib.error.URLError("x"), "reached"), (TimeoutError(), "reached")):
        monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=0, fail=fail: (_ for _ in ()).throw(fail))
        with pytest.raises(ValueError, match=words):
            images.make("an apple")
    monkeypatch.setattr(urllib.request, "urlopen", lambda r, timeout=0: Answer(b"<html>sorry</html>"))
    with pytest.raises(ValueError):
        images.make("an apple")
    assert len(images.listing()) == n


def test_images_tool(db, monkeypatch):
    sent, told = [], []
    monkeypatch.setattr(images, "make", lambda p, s="square": sent.append((p, s)) or (db / "Pictures" / "apple.jpg"))
    monkeypatch.setattr(tools, "STUDIO_CHANGED", told.append)
    asked = []
    assert "didn't make it" in call("images", False, asked, action="generate", prompt="an apple") and sent == [] and "an apple" in asked[0] and "Pollinations" in asked[0]
    assert "apple.jpg" in call("images", True, asked, action="generate", prompt="an apple", size="tall") and sent == [("an apple", "tall")] and told == ["images"]
    (db / "Pictures" / "a.png").write_bytes(png())
    assert "40 x 20" in call("images", action="info", path="a.png") and "the original stays" in call("images", action="convert", path="a.png", max_side=16)
    assert "There is no picture" in call("images", action="info", path="zz.png") and "Unknown action" in call("images", action="delete", path="a.png") and "Only the user" in call("images", action="record")
    mail.seen_by_ai()
    for t, a in (("images", {"action": "generate", "prompt": "the secret"}), ("media", {"action": "radio", "query": "the secret"})):
        asked.clear()
        assert "didn't allow" in call(t, False, asked, True, **a) and len(asked) == 1
    asked.clear()
    call("images", False, asked, True, action="info", path="a.png")
    call("media", False, asked, True, action="search", query="x")
    assert asked == []


# ================ the app ================
def test_stop_ends_it_and_the_bar_knows(db, monkeypatch):
    from jarvis import hud
    pills = []
    monkeypatch.setattr(hud, "REC_HOOK", pills.append)
    h = hud.Hub()
    try:
        st = h.screen.start("video/webm", False, True, True)
        assert h.stats()["screen"]["sound"] is True
        h.screen.piece(st["id"], 0, b"x")
        h.emergency_stop()
        time.sleep(0.2)
        assert h.stats()["screen"] is None and pills[0] is True and pills[-1] is False and any("Stop was pressed" in str(e.get("text")) for e in h.history)
        assert "screen_recording_ended" in (db.parent / "audit.log").read_text(encoding="utf-8")
    finally:
        clock.stop()
        tools.STOP.clear()


def test_over_http(db, monkeypatch):
    """The real server: files only with the page's token, parts of files, pieces and pictures as bytes."""
    from jarvis import hud
    media.add_folder(str(fill(db)))
    i = media.files("A Song")[0]["id"]
    h = hud.Hub()
    monkeypatch.setattr(hud, "HUB", h)
    server = hud.QuietServer(("127.0.0.1", 0), hud.Handler)
    port = server.server_address[1]
    monkeypatch.setattr(hud, "PORT", port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    B = f"http://127.0.0.1:{port}"

    def get(path, **headers):
        try:
            with urllib.request.urlopen(urllib.request.Request(B + path, headers=headers), timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def post(path, data, token=hud.TOKEN):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(B + path, data=raw, method="POST", headers={"X-Jarvis-Token": token}), timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")
    try:
        T = f"&token={hud.TOKEN}"
        s, body, hd = get(f"/api/media/file?id={i}{T}")
        assert s == 200 and len(body) == 102 and hd["Content-Type"] == "audio/mpeg" and hd["Accept-Ranges"] == "bytes" and hd["X-Content-Type-Options"] == "nosniff"
        s, part, hd = get(f"/api/media/file?id={i}{T}", Range="bytes=2-5")
        assert s == 206 and part == body[2:6] and hd["Content-Range"] == "bytes 2-5/102"
        assert get(f"/api/media/file?id={i}{T}", Range="bytes=-2")[1] == body[-2:] and get(f"/api/media/file?id={i}{T}", Range="bytes=100-")[1] == body[100:]
        assert get(f"/api/media/file?id={i}{T}", Range="bytes=500-600")[0] == 416 and get(f"/api/media/file?id={i}{T}", Range="bytes=9-3")[0] == 416
        assert get(f"/api/media/file?id={i}")[0] == 403 and get(f"/api/media/file?id={i}&token=x")[0] == 403 and get(f"/api/media/file?id=../../x{T}")[0] == 404 and get(f"/api/images/file?name=..%2Fx.png{T}")[0] == 404
        s, j = post("/api/images/keep?name=Test&fmt=png", png())
        assert s == 200 and j["name"] == "Test.png" and get(f"/api/images/file?name=Test.png{T}")[0] == 200
        assert post("/api/images/keep?name=x", b"rubbish")[0] == 400 and post("/api/images/keep?name=x", png(), "wrong")[0] == 403 and post("/api/images/keep?name=x&quality=abc", png())[0] == 400
        s, j = post("/api/rec/start", {"kind": "video/webm", "agree": True})
        rid = j["state"]["id"]
        assert post(f"/api/rec/piece?id={rid}&n=0", b"abc")[0] == 200 and post(f"/api/rec/piece?id={rid}&n=5", b"abc")[0] == 400 and post(f"/api/rec/piece?id={rid}&n=1", b"abc", "wrong")[0] == 403
        assert post("/api/rec/start", {"kind": "video/webm", "agree": True})[0] == 400
        s, j = post("/api/rec/stop", {"id": rid})
        name = j["recordings"][0]["name"]
        assert get(f"/api/rec/file?name={urllib.parse.quote(name)}{T}")[1] == b"abc"
        monkeypatch.setenv("JARVIS_NO_MIC", "1")
        assert post("/api/rec/start", {"kind": "video/webm", "agree": True, "mic": True})[0] == 400
        assert b"__TOKEN__" not in get(f"/recpill?x=1{T}")[1] and get("/recpill")[0] == 403
        assert post("/api/media/nope", {})[0] == 404 and post("/api/media/volume", {"value": "loud"})[0] == 400 and post("/api/rec/open", {"name": "../x"})[0] == 400 and post("/api/media/folder", ["x"])[0] == 400
    finally:
        server.shutdown()
        server.server_close()
        clock.stop()


def test_where_they_may_be_used(db):
    for t in ("media", "images"):
        with pytest.raises(ValueError):
            agents.save("X", "r", [t])
    automations.check_step({"tool": "media", "args": {"action": "volume", "value": 20}})
    for bad in ({"tool": "media", "args": {"action": "radio", "query": "x"}}, {"tool": "images", "args": {"action": "generate", "prompt": "x"}}):
        with pytest.raises(ValueError):
            automations.check_step(bad)
    assert {"media", "images"} <= set(providers.LOCAL_TOOLS) & set(providers.BIG_TOOLS) and plans.LOOKING >= {"media:now", "images:info"} and not {"images:generate", "media:play"} & plans.LOOKING
    assert guard.is_untrusted("media", {"action": "now"})
    from jarvis import hud
    assert "image_online" in hud.Hub.PERMISSION_KINDS
    names = json.dumps([d for d in tools.TOOL_DEFINITIONS])
    assert "screen recording" not in names.lower() and not any(d["name"] in ("screenrec", "record_screen") for d in tools.TOOL_DEFINITIONS)


def test_database_upgrade_keeps_everything(db, tmp_path):
    storage.close()
    c = sqlite3.connect(tmp_path / "old.db")
    for sql in storage.MIGRATIONS[:12]:
        c.executescript(sql)
    c.execute("INSERT INTO people (name, created) VALUES ('keep me', '2026-01-01')")
    c.execute("PRAGMA user_version = 12")
    c.commit()
    assert storage.migrate(c) == len(storage.MIGRATIONS) and c.execute("SELECT name FROM people").fetchone() == ("keep me",)
    c.close()

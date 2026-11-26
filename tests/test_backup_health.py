"""Phase 9, part 3: backup, putting back, health and repair. Made-up data folder; nothing of Windows is opened or changed, the Recycle
Bin, the DNS cache and the real keys are never touched."""
import io
import json
import os
import re
import sqlite3
import struct
import sys
import time
import types
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jarvis import agents, audit, automations, backup, config, doctor, guard, hud, install, keystore, netcheck, plans, privacy, providers, schedule, storage, timeline, tools, vault

PW = "correct horse battery"
HTML = hud.HTML_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.fixture
def home(tmp_path, monkeypatch):
    d = tmp_path / "data"
    for n in ("notes", "screenshots"):
        (d / n).mkdir(parents=True)
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: d / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", d / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: d / "audit.log")
    monkeypatch.setattr(config, "DATA_DIR", d)
    monkeypatch.setattr(config, "NOTES_DIR", d / "notes")
    monkeypatch.setattr(config, "SCREENSHOT_DIR", d / "screenshots")
    monkeypatch.setattr(keystore, "KEYS_FILE", d / "keys.dat", raising=False)
    kept: dict = {}
    monkeypatch.setattr(keystore, "load", lambda path=None: dict(kept))
    monkeypatch.setattr(keystore, "save", lambda new, path=None: (kept.update(new), (d / "keys.dat").write_text("x"))[0])
    monkeypatch.setattr(backup, "N", 2 ** 12)
    monkeypatch.setattr(vault, "N", 2 ** 12)
    monkeypatch.setattr(vault, "_OPEN", None)
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "Zubaida"))
    monkeypatch.setitem(backup._TRIED, "at", 0.0)
    for k in [k for k in os.environ if k.endswith("_API_KEY")]:
        monkeypatch.delenv(k)
    home = types.SimpleNamespace(d=d, kept=kept, tmp=tmp_path)
    yield home
    vault._OPEN = None
    storage.close()


@pytest.fixture
def full(home):
    storage.add_event({"type": "user", "text": "hello zebra"})
    (config.NOTES_DIR / "a.md").write_text("note zebra", encoding="utf-8")
    (config.SCREENSHOT_DIR / "s.png").write_bytes(b"PICTUREzebra" * 50)
    schedule.set_setting("assistant_name", "Zebra")
    home.kept["GROQ_API_KEY"] = "gsk_zebra"
    vault.create(PW, PW)
    vault.lock()
    return home


def texts():
    return [e["text"] for e in storage.recent_events()]


# ---------------- a backup ----------------
def test_the_real_numbers():
    assert "N = 2 ** 16" in open(backup.__file__, encoding="utf-8").read()


def test_one_file_nothing_readable(full):
    r = backup.make(keys=True, shots=True, password="backup pass 9")
    raw = Path(r["path"]).read_bytes()
    assert r["files"] >= 6 and r["password"] and r["path"].startswith(str(full.tmp / "Zubaida" / "Documents"))
    for w in (b"zebra", b"Zebra", b"gsk_", b"assistant.db", b"notes", b"PICTURE", b"backup pass"):
        assert w not in raw, w
    assert not list(full.d.glob("backup.tmp")) and not list(Path(r["path"]).parent.glob("*.part"))


def test_what_is_in_it_and_what_never(full):
    for n in ("lock.dat", "mail.dat", "keys.dat", ".env", "jarvis.log", "running.json"):
        (full.d / n).write_text("secret thing")
    (full.d / "webview").mkdir()
    (full.d / "webview" / "x").write_text("c")
    r = backup.make()
    with open(r["path"], "rb") as f:
        h, start, about = backup._header(f)
        with zipfile.ZipFile(io.BufferedReader(backup._Open(f, start, r["size"], backup._key_of(h), about))) as z:
            names = set(z.namelist())
    assert {"data/assistant.db", "data/settings.json", "notes/a.md", "vault/vault.json", "manifest.json"} <= names
    assert not any(w in n for n in names for w in ("lock.dat", "mail.dat", "keys", ".env", "jarvis.log", "webview", "screenshots", "running"))


def test_back_again(full):
    r = backup.make(keys=True, shots=True)
    storage.clear_events()
    (config.NOTES_DIR / "a.md").unlink()
    (config.NOTES_DIR / "new.md").write_text("later")
    schedule.set_setting("assistant_name", "Other")
    full.kept.clear()
    got = backup.prepare(r["path"], ["app", "settings", "notes", "keys", "vault", "screenshots"])
    assert texts() == [] and Path(got["point"]).is_file()                                            # nothing changed yet
    storage.close()
    said = backup.apply_pending()
    assert "back in place" in said and texts() == ["hello zebra"]
    assert [p.name for p in config.NOTES_DIR.iterdir()] == ["a.md"] and schedule.get_setting("assistant_name") == "Zebra"
    assert full.kept == {"GROQ_API_KEY": "gsk_zebra"} and vault.exists() and vault.unlock(PW)
    assert not backup.pending_dir().exists() and not (full.d / "restore.before").exists() and backup.apply_pending() == ""
    ev = [e["event"] for e in audit.recent(20)]
    assert "restore_prepared" in ev and "restored" in ev


def test_the_restore_point_brings_now_back(full):
    r = backup.make()
    storage.add_event({"type": "user", "text": "later"})
    point = backup.prepare(r["path"], ["app"])["point"]
    storage.close()
    backup.apply_pending()
    assert texts() == ["hello zebra"]
    backup.prepare(point, ["app"])
    storage.close()
    backup.apply_pending()
    assert texts() == ["hello zebra", "later"]


def test_only_what_was_chosen(full):
    r = backup.make(keys=True)
    storage.clear_events()
    schedule.set_setting("assistant_name", "Other")
    full.kept["GROQ_API_KEY"] = "new"
    backup.prepare(r["path"], ["app"])
    storage.close()
    backup.apply_pending()
    assert texts() == ["hello zebra"] and schedule.get_setting("assistant_name") == "Other" and full.kept["GROQ_API_KEY"] == "new"
    for bad in ([], None, "app", ["everything"], [5]):
        with pytest.raises(backup.BackupError):
            backup.prepare(r["path"], bad)


def test_all_or_nothing(full, monkeypatch):
    r = backup.make()
    storage.clear_events()
    schedule.set_setting("assistant_name", "Other")
    backup.prepare(r["path"], ["app", "settings", "notes"])
    storage.close()
    real, n = backup._move, []

    def fails(a, b):
        n.append(1)
        if len(n) == 5:
            raise OSError("no")
        real(a, b)
    monkeypatch.setattr(backup, "_move", fails)
    assert "everything is as it was" in backup.apply_pending()
    assert texts() == [] and schedule.get_setting("assistant_name") == "Other" and (config.NOTES_DIR / "a.md").is_file()
    assert not backup.pending_dir().exists()


def test_changed_by_one_bit_is_refused(full):
    p = Path(backup.make()["path"])
    raw = bytearray(p.read_bytes())
    for at in (len(raw) - 3, len(raw) // 2, 30, 14):
        bad = bytearray(raw)
        bad[at] ^= 1
        p.write_bytes(bad)
        with pytest.raises(backup.BackupError):
            backup.look(str(p))
    p.write_bytes(raw[:-500])
    with pytest.raises(backup.BackupError):
        backup.look(str(p))
    p.write_bytes(b"not one")
    with pytest.raises(backup.BackupError):
        backup.look(str(p))


def test_big_files_in_pieces_and_pieces_not_exchanged(full):
    (config.NOTES_DIR / "big.bin").write_bytes(os.urandom(3 * backup.CHUNK + 17))
    p = Path(backup.make()["path"])
    assert backup.look(str(p))["locked"] is False
    raw = bytearray(p.read_bytes())
    with open(p, "rb") as f:
        start = backup._header(f)[1]
    n = backup.CHUNK + 16
    raw[start:start + n], raw[start + n:start + 2 * n] = raw[start + n:start + 2 * n], raw[start:start + n]
    p.write_bytes(raw)
    with pytest.raises(backup.BackupError):
        backup.look(str(p))


def test_another_pc_needs_the_password(full, monkeypatch):
    r = backup.make(password="backup pass 9")
    plain = backup.make()
    monkeypatch.setattr(backup, "_unprotect", lambda b: None)                                          # (another Windows account)
    monkeypatch.setattr(time, "sleep", lambda s: None)
    assert backup.look(r["path"]) == {"locked": True, "name": Path(r["path"]).name, "made": backup.look(r["path"])["made"], "app": backup.look(r["path"])["app"]}
    with pytest.raises(backup.BackupError, match="isn't the password"):
        backup.look(r["path"], "wrong pass 1")
    assert backup.look(r["path"], "backup pass 9")["locked"] is False
    with pytest.raises(backup.BackupError, match="only with the Windows account"):
        backup.look(plain["path"])
    with pytest.raises(backup.BackupError, match="needs its password"):
        backup.prepare(r["path"], ["app"])
    assert backup.prepare(r["path"], ["app"], "backup pass 9")["parts"] == ["app"]


def test_the_backup_password(full):
    for a, b in (("short", "short"), ("password123", "password123"), ("backup pass 9", "backup pass 8"), ("", "")):
        with pytest.raises(backup.BackupError):
            backup.set_password(a, b)
    backup.set_password("backup pass 9", "backup pass 9")
    assert b"backup pass" not in (full.d / "backup.dat").read_bytes() and backup.settings()["password"]
    r = backup.make()
    assert r["password"] and backup._key_of({**backup._header(open(r["path"], "rb"))[0], "slots": {k: v for k, v in backup._header(open(r["path"], "rb"))[0]["slots"].items() if k == "password"}}, "backup pass 9")
    backup.remove_password()
    assert not backup.make()["password"]


def test_something_that_does_not_belong_is_refused(full):
    for arc in ("../evil.txt", "notes/../../x", "data/keys.dat", "data/lock.dat", "notes/a\\b", "notes/C:x", "vault/evil.exe", "screenshots/..", "x/y", "data/assistant.db/../x", "notes/con. ", "notes//x"):
        assert not backup._safe(arc), arc
    for arc in ("notes/a b/ڈ.md", "data/settings.json", "vault/files/" + "a" * 24 + ".bin", "secret/keys.json"):
        assert backup._safe(arc), arc
    key, bid = b"k" * 32, "ab" * 8
    head = json.dumps({"v": 1, "id": bid, "made": "2026-01-01T00:00:00", "app": "1", "why": "", "db": 1, "slots": {"windows": backup._b(backup._protect(key))}}).encode()
    front = backup.MAGIC + struct.pack(">I", len(head)) + head
    p = full.tmp / "evil.pabackup"
    with open(p, "wb") as f:
        import hashlib
        f.write(front)
        s = backup._Seal(f, key, hashlib.sha256(front).digest())
        with zipfile.ZipFile(s, "w") as z:
            z.writestr("notes/../../../evil.txt", "x")
            z.writestr("manifest.json", json.dumps({"app": "1", "made": "2026-01-01T00:00:00", "db": 1, "files": {"notes/../../../evil.txt": [1, hashlib.sha256(b"x").hexdigest()]}}))
        s.finish()
    with pytest.raises(backup.BackupError, match="doesn't belong"):
        backup.prepare(str(p), ["notes"])
    assert not list(full.tmp.rglob("evil.txt")) and not backup.pending_dir().exists()


def test_a_newer_version_is_refused(full, monkeypatch):
    r = backup.make()
    monkeypatch.setattr(storage, "MIGRATIONS", storage.MIGRATIONS[:-1])
    with pytest.raises(backup.BackupError, match="newer version"):
        backup.look(r["path"])


def test_paths(full):
    for bad in ("", "x.pabackup", "\\\\pc\\share\\a.pabackup", "//pc/a.pabackup", str(full.d / "assistant.db"), str(full.tmp / "none.pabackup"), None, 5):
        with pytest.raises(backup.BackupError):
            backup.look(bad)
    for bad in ("\\\\pc\\x", "relative", str(full.d / "inside"), "Z:\\nowhere\\x"):
        with pytest.raises(backup.BackupError):
            backup.set_settings({"folder": bad})
    backup.set_settings({"folder": str(full.tmp / "other")})
    assert backup.make()["path"].startswith(str(full.tmp / "other"))
    backup.set_settings({"folder": ""})
    assert backup.folder() == backup.default_folder()


def test_settings_are_checked(home):
    for bad in ({"every": "hourly"}, {"keep": 1}, {"keep": True}, {"keep": "7"}, {"every": None}):
        with pytest.raises(backup.BackupError):
            backup.set_settings(bad)
    backup.set_settings({"every": "daily", "keep": 3, "keys": "yes"})
    s = backup.settings()
    assert (s["every"], s["keep"], s["keys"], s["shots"]) == ("daily", 3, False, False)


def test_old_ones_go_only_its_own(full):
    backup.set_settings({"keep": 3})
    f = backup.folder()
    f.mkdir(parents=True)
    (f / "My own.pabackup").write_bytes(b"x")
    (f / "holiday.jpg").write_bytes(b"x")
    for i in range(6):
        (f / f"Personal Assistant 2025-01-0{i + 1} 10.00.00.pabackup").write_bytes(b"old")
    backup.make()
    names = sorted(p.name for p in f.iterdir())
    assert "My own.pabackup" in names and "holiday.jpg" in names and len(names) == 5
    assert sum(n.startswith("Personal Assistant 2025") for n in names) == 2


def test_one_at_a_time_and_no_room(full, monkeypatch):
    with backup._LOCK:
        with pytest.raises(backup.BackupError, match="already"):
            backup.make()
    monkeypatch.setattr(backup, "_free", lambda p: 1000)
    with pytest.raises(backup.BackupError, match="room"):
        backup.make()
    assert not list(backup.folder().glob("*")) and not backup._LOCK.locked()


def test_a_fault_while_writing_leaves_nothing(full, monkeypatch):
    monkeypatch.setattr(backup, "_verify", lambda p, k: (_ for _ in ()).throw(backup.BackupError("That backup was changed or is damaged.")))
    with pytest.raises(backup.BackupError):
        backup.make()
    assert not list(backup.folder().glob("*")) and backup.settings()["last"] == ""


def test_by_itself(full, monkeypatch):
    now = datetime.now()
    assert not backup.due(now) and backup.tick(now, lambda *a: None) == 0
    backup.set_settings({"every": "daily"})
    assert backup.due(now)
    backup.make()
    assert not backup.due(now + timedelta(hours=22)) and backup.due(now + timedelta(hours=24))
    backup.set_settings({"every": "weekly"})
    assert not backup.due(now + timedelta(days=6)) and backup.due(now + timedelta(days=7))
    said = []
    monkeypatch.setattr(backup, "make", lambda **k: (_ for _ in ()).throw(backup.BackupError("There isn't enough room in X.")))
    for _ in range(2):
        backup._TRIED["at"] = 0.0
        assert backup.tick(now + timedelta(days=8), lambda m, k: said.append(m)) == 1
        end = time.time() + 5
        while time.time() < end and any(t.name == "backup" for t in __import__("threading").enumerate()):
            time.sleep(0.02)
    assert len(said) == 1 and "room" in said[0] and "room" in backup.settings()["last_error"]         # told once
    assert backup.tick(now + timedelta(days=8), lambda m, k: None) == 0                                 # not again for an hour


def test_a_restore_point_before_another_version(full):
    assert backup.before_update() and not backup.before_update()
    schedule.set_setting("app_version", "1.0.0")
    assert backup.before_update()
    b = [x for x in backup.listing() if x["point"]]
    assert len(b) == 2 and any("from 1.0.0" in x["why"] for x in b) and schedule.get_setting("app_version") == hud.__version__
    assert backup.settings()["last"] == ""                                                              # (a point isn't your backup)


def test_a_new_user_has_no_point(home):
    assert not backup.before_update() and schedule.get_setting("app_version") == hud.__version__


def test_delete_goes_to_the_recycle_bin(full, monkeypatch):
    gone = []
    monkeypatch.setattr(tools, "recycle", lambda p: gone.append(p) or True)
    r = backup.make()
    backup.delete(r["path"])
    assert gone == [Path(r["path"])]


def test_the_vault_in_a_backup_stays_shut(full):
    r = backup.make()
    i = backup.look(r["path"])
    assert "vault" in [p["id"] for p in i["parts"]] and "zebra" not in json.dumps(i)
    with open(r["path"], "rb") as f:
        h, start, about = backup._header(f)
        with zipfile.ZipFile(io.BufferedReader(backup._Open(f, start, r["size"], backup._key_of(h), about))) as z:
            assert b"ciphertext" in z.read("vault/vault.json") or PW.encode() not in z.read("vault/vault.json")


# ---------------- health ----------------
class Hub:
    brain = types.SimpleNamespace(names=[], down={}, limited={}, current="")
    _live_errors: list = []
    live = None
    recording = False


def row(c, i):
    return next(r for r in c["rows"] if r["id"] == i)


def test_every_check_answers(full):
    c = doctor.check(Hub())
    assert len(c["rows"]) == len(doctor.CHECKS) and not [r for r in c["rows"] if "Couldn't be checked" in r["detail"]], [r for r in c["rows"] if "Couldn't" in r["detail"]]
    assert all(r["state"] in ("ok", "info", "warn", "bad") and r["name"] and r["detail"] for r in c["rows"])
    assert all(r["fix"] in ("", *doctor.REPAIRS) for r in c["rows"])
    assert row(c, "database")["state"] == "ok" and row(c, "ai")["state"] == "bad" and row(c, "backup")["state"] == "warn"
    order = [r["state"] for r in c["rows"]]
    assert order == sorted(order, key=["bad", "warn", "ok", "info"].index)


def test_a_check_that_fails_is_a_finding(full, monkeypatch):
    def _boom(h):
        raise RuntimeError("no")
    monkeypatch.setattr(doctor, "CHECKS", [doctor._database, _boom])
    c = doctor.check(Hub())
    assert "RuntimeError" in row(c, "boom")["detail"] and c["bad"] == 0


def test_a_damaged_database_is_seen_and_repaired(full):
    for i in range(400):
        storage.add_event({"type": "user", "text": f"line {i} " + "x" * 200})
    c = storage.conn()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    page = c.execute("SELECT rootpage FROM sqlite_master WHERE type = 'index' AND tbl_name = 'events'").fetchone()
    size = c.execute("PRAGMA page_size").fetchone()[0]
    storage.close()
    p = storage.path()
    raw = bytearray(p.read_bytes())
    at = ((page[0] if page else 40) - 1) * size
    raw[at:at + size] = os.urandom(size)
    p.write_bytes(raw)
    assert doctor._database(Hub())["state"] == "bad"
    said = doctor.repair("database", Hub())
    assert "whole" in said or "made anew" in said
    assert doctor._database(Hub())["state"] == "ok" and len(storage.recent_events(1000)) > 300


def test_the_rescue_keeps_what_can_be_read(full):
    for i in range(20):
        storage.add_event({"type": "user", "text": f"line {i}"})
    saved, lost = doctor._rescue()
    assert saved >= 20 and lost == 0 and len(texts()) == 21 and (full.d / "assistant.db.damaged").is_file()
    assert storage.conn().execute("PRAGMA user_version").fetchone()[0] == len(storage.MIGRATIONS)


def test_a_whole_database_is_only_tidied(full):
    assert "whole" in doctor.repair("database", Hub()) and texts() == ["hello zebra"]
    assert [b for b in backup.listing() if b["point"]][0]["why"] == "before the database is repaired"


def test_no_restore_point_no_change(full, monkeypatch):
    monkeypatch.setattr(backup, "make", lambda **k: (_ for _ in ()).throw(backup.BackupError("There isn't enough room in X.")))
    schedule.set_setting("theme", "light")
    for w in ("settings", "database"):
        with pytest.raises(doctor.CareError, match="nothing was changed"):
            doctor.repair(w, Hub())
    assert schedule.get_setting("theme") == "light"


def test_files(full):
    (full.d / "profile.json").write_text("{broken")
    old = full.d / "x.tmp"
    old.write_text("left")
    os.utime(old, (time.time() - 200000,) * 2)
    (full.d / "fresh.tmp").write_text("at work")
    r = doctor._files(Hub())
    assert r["state"] == "bad" and "profile.json" in r["detail"] and r["fix"] == "files"
    said = doctor.repair("files", Hub())
    assert "1 leftover" in said and "profile.json" in said and not old.exists() and (full.d / "fresh.tmp").exists() and (full.d / "profile.json.broken").exists()
    assert doctor._files(Hub())["state"] == "ok"


def test_settings_back(full):
    old = {"theme": "light", "speak": False, "brain": "groq", "local_voice_en": "x", "lock": {"ways": ["pin"]}, "local_only": True, "keep_history": False, "news_follow": ["cricket"], "assistant_name": "Maya", "setup_done": True,
           "permissions": {"powershell": "allow", "email": "never"}, "journal_ai": True, "vault_tries": {"n": 3}}
    for k, v in old.items():
        schedule.set_setting(k, v)
    doctor.repair("settings", Hub())
    s = json.loads((full.d / "settings.json").read_text(encoding="utf-8"))
    assert not set(s) & {"theme", "speak", "brain", "local_voice_en"} and s["permissions"] == {"email": "never"}
    for k in ("lock", "local_only", "keep_history", "news_follow", "assistant_name", "setup_done", "journal_ai", "vault_tries"):
        assert s[k] == old[k], k
    assert texts() == ["hello zebra"] and vault.exists() and [b for b in backup.listing() if b["point"]]


def test_only_known_repairs_and_tools(full, monkeypatch):
    for bad in ("format", "", None, 5, ["database"], "../x"):
        with pytest.raises((doctor.CareError, TypeError)):
            doctor.repair(bad, Hub())
    opened = []
    monkeypatch.setattr(os, "startfile", lambda *a, **k: opened.append((a, k)), raising=False)
    for k in doctor.WINDOWS:
        doctor.open_windows(k)
    doctor.open_windows("ms-settings:sound")
    assert len(opened) == len(doctor.WINDOWS) + 1
    for bad in ("calc.exe", "ms-settings:windowsdefender", "https://x.com", "", None, "cmd"):
        with pytest.raises(doctor.CareError):
            doctor.open_windows(bad)
    assert len(opened) == len(doctor.WINDOWS) + 1


def test_repairs_of_windows_parts(full, monkeypatch):
    monkeypatch.setattr(netcheck, "flush_dns", lambda: "Flushed the DNS cache.")
    assert "Flushed" in doctor.repair("dns", Hub())
    for w in ("startup", "shortcuts"):
        with pytest.raises(doctor.CareError, match="installed app"):
            doctor.repair(w, Hub())
    with pytest.raises(doctor.CareError, match="No document folders"):
        doctor.repair("index", Hub())
    with pytest.raises(doctor.CareError, match="isn't available"):
        monkeypatch.setattr(hud, "recorder", None)
        doctor.repair("mic", Hub())


def test_documents_are_read_again(full, monkeypatch):
    from jarvis import docindex
    started = []
    monkeypatch.setattr(docindex, "folders", lambda: [{"id": 1, "path": "C:/x"}])
    monkeypatch.setattr(docindex, "start", lambda: started.append(1))
    doctor.repair("index", Hub())
    assert started and storage.conn().execute("SELECT COUNT(*) FROM docs").fetchone()[0] == 0


def test_the_window_cache(full):
    web = full.d / "webview" / "EBWebView"
    for p in ("Default/Cache/x", "Default/Code Cache/y", "Default/Local Storage/keep", "GrShaderCache/z", "Default/IndexedDB/keep"):
        (web / p).parent.mkdir(parents=True, exist_ok=True)
        (web / p).write_text("x")
    assert doctor.clear_window_cache() is False and (web / "Default/Cache/x").exists()
    doctor.repair("window", Hub())
    assert (web / "Default/Cache/x").exists()                                                          # only at the next start
    assert doctor.clear_window_cache() is True
    assert not (web / "Default/Cache").exists() and not (web / "GrShaderCache").exists()
    assert (web / "Default/Local Storage/keep").exists() and (web / "Default/IndexedDB/keep").exists() and not (full.d / "clear_window").exists()


def test_the_report_says_nothing_private(full, monkeypatch):
    (full.d / "jarvis.log").write_text("===== Jarvis started =====\n[planner] OperationalError: my secret words\nValueError: gsk" + "_abcdef1234567890abcd\n", encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", full.d)
    r = doctor.report(Hub())
    t = Path(r["path"]).read_text(encoding="utf-8")
    assert Path(r["path"]).parent == full.tmp / "Zubaida" / "Documents" and "planner: OperationalError" in t
    for w in ("secret words", "gsk_", "Zubaida", "zubaida", "hello zebra"):
        assert w not in t
    assert doctor.report(Hub())["path"] != r["path"]                                                    # an earlier one is never written over
    assert "Zubaida" not in doctor.for_ai(Hub())


def test_faults_since_the_start_only(full):
    (full.d / "jarvis.log").write_text("OldError: x\n===== Jarvis started =====\n[live] ConnectionResetError: y\n[live] ConnectionResetError: z\nNothing here\n", encoding="utf-8")
    assert doctor.log_errors() == [{"what": "live: ConnectionResetError", "n": 2}]


# ---------------- ended unexpectedly ----------------
@pytest.fixture
def beats(full, monkeypatch):
    monkeypatch.setitem(doctor._BEAT, "on", True)                                                        # (no thread here)
    import psutil
    monkeypatch.setattr(psutil, "boot_time", lambda: 1000.0)
    monkeypatch.setattr(psutil, "users", lambda: [])
    return full


def mark(home, beat, app=None):
    (home.d / "running.json").write_text(json.dumps({"pid": 1, "beat": beat, "app": app or hud.__version__}))


def test_a_crash_is_noticed(beats):
    assert doctor.started() == ""
    mark(beats, time.time() - 60)
    assert doctor.started() == "crash" and len(doctor.crashes()) == 1
    assert doctor._crashed(Hub())["state"] == "warn" and "ended_unexpectedly" in [e["event"] for e in audit.recent(5)]
    doctor._BEAT["on"] = True
    doctor.ended()
    doctor._BEAT["on"] = True
    assert not (beats.d / "running.json").exists() and doctor.started() == "" and len(doctor.crashes()) == 1


def test_what_is_not_a_crash(beats, monkeypatch):
    import psutil
    mark(beats, 900.0)
    assert doctor.started() == "off"                                                                     # the PC was restarted
    mark(beats, time.time() - 600, app="1.0.0")
    assert doctor.started() == ""                                                                        # Setup closed the older version
    monkeypatch.setattr(psutil, "users", lambda: [types.SimpleNamespace(started=time.time() - 100)])
    mark(beats, time.time() - 600)
    assert doctor.started() == "off"                                                                     # signed out (fast startup)
    (beats.d / "running.json").write_text("{bad")
    assert doctor.started() == "" and doctor.crashes() == []


def test_old_crashes_are_forgotten(beats):
    schedule.set_setting("crashes", ["2020-01-01T00:00:00", datetime.now().isoformat(), 5])
    assert len(doctor.crashes()) == 1


def test_setup_closing_the_app_is_no_crash(full, monkeypatch):
    import psutil
    (full.d / "running.json").write_text("{}")
    killed = []
    p = types.SimpleNamespace(info={"pid": 999999, "exe": str(full.tmp / "app" / "x.exe")}, kill=lambda: killed.append(1))
    monkeypatch.setattr(psutil, "process_iter", lambda a: [p])
    assert install.stop_running(full.tmp / "app") == 1 and killed and not (full.d / "running.json").exists()


# ---------------- start and restart ----------------
def test_at_the_start(full, monkeypatch):
    r = backup.make(keys=True)
    full.kept.clear()
    storage.clear_events()
    backup.prepare(r["path"], ["app", "keys"])
    storage.close()
    monkeypatch.setitem(os.environ, "GROQ_API_KEY", "old")
    assert "back in place" in doctor.at_start() and texts() == ["hello zebra"] and os.environ["GROQ_API_KEY"] == "gsk_zebra"
    monkeypatch.setattr(backup, "apply_pending", lambda: 1 / 0)
    assert doctor.at_start() == ""                                                                       # a fault doesn't stop the app


def test_waiting_for_the_old_one():
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.8)"])
    t = time.monotonic()
    doctor.wait_for(p.pid, 10)
    assert 0.3 < time.monotonic() - t < 8
    t = time.monotonic()
    doctor.wait_for(os.getpid(), 0.5)
    assert time.monotonic() - t < 3


def test_the_start_puts_back_before_anything_is_opened():
    src = open(hud.__file__, encoding="utf-8").read()
    m = src[src.index("\ndef main("):]
    assert m.index("QuietServer(") < m.index("doctor.at_start()") < m.index("netlog.install()") < m.index("HUB = Hub()")
    d = open(Path(hud.__file__).with_name("desktop.py"), encoding="utf-8").read()
    assert d.count("doctor.ended()") == 3 and "QUIT_HOOK = icon.quit" in d
    assert "--wait-for" in open(Path(hud.__file__).with_name("__main__.py"), encoding="utf-8").read()


# ---------------- the page's requests ----------------
@pytest.fixture
def hub(full, monkeypatch):
    h = hud.Hub()
    monkeypatch.setattr(hud, "HUB", h)
    h.again = []
    monkeypatch.setattr(hud, "restart", lambda: h.again.append(1))
    yield h
    h.ringer.stop()


def call(page, action, data=None):
    h = hud.Handler.__new__(hud.Handler)
    out = {}
    h._json = lambda d, code=200: out.update(body=d, code=code)
    h._daily_api(page, action, data or {})
    return out["code"], out["body"]


def test_requests_of_the_backup_page(hub, full, monkeypatch):
    assert call("backup", "load")[1]["settings"]["every"] == "off"
    c, j = call("backup", "make")
    assert c == 200 and j["made"]["files"] > 3 and len(j["list"]) == 1
    assert call("backup", "save", {"every": "weekly", "keep": 14})[1]["settings"]["keep"] == 14
    assert call("backup", "save", {"every": "x"})[0] == 400
    assert call("backup", "password", {"password": "a", "again": "a"})[0] == 400
    assert call("backup", "password", {"password": "backup pass 9", "again": "backup pass 9"})[1]["settings"]["password"] is True
    assert call("backup", "password_remove")[1]["settings"]["password"] is False
    assert call("backup", "look", {"path": j["made"]["path"]})[1]["locked"] is False
    c, r = call("backup", "restore", {"path": j["made"]["path"], "parts": ["app"]})
    assert c == 200 and r["restart"] and hub.again == [1] and backup.settings()["pending"]
    opened = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(p), raising=False)
    call("backup", "open"), call("backup", "open", {"points": True})
    assert opened == [str(backup.folder()), str(backup.points_dir())]
    monkeypatch.setattr(hud, "_pick_folder", lambda w="": "")
    monkeypatch.setattr(hud, "_pick_file", lambda k, s="": "")
    assert call("backup", "pick")[1] == {"path": ""} and call("backup", "pick_file")[1] == {"path": ""}
    assert call("backup", "nothing")[0] == 404 and call("backup", "look", {"path": ["x"]})[0] == 400 and call("backup", "delete", {})[0] == 400


def test_not_while_something_is_recorded(hub, full, monkeypatch):
    p = backup.make()["path"]
    monkeypatch.setattr(hub, "meeting_on", lambda: True)
    for page, action, data in (("backup", "restore", {"path": p, "parts": ["app"]}), ("health", "repair", {"what": "restart"}), ("health", "repair", {"what": "settings"})):
        c, j = call(page, action, data)
        assert c == 400 and "recorded" in j["error"]
    assert hub.again == [] and not backup.settings()["pending"]
    monkeypatch.setattr(hub, "meeting_on", lambda: False)
    hub.live = types.SimpleNamespace(active=True)
    assert "Live" in call("health", "repair", {"what": "restart"})[1]["error"]
    hub.live = None


def test_requests_of_the_health_page(hub, full, monkeypatch):
    c, j = call("health", "check")
    assert c == 200 and len(j["rows"]) == len(doctor.CHECKS) and {"id", "name", "about", "restart"} <= set(j["repairs"][0])
    c, j = call("health", "repair", {"what": "files"})
    assert "leftover" in j["said"] and j["rows"]
    c, j = call("health", "repair", {"what": "restart"})
    assert j["restart"] and hub.again == [1]
    assert call("health", "repair", {"what": "format"})[0] == 400 and call("health", "repair", {"what": ["x"]})[0] == 400 and call("health", "open", {"what": "calc"})[0] == 400
    assert call("health", "report")[1]["path"].endswith(".txt") and call("health", "x")[0] == 404
    ev = [e["event"] for e in audit.recent(10)]
    assert "repaired" in ev


def test_a_lock_stops_them():
    assert not any(p.startswith(("/api/backup", "/api/health")) for p in hud.WHILE_LOCKED)


# ---------------- the AI ----------------
def test_the_ai_looks_and_backs_up_only(hub, full):
    ctx = types.SimpleNamespace(approve=lambda *a, **k: pytest.fail("asked"))
    out = tools.self_check_tool({"action": "check"}, ctx)
    assert "Database" not in out.split("\n")[0] and "Settings › Health" in out and "problem" in out
    assert "backup was made" in tools.self_check_tool({"action": "backup"}, ctx) and len(backup.listing()) == 1
    d = next(x for x in tools.TOOL_DEFINITIONS if x["name"] == "self_check")
    assert d["input_schema"]["properties"]["action"]["enum"] == ["check", "backup", "updates"]
    assert "self_check" not in agents.AGENT_TOOLS and "self_check" not in automations.STEP_TOOLS
    assert "self_check" in providers.LOCAL_TOOLS and "self_check:check" in plans.LOOKING and "self_check:backup" not in plans.LOOKING
    for said in ("khud ko check karo", "something is wrong with you", "make a backup", "awaz theek nahi"):
        assert re.search(providers.BIG_TOOLS["self_check"], said, re.I), said


def test_a_backup_is_a_secret_file():
    for p in ("C:\\x\\Personal Assistant 2026-01-01 10.00.00.pabackup", "D:/a/backup.dat"):
        assert guard.secret_file(p)


def test_it_is_in_the_list_of_what_is_kept(full):
    backup.make()
    i = next(x for x in privacy.kept()["items"] if x["id"] == "backups")
    assert i["n"] == 1 and i["bytes"] > 0 and not i["clear"] and i["go"] == "backup"


def test_the_timeline_has_words_for_it():
    src = open(backup.__file__, encoding="utf-8").read() + open(doctor.__file__, encoding="utf-8").read()
    for e in re.findall(r'audit\.record\("([a-z_]+)"', src):
        assert e in timeline._WORDS, e


# ---------------- the page ----------------
def test_the_page_has_both_tabs():
    for t in ("backup", "health"):
        assert f'data-settab="{t}"' in HTML and f'data-setgroup="{t}"' in HTML
    for i in re.findall(r'\$\("((?:bk|hc)[A-Za-z0-9]+)"\)', HTML):
        assert f'id="{i}"' in HTML, i
    assert HTML.index("let bkD = null") < HTML.index('setTab(storeGet("jarvis.settab")')
    assert "setCur" in HTML and '["backup", "health"' in HTML
    for r in doctor.REPAIRS.values():
        assert "—" not in r[0] + r[1]

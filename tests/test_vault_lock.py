"""Phase 9, part 2: the vault and the privacy lock. Made-up data folder; Windows Hello is never asked (a pretend answer), the real
clipboard is never touched."""
import base64
import json
import os
import re
import threading
import time
from datetime import date, datetime, timedelta

import pytest

from jarvis import agents, audit, automations, config, guard, hello, lock, privacy, providers, schedule, storage, timeline, tools, vault

PW, PW2 = "correct horse battery", "another long phrase 7"


@pytest.fixture
def home(tmp_path, monkeypatch):
    storage.close()
    monkeypatch.setattr(storage, "path", lambda: tmp_path / "assistant.db")
    monkeypatch.setattr(schedule, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(audit, "file", lambda: tmp_path / "audit.log")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(vault, "N", 2 ** 12)                       # (quick here; the real number is checked below)
    monkeypatch.setattr(vault, "CHANGED", None)
    monkeypatch.setattr(lock, "CHANGED", None)
    monkeypatch.setenv("JARVIS_HELLO_TEST", "yes")
    monkeypatch.setattr(vault, "_OPEN", None)
    vault._TRIES.update(n=0, until=0.0)
    vault._CLIP.update(seq=None, timer=None)
    lock._STATE.update(locked=False, why="", since=0.0, signed_in=0.0)
    lock._TRIES.update(n=0, until=0.0)
    tools.STOP.clear()
    yield tmp_path
    vault._OPEN = None
    lock._STATE.update(locked=False)
    storage.close()


@pytest.fixture
def made(home):
    return vault.create(PW, PW)


@pytest.fixture
def s(made):
    return made["session"]


def login(s, **f):
    return vault.save(s, "login", {"title": "Gmail", "username": "me@x.com", "password": "S3cret-pass-ڈ", **f})["id"]


# ---------------- the key ----------------
def test_the_real_numbers():
    import importlib
    src = open(vault.__file__, encoding="utf-8").read()
    assert "N, R, P = 2 ** 17, 8, 1" in src and importlib.import_module("cryptography")


def test_nothing_readable_on_disk(s, home):
    i = login(s, notes="my notes here", url="mail.google.com")
    vault.file_add(s, i, "passport scan.txt", b"PLAINTEXT-OF-THE-FILE" * 100)
    for f in (home / "vault").rglob("*"):
        if f.is_file():
            raw = f.read_bytes()
            for word in (b"Gmail", b"S3cret", b"me@x", b"notes here", b"passport", b"PLAINTEXT", PW.encode(), b"google"):
                assert word not in raw, (f.name, word)
    for f in (home / "audit.log", home / "settings.json"):
        if f.exists():
            assert b"Gmail" not in f.read_bytes() and b"S3cret" not in f.read_bytes()


def test_open_lock_open(made):
    s = made["session"]
    i = login(s)
    assert vault.lock() and not vault.lock() and not vault.is_open()
    for f in (lambda: vault.get(s, i), lambda: vault.listing(s), lambda: vault.reveal(s, i, "password"), lambda: vault.copy(s, i, "password"), lambda: vault.save(s, "note", {"title": "x"})):
        with pytest.raises(vault.VaultError, match="locked"):
            f()
    s2 = vault.unlock(PW)
    assert s2 != s and vault.reveal(s2, i, "password")["value"] == "S3cret-pass-ڈ"
    for bad in (s, "", None, s2[:-1], s2 + "x", 5):                     # only who opened it
        with pytest.raises(vault.VaultError):
            vault.get(bad, i)


def test_one_at_a_time(made):
    s1 = made["session"]
    s2 = vault.unlock(PW)
    with pytest.raises(vault.VaultError):
        vault.listing(s1)
    assert vault.listing(s2) == []


@pytest.mark.parametrize("pw", ["", None, "short", "123456789", "password123456", "aaaaaaaaaaaa", "1234567890", "qwertyuiop12", "x" * 600])
def test_weak_master_passwords(home, pw):
    with pytest.raises(vault.VaultError):
        vault.create(pw, pw)
    assert not vault.exists()


def test_not_the_same_twice_and_not_over_another(home):
    with pytest.raises(vault.VaultError, match="same"):
        vault.create(PW, PW2)
    vault.create(PW, PW)
    with pytest.raises(vault.VaultError, match="already"):
        vault.create(PW2, PW2)
    vault.unlock(PW)


def test_the_same_letters_typed_another_way(home):
    vault.create("pässwörd tree café", "pässwörd tree café")
    import unicodedata
    vault.unlock(unicodedata.normalize("NFD", "pässwörd tree café"))


def test_wrong_tries_wait_longer_and_longer(made, monkeypatch):
    vault.lock()
    for n in range(4):
        with pytest.raises(vault.VaultError, match="isn't the master password.$"):
            vault.unlock("wrong wrong wrong")
    with pytest.raises(vault.VaultError, match="Wait 30"):
        vault.unlock("wrong wrong wrong")
    with pytest.raises(vault.VaultError, match="Too many"):
        vault.unlock(PW)                                                # not even the right one
    vault._TRIES.update(n=0, until=0.0)                                 # a restart
    with pytest.raises(vault.VaultError, match="Too many"):
        vault.unlock(PW)
    real = time.time
    monkeypatch.setattr(vault.time, "time", lambda: real() + 31)
    with pytest.raises(vault.VaultError, match="Wait 60"):
        vault.unlock("wrong wrong wrong")
    monkeypatch.setattr(vault.time, "time", lambda: real() + 100)
    vault.unlock(PW)
    assert schedule.get_setting("vault_tries") is None and vault._TRIES["n"] == 0
    for bad in ("x", [1], [True, 5], {"n": 9}):
        schedule.set_setting("vault_tries", bad)
        vault.unlock(PW)


def test_recovery_code(made):
    i = login(made["session"])
    vault.lock()
    code = made["recovery"]
    assert re.fullmatch(r"([A-Z2-7]{4}-){7}[A-Z2-7]{4}", code)
    with pytest.raises(vault.VaultError, match="recovery code"):
        vault.unlock_recovery("AAAA-" * 7 + "AAAA", PW2, PW2)
    with pytest.raises(vault.VaultError):
        vault.unlock_recovery(code, "short", "short")
    r = vault.unlock_recovery(" " + code.lower().replace("-", " ").replace("o", "0").replace("i", "1").replace("b", "8"), PW2, PW2)
    assert vault.reveal(r["session"], i, "password")["value"].startswith("S3cret") and r["recovery"] != code
    vault.lock()
    with pytest.raises(vault.VaultError):
        vault.unlock(PW)
    with pytest.raises(vault.VaultError):
        vault.unlock_recovery(code, PW, PW)                             # used up
    vault.unlock(PW2)


def test_password_and_code_changed(made):
    s = made["session"]
    with pytest.raises(vault.VaultError):
        vault.change_password(s, "wrong", PW2, PW2)
    vault.change_password(s, PW, PW2, PW2)
    with pytest.raises(vault.VaultError):
        vault.new_recovery(s, PW)
    code = vault.new_recovery(s, PW2)
    vault.lock()
    with pytest.raises(vault.VaultError):
        vault.unlock(PW)
    with pytest.raises(vault.VaultError):
        vault.unlock_recovery(made["recovery"], PW, PW)
    vault.unlock_recovery(code, PW, PW)


@pytest.mark.parametrize("where", ["data", "password", "n", "salt", "id"])
def test_any_change_to_the_file_is_noticed(made, where):
    login(made["session"])
    vault.lock()
    f = vault._file()
    h = json.loads(f.read_text())
    if where in ("data", "password"):
        box = h if where == "data" else h["wrapped"]
        raw = bytearray(base64.b64decode(box[where]))
        raw[-1] ^= 1
        box[where] = base64.b64encode(raw).decode()
    elif where == "n":
        h["n"] = 2
    else:
        h[where] = base64.b64encode(b"0" * 16).decode()
    f.write_text(json.dumps(h))
    with pytest.raises(vault.VaultError):
        vault.unlock(PW)
    assert not vault.is_open()


def test_a_damaged_file_and_the_one_before(made, home):
    s = made["session"]
    login(s)
    vault.lock()
    vault._file().write_text("{half")
    assert vault.listing(vault.unlock(PW)) == []                       # the version before
    vault.lock()
    vault._file().with_name("vault.json.bak").write_text("nothing")
    vault._file().write_text("{half")
    with pytest.raises(vault.VaultError, match="damaged"):
        vault.unlock(PW)
    assert vault.status()["damaged"] and vault.status()["exists"]


def test_a_full_disk_changes_nothing(s, monkeypatch):
    i = login(s)
    monkeypatch.setattr(vault, "_write", lambda h: (_ for _ in ()).throw(OSError(28, "No space left")))
    with pytest.raises(OSError):
        vault.save(s, "login", {"title": "Other"}, i)
    with pytest.raises(OSError):
        login(s, title="New")
    with pytest.raises(OSError):
        vault.file_add(s, i, "x.txt", b"x")
    assert [e["title"] for e in vault.listing(s)] == ["Gmail"] and vault.get(s, i)["files"] == []
    assert not list((vault.folder() / "files").glob("*"))


# ---------------- Windows Hello ----------------
def test_hello_opens_it_and_can_be_turned_off(made, monkeypatch):
    s = made["session"]
    with pytest.raises(vault.VaultError, match="isn't turned on"):
        vault.unlock_hello()
    with pytest.raises(vault.VaultError):
        vault.hello_on(s, "wrong")
    vault.hello_on(s, PW)
    assert vault.status()["hello"]
    vault.lock()
    raw = vault._file().read_text()
    s = vault.unlock_hello()
    assert vault.listing(s) == [] and "pretend" not in raw
    monkeypatch.setenv("JARVIS_HELLO_TEST", "no")
    vault.lock()
    with pytest.raises(ValueError, match="cancelled"):
        vault.unlock_hello()
    assert not vault.is_open()
    monkeypatch.setattr(hello, "sign", lambda n, a: b"another signature" * 8)
    with pytest.raises(vault.VaultError, match="different answer"):
        vault.unlock_hello()
    s = vault.unlock(PW)
    vault.hello_off(s)
    assert not vault.status()["hello"]


def test_the_recovery_code_turns_hello_off(made):
    vault.hello_on(made["session"], PW)
    vault.lock()
    vault.unlock_recovery(made["recovery"], PW2, PW2)
    assert not vault.status()["hello"]


def test_hello_names_and_answers_are_checked(monkeypatch):
    ran = []
    monkeypatch.setattr(hello, "_pretend", lambda: None)
    monkeypatch.setattr(hello, "_run", lambda script, t: ran.append(script) or "Signed " + base64.b64encode(b"x" * 256).decode())
    monkeypatch.setattr(hello, "_to_front", lambda stop: None)
    for bad in ("", "a'; Remove-Item x", "a b", "x" * 65, "ä"):
        for f in (lambda: hello.sign(bad, b"1"), lambda: hello.make_key(bad)):
            with pytest.raises(hello.HelloError):
                f()
    assert not ran
    assert hello.sign("Good-Name1", b"abc") == b"x" * 256 and "'Good-Name1'" in ran[0] and base64.b64encode(b"abc").decode() in ran[0]
    for answer in ("UserCanceled", "NotFound", "", "Signed !!!", "Signed eA=="):
        monkeypatch.setattr(hello, "_run", lambda script, t, a=answer: a)
        with pytest.raises(hello.HelloError):
            hello.sign("Good-Name1", b"abc")
    monkeypatch.setattr(hello, "_run", lambda script, t: ran.append(script) or "Verified")
    assert hello.verify("Open'; evil") is True and "evil" in ran[-1] and "Open'; evil" not in ran[-1]
    monkeypatch.setattr(hello, "_run", lambda script, t: "Canceled")
    assert hello.verify() is False
    monkeypatch.setattr(hello, "_run", lambda script, t: "DisabledByPolicy")
    with pytest.raises(hello.HelloError, match="turned off"):
        hello.verify()


def test_one_box_at_a_time(monkeypatch):
    monkeypatch.setattr(hello, "_pretend", lambda: None)
    go = threading.Event()
    monkeypatch.setattr(hello, "_run", lambda script, t: go.wait(5) and "Verified")
    monkeypatch.setattr(hello, "_to_front", lambda stop: None)
    t = threading.Thread(target=hello.verify)
    t.start()
    time.sleep(0.1)
    with pytest.raises(hello.HelloError, match="already"):
        hello.verify()
    go.set()
    t.join()


def test_the_pretend_answer_only_in_test_copies(monkeypatch):
    monkeypatch.setenv("JARVIS_HELLO_TEST", "yes")
    monkeypatch.setattr(config, "ISOLATED", False)
    assert hello._pretend() is None
    monkeypatch.setattr(config, "ISOLATED", True)
    monkeypatch.delenv("JARVIS_HELLO_TEST")
    assert hello._pretend() == "off" and hello.ready() is False


# ---------------- entries ----------------
def test_lists_have_no_secrets(s):
    i = login(s, totp="JBSWY3DPEHPK3PXP", notes="hush")
    c = vault.save(s, "card", {"title": "Bank", "number": "4111 1111-1111 1234", "cvv": "987", "pin": "5566", "holder": "A B", "expires": "12/30"})["id"]
    p = vault.save(s, "paper", {"title": "Passport", "paper": "Passport", "number": "AB1234567", "expires": "2030-01-01"})["id"]
    text = json.dumps([vault.listing(s), vault.get(s, i), vault.get(s, c), vault.get(s, p), vault.health(s)])
    for secret in ("S3cret", "JBSW", "987", "5566", "411111", "AB1234567"):
        assert secret not in text, secret
    assert "•••• 1234" in json.dumps(vault.listing(s), ensure_ascii=False) and vault.get(s, i)["has"] == {"password": True, "totp": True}
    assert vault.reveal(s, c, "cvv")["value"] == "987" and vault.reveal(s, p, "number")["value"] == "AB1234567"
    for f in ("title2", "files", "was0", "was9", "__class__", "", None, "key", "code"):
        with pytest.raises(vault.VaultError):
            vault.reveal(s, c, f)


@pytest.mark.parametrize("kind,f", [("login", {}), ("login", {"title": ""}), ("login", {"title": "x" * 501}), ("login", {"title": "x", "url": "javascript:alert(1)"}), ("login", {"title": "x", "url": "file:///c:/"}),
                                    ("login", {"title": "x", "totp": "not base32 !"}), ("login", {"title": "x", "totp": "AA"}), ("card", {"title": "x", "number": "12"}), ("card", {"title": "x", "number": "abcd1234efgh"}),
                                    ("paper", {"title": "x", "expires": "31/12/2030"}), ("paper", {"title": "x", "expires": "2030-02-30"}), ("evil", {"title": "x"}), (None, {"title": "x"}), ("note", "text"), ("note", {"title": "x", "notes": "n" * 20001})])
def test_bad_entries(s, kind, f):
    with pytest.raises(vault.VaultError):
        vault.save(s, kind, f)
    assert vault.listing(s) == []


def test_save_change_and_old_passwords(s):
    i = login(s)
    for n in range(7):
        vault.save(s, "login", {"password": f"pass-number-{n}"}, i)
    g = vault.get(s, i)
    assert len(g["was"]) == 5 and vault.reveal(s, i, "was0")["value"] == "pass-number-5" and g["username"] == "me@x.com"
    vault.save(s, "card", {"title": "Renamed"}, i, True, "b, a ,a,")
    e = vault.listing(s)[0]
    assert (e["kind"], e["title"], e["fav"], e["tags"]) == ("login", "Renamed", True, ["a", "b"])
    with pytest.raises(vault.VaultError, match="gone"):
        vault.save(s, "login", {"title": "x"}, "nope")
    assert vault.save(s, "login", {"title": "a\x00b\nc", "url": "example.com:8080/x"})["title"] == "ab c"
    assert vault.listing(s, "example")[0]["url"] == "https://example.com:8080/x"


def test_search_and_kinds(s):
    login(s)
    vault.save(s, "note", {"title": "Wi-Fi", "notes": "hidden words"}, tags=["ghar"])
    assert [e["title"] for e in vault.listing(s, "GMAIL me@")] == ["Gmail"] and vault.listing(s, "hidden") == []          # a secret note isn't searched through
    assert [e["title"] for e in vault.listing(s, "ghar")] == ["Wi-Fi"] and len(vault.listing(s, "", "login")) == 1 and vault.listing(s, "S3cret") == []


def test_bin(s, made):
    i = login(s)
    f = vault.file_add(s, i, "a.txt", b"abc")
    vault.delete(s, i)
    assert vault.listing(s) == [] and vault.trash(s)[0]["title"] == "Gmail"
    vault.restore(s, i)
    assert vault.file_get(s, f["id"]) == ("a.txt", b"abc")
    vault.delete(s, i)
    vault._OPEN["data"]["trash"][i]["gone"] = (datetime.now() - timedelta(days=31)).isoformat()
    vault._save(vault._OPEN)
    vault.lock()
    s = vault.unlock(PW)
    assert vault.trash(s) == [] and not list((vault.folder() / "files").glob("*"))
    with pytest.raises(vault.VaultError):
        vault.restore(s, i)
    vault.delete(s, login(s))
    assert vault.empty_trash(s) == 1


def test_two_step_codes_as_in_the_standard():
    key = base64.b32encode(b"12345678901234567890").decode()
    assert [vault.totp(key, t)[0] for t in (59, 1111111109, 1111111111, 1234567890, 2000000000)] == ["287082", "081804", "050471", "005924", "279037"]
    assert vault.totp(key, 59)[1] == 1 and vault.totp(key, 60)[1] == 30
    assert vault._totp_secret("otpauth://totp/X:me?secret=jbsw%20y3dpehpk3pxp&issuer=X") == "JBSWY3DPEHPK3PXP"


def test_made_passwords():
    seen = {vault.generate() for _ in range(200)}
    assert len(seen) == 200 and all(len(p) == 20 for p in seen)
    for p in seen:
        assert re.search("[a-z]", p) and re.search("[A-Z]", p) and re.search("[0-9]", p) and re.search(r"[!@#$%&*+\-=?_.]", p) and not set(p) & set("Il1O0o")
    assert re.fullmatch("[a-z]{8}", vault.generate(3, False, False, False)) and len(vault.generate(999)) == 64 and len(vault.generate("x")) == 20
    assert vault.strength(vault.generate()) == 4 and vault.strength("password") == 0 and vault.strength("") == 0 and vault.strength("aaaaaaaaaaaaaaaa") < 3


def test_health(s):
    a, b = login(s, title="A", password="abc"), login(s, title="B", password="Very-long-Unique-77!x")
    c = login(s, title="C", password="Very-long-Unique-77!x")
    vault._OPEN["data"]["entries"][b]["set"] = "2020-01-01T00:00:00"
    h = vault.health(s)
    assert [x["title"] for x in h["weak"]] == ["A"] and {x["title"] for x in h["again"]} == {"B", "C"} and [x["title"] for x in h["old"]] == ["B"] and h["score"] == 0
    assert {a, b, c} == {x["id"] for x in vault.listing(s)}


# ---------------- files ----------------
@pytest.mark.parametrize("size", [1, vault.CHUNK - 1, vault.CHUNK, vault.CHUNK + 1, 3 * vault.CHUNK])
def test_files_round_trip(s, size):
    i, data = login(s), os.urandom(size)
    f = vault.file_add(s, i, "x.bin", data)
    assert vault.file_get(s, f["id"]) == ("x.bin", data)


def test_files_changed_cut_or_swapped_are_noticed(s):
    i = login(s)
    a, b = vault.file_add(s, i, "a", b"A" * (2 * vault.CHUNK)), vault.file_add(s, i, "b", b"B" * (2 * vault.CHUNK))
    p, q = vault._path(a["id"]), vault._path(b["id"])
    good = p.read_bytes()
    n = vault.CHUNK + 16
    for bad in (good[:-1], good[:n], good + b"x", bytes([good[0] ^ 1]) + good[1:], good[n:] + good[:n], q.read_bytes(), b""):
        p.write_bytes(bad)
        with pytest.raises(vault.VaultError, match="changed or is damaged"):
            vault.file_get(s, a["id"])
    p.unlink()
    with pytest.raises(vault.VaultError, match="isn't there"):
        vault.file_get(s, a["id"])


def test_file_limits_and_names(s, home, monkeypatch):
    i = login(s)
    for data in (b"", b"x" * (vault.MAX_FILE + 1)):
        with pytest.raises(vault.VaultError):
            vault.file_add(s, i, "x", data)
    with pytest.raises(vault.VaultError):
        vault.file_add(s, i, " .. ", b"x")
    f = vault.file_add(s, i, "..\\..\\evil:name?.txt", b"data")
    assert f["name"] == "_.._evil_name_.txt"
    for bad in ("../x", "", None, "a" * 24 + "x", "G" * 24):
        with pytest.raises(vault.VaultError):
            vault.file_get(s, bad)
        with pytest.raises(vault.VaultError):
            vault._path(bad)
    out = home / "Documents"
    a, b = vault.file_save(s, f["id"], out), vault.file_save(s, f["id"], out)
    assert a.parent == out and a.read_bytes() == b"data" and b.name.endswith("(2).txt")
    monkeypatch.setattr(vault, "MAX_ALL", 10)
    with pytest.raises(vault.VaultError, match="500 MB"):
        vault.file_add(s, i, "y", b"1234567")
    monkeypatch.setattr(vault, "MAX_FILES", 1)
    with pytest.raises(vault.VaultError):
        vault.file_add(s, i, "y", b"1")
    vault.file_delete(s, f["id"])
    assert vault.get(s, i)["files"] == [] and not list((vault.folder() / "files").glob("*"))


# ---------------- in and out ----------------
def test_import(s):
    text = "\ufeffname,url,username,password,note\nA,https://a.com/,me,p1,n\nA,https://a.com/,me,p1,n\n,https://www.b.com/login,you,\"p,2\"\"x\",\nOnly a name,,,,\nBad,javascript:x,u,p3,\n,,,,\n"
    r = vault.import_csv(s, text)
    assert r == {"added": 3, "same": 1, "bad": 1}
    by = {e["title"]: e for e in vault.listing(s)}
    assert set(by) == {"A", "b.com", "Bad"} and by["Bad"]["url"] == "" and vault.reveal(s, by["b.com"]["id"], "password")["value"] == 'p,2"x'
    assert vault.import_csv(s, text)["added"] == 0
    assert vault.import_csv(s, "folder,favorite,type,name,notes,login_uri,login_username,login_password,login_totp\n,,login,Bit,,bit.com,u,pw9,JBSWY3DPEHPK3PXP\n")["added"] == 1
    assert next(e for e in vault.listing(s) if e["title"] == "Bit")["totp"]
    for bad in ("", "a", "x,y\n1,2", None, "x" * (4 * 2**20 + 1)):
        with pytest.raises(vault.VaultError):
            vault.import_csv(s, bad)


def test_export_needs_the_password_again(s, home):
    login(s)
    with pytest.raises(vault.VaultError):
        vault.export_csv(s, "wrong", home / "D")
    p = vault.export_csv(s, PW, home / "D")
    assert "NOT ENCRYPTED" in p.name and "S3cret-pass-ڈ" in p.read_text(encoding="utf-8")


def test_removing_takes_the_word(s, monkeypatch):
    ran = []
    import shutil
    monkeypatch.setattr(tools, "_ps", lambda script, timeout=0: ran.append(script) or shutil.rmtree(vault.folder()))
    for word in ("", "delete", "yes", None):
        with pytest.raises(vault.VaultError):
            vault.remove(word)
    vault.remove("DELETE")
    assert not vault.exists() and not vault.is_open() and "SendToRecycleBin" in ran[0]


# ---------------- locking by itself ----------------
def test_locks_when_not_used(s, monkeypatch):
    real = time.monotonic
    assert vault.check_idle() is False
    monkeypatch.setattr(vault.time, "monotonic", lambda: real() + 290)
    assert vault.check_idle() is False
    vault.listing(s)                                                    # use starts the time again
    monkeypatch.setattr(vault.time, "monotonic", lambda: real() + 580)
    assert vault.check_idle() is False
    monkeypatch.setattr(vault.time, "monotonic", lambda: real() + 900)
    assert vault.check_idle() is True and not vault.is_open()
    for bad in (0, True, 7, "5", None):
        with pytest.raises(vault.VaultError):
            vault.settings({"idle": bad})


def test_asking_for_the_status_is_no_use(s, monkeypatch):
    used = vault._OPEN["used"]
    vault.status()
    vault.is_open()
    assert vault._OPEN["used"] == used


# ---------------- what runs out ----------------
def test_reminders_say_nothing_of_what_it_is(s, home):
    d = (date.today() + timedelta(days=20)).isoformat()
    vault.save(s, "paper", {"title": "My CNIC", "expires": d})
    vault.save(s, "card", {"title": "Bank", "expires": "12/30"})
    assert schedule.get_setting("vault_due") == [d]
    vault.lock()
    said = []
    noon = datetime.now().replace(hour=12)
    notify = lambda t, k: said.append(t)                                                            # noqa: E731
    assert vault.tick(noon.replace(hour=8), notify) == 0
    assert vault.tick(noon, notify) == 1 and vault.tick(noon, notify) == 0
    assert "20 days" in said[0] and "CNIC" not in said[0]
    assert vault.tick(noon + timedelta(days=14), notify) == 1 and vault.tick(noon + timedelta(days=20), notify) == 1 and "today" in said[-1]
    assert vault.tick(noon + timedelta(days=21), notify) == 0
    vault.settings({"remind": False})
    assert schedule.get_setting("vault_due") is None and vault.tick(noon, notify) == 0
    schedule.set_setting("vault_remind", True)
    schedule.set_setting("vault_due", ["junk", 5, None])
    assert vault.tick(noon, notify) == 0


# ---------------- the clipboard ----------------
def test_copy_and_the_clipboard(s, monkeypatch):
    put = []
    monkeypatch.setattr(vault, "_put", put.append)
    i = login(s, totp="JBSWY3DPEHPK3PXP")
    assert vault.copy(s, i, "password") == 30 and put == ["S3cret-pass-ڈ"]
    vault.copy(s, i, "code")
    assert re.fullmatch(r"\d{6}", put[-1])
    vault.copy(s, i, "username")
    with pytest.raises(vault.VaultError):
        vault.copy(s, i, "url")                                         # empty
    seq = [5]
    monkeypatch.setattr(vault, "_sequence", lambda: seq[0])
    vault._CLIP["seq"] = 5
    assert vault.on_clipboard()
    seq[0] = 6                                                          # something else was copied since
    assert not vault.on_clipboard() and vault.clear_clipboard() is False


# ---------------- the AI stays out ----------------
def test_the_ai_has_no_way_in(s, monkeypatch, home):
    login(s)
    ctx = tools.ToolContext(confirm=lambda q, kind=None: True, notify=lambda *a: None)
    for name in tools._HANDLERS:
        assert "vault" not in name and "password" not in name and name not in ("lock", "unlock")
    for lists in (agents.AGENT_TOOLS, providers.LOCAL_TOOLS, automations.STEP_TOOLS):
        assert not any("vault" in x for x in lists)
    looked = []
    for name in ("look_at_screen", "take_screenshot", "read_screen_text"):
        monkeypatch.setitem(tools._HANDLERS, name, lambda inp, c: looked.append(1) or "seen")
        out, err = tools.execute(name, {"source": "window"}, ctx)
        assert err and "vault is open" in out
    assert tools.execute("read_screen_text", {"source": "file", "path": "x"}, ctx)[0] and looked == [1]
    monkeypatch.setitem(tools._HANDLERS, "clipboard", lambda inp, c: "S3cret")
    monkeypatch.setattr(vault, "on_clipboard", lambda: True)
    out, err = tools.execute("clipboard", {"action": "read"}, ctx)
    assert err and "S3cret" not in out
    monkeypatch.setattr(vault, "on_clipboard", lambda: False)
    vault.lock()
    assert tools.execute("look_at_screen", {}, ctx)[0] == "seen"
    for p in (r"C:\x\vault\vault.json", "vault.json.bak", r"D:\lock.dat"):
        assert guard.secret_file(p)
    assert privacy.kept()["items"] and "me@x" not in json.dumps(privacy.kept()) and "S3cret" not in json.dumps(privacy.kept())


def test_the_record_says_what_happened_but_not_with_what(s):
    i = login(s)
    from jarvis import hud
    for a, d in (("reveal", {"field": "password"}), ("get", {}), ("delete", {})):
        call_vault(a, {"session": s, "id": i, **d})
    text = audit.file().read_text(encoding="utf-8")
    assert "vault_secret_shown" in text and "Gmail" not in text and "S3cret" not in text and i not in text
    assert any(r["title"] == "A secret of the vault was shown" for r in timeline.of_day(date.today().isoformat()))
    assert hud


# ---------------- the page's requests ----------------
def call_vault(action, data=None):
    from jarvis import hud
    got = []
    h = hud.Handler.__new__(hud.Handler)
    h._json = lambda d, status=200: got.append((status, d))
    h._bytes = lambda b, k: got.append((200, (b, k)))
    h._vault(action, data or {})
    return got[0]


def test_every_request_of_the_vault(home, monkeypatch):
    st, r = call_vault("create", {"password": PW, "again": PW})
    assert st == 200 and r["recovery"] and r["status"]["open"]
    s = r["session"]
    i = call_vault("save", {"session": s, "kind": "login", "fields": {"title": "A", "password": "pw-1-abc"}})[1]["saved"]
    f = vault.file_add(s, i, "a.svg", b"<svg onload=alert(1)>")
    assert call_vault("view", {"session": s, "file": f["id"]}) == (200, (b"<svg onload=alert(1)>", "application/octet-stream"))        # never shown as something that runs
    for action in ("get", "reveal", "copy", "generate", "strength", "trash", "health", "save", "delete", "restore", "empty", "file_delete", "file_save", "import", "export", "password", "recovery", "hello", "settings", "list", "view"):
        for bad in (None, "", "x" * 32):
            st, r = call_vault(action, {"session": bad, "id": i, "file": f["id"], "password": PW})
            assert st == 400 and r["error"] == "The vault is locked.", action
    assert call_vault("nonsense", {"session": s})[0] == 404
    assert call_vault("status")[1]["exists"] and call_vault("lock")[1]["open"] is False
    assert call_vault("unlock", {"password": ["x"]})[0] == 400 and call_vault("unlock", {"password": PW})[0] == 200
    assert call_vault("list", {"session": s})[0] == 400                 # (the old session)


# ---------------- the privacy lock ----------------
@pytest.fixture
def pin(home):
    lock.set_pin("2580x", "2580x")
    lock.set_settings({"ways": ["pin", "hello"]})
    return home


@pytest.mark.parametrize("p", ["", "123", "1111", "1234", "4321", "56789", "x" * 33])
def test_pins_that_are_too_easy(home, p):
    with pytest.raises(lock.LockError):
        lock.set_pin(p, p)
    assert not lock.settings()["has_pin"]


def test_the_pin_is_not_readable_and_needs_the_old_one(pin):
    raw = (pin / "lock.dat").read_bytes()
    assert b"2580x" not in raw and b"salt" not in raw                  # (locked with the Windows account too)
    for old in (None, "wrong"):
        with pytest.raises(lock.LockError):
            lock.set_pin("9ab3", "9ab3", old)
    with pytest.raises(lock.LockError, match="same"):
        lock.set_pin("9ab3", "9ab4", "2580x")
    lock.set_pin("9ab3", "9ab3", "2580x")
    lock.lock()
    with pytest.raises(lock.LockError):
        lock.unlock_pin("2580x")
    lock.unlock_pin("9ab3")
    with pytest.raises(lock.LockError):
        lock.remove_pin("2580x")
    lock.remove_pin("9ab3")
    assert lock.settings()["ways"] == ["hello"]


def test_no_lock_without_a_way_to_open_it(home):
    assert lock.lock() is False and not lock.is_locked()
    with pytest.raises(lock.LockError):
        lock.set_settings({"ways": ["pin"]})
    for bad in (["face"], "hello", [1], None):
        with pytest.raises(lock.LockError):
            lock.set_settings({"ways": bad})
    for bad in (2, True, "5", None, -1):
        with pytest.raises(lock.LockError):
            lock.set_settings({"idle": bad})


def test_hello_only_when_it_is_there(home, monkeypatch):
    monkeypatch.setenv("JARVIS_HELLO_TEST", "off")
    with pytest.raises(lock.LockError, match="isn't set up"):
        lock.set_settings({"ways": ["hello"]})


def test_opening(pin, monkeypatch):
    told = []
    monkeypatch.setattr(lock, "CHANGED", lambda on, why: told.append((on, why)))
    assert lock.lock() and lock.lock() and told == [(True, "you locked it")]
    with pytest.raises(lock.LockError, match="isn't the PIN"):
        lock.unlock_pin("0000")
    lock.unlock_pin("2580x")
    lock.lock()
    monkeypatch.setenv("JARVIS_HELLO_TEST", "no")
    with pytest.raises(lock.LockError, match="Not opened"):
        lock.unlock_hello()
    assert lock.is_locked()
    monkeypatch.setenv("JARVIS_HELLO_TEST", "yes")
    lock.unlock_hello()
    assert [t[0] for t in told] == [True, False, True, False]
    lock.set_settings({"ways": ["pin"]})
    lock.lock()
    with pytest.raises(lock.LockError, match="isn't in use"):
        lock.unlock_hello()
    lock.unlock_pin("2580x")
    lock.set_settings({"ways": ["hello"]})
    lock.lock()
    with pytest.raises(lock.LockError, match="isn't in use"):
        lock.unlock_pin("2580x")


def test_wrong_pins_wait(pin, monkeypatch):
    lock.lock()
    for _ in range(4):
        with pytest.raises(lock.LockError):
            lock.unlock_pin("0000")
    with pytest.raises(lock.LockError, match="Wait 30"):
        lock.unlock_pin("0000")
    lock._TRIES.update(n=0, until=0.0)                                  # a restart
    with pytest.raises(lock.LockError, match="Too many"):
        lock.unlock_pin("2580x")
    real = time.time
    monkeypatch.setattr(lock.time, "time", lambda: real() + 40)
    lock.unlock_pin("2580x")
    assert not lock.is_locked() and schedule.get_setting("lock_tries") is None


def test_by_itself(pin, monkeypatch):
    w, idle = [False], [0.0]
    monkeypatch.setattr(lock, "windows_locked", lambda: w[0])
    monkeypatch.setattr(lock, "untouched", lambda: idle[0])
    was: dict = {}
    vault.create(PW, PW)
    lock.look(was)
    w[0] = True
    lock.look(was)
    assert not vault.is_open() and not lock.is_locked()                 # the vault always; the app only if you want
    w[0] = False
    lock.set_settings({"windows": True})
    lock.look(was)
    w[0] = True
    lock.look(was)
    assert lock.is_locked() and lock.state()["why"] == "Windows was locked"
    w[0] = False
    lock.look(was)                                                      # signed in to Windows: that counts, for two minutes
    monkeypatch.setenv("JARVIS_HELLO_TEST", "off")
    lock.unlock_hello()
    assert not lock.is_locked()
    lock.lock()
    with pytest.raises(lock.LockError, match="Windows\\+L"):
        lock.unlock_hello()                                             # a sign-in before the lock doesn't
    lock.unlock_pin("2580x")
    lock.set_settings({"windows": False, "idle": 5})
    idle[0] = 299
    lock.look(was)
    assert not lock.is_locked()
    idle[0] = 301
    lock.look(was)
    assert lock.is_locked()
    lock.unlock_pin("2580x")
    lock.set_settings({"windows": True, "idle": 0})
    was["at"] = time.time() - 60                                        # the PC slept
    lock.look(was)
    assert lock.is_locked() and lock.state()["why"] == "the PC slept"


def test_at_the_start(pin, monkeypatch):
    monkeypatch.setattr(lock, "_STARTED", True)
    lock.start()
    assert not lock.is_locked()
    lock.set_settings({"start": True})
    lock.start()
    assert lock.is_locked()


def test_real_windows_answers():
    assert lock.windows_locked() in (True, False, None) and lock.untouched() >= 0


# ---------------- a locked app ----------------
@pytest.fixture
def hub(pin, monkeypatch):
    from jarvis import hud
    h = hud.Hub()
    monkeypatch.setattr(hud, "HUB", h)
    yield h
    lock._STATE.update(locked=False)
    h.ringer.stop()


def test_locking_stops_and_closes(hub, monkeypatch):
    done = []
    monkeypatch.setattr(hub, "live_stop", lambda why="": done.append(("live", why)))
    monkeypatch.setattr(hub, "standby_halt", lambda: done.append("standby"))
    vault.create(PW, PW)
    slot = {"event": threading.Event(), "allow": True, "question": "?", "asked": time.time(), "kind": "lock"}
    hub.pending["x"] = slot
    lock.lock()
    assert ("live", "locked") in done and "standby" in done and not vault.is_open()
    assert slot["event"].is_set() and slot["allow"] is False
    assert not hub.standby_wanted()


def test_a_locked_window_is_told_almost_nothing(hub):
    import queue
    q = queue.Queue()
    hub.subscribers.append(q)
    lock.lock()
    hub.emit("user", keep=True, text="private words")
    hub.notify("Doctor at five", "reminder")
    hub.emit("ringing", rings=[{"id": 1, "label": "Take the pills"}])
    hub.emit("meeting_state", state={"title": "Salary talk", "seconds": 3})
    hub.emit("stats", secret="x")
    hub.submit("do something")
    hub.submit("news please", source="scheduled")
    hub.heard("open the app")
    lock.unlock_pin("2580x")
    hub.emit("notify", text="now")
    got = []
    while not q.empty():
        got.append(q.get())
    text = json.dumps(got)
    assert [e["type"] for e in got] == ["lock", "ringing", "meeting_state", "lock", "notify"]
    for word in ("private words", "Doctor", "pills", "Salary", "news please"):
        assert word not in text, word
    kept = json.dumps(hub.history)
    assert "Doctor at five" in kept and "Not done, because the app was locked: news please" in kept and "do something" not in kept
    assert hub.inbox.empty()


def test_voice_never_opens_it(hub):
    lock.lock()
    for words in ("unlock", "yes", "2580x", "open the app"):
        hub.heard(words)
    assert lock.is_locked()


def test_the_server_refuses_everything_else(hub, monkeypatch):
    from jarvis import hud
    lock.lock()
    got = []
    h = hud.Handler.__new__(hud.Handler)
    h._json = lambda d, status=200: got.append((status, d))
    h._host_ok, h._token_ok = lambda: True, lambda v: True
    h.headers = {"X-Jarvis-Token": "t", "Content-Length": "0"}
    for p in ("/api/info", "/api/profile", "/api/local", "/api/setup", "/api/mics", "/api/media/file?id=1", "/api/tts_stream?text=x", "/api/anything"):
        h.path = p
        h.do_GET()
        assert got[-1][0] == 423, p
    h.path = "/api/stats"
    h.do_GET()
    assert got[-1] == (200, {"locked": True, "meeting": None, "screen": None})
    for p in ("/api/send", "/api/settings", "/api/vault/unlock", "/api/vault/status", "/api/privacy/overview", "/api/time/load", "/api/lock/settings", "/api/lock/set_pin", "/api/lock/now", "/api/live", "/api/listen",
              "/api/confirm", "/api/history/clear", "/api/tts", "/api/transcribe", "/api/images/keep?x", "/api/vault/file?x", "/api/setup", "/api/reset", "/api/clock/load"):
        h.path = p
        h.do_POST()
        assert got[-1][0] == 423, p
    assert not any(x.startswith("/api/vault") or "settings" in x or "send" in x for x in hud.WHILE_LOCKED)
    for name in ("state", "hello", "pin"):
        assert f"/api/lock/{name}" in hud.WHILE_LOCKED


def test_timed_automations_wait(hub, monkeypatch):
    ran = []
    monkeypatch.setattr(hub.runner, "tick", lambda now: ran.append(1))
    lock.lock()
    hub._tick(datetime.now())
    assert not ran
    lock.unlock_pin("2580x")
    hub._tick(datetime.now())
    assert ran == [1]


def test_no_tool_can_open_it_or_change_it():
    for name in tools._HANDLERS:
        assert "unlock" not in name
    src = open(tools.__file__, encoding="utf-8").read()
    assert "lock.unlock" not in src and "vault.unlock" not in src and "vault.reveal" not in src and "vault.need" not in src

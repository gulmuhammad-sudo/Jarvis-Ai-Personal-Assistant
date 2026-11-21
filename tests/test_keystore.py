"""API keys: encrypted with Windows DPAPI, migrated safely out of plain-text .env."""
import os

import pytest

from jarvis import config, keystore

pytestmark = pytest.mark.skipif(not keystore.available(), reason="Windows DPAPI not available")

FAKE = "AIzaFAKE-test-key-0123456789abcdef"


def test_round_trip_and_file_is_not_plain_text(tmp_path):
    f = tmp_path / "keys.dat"
    keystore.save({"GEMINI_API_KEY": FAKE}, f)
    assert keystore.load(f) == {"GEMINI_API_KEY": FAKE}
    assert FAKE.encode() not in f.read_bytes()          # encrypted on disk


def test_save_merges_and_empty_value_removes(tmp_path):
    f = tmp_path / "keys.dat"
    keystore.save({"GEMINI_API_KEY": FAKE, "GROQ_API_KEY": "gsk_fake_1234567890abcd"}, f)
    keystore.save({"GROQ_API_KEY": ""}, f)
    assert keystore.load(f) == {"GEMINI_API_KEY": FAKE}


def test_unreadable_file_gives_nothing_not_a_crash(tmp_path):
    f = tmp_path / "keys.dat"
    f.write_bytes(b"not encrypted data")
    assert keystore.load(f) == {}


def test_is_secret():
    assert keystore.is_secret("GEMINI_API_KEY") and keystore.is_secret("ANTHROPIC_AUTH_TOKEN")
    assert not keystore.is_secret("JARVIS_PROVIDERS") and not keystore.is_secret("JARVIS_USER_NAME")


def test_migration_moves_only_keys_and_keeps_other_settings(tmp_path):
    env, f = tmp_path / ".env", tmp_path / "keys.dat"
    env.write_text("# my settings\nJARVIS_USER_NAME=Sir\nGEMINI_API_KEY=" + FAKE + "\nGROQ_API_KEY=\n", encoding="utf-8")
    moved = keystore.migrate_env_file(env, f)
    assert moved == ["GEMINI_API_KEY"]                   # the empty GROQ line isn't a key
    text = env.read_text(encoding="utf-8")
    assert FAKE not in text and "JARVIS_USER_NAME=Sir" in text and "# my settings" in text
    assert keystore.load(f) == {"GEMINI_API_KEY": FAKE}
    assert keystore.migrate_env_file(env, f) == []       # second time: nothing to do


def test_migration_leaves_env_alone_if_encryption_fails(tmp_path, monkeypatch):
    env, f = tmp_path / ".env", tmp_path / "keys.dat"
    original = "GEMINI_API_KEY=" + FAKE + "\n"
    env.write_text(original, encoding="utf-8")
    monkeypatch.setattr(keystore, "_protect", lambda data: (_ for _ in ()).throw(OSError("no DPAPI")))
    assert keystore.migrate_env_file(env, f) == []
    assert env.read_text(encoding="utf-8") == original   # untouched


def test_save_env_keys_encrypts_keys_and_keeps_settings_in_env(tmp_path, monkeypatch):
    monkeypatch.setattr(keystore, "default_file", lambda: tmp_path / "keys.dat")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config.save_env_keys({"OPENROUTER_API_KEY": "sk-or-v1-fakefakefakefake", "JARVIS_THEME": "light"})
    assert keystore.load(tmp_path / "keys.dat") == {"OPENROUTER_API_KEY": "sk-or-v1-fakefakefakefake"}
    env_text = config.ENV_FILE.read_text(encoding="utf-8")
    assert "JARVIS_THEME=light" in env_text and "sk-or-v1" not in env_text
    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-fakefakefakefake"
    monkeypatch.delenv("OPENROUTER_API_KEY")


def test_test_runs_are_isolated():
    assert config.ISOLATED and "pa-tests-" in str(config.DATA_DIR)

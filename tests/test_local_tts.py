"""Voices on this PC: text -> sounds, which voice is used, safe downloads, settings, and (if voices are available
locally) a real spoken sentence. Never downloads a real voice."""
import io
import os
import tarfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from jarvis import local_tts, providers, schedule, tts


def _has_espeak():
    try:
        import espeakng_loader  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _has_espeak(), reason="espeakng-loader not installed")
def test_text_becomes_ipa_with_pauses():
    ph = local_tts.phonemes("Hello there. How are you?", "en-gb-x-rp")
    assert "h" in ph and "." in ph and ph.endswith("?") and any(c in ph for c in "əˈ")
    ur = local_tts.phonemes("جی، آپ کیسے ہیں؟", "ur")
    assert "," in ur and ur.endswith("?")


@pytest.fixture
def voices(tmp_path, monkeypatch):
    monkeypatch.setattr(local_tts, "voices_dir", lambda: tmp_path / "voices")
    return tmp_path / "voices"


def _fake_voice(root: Path, voice: str):
    d = root / local_tts.VOICES[voice][2]
    d.mkdir(parents=True)
    (d / "x.onnx").write_bytes(b"model")
    (d / "tokens.txt").write_text("a 1\n")


def test_pick_by_script_language_and_setting(voices):
    for v in ("alan", "jenny", "fasih"):
        _fake_voice(voices, v)
    assert local_tts.pick("Good morning") in ("alan", "jenny")
    assert local_tts.pick("صبح بخیر") == "fasih" and local_tts.pick("subah bakhair", "ur") == "fasih"
    assert local_tts.pick("नमस्ते") is None                                   # no Hindi voice downloaded
    schedule.set_setting("local_voice_en", "jenny")
    assert local_tts.pick("Good morning") == "jenny"
    schedule.set_setting("local_voice_en", None)


def _tar(members: dict) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeRelease(BaseHTTPRequestHandler):
    body = b""

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)


@pytest.fixture
def release(voices, monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeRelease)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(local_tts, "URL", f"http://127.0.0.1:{server.server_address[1]}/{{file}}.tar.bz2")
    yield voices
    server.shutdown()


def test_download_unpacks_a_voice(release):
    FakeRelease.body = _tar({"vits-x/en.onnx": b"m", "vits-x/tokens.txt": b"t", "vits-x/en.onnx.json": b"{}"})
    seen = []
    folder = local_tts.download("alan", seen.append)
    assert (folder / "en.onnx").exists() and seen[-1] == 1.0 and local_tts.installed() == ["alan"]
    assert not list(release.glob("*.part")) and not list(release.glob("*.unpacking"))


def test_download_refuses_files_outside_the_folder(release, tmp_path):
    FakeRelease.body = _tar({"../../evil.txt": b"x", "vits-x/en.onnx": b"m"})
    with pytest.raises(Exception):
        local_tts.download("fasih")
    assert not (tmp_path.parent / "evil.txt").exists() and local_tts.installed() == []


def test_download_without_a_model_is_rejected(release):
    FakeRelease.body = _tar({"vits-x/readme.txt": b"nothing"})
    with pytest.raises(OSError):
        local_tts.download("jenny")
    assert local_tts.installed() == []


def test_only_known_voices(release):
    with pytest.raises(ValueError):
        local_tts.download("../evil")


@pytest.fixture
def modes(voices, monkeypatch):
    _fake_voice(voices, "alan")
    monkeypatch.setattr(local_tts, "available", lambda: True)
    monkeypatch.setattr(providers, "online", lambda timeout=1.5: True)
    yield monkeypatch
    schedule.set_setting("tts_engine", "auto")


def test_which_voice_source_is_used(modes):
    schedule.set_setting("tts_engine", "auto")
    assert tts.local_voice("Hello") is None                                    # online: Microsoft voices
    assert tts.local_voice("Hello", after_failure=True) == "alan"              # ...unless they failed
    modes.setattr(providers, "online", lambda timeout=1.5: False)
    assert tts.local_voice("Hello") == "alan"                                  # offline: this PC
    schedule.set_setting("tts_engine", "online")
    assert tts.local_voice("Hello") is None
    schedule.set_setting("tts_engine", "local")
    modes.setattr(providers, "online", lambda timeout=1.5: True)
    assert tts.local_voice("Hello") == "alan" and tts.local_voice("سلام") is None   # no Urdu voice yet


def test_speed_and_pitch_settings(monkeypatch):
    assert tts.speed_pct() == tts._num(tts.RATE) and tts.pitch_hz() == tts._num(tts.PITCH)
    schedule.set_setting("voice_speed", 80)
    schedule.set_setting("voice_pitch", -7)
    try:
        assert tts.speed_pct() == 50 and tts.pitch_hz() == -7                  # clamped to -50..50
        assert tts._resolve("hi", "en-GB-RyanNeural", "en")[1:] == ("+50%", "-7Hz")
    finally:
        schedule.set_setting("voice_speed", None)
        schedule.set_setting("voice_pitch", None)


VOICE_DIR = os.environ.get("PA_TEST_TTS_DIR")     # a voices folder with Alan, to hear the real thing


@pytest.mark.skipif(not (VOICE_DIR and Path(VOICE_DIR, local_tts.VOICES["alan"][2]).exists() and local_tts.available()),
                    reason="set PA_TEST_TTS_DIR to a voices folder with Alan to run a real voice")
def test_real_voice_speaks(monkeypatch):
    monkeypatch.setattr(local_tts, "voices_dir", lambda: Path(VOICE_DIR))
    slow = local_tts.synthesize("Testing the voice on this PC.", "alan", 0.8)
    fast = local_tts.synthesize("Testing the voice on this PC.", "alan", 1.3)
    with wave.open(io.BytesIO(slow)) as w:
        assert w.getframerate() > 8000 and w.getnframes() > 8000
    assert len(slow) > len(fast)

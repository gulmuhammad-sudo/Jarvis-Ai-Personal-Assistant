"""Speech-to-text on this PC: audio conversion, model download, which engine is used, and (if a model file is
available locally) a real transcription. Never downloads a real model and never opens the microphone."""
import io
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import numpy as np
import pytest

from jarvis import local_stt, providers, schedule, stt


def _wav(x: np.ndarray, rate: int, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def test_wav_becomes_16k_mono_float():
    t = np.arange(44100) / 44100
    tone = np.sin(2 * np.pi * 440 * t) * 0.5
    stereo = np.repeat(tone, 2)                                    # interleaved L/R
    pcm = local_stt.wav_to_pcm(_wav(stereo, 44100, channels=2))
    assert pcm.dtype == np.float32 and abs(len(pcm) - 16000) <= 2 and 0.3 < np.abs(pcm).max() < 0.6


class FakeHF(BaseHTTPRequestHandler):
    body = os.urandom(300_000)
    cut = False

    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body[: len(self.body) // 2] if FakeHF.cut else self.body)


@pytest.fixture
def hf(monkeypatch, tmp_path):
    server = HTTPServer(("127.0.0.1", 0), FakeHF)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(local_stt, "URL", f"http://127.0.0.1:{server.server_address[1]}/ggml-{{name}}.bin")
    monkeypatch.setattr(local_stt, "models_dir", lambda: tmp_path / "models")
    FakeHF.cut = False
    yield tmp_path / "models"
    server.shutdown()


def test_download_with_progress(hf):
    seen = []
    p = local_stt.download("base-q5_1", seen.append)
    assert p.read_bytes() == FakeHF.body and seen[-1] == 1.0
    assert local_stt.installed() == ["base-q5_1"] and local_stt.chosen() == "base-q5_1"


def test_cut_off_download_leaves_nothing_behind(hf):
    FakeHF.cut = True
    with pytest.raises(OSError):
        local_stt.download("small-q5_1")
    assert not list(hf.glob("*.bin")) and not list(hf.glob("*.part"))


def test_only_known_models_can_be_downloaded(hf):
    with pytest.raises(ValueError):
        local_stt.download("../../evil")


@pytest.fixture
def engines_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_fake_for_tests_0000000000")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(local_stt, "ready", lambda: True)
    monkeypatch.setattr(providers, "online", lambda timeout=1.5: True)
    yield monkeypatch
    schedule.set_setting("stt_engine", "auto")


def test_engine_order_by_setting(engines_env):
    schedule.set_setting("stt_engine", "auto")
    assert stt.engines() == ["whisper", "local"]                   # online: cloud first, this PC as backup
    engines_env.setattr(providers, "online", lambda timeout=1.5: False)
    assert stt.engines() == ["local"]                              # offline: straight to this PC
    schedule.set_setting("stt_engine", "local")
    assert stt.engines() == ["local"]
    schedule.set_setting("stt_engine", "cloud")
    assert stt.engines() == ["whisper", "local"]


def test_local_choice_without_a_model_keeps_cloud_working(engines_env):
    engines_env.setattr(local_stt, "ready", lambda: False)
    schedule.set_setting("stt_engine", "local")
    assert stt.engines() == ["whisper"]


def test_cloud_failure_falls_back_to_this_pc(engines_env):
    schedule.set_setting("stt_engine", "cloud")
    engines_env.setattr(stt, "_whisper", lambda wav, m: (_ for _ in ()).throw(ConnectionError("offline")))
    engines_env.setattr(stt, "_local", lambda wav, m: "hello from this pc")
    assert stt.transcribe(b"RIFF") == ("hello from this pc", "local")


MODEL_DIR = os.environ.get("PA_TEST_STT_DIR")          # a folder with ggml-base-q5_1.bin, to test the real thing


@pytest.mark.skipif(not (MODEL_DIR and (Path(MODEL_DIR) / "ggml-base-q5_1.bin").exists() and local_stt.available()),
                    reason="set PA_TEST_STT_DIR to a folder with ggml-base-q5_1.bin to run a real transcription")
def test_real_transcription_of_a_spoken_sentence(monkeypatch, tmp_path):
    import subprocess
    monkeypatch.setattr(local_stt, "models_dir", lambda: Path(MODEL_DIR))
    wav = tmp_path / "say.wav"
    ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
          f"$s.SetOutputToWaveFile('{wav}'); $s.Speak('Please set a timer for ten minutes.'); $s.Dispose()")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True,
                   creationflags=0x08000000)
    text = local_stt.transcribe(local_stt.wav_to_pcm(wav.read_bytes()), "en").lower()
    assert "timer" in text and ("10" in text or "ten" in text)

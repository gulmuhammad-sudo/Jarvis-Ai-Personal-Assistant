"""Pakistani voices: online (Uzma and her ways of speaking), on this PC (Aegis, from Piper's own files) and Live calls."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from jarvis import brain, languages, local_tts, schedule, tts

UZMA = [v for v, _ in tts.VOICES if "Uzma" in v]


@pytest.fixture
def setting():
    keys = []

    def put(key, value):
        keys.append(key)
        schedule.set_setting(key, value)
    yield put
    for k in keys:
        schedule.set_setting(k, None)


# ---------------- online ----------------
def test_pakistani_women_are_offered_everywhere():
    assert len(UZMA) == 4 and len({v for v, _ in tts.VOICES}) == len(tts.VOICES)
    assert all("Pakistani" in n and "(female)" in n for v, n in tts.VOICES if v in UZMA)
    for f in ("jarvis/hud.py", "packaging/setup_app.py", "jarvis/hud.html"):
        assert 'startswith("ur-")' not in (Path(__file__).parent.parent / f).read_text(encoding="utf-8") or f.endswith("hud.html")
    page = (Path(__file__).parent.parent / "jarvis/hud.html").read_text(encoding="utf-8")
    assert 'filter(v => !v.id.startsWith("ur-"))' not in page


@pytest.mark.parametrize("text", ["Good morning", "Aaj mausam acha hai", "آج موسم اچھا ہے"])
@pytest.mark.parametrize("lang", ["en", "ur", None])
def test_uzma_reads_urdu_roman_urdu_and_english(text, lang):
    for v in UZMA:
        assert tts._resolve(text, v, lang)[0] == "ur-PK-UzmaNeural"


def test_the_ways_of_speaking_differ_and_are_valid():
    import re
    got = [tts._resolve("سلام", v, "ur") for v in UZMA]
    assert len(set(got)) == 4 and {g[0] for g in got} == {"ur-PK-UzmaNeural"}
    assert all(re.fullmatch(r"[+-]\d+%", r) and re.fullmatch(r"[+-]\d+Hz", p) for _, r, p in got)
    assert dict(zip(UZMA, got))["ur-PK-UzmaNeural"][2] == "+0Hz"
    assert set(tts.STYLES) == {v.split("@")[1] for v in UZMA if "@" in v}


def test_speed_and_pitch_settings_still_count(setting):
    setting("voice_speed", 50)
    setting("voice_pitch", 5)
    assert tts._resolve("سلام", "ur-PK-UzmaNeural@lively", "ur") == ("ur-PK-UzmaNeural", "+56%", "+21Hz")
    setting("voice_speed", -50)
    assert tts._resolve("سلام", "ur-PK-UzmaNeural@soft", "ur")[1] == "-50%"
    assert tts._resolve("سلام", "en-GB-SoniaNeural", "ur") == ("ur-PK-UzmaNeural", "-50%", "+0Hz")


def test_urdu_letters_follow_the_chosen_voice():
    assert tts._resolve("سلام", "en-GB-SoniaNeural", "en")[0] == "ur-PK-UzmaNeural"
    assert tts._resolve("سلام", "en-GB-RyanNeural", "en")[0] == "ur-PK-AsadNeural"


def test_another_language_gets_its_own_voice():
    assert tts._resolve("Bonjour", "ur-PK-UzmaNeural@soft", "fr")[0] == "fr-FR-DeniseNeural"
    assert tts._resolve("Bonjour", "ur-PK-AsadNeural", "fr")[0] == "fr-FR-HenriNeural"


def test_unknown_styles_and_voices_become_the_default():
    for bad in ("ur-PK-UzmaNeural@evil", "ur-PK-UzmaNeural@", "x@soft", "@", None, ""):
        assert tts._resolve("Hello", bad, "en")[0] == tts.DEFAULT_VOICE


# ---------------- how it speaks of itself ----------------
def test_the_instructions_follow_the_voice(setting):
    setting("reading_voice", "en-GB-RyanNeural")
    assert not tts.reading_female() and languages.WOMAN not in brain.system_prompt()
    for v in UZMA + ["en-GB-SoniaNeural"]:
        setting("reading_voice", v)
        assert tts.reading_female() and languages.WOMAN in brain.system_prompt()
    assert languages.WOMAN not in brain.system_prompt(live=True)      # a call goes by the call's voice
    setting("reading_voice", None)
    assert not tts.reading_female()


# ---------------- Live calls ----------------
def test_live_voices(setting):
    from jarvis import live
    pk = [v for v in live.VOICES if "(Pakistani)" in v]
    assert len(pk) == 6 and all(languages.live_female(v) for v in pk)
    for v in live.VOICES:
        name = languages.live_name(v)
        assert name.isalpha() and ("(Pakistani)" in v) == ("Pakistani accent" in languages.accent(v))
        assert (languages.WOMAN in languages.accent(v)) == languages.live_female(v)
        assert "{" not in live.LIVE_NOTE.format(user="Sir", language="x", accent=languages.accent(v))
    assert languages.live_female("Kore") and not languages.live_female("Charon") and not languages.live_female("nope")
    setting("live_voice", "Leda (Pakistani)")
    assert live.voice() == "Leda (Pakistani)"
    setting("live_voice", "Leda (Martian)")
    assert live.voice() == live.DEFAULT_VOICE


def test_google_gets_its_own_voice_name(monkeypatch):
    from jarvis import live
    if live.genai is None:
        pytest.skip("google-genai isn't installed")
    s = live.LiveSession.__new__(live.LiveSession)
    s.voice, s.history, s.model = "Leda (Pakistani)", [], "m"
    c = s._config(None)
    assert c.speech_config.voice_config.prebuilt_voice_config.voice_name == "Leda"
    assert "Pakistani accent" in c.system_instruction and "British accent, like" not in c.system_instruction


# ---------------- on this PC ----------------
META = {"audio": {"sample_rate": 22050}, "espeak": {"voice": "ur"}, "num_speakers": 1,
        "phoneme_id_map": {"_": [0], " ": [3], "a": [14], "ʈ": [90], "aɪ": [161]}}


@pytest.fixture
def piper(tmp_path, monkeypatch):
    files = {"/m/v.onnx": b"\x08\x08MODEL" * 50, "/m/v.onnx.json": json.dumps(META).encode()}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = files.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("Content-Length", str(len(body or b"")))
            self.end_headers()
            self.wfile.write(body or b"")
    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(local_tts, "voices_dir", lambda: tmp_path / "voices")
    monkeypatch.setattr(local_tts, "PIPER_URL", f"http://127.0.0.1:{server.server_address[1]}/{{path}}")
    monkeypatch.setattr(local_tts, "PIPER", {"aegis": tuple((p[1:], hashlib.sha256(b).hexdigest()) for p, b in files.items())})
    yield files
    server.shutdown()


def test_download_checks_and_completes_the_voice(piper):
    seen = []
    folder = local_tts.download("aegis", seen.append)
    assert local_tts.installed() == ["aegis"] and seen[-1] == 1.0
    assert (folder / "tokens.txt").read_bytes() == "_ 0\n  3\na 14\nʈ 90\n".encode()          # no "aɪ": sherpa-onnx ends the program at it
    model = (folder / "v.onnx").read_bytes()
    assert model.startswith(piper["/m/v.onnx"]) and all(x in model for x in (b"sample_rate", b"22050", b"has_espeak", b"piper"))
    assert [x.name for x in folder.parent.iterdir()] == [folder.name]


@pytest.mark.parametrize("name", ["/m/v.onnx", "/m/v.onnx.json"])
def test_a_changed_or_cut_off_file_is_refused(piper, name):
    piper[name] = piper[name][:-1]
    with pytest.raises(OSError, match="isn't the right file"):
        local_tts.download("aegis")
    assert local_tts.installed() == [] and list(local_tts.voices_dir().iterdir()) == []


def test_a_failed_download_keeps_the_voice_you_have(piper):
    local_tts.download("aegis")
    del piper["/m/v.onnx.json"]
    with pytest.raises(OSError):
        local_tts.download("aegis")
    assert local_tts.installed() == ["aegis"]


def test_the_real_list_is_pinned():
    for (path, sha), (path2, sha2) in local_tts.PIPER.values():
        assert path.endswith(".onnx") and path2 == path + ".json" and len(sha) == len(sha2) == 64
    assert "/resolve/main/" not in local_tts.PIPER_URL and local_tts.PIPER_URL.startswith("https://huggingface.co/rhasspy/piper-voices/resolve/")


def test_notes_at_the_end_of_a_model():
    b = local_tts.onnx_notes({"k": "v", "long": "x" * 300})
    assert b.startswith(bytes([14 << 3 | 2, 6, 1 << 3 | 2, 1]) + b"k" + bytes([2 << 3 | 2, 1]) + b"v")
    assert b.endswith(bytes([2 << 3 | 2, 0xAC, 0x02]) + b"x" * 300)


def test_the_voice_on_this_pc_is_like_the_online_one(tmp_path, monkeypatch, setting):
    monkeypatch.setattr(local_tts, "voices_dir", lambda: tmp_path)
    for v in ("alan", "jenny", "fasih", "aegis"):
        (tmp_path / local_tts.VOICES[v][2]).mkdir()
        (tmp_path / local_tts.VOICES[v][2] / "x.onnx").write_bytes(b"m")
    setting("reading_voice", "en-GB-RyanNeural")
    assert local_tts.pick("سلام") == "fasih" and local_tts.pick("Hello") == "alan"
    setting("reading_voice", "ur-PK-UzmaNeural@soft")
    assert local_tts.pick("سلام") == "aegis" and local_tts.pick("salam", "ur") == "aegis" and local_tts.pick("Hello") == "jenny"
    setting("local_voice_ur", "fasih")                                  # your own choice wins
    assert local_tts.pick("سلام") == "fasih"
    import shutil
    shutil.rmtree(tmp_path / local_tts.VOICES["aegis"][2])
    setting("local_voice_ur", None)
    assert local_tts.pick("سلام") == "fasih"                            # a man's voice is better than none



def test_a_headset_plugged_in_doesn_t_make_the_mic_another_device(monkeypatch):
    """PortAudio numbers its devices anew after a rescan: the mic kept from before must be found by its name, not its old number
    (once it pointed at a WDM-KS device that can't be opened, and hands-free didn't start)."""
    from jarvis import recorder
    apis = [{"name": "MME"}, {"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]
    before = [{"name": "Microphone Array (AMD Audio Device)", "max_input_channels": 2, "hostapi": 1, "default_samplerate": 48000}]
    after = [{"name": "Headset (Airbud 690 Ion)", "max_input_channels": 1, "hostapi": 1, "default_samplerate": 16000},
             {"name": "Microphone Array (AMD Audio Device)", "max_input_channels": 2, "hostapi": 2, "default_samplerate": 48000},
             {"name": "Microphone Array (AMD Audio Device)", "max_input_channels": 2, "hostapi": 1, "default_samplerate": 48000}]
    now = {"list": before}
    monkeypatch.setattr(recorder.sd, "query_hostapis", lambda: apis)
    monkeypatch.setattr(recorder.sd, "query_devices", lambda *a, **k: now["list"])
    monkeypatch.setattr(recorder, "_chosen", {"index": 0, "name": "Microphone Array (AMD Audio Device)", "api": "Windows WASAPI", "rate": 48000})
    now["list"] = after                                                           # the rescan after the headset came
    dev = recorder.choose_mic()
    assert dev["index"] == 2 and dev["api"] == "Windows WASAPI" and recorder._chosen["index"] == 2

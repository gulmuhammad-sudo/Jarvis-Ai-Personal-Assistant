"""Small building blocks: safe file saving, names, memory, languages, wake word, Urdu text, error messages."""
import os
import socket

import numpy as np
import pytest

from jarvis import aec, config, memory, schedule, urdu, wake


def test_write_json_retries_when_windows_locks_the_file(tmp_path, monkeypatch):
    target = tmp_path / "x.json"
    real, calls = os.replace, {"n": 0}

    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("locked")
        return real(a, b)
    monkeypatch.setattr(os, "replace", flaky)
    config.write_json(target, {"a": 1})
    assert config.read_json(target, None) == {"a": 1} and calls["n"] == 3


def test_assistant_name_rules():
    assert schedule.clean_name("  Maya ") == "Maya"
    assert schedule.clean_name("مایا") == "مایا"
    with pytest.raises(ValueError):
        schedule.clean_name("!!")
    schedule.set_agent_name("Nova")
    assert schedule.agent_name() == "Nova"


def test_memory_remember_edit_forget():
    memory.remember("likes green tea")
    fact = next(f for f in memory.all_facts() if "green tea" in f["fact"])
    memory.edit(fact["id"], "likes green tea without sugar")
    assert any("without sugar" in f["fact"] for f in memory.all_facts())
    memory.forget(fact["id"])
    assert not any("green tea" in f["fact"] for f in memory.all_facts())


def test_wake_word_by_name():
    hit, rest = wake.match("Maya, time kya hai?", "Maya")
    assert hit and "time" in rest.lower()
    assert not wake.match("the weather is nice today", "Maya")[0]


def test_hindi_letters_become_urdu_script():
    assert urdu.from_devanagari("नहीं") == "نہیں"
    assert urdu.from_devanagari("hello") == "hello"
    assert urdu.mostly_latin("Main theek hoon") and not urdu.mostly_latin("میں ٹھیک ہوں")
    assert urdu.has_other_script("میں") and not urdu.has_other_script("Main")


def test_live_errors_are_explained_plainly():
    from jarvis.live import _friendly, _is_network

    class APIError(Exception):
        pass
    dropped = APIError("1006 None. abnormal closure [internal]")
    assert _is_network(dropped) and "dropped" in _friendly(dropped)
    offline = socket.gaierror(11001, "getaddrinfo failed")
    assert "no internet" in _friendly(offline)
    bad_key = APIError("1008 None. API key not valid")
    assert not _is_network(bad_key) and "key" in _friendly(bad_key)
    assert "1006" not in _friendly(dropped)              # never the raw code


def test_echo_canceller_never_makes_the_sound_louder():
    rng = np.random.default_rng(1)
    a = aec.EchoCanceller(key="")
    a.W = (rng.standard_normal(a.W.shape) + 1j * rng.standard_normal(a.W.shape)) * 3   # a badly wrong filter
    ref = rng.standard_normal(16000 * 2) * 0.2
    mic = np.concatenate([np.zeros(160), ref[:-160]]) * 0.3
    outs = []
    for i in range(0, ref.size - 640, 640):
        a.push_ref(ref[i:i + 640], 1000 + i / 16000)
        outs.append(a.process(mic[i:i + 640], 1000 + i / 16000))
    out = np.concatenate(outs)                   # (output comes in 256-sample blocks, in order from the start)
    for j in range(0, out.size, 256):            # every block: never more than the mic heard
        o, m = out[j:j + 256], mic[j:j + 256]
        assert float(np.dot(o, o)) <= float(np.dot(m, m)) * 1.001 + 1e-6


def test_echo_canceller_passes_your_voice_through_when_nothing_plays():
    a = aec.EchoCanceller(key="")
    voice = np.sin(np.arange(16000) / 8) * 0.1
    out = np.concatenate([a.process(voice[i:i + 640], 5 + i / 16000) for i in range(0, 16000, 640)])
    assert np.allclose(out, voice[:out.size], atol=1e-6)

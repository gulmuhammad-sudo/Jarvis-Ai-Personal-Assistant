"""Things that only go wrong in the installed (windowed) exe, reproduced in tests."""
import sys

from jarvis import local_stt


def test_no_console_does_not_break_local_speech(monkeypatch):
    """The installed app has sys.stdout/stderr = None; pywhispercpp flushes them (1.12.0 exe check found this)."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    local_stt._consoles()
    assert sys.stdout is not None and sys.stderr is not None
    sys.stdout.write("x")
    sys.stdout.flush()

"""Voice I/O using what Windows already ships with.

- Speaking: pyttsx3 (SAPI5) if available, otherwise PowerShell System.Speech.
- Listening: Windows' built-in speech recognizer (System.Speech) via PowerShell,
  so no PyAudio / microphone libraries are needed.
"""
import queue
import re
import subprocess
import threading

from .config import VOICE_RATE

_LISTEN_PS = r"""
Add-Type -AssemblyName System.Speech
$r = New-Object System.Speech.Recognition.SpeechRecognitionEngine
$r.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar))
$r.SetInputToDefaultAudioDevice()
$r.InitialSilenceTimeout = [TimeSpan]::FromSeconds(__TIMEOUT__)
$r.EndSilenceTimeout = [TimeSpan]::FromSeconds(0.8)
$res = $r.Recognize()
if ($res) { [Console]::Out.Write($res.Text) }
"""


def _clean_for_speech(text: str) -> str:
    text = re.sub(r"```.*?```", " (code shown on screen) ", text, flags=re.S)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[*_#`>|]", "", text)
    return text.strip()


class Voice:
    def __init__(self) -> None:
        self._q: "queue.Queue[str | None]" = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    # ---- speaking: one long-lived Windows speech process, fed a line at a time ----
    # (pyttsx3 was dropped: on a background thread it often goes silent after the first reply.)
    _SPEAKER_PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo } |
     Where-Object { $_.Culture.Name -eq 'en-GB' -and $_.Gender -eq 'Male' } | Select-Object -First 1
if (-not $v) { $v = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo } | Where-Object { $_.Gender -eq 'Male' } | Select-Object -First 1 }
if ($v) { $s.SelectVoice($v.Name) }
$s.Rate = __RATE__
while ($null -ne ($line = [Console]::In.ReadLine())) {
    if ($line.Trim()) { $s.Speak($line) }
    [Console]::Out.WriteLine('done'); [Console]::Out.Flush()
}
"""

    def _start_speaker(self):
        rate = max(-10, min(10, round((VOICE_RATE - 175) / 15)))  # words/min -> SAPI -10..10
        return subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", self._SPEAKER_PS.replace("__RATE__", str(rate))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def _worker(self) -> None:
        proc = None
        while True:
            text = self._q.get()
            if text is None:
                break
            try:
                if proc is None or proc.poll() is not None:
                    proc = self._start_speaker()
                proc.stdin.write(text.replace("\n", " ") + "\n")
                proc.stdin.flush()
                proc.stdout.readline()  # wait until this line has been spoken
            except Exception:
                proc = None
                self._ps_say(text)
            finally:
                self._q.task_done()

    @staticmethod
    def _ps_say(text: str) -> None:
        safe = text.replace("'", "''")
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Add-Type -AssemblyName System.Speech; "
             "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
             f"$s.Speak('{safe}')"],
            capture_output=True, check=False)

    def say(self, text: str, wait: bool = False) -> None:
        text = _clean_for_speech(text)
        if text:
            self._q.put(text)
            if wait:
                self._q.join()

    def wait(self) -> None:
        self._q.join()

    @property
    def speaking(self) -> bool:
        return self._q.unfinished_tasks > 0

    # ---- listening ----
    @staticmethod
    def listen(timeout_s: int = 8) -> str:
        """Record one utterance from the default mic and return the text ('' if none)."""
        script = _LISTEN_PS.replace("__TIMEOUT__", str(timeout_s))
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=timeout_s + 30, check=False)
            return out.stdout.strip()
        except subprocess.TimeoutExpired:
            return ""

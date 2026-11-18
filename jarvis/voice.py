"""Fallback listening with Windows' built-in speech recognizer (System.Speech via PowerShell).

Only used when there is no Groq or Gemini key for Whisper; it is less accurate but needs nothing installed.
"""
import subprocess

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


def listen(timeout_s: int = 8) -> str:
    """Record one utterance from the default mic and return the text ('' if none)."""
    script = _LISTEN_PS.replace("__TIMEOUT__", str(timeout_s))
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=timeout_s + 30, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip()
    except subprocess.TimeoutExpired:
        return ""

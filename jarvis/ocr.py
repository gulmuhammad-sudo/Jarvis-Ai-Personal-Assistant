"""Read text from the screen, a window or a picture with Windows' own OCR (Windows.Media.Ocr): free, offline,
nothing leaves the PC. It reads the languages installed in Windows (Settings > Time & language > Language).
Windows PowerShell 5.1 can call the WinRT OCR engine, so no extra package is needed.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}
MAX_CHARS = 12000

_OCR_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) { $t = $asTask.MakeGenericMethod($type).Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync('__PATH__')) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = $null
if ('__LANG__') { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('__LANG__')) }
if (-not $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if (-not $engine) { Write-Output '__NO_ENGINE__'; exit }
$max = [Windows.Media.Ocr.OcrEngine]::MaxImageDimension
if ($bitmap.PixelWidth -gt $max -or $bitmap.PixelHeight -gt $max) { Write-Output "__TOO_BIG__ $max"; exit }
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) { Write-Output $line.Text }
$stream.Dispose()
"""

_CAPTURE_PS = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$l, $t, $w, $h = __RECT__
$bmp = New-Object System.Drawing.Bitmap $w, $h
[System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($l, $t, 0, 0, $bmp.Size)
$bmp.Save('__PATH__', [System.Drawing.Imaging.ImageFormat]::Png)
"""


def _q(path) -> str:
    return str(path).replace("'", "''")


def _ps(script: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def read_image(path, language: str = "") -> str:
    """The text in a picture, line by line ('' when there is none). Raises ValueError with a message."""
    p = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()
    if not p.is_file():
        raise ValueError(f"There's no picture at {p}.")
    if p.suffix.lower() not in IMAGE_TYPES:
        raise ValueError(f"I can read text from pictures ({', '.join(sorted(IMAGE_TYPES))}), not {p.suffix or 'that file'}.")
    lang = language if language and all(ch.isalnum() or ch == "-" for ch in language) else ""
    r = _ps(_OCR_PS.replace("__PATH__", _q(p)).replace("__LANG__", lang))
    out = (r.stdout or "").strip()
    if "__NO_ENGINE__" in out:
        raise ValueError("Windows has no text-recognition language installed (Settings › Time & language › Language).")
    if out.startswith("__TOO_BIG__"):
        raise ValueError(f"That picture is too big for Windows OCR (max {out.split()[-1]} pixels a side).")
    if r.returncode != 0 and not out:
        raise ValueError("Windows OCR failed: " + ((r.stderr or "").strip().splitlines() or ["unknown error"])[-1][:200])
    return out[:MAX_CHARS]


def capture(rect: tuple[int, int, int, int] | None = None) -> Path:
    """A picture of the whole screen (all monitors) or of rect (left, top, right, bottom), in a temp file."""
    path = Path(tempfile.gettempdir()) / f"pa-ocr-{os.getpid()}-{os.urandom(3).hex()}.png"
    if rect:
        l, t, r, b = rect
        spec = f"{l}, {t}, {max(1, r - l)}, {max(1, b - t)}"
    else:
        spec = ("([System.Windows.Forms.SystemInformation]::VirtualScreen.Left), ([System.Windows.Forms.SystemInformation]::VirtualScreen.Top), "
                "([System.Windows.Forms.SystemInformation]::VirtualScreen.Width), ([System.Windows.Forms.SystemInformation]::VirtualScreen.Height)")
    script = _CAPTURE_PS.replace("__RECT__", spec).replace("__PATH__", _q(path))
    # PowerShell must see real pixels on scaled displays
    _ps("Add-Type -Namespace W -Name D -MemberDefinition '[DllImport(\"user32.dll\")] public static extern bool SetProcessDPIAware();'; "
        "[W.D]::SetProcessDPIAware() | Out-Null;" + script)
    if not path.exists():
        raise ValueError("Couldn't take the picture of the screen.")
    return path


def read_screen(rect=None, language: str = "") -> str:
    path = capture(rect)
    try:
        return read_image(path, language)
    finally:
        try:
            path.unlink()
        except OSError:
            pass

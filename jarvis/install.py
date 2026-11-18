"""Creates the Jarvis app icon and the Desktop + Start Menu shortcuts.

Run once ("Personal Assistant.bat" does it automatically):  python run.py --install
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .config import ROOT

ICON = ROOT / "assets" / "jarvis.ico"


def make_icon() -> Path:
    """Draws the arc-reactor style Jarvis icon (multi-size .ico)."""
    from PIL import Image, ImageDraw, ImageFilter
    ICON.parent.mkdir(exist_ok=True)
    S = 512
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 8, S - 8, S - 8), fill=(6, 12, 20, 255))                      # dark disc
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((150, 150, S - 150, S - 150), fill=(92, 207, 255, 200))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(40)))
    d = ImageDraw.Draw(img)
    cyan = (92, 207, 255, 255)
    d.ellipse((40, 40, S - 40, S - 40), outline=(92, 207, 255, 110), width=6)      # outer thin ring
    for i in range(10):                                                          # segmented ring
        start = i * 36 + 4
        d.arc((80, 80, S - 80, S - 80), start, start + 26, fill=cyan, width=28)
    d.ellipse((170, 170, S - 170, S - 170), outline=cyan, width=10)              # inner ring
    d.ellipse((205, 205, S - 205, S - 205), fill=(235, 250, 255, 255))           # core
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ICON, sizes=sizes)
    return ICON


def _shortcut(lnk: Path, target: Path, args: str, workdir: Path, icon: Path, desc: str) -> None:
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}'); "
        "$s.TargetPath = '{target}'; $s.Arguments = '{args}'; $s.WorkingDirectory = '{wd}'; "
        "$s.IconLocation = '{icon},0'; $s.Description = '{desc}'; $s.WindowStyle = 1; $s.Save()"
    ).format(lnk=str(lnk).replace("'", "''"), target=str(target).replace("'", "''"), args=args,
             wd=str(workdir).replace("'", "''"), icon=str(icon).replace("'", "''"), desc=desc)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True)


def create_shortcuts() -> list[Path]:
    icon = make_icon()
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    shell = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('Programs')"],
                           capture_output=True, text=True).stdout.splitlines()
    shell = [line.strip() for line in shell if line.strip()]
    targets = []
    for folder in shell[:2]:
        lnk = Path(folder) / f"{APP_NAME}.lnk"
        _shortcut(lnk, pythonw, "run.py --app", ROOT, icon, "Your personal AI assistant")
        targets.append(lnk)
    return targets


APP_NAME = "Personal Assistant"     # the app's name never changes (the assistant inside can be called anything)


def fix_shortcut_names() -> list[str]:
    """Shortcuts to this app get the fixed app name (older versions named them after the assistant)."""
    ps = (
        "$sh = New-Object -ComObject WScript.Shell; "
        "foreach ($f in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { "
        "Get-ChildItem -Path $f -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object { "
        "$l = $sh.CreateShortcut($_.FullName); "
        "if ($l.Arguments -like '*run.py --app*' -and $l.WorkingDirectory -eq '{root}' -and $_.BaseName -ne '{app}') { "
        "$new = Join-Path $_.DirectoryName '{app}.lnk'; "
        "if (Test-Path $new) {{ Remove-Item $_.FullName }} else {{ Rename-Item $_.FullName '{app}.lnk' }}; $_.Name } } }"
    ).replace("{root}", str(ROOT).replace("'", "''")).replace("{app}", APP_NAME).replace("{{", "{").replace("}}", "}")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30,
                         creationflags=0x08000000)
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def rename_shortcuts(old: str, new: str) -> list[Path]:
    """The Desktop / Start Menu shortcut follows the assistant's name ("Maya.lnk" instead of "Jarvis.lnk")."""
    icon = make_icon()
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    shell = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "[Environment]::GetFolderPath('Desktop'); [Environment]::GetFolderPath('Programs')"],
                           capture_output=True, text=True).stdout.splitlines()
    made = []
    safe = "".join(ch for ch in new if ch not in '\\/:*?"<>|').strip() or "Jarvis"
    for folder in [line.strip() for line in shell if line.strip()][:2]:
        olds = [Path(folder) / f"{n}.lnk" for n in {old, "Jarvis"} if n]
        if not any(o.exists() for o in olds):
            continue                          # no shortcut there: don't create one unasked
        lnk = Path(folder) / f"{safe}.lnk"
        _shortcut(lnk, pythonw, "run.py --app", ROOT, icon, f"{safe} - your personal AI assistant")
        for o in olds:
            if o.exists() and o != lnk:
                o.unlink()
        made.append(lnk)
    return made


if __name__ == "__main__":
    for p in create_shortcuts():
        print("Created", p)

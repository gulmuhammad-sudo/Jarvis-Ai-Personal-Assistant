"""Shortcuts, "start with Windows", the Windows "Installed apps" entry and uninstalling.

The installer ("Personal Assistant Setup.exe", see packaging/) uses these; so does the app itself. From a source
checkout, "python -m jarvis --install" makes Desktop / Start Menu shortcuts that run the code directly.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import APP_NAME, DATA_DIR, FROZEN, ICON, ROOT

EXE_NAME = f"{APP_NAME}.exe"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\PersonalAssistant"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def make_icon() -> Path:
    """Draws the arc-reactor style icon (multi-size .ico). Only needed in a checkout: the .exe brings its own."""
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


# ---------------- what Windows needs ----------------
WEBVIEW2_PAGE = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"       # Microsoft's own small installer for WebView2
_WEBVIEW2 = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
MIN_WINDOWS = 17763                                                        # Windows 10, version 1809


def webview2() -> str:
    """The version of Microsoft Edge WebView2 (it draws the window), '' if it isn't there (older Windows 10)."""
    import winreg
    for root, path in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"),
                       (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients"),
                       (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients")):
        try:
            with winreg.OpenKey(root, rf"{path}\{_WEBVIEW2}") as k:
                v = str(winreg.QueryValueEx(k, "pv")[0])
            if v and v != "0.0.0.0":
                return v
        except OSError:
            pass
    return ""


def message(text: str, title: str = APP_NAME, yes_no: bool = False) -> bool:
    """A plain Windows message (works without WebView2). True for OK / Yes."""
    return ctypes.windll.user32.MessageBoxW(None, text, title, (0x04 if yes_no else 0x00) | 0x30 | 0x10000) in (1, 6)


def need_webview2(title: str = APP_NAME) -> bool:
    """Is WebView2 there? If not: say so in plain words, and open Microsoft's page if you want it."""
    if webview2():
        return True
    if message("This PC doesn't have Microsoft Edge WebView2 yet. It is free, from Microsoft, and draws this app's window.\n\n"
               "Open Microsoft's download now?\n\nRun the file it gives you (it takes a minute), then open this again.", title, yes_no=True):
        os.startfile(WEBVIEW2_PAGE)
    return False


# ---------------- where things go ----------------
def folder(kind: str) -> Path:
    """'desktop', 'programs' (Start Menu) or 'startup' for the signed-in user."""
    csidl = {"desktop": 0x10, "programs": 0x02, "startup": 0x07}[kind]
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    return Path(buf.value)


def launch(app_dir: Path | None = None, tray: bool = False) -> tuple[Path, str, Path]:
    """(program, arguments, start-in folder) that open the app: the installed .exe, or this checkout's Python."""
    if app_dir is not None or FROZEN:
        app_dir = Path(app_dir or ROOT)
        return app_dir / EXE_NAME, "--tray" if tray else "", app_dir
    return ROOT / ".venv" / "Scripts" / "pythonw.exe", "-m jarvis" + (" --tray" if tray else ""), ROOT


def _shortcut(lnk: Path, target: Path, args: str, workdir: Path, icon: Path, desc: str) -> None:
    q = lambda v: str(v).replace("'", "''")   # noqa: E731  (PowerShell single quotes)
    ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}'); "
          f"$s.TargetPath = '{q(target)}'; $s.Arguments = '{q(args)}'; $s.WorkingDirectory = '{q(workdir)}'; "
          f"$s.IconLocation = '{q(icon)},0'; $s.Description = '{q(desc)}'; $s.WindowStyle = 1; $s.Save()")
    lnk.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, capture_output=True, creationflags=NO_WINDOW)


def _icon_for(target: Path) -> Path:
    return target if target.suffix.lower() == ".exe" and target.name == EXE_NAME else (ICON if ICON.exists() else make_icon())


def create_shortcuts(app_dir: Path | None = None, desktop: bool = True, start_menu: bool = True) -> list[Path]:
    target, args, workdir = launch(app_dir)
    made = []
    for kind, wanted in (("desktop", desktop), ("programs", start_menu)):
        lnk = folder(kind) / f"{APP_NAME}.lnk"
        if wanted:
            _shortcut(lnk, target, args, workdir, _icon_for(target), "Your personal AI assistant")
            made.append(lnk)
        elif lnk.exists():
            lnk.unlink()
    return made


def startup_shortcut() -> Path:
    return folder("startup") / f"{APP_NAME}.lnk"


def set_startup(on: bool, app_dir: Path | None = None) -> None:
    """Start with Windows: a shortcut in your Startup folder opens the app in the tray when you sign in."""
    lnk = startup_shortcut()
    try:
        if on:
            target, args, workdir = launch(app_dir, tray=True)
            _shortcut(lnk, target, args, workdir, _icon_for(target), "Starts your personal AI assistant when you sign in")
            print(f"[install] starts with Windows ({lnk.name} in the Startup folder)")
        elif lnk.exists():
            lnk.unlink()
            print("[install] no longer starts with Windows")
    except Exception as e:
        print(f"[install] couldn't change 'start with Windows': {e}")


# ---------------- Windows "Installed apps" entry (current user: no admin rights needed) ----------------
def register(app_dir: Path, version: str) -> None:
    import winreg
    size_kb = sum(f.stat().st_size for f in app_dir.rglob("*") if f.is_file()) // 1024
    exe = app_dir / EXE_NAME
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, value in {"DisplayName": APP_NAME, "DisplayVersion": version, "Publisher": "gulmuhammad-sudo",
                            "DisplayIcon": f'"{exe}",0', "InstallLocation": str(app_dir),
                            "UninstallString": f'"{exe}" --uninstall',
                            "URLInfoAbout": "https://github.com/gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant"}.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, int(size_kb))
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def installed() -> dict | None:
    """{'dir', 'version'} of the installed app, or None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            where = Path(winreg.QueryValueEx(k, "InstallLocation")[0])
            version = winreg.QueryValueEx(k, "DisplayVersion")[0]
        return {"dir": where, "version": version} if (where / EXE_NAME).exists() else None
    except OSError:
        return None


def stop_running(app_dir: Path) -> int:
    """Close the app if it runs from app_dir (before updating or removing it). Returns how many were closed."""
    import psutil
    me, n = os.getpid(), 0
    for p in psutil.process_iter(["pid", "exe"]):
        try:
            exe = p.info["exe"]
            if p.info["pid"] != me and exe and Path(exe).resolve().parent == Path(app_dir).resolve():
                p.kill()
                n += 1
        except (psutil.Error, OSError):
            pass
    return n


def models_dir() -> Path:
    """Where the installed app keeps the offline models and voices you downloaded."""
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_NAME / "models"


def _ask(text: str, yes_no: bool = True, warn: bool = False) -> bool:
    flags = (0x04 if yes_no else 0x00) | (0x30 if warn else 0x20 if yes_no else 0x40)
    return ctypes.windll.user32.MessageBoxW(None, text, f"{APP_NAME} - Uninstall", flags) in (6, 1)


def uninstall() -> None:
    """'Personal Assistant.exe --uninstall' (what Windows Settings > Apps > Uninstall runs)."""
    if not FROZEN:            # a source checkout is never deleted
        print("Uninstalling only applies to the installed app.")
        return
    app_dir = ROOT
    if not _ask(f"Remove {APP_NAME} from this PC?"):
        return
    stop_running(app_dir)
    for lnk in (folder("desktop") / f"{APP_NAME}.lnk", folder("programs") / f"{APP_NAME}.lnk", startup_shortcut()):
        try:
            lnk.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        import winreg
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    models = models_dir()
    also = f"\n\nThe offline models and voices go too:\n{models}" if models.exists() else ""
    if (DATA_DIR.exists() or models.exists()) and _ask(f"Also delete your settings, memories, notes and API keys?\n\n{DATA_DIR}{also}\n\n"
                                                       "Choose No to keep them for next time.", warn=True):
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        shutil.rmtree(models, ignore_errors=True)
        try:
            models.parent.rmdir()                  # %LOCALAPPDATA%\\Personal Assistant, if nothing else is in it
        except OSError:
            pass
    # this .exe can't delete its own folder while it runs: a hidden command does it a moment after we exit
    if (app_dir / EXE_NAME).exists() and app_dir.name and app_dir != Path(app_dir.anchor):
        subprocess.Popen(f'cmd /c ping -n 3 127.0.0.1 >nul & rmdir /s /q "{app_dir}"', creationflags=NO_WINDOW,
                         close_fds=True, cwd=os.environ.get("TEMP", "C:\\"))
    _ask(f"{APP_NAME} has been removed.", yes_no=False)
    sys.exit(0)


if __name__ == "__main__":
    for p in create_shortcuts():
        print("Created", p)

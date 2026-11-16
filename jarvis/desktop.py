"""Jarvis as a desktop app: its own native window (Windows WebView2), no browser, no console.

Start it with the "Jarvis" shortcut on the Desktop / Start Menu, or:  pythonw run.py --app
Everything Jarvis prints goes to data/jarvis.log.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

from .config import DATA_DIR, ROOT

ICON = ROOT / "assets" / "jarvis.ico"
LOG = DATA_DIR / "jarvis.log"


def _log_to_file() -> None:
    """pythonw has no console, so keep a log (trimmed when it gets big)."""
    try:
        if LOG.exists() and LOG.stat().st_size > 2_000_000:
            LOG.replace(LOG.with_suffix(".old.log"))
    except OSError:
        pass
    f = open(LOG, "a", encoding="utf-8", buffering=1)
    f.write(f"\n===== Jarvis started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    sys.stdout = sys.stderr = f


def _message_box(text: str, title: str = "Jarvis") -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, 0x40)
    except Exception:
        print(text)


def _set_window_icon(window) -> None:
    """Give the window and its taskbar button the Jarvis icon instead of Python's."""
    try:
        import clr  # noqa: F401  (pythonnet must be loaded before importing the System namespace)
        from System import Action  # type: ignore
        from System.Drawing import Icon  # type: ignore
        if not ICON.exists():
            return
        form = window.native
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(str(ICON)))))   # UI changes must run on the UI thread
        hwnd = int(form.Handle.ToInt64())
        ok = _set_icon_win32(hwnd)
        print(f"[desktop] window icon set (win32={ok})")
    except Exception as e:
        print(f"[desktop] couldn't set icon: {e}")


def _set_icon_win32(hwnd: int) -> bool:
    """Set the title-bar and taskbar icon straight through Windows (WM_SETICON, big + small)."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
        big = user32.LoadImageW(None, str(ICON), IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
        small = user32.LoadImageW(None, str(ICON), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if not big:
            return False
        user32.SendMessageW(hwnd, WM_SETICON, 1, big)      # ICON_BIG: taskbar / Alt+Tab
        user32.SendMessageW(hwnd, WM_SETICON, 0, small)    # ICON_SMALL: title bar
        return True
    except Exception as e:
        print(f"[desktop] WM_SETICON failed: {e}")
        return False


def main() -> None:
    if sys.stdout is None or "pythonw" in Path(sys.executable).name.lower():
        _log_to_file()
    # Give Jarvis its own taskbar identity so Windows shows the Jarvis icon instead of Python's.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Jarvis.CommandCenter")
    except Exception:
        pass
    # TTS must be able to play without a click first; WebView2 reads extra Chromium flags from here.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")

    from . import hud
    import webview

    if hud.port_in_use():
        # Jarvis is already running (e.g. opened twice): just open another window onto it.
        print("[desktop] Jarvis already running; opening a window onto it.")
    else:
        ready = threading.Event()
        threading.Thread(target=hud.main, kwargs={"open_window": False, "watchdog": False, "ready": ready},
                         daemon=True).start()
        if not ready.wait(60):
            _message_box("Jarvis couldn't start its engine. See data\\jarvis.log for details.")
            return

    from . import schedule
    url = f"http://127.0.0.1:{hud.PORT}/"
    light = schedule.theme() == "light"
    window = webview.create_window(schedule.agent_name(), url, width=1400, height=860, min_size=(1000, 640),
                                   background_color="#EEF2F6" if light else "#05080C", maximized=True, text_select=True)
    hud.TITLE_HOOK = window.set_title
    window.events.shown += lambda: _set_window_icon(window)
    webview.start(gui="edgechromium", private_mode=False, storage_path=str(DATA_DIR / "webview"))
    os._exit(0)   # window closed: stop the server, scheduler and everything else

"""Jarvis as a desktop app: its own native window (Windows WebView2), no browser, no console.

Start it with the "Personal Assistant" shortcut on the Desktop / Start Menu, or:  pythonw run.py --app
Closing the window only hides it: the app keeps running with an icon by the clock (Wi-Fi, volume...);
right-click that icon to open it again, start a Live call or quit. "--tray" starts it hidden there
(what the "start with Windows" shortcut does). Everything it prints goes to data/jarvis.log.
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


def _message_box(text: str, title: str = "Personal Assistant") -> None:
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


class Tray:
    """The icon in the notification area (the ^ menu by the clock). Runs its own Windows message loop."""

    def __init__(self, window) -> None:
        self.window = window
        self.icon = None
        self.hinted = False

    def start(self) -> None:
        from System.Threading import ApartmentState, Thread, ThreadStart  # type: ignore
        t = Thread(ThreadStart(self._run))
        t.IsBackground = True
        t.SetApartmentState(ApartmentState.STA)       # menus need a single-threaded apartment
        t.Start()

    def _run(self) -> None:
        try:
            import System.Windows.Forms as WF  # type: ignore
            from System.Drawing import Font, FontStyle, Icon, SystemIcons  # type: ignore
            from . import hud, live as live_mod, schedule

            def later(fn):                             # never block the tray's own thread
                return lambda *_: threading.Thread(target=fn, daemon=True).start()

            def live_active() -> bool:
                return bool(hud.HUB and hud.HUB.live and hud.HUB.live.active)

            def toggle_live() -> None:
                if not hud.HUB:
                    return
                if live_active():
                    hud.HUB.live_stop()
                elif live_mod.available():
                    hud.HUB.live_start()

            def toggle_startup() -> None:
                on = schedule.get_setting("start_with_windows", True) is False
                schedule.set_setting("start_with_windows", on)
                if hud.STARTUP_HOOK:
                    hud.STARTUP_HOOK(on)
                if hud.HUB:
                    hud.HUB.emit("settings", start_with_windows=on)

            def show(*_):
                later(lambda: show_window(self.window))()

            menu = WF.ContextMenuStrip()
            open_item = menu.Items.Add("Open Personal Assistant")
            open_item.Font = Font(open_item.Font, FontStyle.Bold)
            open_item.Click += show
            live_item = menu.Items.Add("Start live call")
            live_item.Click += later(toggle_live)
            menu.Items.Add(WF.ToolStripSeparator())
            boot_item = WF.ToolStripMenuItem("Start with Windows")
            boot_item.Click += later(toggle_startup)
            menu.Items.Add(boot_item)
            menu.Items.Add(WF.ToolStripSeparator())
            quit_item = menu.Items.Add("Quit")
            quit_item.Click += later(self.quit)

            def opening(*_):
                live_item.Text = "End live call" if live_active() else "Start live call"
                live_item.Enabled = live_active() or live_mod.available()
                boot_item.Checked = schedule.get_setting("start_with_windows", True) is not False
            menu.Opening += opening

            def clicked(sender, e):
                if e.Button == WF.MouseButtons.Left:
                    show()

            icon = WF.NotifyIcon()
            icon.Icon = Icon(str(ICON)) if ICON.exists() else SystemIcons.Application
            icon.Text = "Personal Assistant"
            icon.ContextMenuStrip = menu
            icon.MouseClick += clicked
            icon.Visible = True
            self.icon = icon
            print("[desktop] tray icon ready")
            WF.Application.Run()
        except Exception as e:
            print(f"[desktop] couldn't add the tray icon: {type(e).__name__}: {e}")

    def hint(self) -> None:
        """The first time the window is closed: say where the app went."""
        if self.icon and not self.hinted:
            self.hinted = True
            try:
                import System.Windows.Forms as WF  # type: ignore
                self.icon.ShowBalloonTip(5000, "Still running",
                                         "Personal Assistant is still here. Click this icon to open it; "
                                         "right-click it to quit.", WF.ToolTipIcon.Info)
            except Exception:
                pass

    def quit(self) -> None:
        QUITTING.set()
        try:
            from . import hud
            if hud.HUB and hud.HUB.live and hud.HUB.live.active:
                hud.HUB.live_stop("app closed")
                time.sleep(0.5)
        except Exception:
            pass
        if self.icon:
            try:
                self.icon.Visible = False
                self.icon.Dispose()
            except Exception:
                pass
        os._exit(0)


QUITTING = threading.Event()


def show_window(window) -> None:
    """Bring the window back from the tray (maximized if it had been minimized)."""
    try:
        from System import Action  # type: ignore
        import System.Windows.Forms as WF  # type: ignore
        form = window.native

        def show():
            form.Show()
            if form.WindowState == WF.FormWindowState.Minimized:
                form.WindowState = WF.FormWindowState.Maximized
            form.Activate()
            form.BringToFront()
        form.Invoke(Action(show))
    except Exception as e:
        print(f"[desktop] couldn't show the window: {e}")
        window.show()


def _keep_running_on_close(window, tray: Tray) -> None:
    """The window's X (or Alt+F4) hides it to the tray instead of quitting. Signing out / shutting down still closes it."""
    for _ in range(600):
        if getattr(window, "native", None) is not None:
            break
        time.sleep(0.1)
    try:
        import System.Windows.Forms as WF  # type: ignore
        from System import Action  # type: ignore
        form = window.native

        def closing(sender, args):
            if args.CloseReason == WF.CloseReason.UserClosing and not QUITTING.is_set():
                args.Cancel = True
                sender.Hide()
                threading.Thread(target=tray.hint, daemon=True).start()
        form.Invoke(Action(lambda: form.add_FormClosing(WF.FormClosingEventHandler(closing))))
        print("[desktop] closing the window hides it to the tray")
    except Exception as e:
        print(f"[desktop] couldn't keep running on close: {type(e).__name__}: {e}")


def _show_running_app() -> bool:
    """The app is already running (maybe hidden in the tray): ask it to show its window."""
    import json
    import re
    import urllib.request
    from . import hud
    try:
        base = f"http://127.0.0.1:{hud.PORT}"
        page = urllib.request.urlopen(base + "/", timeout=5).read().decode("utf-8", "ignore")
        token = re.search(r'const TOKEN = "([^"]+)"', page).group(1)
        req = urllib.request.Request(base + "/api/window", data=b'{"action": "show"}', method="POST",
                                     headers={"X-Jarvis-Token": token, "Content-Type": "application/json"})
        return bool(json.loads(urllib.request.urlopen(req, timeout=5).read()).get("ok"))
    except Exception as e:
        print(f"[desktop] couldn't reach the running app: {e}")
        return False


def main(tray: bool = False) -> None:
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

    owner = not hud.port_in_use()
    if not owner:
        # Already running (perhaps hidden in the tray): show that window instead of opening a second one.
        if tray or _show_running_app():
            print("[desktop] already running; showed its window.")
            return
        print("[desktop] already running; opening a window onto it.")
    else:
        ready = threading.Event()
        threading.Thread(target=hud.main, kwargs={"open_window": False, "watchdog": False, "ready": ready, "boot": tray},
                         daemon=True).start()
        if not ready.wait(60):
            _message_box("Jarvis couldn't start its engine. See data\\jarvis.log for details.")
            return

    from . import schedule
    url = f"http://127.0.0.1:{hud.PORT}/"
    light = schedule.theme() == "light"
    window = webview.create_window("Personal Assistant", url, width=1400, height=860, min_size=(1000, 640),
                                   background_color="#EEF2F6" if light else "#05080C", maximized=True, text_select=True,
                                   hidden=tray)
    window.events.shown += lambda: _set_window_icon(window)

    def tray_and_startup() -> None:
        from . import install
        icon = Tray(window)
        icon.start()
        _keep_running_on_close(window, icon)
        hud.WINDOW_HOOK = lambda action="show": show_window(window)
        hud.STARTUP_HOOK = install.set_startup
        install.set_startup(schedule.get_setting("start_with_windows", True) is not False)

    store = str(DATA_DIR / "webview")
    if owner:          # (a second window onto a running app just closes normally)
        webview.start(tray_and_startup, gui="edgechromium", private_mode=False, storage_path=store)
    else:
        webview.start(gui="edgechromium", private_mode=False, storage_path=store)
    os._exit(0)   # Quit (or Windows signing out): stop the server, scheduler and everything else

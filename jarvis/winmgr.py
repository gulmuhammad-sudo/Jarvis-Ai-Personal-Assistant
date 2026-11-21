"""Desktop and window management (Phase 5): list windows, focus, minimise/maximise, snap, arrange, workspaces.

Plain Win32 through ctypes (nothing to install). This app's own window is never listed or moved.
Workspaces are saved layouts ("Study": Chrome on the left, VS Code on the right) in the local database
(storage.py, table workspaces); restoring one opens the apps that are closed and puts every window back.
Window titles come from other programs (a web page sets the browser's title), so tools.py marks them untrusted.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:          # pragma: no cover
    psutil = None

POSITIONS = ("left", "right", "top", "bottom", "top_left", "top_right", "bottom_left", "bottom_right", "center", "full")
MAX_ARRANGE = 6
MAX_SAVED_WINDOWS = 12
# what people call an app -> its process name
ALIASES = {
    "vs code": "code", "vscode": "code", "visual studio code": "code", "edge": "msedge", "microsoft edge": "msedge",
    "google chrome": "chrome", "word": "winword", "powerpoint": "powerpnt", "file explorer": "explorer",
    "explorer": "explorer", "files": "explorer", "terminal": "windowsterminal", "windows terminal": "windowsterminal",
    "task manager": "taskmgr", "paint": "mspaint", "whatsapp": "whatsapp", "teams": "ms-teams", "spotify": "spotify",
}
# process name -> friendly name for lists
FRIENDLY = {
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "code": "VS Code", "winword": "Word", "excel": "Excel",
    "powerpnt": "PowerPoint", "explorer": "File Explorer", "notepad": "Notepad", "windowsterminal": "Terminal",
    "taskmgr": "Task Manager", "mspaint": "Paint", "spotify": "Spotify", "ms-teams": "Teams", "vlc": "VLC",
    "applicationframehost": "",          # Store apps: the title says which one
}
_NO_LAUNCH = {"applicationframehost", "systemsettings", "shellexperiencehost", "searchhost", "startmenuexperiencehost",
              "textinputhost", "lockapp"}

IS_WIN = sys.platform == "win32"


# ---------------- pure layout maths (tested without Windows) ----------------
Rect = tuple[int, int, int, int]          # left, top, right, bottom


def snap_rect(area: Rect, pos: str) -> Rect:
    """Where a window goes for a snap position, inside a monitor's work area (no taskbar)."""
    l, t, r, b = area
    w, h = r - l, b - t
    mx, my = l + w // 2, t + h // 2
    rects = {"left": (l, t, mx, b), "right": (mx, t, r, b), "top": (l, t, r, my), "bottom": (l, my, r, b),
             "top_left": (l, t, mx, my), "top_right": (mx, t, r, my), "bottom_left": (l, my, mx, b),
             "bottom_right": (mx, my, r, b), "center": (l + w // 6, t + h // 8, r - w // 6, b - h // 8), "full": area}
    if pos not in rects:
        raise ValueError(f"Unknown position {pos!r}. Use one of: {', '.join(POSITIONS)}.")
    return rects[pos]


def arrange_rects(area: Rect, n: int) -> list[Rect]:
    """n windows side by side: 2 halves, 3 = one big + two stacked, 4 = quarters, 5-6 = 3 columns x 2 rows."""
    if n < 1:
        return []
    if n > MAX_ARRANGE:
        raise ValueError(f"I can arrange up to {MAX_ARRANGE} windows at once.")
    if n == 1:
        return [area]
    if n == 2:
        return [snap_rect(area, "left"), snap_rect(area, "right")]
    if n == 3:
        return [snap_rect(area, "left"), snap_rect(area, "top_right"), snap_rect(area, "bottom_right")]
    if n == 4:
        return [snap_rect(area, p) for p in ("top_left", "top_right", "bottom_left", "bottom_right")]
    l, t, r, b = area
    w, my = (r - l) // 3, t + (b - t) // 2
    cells = [(l + i * w, row_t, l + (i + 1) * w if i < 2 else r, row_b) for row_t, row_b in ((t, my), (my, b)) for i in range(3)]
    return cells[:n]


def to_fraction(rect: Rect, area: Rect) -> list[float]:
    l, t, r, b = area
    w, h = max(1, r - l), max(1, b - t)
    return [round((rect[0] - l) / w, 4), round((rect[1] - t) / h, 4), round((rect[2] - l) / w, 4), round((rect[3] - t) / h, 4)]


def from_fraction(frac: list[float], area: Rect) -> Rect:
    l, t, r, b = area
    w, h = r - l, b - t
    fl, ft, fr, fb = (min(1.0, max(0.0, float(x))) for x in frac)
    if fr - fl < 0.05 or fb - ft < 0.05:          # nonsense: a sensible size in the middle
        return snap_rect(area, "center")
    return (l + round(fl * w), t + round(ft * h), l + round(fr * w), t + round(fb * h))


# ---------------- Win32 ----------------
@dataclass
class Win:
    hwnd: int
    title: str
    pid: int
    process: str           # lower-case, no .exe
    exe: str
    rect: Rect
    state: str             # normal | minimized | maximized

    @property
    def app(self) -> str:
        name = FRIENDLY.get(self.process)
        if name:
            return name
        if name == "" or not self.process:
            return self.title.split(" - ")[-1][:40] or "App"
        return self.process[:1].upper() + self.process[1:]


if IS_WIN:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    kernel32 = ctypes.WinDLL("kernel32")
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    for _f, _a, _r in [
        ("EnumWindows", [WNDENUMPROC, wintypes.LPARAM], wintypes.BOOL),
        ("IsWindowVisible", [wintypes.HWND], wintypes.BOOL),
        ("IsWindow", [wintypes.HWND], wintypes.BOOL),
        ("IsIconic", [wintypes.HWND], wintypes.BOOL),
        ("IsZoomed", [wintypes.HWND], wintypes.BOOL),
        ("GetWindow", [wintypes.HWND, wintypes.UINT], wintypes.HWND),
        ("GetWindowLongW", [wintypes.HWND, ctypes.c_int], ctypes.c_long),
        ("GetWindowTextLengthW", [wintypes.HWND], ctypes.c_int),
        ("GetWindowTextW", [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
        ("GetWindowThreadProcessId", [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
        ("GetWindowRect", [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        ("ShowWindow", [wintypes.HWND, ctypes.c_int], wintypes.BOOL),
        ("SetWindowPos", [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        ("SetForegroundWindow", [wintypes.HWND], wintypes.BOOL),
        ("GetForegroundWindow", [], wintypes.HWND),
        ("BringWindowToTop", [wintypes.HWND], wintypes.BOOL),
        ("AttachThreadInput", [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL], wintypes.BOOL),
        ("MonitorFromWindow", [wintypes.HWND, wintypes.DWORD], wintypes.HMONITOR),
        ("GetMonitorInfoW", [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)], wintypes.BOOL),
        ("EnumDisplayMonitors", [wintypes.HDC, ctypes.POINTER(wintypes.RECT), MONITORENUMPROC, wintypes.LPARAM], wintypes.BOOL),
    ]:
        getattr(user32, _f).argtypes, getattr(user32, _f).restype = _a, _r
    try:
        user32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    except AttributeError:      # very old Windows
        pass
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD

SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE = 3, 6, 9


@contextmanager
def _dpi():
    """Real pixels on every monitor (otherwise a scaled display gives wrong sizes)."""
    old = None
    try:
        old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))      # per-monitor aware v2
    except Exception:
        pass
    try:
        yield
    finally:
        if old:
            try:
                user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))
            except Exception:
                pass


def _need_windows() -> None:
    if not IS_WIN:
        raise RuntimeError("Window management only works on Windows.")


def _proc(pid: int) -> tuple[str, str]:
    if not psutil:
        return "", ""
    try:
        p = psutil.Process(pid)
        name = (p.name() or "").lower().removesuffix(".exe")
        try:
            exe = p.exe() or ""
        except (psutil.AccessDenied, OSError):
            exe = ""
        return name, exe
    except (psutil.Error, OSError):
        return "", ""


def _cloaked(h) -> bool:
    val = ctypes.c_int(0)
    return dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(val), ctypes.sizeof(val)) == 0 and val.value != 0


def windows() -> list[Win]:
    """Open app windows, top-most first (not this app, not hidden helpers, not dialogs)."""
    _need_windows()
    own, out = os.getpid(), []

    def cb(h, _):
        try:
            if not user32.IsWindowVisible(h) or user32.GetWindow(h, 4) or user32.GetWindowLongW(h, -20) & 0x80:
                return True                                   # hidden, owned (dialogs) or tool windows
            n = user32.GetWindowTextLengthW(h)
            if n <= 0 or _cloaked(h):
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(h, buf, n + 1)
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == own or buf.value in ("Program Manager", "Windows Input Experience"):
                return True
            r = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(r))
            state = "minimized" if user32.IsIconic(h) else "maximized" if user32.IsZoomed(h) else "normal"
            name, exe = _proc(pid.value)
            out.append(Win(int(h), buf.value, pid.value, name, exe, (r.left, r.top, r.right, r.bottom), state))
        except Exception:
            pass
        return True

    with _dpi():
        user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def describe(wins: list[Win]) -> str:
    if not wins:
        return "No app windows are open."
    return "\n".join(f"{i}. {w.app} — {w.title[:90]}" + ("" if w.state == "normal" else f" [{w.state}]")
                     for i, w in enumerate(wins, 1))


def find(query: str, wins: list[Win] | None = None) -> Win | None:
    """A window by list number, app name ("vs code", "chrome") or words of its title; the top-most wins."""
    wins = windows() if wins is None else wins
    q = " ".join(str(query or "").lower().split()).removesuffix(".exe")
    if not q:
        return None
    if q.lstrip("#").isdigit():
        i = int(q.lstrip("#"))
        return wins[i - 1] if 1 <= i <= len(wins) else None
    proc = ALIASES.get(q, q)
    for test in (lambda w: w.process == proc, lambda w: w.app.lower() == q, lambda w: w.process.startswith(proc),
                 lambda w: q in w.title.lower()):
        hit = next((w for w in wins if test(w)), None)
        if hit:
            return hit
    return None


def monitors() -> list[Rect]:
    """Work areas of all monitors (without the taskbar), primary first."""
    _need_windows()
    out: list[tuple[bool, Rect]] = []

    def cb(hmon, _hdc, _rc, _):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            w = mi.rcWork
            out.append((bool(mi.dwFlags & 1), (w.left, w.top, w.right, w.bottom)))
        return True

    with _dpi():
        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    out.sort(key=lambda m: not m[0])
    return [r for _, r in out] or [(0, 0, 1920, 1040)]


def work_area(hwnd: int) -> Rect:
    with _dpi():
        mon = user32.MonitorFromWindow(hwnd, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    w = mi.rcWork
    return (w.left, w.top, w.right, w.bottom)


def _frame(hwnd: int) -> tuple[Rect, Rect]:
    """(the window rect, the visible frame): Windows 10/11 windows have an invisible border of a few pixels."""
    r, f = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(f), ctypes.sizeof(f)) != 0:
        f = r
    return (r.left, r.top, r.right, r.bottom), (f.left, f.top, f.right, f.bottom)


def place(hwnd: int, rect: Rect) -> None:
    """Put a window's visible frame exactly on rect."""
    with _dpi():
        if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.15)
        (wl, wt, wr, wb), (fl, ft, fr, fb) = _frame(hwnd)
        ml, mt, mr, mb = fl - wl, ft - wt, wr - fr, wb - fb
        l, t, r, b = rect
        user32.SetWindowPos(hwnd, None, l - ml, t - mt, (r - l) + ml + mr, (b - t) + mt + mb, 0x0004 | 0x0010)  # no z-order, no activate


def visible_rect(hwnd: int) -> Rect:
    with _dpi():
        return _frame(hwnd)[1]


def focus(hwnd: int) -> bool:
    """Bring a window to the front (Windows only lets the active app do that, so borrow its input queue)."""
    with _dpi():
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd:
            return True
        fg = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        me = kernel32.GetCurrentThreadId()
        if fg_thread and fg_thread != me:
            user32.AttachThreadInput(me, fg_thread, True)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if fg_thread and fg_thread != me:
                user32.AttachThreadInput(me, fg_thread, False)
        return user32.GetForegroundWindow() == hwnd


def _show(hwnd: int, cmd: int) -> None:
    with _dpi():
        user32.ShowWindow(hwnd, cmd)


# ---------------- what the tools call ----------------
def act(action: str, query: str = "", position: str = "") -> str:
    """list | focus | minimize | maximize | restore | snap | minimize_all"""
    action = (action or "list").lower()
    wins = windows()
    if action == "list":
        return describe(wins)
    if action == "minimize_all":
        n = 0
        for w in wins:
            if w.state != "minimized":
                _show(w.hwnd, SW_MINIMIZE)
                n += 1
        return f"Minimised {n} window(s)." if n else "Everything is already minimised."
    w = find(query, wins)
    if not w:
        return f"I can't find an open window for {query!r}. Open windows:\n{describe(wins)}"
    label = f"{w.app} ({w.title[:60]})" if w.app.lower() not in w.title.lower() else w.title[:70]
    if action == "focus":
        return f"Brought {label} to the front." if focus(w.hwnd) else f"Windows didn't let me bring {label} to the front; it's flashing in the taskbar."
    if action == "minimize":
        _show(w.hwnd, SW_MINIMIZE)
        return f"Minimised {label}."
    if action == "maximize":
        _show(w.hwnd, SW_MAXIMIZE)
        return f"Maximised {label}."
    if action == "restore":
        _show(w.hwnd, SW_RESTORE)
        return f"Restored {label}."
    if action == "snap":
        pos = (position or "left").lower().replace(" ", "_").replace("-", "_")
        if pos in ("full", "maximize", "maximized"):
            _show(w.hwnd, SW_MAXIMIZE)
            return f"Maximised {label}."
        place(w.hwnd, snap_rect(work_area(w.hwnd), pos))
        return f"Moved {label} to the {pos.replace('_', ' ')}."
    raise ValueError(f"Unknown action {action!r}.")


def arrange(apps: list[str] | None = None) -> str:
    """Put 2-6 windows side by side on the screen of the first one (the top-most windows if no apps are named)."""
    wins = windows()
    picked: list[Win] = []
    missing = []
    for a in apps or []:
        w = find(a, [x for x in wins if x not in picked])
        (picked.append(w) if w else missing.append(a))
    if not apps:
        picked = [w for w in wins if w.state != "minimized"][:4]
    if not picked:
        return "There are no windows to arrange." + (f" Not open: {', '.join(missing)}." if missing else "")
    area = work_area(picked[0].hwnd)
    for w, r in zip(picked, arrange_rects(area, len(picked))):
        place(w.hwnd, r)
    msg = "Arranged " + ", ".join(w.app for w in picked) + " side by side." if len(picked) > 1 else f"Filled the screen with {picked[0].app}."
    return msg + (f" Not open: {', '.join(missing)}." if missing else "")


# ---------------- workspaces ----------------
def _db():
    from . import storage
    return storage.conn(), storage._LOCK


def _now() -> str:
    return datetime.now().isoformat(timespec="minutes")


def list_workspaces() -> list[dict]:
    c, lock = _db()
    with lock:
        rows = c.execute("SELECT id, name, layout, updated, uses FROM workspaces ORDER BY name COLLATE NOCASE").fetchall()
    out = []
    for i, name, layout, updated, uses in rows:
        items = json.loads(layout)
        out.append({"id": i, "name": name, "apps": [it.get("app") or it.get("process") for it in items],
                    "windows": len(items), "updated": updated, "uses": uses})
    return out


def _get(name_or_id) -> tuple[int, str, list] | None:
    c, lock = _db()
    with lock:
        if isinstance(name_or_id, int) or str(name_or_id).isdigit():
            r = c.execute("SELECT id, name, layout FROM workspaces WHERE id = ?", (int(name_or_id),)).fetchone()
        else:
            name = " ".join(str(name_or_id).split()).strip(" \"'")
            r = c.execute("SELECT id, name, layout FROM workspaces WHERE name = ?", (name,)).fetchone()
            if not r:
                rows = c.execute("SELECT id, name, layout FROM workspaces WHERE name LIKE ?", (name.replace("%", "") + "%",)).fetchall()
                r = rows[0] if len(rows) == 1 else None
    return (r[0], r[1], json.loads(r[2])) if r else None


def save_workspace(name: str) -> str:
    name = " ".join((name or "").split())
    if not name or len(name) > 40:
        raise ValueError("Give the workspace a name (up to 40 characters).")
    wins = [w for w in windows() if w.state != "minimized"][:MAX_SAVED_WINDOWS]
    if not wins:
        raise ValueError("There are no open windows to save.")
    mons = monitors()
    items = []
    for w in wins:
        area = work_area(w.hwnd)
        mon = mons.index(area) if area in mons else 0
        items.append({"app": w.app, "process": w.process, "exe": w.exe, "title": w.title[:120], "monitor": mon,
                      "state": w.state, "place": None if w.state == "maximized" else to_fraction(visible_rect(w.hwnd), area)})
    c, lock = _db()
    with lock, c:
        c.execute("INSERT INTO workspaces(name, layout, created, updated) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(name) DO UPDATE SET layout = excluded.layout, updated = excluded.updated",
                  (name, json.dumps(items, ensure_ascii=False), _now(), _now()))
    return f"Saved workspace \"{name}\" with {len(items)} window(s): {', '.join(dict.fromkeys(i['app'] for i in items))}."


def delete_workspace(name_or_id) -> str:
    ws = _get(name_or_id)
    if not ws:
        return f"There's no workspace called {name_or_id!r}."
    c, lock = _db()
    with lock, c:
        c.execute("DELETE FROM workspaces WHERE id = ?", (ws[0],))
    return f"Deleted workspace \"{ws[1]}\"."


def _match(item: dict, wins: list[Win], used: set[int]) -> Win | None:
    same = [w for w in wins if w.process == item.get("process") and w.hwnd not in used]
    if not same:
        return None
    title = (item.get("title") or "").lower()
    words = set(title.split())
    return max(same, key=lambda w: (w.title.lower() == title, len(words & set(w.title.lower().split()))))


def can_launch(exe: str) -> bool:
    if not exe or not Path(exe).is_file():
        return False
    low = exe.lower()
    return "\\windowsapps\\" not in low and Path(low).stem not in _NO_LAUNCH and Path(exe).resolve() != Path(sys.executable).resolve()


def restore_workspace(name_or_id, wait: float = 12.0) -> str:
    ws = _get(name_or_id)
    if not ws:
        names = ", ".join(w["name"] for w in list_workspaces()) or "none yet"
        return f"There's no workspace called {name_or_id!r}. Saved workspaces: {names}."
    wid, name, items = ws
    mons = monitors()
    used: set[int] = set()
    placed, opened, failed = [], [], []
    for it in items:
        current = windows()
        w = _match(it, current, used)
        if not w and can_launch(it.get("exe", "")):
            before = {x.hwnd for x in current}
            try:
                subprocess.Popen([it["exe"]], cwd=str(Path(it["exe"]).parent), close_fds=True,
                                 creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
            except OSError:
                pass
            end = time.time() + wait
            while time.time() < end and not w:
                time.sleep(0.5)
                w = next((x for x in windows() if x.process == it.get("process") and x.hwnd not in before and x.hwnd not in used), None)
            if w:
                opened.append(it.get("app") or it.get("process"))
                time.sleep(0.6)                      # let it finish drawing before moving it
        if not w:
            failed.append(it.get("app") or it.get("process"))
            continue
        used.add(w.hwnd)
        area = mons[it.get("monitor", 0)] if it.get("monitor", 0) < len(mons) else mons[0]
        if it.get("state") == "maximized" or not it.get("place"):
            place(w.hwnd, snap_rect(area, "center"))   # on the right monitor first
            _show(w.hwnd, SW_MAXIMIZE)
        else:
            place(w.hwnd, from_fraction(it["place"], area))
        placed.append(it.get("app") or it.get("process"))
    c, lock = _db()
    with lock, c:
        c.execute("UPDATE workspaces SET uses = uses + 1 WHERE id = ?", (wid,))
    msg = f"Workspace \"{name}\": placed {len(placed)} window(s)"
    if opened:
        msg += f", opened {', '.join(opened)}"
    if failed:
        msg += f". Couldn't open: {', '.join(failed)}"
    return msg + "."

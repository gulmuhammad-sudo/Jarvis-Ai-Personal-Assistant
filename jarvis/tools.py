"""Everything Jarvis can *do* on your PC.

Each tool has a JSON-schema definition (sent to the AI model) and a Python function
(run locally when the model calls it). Risky tools ask you to confirm first.

Sections: basics · web · daily life (briefing, YouTube, prayers, alarms, language) · PC control.
"""
from __future__ import annotations

import base64
import html as _html
import json
import os
import platform
import re as _re
import shutil
import subprocess
import threading
import time
import urllib.parse as _up
import urllib.request as _ur
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus

from . import audit, guard, memory
from . import schedule as _sched
from .config import NOTES_DIR, ROOT, SCREENSHOT_DIR

try:
    import psutil
except ImportError:  # optional
    psutil = None

# Emergency stop: set by the Stop button / tray menu. While set, no tool runs and every approval is "no";
# it is cleared when you give the next instruction.
STOP = threading.Event()


class ToolContext:
    """Hooks the tools use to talk back to the person at the keyboard."""

    def __init__(self, confirm: Callable[[str], bool], notify: Callable[..., None]):
        self.confirm = confirm
        self.notify = notify
        self.timers: dict[int, tuple[threading.Timer, str, datetime]] = {}
        self._next_timer = 1
        self.set_language: Callable[[str], None] | None = None   # set by the HUD / console
        self.set_name: Callable[[str], str] | None = None           # rename the assistant (HUD)
        self.set_theme: Callable[[str], None] | None = None         # light / dark Command Center (HUD)
        self.set_brain: Callable[[str, str | None], str] | None = None  # choose the AI provider (HUD)
        self.set_chat_script: Callable[[str], None] | None = None     # chat text in English letters / Urdu script (HUD)
        self.language = "en"

    def approve(self, question: str, kind: str | None = None) -> bool:
        """Ask before acting. kind groups similar requests: once you allow e.g. "powershell", the HUD stops
        asking for that kind until the app restarts (never for shutdown/restart or deleting files)."""
        if STOP.is_set():
            granted = False
        else:
            try:
                granted = bool(self.confirm(question, kind=kind))
            except TypeError:                 # a confirm() that doesn't know about kinds (console)
                granted = bool(self.confirm(question))
        audit.record("approval", kind=kind or "", question=question, granted=granted)
        return granted


def _ps(command: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-Command", command],
                          capture_output=True, text=True, timeout=timeout, check=False,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _ps_quote(text: str) -> str:
    """Make text safe inside a single-quoted PowerShell string."""
    return str(text).replace("'", "''")


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #

def get_datetime(_: dict, ctx: ToolContext) -> str:
    now = datetime.now()
    return now.strftime("%A, %d %B %Y, %I:%M %p (local time)")


def system_status(_: dict, ctx: ToolContext) -> str:
    lines = [f"OS: {platform.system()} {platform.release()} ({platform.machine()})",
             f"Computer name: {platform.node()}"]
    if psutil:
        lines.append(f"CPU usage: {psutil.cpu_percent(interval=0.5)}% across {psutil.cpu_count()} logical cores")
        vm = psutil.virtual_memory()
        lines.append(f"RAM: {vm.used / 2**30:.1f} / {vm.total / 2**30:.1f} GB used ({vm.percent}%)")
        bat = psutil.sensors_battery()
        if bat:
            plug = "charging" if bat.power_plugged else "on battery"
            lines.append(f"Battery: {bat.percent:.0f}% ({plug})")
        up = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        lines.append(f"Uptime: {str(up).split('.')[0]}")
        top = sorted(psutil.process_iter(["name", "memory_info"]),
                     key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0,
                     reverse=True)[:5]
        lines.append("Top memory users: " + ", ".join(
            f"{p.info['name']} ({p.info['memory_info'].rss / 2**20:.0f} MB)" for p in top if p.info["memory_info"]))
    total, used, free = shutil.disk_usage(Path.home().anchor)
    lines.append(f"Disk {Path.home().anchor}: {free / 2**30:.0f} GB free of {total / 2**30:.0f} GB")
    try:
        from . import gpu
        g = gpu.monitor()
        for _ in range(15):                      # first reading takes a few seconds
            if g.percent is not None:
                break
            time.sleep(0.3)
        if g.percent is not None:
            lines.append(f"GPU ({g.name or 'graphics'}): {g.percent:.0f}% busy"
                         + (f" (mostly {g.engine})" if g.engine and g.percent >= 5 else "")
                         + (f", {g.mem_mb / 1024:.1f} GB GPU memory in use" if g.mem_mb else ""))
    except Exception:
        pass
    return "\n".join(lines)


def open_website(inp: dict, ctx: ToolContext) -> str:
    url = inp["url"].strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} in the default browser."


def search_web_in_browser(inp: dict, ctx: ToolContext) -> str:
    site = inp.get("site", "google")
    q = quote_plus(inp["query"])
    urls = {
        "google": f"https://www.google.com/search?q={q}",
        "youtube": f"https://www.youtube.com/results?search_query={q}",
        "maps": f"https://www.google.com/maps/search/{q}",
        "wikipedia": f"https://en.wikipedia.org/wiki/Special:Search?search={q}",
    }
    url = urls.get(site, urls["google"])
    webbrowser.open(url)
    return f"Opened {site} search for '{inp['query']}'."


_APP_ALIASES = {
    "notepad": "notepad", "calculator": "calc", "calc": "calc", "paint": "mspaint",
    "explorer": "explorer", "file explorer": "explorer", "files": "explorer",
    "cmd": "cmd", "command prompt": "cmd", "terminal": "wt", "powershell": "powershell",
    "task manager": "taskmgr", "settings": "ms-settings:", "control panel": "control",
    "chrome": "chrome", "edge": "msedge", "firefox": "firefox", "word": "winword",
    "excel": "excel", "powerpoint": "powerpnt", "outlook": "outlook", "vscode": "code",
    "vs code": "code", "visual studio code": "code", "spotify": "spotify:",
    "camera": "microsoft.windows.camera:", "snipping tool": "snippingtool",
    "whatsapp": "whatsapp:", "store": "ms-windows-store:", "clock": "ms-clock:",
}


_SHELL_CHARS = set('&|<>^%"`\r\n;')


def open_application(inp: dict, ctx: ToolContext) -> str:
    name = inp["name"].strip()
    if not name or any(c in _SHELL_CHARS for c in name):
        return f"'{name}' doesn't look like an app name."
    target = _APP_ALIASES.get(name.lower(), name)
    try:
        # ShellExecute finds registered apps (chrome, winword...), URI apps (spotify:) and files;
        # shutil.which covers command-line launchers such as code.cmd. No shell is involved.
        os.startfile(shutil.which(target) or target)
        return f"Launched {name}."
    except OSError as e:
        # Fall back to the Start-menu list for installed Store / desktop apps.
        r = _ps(f"$a = Get-StartApps | Where-Object {{ $_.Name -like '*{_ps_quote(name)}*' }} | "
                "Select-Object -First 1; if ($a) { Start-Process ('shell:AppsFolder\\' + $a.AppID); $a.Name }")
        if r.stdout.strip():
            return f"Launched {r.stdout.strip()}."
        return f"Could not find an app called '{name}' ({e.strerror or e})."


def open_path(inp: dict, ctx: ToolContext) -> str:
    p = Path(os.path.expandvars(os.path.expanduser(inp["path"])))
    if not p.exists():
        return f"Path not found: {p}"
    os.startfile(str(p))
    return f"Opened {p}."


def find_files(inp: dict, ctx: ToolContext) -> str:
    pattern = inp["pattern"]
    folder = Path(os.path.expanduser(inp.get("folder") or "~"))
    limit = int(inp.get("max_results", 20))
    skip = {"AppData", "node_modules", ".git", ".venv", "$Recycle.Bin", "Windows"}
    hits: list[str] = []
    deadline = time.time() + 20
    for dirpath, dirnames, filenames in os.walk(folder):
        if time.time() > deadline:
            hits.append("[stopped searching after 20 s; try a more specific folder]")
            break
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for f in filenames:
            if Path(f).match(pattern) or pattern.lower() in f.lower():
                hits.append(str(Path(dirpath) / f))
                if len(hits) >= limit:
                    return "\n".join(hits)
    return "\n".join(hits) if hits else f"No files matching '{pattern}' under {folder}."


def read_text_file(inp: dict, ctx: ToolContext) -> str:
    p = Path(os.path.expanduser(inp["path"]))
    if not p.is_file():
        return f"Not a file: {p}"
    data = p.read_text(encoding="utf-8", errors="replace")
    if len(data) > 60_000:
        return data[:60_000] + f"\n\n[... file is {len(data)} chars; showing the first 60,000]"
    return data


def save_note(inp: dict, ctx: ToolContext) -> str:
    title = "".join(c for c in inp["title"] if c.isalnum() or c in " -_").strip() or "note"
    path = NOTES_DIR / f"{datetime.now():%Y-%m-%d} {title}.md"
    with path.open("a", encoding="utf-8") as f:
        f.write(inp["content"].rstrip() + "\n")
    return f"Saved note to {path}."


def list_notes(_: dict, ctx: ToolContext) -> str:
    notes = sorted(NOTES_DIR.glob("*.md"))
    return "\n".join(n.name for n in notes) or "No notes yet."


def remember_fact(inp: dict, ctx: ToolContext) -> str:
    return memory.remember(inp["fact"], inp.get("category"), inp.get("importance"))


def recall_memories(inp: dict, ctx: ToolContext) -> str:
    query, cat = str(inp.get("query") or ""), inp.get("category")
    if not query and not cat:
        return memory.as_text(limit=500)
    found = memory.search(query, cat, limit=40)
    if not found:
        return f"No memories match {query or cat!r}."
    return "\n".join(f"#{m['id']} [{m['category']}, importance {m['importance']}]: {m['fact']}" for m in found)


def forget_memory(inp: dict, ctx: ToolContext) -> str:
    return memory.forget(int(inp["id"]))


_USER_DIRS = ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos", "OneDrive")


def _user_path(raw: str) -> Path:
    """A path inside your own folders (Desktop, Documents, Downloads...). Anything else is refused."""
    home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    p = Path(os.path.expandvars(os.path.expanduser(raw.strip().strip('"'))))
    if not p.is_absolute():
        first = p.parts[0].lower() if p.parts else ""
        p = home / p if first in (d.lower() for d in _USER_DIRS) else home / "Documents" / p
    p = p.resolve()
    allowed = [(home / d).resolve() for d in _USER_DIRS]
    if not any(p == a or a in p.parents for a in allowed) or ROOT.resolve() in [p, *p.parents]:
        raise ValueError(f"I only create files inside your Desktop, Documents, Downloads, Pictures, Music or Videos folders, not {p}.")
    return p


def write_file(inp: dict, ctx: ToolContext) -> str:
    p = _user_path(inp["path"])
    text = str(inp.get("content", ""))
    if p.exists() and p.is_dir():
        return f"{p} is a folder."
    append = bool(inp.get("append"))
    if p.exists() and not append and not ctx.approve(f"{p.name} already exists in {p.parent}. Replace it?", kind="overwrite"):
        return "Okay, I left the existing file alone."
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a" if append else "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return f"{'Added to' if append else 'Saved'} {p} ({len(text)} characters)."


def make_folder(inp: dict, ctx: ToolContext) -> str:
    p = _user_path(inp["path"])
    p.mkdir(parents=True, exist_ok=True)
    return f"Folder ready: {p}"


def edit_memory(inp: dict, ctx: ToolContext) -> str:
    return memory.update(int(inp["id"]), inp.get("fact"), inp.get("category"), inp.get("importance"))


def merge_memories(inp: dict, ctx: ToolContext) -> str:
    return memory.merge([int(i) for i in inp.get("ids") or []] or None, inp.get("fact"))


def switch_ai_model(inp: dict, ctx: ToolContext) -> str:
    if not ctx.set_brain:
        return "Switching the AI isn't available here."
    try:
        msg = ctx.set_brain(inp.get("provider") or "auto", inp.get("model") or None)
    except ValueError as e:
        return str(e)
    return msg + " (Your next typed or Classic-voice message goes there; Live voice calls always use Gemini Live.)"


def set_timer(inp: dict, ctx: ToolContext) -> str:
    seconds = float(inp["seconds"])
    if not 0 < seconds <= 7 * 86400:
        return "Timers can be from 1 second up to 7 days. For a clock time, use set_alarm."
    message = inp.get("message") or "Your timer is done."
    tid = ctx._next_timer
    ctx._next_timer += 1

    def fire():
        ctx.timers.pop(tid, None)
        ctx.notify(f"Reminder: {message}")

    t = threading.Timer(seconds, fire)
    t.daemon = True
    t.start()
    due = datetime.now() + timedelta(seconds=seconds)
    ctx.timers[tid] = (t, message, due)
    return f"Timer #{tid} set for {due:%I:%M:%S %p}: {message}"


def list_timers(_: dict, ctx: ToolContext) -> str:
    if not ctx.timers:
        return "No active timers."
    return "\n".join(f"#{i}: {m} at {d:%I:%M:%S %p}" for i, (_, m, d) in ctx.timers.items())


def cancel_timer(inp: dict, ctx: ToolContext) -> str:
    item = ctx.timers.pop(int(inp["id"]), None)
    if not item:
        return f"No timer #{inp['id']}."
    item[0].cancel()
    return f"Cancelled timer #{inp['id']}."


_MEDIA_KEYS = {"play_pause": 179, "next": 176, "previous": 177, "stop": 178,
               "volume_up": 175, "volume_down": 174, "mute": 173}


def media_control(inp: dict, ctx: ToolContext) -> str:
    action = inp["action"]
    times = max(1, min(int(inp.get("times", 1)), 50))
    key = _MEDIA_KEYS.get(action)
    if key is None:
        return f"Unknown action {action}."
    _ps(f"$w = New-Object -ComObject WScript.Shell; 1..{times} | ForEach-Object {{ $w.SendKeys([char]{key}) }}")
    return f"Done: {action}" + (f" x{times}" if times > 1 else "")


def clipboard(inp: dict, ctx: ToolContext) -> str:
    if inp["action"] == "read":
        return _ps("Get-Clipboard -Raw").stdout or "(clipboard is empty)"
    text = inp.get("text", "")
    subprocess.run(["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                   input=text, text=True, check=False)
    return "Copied to clipboard."


_SCREENSHOT_PS = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$scale = [Math]::Min(1.0, 1568 / [Math]::Max($b.Width, $b.Height))
$w = [int]($b.Width * $scale); $h = [int]($b.Height * $scale)
$small = New-Object System.Drawing.Bitmap $bmp, $w, $h
$small.Save('__PATH__', [System.Drawing.Imaging.ImageFormat]::Jpeg)
"""


def look_at_screen(_: dict, ctx: ToolContext) -> list[dict] | str:
    path = SCREENSHOT_DIR / f"screen_{datetime.now():%Y%m%d_%H%M%S}.jpg"
    _ps(_SCREENSHOT_PS.replace("__PATH__", _ps_quote(path)))
    if not path.exists():
        return "Screenshot failed."
    data = base64.standard_b64encode(path.read_bytes()).decode()
    return [
        {"type": "text", "text": f"Screenshot of the user's screen (saved to {path}):"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
    ]


def run_powershell(inp: dict, ctx: ToolContext) -> str:
    cmd = inp["command"]
    why = inp.get("reason", "")
    blocked = guard.check_powershell(cmd)
    if blocked:
        audit.record("blocked", tool="run_powershell", command=cmd, reason=blocked)
        return (f"I won't run that command: it means {blocked}, which is too risky to do automatically, even "
                "with your OK. If you really need it, run it yourself in PowerShell.")
    if not ctx.approve(kind="powershell", question=f"{_sched.agent_name()} wants to run this PowerShell command{f' ({why})' if why else ''}:\n    {cmd}"):
        return "The user declined to run this command."
    try:
        r = _ps(cmd, timeout=int(inp.get("timeout_seconds", 120)))
    except subprocess.TimeoutExpired:
        return "Command timed out."
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr.strip() else "")
    out = out.strip() or "(no output)"
    if len(out) > 20_000:
        out = out[:20_000] + "\n[... output truncated]"
    return f"exit code {r.returncode}\n{out}"


def lock_computer(_: dict, ctx: ToolContext) -> str:
    if not ctx.approve("Lock the computer now?", kind="lock"):
        return "The user declined."
    subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=False)
    return "Computer locked."


# --------------------------------------------------------------------------- #
# Definitions sent to Claude
# --------------------------------------------------------------------------- #

def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


TOOLS: list[tuple[dict, Callable[[dict, ToolContext], Any]]] = [
    ({"name": "get_datetime", "description": "Get the current local date and time.",
      "input_schema": _obj({})}, get_datetime),
    ({"name": "system_status",
      "description": "Report the PC's health: CPU, RAM, battery, disk space, uptime and the top memory-hungry processes.",
      "input_schema": _obj({})}, system_status),
    ({"name": "open_website", "description": "Open a URL in the user's default browser.",
      "input_schema": _obj({"url": {"type": "string"}}, ["url"])}, open_website),
    ({"name": "search_web_in_browser",
      "description": "Open a search results page in the browser for the user to look at (Google, YouTube, Maps or Wikipedia). "
                     "Use this when the user wants to SEE results or play something on YouTube; use web_search when you need the answer yourself.",
      "input_schema": _obj({"query": {"type": "string"},
                            "site": {"type": "string", "enum": ["google", "youtube", "maps", "wikipedia"]}},
                           ["query"])}, search_web_in_browser),
    ({"name": "open_application",
      "description": "Launch a Windows application by name, e.g. 'notepad', 'chrome', 'spotify', 'vs code', 'calculator', 'settings'.",
      "input_schema": _obj({"name": {"type": "string"}}, ["name"])}, open_application),
    ({"name": "open_path", "description": "Open a file or folder with its default program (e.g. '~/Downloads', 'C:/Users/me/report.pdf').",
      "input_schema": _obj({"path": {"type": "string"}}, ["path"])}, open_path),
    ({"name": "find_files",
      "description": "Search for files by name or glob pattern (e.g. '*.pdf', 'resume'). Searches the user's home folder unless a folder is given.",
      "input_schema": _obj({"pattern": {"type": "string"}, "folder": {"type": "string"},
                            "max_results": {"type": "integer"}}, ["pattern"])}, find_files),
    ({"name": "read_text_file", "description": "Read a text file (code, txt, md, csv, json...) so you can summarise or answer questions about it.",
      "input_schema": _obj({"path": {"type": "string"}}, ["path"])}, read_text_file),
    ({"name": "save_note", "description": "Save or append to a markdown note in Jarvis's notes folder (to-do lists, ideas, meeting notes).",
      "input_schema": _obj({"title": {"type": "string"}, "content": {"type": "string"}}, ["title", "content"])}, save_note),
    ({"name": "list_notes", "description": "List the notes Jarvis has saved.", "input_schema": _obj({})}, list_notes),
    ({"name": "remember_fact",
      "description": "Store a durable fact about the user in long-term memory (name, preferences, people, routines, ongoing projects). "
                     "Use this proactively when the user tells you something worth remembering across sessions. "
                     "category and importance (1 normal, 2 important, 3 key) are optional; they're guessed if left out.",
      "input_schema": _obj({"fact": {"type": "string"},
                            "category": {"type": "string", "enum": list(memory.CATEGORIES)},
                            "importance": {"type": "integer", "enum": [1, 2, 3]}}, ["fact"])}, remember_fact),
    ({"name": "recall_memories",
      "description": "Look up long-term memories (with ids). query: words to search for, e.g. 'wife birthday'; category: "
                     "only that kind. Both empty = everything.",
      "input_schema": _obj({"query": {"type": "string"}, "category": {"type": "string", "enum": list(memory.CATEGORIES)}})},
     recall_memories),
    ({"name": "forget_memory", "description": "Delete a long-term memory by id.",
      "input_schema": _obj({"id": {"type": "integer"}}, ["id"])}, forget_memory),
    ({"name": "write_file",
      "description": "Create (or replace / append to) a text file: .txt, .md, .py, .html, .csv, .json and so on. "
                     "Use this instead of PowerShell to make files. path: e.g. 'Desktop/todo.txt' or a full path inside "
                     "Desktop, Documents or Downloads (a bare name goes to Documents). New files need no approval.",
      "input_schema": _obj({"path": {"type": "string"}, "content": {"type": "string"},
                            "append": {"type": "boolean"}}, ["path", "content"])}, write_file),
    ({"name": "make_folder", "description": "Create a folder inside Desktop, Documents or Downloads (no approval needed).",
      "input_schema": _obj({"path": {"type": "string"}}, ["path"])}, make_folder),
    ({"name": "edit_memory",
      "description": "Change a long-term memory by id (call recall_memories first for the ids): its text, category and/or "
                     "importance (1 normal, 2 important, 3 key).",
      "input_schema": _obj({"id": {"type": "integer"}, "fact": {"type": "string"},
                            "category": {"type": "string", "enum": list(memory.CATEGORIES)},
                            "importance": {"type": "integer", "enum": [1, 2, 3]}}, ["id"])}, edit_memory),
    ({"name": "merge_memories",
      "description": "Combine memories into ONE memory, e.g. 'put all my memories into one'. ids: which ones (empty = all). "
                     "fact: optional tidy combined text you wrote; if empty they are joined as they are.",
      "input_schema": _obj({"ids": {"type": "array", "items": {"type": "integer"}}, "fact": {"type": "string"}})}, merge_memories),
    ({"name": "switch_ai_model",
      "description": "Switch which AI answers: 'gemini', 'groq', 'openrouter', 'deepseek' or 'auto' (the normal order with "
                     "automatic fallback), optionally a specific model of that provider. Use for 'Groq pe chalo', "
                     "'use OpenRouter', 'switch back to automatic'.",
      "input_schema": _obj({"provider": {"type": "string"}, "model": {"type": "string"}}, ["provider"])}, switch_ai_model),
    ({"name": "set_timer",
      "description": "Set a timer/reminder that fires after N seconds while Jarvis is running. Convert minutes/hours or a clock time to seconds first (call get_datetime if needed).",
      "input_schema": _obj({"seconds": {"type": "number"}, "message": {"type": "string"}}, ["seconds"])}, set_timer),
    ({"name": "list_timers", "description": "List active timers.", "input_schema": _obj({})}, list_timers),
    ({"name": "cancel_timer", "description": "Cancel a timer by id.",
      "input_schema": _obj({"id": {"type": "integer"}}, ["id"])}, cancel_timer),
    ({"name": "media_control",
      "description": "Control media playback and system volume. Each volume step is about 2%.",
      "input_schema": _obj({"action": {"type": "string", "enum": list(_MEDIA_KEYS)},
                            "times": {"type": "integer", "description": "How many key presses (volume steps)."}},
                           ["action"])}, media_control),
    ({"name": "clipboard", "description": "Read the clipboard, or copy text to it.",
      "input_schema": _obj({"action": {"type": "string", "enum": ["read", "write"]},
                            "text": {"type": "string"}}, ["action"])}, clipboard),
    ({"name": "look_at_screen",
      "description": "Take a screenshot of the user's screen and look at it. Use when the user says 'look at this', 'what's on my screen', or asks about an error they are seeing.",
      "input_schema": _obj({})}, look_at_screen),
    ({"name": "run_powershell",
      "description": "Run a PowerShell command on the user's Windows PC. The user is asked to approve every command. "
                     "Use for anything the other tools can't do: system settings queries, file operations, network info, installing software, etc.",
      "input_schema": _obj({"command": {"type": "string"},
                            "reason": {"type": "string", "description": "One short line explaining what this does."},
                            "timeout_seconds": {"type": "integer"}}, ["command", "reason"])}, run_powershell),
    ({"name": "lock_computer", "description": "Lock the Windows session (asks the user first).",
      "input_schema": _obj({})}, lock_computer),
]

TOOL_DEFINITIONS = [d for d, _ in TOOLS]
_HANDLERS = {d["name"]: fn for d, fn in TOOLS}

# Anthropic-hosted web search (only used with an Anthropic API key; other models use web_search below).
SERVER_TOOLS = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]


RESULT_HOOK: Callable[[str, dict, Any, bool], None] | None = None   # the HUD shows results in Activity


def execute(name: str, tool_input: dict, ctx: ToolContext) -> tuple[Any, bool]:
    """Run a tool. Returns (content, is_error). Every call goes into the audit log; text from web pages, files
    and the clipboard comes back marked as untrusted (see guard.py)."""
    args = tool_input if isinstance(tool_input, dict) else {}
    if STOP.is_set():
        audit.record("tool", tool=name, args=args, ok=False, result="stopped by the user")
        return "Stopped: the user pressed Stop. Don't continue this task; say it was stopped.", True
    out, err = _execute(name, tool_input, ctx)
    audit.record("tool", tool=name, args=args, ok=not err,
                 result=(out if isinstance(out, str) else "[image]")[:120])
    if RESULT_HOOK:
        try:
            RESULT_HOOK(name, args, out, err)
        except Exception:
            pass
    if not err and isinstance(out, str) and guard.is_untrusted(name, args):
        out = guard.wrap(name, out)
    return out, err


def _execute(name: str, tool_input: dict, ctx: ToolContext) -> tuple[Any, bool]:
    fn = _HANDLERS.get(name)
    if fn is None:
        return f"Unknown tool: {name}", True
    if not isinstance(tool_input, dict):
        return "Tool input must be a JSON object.", True
    try:
        return fn(tool_input, ctx), False
    except KeyError as e:
        return f"Missing required parameter: {e}", True
    except Exception as e:  # report failures back to Claude instead of crashing
        return f"{type(e).__name__}: {e}", True


# --------------------------------------------------------------------------- #
# Web tools for providers without built-in web search (Gemini/Groq/DeepSeek)
# --------------------------------------------------------------------------- #
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def _strip_tags(s: str) -> str:
    return _html.unescape(_re.sub(r"<[^>]+>", "", s)).strip()


_ddg_blocked_until = 0.0     # DuckDuckGo asked for a "prove you're human" challenge: skip it for a while


def _free_search(query: str, limit: int = 6) -> str | None:
    """Backup search with no key and no limit: Google News headlines + the best Wikipedia match."""
    import xml.etree.ElementTree as ET
    region = os.environ.get("JARVIS_NEWS_REGION", "PK")
    out = []
    try:
        url = "https://news.google.com/rss/search?" + _up.urlencode(
            {"q": query, "hl": f"en-{region}", "gl": region, "ceid": f"{region}:en"})
        with _ur.urlopen(_ur.Request(url, headers=_UA), timeout=15) as r:
            items = ET.fromstring(r.read()).findall(".//item")[:limit]
        for i, it in enumerate(items, 1):
            date = (it.findtext("pubDate") or "")[:16]
            out.append(f"{i}. {it.findtext('title')} ({date})\n   {it.findtext('link')}")
    except Exception:
        pass
    try:
        url = "https://en.wikipedia.org/w/api.php?" + _up.urlencode(
            {"action": "query", "generator": "search", "gsrsearch": query, "gsrlimit": 1, "prop": "extracts",
             "exintro": 1, "explaintext": 1, "exchars": 900, "format": "json"})
        with _ur.urlopen(_ur.Request(url, headers=_UA), timeout=15) as r:
            pages = (json.loads(r.read()).get("query") or {}).get("pages") or {}
        for pg in pages.values():
            if pg.get("extract"):
                out.append(f"Wikipedia, {pg['title']}: {pg['extract'].strip()}\n   "
                           f"https://en.wikipedia.org/wiki/{_up.quote(pg['title'].replace(' ', '_'))}")
    except Exception:
        pass
    return ("(Web search engine unavailable; these are news headlines and Wikipedia.)\n" + "\n".join(out)) if out else None


def _groq_search(query: str) -> str | None:
    """Web search through Groq's browser_search tool. Uses a lot of Groq's free daily tokens: last resort."""
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1", max_retries=0, timeout=60)
        r = client.chat.completions.create(
            model=os.environ.get("JARVIS_SEARCH_MODEL", "openai/gpt-oss-20b"),
            messages=[{"role": "user", "content": f"Search the web for: {query}\n\nToday is {datetime.now():%d %B %Y}. "
                       "Reply with the key facts you found (numbers, names, dates), each with its source name and URL. "
                       "Plain text, concise, no tables."}],
            tools=[{"type": "browser_search"}], tool_choice="required", reasoning_effort="low")
    except Exception as e:
        print(f"[search] Groq search failed: {str(e)[:120]}")
        return None
    text = _re.sub(r"【[^】]*】", "", r.choices[0].message.content or "").strip()
    return text or None


def _backup_search(query: str) -> str:
    return (_free_search(query) or _groq_search(query)
            or f"No results found for '{query}' (the web search engine is blocking automated searches right now).")


def web_search(inp: dict, ctx: ToolContext) -> str:
    global _ddg_blocked_until
    query = inp["query"]
    if time.time() < _ddg_blocked_until:
        return _backup_search(query)
    data = _up.urlencode({"q": query}).encode()
    req = _ur.Request("https://html.duckduckgo.com/html/", data=data, headers=_UA)
    with _ur.urlopen(req, timeout=20) as r:
        page = r.read().decode("utf-8", errors="replace")
    if "result__a" not in page and ("anomaly" in page or "bots use DuckDuckGo" in page):
        _ddg_blocked_until = time.time() + 30 * 60
        print("[search] DuckDuckGo is showing a bot challenge; using the backup search for 30 minutes")
        return _backup_search(query)
    results = []
    for m in _re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]+class="result__a"|$)',
                          page, flags=_re.S):
        href, title, rest = m.groups()
        if "uddg=" in href:  # DuckDuckGo redirect link -> real URL
            href = _up.unquote(_up.parse_qs(_up.urlparse(href).query).get("uddg", [href])[0])
        snip = _re.search(r'class="result__snippet"[^>]*>(.*?)</a>', rest, flags=_re.S)
        results.append(f"{len(results) + 1}. {_strip_tags(title)}\n   {href}\n   {_strip_tags(snip.group(1)) if snip else ''}")
        if len(results) >= int(inp.get("max_results", 6)):
            break
    return "\n".join(results) if results else f"No results found for '{query}'."


def fetch_webpage(inp: dict, ctx: ToolContext) -> str:
    url = inp["url"]
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    with _ur.urlopen(_ur.Request(url, headers=_UA), timeout=25) as r:
        raw = r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    raw = _re.sub(r"(?is)<(script|style|noscript|svg|nav|footer|header)[^>]*>.*?</\1>", " ", raw)
    text = _re.sub(r"[ \t]+", " ", _strip_tags(_re.sub(r"(?i)<(br|p|div|li|h\d|tr)[^>]*>", "\n", raw)))
    text = _re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return text[:15_000] + ("\n[... page truncated]" if len(text) > 15_000 else "")


WEB_TOOLS = [
    ({"name": "web_search",
      "description": "Search the live web (news, weather, prices, scores, facts). Returns titles, URLs and snippets; "
                     "use fetch_webpage to read a result in full.",
      "input_schema": _obj({"query": {"type": "string"}, "max_results": {"type": "integer"}}, ["query"])}, web_search),
    ({"name": "fetch_webpage", "description": "Download a web page and return its readable text.",
      "input_schema": _obj({"url": {"type": "string"}}, ["url"])}, fetch_webpage),
]
WEB_TOOL_DEFINITIONS = [d for d, _ in WEB_TOOLS]
_HANDLERS.update({d["name"]: fn for d, fn in WEB_TOOLS})


# --------------------------------------------------------------------------- #
# Daily life skills: briefing, weather, YouTube, prayer times, alarms, language
# --------------------------------------------------------------------------- #
def daily_briefing(inp: dict, ctx: ToolContext) -> str:
    parts = [f"Date and time: {datetime.now():%A, %d %B %Y, %I:%M %p}."]
    loc = _sched.get_location()
    parts.append(f"Location: {loc['city']}{', ' + loc['country'] if loc.get('country') else ''}.")
    for label, fn in (("Weather", _sched.weather_text), ("Prayer", _sched.prayer_text)):
        try:
            parts.append(f"{label}: {fn()}")
        except Exception as e:
            parts.append(f"{label}: unavailable ({type(e).__name__}).")
    alarms = [a for a in _sched.list_alarms() if _sched.next_fire(a)]
    parts.append("Alarms: " + ("; ".join(_sched.describe_alarm(a) for a in alarms) if alarms else "none set") + ".")
    if ctx.timers:
        parts.append("Timers: " + "; ".join(f"{m} at {d:%H:%M}" for _, m, d in ctx.timers.values()) + ".")
    if psutil:
        bat = psutil.sensors_battery()
        parts.append(f"PC: CPU {psutil.cpu_percent(interval=0.3)}%, RAM {psutil.virtual_memory().percent}%"
                     + (f", battery {bat.percent:.0f}%{' charging' if bat.power_plugged else ''}" if bat else "") + ".")
    try:
        parts.append("Top headlines: " + " | ".join(_sched.headlines(int(inp.get("headlines", 5)))))
    except Exception as e:
        parts.append(f"Headlines: unavailable ({type(e).__name__}).")
    parts.append("(Summarise this as a warm, concise spoken briefing: greeting, weather, next prayer, "
                 "alarms/timers, 3 headlines, PC note only if something needs attention.)")
    return "\n".join(parts)


def get_weather(inp: dict, ctx: ToolContext) -> str:
    return _sched.weather_text(inp.get("city") or None)


def play_youtube(inp: dict, ctx: ToolContext) -> str:
    query = inp["query"].strip()
    req = _ur.Request("https://www.youtube.com/results?search_query=" + quote_plus(query), headers=_UA)
    with _ur.urlopen(req, timeout=20) as r:
        page = r.read().decode("utf-8", errors="replace")
    m = _re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".{0,4000}?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"',
                   page, _re.S)
    if m:
        vid = m.group(1)
        try:
            title = json.loads(f'"{m.group(2)}"')
        except ValueError:
            title = query
    else:
        ids = _re.findall(r'"videoId":"([\w-]{11})"', page)
        vid, title = (ids[0], query) if ids else (None, query)
    if not vid:
        webbrowser.open("https://www.youtube.com/results?search_query=" + quote_plus(query))
        return f"Couldn't pick a video, so I opened YouTube search results for '{query}'."
    webbrowser.open(f"https://www.youtube.com/watch?v={vid}&autoplay=1")
    return f"Now playing on YouTube: {title}"


def prayer_times_tool(inp: dict, ctx: ToolContext) -> str:
    return _sched.prayer_text(inp.get("city") or None)


def prayer_reminders(inp: dict, ctx: ToolContext) -> str:
    on = bool(inp["enabled"])
    _sched.set_setting("prayer_reminders", on)
    lead = _sched.Scheduler.prayer_lead()
    return (f"Prayer reminders are on: I'll remind you {lead} minutes before each prayer and at prayer time."
            if on else "Prayer reminders are off.")


def set_alarm(inp: dict, ctx: ToolContext) -> str:
    a = _sched.add_alarm(inp["time"], inp.get("label", ""), inp.get("repeat", "once"), inp.get("days"))
    return "Alarm set: " + _sched.describe_alarm(a)


def list_alarms_tool(_: dict, ctx: ToolContext) -> str:
    alarms = _sched.list_alarms()
    return "\n".join(_sched.describe_alarm(a) for a in alarms) if alarms else "No alarms set."


def delete_alarm_tool(inp: dict, ctx: ToolContext) -> str:
    return f"Deleted alarm #{inp['id']}." if _sched.delete_alarm(int(inp["id"])) else f"No alarm #{inp['id']}."


def set_language(inp: dict, ctx: ToolContext) -> str:
    lang = "ur" if str(inp["language"]).lower().startswith("ur") else "en"
    if ctx.set_language:
        ctx.set_language(lang)
    else:
        ctx.language = lang
    return ("Language set to Urdu: I'll listen for Urdu and reply in Urdu with an Urdu voice."
            if lang == "ur" else "Language set to English.")


def set_chat_script(inp: dict, ctx: ToolContext) -> str:
    script = "urdu" if str(inp["script"]).lower().startswith("u") else "roman"
    if ctx.set_chat_script:
        ctx.set_chat_script(script)
    else:
        _sched.set_setting("chat_script", script)
    return ("Done: the chat is now typed in Urdu script (English replies are translated into Urdu)."
            if script == "urdu" else "Done: the chat is typed in English letters again (Roman Urdu for Urdu).")


def set_assistant_name(inp: dict, ctx: ToolContext) -> str:
    try:
        name = ctx.set_name(inp["name"]) if ctx.set_name else _sched.set_agent_name(inp["name"])
    except ValueError as e:
        return f"Couldn't rename: {e}"
    return (f"Done: my name is now {name}. Introduce yourself as {name} from now on. "
            "(A matching voice can be picked in Settings: Live voice, e.g. Kore or Aoede for a female voice.)")


def set_theme_tool(inp: dict, ctx: ToolContext) -> str:
    mode = str(inp["theme"]).lower()
    mode = "light" if mode.startswith("l") else "system" if mode.startswith(("s", "a", "w")) else "dark"
    if ctx.set_theme:
        ctx.set_theme(mode)
    else:
        _sched.set_setting("theme", mode)
    return {"light": "Switched to the light theme.", "dark": "Switched to the dark theme.",
            "system": "The theme now follows Windows (light or dark)."}[mode]


def set_location_tool(inp: dict, ctx: ToolContext) -> str:
    loc = _sched.set_location(inp["city"], inp.get("country", ""))
    found = " (found on the map)" if loc.get("lat") is not None else " (couldn't find exact coordinates; using the city name)"
    return f"Location saved: {loc['city']}{', ' + loc['country'] if loc.get('country') else ''}{found}."


LIFE_TOOLS = [
    ({"name": "daily_briefing",
      "description": "Collect everything for the user's daily briefing: date, weather, prayer times, alarms, timers, PC health and top news headlines. "
                     "Use whenever the user asks for a briefing, a morning update or what's happening today, then summarise it as a short spoken briefing.",
      "input_schema": _obj({"headlines": {"type": "integer", "description": "How many headlines (default 5)."}})}, daily_briefing),
    ({"name": "get_weather", "description": "Current weather and today's forecast for the user's location, or for a named city.",
      "input_schema": _obj({"city": {"type": "string"}})}, get_weather),
    ({"name": "play_youtube",
      "description": "Find a song or video on YouTube and start playing it right away in the browser, e.g. 'Atif Aslam Tajdar-e-Haram' or 'Naruto opening'. "
                     "Use this (not search_web_in_browser) whenever the user wants to play, listen to or watch something.",
      "input_schema": _obj({"query": {"type": "string"}}, ["query"])}, play_youtube),
    ({"name": "prayer_times", "description": "Today's namaz/prayer times (Fajr, Dhuhr, Asr, Maghrib, Isha) for the user's location or a named city, and the next prayer.",
      "input_schema": _obj({"city": {"type": "string"}})}, prayer_times_tool),
    ({"name": "prayer_reminders", "description": "Turn the automatic prayer reminders (before and at each prayer time) on or off.",
      "input_schema": _obj({"enabled": {"type": "boolean"}}, ["enabled"])}, prayer_reminders),
    ({"name": "set_alarm",
      "description": "Set an alarm at a clock time that rings even across restarts. repeat: once, daily, weekdays, weekends, or days (with days like ['mon','wed']). "
                     "Use set_timer instead for 'in N minutes'.",
      "input_schema": _obj({"time": {"type": "string", "description": "Clock time, e.g. '07:30' or '6:45 pm'."},
                            "label": {"type": "string"},
                            "repeat": {"type": "string", "enum": ["once", "daily", "weekdays", "weekends", "days"]},
                            "days": {"type": "array", "items": {"type": "string"}}}, ["time"])}, set_alarm),
    ({"name": "list_alarms", "description": "List the saved alarms with ids and when they ring next.", "input_schema": _obj({})}, list_alarms_tool),
    ({"name": "delete_alarm", "description": "Delete an alarm by id.", "input_schema": _obj({"id": {"type": "integer"}}, ["id"])}, delete_alarm_tool),
    ({"name": "set_language",
      "description": "Switch how Jarvis listens and speaks: 'urdu' (Urdu speech recognition, Urdu replies, Urdu voice) or 'english'. "
                     "Use when the user asks to talk in Urdu (e.g. 'Urdu mein baat karo') or in English.",
      "input_schema": _obj({"language": {"type": "string", "enum": ["urdu", "english"]}}, ["language"])}, set_language),
    ({"name": "set_chat_script",
      "description": "How the chat on screen is written (not how you speak). 'roman' (default): everything in English "
                     "letters, Urdu as Roman Urdu. 'urdu': the chat is typed in Urdu script, English replies translated "
                     "into Urdu. Use 'urdu' ONLY when the user asks for it, e.g. 'Urdu mein type karke do', 'Urdu mein "
                     "likh ke do', 'chat ko Urdu mein translate karo'; 'roman' for 'English mein likho' / 'Roman mein likho'.",
      "input_schema": _obj({"script": {"type": "string", "enum": ["roman", "urdu"]}}, ["script"])}, set_chat_script),
    ({"name": "set_assistant_name",
      "description": "Rename the assistant (you). Use when the user wants to call you something else, "
                     "e.g. 'your name is Maya now', 'tumhara naam Friday rakh do'. Everything keeps working; only the name changes.",
      "input_schema": _obj({"name": {"type": "string"}}, ["name"])}, set_assistant_name),
    ({"name": "set_theme",
      "description": "Switch the Command Center's look: 'light', 'dark', or 'system' (follow Windows). "
                     "Use for 'light mode', 'dark mode on karo', 'white theme' and similar.",
      "input_schema": _obj({"theme": {"type": "string", "enum": ["light", "dark", "system"]}}, ["theme"])}, set_theme_tool),
    ({"name": "set_location", "description": "Save the user's city (and country) so weather and prayer times are exact.",
      "input_schema": _obj({"city": {"type": "string"}, "country": {"type": "string"}}, ["city"])}, set_location_tool),
]
TOOL_DEFINITIONS += [d for d, _ in LIFE_TOOLS]
_HANDLERS.update({d["name"]: fn for d, fn in LIFE_TOOLS})


# --------------------------------------------------------------------------- #
# PC control skills: close apps, power, brightness, Wi-Fi/Bluetooth,
# screenshots and Downloads cleanup
# --------------------------------------------------------------------------- #
_PROC_ALIASES = {
    "chrome": ["chrome"], "google chrome": ["chrome"], "edge": ["msedge"], "microsoft edge": ["msedge"],
    "firefox": ["firefox"], "notepad": ["notepad"], "calculator": ["CalculatorApp", "calc"], "calc": ["CalculatorApp", "calc"],
    "word": ["WINWORD"], "excel": ["EXCEL"], "powerpoint": ["POWERPNT"], "outlook": ["OUTLOOK", "olk"],
    "vscode": ["Code"], "vs code": ["Code"], "visual studio code": ["Code"], "spotify": ["Spotify"],
    "whatsapp": ["WhatsApp", "WhatsApp.Root"], "telegram": ["Telegram"], "discord": ["Discord"], "zoom": ["Zoom"],
    "teams": ["ms-teams", "Teams"], "vlc": ["vlc"], "paint": ["mspaint"], "file explorer": ["explorer"],
    "steam": ["steam"], "obs": ["obs64"], "task manager": ["Taskmgr"],
}
# Never close these: Jarvis itself, Windows essentials, or the shell.
_PROTECTED = {"python", "pythonw", "powershell", "pwsh", "cmd", "conhost", "csrss", "winlogon", "lsass",
              "svchost", "dwm", "services", "smss", "wininit", "system", "explorer", "claude"}


def close_app(inp: dict, ctx: ToolContext) -> str:
    name = inp["name"].strip()
    force = bool(inp.get("force"))
    targets = _PROC_ALIASES.get(name.lower(), [name.removesuffix(".exe")])
    if any(t.lower() in _PROTECTED for t in targets):
        if not ctx.approve(f"'{name}' is part of Windows or Jarvis itself. Close it anyway?", kind="close_system"):
            return "Okay, I left it running."
    if force and not ctx.approve(f"Force-close {name}? Unsaved work in it will be lost.", kind="force_close"):
        return "Okay, I didn't force-close it."
    if not psutil:
        return "Can't list running apps (psutil missing)."
    procs = [p for p in psutil.process_iter(["name"])
             if p.info["name"] and p.info["name"].lower().removesuffix(".exe") in {t.lower() for t in targets}]
    if not procs:
        return f"{name} isn't running."
    names = {p.info['name'] for p in procs}
    # Unsaved work shows as a '*' in the window title (Notepad, Word, VS Code...): ask before closing.
    pids = ",".join(str(p.pid) for p in procs)
    titles = [t for t in _ps(f"Get-Process -Id {pids} -ErrorAction SilentlyContinue | "
                             "ForEach-Object { $_.MainWindowTitle }").stdout.splitlines() if t.strip()]
    unsaved = [t for t in titles if t.lstrip().startswith("*") or "unsaved" in t.lower()]
    if unsaved and not ctx.approve(f"{name} has unsaved work ({unsaved[0][:60]}). Close it anyway? It may ask you to save.", kind="close_unsaved"):
        return f"Okay, I left {name} open because it has unsaved work."
    for n in names:  # polite close first (the app can still ask to save), then force if asked
        subprocess.run(["taskkill", "/IM", n] + (["/F"] if force else []) + ["/T"], capture_output=True, text=True)
    time.sleep(1.5)
    left = [p for p in procs if p.is_running()]
    if left and not force:
        return (f"Asked {name} to close; {len(left)} window(s) are still open (it may be asking to save). "
                "Say 'force close' if you want me to end it.")
    return f"Closed {name}."


def power_action(inp: dict, ctx: ToolContext) -> str:
    action = inp["action"]
    delay = max(0, min(int(inp.get("delay_seconds", 30)), 3600))
    if action == "cancel":
        r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True)
        return "Cancelled the pending shutdown/restart." if r.returncode == 0 else "There was no shutdown or restart pending."
    labels = {"shutdown": "shut down", "restart": "restart", "sleep": "put the PC to sleep",
              "hibernate": "hibernate", "sign_out": "sign you out of Windows"}
    if action not in labels:
        return f"Unknown action {action}."
    when = f" in {delay} seconds" if action in ("shutdown", "restart") and delay else ""
    if not ctx.approve(f"{_sched.agent_name()} wants to {labels[action]}{when}. Save your work first. Go ahead?", kind="power"):
        return "Cancelled. Nothing was changed."
    if action == "shutdown":
        subprocess.run(["shutdown", "/s", "/t", str(delay)], check=False)
        return f"Shutting down in {delay} seconds. Say 'cancel shutdown' to stop it."
    if action == "restart":
        subprocess.run(["shutdown", "/r", "/t", str(delay)], check=False)
        return f"Restarting in {delay} seconds. Say 'cancel restart' to stop it."
    if action == "sign_out":
        subprocess.run(["shutdown", "/l"], check=False)
        return "Signing out."
    mode = "Hibernate" if action == "hibernate" else "Suspend"
    threading.Timer(2.0, lambda: _ps(
        "Add-Type -AssemblyName System.Windows.Forms; "
        f"[System.Windows.Forms.Application]::SetSuspendState('{mode}', $false, $false)")).start()
    return "Going to sleep now." if action == "sleep" else "Hibernating now."


def set_brightness(inp: dict, ctx: ToolContext) -> str:
    cur = _ps("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1).CurrentBrightness").stdout.strip()
    if not cur.isdigit():
        return "This screen doesn't allow brightness control from Windows (common on desktop monitors)."
    level = inp.get("level")
    change = inp.get("change")
    if level is None and change is None:
        return f"Brightness is {cur}%."
    new = int(level) if level is not None else int(cur) + int(change)
    new = max(0, min(100, new))
    _ps(f"(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods).WmiSetBrightness(1, {new}) | Out-Null")
    return f"Brightness set to {new}% (was {cur}%)."


_RADIO_PS = r"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, $t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
[Windows.Devices.Radios.Radio, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState, Windows.System.Devices, ContentType = WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
$r = $radios | Where-Object { $_.Kind -eq '__KIND__' } | Select-Object -First 1
if (-not $r) { 'missing'; exit }
if ('__STATE__' -ne 'status') { Await ($r.SetStateAsync('__STATE__')) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null; Start-Sleep -Milliseconds 400 }
$r.State
"""


def _radio(kind: str, state: str) -> str:
    return _ps(_RADIO_PS.replace("__KIND__", kind).replace("__STATE__", state), timeout=30).stdout.strip().splitlines()[-1:] or ["?"]


def wireless(inp: dict, ctx: ToolContext) -> str:
    device = "WiFi" if inp["device"].lower().replace("-", "") in ("wifi", "wlan") else "Bluetooth"
    label = "Wi-Fi" if device == "WiFi" else "Bluetooth"
    action = inp.get("action", "status")
    if action == "status":
        state = _radio(device, "status")[0]
        return f"{label} is {state.lower()}." if state != "missing" else f"This PC has no {label} radio."
    turn_on = action == "on"
    back_in = int(inp.get("back_on_after_minutes", 0) or 0)
    if device == "WiFi" and not turn_on:
        extra = f" I'll switch it back on after {back_in} minutes." if back_in else \
            " While it's off I can't think or understand speech (I need the internet), so turn it back on from the taskbar."
        if not ctx.approve(f"Turn Wi-Fi off?{extra}", kind="wifi_off"):
            return "Okay, Wi-Fi stays on."
    state = _radio(device, "On" if turn_on else "Off")[0]
    if state == "missing":
        return f"This PC has no {label} radio."
    if device == "WiFi" and not turn_on and back_in:
        threading.Timer(back_in * 60, lambda: (_radio("WiFi", "On"), ctx.notify("Wi-Fi is back on.", "info"))).start()
    return f"{label} is now {state.lower()}."


def take_screenshot(inp: dict, ctx: ToolContext) -> str:
    folder = Path(os.path.expanduser(inp.get("folder") or "")) if inp.get("folder") else \
        Path(os.path.join(os.environ.get("USERPROFILE", str(Path.home())), "Pictures", "Jarvis Screenshots"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"Screenshot {datetime.now():%Y-%m-%d %H.%M.%S}.png"
    _ps(r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
[System.Drawing.Graphics]::FromImage($bmp).CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$bmp.Save('__PATH__', [System.Drawing.Imaging.ImageFormat]::Png)
""".replace("__PATH__", _ps_quote(path)))
    if not path.exists():
        return "The screenshot failed."
    if inp.get("open_folder"):
        subprocess.run(["explorer", "/select,", str(path)], check=False)
    return f"Screenshot saved: {path}"


def _scan(folder: Path, older_than_days: int, min_mb: float, pattern: str = "*") -> list[Path]:
    cutoff = time.time() - older_than_days * 86400
    out = []
    for f in folder.glob(pattern):
        try:
            st = f.stat()
        except OSError:
            continue
        if f.is_file() and st.st_mtime < cutoff and st.st_size >= min_mb * 2**20:
            out.append(f)
    return sorted(out, key=lambda f: f.stat().st_size, reverse=True)


def _downloads() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"


def _folder_problem(folder: Path, pattern: str) -> str | None:
    """Why this folder/pattern must not be cleaned, or None if it's fine."""
    if any(sep in pattern for sep in ("/", "\\")) or ".." in pattern:
        return "The pattern must be a simple file pattern like '*.zip'."
    f = folder.resolve()
    home = Path.home().resolve()
    if f == Path(f.anchor) or f == home:
        return f"{f} is too broad; pick a specific folder such as Downloads."
    protected = [os.environ.get("SystemRoot", r"C:\Windows"), os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.environ.get("ProgramData", r"C:\ProgramData"),
                 str(home / "AppData"), str(ROOT)]
    for b in protected:
        b = Path(b).resolve()
        if f == b or b in f.parents:
            return f"{f} is a system or Jarvis folder, so I won't clean it."
    return None


def find_old_files(inp: dict, ctx: ToolContext) -> str:
    folder = Path(os.path.expanduser(inp["folder"])) if inp.get("folder") else _downloads()
    if not folder.is_dir():
        return f"Folder not found: {folder}"
    pattern = inp.get("pattern") or "*"
    if any(sep in pattern for sep in ("/", "\\")) or ".." in pattern:
        return "The pattern must be a simple file pattern like '*.zip'."
    days = int(inp.get("older_than_days", 30))
    files = _scan(folder, days, float(inp.get("min_size_mb", 0)), pattern)
    if not files:
        return f"No files older than {days} days in {folder}."
    total = sum(f.stat().st_size for f in files)
    top = "\n".join(f"- {f.name} ({f.stat().st_size / 2**20:.1f} MB, {datetime.fromtimestamp(f.stat().st_mtime):%d %b %Y})"
                    for f in files[:15])
    more = f"\n…and {len(files) - 15} more" if len(files) > 15 else ""
    return f"{len(files)} files older than {days} days in {folder}, {total / 2**20:.0f} MB in total:\n{top}{more}"


def clean_folder(inp: dict, ctx: ToolContext) -> str:
    folder = Path(os.path.expanduser(inp["folder"])) if inp.get("folder") else _downloads()
    if not folder.is_dir():
        return f"Folder not found: {folder}"
    pattern = inp.get("pattern") or "*"
    problem = _folder_problem(folder, pattern)
    if problem:
        return problem
    days = int(inp.get("older_than_days", 30))
    files = _scan(folder, days, float(inp.get("min_size_mb", 0)), pattern)
    if not files:
        return f"Nothing to clean: no files older than {days} days in {folder}."
    total = sum(f.stat().st_size for f in files) / 2**20
    preview = ", ".join(f.name for f in files[:6]) + (f" and {len(files) - 6} more" if len(files) > 6 else "")
    if not ctx.approve(kind="clean", question=f"Move {len(files)} files ({total:.0f} MB) older than {days} days from {folder} to the Recycle Bin?\n    {preview}\n"
                       "(You can restore them from the Recycle Bin.)"):
        return "Okay, I didn't touch anything."
    moved = 0
    for f in files:
        r = _ps("Add-Type -AssemblyName Microsoft.VisualBasic; "
                "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile('" + _ps_quote(f) + "', "
                "'OnlyErrorDialogs', 'SendToRecycleBin')")
        if r.returncode == 0 and not f.exists():
            moved += 1
    return f"Moved {moved} of {len(files)} files ({total:.0f} MB) to the Recycle Bin."


PC_TOOLS = [
    ({"name": "close_app",
      "description": "Close a running app by name, e.g. 'chrome', 'word', 'spotify'. Closes politely so the app can ask to save; "
                     "set force=true only if the user says force close (asks for approval).",
      "input_schema": _obj({"name": {"type": "string"}, "force": {"type": "boolean"}}, ["name"])}, close_app),
    ({"name": "power_action",
      "description": "Shut down, restart, sleep, hibernate or sign out of the PC (always asks the user to approve), or cancel a pending shutdown/restart.",
      "input_schema": _obj({"action": {"type": "string", "enum": ["shutdown", "restart", "sleep", "hibernate", "sign_out", "cancel"]},
                            "delay_seconds": {"type": "integer", "description": "For shutdown/restart; default 30."}}, ["action"])}, power_action),
    ({"name": "set_brightness",
      "description": "Read or change screen brightness: level = exact percent (0-100) or change = +/- percent (e.g. 20 or -20). No arguments = report current level.",
      "input_schema": _obj({"level": {"type": "integer"}, "change": {"type": "integer"}})}, set_brightness),
    ({"name": "wireless",
      "description": "Turn Wi-Fi or Bluetooth on/off or report its status. Turning Wi-Fi off asks for approval because Jarvis needs the internet; "
                     "back_on_after_minutes switches it back on automatically.",
      "input_schema": _obj({"device": {"type": "string", "enum": ["wifi", "bluetooth"]},
                            "action": {"type": "string", "enum": ["on", "off", "status"]},
                            "back_on_after_minutes": {"type": "integer"}}, ["device"])}, wireless),
    ({"name": "take_screenshot",
      "description": "Take a screenshot and SAVE it as a PNG (default folder: Pictures\\Jarvis Screenshots). Use look_at_screen instead when you need to see the screen yourself.",
      "input_schema": _obj({"folder": {"type": "string"}, "open_folder": {"type": "boolean"}})}, take_screenshot),
    ({"name": "find_old_files",
      "description": "List old (and optionally large) files in a folder, Downloads by default: older_than_days (default 30), min_size_mb, pattern like '*.zip'.",
      "input_schema": _obj({"folder": {"type": "string"}, "older_than_days": {"type": "integer"},
                            "min_size_mb": {"type": "number"}, "pattern": {"type": "string"}})}, find_old_files),
    ({"name": "clean_folder",
      "description": "Clean up a folder (Downloads by default) by moving old files to the Recycle Bin, never deleting permanently. "
                     "Shows the user what will move and asks for approval. Same filters as find_old_files.",
      "input_schema": _obj({"folder": {"type": "string"}, "older_than_days": {"type": "integer"},
                            "min_size_mb": {"type": "number"}, "pattern": {"type": "string"}})}, clean_folder),
]
TOOL_DEFINITIONS += [d for d, _ in PC_TOOLS]
_HANDLERS.update({d["name"]: fn for d, fn in PC_TOOLS})

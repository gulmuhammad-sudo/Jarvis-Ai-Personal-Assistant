"""Developer helpers (Phase 5), all read-only: which dev tools are installed, a project's git status, and which
program is listening on a port ("what's using 3000?"). Nothing here changes files, settings or processes.
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import shutil
import subprocess
from pathlib import Path

try:
    import psutil
except ImportError:          # pragma: no cover
    psutil = None

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# label -> (command, args); the first line with a version number is shown
TOOLS = {
    "Git": ("git", ["--version"]), "Python": ("python", ["--version"]), "Node.js": ("node", ["--version"]),
    "npm": ("npm", ["--version"]), "VS Code": ("code", ["--version"]), "Java": ("java", ["-version"]),
    ".NET": ("dotnet", ["--version"]), "Docker": ("docker", ["--version"]), "GitHub CLI": ("gh", ["--version"]),
    "Go": ("go", ["version"]), "Rust": ("rustc", ["--version"]), "PHP": ("php", ["--version"]),
}


def _version(cmd: str, args: list[str]) -> str | None:
    exe = shutil.which(cmd)
    if not exe:
        return None
    try:
        call = [exe, *args] if not exe.lower().endswith((".cmd", ".bat")) else ["cmd", "/c", exe, *args]
        r = subprocess.run(call, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=8, creationflags=_NOWIN)
    except (OSError, subprocess.TimeoutExpired):
        return "installed"
    for ln in ((r.stdout or "") + "\n" + (r.stderr or "")).splitlines():
        m = re.search(r"\d+\.\d+(\.\d+)?", ln)
        if m:
            return m.group(0)
    return "installed"


def tools_installed() -> dict[str, str | None]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {label: pool.submit(_version, c, a) for label, (c, a) in TOOLS.items()}
    return {label: f.result() for label, f in futures.items()}


def describe_tools(found: dict[str, str | None]) -> str:
    have = [f"{k} {v}" for k, v in found.items() if v]
    missing = [k for k, v in found.items() if not v]
    return ("Installed: " + (", ".join(have) or "none of the usual tools")) + (f"\nNot found: {', '.join(missing)}" if missing else "")


def _git(path: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=15, creationflags=_NOWIN)
    if r.returncode != 0:
        raise ValueError((r.stderr or r.stdout or "git failed").strip().splitlines()[-1][:200])
    return r.stdout


def git_status(path: str) -> str:
    if not shutil.which("git"):
        return "Git isn't installed."
    p = Path(os.path.expandvars(os.path.expanduser(str(path or ".")))).resolve()
    if not p.is_dir():
        return f"There's no folder at {p}."
    try:
        root = Path(_git(p, "rev-parse", "--show-toplevel").strip())
    except ValueError:
        return f"{p} isn't inside a git repository."
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    status = _git(root, "status", "--porcelain=v1", "--branch")
    lines = status.splitlines()
    track = lines[0] if lines and lines[0].startswith("##") else ""
    files = [ln for ln in lines if not ln.startswith("##")]
    ahead = re.search(r"ahead (\d+)", track)
    behind = re.search(r"behind (\d+)", track)
    changed = sum(1 for f in files if not f.startswith("??"))
    new = sum(1 for f in files if f.startswith("??"))
    log = _git(root, "log", "-5", "--pretty=format:%h %ad %s", "--date=short").strip()
    out = [f"Repository {root.name} on branch {branch}"
           + (f", {ahead.group(1)} commit(s) not pushed" if ahead else "") + (f", {behind.group(1)} behind" if behind else "") + ".",
           f"Changed files: {changed}, new untracked files: {new}." if files else "Working tree clean.",
           "Last commits:\n" + (log or "(none)")]
    return "\n".join(out)


def ports(port: int | None = None) -> str:
    """Programs listening for connections (optionally on one port)."""
    if not psutil:
        return "Can't list ports (psutil missing)."
    try:
        conns = psutil.net_connections(kind="inet")
    except (psutil.AccessDenied, OSError) as e:
        return f"Windows didn't let me list the ports: {e}"
    rows = {}
    for c in conns:
        if c.status != psutil.CONN_LISTEN or not c.laddr:
            continue
        if port and c.laddr.port != int(port):
            continue
        try:
            name = psutil.Process(c.pid).name() if c.pid else "System"
        except (psutil.Error, OSError):
            name = f"pid {c.pid}"
        rows[(c.laddr.port, name)] = f"{c.laddr.port}: {name} (pid {c.pid}, {c.laddr.ip})"
    if not rows:
        return f"Nothing is listening on port {port}." if port else "No programs are listening on any port."
    return "\n".join(v for _, v in sorted(rows.items())[:60])

"""Brain backend that uses your Claude account (via the Claude Code CLI) instead of an API key.

Each message runs `claude -p` in headless mode. Jarvis's tools are offered to it through a
small MCP server (mcp_server.py), and the conversation continues with --resume. Only the
Jarvis tools plus web search and web fetch are enabled. Claude Code's own file-editing
and shell tools are switched off.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

from . import memory, tools
from .brain import ProviderError, system_prompt
from .bridge import start_bridge
from .config import DATA_DIR

MCP_PREFIX = "mcp__jarvis__"
SESSION_DIR = DATA_DIR / "claude_session"
SESSION_DIR.mkdir(exist_ok=True)


def find_claude() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    for p in (Path.home() / ".local" / "bin" / "claude.exe",
              Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"):
        if p.exists():
            return str(p)
    return None


def login_status(claude: str) -> tuple[bool, str]:
    """(logged_in, detail) for the Claude Code CLI."""
    try:
        r = subprocess.run([claude, "auth", "status"], capture_output=True, text=True,
                           timeout=30, stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    out = (r.stdout + r.stderr).strip()
    try:
        data = json.loads(r.stdout)
        return bool(data.get("loggedIn")), out
    except (json.JSONDecodeError, AttributeError):
        return r.returncode == 0 and "not logged in" not in out.lower(), out


class ClaudeCodeBrain:
    def __init__(self, ctx: tools.ToolContext,
                 on_text: Callable[[str], None],
                 on_tool: Callable[[str, dict], None]):
        from .brain import SYSTEM_PROMPT
        self._template = SYSTEM_PROMPT
        self.claude = find_claude()
        self.ctx = ctx
        self.on_text = on_text
        self.on_tool = on_tool
        self.session_id: str | None = None
        self._pending_note: str | None = None
        bridge_url, bridge_token = start_bridge(ctx)
        self.mcp_config = SESSION_DIR / "mcp.json"
        self.mcp_config.write_text(json.dumps({"mcpServers": {"jarvis": {
            "command": sys.executable,
            "args": [str(Path(__file__).with_name("mcp_server.py"))],
            "env": {"JARVIS_BRIDGE_URL": bridge_url, "JARVIS_BRIDGE_TOKEN": bridge_token,
                    "PYTHONIOENCODING": "utf-8"},
        }}}), encoding="utf-8")
        self.prompt_file = SESSION_DIR / "system_prompt.txt"
        self._write_prompt()

    def _write_prompt(self) -> None:
        self.prompt_file.write_text(
            system_prompt(self._template), encoding="utf-8")

    def reset(self) -> None:
        self.session_id = None
        self._write_prompt()

    def set_voice_mode(self, on: bool) -> None:
        from .brain import VOICE_OFF_NOTE, VOICE_ON_NOTE
        self._pending_note = VOICE_ON_NOTE if on else VOICE_OFF_NOTE

    def ask(self, user_text: str) -> str:
        if not self.claude:
            err = ProviderError("Claude Code isn't installed on this PC")
            err.permanent = True
            raise err
        prompt = user_text
        if self._pending_note:
            prompt = f"[{self._pending_note}]\n\n{user_text}"
            self._pending_note = None

        cmd = [self.claude, "-p",
               "--output-format", "stream-json", "--verbose",
               "--system-prompt-file", str(self.prompt_file),
               "--mcp-config", str(self.mcp_config), "--strict-mcp-config",
               "--tools", "WebSearch,WebFetch",
               "--allowedTools", "mcp__jarvis,WebSearch,WebFetch",
               "--max-turns", "25"]
        if os.environ.get("JARVIS_CC_MODEL"):
            cmd += ["--model", os.environ["JARVIS_CC_MODEL"]]
        if self.session_id:
            cmd += ["--resume", self.session_id]

        final_text, result_text, is_error = "", "", False
        try:
            proc = subprocess.Popen(cmd, cwd=SESSION_DIR, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise ProviderError(f"couldn't start Claude Code: {e}")
        proc.stdin.write(prompt)
        proc.stdin.close()

        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                for block in (ev.get("message") or {}).get("content", []):
                    if ev.get("error") or (ev.get("message") or {}).get("model") == "<synthetic>":
                        continue  # CLI error placeholder; reported once from the result below
                    if block.get("type") == "text" and block.get("text", "").strip():
                        final_text = block["text"].strip()
                        self.on_text(final_text)
                    elif block.get("type") == "tool_use":
                        name = block.get("name", "")
                        self.on_tool(name.removeprefix(MCP_PREFIX), block.get("input") or {})
            elif ev.get("type") == "result":
                self.session_id = ev.get("session_id") or self.session_id
                result_text = (ev.get("result") or "").strip()
                is_error = bool(ev.get("is_error"))
        proc.wait()
        stderr = proc.stderr.read().strip()

        if is_error or (proc.returncode and not final_text):
            detail = result_text or stderr or f"exit code {proc.returncode}"
            if detail and "session" in detail.lower() and self.session_id:
                self.session_id = None  # stale session; start fresh next time
            if "not logged in" in detail.lower() or "/login" in detail:
                err = ProviderError("your Claude account isn't signed in (run: claude auth login)")
                err.permanent = True
                raise err
            if "limit" in detail.lower():
                raise ProviderError(f"your Claude usage limit was hit ({detail[:200]})")
            raise ProviderError(f"Claude Code reported a problem: {detail[:300]}")
        if not final_text and result_text:
            self.on_text(result_text)
            final_text = result_text
        return final_text

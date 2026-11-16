"""Tool bridge: lets the Claude Code backend run Jarvis's tools inside this process.

Claude Code talks to jarvis/mcp_server.py (a tiny MCP server it starts itself), and that
server forwards each tool call here over localhost. Running tools here means timers,
approvals and the HUD all keep working exactly as they do with the API backend.
"""
from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import tools


def start_bridge(ctx: tools.ToolContext) -> tuple[str, str]:
    """Start the bridge on a free localhost port. Returns (url, token)."""
    token = secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def do_POST(self) -> None:
            if self.path != "/tool" or not secrets.compare_digest(self.headers.get("X-Jarvis-Token", ""), token):
                self.send_response(403)
                self.end_headers()
                return
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
                content, is_error = tools.execute(str(req.get("name")), req.get("input") or {}, ctx)
            except Exception as e:
                content, is_error = f"{type(e).__name__}: {e}", True
            body = json.dumps({"content": content, "is_error": is_error}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", token

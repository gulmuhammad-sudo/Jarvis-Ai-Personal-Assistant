"""Minimal MCP (Model Context Protocol) server over stdio, started by Claude Code.

It advertises Jarvis's tools and forwards every call to the bridge running inside the
Jarvis process (see bridge.py). Standard library only.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jarvis.tools import TOOL_DEFINITIONS  # noqa: E402

BRIDGE_URL = os.environ.get("JARVIS_BRIDGE_URL", "")
BRIDGE_TOKEN = os.environ.get("JARVIS_BRIDGE_TOKEN", "")


def send(msg: dict) -> None:
    sys.stdout.buffer.write((json.dumps(msg) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def call_tool(name: str, args: dict) -> dict:
    req = urllib.request.Request(
        BRIDGE_URL + "/tool",
        data=json.dumps({"name": name, "input": args}).encode(),
        headers={"Content-Type": "application/json", "X-Jarvis-Token": BRIDGE_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            res = json.load(r)
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Jarvis bridge unreachable: {e}"}], "isError": True}

    content = res.get("content")
    blocks = []
    if isinstance(content, list):
        for b in content:
            if b.get("type") == "image":
                blocks.append({"type": "image", "data": b["source"]["data"], "mimeType": b["source"]["media_type"]})
            else:
                blocks.append({"type": "text", "text": b.get("text", "")})
    else:
        blocks.append({"type": "text", "text": str(content)})
    return {"content": blocks, "isError": bool(res.get("is_error"))}


def main() -> None:
    tools = [{"name": d["name"], "description": d["description"], "inputSchema": d["input_schema"]}
             for d in TOOL_DEFINITIONS]
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:  # notification (e.g. notifications/initialized)
            continue
        params = msg.get("params") or {}
        if method == "initialize":
            result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                      "capabilities": {"tools": {}},
                      "serverInfo": {"name": "jarvis", "version": "1.0.0"}}
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            result = call_tool(params.get("name", ""), params.get("arguments") or {})
        elif method == "ping":
            result = {}
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method {method}"}})
            continue
        send({"jsonrpc": "2.0", "id": mid, "result": result})


if __name__ == "__main__":
    main()

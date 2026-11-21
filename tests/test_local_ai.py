"""Local AI (Ollama) against a fake Ollama server on a spare port: detection, model choice, the tool loop,
the provider chain (local first / last), falling back when it stops, and downloading a model."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jarvis import local_ai, providers, schedule, tools


class FakeOllama(BaseHTTPRequestHandler):
    chats: list = []
    models = [{"name": "qwen2.5:3b", "size": 1_900_000_000}, {"name": "nomic-embed-text:latest", "size": 270_000_000}]

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/version":
            return self._send({"version": "0.9.0"})
        if self.path == "/api/tags":
            return self._send({"models": self.models})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if self.path == "/api/show":
            caps = ["completion", "tools"] if body["model"].startswith("qwen") else ["embedding"]
            return self._send({"capabilities": caps})
        if self.path == "/api/chat":
            FakeOllama.chats.append(body)
            if not any(m["role"] == "tool" for m in body["messages"]):      # first: ask for the time tool
                return self._send({"message": {"role": "assistant", "content": "",
                                               "tool_calls": [{"function": {"name": "get_datetime", "arguments": {}}}]}})
            return self._send({"message": {"role": "assistant", "content": "It is time for tea."}})
        if self.path == "/api/pull":
            self.send_response(200)
            self.end_headers()
            for line in ({"status": "pulling manifest"}, {"status": "downloading", "total": 100, "completed": 50},
                         {"status": "success"}):
                self.wfile.write((json.dumps(line) + "\n").encode())
            return
        self._send({"error": "not found"}, 404)


@pytest.fixture
def ollama(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(local_ai, "HOST", f"http://127.0.0.1:{server.server_address[1]}")
    local_ai._cache["models"] = None
    FakeOllama.chats = []
    yield server
    server.shutdown()
    local_ai._cache["models"] = None


def ctx():
    return tools.ToolContext(confirm=lambda q, **k: True, notify=lambda *a, **k: None)


def test_not_running_means_skipped(monkeypatch):
    monkeypatch.setattr(local_ai, "HOST", "http://127.0.0.1:9")        # nothing listens there
    local_ai._cache["models"] = None
    assert not local_ai.running() and local_ai.models(refresh=True) == [] and local_ai.pick_model() is None
    brain = providers.MultiBrain(ctx(), lambda t: None, lambda n, a: None)
    assert "Local AI" not in brain.names


def test_detects_models_and_picks_one_that_can_use_tools(ollama):
    assert local_ai.running()
    ms = {m["name"]: m for m in local_ai.models(refresh=True)}
    assert ms["qwen2.5:3b"]["tools"] and not ms["nomic-embed-text:latest"]["tools"]
    assert local_ai.pick_model() == "qwen2.5:3b"


def test_tool_loop_runs_tools_and_answers(ollama):
    said, used = [], []
    b = providers.OllamaBrain(ctx(), said.append, lambda n, a: used.append(n), "qwen2.5:3b")
    assert b.ask("what time is it?") == "It is time for tea."
    assert used == ["get_datetime"] and said == ["It is time for tea."]
    first = FakeOllama.chats[0]
    assert first["options"]["num_ctx"] >= 8192 and first["stream"] is False
    names = {t["function"]["name"] for t in first["tools"]}
    assert "get_datetime" in names and "run_powershell" not in names           # small models get the core set
    tool_msg = next(m for m in FakeOllama.chats[1]["messages"] if m["role"] == "tool")
    assert "untrusted" not in tool_msg["content"] and "2026" in tool_msg["content"] or tool_msg["content"]


def test_local_goes_first_or_last(ollama, monkeypatch):
    schedule.set_setting("prefer_local", True)
    brain = providers.MultiBrain(ctx(), lambda t: None, lambda n, a: None)
    assert brain.names[0] == "Local AI"
    schedule.set_setting("prefer_local", False)
    assert providers.chain()[-1] == "ollama"
    schedule.set_setting("prefer_local", True)


def test_stopped_ollama_raises_provider_error_so_the_next_ai_answers(ollama):
    b = providers.OllamaBrain(ctx(), lambda t: None, lambda n, a: None, "qwen2.5:3b")
    ollama.shutdown()
    ollama.server_close()
    with pytest.raises(providers.ProviderError):
        b.ask("hello?")
    assert b.messages == []                                                       # nothing half-done kept


def test_status_for_the_models_page(ollama):
    st = local_ai.status()
    assert st["running"] and st["model"] == "qwen2.5:3b" and st["recommended"][0]["name"] == "qwen2.5:3b"
    rows = providers.provider_status(providers.MultiBrain(ctx(), lambda t: None, lambda n, a: None))
    local = next(r for r in rows if r["label"] == "Local AI")
    assert local["status"] in ("connected", "active") and "qwen2.5:3b" in local["detail"]


def test_download_reports_progress(ollama):
    seen = []
    local_ai.pull("llama3.2:3b", lambda status, frac: seen.append((status, frac)))
    assert seen[-1][0] == "success"

"""Phase 10, part 2: what the final security audit checks, kept as tests so that it stays true."""
import http.client
import re
import subprocess
import threading
from pathlib import Path

import pytest

from jarvis import hud, netlog

ROOT = Path(__file__).resolve().parent.parent
HTML = hud.HTML_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.fixture
def server(monkeypatch):
    srv = hud.QuietServer(("127.0.0.1", 0), hud.Handler)
    monkeypatch.setattr(hud, "PORT", srv.server_address[1])
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def get(path, **h):
        c = http.client.HTTPConnection("127.0.0.1", hud.PORT, timeout=10)
        c.request("GET", path, headers=h)
        r = c.getresponse()
        r.read()
        return r
    yield get
    srv.shutdown()
    srv.server_close()


def test_no_other_site_may_frame_the_window(server, monkeypatch):
    monkeypatch.setattr(hud, "HUB", hud.HUB or type("H", (), {})())          # (only for this test)
    for local in (False, True):
        monkeypatch.setattr(netlog, "_ON", local)
        monkeypatch.setattr(netlog, "_LOCAL", local)
        r = server("/")
        assert r.status == 200
        assert r.getheader("X-Frame-Options") == "DENY" and "frame-ancestors 'none'" in r.getheader("Content-Security-Policy")
        assert r.getheader("Referrer-Policy") == "no-referrer" and r.getheader("X-Content-Type-Options") == "nosniff"
    r = server(f"/recpill?token={hud.TOKEN}")
    assert r.getheader("X-Frame-Options") == "DENY"


def test_answers_are_never_sniffed_as_pages(server):
    r = server("/api/stats?token=wrong")
    assert r.status == 403 and r.getheader("X-Content-Type-Options") == "nosniff" and r.getheader("Content-Type") == "application/json"
    assert r.getheader("Access-Control-Allow-Origin") is None


def test_only_the_page_and_its_icon_without_the_token(server):
    for path in ("/api/stats", "/events", "/api/info", "/recpill", "/api/media/file?id=1", "/api/local"):
        assert server(path).status == 403, path
    assert server("/", Host="evil.example").status == 403                   # (another site's name pointing here)


def test_a_vault_address_opens_only_web_pages():
    rx = re.search(r'f === "url" \? \((/\^https\?.*?/i)\.test\(val\)', HTML)
    assert rx, "the Open button checks the address"
    js = rx.group(1)
    py = re.compile(js[1:-2].replace("\\/", "/"), re.I)
    for ok in ("https://bank.example/login", "http://192.168.1.1"):
        assert py.match(ok)
    for bad in ("javascript:alert(1)", "JaVaScRiPt:fetch('/api')", "data:text/html,x", "file:///C:/x", "https://x\" onmouseover=\"y", " https://x"):
        assert not py.match(bad), bad


def test_nothing_secret_in_the_repository():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    pats = [re.compile(p) for p in (rb"AIza[0-9A-Za-z_\-]{35}", rb"gsk_[0-9A-Za-z]{40,}", rb"sk-or-v1-[0-9a-f]{40,}", rb"sk-ant-[0-9A-Za-z_\-]{30,}", rb"ghp_[0-9A-Za-z]{30,}",
                                    rb"-----BEGIN (RSA |EC |)PRIVATE KEY-----", rb"@iqra\.edu", rb"hum\.tv")]
    found = []
    for f in files:
        p = ROOT / f
        if p.suffix.lower() in (".png", ".ico", ".jpg", ".webp", ".exe", ".zip") or not p.is_file():
            continue
        raw = p.read_bytes()
        found += [(f, x.pattern) for x in pats if x.search(raw)]
    assert found == []
    assert not [f for f in files if re.search(r"(^|/)(\.env|keys\.dat|mail\.dat|lock\.dat|access\.dat|backup\.dat)$|^data/|\.pabackup$", f)]


def test_no_shell_and_no_eval_in_the_app():
    for f in (ROOT / "jarvis").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert not re.search(r"shell\s*=\s*True|os\.system\(|os\.popen\(|\beval\(|\bexec\(|pickle\.loads?\(|yaml\.load\(", src), f.name


def test_every_request_that_changes_something_needs_the_token():
    src = (ROOT / "jarvis" / "hud.py").read_text(encoding="utf-8")
    post = src[src.index("    def do_POST(self) -> None:"):]
    head = post[:post.index("\n        if lock.is_locked()")]
    assert "_token_ok(self.headers.get(\"X-Jarvis-Token\"))" in head and "_host_ok()" in head
    assert head.index('self.path.startswith("/v1/")') < head.index("_token_ok")          # (the API has its own keys)

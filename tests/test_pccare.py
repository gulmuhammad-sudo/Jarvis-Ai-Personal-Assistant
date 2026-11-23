"""Phase 5, part 2: software manager (winget), network center, developer tools. Nothing is installed, updated or
removed here: winget is replaced by fakes; the real read-only checks are marked `network`."""
import shutil
import subprocess

import pytest

from jarvis import devtools, guard, netcheck, software, tools

SEARCH = """Name             Id                    Version    Match
--------------------------------------------------------------
VLC media player VideoLAN.VLC          3.0.24     Moniker: vlc
pympress         Cimbali.pympress      1.8.6      Tag: vlc
<additional entries truncated due to result limit>
"""
UPGRADE = """Name                    Id                     Version   Available
---------------------------------------------------------------------
Git                     Git.Git                2.55.0.5  2.56.1
VLC media player        VideoLAN.VLC           3.0.23    3.0.24
2 upgrades available.
"""
LIST = """Name         Id                                           Version          Available Source
-------------------------------------------------------------------------------------------
AMD Software ARP\\Machine\\X64\\AMD Catalyst Install Manager 26.1.1
Git          Git.Git                                      2.55.0.5         2.56.1    winget
"""


def test_parse_search_skips_the_truncation_note():
    rows = software.parse_table(SEARCH)
    assert [r["id"] for r in rows] == ["VideoLAN.VLC", "Cimbali.pympress"]
    assert rows[0]["name"] == "VLC media player" and rows[0]["match"] == "Moniker: vlc"


def test_parse_upgrades_and_list():
    ups = software.parse_table(UPGRADE)
    assert [(u["id"], u["available"]) for u in ups] == [("Git.Git", "2.56.1"), ("VideoLAN.VLC", "3.0.24")]
    rows = software.parse_table(LIST)
    assert rows[1]["source"] == "winget" and rows[0]["id"].startswith("ARP\\")
    assert software.parse_table("No installed package found matching input criteria.") == []


@pytest.mark.parametrize("pkg", ["VideoLAN.VLC", "Microsoft.VisualStudioCode", "7zip.7zip", "Mozilla.Firefox.ESR"])
def test_good_ids(pkg):
    assert software.check_id(pkg) == pkg


@pytest.mark.parametrize("pkg", ["", "vlc; del C:\\", "--force", "a b", "x" * 200, "VideoLAN.VLC&calc"])
def test_bad_ids(pkg):
    with pytest.raises(ValueError):
        software.check_id(pkg)


@pytest.fixture
def fake_winget(monkeypatch):
    calls = []
    monkeypatch.setattr(software, "available", lambda: True)
    monkeypatch.setattr(software, "search", lambda q, count=10: software.parse_table(SEARCH))
    monkeypatch.setattr(software, "upgrades", lambda: software.parse_table(UPGRADE))
    monkeypatch.setattr(software, "installed", lambda q="": [r for r in software.parse_table(LIST) if q.lower() in (r["name"] + r["id"]).lower()])
    monkeypatch.setattr(software, "change", lambda action, pkg="", on_done=None, name="": calls.append((action, pkg)) or f"{action} {name or pkg} started")
    return calls


def ctx(answer, asked):
    def confirm(q, **k):
        asked.append((q, k.get("kind")))
        return answer
    return tools.ToolContext(confirm=confirm, notify=lambda *a, **k: None)


def test_looking_needs_no_ok_and_is_untrusted(fake_winget):
    asked = []
    out, err = tools.execute("software", {"action": "search", "query": "vlc"}, ctx(True, asked))
    assert not err and "VideoLAN.VLC" in out and out.startswith('<untrusted source="software">') and asked == []
    out, _ = tools.execute("software", {"action": "updates"}, ctx(True, asked))
    assert "2 update(s)" in out and asked == [] and fake_winget == []


@pytest.mark.parametrize("args,action,pkg", [
    ({"action": "install", "id": "VideoLAN.VLC"}, "install", "VideoLAN.VLC"),
    ({"action": "update", "id": "git.git"}, "upgrade", "Git.Git"),
    ({"action": "uninstall", "query": "Git.Git"}, "uninstall", "Git.Git"),
    ({"action": "update_all"}, "upgrade_all", ""),
])
def test_changes_ask_first(fake_winget, args, action, pkg):
    asked = []
    out, _ = tools.execute("software", args, ctx(False, asked))
    assert asked and asked[0][1] == "software" and fake_winget == []          # said no: nothing ran
    assert "Okay" in out
    out, _ = tools.execute("software", args, ctx(True, []))
    assert fake_winget == [(action, pkg)] and "started" in out


def test_install_refuses_unknown_or_odd_ids(fake_winget):
    asked = []
    out, _ = tools.execute("software", {"action": "install", "id": "Evil.Package"}, ctx(True, asked))
    assert "no winget package" in out and not asked and not fake_winget
    out, _ = tools.execute("software", {"action": "install", "id": "x & calc"}, ctx(True, asked))
    assert "doesn't look like" in out and not asked


def test_update_without_waiting_update(fake_winget):
    out, _ = tools.execute("software", {"action": "update", "id": "Mozilla.Firefox"}, ctx(True, []))
    assert "no update waiting" in out and not fake_winget


def test_only_one_change_at_a_time(monkeypatch):
    monkeypatch.setattr(software, "_run", lambda args, timeout=0: (0, ""))
    software._BUSY.acquire()
    try:
        assert "still running" in software.change("install", "VideoLAN.VLC")
    finally:
        software._BUSY.release()


def test_change_reports_back(monkeypatch):
    import threading
    monkeypatch.setattr(software, "_run", lambda args, timeout=0: (0, "Successfully installed"))
    done = threading.Event()
    got = []
    software.change("install", "VideoLAN.VLC", lambda m: (got.append(m), done.set()), "VLC media player")
    assert done.wait(5) and got == ["Installing VLC media player: done."]
    assert software._BUSY.acquire(blocking=False)
    software._BUSY.release()


def test_summary_messages():
    assert "already up to date" in software._summary(1, "No available upgrade found.", "Updating", "Git")
    assert "failed" in software._summary(2, "Installer hash does not match.", "Installing", "VLC")


# ---------------- network ----------------
NETSH = """There is 1 interface on the system:

    Name                   : Wi-Fi
    State                  : connected
    SSID                   : HomeNet
    Band                   : 5 GHz
    Receive rate (Mbps)    : 433.3
    Transmit rate (Mbps)   : 300
    Signal                 : 31%
"""


def test_parse_netsh():
    w = netcheck.parse_netsh(NETSH)
    assert w == {"name": "Wi-Fi", "state": "connected", "ssid": "HomeNet", "band": "5 GHz", "rx_mbps": 433.3,
                 "tx_mbps": 300.0, "signal": 31}


GW = [{"alias": "Wi-Fi", "gw": "192.168.1.1"}]
WIFI = {"state": "connected", "signal": 90}


@pytest.mark.parametrize("r,expect", [
    ({"wifi": WIFI, "gateways": GW, "gw_ms": 3, "net_ms": 40, "dns_ms": 20, "web": "ok"}, "Internet is working (40 ms"),
    ({"wifi": {"state": "connected", "signal": 25}, "gateways": GW, "gw_ms": 3, "net_ms": 40, "dns_ms": 20, "web": "ok"}, "weak (25%)"),
    ({"wifi": WIFI, "gateways": GW, "gw_ms": 3, "net_ms": 300, "dns_ms": 20, "web": "ok"}, "slow"),
    ({"wifi": {"state": "disconnected"}, "gateways": [], "gw_ms": None, "net_ms": None, "dns_ms": None, "web": "fail"}, "Wi-Fi is disconnected"),
    ({"wifi": {}, "gateways": [], "gw_ms": None, "net_ms": None, "dns_ms": None, "web": "fail"}, "no router found"),
    ({"wifi": WIFI, "gateways": GW, "gw_ms": 3, "net_ms": 40, "dns_ms": 20, "web": "portal"}, "wants you to sign in"),
    ({"wifi": WIFI, "gateways": GW, "gw_ms": 3, "net_ms": 40, "dns_ms": None, "web": "fail"}, "DNS problem"),
    ({"wifi": WIFI, "gateways": GW, "gw_ms": None, "net_ms": None, "dns_ms": None, "web": "fail"}, "Can't reach the router"),
    ({"wifi": WIFI, "gateways": GW, "gw_ms": 4, "net_ms": None, "dns_ms": None, "web": "fail"}, "no internet behind it"),
    ({"wifi": WIFI, "gateways": GW, "gw_ms": 4, "net_ms": 30, "dns_ms": 15, "web": "fail"}, "firewall, proxy or VPN"),
])
def test_verdicts(r, expect):
    assert expect in netcheck.verdict(r)


def test_network_tool_describes(monkeypatch):
    monkeypatch.setattr(netcheck, "check", lambda: {"wifi": WIFI | {"ssid": "HomeNet"}, "gateways": GW, "gw_ms": 3,
                                                    "net_ms": 40, "dns_ms": 20, "web": "ok", "verdict": "Internet is working."})
    out, err = tools.execute("network", {"action": "check"}, tools.ToolContext(confirm=lambda q, **k: True, notify=lambda *a, **k: None))
    assert not err and out.splitlines()[0] == "Internet is working." and "HomeNet" in out and "Router: 192.168.1.1" in out


# ---------------- developer tools ----------------
@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_git_status_of_a_repo(tmp_path):
    run = lambda *a: subprocess.run(["git", "-C", str(tmp_path), *a], capture_output=True, check=True)  # noqa: E731
    run("init", "-q", "-b", "main")
    run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty", "-m", "first commit")
    (tmp_path / "new.txt").write_text("x")
    out = devtools.git_status(str(tmp_path))
    assert "on branch main" in out and "new untracked files: 1" in out and "first commit" in out


def test_git_status_outside_a_repo(tmp_path):
    out = devtools.git_status(str(tmp_path))
    assert "isn't inside a git repository" in out or "Git isn't installed" in out
    assert "no folder" in devtools.git_status(str(tmp_path / "missing"))


def test_dev_tools_untrusted_and_versions(monkeypatch):
    monkeypatch.setattr(devtools, "tools_installed", lambda: {"Git": "2.55.0", "Docker": None})
    out, _ = tools.execute("dev_tools", {"action": "versions"}, tools.ToolContext(confirm=lambda q, **k: True, notify=lambda *a, **k: None))
    assert guard.is_untrusted("dev_tools") and "Git 2.55.0" in out and "Not found: Docker" in out


def test_free_port():
    assert "Nothing is listening on port 1" in devtools.ports(1)


@pytest.mark.network
def test_real_read_only_checks():
    assert software.search("vlc", 3)
    r = netcheck.check()
    assert r["verdict"]


def test_no_mic_flag_keeps_the_microphone_closed():
    """Tests and demo copies run with JARVIS_NO_MIC=1: not even a spoken yes/no for an approval opens the mic."""
    from jarvis import hud
    assert hud.recorder is None


class _Resp:
    def __init__(self, body=b"", status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body


@pytest.mark.parametrize("answers,expect,calls", [
    ([_Resp(b"Microsoft Connect Test")], "ok", 1),
    ([OSError("lost"), _Resp(b"Microsoft Connect Test")], "ok", 2),            # one lost request isn't a verdict
    ([OSError("x"), OSError("x"), _Resp(b"", 204)], "ok", 3),                  # Microsoft's page down, the web works
    ([OSError("x"), OSError("x"), OSError("x")], "fail", 3),
    ([_Resp(b"<html>Sign in to Hotel Wi-Fi</html>")], "portal", 1),
])
def test_web_test_retries_before_blaming_anything(monkeypatch, answers, expect, calls):
    todo, seen = list(answers), []

    def urlopen(url, timeout=0):
        seen.append(url)
        a = todo.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(netcheck.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(netcheck.time, "sleep", lambda s: None)
    assert netcheck._web() == expect and len(seen) == calls

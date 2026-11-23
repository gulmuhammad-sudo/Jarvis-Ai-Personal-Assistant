"""Network and internet center (Phase 5): what's wrong with the internet, in plain words.

check(): Wi-Fi name/signal, router (gateway) ping, internet ping, DNS, and whether a web page really loads
(Windows' own connectivity test page, which also spots "sign in to this Wi-Fi" pages) -> one verdict.
speed(): download speed from Cloudflare's public speed-test endpoint (about 10 MB, nothing about you is sent).
flush_dns(): the usual first fix. Nothing here changes a setting.
"""
from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import urllib.request

NCSI_URL = "http://www.msftconnecttest.com/connecttest.txt"      # what Windows itself uses
NCSI_TEXT = "Microsoft Connect Test"
SPEED_URL = "https://speed.cloudflare.com/__down?bytes={n}"
WEB_BACKUP_URL = "https://www.gstatic.com/generate_204"         # a second, unrelated site (answers 204, empty)
INTERNET_HOST = "1.1.1.1"
DNS_NAME = "www.microsoft.com"
_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ps(script: str, timeout: int = 30) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, creationflags=_NOWIN)
    return r.stdout or ""


def parse_netsh(text: str) -> dict:
    """`netsh wlan show interfaces` -> {name, state, ssid, signal, band, rx_mbps, tx_mbps} (first interface)."""
    info: dict = {}
    for ln in text.splitlines():
        m = re.match(r"\s*([A-Za-z][A-Za-z ()-]*?)\s*:\s(.*)$", ln)
        if not m:
            continue
        key, val = m.group(1).strip().lower(), m.group(2).strip()
        if key == "name" and "name" in info:
            break                                         # second adapter: keep the first
        if key in ("name", "state", "ssid", "band", "radio type"):
            info[key.replace(" ", "_")] = val
        elif key == "signal":
            info["signal"] = int(re.sub(r"\D", "", val) or 0)
        elif key.startswith("receive rate"):
            info["rx_mbps"] = float(val or 0)
        elif key.startswith("transmit rate"):
            info["tx_mbps"] = float(val or 0)
    return info


def wifi() -> dict:
    try:
        r = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10, creationflags=_NOWIN)
        return parse_netsh(r.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return {}


_PROBE_PS = r"""
$gw = @(Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq 'Up' } |
  ForEach-Object { @{ alias = $_.InterfaceAlias; gw = $_.IPv4DefaultGateway.NextHop } })
function P($h) { $r = Test-Connection -ComputerName $h -Count 2 -ErrorAction SilentlyContinue
  if ($r) { [math]::Round(($r | Measure-Object ResponseTime -Average).Average) } else { -1 } }
$gwPing = if ($gw.Count) { P $gw[0].gw } else { -1 }
@{ gateways = $gw; gw_ms = $gwPing; net_ms = (P '__HOST__') } | ConvertTo-Json -Depth 4 -Compress
"""


def _probe() -> dict:
    try:
        out = _ps(_PROBE_PS.replace("__HOST__", INTERNET_HOST), timeout=40)
        data = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except (ValueError, IndexError, subprocess.TimeoutExpired, OSError):
        data = {}
    gws = data.get("gateways") or []
    if isinstance(gws, dict):
        gws = [gws]
    ms = lambda v: None if v is None or int(v) < 0 else int(v)  # noqa: E731
    return {"gateways": gws, "gw_ms": ms(data.get("gw_ms")), "net_ms": ms(data.get("net_ms"))}


def _dns() -> float | None:
    t = time.perf_counter()
    try:
        socket.getaddrinfo(DNS_NAME, 443)
        return round((time.perf_counter() - t) * 1000)
    except OSError:
        return None


def _web() -> str:
    """ok | portal (a 'sign in to this Wi-Fi' page answered instead) | fail

    One lost request must not be reported as "web pages don't load" (it happened once on a working connection),
    so: two tries, then a second, unrelated site."""
    for attempt in range(2):
        try:
            with urllib.request.urlopen(NCSI_URL, timeout=5) as r:
                return "ok" if r.read(200).decode("utf-8", "ignore").strip() == NCSI_TEXT else "portal"
        except Exception:
            if attempt == 0:
                time.sleep(0.7)
    try:
        with urllib.request.urlopen(WEB_BACKUP_URL, timeout=5) as r:
            return "ok" if r.status == 204 else "portal"
    except Exception:
        return "fail"


def verdict(r: dict) -> str:
    """One plain answer from the raw results (kept separate so it can be tested)."""
    w, gw, net, dns, web = r.get("wifi") or {}, r.get("gateways"), r.get("net_ms"), r.get("dns_ms"), r.get("web")
    weak = w.get("state") == "connected" and w.get("signal") is not None and w["signal"] < 40
    if not gw:
        if w and w.get("state") != "connected":
            return "Not connected: Wi-Fi is disconnected. Connect to a network first."
        return "Not connected to any network (no router found). Check Wi-Fi or the cable."
    if web == "portal":
        return "Connected, but this Wi-Fi wants you to sign in: open any website in the browser to get its sign-in page."
    if web == "ok" and dns is not None:
        msg = "Internet is working"
        if net is not None:
            msg += f" ({net} ms to the internet" + (", slow" if net > 150 else "") + ")"
        msg += "."
        if weak:
            msg += f" Wi-Fi signal is weak ({w['signal']}%): move closer to the router for better speed."
        return msg
    if net is not None and dns is None:
        return "Internet is reachable but names don't resolve (DNS problem). Try 'flush DNS', or set DNS to 1.1.1.1 / 8.8.8.8."
    if r.get("gw_ms") is None and net is None:
        return ("Can't reach the router" + (f" (Wi-Fi signal {w['signal']}%)" if w.get("signal") is not None else "")
                + ". Restart the router or reconnect to Wi-Fi.")
    if net is None:
        return "The router answers but there's no internet behind it: restart the router, or the internet provider has a problem."
    return ("The internet answers pings, but three web page tests failed. Run the check again; if it stays like this, "
            "a firewall, proxy or VPN may be blocking web pages.")


def check() -> dict:
    r = {"wifi": wifi(), **_probe(), "dns_ms": _dns(), "web": _web()}
    r["verdict"] = verdict(r)
    return r


def describe(r: dict) -> str:
    w = r.get("wifi") or {}
    lines = [r["verdict"]]
    if w:
        lines.append(f"Wi-Fi: {w.get('ssid') or w.get('name') or '?'} — {w.get('state', '?')}"
                     + (f", signal {w['signal']}%" if "signal" in w else "") + (f", {w['band']}" if w.get("band") else "")
                     + (f", link {w['rx_mbps']:.0f} Mbps" if w.get("rx_mbps") else ""))
    gws = r.get("gateways") or []
    lines.append("Router: " + (f"{gws[0].get('gw')} ({gws[0].get('alias')}) " + (f"{r['gw_ms']} ms" if r.get("gw_ms") is not None else "no ping reply")
                               if gws else "none"))
    lines.append("Internet ping: " + (f"{r['net_ms']} ms" if r.get("net_ms") is not None else "no reply"))
    lines.append("DNS: " + (f"{r['dns_ms']} ms" if r.get("dns_ms") is not None else "failed"))
    lines.append("Web page test: " + {"ok": "loads", "portal": "a Wi-Fi sign-in page answered", "fail": "failed"}.get(r.get("web"), "?"))
    return "\n".join(lines)


def speed(megabytes: int = 10, max_seconds: float = 15.0) -> dict:
    n = max(1, min(int(megabytes), 50)) * 1_000_000
    req = urllib.request.Request(SPEED_URL.format(n=n), headers={"User-Agent": "PersonalAssistant-speedtest"})
    got, t0 = 0, time.perf_counter()
    with urllib.request.urlopen(req, timeout=15) as resp:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            got += len(chunk)
            if time.perf_counter() - t0 > max_seconds:
                break
    secs = max(0.001, time.perf_counter() - t0)
    return {"mbps": round(got * 8 / secs / 1_000_000, 1), "megabytes": round(got / 1_000_000, 1), "seconds": round(secs, 1)}


def flush_dns() -> str:
    r = subprocess.run(["ipconfig", "/flushdns"], capture_output=True, text=True, timeout=20, creationflags=_NOWIN)
    return "Flushed the DNS cache." if r.returncode == 0 else "Couldn't flush the DNS cache."

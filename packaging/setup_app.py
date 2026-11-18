"""'Personal Assistant Setup.exe': installs the app for the signed-in user (no admin rights needed).

A small wizard (setup.html in a WebView2 window) asks where to install and how you want the assistant set up:
its name, what it calls you, language, voices, look, AI keys and startup options. Then it copies the app,
brings over the settings, memories and keys of an older copy (the run.py / .bat version or an earlier install),
makes the shortcuts and adds "Personal Assistant" to Windows Settings > Apps (with Uninstall).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
PAYLOAD = HERE / "payload" / "app.zip" if getattr(sys, "frozen", False) else \
    Path(__file__).resolve().parent.parent / "build" / "payload" / "app.zip"
APP_NAME = "Personal Assistant"
# Settings live where the installed app looks for them (JARVIS_DATA_DIR only for testing the installer).
DATA = Path(os.environ.get("JARVIS_DATA_DIR") or
            Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME)
os.environ["JARVIS_DATA_DIR"] = str(DATA)          # jarvis.schedule / memory below write there
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import __version__, install, languages, memory, schedule, tts  # noqa: E402

KEYS = {"gemini": "GEMINI_API_KEY", "groq": "GROQ_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
NO_WINDOW = 0x08000000
DEFAULT_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Programs" / APP_NAME
TEST = os.environ.get("PA_SETUP_TEST") == "1"      # tests: no shortcuts, Startup, registry or closing apps


def _read_env(path: Path) -> dict[str, str]:
    out = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                if v.strip():
                    out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _shortcut_info(lnk: Path) -> dict:
    q = str(lnk).replace("'", "''")
    ps = (f"$l = (New-Object -ComObject WScript.Shell).CreateShortcut('{q}'); "
          "[Console]::Out.Write($l.TargetPath + '|' + $l.Arguments + '|' + $l.WorkingDirectory)")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=20, creationflags=NO_WINDOW).stdout.split("|")
        return {"target": out[0], "args": out[1], "dir": out[2]} if len(out) == 3 else {}
    except Exception:
        return {}


def find_old_copy() -> Path | None:
    """The folder of a copy started with run.py / 'python -m jarvis' (before there was an installer)."""
    for kind in ("desktop", "programs", "startup"):
        try:
            lnk = install.folder(kind) / f"{APP_NAME}.lnk"
        except Exception:
            continue
        if lnk.exists():
            info = _shortcut_info(lnk)
            where = Path(info.get("dir") or ".")
            if ("run.py" in info.get("args", "") or "jarvis" in info.get("args", "")) and (where / "jarvis").is_dir():
                return where
    return None


class Api:
    """Called from setup.html (window.pywebview.api.*)."""

    def __init__(self) -> None:
        self._window = None
        self._old = find_old_copy()
        self._existing = None if TEST else install.installed()
        self._done_dir: Path | None = None

    # ---------- what the wizard shows ----------
    def info(self) -> dict:
        src = self._old / "data" if self._old and not (DATA / "settings.json").exists() else DATA
        settings = json.loads((src / "settings.json").read_text(encoding="utf-8")) if (src / "settings.json").exists() else {}
        prof = json.loads((src / "profile.json").read_text(encoding="utf-8")) if (src / "profile.json").exists() else {}
        env = {**_read_env(self._old / ".env" if self._old else Path("-")), **_read_env(DATA / ".env")}
        return {
            "version": __version__, "default_dir": str(self._existing["dir"] if self._existing else DEFAULT_DIR),
            "existing": {"dir": str(self._existing["dir"]), "version": self._existing["version"]} if self._existing else None,
            "old": str(self._old) if self._old else None, "data": str(DATA),
            "languages": languages.choices(), "live_voices": languages.LIVE_VOICES,
            "reading_voices": [{"id": v, "name": n} for v, n in tts.VOICES if not v.startswith("ur-")],
            "keys": {k: bool(env.get(name) or os.environ.get(name)) for k, name in KEYS.items()},
            "s": {"name": settings.get("assistant_name") or "Jarvis", "call": prof.get("call", ""), "user_name": prof.get("name", ""),
                  "language": settings.get("language") or "en", "live_voice": settings.get("live_voice") or "Charon",
                  "reading_voice": settings.get("reading_voice") or "en-GB-RyanNeural",
                  "engine": settings.get("voice_engine") or "live", "theme": settings.get("theme") or "dark",
                  "face": settings.get("face") or "globe", "hands_free": settings.get("hands_free", True) is not False,
                  "wake_word": settings.get("wake_word", True) is not False,
                  "start_with_windows": settings.get("start_with_windows", True) is not False,
                  "live_on_open": settings.get("live_on_open", True) is not False,
                  "chat_script": settings.get("chat_script") or "roman"},
        }

    def browse(self, current: str) -> str | None:
        import webview
        got = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=current or str(DEFAULT_DIR.parent))
        if not got:
            return None
        pick = Path(got[0] if isinstance(got, (list, tuple)) else got)
        return str(pick if pick.name == APP_NAME else pick / APP_NAME)

    @staticmethod
    def open_url(url: str) -> None:
        """'get one' links open in your browser (only these three key pages)."""
        if url in ("https://aistudio.google.com/apikey", "https://console.groq.com/keys", "https://openrouter.ai/keys"):
            os.startfile(url)

    def check_name(self, name: str) -> str:
        try:
            schedule.clean_name(name)
            return ""
        except ValueError as e:
            return str(e)

    # ---------- installing ----------
    def install(self, c: dict) -> None:
        threading.Thread(target=self._install, args=(c,), daemon=True).start()

    def _progress(self, pct: float, text: str) -> None:
        if self._window:
            self._window.evaluate_js(f"progress({pct:.0f}, {json.dumps(text)})")

    def _install(self, c: dict) -> None:
        try:
            target = Path(c.get("dir") or DEFAULT_DIR).expanduser()
            if target.exists() and any(target.iterdir()) and not (target / install.EXE_NAME).exists():
                if any(p.name not in ("desktop.ini",) for p in target.iterdir()):
                    raise RuntimeError(f"{target} already has other files in it. Choose an empty folder.")
            self._progress(2, "Closing Personal Assistant if it is running")
            if not TEST:
                install.stop_running(target)
                if self._old:
                    self._stop_old(self._old)
            time.sleep(0.8)

            self._progress(5, "Copying the app")
            target.mkdir(parents=True, exist_ok=True)
            internal = target / "_internal"
            if internal.exists():
                shutil.rmtree(internal)                    # an update replaces the old program files
            with zipfile.ZipFile(PAYLOAD) as z:
                names = z.infolist()
                for i, m in enumerate(names):
                    z.extract(m, target)
                    if i % 40 == 0:
                        self._progress(5 + 75 * i / len(names), "Copying the app")

            self._progress(82, "Bringing over your settings")
            DATA.mkdir(parents=True, exist_ok=True)
            if self._old and c.get("migrate", True):
                self._migrate(self._old)

            self._progress(88, "Saving your choices")
            self._apply(c)

            self._progress(93, "Making shortcuts")
            if not TEST:
                install.create_shortcuts(target, desktop=bool(c.get("desktop", True)), start_menu=True)
                install.set_startup(bool(c.get("start_with_windows", True)), app_dir=target)
                install.register(target, __version__)
            self._done_dir = target
            self._progress(100, "Done")
            if self._window:
                self._window.evaluate_js("installed()")
        except Exception as e:
            msg = str(e) if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}"
            if isinstance(e, PermissionError):
                msg = "Windows didn't allow writing there. Choose a folder in your user folder (the suggested one works)."
            if self._window:
                self._window.evaluate_js(f"failed({json.dumps(msg)})")
            else:
                raise

    @staticmethod
    def _stop_old(old: Path) -> None:
        """The old run.py / python -m jarvis copy holds the microphone and port: close it."""
        import psutil
        for p in psutil.process_iter(["pid", "name", "cmdline", "cwd"]):
            try:
                cmd = " ".join(p.info["cmdline"] or [])
                if "python" in (p.info["name"] or "").lower() and ("run.py" in cmd or "-m jarvis" in cmd) \
                        and Path(p.info["cwd"] or ".").resolve() == old.resolve():
                    p.kill()
            except (psutil.Error, OSError):
                pass

    @staticmethod
    def _migrate(old: Path) -> None:
        """Copy the older copy's data folder and keys, without overwriting anything already here."""
        src = old / "data"
        if src.is_dir():
            for f in src.rglob("*"):
                dest = DATA / f.relative_to(src)
                if f.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif not dest.exists() and f.suffix not in (".tmp", ".lock"):
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(f, dest)
                    except OSError:
                        pass
        have = _read_env(DATA / ".env")
        add = {k: v for k, v in _read_env(old / ".env").items() if k not in have}
        if add:
            _save_env(add)

    @staticmethod
    def _apply(c: dict) -> None:
        try:
            schedule.set_agent_name(c.get("name") or "Jarvis")
        except ValueError:
            pass
        prof = memory.profile()
        prof["call"] = str(c.get("call") or "").strip()[:100]
        prof["name"] = str(c.get("user_name") or "").strip()[:100]
        memory.save_profile(prof)
        put = schedule.set_setting
        put("language", languages.clean(c.get("language") or "en"))
        if c.get("live_voice") in languages.LIVE_VOICES:
            put("live_voice", c["live_voice"])
        if c.get("reading_voice"):
            put("reading_voice", str(c["reading_voice"])[:60])
        put("voice_engine", "classic" if c.get("engine") == "classic" else "live")
        put("theme", c.get("theme") if c.get("theme") in schedule.THEMES else "dark")
        put("face", c.get("face") if c.get("face") in ("globe", "mask", "rings", "photo") else "globe")
        put("chat_script", "urdu" if c.get("chat_script") == "urdu" else "roman")
        for k in ("hands_free", "wake_word", "start_with_windows", "live_on_open"):
            put(k, bool(c.get(k, True)))
        put("setup_done", True)                         # the app won't ask all this again
        keys = {KEYS[k]: str(v).strip() for k, v in (c.get("keys") or {}).items()
                if k in KEYS and re.fullmatch(r"[A-Za-z0-9_\-.:]{16,200}", str(v or "").strip())}
        if keys:
            _save_env(keys)

    # ---------- the end ----------
    def launch(self) -> None:
        if self._done_dir and not TEST:
            env = {k: v for k, v in os.environ.items() if k != "JARVIS_DATA_DIR"}
            subprocess.Popen([str(self._done_dir / install.EXE_NAME)], cwd=str(self._done_dir), env=env, close_fds=True)
        self.close()

    def close(self) -> None:
        if self._window:
            self._window.destroy()


def _save_env(new: dict[str, str]) -> None:
    path = DATA / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for key, value in new.items():
        hit = next((i for i, line in enumerate(lines) if line.split("=", 1)[0].strip() == key), None)
        if hit is None:
            lines.append(f"{key}={value}")
        else:
            lines[hit] = f"{key}={value}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    import webview
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PersonalAssistant.Setup")
    except Exception:
        pass
    api = Api()
    html = (HERE / "setup.html").read_text(encoding="utf-8")
    api._window = webview.create_window(f"{APP_NAME} Setup", html=html, js_api=api, width=900, height=640,
                                       resizable=False, background_color="#05080C")
    webview.start(gui="edgechromium", private_mode=True)


if __name__ == "__main__":
    main()

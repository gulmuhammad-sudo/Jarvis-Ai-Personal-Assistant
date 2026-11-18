"""Settings, paths and small shared helpers for Jarvis."""
import json
import os
import threading
from pathlib import Path

import sys
import warnings

# pycaw warns about every audio device property it can't read: harmless, and it filled the log
warnings.filterwarnings("ignore", category=UserWarning, module="pycaw")

APP_NAME = "Personal Assistant"     # the app's name never changes (the assistant inside can be called anything)
FROZEN = bool(getattr(sys, "frozen", False))      # the installed .exe (built with PyInstaller)
# ROOT: the program folder (where "Personal Assistant.exe" is, or this source checkout).
# RES: where the bundled files are (assets/...): inside the .exe's _internal folder, or the checkout.
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
RES = Path(getattr(sys, "_MEIPASS", ROOT))
ICON = RES / "assets" / "jarvis.ico"
# Your settings, memories and keys: %APPDATA%\Personal Assistant for the installed app, data\ in a checkout.
# JARVIS_DATA_DIR: a different data folder (tests and test copies never touch your real settings)
USER_DATA = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
DATA_DIR = (Path(os.environ["JARVIS_DATA_DIR"]) if os.environ.get("JARVIS_DATA_DIR")
            else USER_DATA if FROZEN else ROOT / "data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
MEMORY_FILE = DATA_DIR / "memory.json"
NOTES_DIR = DATA_DIR / "notes"
NOTES_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (KEY=VALUE lines) so we don't need python-dotenv."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# API keys: data folder's .env for the installed app (a checkout keeps using the .env next to the code)
ENV_FILE = DATA_DIR / ".env" if FROZEN else ROOT / ".env"
_load_dotenv(ENV_FILE)


def save_env_keys(new: dict[str, str]) -> None:
    """Add or replace KEY=value lines in the .env file (your PC only) and use them right away."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    for key, value in new.items():
        hit = next((i for i, line in enumerate(lines) if line.split("=", 1)[0].strip() == key), None)
        if hit is None:
            lines.append(f"{key}={value}")
        else:
            lines[hit] = f"{key}={value}"
        os.environ[key] = value
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

MODEL = os.environ.get("JARVIS_MODEL", "claude-opus-5-5")      # only used with an Anthropic API key
EFFORT = os.environ.get("JARVIS_EFFORT", "medium")              # low | medium | high | xhigh | max
USER_NAME = os.environ.get("JARVIS_USER_NAME", "Sir")
DEFAULT_PROVIDERS = "gemini,groq,openrouter,deepseek"


def provider_order() -> list[str]:
    """AI providers to try, in order (JARVIS_PROVIDERS in .env)."""
    raw = os.environ.get("JARVIS_PROVIDERS", DEFAULT_PROVIDERS)
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


# --- JSON files in data/: one lock so two threads never overwrite each other's changes ---
DATA_LOCK = threading.RLock()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    """Write atomically (temp file + replace), so a crash mid-write can't leave a half-written file."""
    import time
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows keeps a file locked for a moment while antivirus / search indexing / OneDrive reads it
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))

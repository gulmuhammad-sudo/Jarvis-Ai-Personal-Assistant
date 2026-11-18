"""Settings, paths and small shared helpers for Jarvis."""
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# JARVIS_DATA_DIR: a different data folder (tests and test copies never touch your real settings)
DATA_DIR = Path(os.environ["JARVIS_DATA_DIR"]) if os.environ.get("JARVIS_DATA_DIR") else ROOT / "data"
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


_load_dotenv(ROOT / ".env")

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
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)

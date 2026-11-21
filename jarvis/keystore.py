"""API keys, encrypted for your Windows account (DPAPI) in keys.dat in the data folder.

Only the same Windows user on the same PC can decrypt them; no password to remember, nothing to pay for.
Keys found in plain text in .env are moved here automatically (and only removed from .env after they have been
read back correctly). Other .env settings stay where they are.

Nothing here ever prints or logs a key's value.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_SECRET = re.compile(r"^[A-Z0-9_]*(API_KEY|AUTH_TOKEN|SECRET|ACCESS_TOKEN)$")
_ENTROPY = b"Personal Assistant keys v1"


def is_secret(name: str) -> bool:
    return bool(_SECRET.match(name.strip()))


def default_file() -> Path:
    from .config import DATA_DIR
    return DATA_DIR / "keys.dat"


def _protect(data: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptProtectData(data, "Personal Assistant keys", _ENTROPY, None, None, 0)


def _unprotect(blob: bytes) -> bytes:
    import win32crypt
    return win32crypt.CryptUnprotectData(blob, _ENTROPY, None, None, 0)[1]


def available() -> bool:
    try:
        return _unprotect(_protect(b"ok")) == b"ok"
    except Exception:
        return False


def load(path: Path | None = None) -> dict[str, str]:
    """The stored keys ({} if there are none or they can't be read, e.g. keys.dat from another Windows user)."""
    path = Path(path or default_file())
    if not path.exists():
        return {}
    try:
        data = json.loads(_unprotect(path.read_bytes()).decode("utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[keys] couldn't read {path.name} ({type(e).__name__}); was it made by another Windows account?")
        return {}


def save(new: dict[str, str], path: Path | None = None) -> None:
    """Add or replace keys (empty values remove a key). Raises if the result can't be read back."""
    path = Path(path or default_file())
    merged = load(path)
    for k, v in new.items():
        if str(v or "").strip():
            merged[k] = str(v).strip()
        else:
            merged.pop(k, None)
    blob = _protect(json.dumps(merged).encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(blob)
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))
    if load(path) != merged:
        raise RuntimeError("the saved keys didn't read back correctly")
    for k, v in merged.items():
        os.environ[k] = v


def load_into_env(path: Path | None = None) -> list[str]:
    """Put the stored keys into the environment (a key already set there wins). Returns the names."""
    keys = load(path)
    for k, v in keys.items():
        os.environ.setdefault(k, v)
    return sorted(keys)


def migrate_env_file(env_file: Path, path: Path | None = None) -> list[str]:
    """Move plain-text keys from env_file into keys.dat. Returns the names moved ([] if nothing to do).

    Safe order: encrypt and save, read every key back, and only then rewrite env_file without them.
    If anything fails, env_file is left exactly as it was."""
    env_file = Path(env_file)
    if not env_file.exists():
        return []
    lines = env_file.read_text(encoding="utf-8").splitlines()
    found: dict[str, str] = {}
    for line in lines:
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            v = v.strip().strip('"').strip("'")
            if is_secret(k) and v:
                found[k.strip()] = v
    if not found:
        return []
    try:
        save(found, path)
        stored = load(path)
        if any(stored.get(k) != v for k, v in found.items()):
            raise RuntimeError("keys didn't read back correctly")
    except Exception as e:
        print(f"[keys] left the keys in {env_file.name} (couldn't encrypt them: {type(e).__name__})")
        return []
    keep = [line for line in lines
            if not (line.strip() and "=" in line and not line.strip().startswith("#")
                    and line.split("=", 1)[0].strip() in found)]
    note = f"# API keys moved to keys.dat (encrypted for your Windows account) on {time.strftime('%Y-%m-%d')}"
    if note.split(" on ")[0] not in "\n".join(keep):
        keep.append(note)
    tmp = env_file.with_name(env_file.name + ".tmp")
    tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
    os.replace(tmp, env_file)
    print(f"[keys] moved {len(found)} API key(s) from {env_file.name} into encrypted storage: {', '.join(sorted(found))}")
    return sorted(found)

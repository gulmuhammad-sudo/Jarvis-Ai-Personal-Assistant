"""Images (Phase 8): keeping what the Studio page edited, simple changes to picture files, and making pictures online.

Editing happens on this PC (in the page, or here with Pillow). Only making a picture goes online: the words you wrote go to
Pollinations.ai (free, no key), after you pressed the button or said yes. New files only, in Pictures\\Personal Assistant; what
is in a photo besides the picture (place, camera) isn't kept.
"""
from __future__ import annotations

import io
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

MAX_IN = 60 * 1024 ** 2
MAX_PIXELS = 60_000_000
MAX_SIDE = 12_000
READS = ("PNG", "JPEG", "WEBP", "BMP", "GIF", "TIFF", "AVIF")
WRITES = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}
SIZES = {"square": (1024, 1024), "wide": (1344, 768), "tall": (768, 1344)}
ONLINE = "https://image.pollinations.ai/prompt/"


def folder() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Pictures" / "Personal Assistant"


def _open(raw: bytes):
    """A picture, checked: its real kind (not its name), and not bigger than this PC can handle."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    if len(raw) > MAX_IN:
        raise ValueError("That picture is too large (up to 60 MB).")
    try:
        im = Image.open(io.BytesIO(raw), formats=READS)
        w, h = im.size
        if w * h > MAX_PIXELS or max(w, h) > MAX_SIDE:
            raise ValueError("That picture has too many pixels.")
        im.load()
        return ImageOps.exif_transpose(im)
    except (UnidentifiedImageError, OSError, SyntaxError, EOFError, Image.DecompressionBombError):
        raise ValueError("That isn't a picture I can read (PNG, JPEG, WebP, BMP, GIF, TIFF).") from None


def _encode(im, fmt: str, quality: int = 90) -> bytes:
    f = WRITES.get(str(fmt or "png").lower().lstrip("."))
    if not f:
        raise ValueError("I can save as png, jpg or webp.")
    q = max(10, min(100, int(quality)))
    out = io.BytesIO()
    if f == "JPEG":
        if im.mode not in ("RGB", "L"):
            from PIL import Image
            rgba = im.convert("RGBA")
            base = Image.new("RGB", rgba.size, (255, 255, 255))
            base.paste(rgba, mask=rgba.getchannel("A"))
            im = base
        im.save(out, "JPEG", quality=q, optimize=True)
    elif f == "WEBP":
        im.convert("RGBA" if "A" in im.mode or im.mode == "P" else "RGB").save(out, "WEBP", quality=q)
    else:
        im.convert("RGBA" if "A" in im.mode or im.mode == "P" else im.mode if im.mode in ("RGB", "L") else "RGB").save(out, "PNG", optimize=True)
    return out.getvalue()


def _name(text: Any, usual: str = "Picture") -> str:
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f.]+', " ", str(text or ""))
    n = " ".join(n.split())[:60].strip()
    return usual if not n or re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)", n) else n


def _store(data: bytes, name: str, ext: str, into: Path | None = None) -> Path:
    """Never over an existing file."""
    d = into or folder()
    d.mkdir(parents=True, exist_ok=True)
    for n in range(1, 1000):
        p = d / f"{name}{f' ({n})' if n > 1 else ''}.{ext}"
        try:
            with open(p, "xb") as f:
                f.write(data)
            return p
        except FileExistsError:
            continue
    raise ValueError("There are too many pictures of that name.")


def keep(raw: bytes, name: Any = "", fmt: Any = "png", quality: Any = 90) -> Path:
    """What the page edited. It is read and written again here: whatever else was in the bytes isn't kept."""
    im = _open(raw)
    f = str(fmt or "png").lower().lstrip(".")
    data = _encode(im, f, int(quality or 90))
    return _store(data, _name(name), "jpg" if f == "jpeg" else f)


def picture_path(path: Any) -> Path:
    """A picture file of the owner's, for the assistant: in the home folder, an ordinary file."""
    from . import guard
    raw = str(path or "").strip().strip('"')
    if not raw:
        raise ValueError("Which picture?")
    if guard.elsewhere(raw):
        raise ValueError("Pictures on other computers aren't read.")
    home = Path(os.environ.get("USERPROFILE", str(Path.home()))).resolve()
    p = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not p.is_absolute():
        p = next((q for q in (home / p, *(home / d / p for d in ("Pictures", "Pictures/Personal Assistant", "Desktop", "Downloads", "Documents"))) if q.is_file()), home / p)
    try:
        p = p.resolve(strict=True)
    except OSError:
        raise ValueError(f"There is no picture {raw!r}.") from None
    from .tools import _USER_DIRS
    if not any((home / d).resolve() in p.parents for d in _USER_DIRS) or not p.is_file():
        raise ValueError("I only open pictures in the user's own folders (Desktop, Documents, Downloads, Pictures, Music, Videos).")
    return p


def info(path: Any) -> dict:
    p = picture_path(path)
    im = _open(p.read_bytes())
    return {"path": str(p), "width": im.size[0], "height": im.size[1], "kb": p.stat().st_size // 1024}


def convert(path: Any, fmt: Any = "", max_side: Any = None, quality: Any = 85, rotate: Any = 0, grey: Any = False) -> Path:
    """A changed copy next to the original (the original stays)."""
    from PIL import Image
    p = picture_path(path)
    im = _open(p.read_bytes())
    r = int(rotate or 0) % 360
    if r not in (0, 90, 180, 270):
        raise ValueError("I can turn it by 90, 180 or 270 degrees.")
    if r:
        im = im.rotate(-r, expand=True)
    if max_side not in (None, "", 0):
        n = int(max_side)
        if not 16 <= n <= MAX_SIDE:
            raise ValueError(f"The longest side: 16 to {MAX_SIDE} pixels.")
        if max(im.size) > n:
            im.thumbnail((n, n), Image.LANCZOS)
    if grey is True:
        im = im.convert("LA" if "A" in im.mode else "L").convert("RGBA" if "A" in im.mode else "RGB")
    f = str(fmt or "").lower().lstrip(".") or {".png": "png", ".webp": "webp"}.get(p.suffix.lower(), "jpg")
    return _store(_encode(im, f, int(quality or 85)), _name(f"{p.stem} edited"), "jpg" if f == "jpeg" else f, p.parent)


# ---------------- making one online ----------------
def clean_prompt(text: Any) -> str:
    t = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).split())
    if len(t) < 3:
        raise ValueError("What should be in the picture?")
    if len(t) > 600:
        raise ValueError("Describe it in up to 600 characters.")
    return t


def generate(prompt: Any, size: Any = "square") -> bytes:
    """The picture as JPEG. The words go to Pollinations.ai (with its filter for indecent pictures on)."""
    t = clean_prompt(prompt)
    if str(size or "square") not in SIZES:
        raise ValueError(f"Sizes: {', '.join(SIZES)}.")
    w, h = SIZES[str(size or "square")]
    seed = int.from_bytes(os.urandom(4), "big") % 1_000_000
    url = ONLINE + urllib.parse.quote(t, safe="") + "?" + urllib.parse.urlencode({"width": w, "height": h, "seed": seed, "nologo": "true", "private": "true", "safe": "true"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "PersonalAssistant"}), timeout=120) as r:
            raw = r.read(MAX_IN + 1)
    except urllib.error.HTTPError as e:
        e.close()                                         # (its answer holds a connection)
        raise ValueError("The free service refused that description." if e.code in (400, 403, 451) else "The free service is busy. Try again in a minute." if e.code in (429, 500, 502, 503) else
                         f"The free service answered with an error ({e.code}).") from None
    except OSError:
        raise ValueError("The free service can't be reached. Is the internet on?") from None
    return _encode(_open(raw), "jpg", 93)


def make(prompt: Any, size: Any = "square") -> Path:
    data = generate(prompt, size)
    return _store(data, _name(clean_prompt(prompt)[:40], "Picture"), "jpg")


def listing(limit: int = 60) -> list[dict]:
    d = folder()
    rows = []
    if d.is_dir():
        for p in d.iterdir():
            if p.suffix.lower() in (".png", ".jpg", ".webp") and p.is_file():
                s = p.stat()
                rows.append({"name": p.name, "kb": s.st_size // 1024, "at": datetime.fromtimestamp(s.st_mtime).strftime("%Y-%m-%dT%H:%M:%S")})
    return sorted(rows, key=lambda r: r["at"], reverse=True)[:limit]


def path_of(name: Any) -> Path | None:
    n = str(name or "")
    if not n or n != Path(n).name or re.search(r'[<>:"/\\|?*\x00-\x1f]', n):
        return None
    p = folder() / n
    return p if p.suffix.lower() in (".png", ".jpg", ".webp") and p.is_file() and not p.is_symlink() else None

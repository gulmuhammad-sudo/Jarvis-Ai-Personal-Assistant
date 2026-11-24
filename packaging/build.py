"""Build the Windows app and its installer.

    .venv\\Scripts\\python.exe -m pip install pyinstaller
    .venv\\Scripts\\python.exe packaging\\build.py

Makes one file in the project, next to READ ME FIRST.txt where everyone sees it:
    Personal Assistant Setup.exe      the installer: the one file to run or share
(An older one is only replaced when the new one is finished.) Everything else is made in %TEMP%\\PersonalAssistant-build, so
the project folder stays clean:
    app\\Personal Assistant\\Personal Assistant.exe      the app itself, to test the build
    release\\      what goes on GitHub: Personal-Assistant-Setup.exe, the ZIP with the instructions, SHA256.txt (see release.py)
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
BUILD = Path(tempfile.gettempdir()) / "PersonalAssistant-build"     # work files: outside the project
RELEASE = BUILD / "release"
NAME = "Personal Assistant"
ICON = ROOT / "assets" / "jarvis.ico"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "jarvis" / "__init__.py").read_text(encoding="utf-8")).group(1)
SEP = ";"   # PyInstaller's --add-data separator on Windows
REPO = "gulmuhammad-sudo/Jarvis-Ai-Personal-Assistant"
README = ROOT / "READ ME FIRST.txt"
# folders that only the tools need: not shown in Explorer (nothing is deleted; Explorer › View › Hidden items shows them)
HIDE = (".venv", ".git", ".claude", ".pytest_cache", "data", "build", "__pycache__", "jarvis/__pycache__", "packaging/__pycache__", "tests/__pycache__")
EXCLUDE = ["tkinter", "matplotlib", "IPython", "pytest", "PyInstaller"]


def version_file(desc: str, exe: str) -> Path:
    """The Details tab of the .exe's Properties (name, version, description)."""
    v = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
    path = BUILD / f"version-{exe}.txt"
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'gulmuhammad-sudo'), StringStruct('FileDescription', '{desc}'),
    StringStruct('FileVersion', '{VERSION}'), StringStruct('InternalName', '{exe}'),
    StringStruct('OriginalFilename', '{exe}.exe'), StringStruct('ProductName', '{NAME}'),
    StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")
    return path


def pyinstaller(*args: str) -> None:
    # --clean: never reuse PyInstaller's cache (a cached build once shipped the previous version number)
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", f"--icon={ICON}",
           f"--workpath={BUILD / 'work'}", f"--specpath={BUILD}", *[f"--exclude-module={m}" for m in EXCLUDE], *args]
    print(">", " ".join(cmd[3:]), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def splash() -> Path:
    """The picture Setup shows while it unpacks itself (a few seconds without it: people click again)."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = 460, 150
    img = Image.new("RGB", (W, H), (8, 16, 24))
    glow = Image.new("RGB", (W, H), (8, 16, 24))
    ImageDraw.Draw(glow).ellipse((-120, -160, 260, 160), fill=(22, 74, 108))
    from PIL import ImageFilter
    img = glow.filter(ImageFilter.GaussianBlur(70))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W - 1, H - 1), outline=(60, 100, 128))
    icon = Image.open(ICON).convert("RGBA").resize((76, 76), Image.LANCZOS)
    img.paste(icon, (28, 37), icon)
    font = lambda name, size: ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / name), size)          # noqa: E731
    d.text((126, 42), NAME, font=font("segoeuib.ttf", 25), fill=(235, 246, 252))
    d.text((126, 82), "Setup is getting ready…", font=font("segoeui.ttf", 16), fill=(150, 178, 196))
    out = BUILD / "splash.png"
    img.save(out)
    return out


def release_files(setup: Path) -> None:
    """What a new user downloads: the Setup alone, or a ZIP that shows the Setup and the instructions as soon as it's opened."""
    shutil.rmtree(RELEASE, ignore_errors=True)
    RELEASE.mkdir(parents=True)
    exe, zip_ = RELEASE / "Personal-Assistant-Setup.exe", RELEASE / f"Personal-Assistant-{VERSION}.zip"
    shutil.copy2(setup, exe)
    with zipfile.ZipFile(zip_, "w", zipfile.ZIP_STORED) as z:
        z.write(setup, f"{NAME}/{NAME} Setup.exe")
        z.writestr(f"{NAME}/READ ME FIRST.txt", README.read_text(encoding="utf-8").replace("\n", "\r\n"))
    (RELEASE / "SHA256.txt").write_text("".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in (exe, zip_)), encoding="utf-8")


def tidy() -> None:
    """Only what matters shows in the project folder."""
    for name in HIDE:
        p = ROOT / name
        if p.exists():
            ctypes.windll.kernel32.SetFileAttributesW(str(p), ctypes.windll.kernel32.GetFileAttributesW(str(p)) | 0x02)


def main() -> None:
    if not ICON.exists():
        sys.path.insert(0, str(ROOT))
        from jarvis.install import make_icon
        make_icon()
    BUILD.mkdir(exist_ok=True)
    app_dir = BUILD / "app" / NAME
    shutil.rmtree(app_dir, ignore_errors=True)

    # 1) the app: one folder with "Personal Assistant.exe"
    pyinstaller(f"--name={NAME}", f"--distpath={BUILD / 'app'}",f"--version-file={version_file('Personal Assistant', NAME)}",
                f"--add-data={ROOT / 'jarvis' / 'hud.html'}{SEP}jarvis", f"--add-data={ROOT / 'assets'}{SEP}assets",
                "--collect-submodules=jarvis", "--collect-data=edge_tts", "--collect-data=certifi",
                "--collect-all=pywhispercpp",          # local speech-to-text: native whisper.cpp library
                "--collect-data=docx", "--collect-data=pptx",             # Word / PowerPoint templates
                "--collect-all=sherpa_onnx", "--collect-all=espeakng_loader",   # voices on this PC + espeak data
                str(PKG / "app.py"))

    # 2) the app folder, zipped, goes inside the installer
    payload = BUILD / "payload" / "app.zip"
    payload.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in sorted(app_dir.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(app_dir))
    print(f"payload: {payload.stat().st_size / 1e6:.0f} MB", flush=True)

    # 3) the installer: one file
    setup_name = f"{NAME} Setup"
    pyinstaller("--onefile", f"--name={setup_name}", f"--distpath={BUILD / 'setup'}", f"--splash={splash()}",
                f"--version-file={version_file('Personal Assistant installer', setup_name)}",
                f"--add-data={payload}{SEP}payload", f"--add-data={PKG / 'setup.html'}{SEP}.",
                f"--add-data={ROOT / 'assets'}{SEP}assets",
                *[f"--exclude-module={m}" for m in ("numpy", "scipy", "google", "openai", "anthropic", "sounddevice",
                                                    "PIL", "pycaw", "comtypes", "edge_tts")],
                str(PKG / "setup_app.py"))
    made, setup = BUILD / "setup" / f"{setup_name}.exe", ROOT / f"{setup_name}.exe"
    release_files(made)
    shutil.copy2(made, setup.with_suffix(".new"))
    os.replace(setup.with_suffix(".new"), setup)               # the old one stays until the new one is whole
    tidy()
    print(f"\nDone (version {VERSION}):\n  {app_dir / (NAME + '.exe')}\n  {RELEASE}\n  {setup}"
          f"  ({setup.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()

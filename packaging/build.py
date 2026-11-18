"""Build the Windows app and its installer.

    .venv\\Scripts\\python.exe -m pip install pyinstaller
    .venv\\Scripts\\python.exe packaging\\build.py

Makes:
    dist\\Personal Assistant\\Personal Assistant.exe    the app (one folder, what gets installed)
    dist\\Personal Assistant Setup.exe                 the installer: the one file to run or share
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
BUILD, DIST = ROOT / "build", ROOT / "dist"
NAME = "Personal Assistant"
ICON = ROOT / "assets" / "jarvis.ico"
VERSION = re.search(r'__version__ = "([^"]+)"', (ROOT / "jarvis" / "__init__.py").read_text(encoding="utf-8")).group(1)
SEP = ";"   # PyInstaller's --add-data separator on Windows
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
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", f"--icon={ICON}",
           f"--workpath={BUILD / 'work'}", f"--specpath={BUILD}", *[f"--exclude-module={m}" for m in EXCLUDE], *args]
    print(">", " ".join(cmd[3:]), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)


def main() -> None:
    if not ICON.exists():
        sys.path.insert(0, str(ROOT))
        from jarvis.install import make_icon
        make_icon()
    BUILD.mkdir(exist_ok=True)
    app_dir = DIST / NAME
    shutil.rmtree(app_dir, ignore_errors=True)

    # 1) the app: one folder with "Personal Assistant.exe"
    pyinstaller(f"--name={NAME}", f"--distpath={DIST}", f"--version-file={version_file('Personal Assistant', NAME)}",
                f"--add-data={ROOT / 'jarvis' / 'hud.html'}{SEP}jarvis", f"--add-data={ROOT / 'assets'}{SEP}assets",
                "--collect-submodules=jarvis", "--collect-data=edge_tts", "--collect-data=certifi",
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
    (DIST / f"{setup_name}.exe").unlink(missing_ok=True)
    pyinstaller("--onefile", f"--name={setup_name}", f"--distpath={DIST}",
                f"--version-file={version_file('Personal Assistant installer', setup_name)}",
                f"--add-data={payload}{SEP}payload", f"--add-data={PKG / 'setup.html'}{SEP}.",
                f"--add-data={ROOT / 'assets'}{SEP}assets",
                *[f"--exclude-module={m}" for m in ("numpy", "scipy", "google", "openai", "anthropic", "sounddevice",
                                                    "PIL", "pycaw", "comtypes", "edge_tts")],
                str(PKG / "setup_app.py"))
    print(f"\nDone (version {VERSION}):\n  {app_dir / (NAME + '.exe')}\n  {DIST / (setup_name + '.exe')}"
          f"  ({(DIST / (setup_name + '.exe')).stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()

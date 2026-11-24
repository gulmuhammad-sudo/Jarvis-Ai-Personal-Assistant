"""Put the build on GitHub as a release (what new users download).

    .venv\Scripts\python.exe packaging\release.py            checks everything, says what it would do
    .venv\Scripts\python.exe packaging\release.py --publish  does it (needs the GitHub command line, signed in)

Refuses when: the build isn't this version, the Setup in it is damaged, there are changes that aren't committed, or the tag
isn't on GitHub yet. The notes are docs/RELEASE_NOTES.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import RELEASE, REPO, ROOT, VERSION  # noqa: E402

NOTES = ROOT / "docs" / "RELEASE_NOTES.md"
TAG = f"v{VERSION}"


def run(*cmd: str, ok: bool = True) -> str:
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if ok and r.returncode:
        raise SystemExit(f"{' '.join(cmd[:3])}…: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout.strip()


def check() -> list[Path]:
    exe, zip_, sums = RELEASE / "Personal-Assistant-Setup.exe", RELEASE / f"Personal-Assistant-{VERSION}.zip", RELEASE / "SHA256.txt"
    for f in (exe, zip_, sums):
        if not f.is_file():
            raise SystemExit(f"{f.name} isn't there. Build first (packaging\\build.py).")
    for line in sums.read_text(encoding="utf-8").splitlines():
        want, name = line.split("  ")
        if hashlib.sha256((RELEASE / name).read_bytes()).hexdigest() != want:
            raise SystemExit(f"{name} isn't what was built.")
    out = Path(tempfile.mkdtemp(prefix="pa-check-")) / "r.json"
    subprocess.run([str(exe), "--check", str(out)], timeout=300, check=True, env={**os.environ, "PA_SETUP_TEST": "1", "JARVIS_DATA_DIR": str(out.parent / "data")})
    r = json.loads(out.read_text(encoding="utf-8"))
    if r["version"] != VERSION or r.get("damaged") or not r.get("exe") or not r["frozen"]:
        raise SystemExit(f"The Setup doesn't check out: {r}")
    if run("git", "status", "--porcelain"):
        raise SystemExit("There are changes that aren't committed.")
    if run("git", "rev-parse", f"{TAG}^{{commit}}") != run("git", "rev-parse", "HEAD") and run("git", "diff", "--name-only", TAG, "HEAD", "--", "jarvis", "packaging", "assets"):
        raise SystemExit(f"{TAG} isn't what is built now: tag the commit you built.")
    if not run("git", "ls-remote", "--tags", "origin", f"refs/tags/{TAG}"):
        raise SystemExit(f"{TAG} isn't on GitHub yet: push it first.")
    if f"# Personal Assistant {VERSION}" not in NOTES.read_text(encoding="utf-8"):
        raise SystemExit("docs/RELEASE_NOTES.md is still about another version.")
    return [exe, zip_, sums]


def main() -> None:
    files = check()
    print(f"{TAG}: everything checks out\n  " + "\n  ".join(f"{f.name}  {f.stat().st_size / 1e6:.1f} MB" for f in files))
    if "--publish" not in sys.argv:
        return print("Nothing published. Add --publish to do it.")
    body = NOTES.read_text(encoding="utf-8").split("\n", 1)[1].strip()
    notes = Path(tempfile.mkdtemp(prefix="pa-notes-")) / "notes.md"
    notes.write_text(body + "\n\n### Checksums (SHA-256)\n```\n" + files[2].read_text(encoding="utf-8") + "```\n", encoding="utf-8")
    # as a draft first: the download link never points at a release whose files are still being sent
    print(run("gh", "release", "create", TAG, "-R", REPO, "--draft", "--title", f"Personal Assistant {VERSION}", "--notes-file", str(notes), *map(str, files)))
    got = json.loads(run("gh", "release", "view", TAG, "-R", REPO, "--json", "assets"))["assets"]
    if {(a["name"], a["size"]) for a in got} != {(f.name, f.stat().st_size) for f in files}:
        raise SystemExit("Not all files arrived; the release is still a draft.")
    print(run("gh", "release", "edit", TAG, "-R", REPO, "--draft=false", "--latest"))


if __name__ == "__main__":
    main()

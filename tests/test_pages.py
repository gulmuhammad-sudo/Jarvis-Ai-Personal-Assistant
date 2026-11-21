"""The two HTML pages: their JavaScript must at least parse (a broken string once blanked the whole app)."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="Node.js not installed (only used to syntax-check the page scripts)")
@pytest.mark.parametrize("page", ["jarvis/hud.html", "packaging/setup.html"])
def test_page_script_parses(page, tmp_path):
    html = (ROOT / page).read_text(encoding="utf-8")
    js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    assert js.strip()
    f = tmp_path / "page.js"
    f.write_text(js, encoding="utf-8")
    r = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]


def test_every_button_the_script_uses_exists():
    html = (ROOT / "jarvis/hud.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([A-Za-z][\w-]*)"', html))
    used = set(re.findall(r'\$\("([A-Za-z][\w-]*)"\)\.on(?:click|change)', html))
    assert not (used - ids), f"script wires up missing elements: {sorted(used - ids)}"

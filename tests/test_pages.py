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


def test_focus_mode_shows_only_the_face_and_a_voice_dock():
    """Hide details = only the globe/rings/mask: menu, top bar and footer go; a small dock keeps mic, hands-free,
    spoken replies, Stop and a way back to the details."""
    html = (ROOT / "jarvis/hud.html").read_text(encoding="utf-8")
    assert "body.focus .side, body.focus .top, body.focus .foot { display: none !important; }" in html
    dock = re.search(r'<div class="fdock" id="fdock".*?</div>', html, re.S).group(0)
    assert all(f'id="{i}"' in dock for i in ("fdMic", "fdHf", "fdSpeak", "fdStop", "fdShow"))
    for wire in ('$("fdMic").onclick = () => listen()', '$("fdStop").onclick = () => $("stopBtn").click()',
                 '$("fdShow").onclick = () => $("detailsBtn").click()'):
        assert wire in html


@pytest.mark.parametrize("page", ["jarvis/hud.html", "packaging/setup.html"])
def test_nothing_is_defined_twice(page):
    """A second function with the same name silently replaces the first: a new renderAgents() once stopped the whole
    app at start-up, and the syntax check couldn't see it."""
    from collections import Counter
    html = (ROOT / page).read_text(encoding="utf-8")
    js = "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))
    names = re.findall(r"^(?:async )?function\*? (\w+)", js, re.M) + re.findall(r"^(?:const|let|var) (\w+)", js, re.M)
    assert not [n for n, c in Counter(names).items() if c > 1]
    ids = re.findall(r'\bid="([A-Za-z][\w-]*)"', re.sub(r"<script>.*?</script>", "", html, flags=re.S))
    assert not [i for i, c in Counter(ids).items() if c > 1]

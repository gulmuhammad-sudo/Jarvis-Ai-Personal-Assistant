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


def test_glass_is_not_paid_for_with_blur():
    """Blurring every panel doubled the CPU use of the page and looked the same: only popups are blurred. Solid without transparency effects."""
    html = (ROOT / "jarvis/hud.html").read_text(encoding="utf-8")
    css = re.search(r"<style>(.*?)</style>", html, re.S).group(1)
    blurred = {s.strip() for sel in re.findall(r"([^{}]+)\{[^{}]*backdrop-filter: blur", re.sub(r"/\*.*?\*/", "", css, flags=re.S)) for s in sel.split(",")}
    assert blurred and not {".card", ".hero", ".side > nav", ".foot", ".item", ".setrow", ".card:not(.hero)", ".card.page"} & blurred, blurred
    assert "prefers-reduced-transparency: reduce" in css and "select option, select optgroup { background: var(--solid)" in css


def test_voice_panel_is_the_same_at_every_height():
    """Its text once lay over the mic, and its layout kept changing with the window: now one layout, of one height.
    The rules need the .vbody prefix: without it the plain #wave / #vLabel / .mic rules further down win."""
    html = (ROOT / "jarvis/hud.html").read_text(encoding="utf-8")
    assert "container: voice" not in html and ".voicecard { flex: none; height: 122px; }" in html
    for part in (".vbody .mic { grid-column: 1; grid-row: 1 / span 2; width: 52px;", ".vbody #vLabel { grid-column: 2; grid-row: 1;", ".vbody #wave { grid-column: 2; grid-row: 2;", ".vbody .unmute { grid-column: 2; grid-row: 2;"):
        assert part in html, part


def test_page_lookups_never_find_the_menu_button():
    """[data-view="x"] is on the menu button too, and it comes first: the Planner's buttons were wired to nothing."""
    html = (ROOT / "jarvis/hud.html").read_text(encoding="utf-8")
    assert not re.findall(r"""querySelector\(['"]\[data-view=""", html)


def test_no_function_is_written_twice():
    """A second function with the same name silently replaces the first: the ringing popup was drawn by the orb's drawRings."""
    html = (ROOT / "jarvis/hud.html").read_text(encoding="utf-8")
    names = re.findall(r"^(?:async )?function (\w+)", html, re.M)
    assert len(names) > 100 and sorted(n for n in set(names) if names.count(n) > 1) == []


def test_no_name_is_declared_twice():
    """Two top-level lets with one name stop the whole page from loading (nearly shipped: dxSeq)."""
    html = (ROOT / "jarvis/hud.html").read_text(encoding="utf-8")
    names = re.findall(r"^(?:async )?function (\w+)", html, re.M)
    for line in re.findall(r"^(?:let|const|var) (.*)$", html, re.M):
        depth, start = 0, True                                # names at the top of the list, not inside the values
        for part in re.split(r"([(\[{}\])]|, |;|`[^`]*`|\"[^\"]*\"|'[^']*')", line):
            if part in ("(", "[", "{"):
                depth += 1
            elif part in (")", "]", "}"):
                depth -= 1
            elif part == ", ":
                start = depth == 0
                continue
            elif part == ";" and depth == 0:
                break
            m = re.match(r"(\w+)\s*(=|$)", part or "") if start and depth == 0 else None
            if m:
                names.append(m.group(1))
            if part:
                start = False
    assert len(names) > 300 and sorted(n for n in set(names) if names.count(n) > 1) == []

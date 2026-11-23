"""Documents (Phase 7): read PDF, Word, Excel, PowerPoint and text files; make Word, Excel, PowerPoint and PDF files.

Reading never runs anything: macros, formulas and links in a file are ignored, only its text is taken. Files are checked
first (size, "zip bombs", XML that pulls in other files), and a file that takes too long is given up on.
Making: from Markdown (headings, lists, tables, **bold**) or, for Excel, rows. Excel formulas are kept only when they are
plain arithmetic from a short list of functions: others can fetch addresses or start programs, so they become text.
PDFs are printed by Windows' own Edge, hidden and without internet, so Urdu comes out right.
"""
from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Any

MAX_FILE = 60 * 2**20
MAX_UNPACKED = 300 * 2**20
MAX_PART = 80 * 2**20
MAX_CHARS = 400_000
MAX_PAGES = 1000
SECONDS = 60
TEXT = {".txt", ".md", ".csv", ".tsv", ".log", ".json", ".xml", ".html", ".htm", ".rtf", ".py", ".js", ".ini", ".yaml", ".yml", ".srt"}
OFFICE = {".docx", ".xlsx", ".pptx"}
READS = TEXT | OFFICE | {".pdf"}
MAKES = {".docx", ".xlsx", ".pptx", ".pdf"}
_ARABIC = re.compile(r"[֐-ࣿיִ-﷿ﹰ-ﻼ]")


# ---------------- reading ----------------
def check_file(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"There's no file at {path}.")
    if path.suffix.lower() not in READS:
        raise ValueError(f"I can read {', '.join(sorted(READS))}, not {path.suffix or 'that file'}.")
    size = path.stat().st_size
    if size > MAX_FILE:
        raise ValueError(f"That file is too big ({size // 2**20} MB; up to {MAX_FILE // 2**20}).")
    if path.suffix.lower() in OFFICE:
        _check_zip(path)


def _check_zip(path: Path) -> None:
    """An Office file is a zip of XML parts: refuse ones that unpack to far too much, or whose XML defines entities
    (a way to read other files or to fill the memory)."""
    try:
        with zipfile.ZipFile(path) as z:
            parts = z.infolist()
            if len(parts) > 10_000 or sum(p.file_size for p in parts) > MAX_UNPACKED:
                raise ValueError("That file unpacks to far too much, so I won't open it.")
            for p in parts:
                if p.file_size > 2**20 and p.file_size > 300 * max(1, p.compress_size):
                    raise ValueError("That file unpacks to far too much, so I won't open it.")
                if not p.filename.lower().endswith((".xml", ".rels", ".vml")):
                    continue
                if p.file_size > MAX_PART:
                    raise ValueError("That file is too big inside.")
                with z.open(p) as f:              # read in pieces; what the header says about sizes isn't trusted
                    total, tail = 0, b""
                    while True:
                        chunk = f.read(2**20)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_PART:
                            raise ValueError("That file is too big inside.")
                        seen = (tail + chunk).replace(b"\0", b"").upper()
                        if b"<!DOCTYPE" in seen or b"<!ENTITY" in seen:
                            raise ValueError("That file has unusual XML that could pull in other files, so I won't open it.")
                        tail = chunk[-32:]
    except zipfile.BadZipFile:
        raise ValueError("That file is damaged, or it has a password, or it isn't really an Office file.") from None


def _limited(fn, *args, seconds: float = SECONDS):
    """Run fn, but give up after a while (a damaged file can keep a reader busy for ever)."""
    box: dict[str, Any] = {}
    stop = threading.Event()

    def work():
        try:
            box["out"] = fn(*args, stop)
        except BaseException as e:                # noqa: BLE001  (handed to the caller below)
            box["err"] = e
    t = threading.Thread(target=work, daemon=True, name="read-document")
    t.start()
    t.join(seconds)
    if t.is_alive():
        stop.set()
        raise ValueError("That file takes too long to read, so I gave up.")
    if "err" in box:
        e = box["err"]
        if isinstance(e, ValueError) and getattr(e, "mine", False):
            raise e
        raise ValueError(f"I couldn't read that file; it may be damaged ({type(e).__name__}).") from e
    return box["out"]


def _mine(text: str) -> ValueError:
    e = ValueError(text)
    e.mine = True                                 # type: ignore[attr-defined]
    return e


def _pdf(path: Path, stop) -> list[tuple[str, str]]:
    import logging

    import pypdf
    logging.getLogger("pypdf").setLevel(logging.CRITICAL)
    r = pypdf.PdfReader(str(path), strict=False)
    if r.is_encrypted and not r.decrypt(""):
        raise _mine("That PDF has a password.")
    out, total = [], 0
    for n, page in enumerate(r.pages, 1):
        if stop.is_set() or n > MAX_PAGES or total > MAX_CHARS:
            break
        # PDFs keep Urdu as joined letter shapes: back to normal letters, or a search never finds them
        text = unicodedata.normalize("NFKC", page.extract_text() or "").strip()
        total += len(text)
        out.append((f"page {n}", text))
    return out


def _docx(path: Path, stop) -> list[tuple[str, str]]:
    import docx
    from docx.table import Table
    d = docx.Document(str(path))
    lines: list[str] = []
    for item in d.iter_inner_content():
        if stop.is_set():
            break
        if isinstance(item, Table):
            for row in item.rows:
                cells: list[str] = []
                for c in row.cells:                # a merged cell comes once per column
                    t = " ".join(c.text.split())
                    if not cells or cells[-1] != t:
                        cells.append(t)
                lines.append(" | ".join(cells))
        elif item.text.strip():
            style = (item.style.name or "") if item.style is not None else ""
            level = re.match(r"Heading (\d)", style)
            lines.append(("#" * int(level.group(1)) + " " if level else "- " if style.startswith("List") else "") + item.text)
    return [("", "\n".join(lines))]


def _xlsx(path: Path, stop) -> list[tuple[str, str]]:
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True, keep_links=False)
    out = []
    try:
        for ws in wb.worksheets[:50]:
            rows, blank = [], 0
            for row in ws.iter_rows(max_row=20_000, max_col=100, values_only=True):
                if stop.is_set() or len(rows) > 5000 or blank > 200:
                    break
                vals = ["" if v is None else str(v).replace("\t", " ").replace("\n", " ") for v in row]
                while vals and not vals[-1]:
                    vals.pop()
                blank = 0 if vals else blank + 1
                if vals:
                    rows.append("\t".join(vals))
            out.append((f"sheet {ws.title}", "\n".join(rows)))
    finally:
        wb.close()
    return out


def _pptx(path: Path, stop) -> list[tuple[str, str]]:
    import pptx
    out = []
    for n, slide in enumerate(pptx.Presentation(str(path)).slides, 1):
        if stop.is_set() or n > MAX_PAGES:
            break
        lines: list[str] = []

        def take(shapes, depth=0):
            for s in shapes:
                if getattr(s, "has_table", False) and s.has_table:
                    lines.extend(" | ".join(" ".join(c.text.split()) for c in r.cells) for r in s.table.rows)
                elif s.has_text_frame and s.text_frame.text.strip():
                    lines.append(s.text_frame.text.strip())
                elif hasattr(s, "shapes") and depth < 5:
                    take(s.shapes, depth + 1)
        take(slide.shapes)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame and slide.notes_slide.notes_text_frame.text.strip():
            lines.append("(speaker notes) " + slide.notes_slide.notes_text_frame.text.strip())
        out.append((f"slide {n}", "\n".join(lines)))
    return out


def _plain(path: Path, stop) -> list[tuple[str, str]]:
    raw = path.read_bytes()[:MAX_CHARS * 4]
    for enc in ("utf-8-sig", "utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "replace")
    if path.suffix.lower() in (".html", ".htm"):
        text = re.sub(r"(?is)<(script|style).*?</\1\s*>", " ", text)
        text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    if path.suffix.lower() == ".rtf":
        text = re.sub(r"\{\\\*?\\[^{}]*\}|\\[a-z]+-?\d* ?|[{}]", "", text)
    return [("", text)]


def parts(path: Path, seconds: float = SECONDS) -> list[tuple[str, str]]:
    """The text of a document as (label, text): a page, sheet or slide each, or one part without a label."""
    check_file(path)
    fn = {".pdf": _pdf, ".docx": _docx, ".xlsx": _xlsx, ".pptx": _pptx}.get(path.suffix.lower(), _plain)
    return _limited(fn, path, seconds=seconds)


def _wanted(spec: Any, items: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """'3', '2-5', '1,4' or a sheet's name."""
    s = " ".join(str(spec or "").lower().replace("pages", "").replace("page", "").replace("slides", "").replace("slide", "").split())
    if not s:
        return items
    named = [i for i in items if i[0].lower() in (s, f"sheet {s}")]
    if named:
        return named
    nums: set[int] = set()
    for bit in s.split(","):
        m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", bit)
        if not m:
            raise ValueError(f"Which part? There are: {', '.join(i[0] for i in items[:12])}" + (" …" if len(items) > 12 else "") + ".")
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        nums.update(range(a, min(b, a + MAX_PAGES) + 1))
    out = [x for n, x in enumerate(items, 1) if n in nums]
    if not out:
        raise ValueError(f"It only has {len(items)} parts.")
    return out


def read(path: Path, part: Any = "", limit: int = 40_000) -> str:
    """The text for the AI, with the parts marked; says so when there's more or nothing to read."""
    items = parts(path)
    chosen = _wanted(part, items)
    text = "\n\n".join((f"[{label}]\n" if label else "") + t for label, t in chosen if t.strip())
    if not text.strip():
        return ("There's no text in it. It is probably a scan (pictures of pages)." if path.suffix.lower() == ".pdf" else "It is empty.")
    head = f"{path.name}" + (f", {len(items)} parts" if len(items) > 1 else "") + "\n"
    more = f"\n[... the first {limit} of {len(text)} characters; ask for a part, e.g. pages 5-8]" if len(text) > limit else ""
    return head + text[:limit] + more


# ---------------- Markdown -> blocks ----------------
def blocks(markdown: str) -> list[tuple[str, Any]]:
    """('h', level, text) | ('p', text) | ('li', ordered, text) | ('table', rows) | ('rule',)"""
    out: list = []
    lines = str(markdown or "").replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1
            continue
        m = re.match(r"(#{1,6})\s+(.*)", ln)
        if m:
            out.append(("h", min(len(m.group(1)), 4), m.group(2).strip(" #")))
        elif re.fullmatch(r"\s*([-*_])(\s*\1){2,}\s*", ln):
            out.append(("rule",))
        elif ln.lstrip().startswith("|") and ln.count("|") >= 2:
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            width = max((len(r) for r in rows), default=0)
            if rows:
                out.append(("table", [r + [""] * (width - len(r)) for r in rows]))
            continue
        elif re.match(r"\s*[-*•]\s+", ln):
            out.append(("li", False, re.sub(r"^\s*[-*•]\s+", "", ln)))
        elif re.match(r"\s*\d+[.)]\s+", ln):
            out.append(("li", True, re.sub(r"^\s*\d+[.)]\s+", "", ln)))
        else:
            out.append(("p", ln.strip()))
        i += 1
    return out


def spans(text: str) -> list[tuple[str, bool]]:
    """[(text, bold)] from **bold**; other marks are dropped."""
    out = []
    for n, bit in enumerate(re.split(r"\*\*(.+?)\*\*", text)):
        bit = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", bit).replace("`", "")
        if bit:
            out.append((bit, n % 2 == 1))
    return out or [("", False)]


def _clean(text: Any) -> str:
    """Characters Office files can't hold."""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]", "", str(text))


# ---------------- making ----------------
def _make_docx(path: Path, title: str, markdown: str) -> None:
    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    d = docx.Document()

    def fill(p, text: str):
        for t, bold in spans(_clean(text)):
            run = p.add_run(t)
            run.bold = bold or None
        if _ARABIC.search(text):                  # Urdu: right to left
            p.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p._p.get_or_add_pPr().append(OxmlElement("w:bidi"))
            for run in p.runs:
                run._r.get_or_add_rPr().append(OxmlElement("w:rtl"))
        return p
    if title:
        fill(d.add_heading("", 0), title)
    for b in blocks(markdown):
        if b[0] == "h":
            fill(d.add_heading("", b[1]), b[2])
        elif b[0] == "li":
            fill(d.add_paragraph(style="List Number" if b[1] else "List Bullet"), b[2])
        elif b[0] == "table":
            t = d.add_table(rows=len(b[1]), cols=len(b[1][0]))
            t.style = "Table Grid"
            for r, row in enumerate(b[1]):
                for c, cell in enumerate(row):
                    p = fill(t.cell(r, c).paragraphs[0], cell)
                    if r == 0:
                        for run in p.runs:
                            run.bold = True
        elif b[0] == "rule":
            d.add_paragraph("―" * 20)
        else:
            fill(d.add_paragraph(), b[1])
    d.core_properties.title, d.core_properties.author = _clean(title)[:200], ""
    d.save(str(path))


_FUNCTIONS = {"SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "COUNTIF", "SUMIF", "AVERAGEIF", "ROUND", "ROUNDUP", "ROUNDDOWN", "IF", "AND", "OR",
              "NOT", "ABS", "INT", "MOD", "MEDIAN", "SUMPRODUCT", "TODAY", "NOW", "YEAR", "MONTH", "DAY", "PRODUCT", "LEN", "IFERROR", "POWER", "SQRT"}


def safe_formula(text: str) -> bool:
    """Plain arithmetic over cells of this file with the functions above. Nothing that reaches outside: no other file, no
    address, no DDE, no WEBSERVICE / HYPERLINK / INDIRECT."""
    if not re.fullmatch(r"=[A-Za-z0-9_$:(),.+\-*/^%<>=&!'\" ]{1,500}", text) or re.search(r"://|\\|\[|\||@|#", text):
        return False
    bare = re.sub(r"\"[^\"]*\"|'[^']*'", "", text)         # words inside quotes aren't functions
    return all(f.upper() in _FUNCTIONS for f in re.findall(r"([A-Za-z_.][\w.]*)\s*\(", bare)) and "'" not in bare.replace("''", "")


def _cell(v: Any) -> Any:
    if isinstance(v, bool) or v is None or isinstance(v, (int, float)):
        return v
    s = _clean(v)[:32_000]
    t = s.strip()
    if re.fullmatch(r"-?\d{1,15}", t) and not re.match(r"-?0\d", t):          # keep 0300-… and long numbers as text
        return int(t)
    if re.fullmatch(r"-?(0|[1-9]\d{0,14})\.\d{1,10}", t):
        return float(t)
    return s


def sheets_from(content: Any) -> dict[str, list[list[Any]]]:
    """Rows from JSON ({"Sheet": [[...], ...]} or [[...], ...]), a Markdown table, or CSV text."""
    data = content
    if isinstance(content, str):
        t = content.strip()
        if t[:1] in "[{":
            try:
                data = json.loads(t)
            except ValueError:
                raise ValueError("The rows aren't valid JSON.") from None
        else:
            tables = [b[1] for b in blocks(t) if b[0] == "table"]
            data = {f"Sheet{n}": rows for n, rows in enumerate(tables, 1)} if tables else [r for r in csv.reader(io.StringIO(t)) if r]
    if isinstance(data, list):
        data = {"Sheet1": data}
    if not isinstance(data, dict) or not data:
        raise ValueError("There are no rows.")
    out: dict[str, list[list[Any]]] = {}
    for name, rows in list(data.items())[:30]:
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):         # [{"a": 1}, ...]
            keys = list(dict.fromkeys(k for r in rows if isinstance(r, dict) for k in r))
            rows = [keys] + [[r.get(k) for k in keys] for r in rows if isinstance(r, dict)]
        if not isinstance(rows, list) or not all(isinstance(r, (list, tuple)) for r in rows):
            raise ValueError("Each sheet must be a list of rows.")
        if len(rows) > 20_000 or any(len(r) > 200 for r in rows):
            raise ValueError("That's too many rows or columns.")
        title = re.sub(r"[\\/*?:\[\]]", " ", _clean(name)).strip("' ")[:31] or f"Sheet{len(out) + 1}"
        while title.lower() in (k.lower() for k in out):
            title = f"{title[:27]} {len(out) + 1}"
        out[title] = [list(r) for r in rows]
    return out


def _make_xlsx(path: Path, title: str, content: Any) -> int:
    """Returns how many formulas were turned into text."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    blocked = 0
    for name, rows in sheets_from(content).items():
        ws = wb.create_sheet(name)
        for r, row in enumerate(rows, 1):
            for c, v in enumerate(row, 1):
                if isinstance(v, (list, dict)):
                    v = json.dumps(v, ensure_ascii=False)
                v = _cell(v)
                cell = ws.cell(r, c)
                if isinstance(v, str) and v.lstrip().startswith("="):
                    if safe_formula(v.strip()):
                        cell.value = v.strip()
                    else:
                        cell.value, blocked = v, blocked + 1
                        cell.data_type = "s"
                        cell.quotePrefix = True
                else:
                    cell.value = v
                    if isinstance(v, str):
                        cell.data_type = "s"
                if isinstance(v, str) and _ARABIC.search(v):
                    cell.alignment = Alignment(horizontal="right", readingOrder=2, wrap_text=len(v) > 60)
                elif isinstance(v, str) and len(v) > 60:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        if rows and all(isinstance(v, str) and v for v in rows[0]) and len(rows) > 1:        # a heading row
            for cell in ws[1]:
                cell.font, cell.fill = Font(bold=True), PatternFill("solid", fgColor="DDEBF7")
            ws.freeze_panes = "A2"
        for c in range(1, max((len(r) for r in rows), default=0) + 1):
            ws.column_dimensions[get_column_letter(c)].width = min(60, max([8] + [len(str(r[c - 1])) + 2 for r in rows[:300] if len(r) >= c and r[c - 1] is not None]))
    wb.properties.title, wb.properties.creator = _clean(title)[:200], ""
    wb.save(str(path))
    return blocked


def slides_from(title: str, markdown: str) -> list[dict]:
    """[{title, lines: [(text, level, bullet)], table, notes}]: each # or ## heading starts a slide; '>' lines are speaker notes."""
    out: list[dict] = []
    cur: dict | None = None
    for raw in str(markdown or "").replace("\r\n", "\n").split("\n"):
        if raw.lstrip().startswith(">"):
            if cur is not None:
                cur["notes"].append(raw.lstrip("> ").strip())
            continue
        if not raw.strip():
            continue
        m = re.match(r"#{1,2}\s+(.*)", raw)
        if m or cur is None:
            cur = {"title": m.group(1).strip() if m else title, "lines": [], "table": [], "notes": []}
            out.append(cur)
            if m:
                continue
        if raw.lstrip().startswith("|"):
            cells = [c.strip() for c in raw.strip().strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                cur["table"].append(cells)
            continue
        level = min(2, (len(raw) - len(raw.lstrip())) // 2)
        text = re.sub(r"^\s*([-*•]|\d+[.)]|#{3,6})\s+", "", raw).strip()
        if not re.fullmatch(r"[-*_ ]{3,}", text):
            cur["lines"].append((text, level, bool(re.match(r"\s*([-*•]|\d+[.)])\s+", raw))))
    # too much for one slide goes on to the next
    full: list[dict] = []
    for s in out[:200]:
        first = True
        lines = s["lines"]
        while first or lines:
            take, size = [], 0
            while lines and len(take) < 8 and (size + len(lines[0][0]) < 620 or not take):
                size += len(lines[0][0])
                take.append(lines[0])
                lines = lines[1:]
            full.append({**s, "lines": take, "table": s["table"] if first else [], "notes": s["notes"] if first else [],
                         "title": s["title"] if first else s["title"] + " (2)"})
            first = False
    return full


THEMES = {"light": ("FFFFFF", "1F2937", "2563EB"), "dark": ("0B1220", "E5EDF5", "5CCFFF"), "green": ("F4FBF6", "12352A", "15803D"),
          "warm": ("FFF9F2", "3B2A1E", "C2410C")}


def _make_pptx(path: Path, title: str, markdown: str, theme: str = "light") -> int:
    import pptx
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Inches, Pt
    bg, ink, accent = (RGBColor.from_string(c) for c in THEMES.get(str(theme).lower(), THEMES["light"]))
    prs = pptx.Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]

    def new():
        s = prs.slides.add_slide(blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = bg
        return s

    def text(slide, box, lines, size, bold=False, colour=None, centre=False):
        tf = slide.shapes.add_textbox(*box).text_frame
        tf.word_wrap = True
        for n, (t, level, bullet) in enumerate(lines):
            p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
            rtl = bool(_ARABIC.search(t))
            for k, (bit, b) in enumerate(spans(_clean(t))):
                r = p.add_run()
                r.text = ("– " if level else "• ") + bit if bullet and not k and not centre else bit
                r.font.size, r.font.bold = Pt(size - 3 * level), bold or b
                r.font.color.rgb = colour or ink
            p.space_after = Pt(size * .45)
            if rtl:
                p.alignment = PP_ALIGN.RIGHT
                p._p.get_or_add_pPr().set("rtl", "1")
            elif centre:
                p.alignment = PP_ALIGN.CENTER
            p.level = 0
    slides = slides_from(title, markdown)
    n = 0
    if title:
        s = new()
        text(s, (Inches(1), Inches(2.6), Inches(11.3), Inches(1.6)), [(title, 0, False)], 44, True, accent, True)
        n += 1
        if slides and slides[0]["title"].strip().lower() == title.strip().lower() and not slides[0]["table"] and len(slides[0]["lines"]) <= 2:
            if slides[0]["lines"]:
                text(s, (Inches(1.5), Inches(4.3), Inches(10.3), Inches(1.2)), [(x[0], 0, False) for x in slides[0]["lines"]], 22, False, ink, True)
            slides = slides[1:]
    for sl in slides:
        s = new()
        n += 1
        text(s, (Inches(.7), Inches(.45), Inches(11.9), Inches(1)), [(sl["title"], 0, False)], 32, True, accent)
        bar = s.shapes.add_shape(1, Inches(.75), Inches(1.42), Inches(1.4), Emu(38100))
        bar.fill.solid()
        bar.fill.fore_color.rgb = accent
        bar.line.fill.background()
        top = 1.75
        if sl["lines"]:
            size = 24 if sum(len(x[0]) for x in sl["lines"]) < 320 else 19
            text(s, (Inches(.75), Inches(top), Inches(11.8), Inches(5.2 if not sl["table"] else 2.2)), sl["lines"], size)
            top = 4.1
        rows = [r for r in sl["table"] if r][:14]
        if rows:
            cols = min(8, max(len(r) for r in rows))
            t = s.shapes.add_table(len(rows), cols, Inches(.75), Inches(top), Inches(11.8), Inches(.42 * len(rows))).table
            for r, row in enumerate(rows):
                for c in range(cols):
                    cell = t.cell(r, c)
                    cell.text = _clean(row[c]) if c < len(row) else ""
                    for p in cell.text_frame.paragraphs:
                        p.font.size = Pt(15)
        if sl["notes"]:
            s.notes_slide.notes_text_frame.text = _clean("\n".join(sl["notes"]))
    if not n:
        raise ValueError("There's nothing to put on the slides.")
    prs.core_properties.title, prs.core_properties.author = _clean(title)[:200], ""
    prs.save(str(path))
    return n


def to_html(title: str, markdown: str) -> str:
    """A page for printing: our own tags only, everything else escaped, and nothing may be loaded."""
    def inline(t: str) -> str:
        return "".join(f"<b>{html.escape(x)}</b>" if b else html.escape(x) for x, b in spans(_clean(t)))

    def rtl(t: str) -> str:
        return ' dir="rtl"' if _ARABIC.search(t) else ""
    out, lst = [], ""
    for b in blocks(markdown):
        want = ("ol" if b[1] else "ul") if b[0] == "li" else ""
        if lst and want != lst:
            out.append(f"</{lst}>")
            lst = ""
        if b[0] == "li":
            if not lst:
                out.append(f"<{want}{rtl(b[2])}>")
                lst = want
            out.append(f"<li{rtl(b[2])}>{inline(b[2])}</li>")
        elif b[0] == "h":
            out.append(f"<h{b[1]}{rtl(b[2])}>{inline(b[2])}</h{b[1]}>")
        elif b[0] == "table":
            rows = "".join("<tr>" + "".join(f"<{'th' if n == 0 else 'td'}{rtl(c)}>{inline(c)}</{'th' if n == 0 else 'td'}>" for c in r) + "</tr>" for n, r in enumerate(b[1]))
            out.append(f"<table>{rows}</table>")
        elif b[0] == "rule":
            out.append("<hr>")
        else:
            out.append(f"<p{rtl(b[1])}>{inline(b[1])}</p>")
    if lst:
        out.append(f"</{lst}>")
    head = f"<h1 class=t{rtl(title)}>{html.escape(_clean(title))}</h1>" if title else ""
    return ("<!doctype html><html><head><meta charset=utf-8><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
            f"<title>{html.escape(_clean(title))}</title><style>@page{{size:A4;margin:20mm}}body{{font:12pt/1.55 'Segoe UI','Noto Nastaliq Urdu','Jameel Noori Nastaleeq',sans-serif;color:#111}}"
            "h1.t{font-size:24pt;margin:0 0 12pt}h1,h2,h3,h4{line-height:1.3;margin:14pt 0 6pt;page-break-after:avoid}p{margin:0 0 8pt}table{border-collapse:collapse;margin:8pt 0;width:100%}"
            "td,th{border:1px solid #999;padding:4pt 7pt;text-align:start;vertical-align:top}th{background:#eef3f8}tr{page-break-inside:avoid}[dir=rtl]{line-height:2.1}</style></head><body>"
            + head + "".join(out) + "</body></html>")


def edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        p = Path(base or "", "Microsoft", "Edge", "Application", "msedge.exe") if base else None
        if p and p.is_file():
            return str(p)
    return shutil.which("msedge")


def _sweep(folder: Path) -> None:
    """Remove Edge's temporary profile (it can hold on to a file for a moment after it ends), and any an earlier crash left."""
    for _ in range(40):
        shutil.rmtree(folder, ignore_errors=True)
        if not folder.exists():
            break
        time.sleep(0.25)
    for old in folder.parent.glob("pa-pdf-*"):
        try:
            if old.is_dir() and not old.is_symlink() and time.time() - old.stat().st_mtime > 600:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass


def _make_pdf(path: Path, title: str, markdown: str) -> None:
    exe = edge()
    if not exe:
        raise ValueError("Making a PDF needs Microsoft Edge, and it isn't on this PC. Make a Word file instead.")
    tmp = tempfile.mkdtemp(prefix="pa-pdf-")
    try:
        page, out = Path(tmp) / "page.html", Path(tmp) / "out.pdf"
        page.write_text(to_html(title, markdown), encoding="utf-8")
        # its own empty profile (never yours), no window, no internet
        args = [exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-sync",
                "--disable-background-networking", "--disable-component-update", "--proxy-server=http://127.0.0.1:9", "--no-pdf-header-footer",
                f"--user-data-dir={Path(tmp) / 'profile'}", f"--print-to-pdf={out}", page.as_uri()]
        p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        end = time.time() + 60
        while time.time() < end and p.poll() is None:
            time.sleep(0.2)
        if p.poll() is None:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        for _ in range(25):                       # Edge may finish writing a moment after it ends
            if out.is_file() and out.stat().st_size > 400:
                break
            time.sleep(0.2)
        if not out.is_file() or not out.read_bytes().startswith(b"%PDF"):
            raise ValueError("Edge couldn't make the PDF. Make a Word file instead.")
        shutil.move(str(out), str(path))
    finally:
        try:
            (Path(tmp) / "page.html").unlink(missing_ok=True)
        except OSError:
            pass
        threading.Thread(target=_sweep, args=(Path(tmp),), daemon=True).start()


def make(path: Path, content: Any, title: str = "", theme: str = "light") -> str:
    """Write a document (by its ending). It is made next to its place first and only then put there."""
    kind = path.suffix.lower()
    if kind not in MAKES:
        raise ValueError(f"I can make {', '.join(sorted(MAKES))}.")
    title = " ".join(str(title or "").split())[:200]
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    if len(text) > MAX_CHARS * 2:
        raise ValueError("That's too much text for one file.")
    if not text.strip() and not title:
        raise ValueError("There's nothing to write.")
    if kind in (".docx", ".pdf") and title:       # the title is written once, even if the text starts with it
        m = re.match(r"\s*#\s+(.+?)\s*#*\s*(?:\n|$)", text)
        if m and " ".join(m.group(1).replace("*", "").split()).casefold() == title.casefold():
            text = text[m.end():]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"~pa-{os.getpid()}-{threading.get_ident()}{kind}")
    note = ""
    try:
        if kind == ".docx":
            _make_docx(tmp, title, text)
        elif kind == ".pptx":
            note = f", {_make_pptx(tmp, title, text, theme)} slides"
        elif kind == ".pdf":
            _make_pdf(tmp, title, text)
        else:
            n = _make_xlsx(tmp, title, content)
            note = f" ({n} formula(s) kept as text because they could reach outside the file)" if n else ""
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return f"Made {path}{note}."

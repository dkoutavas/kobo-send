"""Convert a PDF to a reflowable EPUB: marker for the text, glyph positions for the code.

This module runs in the marker virtual environment, not in the kobo-send one:

    <marker venv>/bin/python -m kobo_send.reflow book.pdf book.epub

marker 2.0 (fast mode, no OCR) reads the PDF text layer and finds the layout:
paragraphs, headings, tables, figures and captions. It labels each line of a
code listing as a separate Text block, so the indentation and the column
alignment are lost. The PDF still has them: code is set in a fixed-pitch font,
and each glyph has an exact x position. This module finds the runs of
fixed-pitch lines with pdftext, rebuilds each run as <pre> from the glyph
columns, and keeps the marker HTML for every other block.

The functions that transform the data do not import marker or pdftext, so the
unit tests run in the standard kobo-send environment.
"""

from __future__ import annotations

import base64
import html
import io
import json
import re
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import epub

FIXED_PITCH = 1  # PDF font descriptor flag, bit 1
MONO_NAME = re.compile(r"courier|mono|consol|menlo|inconsolata|lettergothic|typewriter", re.I)
SKIP_BLOCKS = {"PageHeader", "PageFooter"}
REF = re.compile(r"<content-ref src=['\"]([^'\"]+)['\"]></content-ref>")
HEADING = re.compile(r"^\s*<h([1-6])\b")
TAGS = re.compile(r"<[^>]+>")
CHAPTER_LEVEL = 1  # without PDF bookmarks, a heading at this level or higher starts a new chapter
MAX_CHAPTERS = 100  # with PDF bookmarks, split at the deepest level that gives at most this many chapters
CAPTION_GAP = 20.0  # points between a listing caption and the code below it
PDFTEXT_BATCH = 50  # pages for each pdftext call, to limit memory with keep_chars
MIN_CHARS_PER_PAGE = 50  # below this, the PDF has no usable text layer


class ReflowError(Exception):
    pass


@dataclass
class Part:
    html: str
    level: int = 0  # heading level, or 0 for body content
    title: str = ""


@dataclass
class Images:
    files: dict[str, bytes] = field(default_factory=dict)

    def add(self, b64: str) -> str:
        data = base64.b64decode(b64)
        ext = "png" if data.startswith(b"\x89PNG") else "jpg"
        name = f"img{len(self.files) + 1:04d}.{ext}"
        self.files[name] = data
        return name


# ---- Code listings -----------------------------------------------------------


def is_mono(span: dict) -> bool:
    font = span["font"]
    return bool((font.get("flags") or 0) & FIXED_PITCH) or bool(MONO_NAME.search(font.get("name") or ""))


def page_lines(page: dict) -> list[dict]:
    """Return the text lines of one pdftext page. Only fixed-pitch lines keep their glyphs."""
    lines = []
    for block in page["blocks"]:
        for line in block["lines"]:
            text = "".join(s["text"] for s in line["spans"]).strip()
            if not text:
                continue
            mono = all(is_mono(s) for s in line["spans"] if s["text"].strip())
            chars = [c for s in line["spans"] for c in s["chars"] if not c["char"].isspace()] if mono else []
            lines.append({"bbox": line["bbox"], "text": text, "mono": mono, "chars": chars})
    return lines


def code_runs(lines: list[dict]) -> list[dict]:
    """Group fixed-pitch lines that sit close together in one column."""
    runs: list[dict] = []
    for line in sorted((l for l in lines if l["mono"]), key=lambda l: (l["bbox"][1], l["bbox"][0])):
        x0, y0, x1, y1 = line["bbox"]
        run = runs[-1] if runs else None
        if run and y0 - run["bbox"][3] < 1.5 * (y1 - y0) and x0 <= run["bbox"][2] and x1 >= run["bbox"][0] - 60:
            run["lines"].append(line)
            rb = run["bbox"]
            run["bbox"] = [min(rb[0], x0), rb[1], max(rb[2], x1), max(rb[3], y1)]
        else:
            runs.append({"lines": [line], "bbox": list(line["bbox"])})
    return runs


def render_run(run: dict) -> str:
    """Place every glyph at its column, so the indentation and the alignment come back."""
    steps = [
        b["bbox"][0] - a["bbox"][0]
        for line in run["lines"]
        for a, b in zip(line["chars"], line["chars"][1:])
        if b["bbox"][0] > a["bbox"][0]
    ]
    # Most neighbouring glyphs are one column apart. Steps over a space are multiples of that.
    width = min(statistics.median(steps), statistics.mode(round(s, 1) for s in steps)) if steps else 1.0
    left = min(c["bbox"][0] for line in run["lines"] for c in line["chars"])
    out: list[str] = []
    prev_bottom = None
    for line in run["lines"]:
        top, bottom = line["bbox"][1], line["bbox"][3]
        if prev_bottom is not None and top - prev_bottom > 0.8 * (bottom - top):
            out.append("")  # a blank line in the listing
        row: list[str] = []
        for c in line["chars"]:
            col = max(round((c["bbox"][0] - left) / width), len(row))
            row.extend(" " * (col - len(row)))
            row.append(c["char"])
        out.append("".join(row))
        prev_bottom = bottom
    return "<pre><code>" + html.escape("\n".join(out)) + "</code></pre>"


def centre_in(bbox: list[float], box: list[float]) -> bool:
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    return box[0] - 1 <= cx <= box[2] + 1 and box[1] - 1 <= cy <= box[3] + 1


def caption_targets(blocks: list[dict], runs: list[dict]) -> dict[str, int]:
    """Map each Caption block id to the code run that starts right below it.

    marker sometimes puts a listing caption after the next paragraph. The page
    position is reliable: the caption sits directly above its listing.
    """
    targets = {}
    for b in blocks:
        if b["block_type"] != "Caption":
            continue
        for i, run in enumerate(runs):
            gap = run["bbox"][1] - b["bbox"][3]
            overlaps = run["bbox"][0] < b["bbox"][2] and run["bbox"][2] > b["bbox"][0]
            if 0 <= gap <= CAPTION_GAP and overlaps:
                targets[b["id"]] = i
                break
    return targets


# ---- Pages and chapters ------------------------------------------------------


def text_of(fragment: str) -> str:
    return " ".join(html.unescape(TAGS.sub(" ", fragment)).split())


def index(block: dict, by_id: dict[str, dict]) -> None:
    by_id[block["id"]] = block
    for child in block.get("children") or []:
        index(child, by_id)


def resolve(block: dict, by_id: dict[str, dict], images: Images) -> str:
    """Return the HTML of a block, with its child blocks and its image filled in."""
    own = (block.get("images") or {}).get(block["id"])
    if own:
        return f'<img src="../images/{images.add(own)}" alt=""/>'
    return REF.sub(
        lambda m: resolve(by_id[m.group(1)], by_id, images) if m.group(1) in by_id else "",
        block.get("html") or "",
    )


def page_parts(mpage: dict, lines: list[dict], images: Images) -> list[Part]:
    """Turn one marker page into parts, with the code listings rebuilt from the glyphs."""
    by_id: dict[str, dict] = {}
    index(mpage, by_id)
    blocks = mpage.get("children") or []
    runs = code_runs(lines)
    run_of = {id(l): i for i, run in enumerate(runs) for l in run["lines"]}
    captions = caption_targets(blocks, runs)
    captions_of: dict[int, list[dict]] = {}
    for cid, i in captions.items():
        captions_of.setdefault(i, []).append(by_id[cid])

    parts: list[Part] = []
    emitted: set[int] = set()
    for block in blocks:
        if block["block_type"] in SKIP_BLOCKS or block["id"] in captions:
            continue
        inside = [] if (block.get("images") or {}).get(block["id"]) else [
            l for l in lines if centre_in(l["bbox"], block["bbox"])
        ]
        mono = [l for l in inside if l["mono"]]
        # A paragraph can have a wrapped line that is all code. Only a mostly fixed-pitch block is a listing.
        if not mono or 2 * len(mono) < len(inside):
            body = resolve(block, by_id, images)
            if not body.strip():
                continue
            m = HEADING.match(body) if block["block_type"] == "SectionHeader" else None
            parts.append(Part(body, int(m.group(1)), text_of(body)) if m else Part(body))
            continue
        for i in dict.fromkeys(run_of[id(l)] for l in mono):
            if i in emitted:
                continue
            emitted.add(i)
            parts += [Part(resolve(c, by_id, images)) for c in captions_of.get(i, [])]
            parts.append(Part(render_run(runs[i])))
        # Prose that marker merged into the listing block, such as a margin note.
        notes = [l["text"] for l in inside if not l["mono"]]
        if notes:
            parts.append(Part(f'<p class="note">{html.escape(" ".join(notes))}</p>'))
    return parts


def split_depth(outline: list[tuple[int, str, int]]) -> int:
    """The deepest bookmark level that splits the book into at most MAX_CHAPTERS chapters."""
    depth = 0
    for level in sorted({lvl for lvl, _, _ in outline}):
        if sum(1 for lvl, _, _ in outline if lvl <= level) > MAX_CHAPTERS:
            break
        depth = level
    return depth


def build(
    pages: list[tuple[int, list[Part]]], outline: list[tuple[int, str, int]], book_title: str
) -> tuple[list[epub.Chapter], list[epub.TocEntry] | None]:
    """Split the pages into chapters at the PDF bookmarks, and turn every bookmark into a TOC entry.

    Each page starts with an anchor, so a bookmark inside a chapter links to its page.
    Without bookmarks, fall back to the headings and a flat table of contents.
    """
    if not outline:
        return chapters([part for _, parts in pages for part in parts], book_title), None
    depth = split_depth(outline)
    starts: dict[int, str] = {}
    for level, title, page in outline:
        if level <= depth:
            starts.setdefault(page, title)
    out: list[epub.Chapter] = []
    body: list[str] = []
    title = book_title
    first_page: list[int] = []
    chapter_of: dict[int, int] = {}
    for number, parts in pages:
        if number in starts and body:
            out.append(epub.Chapter(title, "\n".join(body)))
            body = []
        if not body:  # the first page of a chapter
            first_page.append(number)
            title = starts.get(number, title)
        chapter_of[number] = len(out)
        body.append(f'<span id="p{number}"></span>')
        body += [p.html for p in parts]
    if body:
        out.append(epub.Chapter(title, "\n".join(body)))
    toc = []
    for level, entry_title, page in outline:
        if page not in chapter_of:
            continue
        i = chapter_of[page]
        anchor = "" if first_page[i] == page else f"#p{page}"
        toc.append(epub.TocEntry(level, entry_title, f"text/{epub.chapter_name(i)}{anchor}"))
    return out, toc


def chapters(parts: list[Part], book_title: str) -> list[epub.Chapter]:
    """Start a new chapter at each heading of level CHAPTER_LEVEL or higher."""
    out: list[epub.Chapter] = []
    body: list[str] = []
    title = book_title
    for part in parts:
        starts = 0 < part.level <= CHAPTER_LEVEL
        if starts and body:
            out.append(epub.Chapter(title, "\n".join(body)))
            body = []
        if starts:
            title = part.title or f"Section {len(out) + 1}"
        body.append(part.html)
    if body:
        out.append(epub.Chapter(title, "\n".join(body)))
    return out


# ---- marker, pdftext and pypdfium2 (marker environment only) -----------------


def run_marker(pdf: Path, workdir: Path) -> dict:
    marker = Path(sys.executable).with_name("marker_single")
    link = workdir / "book.pdf"  # a plain name, so the marker output path is predictable
    link.symlink_to(pdf.resolve())
    cmd = [
        str(marker), str(link), "--mode", "fast", "--disable_ocr",
        "--output_format", "json", "--output_dir", str(workdir / "out"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    out = workdir / "out" / "book" / "book.json"
    if result.returncode != 0 or not out.is_file():
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-15:])
        raise ReflowError(f"marker_single failed (exit {result.returncode})\n{tail}")
    return json.loads(out.read_text(encoding="utf-8"))


def pdf_lines(pdf: Path, pages: list[int]) -> dict[int, list[dict]]:
    from pdftext.extraction import dictionary_output

    out: dict[int, list[dict]] = {}
    for start in range(0, len(pages), PDFTEXT_BATCH):
        batch = pages[start : start + PDFTEXT_BATCH]
        for number, page in zip(batch, dictionary_output(str(pdf), page_range=batch, keep_chars=True)):
            out[number] = page_lines(page)
    return out


@dataclass
class Info:
    title: str
    author: str
    cover: bytes
    outline: list[tuple[int, str, int]]  # (level, title, page index) for each bookmark


def pdf_info(pdf: Path) -> Info:
    """Read the metadata and the bookmarks, and render the first page as the cover."""
    import pypdfium2

    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        meta = doc.get_metadata_dict()
        outline = []
        for mark in doc.get_toc():
            dest = mark.get_dest()
            page = dest.get_index() if dest else None
            if page is not None:
                outline.append((mark.level, " ".join(mark.get_title().split()), page))
        image = doc[0].render(scale=1.5).to_pil().convert("RGB")
    finally:
        doc.close()
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=85)
    return Info((meta.get("Title") or "").strip(), (meta.get("Author") or "").strip(), buf.getvalue(), outline)


def convert(pdf: Path, out: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="kobo-reflow-") as tmp:
        doc = run_marker(pdf, Path(tmp))
    mpages = doc["children"]
    numbers = [int(re.search(r"/page/(\d+)/", p["id"]).group(1)) for p in mpages]
    lines = pdf_lines(pdf, numbers)
    if sum(len(l["text"]) for page in lines.values() for l in page) < MIN_CHARS_PER_PAGE * max(len(numbers), 1):
        raise ReflowError("the PDF has almost no text layer, probably a scan. Use the fit mode for it.")
    images = Images()
    pages = [(n, page_parts(mpage, lines[n], images)) for mpage, n in zip(mpages, numbers)]
    info = pdf_info(pdf)
    title = info.title or pdf.stem
    book, toc = build(pages, info.outline, title)
    epub.write(out, title=title, author=info.author, chapters=book, images=images.files, cover=info.cover, toc=toc)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print("usage: python -m kobo_send.reflow BOOK.pdf OUT.epub", file=sys.stderr)
        return 2
    try:
        convert(Path(args[0]), Path(args[1]))
    except ReflowError as e:
        print(f"reflow: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Prototype: rebuild the code regions in marker JSON output from PDF glyph positions.

marker labels each line of a code listing as a separate Text block, so the
indentation and column alignment are lost. The PDF still has them: code is set
in a fixed-pitch font, and each glyph has an exact x position. This script
finds the runs of fixed-pitch lines with pdftext, rebuilds each run as <pre>
from the glyph columns, and keeps marker's HTML for every other block.

Run it with the Python of the marker virtual environment:
    python codefix.py book.pdf marker-output.json out.html
"""

from __future__ import annotations

import html
import json
import re
import statistics
import sys

from pdftext.extraction import dictionary_output

FIXED_PITCH = 1  # PDF font descriptor flag, bit 1
MONO_NAME = re.compile(r"courier|mono|consol|menlo|inconsolata|lettergothic|typewriter", re.I)
SKIP_BLOCKS = {"PageHeader", "PageFooter"}
REF = re.compile(r"<content-ref src=['\"]([^'\"]+)['\"]></content-ref>")


def is_mono(span: dict) -> bool:
    font = span["font"]
    return bool(font.get("flags", 0) & FIXED_PITCH) or bool(MONO_NAME.search(font.get("name") or ""))


def page_lines(page: dict) -> list[dict]:
    lines = []
    for block in page["blocks"]:
        for line in block["lines"]:
            chars = [c for s in line["spans"] for c in s["chars"] if not c["char"].isspace()]
            if not chars:
                continue
            mono = all(is_mono(s) for s in line["spans"] if s["text"].strip())
            text = "".join(s["text"] for s in line["spans"]).strip()
            lines.append({"bbox": line["bbox"], "chars": chars, "mono": mono, "text": text})
    return lines


def code_runs(lines: list[dict]) -> list[dict]:
    """Group fixed-pitch lines that sit close together in one column."""
    runs: list[dict] = []
    for line in sorted((l for l in lines if l["mono"]), key=lambda l: (l["bbox"][1], l["bbox"][0])):
        x0, y0, x1, y1 = line["bbox"]
        height = y1 - y0
        run = runs[-1] if runs else None
        if run and y0 - run["bbox"][3] < 1.5 * height and x0 <= run["bbox"][2] and x1 >= run["bbox"][0] - 60:
            run["lines"].append(line)
            rb = run["bbox"]
            run["bbox"] = [min(rb[0], x0), rb[1], max(rb[2], x1), max(rb[3], y1)]
        else:
            runs.append({"lines": [line], "bbox": list(line["bbox"])})
    return runs


def render_run(run: dict) -> str:
    """Place every glyph at its column, so indentation and alignment come back."""
    steps = [
        b["bbox"][0] - a["bbox"][0]
        for line in run["lines"]
        for a, b in zip(line["chars"], line["chars"][1:])
        if b["bbox"][0] > a["bbox"][0]
    ]
    width = min(statistics.median(steps), statistics.mode(round(s, 1) for s in steps)) if steps else 1.0
    left = min(c["bbox"][0] for line in run["lines"] for c in line["chars"])
    out, prev_bottom = [], None
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


def resolve(block: dict, by_id: dict[str, dict]) -> str:
    return REF.sub(lambda m: resolve(by_id[m.group(1)], by_id) if m.group(1) in by_id else "", block.get("html") or "")


def index(block: dict, by_id: dict[str, dict]) -> None:
    by_id[block["id"]] = block
    for child in block.get("children") or []:
        index(child, by_id)


def fix_page(mpage: dict, lines: list[dict]) -> tuple[str, int]:
    by_id: dict[str, dict] = {}
    index(mpage, by_id)
    runs = code_runs(lines)
    run_of = {id(l): r for r in runs for l in r["lines"]}
    emitted: set[int] = set()
    parts = []
    for block in mpage.get("children") or []:
        if block["block_type"] in SKIP_BLOCKS:
            continue
        inside = [l for l in lines if centre_in(l["bbox"], block["bbox"])]
        touched = [run_of[id(l)] for l in inside if l["mono"]]
        if not touched:
            parts.append(resolve(block, by_id))
            continue
        for run in touched:
            if id(run) not in emitted:
                emitted.add(id(run))
                parts.append(render_run(run))
        # Prose that marker merged into the code block, such as a margin note.
        notes = [l for l in inside if not l["mono"]]
        if notes:
            text = " ".join(l["text"] for l in notes)
            parts.append(f'<p class="note">{html.escape(text)}</p>')
    return "\n".join(parts), len(emitted)


def main(pdf: str, marker_json: str, out_html: str) -> None:
    doc = json.load(open(marker_json, encoding="utf-8"))
    mpages = doc["children"]
    numbers = [int(re.search(r"/page/(\d+)/", p["id"]).group(1)) for p in mpages]
    ppages = dictionary_output(pdf, page_range=numbers, keep_chars=True)
    body, total = [], 0
    for mpage, ppage in zip(mpages, ppages):
        part, n = fix_page(mpage, page_lines(ppage))
        body.append(part)
        total += n
    with open(out_html, "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset=utf-8><body>\n" + "\n".join(body) + "\n</body>\n")
    print(f"{len(mpages)} pages, {total} code blocks rebuilt -> {out_html}")


if __name__ == "__main__":
    main(*sys.argv[1:4])

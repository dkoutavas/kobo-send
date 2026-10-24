"""Light reflow: read the PDF with pypdfium2 only, without marker and torch.

This module runs in an environment that has pypdfium2 (for now the marker one).

It reads the glyphs into the line dicts that reflow.page_lines expects, so code
listings are rebuilt by the same code as in reflow mode. The grouping function is
pure and unit-tested on synthetic glyphs. Only pdf_glyphs, in the last section,
calls pdfium.
"""

from __future__ import annotations

import math

LINE_BREAKS = {"\r", "\n"}  # pdfium puts a line break between two text lines


def lines_from_glyphs(glyphs: list[dict]) -> dict:
    """Group glyphs, in pdfium text order, into a pdftext-style page with one block.

    A line break starts a new line, and so does a glyph whose vertical centre is more than half
    a line height away from the previous glyph: pdfium joins a line that ends in a hyphen to
    the next line, which is right for prose but wrong for a wrapped line of code.
    A font change starts a new span in the line.
    """
    lines: list[dict] = []
    current: list[dict] = []
    last = None  # the previous visible glyph
    for glyph in glyphs:
        visible = glyph["char"] not in LINE_BREAKS and not glyph["char"].isspace()
        if glyph["char"] in LINE_BREAKS or (visible and last and _other_line(glyph["bbox"], last["bbox"])):
            if current:
                lines.append(_line(current))
            current = []
        if glyph["char"] not in LINE_BREAKS:
            current.append(glyph)
        if visible:
            last = glyph
    if current:
        lines.append(_line(current))
    return {"blocks": [{"lines": lines}]}


def _other_line(box: list[float], prev: list[float]) -> bool:
    return abs((box[1] + box[3]) - (prev[1] + prev[3])) / 2 > (prev[3] - prev[1]) / 2


def _line(glyphs: list[dict]) -> dict:
    spans: list[dict] = []
    for g in glyphs:
        if not spans or spans[-1]["font"] != g["font"]:
            spans.append({"text": "", "font": g["font"], "chars": []})
        spans[-1]["text"] += g["char"]
        spans[-1]["chars"].append({"char": g["char"], "bbox": g["bbox"]})
    # pdfium gives generated spaces an empty box, so only visible glyphs define the line box.
    boxes = [g["bbox"] for g in glyphs if not g["char"].isspace()] or [g["bbox"] for g in glyphs]
    bbox = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    return {"bbox": bbox, "spans": spans}


# ---- pdfium (needs pypdfium2) ------------------------------------------------


def pdf_glyphs(page) -> list[dict]:
    """Every upright glyph of a pypdfium2 page: char, box in points from the top left, font name and flags.

    The box is the loose one (the glyph advance, not its ink), as in pdftext, so reflow.page_lines
    sees the same input.
    ponytail: rotated glyphs are skipped. In the test books they are diagram labels, which the
    figure step renders as images. Page rotation is ignored too. Add both when a book needs them.
    """
    from ctypes import byref, c_int, create_string_buffer

    import pypdfium2.raw as pdfium_c

    left, bottom, right, top = page.get_bbox()
    height = math.ceil(abs(top - bottom))
    textpage = page.get_textpage()
    raw = textpage.raw
    loose = pdfium_c.FS_RECTF()
    name, flags = create_string_buffer(256), c_int()
    fonts: dict[tuple[str, int], dict] = {}  # one dict for each font, so a span can compare fonts by value
    glyphs = []
    for i in range(textpage.count_chars()):
        code = pdfium_c.FPDFText_GetUnicode(raw, i)
        char = "�" if 0xD800 <= code <= 0xDFFF else chr(code)  # lone surrogates come from broken font maps
        if pdfium_c.FPDFText_IsHyphen(raw, i):
            char = "-"  # pdfium reports a hyphen at the end of a line as "\x02"
        if pdfium_c.FPDFText_GetCharAngle(raw, i) != 0:
            continue
        pdfium_c.FPDFText_GetLooseCharBox(raw, i, loose)
        x0, y0, x1, y1 = loose.left, loose.bottom, loose.right, loose.top
        size = pdfium_c.FPDFText_GetFontInfo(raw, i, name, len(name), byref(flags))
        key = (name.value.decode("utf-8", errors="replace") if 0 < size <= len(name) else "", flags.value)
        font = fonts.setdefault(key, {"name": key[0], "flags": key[1]})
        ya, yb = height - (y0 - bottom), height - (y1 - bottom)
        glyphs.append({
            "char": char,
            "bbox": [min(x0, x1) - left, min(ya, yb), max(x0, x1) - left, max(ya, yb)],
            "font": font,
        })
    textpage.close()
    return glyphs

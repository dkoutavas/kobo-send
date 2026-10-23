"""A small EPUB 3 writer and an HTML-to-XHTML cleaner. Standard library only."""

from __future__ import annotations

import html
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

KEEP_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code", "b", "strong", "i", "em", "u",
    "sub", "sup", "a", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th", "td",
    "blockquote", "img", "br", "hr", "span", "div", "figure", "figcaption",
}
VOID_TAGS = {"br", "hr", "img"}
KEEP_ATTRS = {"href", "src", "alt", "colspan", "rowspan", "class", "id"}
PAGE_ANCHOR = re.compile(r"p\d+")  # the only ids kept: page anchors that the table of contents links to
# Characters that XML 1.0 does not allow. PDF text layers contain some of them.
_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")

CSS = """\
body { margin: 0 2%; }
pre { white-space: pre-wrap; font-family: monospace; font-size: 0.75em; line-height: 1.25; margin: 0.8em 0; }
p.note { font-size: 0.85em; font-style: italic; margin-left: 1em; padding-left: 0.5em; border-left: 2px solid #888; }
img { max-width: 100%; }
table { border-collapse: collapse; font-size: 0.85em; }
th, td { border: 1px solid #888; padding: 0.2em 0.4em; }
"""

CONTAINER = """\
<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""


@dataclass(frozen=True)
class Chapter:
    title: str
    body: str  # HTML fragment. write() cleans it to XHTML.


@dataclass(frozen=True)
class TocEntry:
    level: int  # 0 is the top level
    title: str
    href: str  # relative to OEBPS, for example "text/ch0003.xhtml#p170"


def chapter_name(index: int) -> str:
    return f"ch{index + 1:04d}.xhtml"


def esc(text: str) -> str:
    return html.escape(_BAD_XML.sub("", text))


class _Cleaner(HTMLParser):
    """Keep a safe subset of tags and attributes, close every tag, escape all text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in KEEP_TAGS:
            return
        kept = []
        for name, value in attrs:
            value = value or ""
            # marker writes in-page anchors that do not exist in the EPUB. Keep web links only.
            if name not in KEEP_ATTRS or (name == "href" and not value.startswith(("http://", "https://"))):
                continue
            if name == "id" and not PAGE_ANCHOR.fullmatch(value):
                continue
            kept.append(f' {name}="{esc(value)}"')
        if tag in VOID_TAGS:
            self.out.append(f"<{tag}{''.join(kept)}/>")
        else:
            self.out.append(f"<{tag}{''.join(kept)}>")
            self.open.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.open:
            return
        while self.open:
            closed = self.open.pop()
            self.out.append(f"</{closed}>")
            if closed == tag:
                break

    def handle_data(self, data: str) -> None:
        self.out.append(esc(data))

    def close(self) -> None:
        super().close()
        while self.open:
            self.out.append(f"</{self.open.pop()}>")


def to_xhtml(fragment: str) -> str:
    cleaner = _Cleaner()
    cleaner.feed(fragment)
    cleaner.close()
    return "".join(cleaner.out)


def write(
    path: Path,
    *,
    title: str,
    author: str,
    chapters: list[Chapter],
    images: dict[str, bytes],
    cover: bytes | None = None,
    toc: list[TocEntry] | None = None,
    language: str = "en",
) -> None:
    """Write an EPUB 3 file with an EPUB 2 NCX table of contents as well, for older readers.

    Without a toc, the table of contents lists the chapters.
    """
    uid = f"urn:uuid:{uuid.uuid4()}"
    names = [chapter_name(i) for i in range(len(chapters))]
    if toc is None:
        toc = [TocEntry(0, c.title, f"text/{n}") for n, c in zip(names, chapters)]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        # The mimetype entry must come first and must not be compressed.
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/style.css", CSS)
        for name, chapter in zip(names, chapters):
            z.writestr(f"OEBPS/text/{name}", _page(chapter.title, to_xhtml(chapter.body), language))
        for name, data in images.items():
            z.writestr(f"OEBPS/images/{name}", data)
        if cover:
            z.writestr("OEBPS/images/cover.jpg", cover)
        z.writestr("OEBPS/nav.xhtml", _nav(toc, language))
        z.writestr("OEBPS/toc.ncx", _ncx(uid, title, toc))
        z.writestr("OEBPS/content.opf", _opf(uid, title, author, language, names, images, cover is not None))


def _page(title: str, body: str, language: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{language}" lang="{language}">\n'
        f'<head><title>{esc(title)}</title><link rel="stylesheet" type="text/css" href="../style.css"/></head>\n'
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def _depths(toc: list[TocEntry]) -> list[int]:
    """Nesting depth of each entry. A level can go down one step at a time only."""
    depths: list[int] = []
    for e in toc:
        depths.append(0 if not depths else max(0, min(e.level, depths[-1] + 1)))
    return depths


def _nav(toc: list[TocEntry], language: str) -> str:
    out, cur = ["<ol>"], 0
    for i, (e, d) in enumerate(zip(toc, _depths(toc))):
        if i:
            # A deeper entry opens a list inside the open <li>. Otherwise close back to its depth.
            out.append("<ol>" if d > cur else "</li>" + "</ol></li>" * (cur - d))
        out.append(f'<li><a href="{esc(e.href)}">{esc(e.title)}</a>')
        cur = d
    out.append(("</li>" + "</ol></li>" * cur) if toc else "")
    out.append("</ol>")
    items = "\n".join(out)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{language}" lang="{language}">\n<head><title>Contents</title></head>\n'
        f'<body><nav epub:type="toc"><h1>Contents</h1>\n{items}\n</nav></body>\n</html>\n'
    )


def _ncx(uid: str, title: str, toc: list[TocEntry]) -> str:
    out, cur = [], 0
    for i, (e, d) in enumerate(zip(toc, _depths(toc))):
        if i and d <= cur:
            out.append("</navPoint>" * (cur - d + 1))
        out.append(
            f'<navPoint id="np{i + 1}" playOrder="{i + 1}"><navLabel><text>{esc(e.title)}</text></navLabel>'
            f'<content src="{esc(e.href)}"/>'
        )
        cur = d
    if toc:
        out.append("</navPoint>" * (cur + 1))
    points = "\n".join(out)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'<head><meta name="dtb:uid" content="{uid}"/></head>\n'
        f"<docTitle><text>{esc(title)}</text></docTitle>\n<navMap>\n{points}\n</navMap>\n</ncx>\n"
    )


def _opf(
    uid: str, title: str, author: str, language: str, names: list[str], images: dict[str, bytes], cover: bool
) -> str:
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = [
        f'<dc:identifier id="uid">{uid}</dc:identifier>',
        f"<dc:title>{esc(title)}</dc:title>",
        f"<dc:language>{language}</dc:language>",
        f'<meta property="dcterms:modified">{modified}</meta>',
    ]
    if author:
        meta.insert(2, f"<dc:creator>{esc(author)}</dc:creator>")
    items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="style.css" media-type="text/css"/>',
    ]
    if cover:
        meta.append('<meta name="cover" content="cover"/>')
        items.append('<item id="cover" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>')
    items += [f'<item id="{n[:-6]}" href="text/{n}" media-type="application/xhtml+xml"/>' for n in names]
    for name in images:
        kind = "image/png" if name.endswith(".png") else "image/jpeg"
        items.append(f'<item id="{name.rsplit(".", 1)[0]}" href="images/{name}" media-type="{kind}"/>')
    spine = "\n".join(f'<itemref idref="{n[:-6]}"/>' for n in names)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n' + "\n".join(meta) + "\n</metadata>\n"
        "<manifest>\n" + "\n".join(items) + "\n</manifest>\n"
        f'<spine toc="ncx">\n{spine}\n</spine>\n</package>\n'
    )

"""The reflow transforms on small synthetic pages. marker and pdftext are not needed."""

import base64
import unittest
from unittest import mock

from kobo_send import reflow

CHAR = 4.8  # Courier glyph advance at 8 pt
MONO = {"name": "Courier", "flags": 1}
SERIF = {"name": "NewBaskerville-Roman", "flags": 0}


def line(text, x, y, font=MONO, height=7.0):
    """A pdftext line with one glyph for each character, CHAR points apart."""
    chars = [
        {"char": ch, "bbox": [x + i * CHAR, y, x + (i + 1) * CHAR, y + height]}
        for i, ch in enumerate(text)
    ]
    span = {"text": text, "font": font, "chars": chars}
    return {"bbox": [x, y, x + len(text) * CHAR, y + height], "spans": [span]}


def pdftext_page(*lines):
    return {"blocks": [{"lines": list(lines)}]}


YAML = [("apiVersion: v1", 0), ("metadata:", 0), ("name: kubia", 2), ("ports:", 2), ("targetPort: 8080", 4)]


def yaml_lines(top=100.0):
    # pdftext keeps one space where the PDF has two or four, so indent with a single space and move x.
    return [
        line((" " if cols else "") + text, 100.0 + (cols - 1) * CHAR if cols else 100.0, top + 9 * i)
        for i, (text, cols) in enumerate(YAML)
    ]


class CodeTest(unittest.TestCase):
    def test_indentation_comes_from_glyph_positions(self):
        lines = reflow.page_lines(pdftext_page(*yaml_lines()))
        runs = reflow.code_runs(lines)
        self.assertEqual(len(runs), 1)
        self.assertEqual(
            reflow.render_run(runs[0]),
            "<pre><code>apiVersion: v1\nmetadata:\n  name: kubia\n  ports:\n    targetPort: 8080</code></pre>",
        )

    def test_column_alignment_inside_a_line(self):
        lines = reflow.page_lines(pdftext_page(line("NAME     AGE", 100, 100), line("kubia    1m", 100, 109)))
        out = reflow.render_run(reflow.code_runs(lines)[0])
        self.assertIn("NAME     AGE\nkubia    1m", out)

    def test_a_large_gap_starts_a_new_listing(self):
        lines = reflow.page_lines(pdftext_page(line("a = 1", 100, 100), line("b = 2", 100, 200)))
        self.assertEqual(len(reflow.code_runs(lines)), 2)

    def test_prose_lines_are_not_code(self):
        lines = reflow.page_lines(pdftext_page(line("Some prose.", 100, 100, SERIF)))
        self.assertEqual(reflow.code_runs(lines), [])


def block(bid, btype, bbox, html=""):
    return {"id": bid, "block_type": btype, "bbox": bbox, "html": html, "children": []}


class PageTest(unittest.TestCase):
    def setUp(self):
        prose = line("To create the service, apply this manifest.", 100, 60, SERIF)
        note = line("This creates a load balancer.", 300, 100, SERIF)
        self.lines = reflow.page_lines(pdftext_page(prose, *yaml_lines(), note))
        self.page = {
            "id": "/page/7/Page/0",
            "block_type": "Page",
            "children": [
                block("/page/7/PageHeader/0", "PageHeader", [0, 0, 500, 20], "<p>Chapter 5</p>"),
                block("/page/7/Text/1", "Text", [99, 59, 400, 68], "<p>To create the service, apply this manifest.</p>"),
                # marker merged the listing and the margin note into one block.
                block("/page/7/Text/2", "Text", [99, 99, 450, 145], "<p>apiVersion: v1 metadata: name: kubia</p>"),
                block("/page/7/Text/3", "Text", [99, 160, 400, 168], "<p>Next paragraph.</p>"),
                # marker put the caption after the next paragraph. It sits right above the listing.
                block("/page/7/Caption/4", "Caption", [99, 85, 400, 95], "<p>Listing 5.12 A service</p>"),
                block("/page/7/SectionHeader/5", "SectionHeader", [99, 180, 400, 190], "<h2>5.4 Ingress</h2>"),
            ],
        }

    def test_order_code_caption_and_note(self):
        parts = reflow.page_parts(self.page, self.lines, reflow.Images())
        html = [p.html for p in parts]
        self.assertEqual(html[0], "<p>To create the service, apply this manifest.</p>")
        self.assertEqual(html[1], "<p>Listing 5.12 A service</p>")
        self.assertTrue(html[2].startswith("<pre><code>apiVersion: v1\nmetadata:\n  name: kubia"))
        self.assertEqual(html[3], '<p class="note">This creates a load balancer.</p>')
        self.assertEqual(html[4], "<p>Next paragraph.</p>")
        self.assertEqual((parts[5].level, parts[5].title), (2, "5.4 Ingress"))
        self.assertNotIn("Chapter 5", "".join(html))

    def test_image_block_becomes_an_img(self):
        jpeg = base64.b64encode(b"\xff\xd8data").decode()
        pic = block("/page/7/Diagram/9", "Diagram", [100, 300, 400, 400])
        pic["images"] = {pic["id"]: jpeg}
        page = {"id": "/page/7/Page/0", "block_type": "Page", "children": [pic]}
        images = reflow.Images()
        parts = reflow.page_parts(page, [], images)
        self.assertEqual(parts[0].html, '<img src="../images/img0001.jpg" alt=""/>')
        self.assertEqual(images.files, {"img0001.jpg": b"\xff\xd8data"})

    def test_paragraph_with_one_code_line_stays_prose(self):
        lines = reflow.page_lines(pdftext_page(
            line("Run the command below to list the pods", 100, 100, SERIF),
            line("of every namespace in the cluster, then", 100, 109, SERIF),
            line("kubectl get pods", 100, 118),
        ))
        page = {"id": "/page/1/Page/0", "block_type": "Page", "children": [
            block("/page/1/Text/0", "Text", [99, 99, 400, 126], "<p>Run the command ... kubectl get pods</p>"),
        ]}
        parts = reflow.page_parts(page, lines, reflow.Images())
        self.assertEqual([p.html for p in parts], ["<p>Run the command ... kubectl get pods</p>"])


class ChapterTest(unittest.TestCase):
    def test_without_bookmarks_split_at_level_one_headings(self):
        parts = [
            reflow.Part("<p>front</p>"),
            reflow.Part("<h1>Intro</h1>", 1, "Intro"),
            reflow.Part("<h2>Sub</h2>", 2, "Sub"),
            reflow.Part("<h1>Next</h1>", 1, "Next"),
            reflow.Part("<p>b</p>"),
        ]
        chapters, toc = reflow.build([(0, parts)], [], "Book")
        self.assertIsNone(toc)
        self.assertEqual([c.title for c in chapters], ["Book", "Intro", "Next"])
        self.assertIn("<h2>Sub</h2>", chapters[1].body)

    def test_split_depth_keeps_the_chapter_count_low(self):
        outline = [(0, "Part", 0)] * 17 + [(1, "Chapter", 0)] * 61 + [(2, "Section", 0)] * 118
        self.assertEqual(reflow.split_depth(outline), 1)
        self.assertEqual(reflow.split_depth([(0, "Ch", 0)] * 24 + [(1, "Sec", 0)] * 141), 0)

    def test_bookmarks_split_chapters_and_link_to_pages(self):
        pages = [(n, [reflow.Part(f"<p>page {n}</p>")]) for n in range(6)]
        outline = [(0, "Front", 0), (0, "1 Intro", 2), (1, "1.1 Why", 3), (0, "2 Pods", 4)]
        # Three top-level bookmarks fit the limit, four with the section do not: split at level 0.
        with mock.patch.object(reflow, "MAX_CHAPTERS", 3):
            chapters, toc = reflow.build(pages, outline, "Book")
        self.assertEqual([c.title for c in chapters], ["Front", "1 Intro", "2 Pods"])
        self.assertIn('<span id="p3"></span>', chapters[1].body)
        self.assertEqual(
            [(e.level, e.title, e.href) for e in toc],
            [
                (0, "Front", "text/ch0001.xhtml"),
                (0, "1 Intro", "text/ch0002.xhtml"),
                (1, "1.1 Why", "text/ch0002.xhtml#p3"),
                (0, "2 Pods", "text/ch0003.xhtml"),
            ],
        )


if __name__ == "__main__":
    unittest.main()

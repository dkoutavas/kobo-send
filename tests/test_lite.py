"""lite.lines_from_glyphs on synthetic glyphs. pypdfium2 is not needed."""

import unittest

from kobo_send import lite, reflow

MONO = {"name": "Courier", "flags": 1}
SERIF = {"name": "NewBaskerville-Roman", "flags": 0}


def glyphs(text, x, y, font=MONO, advance=4.8):
    return [{"char": ch, "bbox": [x + i * advance, y, x + (i + 1) * advance, y + 7.0], "font": font} for i, ch in enumerate(text)]


def newline():
    return {"char": "\r", "bbox": [0.0, 0.0, 0.0, 0.0], "font": {"name": "", "flags": 0}}


class LinesTest(unittest.TestCase):
    def test_line_breaks_split_lines_and_fonts_split_spans(self):
        page = lite.lines_from_glyphs(
            glyphs("Run ", 100.0, 100.0, SERIF) + glyphs("ls", 120.0, 100.0) + [newline()] + glyphs("next", 100.0, 110.0, SERIF)
        )
        lines = page["blocks"][0]["lines"]
        self.assertEqual([[s["text"] for s in l["spans"]] for l in lines], [["Run ", "ls"], ["next"]])
        self.assertEqual([round(v, 6) for v in lines[0]["bbox"]], [100.0, 100.0, 129.6, 107.0])

    def test_generated_space_does_not_stretch_the_line_box(self):
        space = {"char": " ", "bbox": [0.0, 0.0, 0.0, 0.0], "font": MONO}  # pdfium gives generated spaces no box
        line = lite.lines_from_glyphs(glyphs("a", 100.0, 100.0) + [space] + glyphs("b", 109.6, 100.0))["blocks"][0]["lines"][0]
        self.assertEqual([round(v, 6) for v in line["bbox"]], [100.0, 100.0, 114.4, 107.0])
        self.assertEqual(line["spans"][0]["text"], "a b")

    def test_a_glyph_on_a_lower_line_starts_a_new_line_without_a_break(self):
        # pdfium joins "kubia-" and "1295/..." with no line break (Kubernetes in Action, page 168).
        page = lite.lines_from_glyphs(glyphs("kubia-", 370.0, 477.0) + glyphs("1295/", 126.0, 487.0))
        self.assertEqual([l["spans"][0]["text"] for l in page["blocks"][0]["lines"]], ["kubia-", "1295/"])

    def test_listing_is_rebuilt_by_the_reflow_code(self):
        lines = [glyphs("metadata:", 100.0, 100.0), [newline()], glyphs("name: kubia", 109.6, 109.0)]
        page = lite.lines_from_glyphs([g for part in lines for g in part])
        runs = reflow.code_runs(reflow.page_lines(page))
        self.assertEqual(reflow.render_run(runs[0]), "<pre><code>metadata:\n  name: kubia</code></pre>")


if __name__ == "__main__":
    unittest.main()

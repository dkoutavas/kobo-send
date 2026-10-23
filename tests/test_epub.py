import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from kobo_send import epub


class CleanerTest(unittest.TestCase):
    def test_keeps_safe_tags_and_closes_them(self):
        out = epub.to_xhtml('<p block-type="Text">a<br>b &amp; <weird>c</weird><b>d</p>')
        self.assertEqual(out, "<p>a<br/>b &amp; c<b>d</b></p>")

    def test_drops_links_and_keeps_their_text(self):
        out = epub.to_xhtml('<p><a href="#page-3">x</a> <a href="https://k8s.io">y</a></p>')
        self.assertEqual(out, "<p>x y</p>")

    def test_keeps_toc_anchor_ids_only(self):
        self.assertEqual(epub.to_xhtml('<span id="t17"></span><p id="x">a</p>'), '<span id="t17"></span><p>a</p>')

    def test_drops_characters_xml_forbids(self):
        self.assertEqual(epub.to_xhtml("<p>a\x0cb\x00</p>"), "<p>ab</p>")

    def test_keeps_whitespace_in_pre(self):
        self.assertEqual(epub.to_xhtml("<pre>  a\n    b &lt;x&gt;</pre>"), "<pre>  a\n    b &lt;x&gt;</pre>")


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "book.epub"
        epub.write(
            self.path,
            title="T & T",
            author="A",
            chapters=[epub.Chapter("One", "<h1>One</h1><p>x"), epub.Chapter("Two", "<pre>  y</pre>")],
            images={"img0001.jpg": b"\xff\xd8jpeg"},
            cover=b"\xff\xd8cover",
        )

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_mimetype_is_first_and_stored(self):
        with zipfile.ZipFile(self.path) as z:
            first = z.infolist()[0]
            self.assertEqual(first.filename, "mimetype")
            self.assertEqual(first.compress_type, zipfile.ZIP_STORED)
            self.assertEqual(z.read("mimetype"), b"application/epub+zip")

    def test_every_xml_file_is_well_formed(self):
        with zipfile.ZipFile(self.path) as z:
            names = [n for n in z.namelist() if n.endswith((".xhtml", ".opf", ".ncx", ".xml"))]
            self.assertEqual(len(names), 6)
            for name in names:
                ET.fromstring(z.read(name))

    def test_manifest_and_toc_list_everything(self):
        with zipfile.ZipFile(self.path) as z:
            opf = z.read("OEBPS/content.opf").decode()
            nav = z.read("OEBPS/nav.xhtml").decode()
            self.assertEqual(z.read("OEBPS/images/img0001.jpg"), b"\xff\xd8jpeg")
        for href in ("text/ch0001.xhtml", "text/ch0002.xhtml", "images/img0001.jpg", "images/cover.jpg"):
            self.assertIn(f'href="{href}"', opf)
        self.assertIn('properties="cover-image"', opf)
        self.assertIn("<dc:title>T &amp; T</dc:title>", opf)
        self.assertIn('<a href="text/ch0002.xhtml">Two</a>', nav)


class NestedTocTest(unittest.TestCase):
    def test_nav_and_ncx_nest_by_level(self):
        d = Path(tempfile.mkdtemp())
        try:
            toc = [
                epub.TocEntry(0, "Part 1", "text/ch0001.xhtml"),
                epub.TocEntry(1, "1 Intro", "text/ch0001.xhtml#p3"),
                epub.TocEntry(3, "deep", "text/ch0001.xhtml#p4"),  # a jump of two levels nests one step
                epub.TocEntry(0, "Part 2", "text/ch0002.xhtml"),
            ]
            path = d / "b.epub"
            chapters = [epub.Chapter("a", "<p>a</p>"), epub.Chapter("b", "<p>b</p>")]
            epub.write(path, title="B", author="", chapters=chapters, images={}, toc=toc)
            with zipfile.ZipFile(path) as z:
                nav = ET.fromstring(z.read("OEBPS/nav.xhtml"))
                ncx = ET.fromstring(z.read("OEBPS/toc.ncx"))
        finally:
            shutil.rmtree(d)
        ns = {"h": "http://www.w3.org/1999/xhtml", "n": "http://www.daisy.org/z3986/2005/ncx/"}
        top = nav.findall(".//h:nav/h:ol/h:li", ns)
        self.assertEqual([li.find("h:a", ns).text for li in top], ["Part 1", "Part 2"])
        self.assertEqual(top[0].find("h:ol/h:li/h:a", ns).text, "1 Intro")
        self.assertEqual(top[0].find("h:ol/h:li/h:ol/h:li/h:a", ns).text, "deep")
        points = ncx.findall("n:navMap/n:navPoint", ns)
        self.assertEqual([p.find("n:navLabel/n:text", ns).text for p in points], ["Part 1", "Part 2"])
        self.assertEqual(points[0].find("n:navPoint/n:navPoint/n:content", ns).get("src"), "text/ch0001.xhtml#p4")


if __name__ == "__main__":
    unittest.main()

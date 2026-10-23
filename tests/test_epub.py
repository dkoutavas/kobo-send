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

    def test_keeps_web_links_only(self):
        out = epub.to_xhtml('<a href="#page-3">x</a> <a href="https://k8s.io">y</a>')
        self.assertEqual(out, '<a>x</a> <a href="https://k8s.io">y</a>')

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


if __name__ == "__main__":
    unittest.main()

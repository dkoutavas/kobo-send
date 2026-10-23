import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from kobo_send import books


class PlanTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(books.plan("a.epub").target, "a.kepub.epub")
        self.assertEqual(books.plan("a.kepub.epub").target, "a.kepub.epub")
        self.assertEqual(books.plan("a.pdf").target, "a.pdf")
        self.assertEqual(books.plan("A.PDF").target, "A.pdf")

    def test_unsupported(self):
        self.assertIsNone(books.plan("a.mobi"))
        self.assertIsNone(books.plan("notes.txt"))

    def test_other_format_is_replaced(self):
        self.assertEqual(books.plan("a.pdf").other, "a.kepub.epub")
        self.assertEqual(books.plan("a.epub").other, "a.pdf")

    def test_clean_name(self):
        raw = (
            "example.pub_the-practice-of-system-and-network-administration-volume-1-3rd-edition"
            "-9780321919168-0321919165-9780321943187-9780133415087-0133415082"
        )
        self.assertEqual(
            books.clean_name(raw),
            "the-practice-of-system-and-network-administration-volume-1-3rd-edition",
        )
        self.assertEqual(books.clean_name("Kubernetes in Action"), "Kubernetes in Action")
        self.assertEqual(books.clean_name("some-book-12345"), "some-book-12345")


class FileCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        for f in self.dir.iterdir():
            f.unlink()
        self.dir.rmdir()

    def test_opens_zip(self):
        good = self.dir / "good.kepub.epub"
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("mimetype", "application/epub+zip")
        bad = self.dir / "bad.kepub.epub"
        bad.write_bytes(b"not a zip")
        self.assertTrue(books.opens(good))
        self.assertFalse(books.opens(bad))

    def test_opens_pdf(self):
        good = self.dir / "good.pdf"
        good.write_bytes(b"%PDF-1.7\n")
        bad = self.dir / "bad.pdf"
        bad.write_bytes(b"junk")
        self.assertTrue(books.opens(good))
        self.assertFalse(books.opens(bad))

    def test_convert_copies_kepub(self):
        src = self.dir / "a.kepub.epub"
        src.write_bytes(b"data")
        out = self.dir / "out.kepub.epub"
        books.convert(src, out, "koc")
        self.assertEqual(out.read_bytes(), b"data")

    def test_convert_reports_missing_tool(self):
        src = self.dir / "a.epub"
        src.write_bytes(b"data")
        with mock.patch.dict(os.environ, {"PATH": str(self.dir)}):
            with self.assertRaisesRegex(books.ConversionError, "kepubify is not installed"):
                books.convert(src, self.dir / "out.kepub.epub", "koc")


if __name__ == "__main__":
    unittest.main()

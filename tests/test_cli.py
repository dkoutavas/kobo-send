"""The send step against a plain directory that stands in for the Kobo."""

import io
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from kobo_send import books, cli


class SendTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.dest = self.root / "Technical"  # stands in for Books/Technical on the Kobo
        self.work = self.root / "work"
        self.dest.mkdir()
        (self.work / "in").mkdir(parents=True)
        (self.work / "out").mkdir()
        self.book = self.root / "a.kepub.epub"
        with zipfile.ZipFile(self.book, "w") as z:
            z.writestr("mimetype", "application/epub+zip")

    def tearDown(self):
        shutil.rmtree(self.root)

    def send(self, job):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            ok = cli._send(job, self.dest, self.work, "fit")
        return ok, out.getvalue()

    def test_local_book_lands_and_replaces_the_pdf(self):
        (self.dest / "a.pdf").write_bytes(b"%PDF-old")
        ok, out = self.send(cli.Job(books.plan(self.book.name), self.book))
        self.assertTrue(ok, out)
        self.assertEqual((self.dest / "a.kepub.epub").read_bytes(), self.book.read_bytes())
        self.assertFalse((self.dest / "a.pdf").exists())
        self.assertIn("OK   a.kepub.epub", out)

    def test_inbox_book_is_archived_after_success(self):
        fetch = lambda inbox, name, dest: shutil.copyfile(self.book, dest)  # noqa: E731
        with mock.patch.object(cli.inbox, "fetch", side_effect=fetch), mock.patch.object(
            cli.inbox, "archive"
        ) as archive:
            ok, out = self.send(cli.Job(books.plan("a.kepub.epub"), None))
        self.assertTrue(ok, out)
        archive.assert_called_once_with("gdrive:Books", "a.kepub.epub", "Sent")

    def test_failed_conversion_keeps_the_inbox_file(self):
        bad = self.root / "b.epub"
        bad.write_bytes(b"not an epub")
        with mock.patch.object(
            cli.books, "convert", side_effect=books.ConversionError("kepubify failed")
        ), mock.patch.object(cli.inbox, "fetch"), mock.patch.object(cli.inbox, "archive") as archive:
            ok, out = self.send(cli.Job(books.plan(bad.name), None))
        self.assertFalse(ok)
        self.assertIn("FAIL b.epub: kepubify failed", out)
        archive.assert_not_called()
        self.assertEqual(list(self.dest.iterdir()), [])


class GatherTest(unittest.TestCase):
    def test_inbox_ignores_other_files(self):
        with mock.patch.object(cli.inbox, "list_files", return_value=["a.pdf", "notes.txt", "b.epub"]):
            jobs, ok = cli._gather([], "fit")
        self.assertTrue(ok)
        self.assertEqual([j.plan.source_name for j in jobs], ["a.pdf", "b.epub"])

    def test_missing_command_line_file_is_skipped_and_reported(self):
        err = io.StringIO()
        with redirect_stderr(err):
            jobs, ok = cli._gather([Path("/nope/a.pdf")], "fit")
        self.assertEqual(jobs, [])
        self.assertFalse(ok)
        self.assertIn("SKIP /nope/a.pdf: not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()

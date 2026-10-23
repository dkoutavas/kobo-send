import tempfile
import unittest
from pathlib import Path

from kobo_send import config


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.file = Path(tempfile.mkdtemp()) / "config.toml"

    def tearDown(self):
        self.file.unlink(missing_ok=True)
        self.file.parent.rmdir()

    def test_missing_file_gives_defaults(self):
        self.assertEqual(config.load(self.file), config.Config())

    def test_keys_override_defaults(self):
        self.file.write_text('inbox = "gdrive:Ebooks"\nsubdir = "Fiction"\n')
        cfg = config.load(self.file)
        self.assertEqual(cfg.inbox, "gdrive:Ebooks")
        self.assertEqual(cfg.subdir, "Fiction")
        self.assertEqual(cfg.sent, "Sent")

    def test_unknown_key_is_an_error(self):
        self.file.write_text('inbx = "gdrive:Books"\n')
        with self.assertRaisesRegex(ValueError, "unknown keys: inbx"):
            config.load(self.file)

    def test_pdf_mode_must_be_known(self):
        self.file.write_text('pdf_mode = "ocr"\n')
        with self.assertRaisesRegex(ValueError, "pdf_mode must be one of: fit, reflow"):
            config.load(self.file)

    def test_value_must_be_a_string(self):
        self.file.write_text("subdir = 3\n")
        with self.assertRaisesRegex(ValueError, "must be strings: subdir"):
            config.load(self.file)


if __name__ == "__main__":
    unittest.main()

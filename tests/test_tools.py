"""The rclone and lsblk call shapes, with subprocess replaced by a fake."""

import subprocess
import unittest
from unittest import mock

from kobo_send import device, inbox


def done(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


class InboxTest(unittest.TestCase):
    @mock.patch("subprocess.run")
    def test_list_files_is_sorted(self, run):
        run.return_value = done('[{"Name": "b.pdf"}, {"Name": "a.epub"}]')
        self.assertEqual(inbox.list_files("gdrive:Books"), ["a.epub", "b.pdf"])
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["rclone", "lsjson", "--files-only", "gdrive:Books"])

    @mock.patch("subprocess.run")
    def test_archive_moves_into_sent(self, run):
        run.return_value = done()
        inbox.archive("gdrive:Books/", "a b.pdf", "Sent")
        self.assertEqual(
            run.call_args.args[0],
            ["rclone", "moveto", "gdrive:Books/a b.pdf", "gdrive:Books/Sent/a b.pdf"],
        )

    @mock.patch("subprocess.run")
    def test_rclone_failure_is_reported(self, run):
        run.return_value = done(returncode=1, stderr="directory not found")
        with self.assertRaisesRegex(inbox.InboxError, "directory not found"):
            inbox.list_files("gdrive:Nope")


class DeviceTest(unittest.TestCase):
    @mock.patch("subprocess.run")
    def test_mounted_device_is_not_mounted_again(self, run):
        run.return_value = done('{"blockdevices": [{"mountpoints": ["/run/media/u/KOBOeReader"]}]}')
        self.assertEqual(str(device.mount("/dev/sdb")), "/run/media/u/KOBOeReader")
        self.assertEqual(run.call_count, 1)

    @mock.patch("subprocess.run")
    def test_unmount_does_not_power_off(self, run):
        # A power-off stops the Kobo from importing the new books.
        run.return_value = done()
        device.unmount("/dev/sdb")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][:4], ["udisksctl", "unmount", "--block-device", "/dev/sdb"])


if __name__ == "__main__":
    unittest.main()

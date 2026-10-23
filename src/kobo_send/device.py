"""Find, mount and unmount the Kobo with udisks2.

udisks2 lets the user of the active local desktop session mount removable drives
without root. Over SSH the session is not active, so mount and unmount fail with
"Not authorized".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class DeviceError(Exception):
    pass


def find(label: str) -> str | None:
    """Return the block device of the filesystem with this label, or None."""
    link = Path("/dev/disk/by-label") / label
    return str(link.resolve()) if link.exists() else None


def mount(block: str) -> Path:
    """Return the mount point of block. Mount it first if the desktop has not."""
    point = _mountpoint(block)
    if point is None:
        _udisksctl("mount", "--block-device", block)
        point = _mountpoint(block)
    if point is None:
        raise DeviceError(f"{block} did not mount")
    return point


def unmount(block: str) -> None:
    """Unmount the filesystem, so that it is safe to unplug.

    Do not power off the drive. The Kobo rejects the SCSI eject command, so
    udisksctl power-off removes the device through sysfs instead. After that,
    the Kobo skips its "Importing content" scan and the new books do not show.
    The scan runs when the user unplugs the cable.
    """
    _udisksctl("unmount", "--block-device", block)


def _mountpoint(block: str) -> Path | None:
    out = _lsblk("--json", "--output", "MOUNTPOINTS", block)
    points = [p for p in json.loads(out)["blockdevices"][0]["mountpoints"] if p]
    return Path(points[0]) if points else None


def _lsblk(*args: str) -> str:
    return subprocess.run(
        ["lsblk", "--nodeps", *args], capture_output=True, text=True, check=True
    ).stdout


def _udisksctl(*args: str) -> None:
    result = subprocess.run(
        ["udisksctl", *args, "--no-user-interaction"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise DeviceError(f"udisksctl {args[0]} failed: {result.stderr.strip()}")

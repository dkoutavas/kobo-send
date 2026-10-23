"""Find, mount and eject the Kobo with udisks2.

udisks2 lets the user of the active local desktop session mount removable drives
without root. Over SSH the session is not active, so mount and eject fail with
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


def eject(block: str) -> None:
    """Unmount the filesystem and power off the drive, so that it is safe to unplug."""
    disk = _parent(block)
    _udisksctl("unmount", "--block-device", block)
    _udisksctl("power-off", "--block-device", disk)


def _mountpoint(block: str) -> Path | None:
    out = _lsblk("--json", "--output", "MOUNTPOINTS", block)
    points = [p for p in json.loads(out)["blockdevices"][0]["mountpoints"] if p]
    return Path(points[0]) if points else None


def _parent(block: str) -> str:
    """Return the whole disk that holds block. A filesystem without partitions is its own disk."""
    pkname = _lsblk("--noheadings", "--output", "PKNAME", block).strip()
    return f"/dev/{pkname}" if pkname else block


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

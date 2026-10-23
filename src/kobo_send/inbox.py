"""The inbox: a folder on an rclone remote, for example gdrive:Books."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class InboxError(Exception):
    pass


def list_files(inbox: str) -> list[str]:
    """Return the names of the files directly in the inbox, sorted. Subfolders are not read."""
    return sorted(e["Name"] for e in json.loads(_rclone("lsjson", "--files-only", inbox)))


def fetch(inbox: str, name: str, dest: Path) -> None:
    _rclone("copyto", _join(inbox, name), str(dest))


def archive(inbox: str, name: str, sent: str) -> None:
    """Move a sent file into the sent subfolder, so that the next run skips it."""
    _rclone("moveto", _join(inbox, name), _join(inbox, f"{sent}/{name}"))


def _join(inbox: str, name: str) -> str:
    return f"{inbox.rstrip('/')}/{name}"


def _rclone(*args: str) -> str:
    try:
        result = subprocess.run(["rclone", *args], capture_output=True, text=True)
    except FileNotFoundError:
        raise InboxError("rclone is not installed") from None
    if result.returncode != 0:
        raise InboxError(f"rclone {args[0]} failed: {result.stderr.strip()}")
    return result.stdout

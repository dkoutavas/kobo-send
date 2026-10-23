"""The inbox: a local folder, or a folder on an rclone remote such as gdrive:Books."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

# rclone's own rule: "name:path" is a remote, everything else is a local path.
_REMOTE = re.compile(r"^[\w.+@ -]+:")


class InboxError(Exception):
    pass


def list_files(inbox: str) -> list[str]:
    """Return the names of the files directly in the inbox, sorted. Subfolders are not read."""
    if _REMOTE.match(inbox):
        return sorted(e["Name"] for e in json.loads(_rclone("lsjson", "--files-only", inbox)))
    try:
        return sorted(p.name for p in _folder(inbox).iterdir() if p.is_file())
    except OSError as e:
        raise InboxError(f"cannot read the inbox folder: {e}") from None


def fetch(inbox: str, name: str, dest: Path) -> None:
    if _REMOTE.match(inbox):
        _rclone("copyto", _join(inbox, name), str(dest))
    else:
        shutil.copyfile(_folder(inbox) / name, dest)


def archive(inbox: str, name: str, sent: str) -> None:
    """Move a sent file into the sent subfolder, so that the next run skips it."""
    if _REMOTE.match(inbox):
        _rclone("moveto", _join(inbox, name), _join(inbox, f"{sent}/{name}"))
        return
    folder = _folder(inbox)
    (folder / sent).mkdir(exist_ok=True)
    (folder / name).rename(folder / sent / name)


def _folder(inbox: str) -> Path:
    return Path(inbox).expanduser()


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
